# AQL Phase 3 — Correction Detection and Retroactive Patching Requirements

**Feature:** Adaptive Query Learning (AQL) — Phase 3  
**Application:** MCP Client Web  
**Date:** April 4, 2026  
**Status:** Requirements Ready  
**Parent Requirements:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`  
**Parent HLD:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`  
**Parent Implementation Spec:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-IMPLEMENTATION-SPEC.md`

---

## 1. Purpose

This document defines the detailed requirements for **Phase 3** of Adaptive Query Learning (AQL): detecting corrective follow-up messages and retroactively patching the previous turn’s quality record.

Phase 3 builds on Phase 2’s passive quality recording. It does not yet change routing behavior, but it improves the quality-history label set by marking prior turns that the user effectively rejected.

---

## 2. Scope

### In Scope

- Detect whether a new user message is a correction of the immediately previous assistant response.
- Use configured regex patterns only to determine whether a follow-up is corrective.
- Patch the previous turn’s `tool_execution_quality` record by setting `user_corrected = true`.
- Schedule correction patching asynchronously so it does not block the request path.
- Reuse the Phase 2 quality-record collection and existing Milvus plumbing.
- Add focused unit coverage for regex matching and retroactive patch behavior.

### Out of Scope

- Adding any new LLM call for correction classification.
- Modifying current route selection, tool selection, or tool execution behavior.
- Computing quality scores from corrected records.
- Admin reporting over corrected records.
- Real follow-up-gap patching beyond the `user_corrected` flag.
- Affinity routing, freshness-candidate reporting, or chunk reordering.

---

## 3. Functional Requirements

### FR-AQL-P3-01 — Detect corrective follow-up messages
At the start of each new user message, the system shall evaluate whether the message appears to correct the immediately previous assistant response.

### FR-AQL-P3-02 — Regex-only detection
Correction detection shall use the configured regex patterns in `aql_correction_patterns` only. Phase 3 shall not call an LLM for correction detection.

### FR-AQL-P3-03 — Config-driven pattern set
The correction-pattern set shall be sourced from the existing AQL config surface and must support operator override without requiring code changes.

### FR-AQL-P3-04 — Immediate-previous-turn scope only
Phase 3 shall consider only the immediately previous assistant turn / quality record for patching. It shall not search older turns for a match.

### FR-AQL-P3-05 — Retroactive patching
When a corrective follow-up is detected and the prior turn’s quality record is known, the system shall patch that prior record by setting `user_corrected = true`.

### FR-AQL-P3-06 — Preserve all other fields
Correction patching shall preserve all other quality-record fields. The patch must only change the correction label and any minimally required metadata for the upsert.

### FR-AQL-P3-07 — No-op when previous record is unavailable
If the previous turn’s quality record cannot be identified or retrieved, Phase 3 shall no-op with warning/debug logging and continue normal chat processing.

### FR-AQL-P3-08 — Async patch scheduling
Correction patching shall be scheduled asynchronously from the start of `send_message()` and shall not block route selection or the outgoing response.

### FR-AQL-P3-09 — Failure isolation
If correction detection or patching fails because of regex issues, Milvus unavailability, missing metadata, or any other exception, the failure shall be logged at WARNING level and suppressed.

### FR-AQL-P3-10 — No routing behavior change
Phase 3 shall not yet use corrected-history data to change routing decisions. It only improves the stored label for later phases.

---

## 4. Non-Functional Requirements

### NFR-AQL-P3-01 — Additive only
Phase 3 changes shall be additive to the current chat and Phase 2 recording flow.

### NFR-AQL-P3-02 — No visible latency regression
Correction detection and patch scheduling shall not add visible latency to the user-facing request path.

### NFR-AQL-P3-03 — Graceful degradation
If Milvus is unavailable, previous-turn metadata is missing, or regex matching fails unexpectedly, the system shall degrade silently with warning logs only.

### NFR-AQL-P3-04 — No new infrastructure
Phase 3 shall reuse the existing memory service, session manager, and Milvus infrastructure introduced in earlier phases.

### NFR-AQL-P3-05 — Testable without live Milvus
Phase 3 logic shall be unit-testable with fake session metadata, fake Milvus search/upsert behavior, and fake configuration.

---

## 5. Constraints and Assumptions

- Phase 2 quality records already exist in `tool_execution_quality`.
- The previous turn’s quality record must be locatable via in-memory metadata and/or query hash derived from the stored turn context.
- Phase 3 sets `user_corrected = true` only; later phases will consume that signal.
- Phase 3 does not need to patch `follow_up_gap_s` unless that metadata is already trivially available.

---

## 6. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-AQL-P3-01 | Corrective follow-up messages are detected using configured regex patterns only |
| AC-AQL-P3-02 | When a prior quality record is found, `user_corrected` is patched to `true` |
| AC-AQL-P3-03 | Missing prior-record metadata does not break chat flow |
| AC-AQL-P3-04 | Patching is scheduled asynchronously and does not block request handling |
| AC-AQL-P3-05 | No new LLM call is added for correction detection |
| AC-AQL-P3-06 | Existing routing and response behavior remain unchanged |
| AC-AQL-P3-07 | Focused Phase 3 tests and regression remain green |

---

## 7. Validation

```bash
source venv/bin/activate
pytest tests/backend/unit/test_memory_service.py tests/backend/unit/test_main_runtime.py -q
pytest tests/backend/integration/test_chat_api.py -q
python -m pytest -q
```

Validation expectations:
- regex-based detection works for configured phrases,
- prior quality records are patched when available,
- missing-record cases no-op safely,
- and the full chat regression suite remains green.
