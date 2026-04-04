# AQL Phase 2 — Passive Quality Recording Implementation Spec

**Feature:** Adaptive Query Learning (AQL) — Phase 2  
**Application:** MCP Client Web  
**Date:** April 3, 2026  
**Status:** Implementation Backfilled  
**Requirements:** `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-REQUIREMENTS.md`  
**HLD:** `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-HLD.md`  
**Parent Spec:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-IMPLEMENTATION-SPEC.md`

---

## 1. Implementation Intent

This document backfills the concrete file-level implementation spec for the Phase 2 AQL work already present in the repository.

Phase 2 must remain a **passive recording** phase:
- it may observe execution outcomes,
- it may persist quality history,
- but it must not consume that history for routing or reporting.

---

## 2. Files Changed

| File | Change | Notes |
|------|--------|-------|
| `backend/memory_service.py` | Update | Add `record_execution_quality()` and normalization helpers |
| `backend/main.py` | Update | Collect quality signals and schedule background recording |
| `tests/backend/unit/test_memory_service.py` | Update | Add passive quality-record tests |
| `tests/backend/unit/test_main_runtime.py` | Update | Add background scheduling helper tests |

---

## 3. `backend/memory_service.py` Changes

### 3.1 `ToolCacheResult` extension
Add:

```python
freshness_bypassed: bool = False
```

Purpose:
- let the runtime distinguish a normal cache miss from a policy bypass caused by freshness-sensitive tool names,
- so Phase 2 can persist `tools_bypassed` without changing cache behavior.

### 3.2 `record_execution_quality()`
Add:

```python
async def record_execution_quality(
    self,
    *,
    user_message: str,
    session_id: str,
    domain_tags: Optional[list[str]] = None,
    issue_type: str = "",
    tools_selected: Optional[list[str]] = None,
    tools_succeeded: Optional[list[str]] = None,
    tools_failed: Optional[list[str]] = None,
    tools_bypassed: Optional[list[str]] = None,
    tools_cache_hit: Optional[list[str]] = None,
    chunk_yields: Optional[list[dict[str, int]]] = None,
    llm_turn_count: int = 0,
    synthesis_tokens: int = 0,
    routing_mode: str = "llm_fallback",
    user_corrected: bool = False,
    follow_up_gap_s: int = -1,
) -> None:
    ...
