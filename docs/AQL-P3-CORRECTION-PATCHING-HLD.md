# AQL Phase 3 — Correction Detection and Retroactive Patching HLD

**Feature:** Adaptive Query Learning (AQL) — Phase 3  
**Application:** MCP Client Web  
**Date:** April 4, 2026  
**Status:** Design Ready  
**Parent Docs:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`, `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`

---

## 1. Executive Summary

Phase 3 adds a lightweight feedback-labeling mechanism to Adaptive Query Learning: when the next user message looks like a correction, the system marks the previous turn’s quality record as corrected.

This phase improves the quality of the stored execution history without changing routing, tool selection, or chat responses. It builds directly on the Phase 2 quality records already written to `tool_execution_quality`.

---

## 2. Design Goals

1. Label poor prior turns with a cheap, reliable heuristic.
2. Avoid any additional LLM call in the correction path.
3. Keep patching asynchronous and fail-open.
4. Limit scope to the immediately previous turn to avoid ambiguous historical patching.
5. Prepare later phases to exclude corrected records from affinity routing.

---

## 3. Architecture Placement

### 3.1 Runtime Placement

Phase 3 hooks in at the start of `send_message()` before routing decisions are made:

```text
New user message arrives
  → inspect immediately previous turn metadata
  → regex-match correction patterns against current message
  → if corrective, schedule background patch for previous quality record
  → continue normal routing / tool execution flow unchanged
```

### 3.2 Persistence Placement

The patch target is the existing `tool_execution_quality` collection introduced in Phase 1 and populated in Phase 2.

No new collection is introduced.

---

## 4. Data Flow Design

### 4.1 Inputs

Phase 3 depends on three inputs:
- current user message text,
- configured correction regex patterns,
- metadata identifying the previous turn’s quality record (directly or via query hash).

### 4.2 Detection Flow

```text
send_message()
  1. Read current message text
  2. Retrieve previous-turn metadata from in-memory session state
  3. Evaluate text against compiled correction regexes
  4. If matched and previous record metadata exists:
       schedule patch_correction_signal(...)
  5. Continue request processing unchanged
```

### 4.3 Patch Flow

```text
MemoryService.patch_correction_signal()
  1. Search tool_execution_quality for prior record by session + query_hash
  2. If found, reconstruct/upsert record with user_corrected=True
  3. Log patched record id / query hash
  4. Swallow failures with warning logs
```

---

## 5. Component Delta

| Component | Change | Description |
|---|---|---|
| `backend/memory_service.py` | Extended | Adds correction-pattern matching and quality-record patch method |
| `backend/main.py` | Extended | Wires pre-routing correction detection and async patch scheduling |
| `backend/session_manager.py` | Optional extension | Exposes prior-turn metadata if current state is insufficient |
| `tests/backend/unit/test_memory_service.py` | Extended | Covers regex matching and patch logic |
| `tests/backend/unit/test_main_runtime.py` | Extended | Covers detection trigger and scheduling behavior |

---

## 6. Detection Strategy

### 6.1 Pattern Source

Patterns come from `aql_correction_patterns` in runtime config. They are operator-configurable and already normalized in earlier phases.

### 6.2 Matching Strategy

- Use regex matching only.
- Evaluate the raw current user message text.
- Treat a match as a heuristic signal, not a perfect truth label.
- Limit scope to the immediately prior turn.

### 6.3 Examples of corrective signals

Examples include messages containing patterns like:
- `wrong`
- `incorrect`
- `actually`
- `not right`
- `that's not`
- `no,`

---

## 7. Patch Semantics

### 7.1 Patch target

The target is the Phase 2 quality record for the immediately prior turn.

### 7.2 Patch contents

The patch should preserve the existing record contents and change only:
- `user_corrected` → `true`

If the Milvus wrapper requires a full-record upsert, the implementation may re-upsert the entire record with that one field changed.

### 7.3 Missing-record behavior

If the target record cannot be found, the system logs and exits without affecting the request path.

---

## 8. Failure and Compatibility Strategy

- If no prior-turn metadata exists, skip patching.
- If no correction regex matches, skip patching.
- If Milvus search or upsert fails, log a warning and continue.
- If session metadata access is unavailable, add a minimal internal helper rather than changing public APIs.
- Do not change tool routing, tool execution, or final response content in this phase.

---

## 9. Validation

Phase 3 is successful when:
- correction-like follow-ups are detected by regex,
- matching prior quality records are patched to `user_corrected=true`,
- missing-record cases no-op safely,
- and the chat runtime behaves identically aside from the stored correction label.
