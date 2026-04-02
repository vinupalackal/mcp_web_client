# M3 Issue #11 — Retrieval Trace Helpers Implementation Spec

**Issue**: #11 — M3: Add retrieval trace helpers in `backend/session_manager.py`  
**Milestone**: M3 - Chat Integration  
**HLD**: `docs/M3-TRACE-HELPERS-HLD.md`  
**Requirements**: `docs/M3-TRACE-HELPERS-REQUIREMENTS.md`

---

## 1. Files Changed

| File | Change Type | Summary |
|------|-------------|---------|
| `backend/session_manager.py` | Edit | 3 changes: `__init__`, new methods, `delete_session` |
| `tests/backend/unit/test_session_manager.py` | Edit | Append 4 new test cases |

---

## 2. backend/session_manager.py Edits

### 2.1 `__init__` — add retrieval_traces dict

```python
def __init__(self):
    self.sessions: Dict[str, SimpleSession] = {}
    self.messages: Dict[str, List[ChatMessage]] = {}
    self.tool_traces: Dict[str, List[Dict[str, Any]]] = {}
    self.retrieval_traces: Dict[str, List[Dict[str, Any]]] = {}   # NEW
```

### 2.2 Add methods after `get_tool_traces`

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
    """Record a retrieval event for diagnostics."""
    from datetime import datetime, timezone
    if session_id not in self.retrieval_traces:
        self.retrieval_traces[session_id] = []
    self.retrieval_traces[session_id].append({
        "query_hash": query_hash,
        "collection_keys": list(collection_keys),
        "result_count": result_count,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "latency_ms": latency_ms,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    })
    logger_internal.debug(
        "Retrieval trace added: session=%s results=%d degraded=%s",
        session_id, result_count, degraded,
    )

def get_retrieval_traces(self, session_id: str) -> List[Dict[str, Any]]:
    """Return a copy of retrieval traces for a session."""
    return list(self.retrieval_traces.get(session_id, []))
```

### 2.3 `delete_session` — pop retrieval_traces

```python
del self.sessions[session_id]
self.messages.pop(session_id, None)
self.tool_traces.pop(session_id, None)
self.retrieval_traces.pop(session_id, None)   # NEW
```

---

## 3. test_session_manager.py Additions

Append after the last existing test class:

```python
class TestRetrievalTraces:
    """TC-TRACE-01 through TC-TRACE-04."""

    def test_add_retrieval_trace_stores_all_fields(self):
        ...   # verifies query_hash, result_count, degraded, recorded_at

    def test_get_retrieval_traces_empty_for_unknown_session(self):
        ...   # returns [] without error

    def test_delete_session_removes_retrieval_traces(self):
        ...   # add trace, delete session, confirm gone

    def test_multiple_traces_accumulate_in_order(self):
        ...   # add 3 traces, confirm len==3 and order preserved
```

---

## 4. How to See the Before / After Difference

**Before**: `SessionManager` has no retrieval awareness; all retrieval state is invisible to session
diagnostics.

**After**:
```python
sm = SessionManager()
sm.create_session("s1")
sm.add_retrieval_trace("s1", query_hash="abc123", collection_keys=["code_memory"],
                       result_count=3, degraded=False)
traces = sm.get_retrieval_traces("s1")
assert len(traces) == 1
assert "recorded_at" in traces[0]
```
