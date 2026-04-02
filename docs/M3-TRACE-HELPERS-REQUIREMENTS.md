# M3 Issue #11 — Retrieval Trace Helpers Requirements

**Issue**: #11 — M3: Add retrieval trace helpers in `backend/session_manager.py`  
**Milestone**: M3 - Chat Integration  
**Parent Docs**: `Milvus_MCP_Integration_Requirements.md`, `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`  
**HLD**: `docs/MILVUS_MCP_INTEGRATION_HLD.md` §4.5  
**File Changed**: `backend/session_manager.py`

---

## 1. Context

`SessionManager` already owns `tool_traces` — a per-session list of tool execution records.  This
issue adds a parallel lightweight trace store for **retrieval events** so that diagnostic tooling,
future observability endpoints, and integration tests can inspect what retrieval actually happened
during a given session, without touching the tool trace structure or session lifecycle behavior.

---

## 2. Functional Requirements

### FR-TRACE-01 — Add retrieval trace store
`SessionManager.__init__` must initialize `retrieval_traces: Dict[str, List[Dict[str, Any]]]`
alongside the existing `tool_traces` dict.

### FR-TRACE-02 — `add_retrieval_trace()`
Add a method:
```python
def add_retrieval_trace(
    self,
    session_id: str,
    *,
    query_hash: str,
    collection_keys: list[str],
    result_count: int,
    degraded: bool,
    degraded_reason: str,
    latency_ms: float,
) -> None
```
The method must create the session's trace list if missing (identical to the `tool_traces` guard
pattern).

### FR-TRACE-03 — `get_retrieval_traces()`
Add a read-only accessor:
```python
def get_retrieval_traces(self, session_id: str) -> list[dict[str, Any]]
```
Returns a copy of the trace list (or empty list if session has no traces).

### FR-TRACE-04 — `build_history_summary()` extension (optional)
If `build_history_summary()` produces a human-readable session summary, include a count of
retrieval traces and any degraded events in the summary.  This is optional for Phase 1 but
must not break the existing summary output format.

### FR-TRACE-05 — Session delete clears retrieval traces
`delete_session()` must pop `retrieval_traces[session_id]` in addition to `messages` and
`tool_traces`.

### FR-TRACE-06 — No coupling to MemoryService
`session_manager.py` must not import from `backend/memory_service.py`.  Trace data is passed
in by the caller (`main.py`); `SessionManager` is a passive container.

---

## 3. Non-Functional Requirements

- NFR-TRACE-01: Zero regression on all existing session tests.
- NFR-TRACE-02: `add_retrieval_trace` is callable with keyword arguments only (enforce via `*`).
- NFR-TRACE-03: Each trace dict stored includes a timestamp (`recorded_at` ISO string) added
  automatically by `add_retrieval_trace`.

---

## 4. Acceptance Criteria

| ID | Criterion |
|----|-----------|
| AC-TRACE-01 | `SessionManager` initializes `retrieval_traces` dict in `__init__` |
| AC-TRACE-02 | `add_retrieval_trace` stores a dict with all named fields + `recorded_at` |
| AC-TRACE-03 | `get_retrieval_traces` returns empty list for unknown session_id |
| AC-TRACE-04 | `delete_session` removes retrieval traces |
| AC-TRACE-05 | All existing `test_session_manager.py` tests still pass |
| AC-TRACE-06 | New tests `TC-TRACE-01` through `TC-TRACE-04` are added and pass |
| AC-TRACE-07 | `make test` passes with ≥ 562 backend tests |
