# M3 Issue #11 — Retrieval Trace Helpers HLD

**Issue**: #11 — M3: Add retrieval trace helpers in `backend/session_manager.py`  
**Milestone**: M3 - Chat Integration  
**Requirements**: `docs/M3-TRACE-HELPERS-REQUIREMENTS.md`  
**Parent HLD**: `docs/MILVUS_MCP_INTEGRATION_HLD.md` §4.5

---

## 1. Scope

Minimal, additive changes to `backend/session_manager.py`:

| Change | Impact |
|--------|--------|
| New `retrieval_traces` dict in `__init__` | Storage only |
| `add_retrieval_trace()` | New method, keyword-only args |
| `get_retrieval_traces()` | New read accessor |
| `delete_session()` pop | Consistent cleanup |

No other files are changed.  The trace data is a thin diagnostic layer; it does not affect session
ownership, message history, or tool execution.

---

## 2. Data Shape

Each retrieval trace entry is a plain `dict`:

```python
{
    "query_hash": str,           # first 16 chars of SHA-256 of query text
    "collection_keys": list,     # e.g. ["code_memory", "doc_memory"]
    "result_count": int,
    "degraded": bool,
    "degraded_reason": str,      # "" when not degraded
    "latency_ms": float,
    "recorded_at": str,          # ISO-8601 UTC timestamp added by add_retrieval_trace
}
```

Rationale for plain dict: matches the existing `tool_traces` pattern exactly; avoids importing
dataclasses into `session_manager.py` that would create a new dependency layer.

---

## 3. Method Signatures

```python
def add_retrieval_trace(
    self,
    session_id: str,
    *,
    query_hash: str,
    collection_keys: list,
    result_count: int,
    degraded: bool,
    degraded_reason: str = "",
    latency_ms: float = 0.0,
) -> None:
    from datetime import datetime, timezone
    if session_id not in self.retrieval_traces:
        self.retrieval_traces[session_id] = []
    self.retrieval_traces[session_id].append({
        "query_hash": query_hash,
        "collection_keys": collection_keys,
        "result_count": result_count,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "latency_ms": latency_ms,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    })


def get_retrieval_traces(self, session_id: str) -> list:
    return list(self.retrieval_traces.get(session_id, []))
```

---

## 4. delete_session() Delta

```python
def delete_session(self, session_id: str) -> bool:
    ...
    del self.sessions[session_id]
    self.messages.pop(session_id, None)
    self.tool_traces.pop(session_id, None)
    self.retrieval_traces.pop(session_id, None)   # NEW
    ...
```

---

## 5. Integration with main.py (Issue #10 connector)

After `enrich_for_turn()` returns, `main.py` calls:

```python
session_manager.add_retrieval_trace(
    session_id,
    query_hash=retrieval_result_query_hash,
    collection_keys=["code_memory", "doc_memory"],
    result_count=len(retrieval_result.blocks),
    degraded=retrieval_result.degraded,
    degraded_reason=retrieval_result.degraded_reason,
    latency_ms=retrieval_result.latency_ms,
)
```

This call is guarded by `if _memory_service is not None` in `main.py`.

---

## 6. Test Strategy

Add 4 new tests to `tests/backend/unit/test_session_manager.py`:

| Test | Scenario |
|------|---------|
| TC-TRACE-01 | `add_retrieval_trace` stores all fields including `recorded_at` |
| TC-TRACE-02 | `get_retrieval_traces` returns empty list for missing session |
| TC-TRACE-03 | `delete_session` removes retrieval traces |
| TC-TRACE-04 | Multiple traces accumulate in order |

---

## 7. Definition of Done

- `backend/session_manager.py` has `retrieval_traces`, `add_retrieval_trace`, `get_retrieval_traces`.
- `delete_session` clears traces.
- TC-TRACE-01 through TC-TRACE-04 all pass.
- All existing session manager tests still pass.
