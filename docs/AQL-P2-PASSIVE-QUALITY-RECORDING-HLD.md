# AQL Phase 2 — Passive Quality Recording HLD

**Feature:** Adaptive Query Learning (AQL) — Phase 2  
**Application:** MCP Client Web  
**Date:** April 3, 2026  
**Status:** Design Backfilled  
**Parent Docs:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`, `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`

---

## 1. Executive Summary

Phase 2 activates the first operational part of Adaptive Query Learning: writing passive execution-quality history for completed chat turns.

This phase is intentionally **observe-only**. It does not use quality history for routing or reporting. Instead, it records the data needed by later phases while preserving all existing chat, tool-execution, direct-route, memory-route, and split-phase behavior.

In the current implementation, Phase 2 is realized in two places:
1. `backend/main.py` collects quality signals from the existing request flow and schedules recording with a background task.
2. `backend/memory_service.py` embeds the query and upserts the assembled quality record into `tool_execution_quality`.

---

## 2. Design Goals

1. Persist useful learning signals without changing response behavior.
2. Avoid blocking the user-visible response path.
3. Reuse current execution state instead of duplicating routing logic.
4. Reuse existing Milvus plumbing from Phase 1.
5. Keep failure handling fail-open and warning-only.

---

## 3. Architecture Placement

### 3.1 Runtime Placement

Phase 2 sits at the end of the normal chat pipeline:

```text
User message
  → routing / tool selection / tool execution / synthesis
  → final assistant response assembled
  → conversation memory recorded (existing)
  → quality-record task scheduled (new)
  → ChatResponse returned
```

The background task is scheduled from the final response path so response construction is not blocked. The actual persistence work runs in `MemoryService.record_execution_quality()`.

### 3.2 Non-goals in this phase

Phase 2 does not:
- inspect future user messages,
- patch records for correction signals,
- search quality history,
- alter allowed tools,
- reorder split-phase chunks,
- or expose any new admin endpoint.

---

## 4. Data Flow Design

### 4.1 Signal Collection in `send_message()`

`backend/main.py` already has all of the signals needed for a passive quality record. Phase 2 adds local accumulators that harvest those signals without changing the flow:

```text
send_message()
├── request_mode_details["domains"]          → domain_tags
├── issue_classification / request_mode       → issue_type
├── tool_executions                           → selected / succeeded / failed / cache_hit
├── tool-cache freshness bypass               → tools_bypassed
├── split-phase chunk callbacks               → chunk_yields
├── LLM call sites                            → llm_turn_count
└── final response usage                      → synthesis_tokens
```

### 4.2 Background Scheduling

A helper function in `backend/main.py` performs scheduling:

```text
_schedule_execution_quality_record(memory_service, payload)
  → validate method + config
  → asyncio.create_task(record_execution_quality(**payload))
  → attach done-callback for defensive warning logging
```

This helper makes Phase 2 reusable across both final-success and fallback-success response paths.

### 4.3 Persistence Flow

The scheduled task calls:

```text
MemoryService.record_execution_quality()
  1. Normalize query text
  2. Build query hash
  3. Embed query via existing EmbeddingService
  4. Compute TTL / expires_at
  5. Serialize list fields to JSON strings
  6. Upsert record into tool_execution_quality
  7. Optionally log row-count summary
```

---

## 5. Component Delta

| Component | Change | Description |
|---|---|---|
| `backend/main.py` | Extended | Collects quality signals and schedules fire-and-forget recording |
| `backend/memory_service.py` | Extended | Adds `record_execution_quality()` and normalization helpers |
| `tests/backend/unit/test_main_runtime.py` | Extended | Covers runtime scheduling helper |
| `tests/backend/unit/test_memory_service.py` | Extended | Covers quality-record persistence and failure isolation |

Phase 2 does **not** require a Milvus schema change because Phase 1 already introduced `tool_execution_quality`.

---

## 6. Record Shape Design

Phase 2 writes one record per completed turn with these effective groups:

### 6.1 Identity and lifecycle
- `id`
- `query_hash`
- `session_id`
- `timestamp`
- `expires_at`

### 6.2 Query context
- query embedding
- `domain_tags`
- `issue_type`

### 6.3 Tool outcome metadata
- `tools_selected`
- `tools_succeeded`
- `tools_failed`
- `tools_bypassed`
- `tools_cache_hit`

### 6.4 Runtime-cost metadata
- `chunk_yields`
- `llm_turn_count`
- `synthesis_tokens`
- `routing_mode`

### 6.5 Deferred-learning fields
- `user_corrected = false`
- `follow_up_gap_s = -1`

These deferred fields are placeholders for later phases and are intentionally populated with safe defaults in Phase 2.

---

## 7. Signal Semantics

### 7.1 `tools_selected`
Derived from the already executed tool list, not from the original offered catalog.

### 7.2 `tools_succeeded` / `tools_failed`
Derived from the existing `success` flag in `tool_executions`.

### 7.3 `tools_cache_hit`
Derived from tool executions that returned cached results via the existing tool-cache path.

### 7.4 `tools_bypassed`
Derived only from cache-policy decisions where a cacheable lookup was skipped because the tool was freshness-sensitive.

### 7.5 `chunk_yields`
Recorded only when split-phase selection runs. Each row summarizes how many tools were offered to a chunk and how many new tool calls were selected from that chunk.

### 7.6 `routing_mode`
In the current implementation, Phase 2 persists:
- `direct` for direct-route-selected turns,
- `memory` for memory-retrieval routes,
- `llm_fallback` otherwise.

`affinity` is not used yet because later routing phases are not implemented.

---

## 8. Failure and Degradation Strategy

Phase 2 follows the existing memory-subsystem philosophy:

- If AQL is disabled, no quality task is scheduled.
- If the memory service lacks `record_execution_quality()`, scheduling is skipped.
- If embedding generation fails, the failure is logged and suppressed.
- If Milvus upsert fails, the failure is logged and suppressed.
- If the background task raises unexpectedly, the scheduling helper logs a warning.

No failure in this path is allowed to alter the assistant response.

---

## 9. Compatibility Strategy

### 9.1 Response-path compatibility
Phase 2 adds only a background task schedule to the final response path. It does not mutate the returned `ChatResponse`.

### 9.2 Routing compatibility
Phase 2 reads routing outcomes but does not change them.

### 9.3 Tool-cache compatibility
Phase 2 observes cache hits and freshness bypasses but does not change cache admission rules.

### 9.4 Split-phase compatibility
Phase 2 records chunk yield summaries using callbacks but does not change chunk ordering, early-stop behavior, deduping, or MCP execution timing.

---

## 10. Validation

Phase 2 is successful when:
- completed turns schedule passive quality recording when enabled,
- quality records persist the expected shape,
- failures are swallowed safely,
- and the broader chat/memory regression suite remains green.
