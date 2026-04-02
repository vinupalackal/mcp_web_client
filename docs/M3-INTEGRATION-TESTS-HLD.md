# M3 Issue #12 — Memory Integration Test Coverage HLD

**Issue**: #12 — M3: Add memory integration test coverage  
**Milestone**: M3 - Chat Integration  
**Requirements**: `docs/M3-INTEGRATION-TESTS-REQUIREMENTS.md`  
**Parent HLD**: `docs/MILVUS_MCP_INTEGRATION_HLD.md` §12.2

---

## 1. Scope

Three new integration test files.  No production code changes.

| File | Tests |
|------|-------|
| `tests/backend/integration/test_memory_health_api.py` | TC-HEALTH-01 – TC-HEALTH-03 |
| `tests/backend/integration/test_memory_retrieval_flow.py` | TC-FLOW-01 – TC-FLOW-03 |
| `tests/backend/integration/test_memory_degraded_mode.py` | TC-DEGRADE-01 – TC-DEGRADE-02 |

---

## 2. test_memory_health_api.py

### Pattern

Uses the existing `httpx.AsyncClient` + FastAPI `TestClient` fixture from `conftest.py`.
Monkeypatches `backend.main._memory_service` to inject a fake `MemoryService`.

### TC-HEALTH-01: memory disabled
```
Setup:   _memory_service = None
Request: GET /health
Assert:  response["memory"]["enabled"] == False
         response["status"] == "healthy"
```

### TC-HEALTH-02: memory enabled and healthy
```
Setup:   _memory_service = FakeMemoryService(healthy=True)
Request: GET /health
Assert:  response["memory"]["enabled"] == True
         response["memory"]["healthy"] == True
         response["memory"]["degraded"] == False
         response["status"] == "healthy"
```

### TC-HEALTH-03: memory enabled and degraded
```
Setup:   _memory_service = FakeMemoryService(healthy=False, degraded=True)
Request: GET /health
Assert:  response["memory"]["degraded"] == True
         response["status"] == "healthy"  # app-level status unaffected
```

---

## 3. test_memory_retrieval_flow.py

### TC-FLOW-01: chat with memory disabled
```
Setup:   _memory_service = None
Request: POST /api/sessions/{id}/messages  {"content": "explain the code"}
Assert:  200 OK, valid ChatResponse schema
         No retrieval_traces recorded (memory not wired)
```

### TC-FLOW-02: chat with memory enabled, retrieval succeeds
```
Setup:   _memory_service = FakeMemoryService returning 2 blocks
Request: POST /api/sessions/{id}/messages  {"content": "explain the code"}
Assert:  200 OK, valid ChatResponse schema
         session_manager.get_retrieval_traces(session_id) has 1 entry
         trace["result_count"] == 2
         trace["degraded"] == False
```

### TC-FLOW-03: chat with memory enabled, retrieval returns empty
```
Setup:   _memory_service = FakeMemoryService returning 0 blocks (not degraded)
Request: POST /api/sessions/{id}/messages  {"content": "explain the code"}
Assert:  200 OK, valid ChatResponse schema
         trace["result_count"] == 0
```

---

## 4. test_memory_degraded_mode.py

### TC-DEGRADE-01: retrieval degraded mid-turn
```
Setup:   _memory_service = FakeMemoryService(degraded=True on enrich_for_turn)
Request: POST /api/sessions/{id}/messages
Assert:  200 OK, valid ChatResponse
         trace["degraded"] == True
         response does NOT contain an error field
```

### TC-DEGRADE-02: memory service unavailable at startup (simulated by None)
```
Setup:   _memory_service = None  (simulates startup failure leaving memory=None)
Request: GET /health  AND  POST /api/sessions/{id}/messages
Assert:  /health → memory.enabled=False
         chat → 200 OK, valid ChatResponse
```

---

## 5. Fake MemoryService Helper

Define `_FakeMemoryService` in a shared helper or inline in each test file:

```python
class _FakeMemoryService:
    def __init__(self, *, healthy=True, degraded=False, blocks=None):
        self._healthy = healthy
        self._degraded = degraded
        self._blocks = blocks or []

    async def enrich_for_turn(self, *, user_message, session_id, repo_id=None):
        from backend.memory_service import RetrievalResult, RetrievalBlock
        if self._degraded:
            return RetrievalResult(degraded=True, degraded_reason="fake degraded")
        return RetrievalResult(blocks=self._blocks, degraded=False)

    async def health_status(self):
        return {
            "enabled": True,
            "healthy": self._healthy,
            "degraded": not self._healthy,
            "active_collections": ["mcp_client_code_memory_v1"],
            "last_failure_reason": None if self._healthy else "fake failure",
        }
```

---

## 6. Definition of Done

- All 7 integration tests pass (3 health + 3 flow + 2 degraded = 8 total across 3 files — adjust to
  actual test count).
- No existing integration tests broken.
- `make test` passes.