```

Implementation details:
- Return immediately when memory or AQL is disabled.
- Normalize the query using the existing `_build_query()` helper.
- Build `query_hash` using the existing `_query_hash()` helper.
- Build `record_id` as `quality-{query_hash}-{uuid_suffix}`.
- Clean list fields via helper methods before persistence.
- Reuse the existing embedding service via `embed_texts([normalized_query])`.
- Compute `expires_at = now_ts + aql_quality_retention_days * 86400`.
- Upsert one Milvus record into `tool_execution_quality`.
- Serialize list-valued fields with `json.dumps(...)`.
- Log start/end and optionally emit a console-style row-count summary.
- Swallow all exceptions with warning logs only.

### 3.3 Helper methods
Add:

```python
def _clean_string_list(self, values: Optional[Sequence[Any]]) -> list[str]: ...
def _clean_chunk_yields(self, values: Optional[Sequence[dict[str, Any]]]) -> list[dict[str, int]]: ...
```

Purpose:
- normalize payloads before persistence,
- avoid runtime code branching on malformed inputs,
- and keep the record shape deterministic for later phases.

### 3.4 `lookup_tool_cache()`
Update the freshness-sensitive bypass return path:

```python
return ToolCacheResult(freshness_bypassed=True)
```

This is observational only and must not change hit/miss semantics.

---

## 4. `backend/main.py` Changes

### 4.1 Background scheduling helper
Add:

```python
def _schedule_execution_quality_record(*, memory_service: Any, payload: Dict[str, Any]) -> bool: ...
```

Behavior:
- return `False` when the memory service is missing,
- return `False` when `record_execution_quality()` is absent,
- return `False` when AQL is disabled,
- otherwise create an `asyncio.create_task(...)` and attach a done-callback for defensive warning logging.

### 4.2 Per-turn local accumulators in `send_message()`
Add local tracking state:

```python
aql_tools_bypassed: set[str] = set()
aql_chunk_yields: List[Dict[str, int]] = []
aql_llm_turn_count = 0
aql_synthesis_tokens = 0
```

Add local helpers:

```python
def _record_chunk_yield(chunk_index: int, offered: int, selected: int) -> None: ...
def _current_routing_mode() -> str: ...
def _build_execution_quality_payload() -> Dict[str, Any]: ...
```

### 4.3 LLM-turn accounting
Increment `aql_llm_turn_count` at the existing LLM call sites:
- strict classification call,
- split-phase chunk calls,
- split-phase synthesis call when used,
- normal LLM request path.

### 4.4 Split-phase chunk-yield capture
Thread a `chunk_yield_collector` callback through:
- `_collect_split_phase_tool_calls(...)`
- `_stream_split_phase_tool_calls(...)`

Record:
- chunk index,
- number of tools offered to that chunk,
- number of tool calls selected from that chunk.

This is observational only and must not affect dedupe, early-stop, or pipeline behavior.

### 4.5 Tool-cache signal capture
In `_run_one_mcp_tool(...)`:
- add the tool name to `aql_tools_bypassed` when `lookup_tool_cache()` returns `freshness_bypassed=True`,
- preserve cache-hit status in tool execution records by carrying `cache_hit` into `tool_executions`.

### 4.6 Final synthesis-token capture
On the final assistant-response path:
- read `llm_response.get("usage")`,
- set `aql_synthesis_tokens` from `total_tokens` or `completion_tokens`,
- default to `0` when usage is absent.

### 4.7 Final scheduling points
After existing conversation-memory recording in both success-return paths:

```python
_schedule_execution_quality_record(
    memory_service=_memory_service,
    payload=_build_execution_quality_payload(),
)
```

Schedule from:
- final assistant response path,
- max-tool-call fallback path.

Do not schedule from the exception path in Phase 2.

---

## 5. Tests

### 5.1 `tests/backend/unit/test_memory_service.py`
Add tests:

```python
def test_record_execution_quality_upserts_quality_record_when_enabled(...): ...
def test_record_execution_quality_swallows_embedding_errors(...): ...
```

Coverage goals:
- record is written to `tool_execution_quality`,
- JSON fields are serialized as expected,
- defaults such as `user_corrected=False` and `follow_up_gap_s=-1` are present,
- embedding failure is swallowed.

### 5.2 `tests/backend/unit/test_main_runtime.py`
Add tests:

```python
def test_schedule_execution_quality_record_creates_background_task(...): ...
def test_schedule_execution_quality_record_skips_when_disabled(...): ...
```

Coverage goals:
- scheduler only creates a task when AQL is enabled,
- task callback is attached,
- disabled mode is a clean no-op.

### 5.3 Regression validation
Run:

```bash
pytest tests/backend/unit/test_memory_service.py tests/backend/unit/test_main_runtime.py -q
pytest tests/backend/integration/test_chat_api.py tests/backend/integration/test_memory_retrieval_flow.py tests/backend/integration/test_memory_degraded_mode.py -q
pytest -q
```

Expected backfilled validation result:
- focused unit suites pass,
- targeted chat/memory integrations pass,
- full backend regression remains green.

---

## 6. Deliverable

Phase 2 is complete when:
- completed turns produce passive AQL quality records when enabled,
- the response path remains non-blocking and fail-open,
- quality history is stored in `tool_execution_quality`,
- and no routing or admin behavior changes occur.

---

## 7. Deferred to Later Phases

The following remain intentionally out of scope for Phase 2:
- correction detection and record patching,
- real `follow_up_gap_s` computation,
- affinity-history search,
- affinity routing,
- admin quality reporting,
- freshness-candidate APIs,
- split-phase chunk reordering.
