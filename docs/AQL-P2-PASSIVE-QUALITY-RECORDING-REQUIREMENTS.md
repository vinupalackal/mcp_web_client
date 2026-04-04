# AQL Phase 2 — Passive Quality Recording Requirements

**Feature:** Adaptive Query Learning (AQL) — Phase 2  
**Application:** MCP Client Web  
**Date:** April 3, 2026  
**Status:** Requirements Backfilled  
**Parent Requirements:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`  
**Parent HLD:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`  
**Parent Implementation Spec:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-IMPLEMENTATION-SPEC.md`

---

## 1. Purpose

This document defines the detailed requirements for **Phase 2** of Adaptive Query Learning (AQL): passively recording execution-quality history for completed chat turns.

Phase 2 is the first behavior-bearing AQL phase, but it remains **non-routing**. It records quality signals for future learning without changing direct-route behavior, memory-route behavior, split-phase selection decisions, or user-visible chat responses.

---

## 2. Scope

### In Scope

- Add passive quality-record persistence to `tool_execution_quality` for completed chat turns.
- Capture execution-quality signals already produced by the existing chat/tool flow.
- Schedule quality recording asynchronously from the final response path so response construction is not blocked.
- Persist a query embedding, quality metadata, routing metadata, and TTL fields using the existing Milvus store.
- Capture tool-cache hit and freshness-bypass signals when those decisions already occur.
- Capture split-phase chunk-yield signals when split-phase tool selection runs.
- Add focused unit coverage for the new memory-service method and runtime scheduler.

### Out of Scope

- Correction detection or retroactive patching.
- Affinity lookup or affinity-driven routing.
- Split-phase chunk reordering.
- Admin quality reporting endpoints.
- Modifying direct-route, memory-route, or fallback routing decisions.
- Computing real follow-up delay from the next user message.
- Writing AQL records into a sidecar SQL store.

---

## 3. Functional Requirements

### FR-AQL-P2-01 — Passive quality record per completed turn
When `enable_adaptive_learning = true`, the system shall write one quality record to `tool_execution_quality` for each completed chat turn that returns either:
- a final assistant response, or
- the max-tool-call fallback assistant response.

### FR-AQL-P2-02 — No quality write on failed request path
The system shall not require a quality-record write for the exception path that returns an error-style assistant message after an unhandled failure.

### FR-AQL-P2-03 — Recorded query payload
Each Phase 2 quality record shall include:
- the normalized user message text,
- a query hash derived from that normalized text,
- and the vector embedding of the normalized text.

### FR-AQL-P2-04 — Recorded execution metadata
Each Phase 2 quality record shall capture the following execution metadata when available:
- `domain_tags`
- `issue_type`
- `tools_selected`
- `tools_succeeded`
- `tools_failed`
- `tools_bypassed`
- `tools_cache_hit`
- `chunk_yields`
- `llm_turn_count`
- `synthesis_tokens`
- `routing_mode`
- `session_id`
- `timestamp`
- `expires_at`
- `user_corrected = false`
- `follow_up_gap_s = -1`

### FR-AQL-P2-05 — Tool-cache freshness bypass capture
When the existing tool-cache policy bypasses a tool because it is freshness-sensitive, the tool name shall be added to the quality record’s `tools_bypassed` field.

### FR-AQL-P2-06 — Tool-cache hit capture
When a tool result is served from the existing tool cache, the tool name shall be added to the quality record’s `tools_cache_hit` field.

### FR-AQL-P2-07 — Split-phase chunk-yield capture
When split-phase tool selection is used, the system shall capture per-chunk yield summaries in the form:
- `{"chunk": <index>, "offered": <count>, "selected": <count>}`

For non-split turns, `chunk_yields` may be empty.

### FR-AQL-P2-08 — Routing-mode capture
Phase 2 shall capture routing mode using the existing routing decisions already present in `send_message()`.

At minimum, the persisted value shall distinguish:
- `direct`
- `memory`
- `llm_fallback`

Phase 2 does not require `affinity` because affinity routing is not yet implemented.

### FR-AQL-P2-09 — LLM-turn capture
Phase 2 shall capture the number of LLM calls consumed by the current turn, including:
- optional classification calls,
- split-phase chunk selection calls,
- normal tool-selection calls,
- and the final synthesis call.

### FR-AQL-P2-10 — Synthesis-token capture
Phase 2 shall capture synthesis-token usage from the final LLM response usage payload when available. If usage is missing, the system may store `0`.

### FR-AQL-P2-11 — Async, non-blocking scheduling
Quality recording shall be scheduled using a fire-and-forget background task from the final response path and shall not block construction of the outgoing `ChatResponse`.

### FR-AQL-P2-12 — Failure isolation
If embedding generation, Milvus upsert, or any other quality-record step fails, the failure shall be logged at WARNING level and suppressed. The chat turn must still succeed.

### FR-AQL-P2-13 — TTL application
Phase 2 shall apply `aql_quality_retention_days` to compute `expires_at` for each quality record.

### FR-AQL-P2-14 — Existing behavior preserved
Phase 2 shall not change:
- tool selection order,
- direct-route bypass behavior,
- memory-route behavior,
- tool-cache policy,
- split-phase execution semantics,
- or final assistant response content.

---

## 4. Non-Functional Requirements

### NFR-AQL-P2-01 — Additive only
Phase 2 changes shall remain additive to the existing chat pipeline.

### NFR-AQL-P2-02 — No visible latency regression
Quality-record persistence shall not introduce visible response latency to the user.

### NFR-AQL-P2-03 — Degraded-mode compatible
If Milvus or embeddings are unavailable, Phase 2 shall degrade silently with warning logs only.

### NFR-AQL-P2-04 — Existing infrastructure only
Phase 2 shall reuse the existing embedding service, memory service, Milvus store, and chat runtime flow.

### NFR-AQL-P2-05 — Testable without live Milvus
Phase 2 logic shall be unit-testable using fake embedding and fake Milvus-store objects.

---

## 5. Constraints and Assumptions

- The physical collection `tool_execution_quality` and its schema already exist from Phase 1.
- `user_corrected` remains `false` in Phase 2; later phases patch it.
- `follow_up_gap_s` remains `-1` in Phase 2; later phases may compute a real value.
- List-valued fields are stored as JSON strings to match the existing Milvus scalar-field strategy.
- Phase 2 records quality history only; it does not consume that history.

---

## 6. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-AQL-P2-01 | A completed chat turn schedules one passive quality-record write when AQL is enabled |
| AC-AQL-P2-02 | Quality writes are skipped when AQL is disabled |
| AC-AQL-P2-03 | Persisted records include query hash, embedding, session ID, routing mode, TTL fields, and execution metadata |
| AC-AQL-P2-04 | Tool-cache hits and freshness-bypassed tools are captured when those events occur |
| AC-AQL-P2-05 | Split-phase chunk-yield summaries are captured when split-phase runs |
| AC-AQL-P2-06 | Embedding or Milvus failures do not break the chat response path |
| AC-AQL-P2-07 | Existing routing and user-visible assistant behavior remain unchanged |
| AC-AQL-P2-08 | Focused unit tests and full regression remain green |

---

## 7. Validation

```bash
source venv/bin/activate
pytest tests/backend/unit/test_memory_service.py tests/backend/unit/test_main_runtime.py -q
pytest tests/backend/integration/test_chat_api.py tests/backend/integration/test_memory_retrieval_flow.py tests/backend/integration/test_memory_degraded_mode.py -q
python -m pytest -q
```

Validation expectations:
- quality records are written only when enabled,
- scheduling is non-blocking,
- failures are swallowed with logs,
- and the chat/runtime regression suite stays green.
