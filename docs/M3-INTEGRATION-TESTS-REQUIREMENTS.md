# M3 Issue #12 — Memory Integration Test Coverage Requirements

**Issue**: #12 — M3: Add memory integration test coverage  
**Milestone**: M3 - Chat Integration  
**Parent Docs**: `Milvus_MCP_Integration_Requirements.md`, `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`  
**Depends On**: Issues #9, #10, #11  
**New Files**: `tests/backend/integration/test_memory_health_api.py`,
`tests/backend/integration/test_memory_retrieval_flow.py`,
`tests/backend/integration/test_memory_degraded_mode.py`

---

## 1. Context

Issues #9–#11 deliver the implementation.  Issue #12 closes the test coverage gap with integration
tests that exercise the wired application end-to-end using `httpx.AsyncClient` against the FastAPI
`TestClient`, identical in pattern to `tests/backend/integration/test_chat_api.py`.

All tests run without a real Milvus instance.  `MemoryService` is either injected with fakes or the
memory subsystem is left disabled (the default) to verify the no-op path.

---

## 2. Functional Requirements

### FR-INTTEST-01 — Health endpoint: memory disabled
`GET /health` must return `memory.enabled=false` when the app is started without `MEMORY_ENABLED`.

### FR-INTTEST-02 — Health endpoint: memory enabled and healthy
When the app is started with `MEMORY_ENABLED=true` and a mock `MemoryService` is injected that
returns `healthy=True`, `GET /health` must return `memory.healthy=true`.

### FR-INTTEST-03 — Health endpoint: memory enabled and degraded
When a mock `MemoryService.health_status()` returns `healthy=False, degraded=True`, the `/health`
response must still have top-level `status=healthy` (memory degradation does not degrade the app).

### FR-INTTEST-04 — Chat flow: memory disabled → no-op path
`POST /api/sessions/{id}/messages` with memory disabled must return the same `ChatResponse` schema
as the current app; no extra keys are required.

### FR-INTTEST-05 — Chat flow: memory enabled, retrieval succeeds
With a mock `MemoryService` injected that returns 2 non-degraded blocks, the chat response is
still a valid `ChatResponse` and the LLM synthesis is called with augmented context.

### FR-INTTEST-06 — Chat flow: memory enabled, retrieval degraded
With a mock `MemoryService` injected that returns `degraded=True`, the chat response is valid;
no error is surfaced to the caller.

### FR-INTTEST-07 — Milvus unavailable at startup
When `MEMORY_ENABLED=true` but the Milvus URI is unreachable, the app still starts and chat still
works.  The `/health` response shows memory as degraded.

### FR-INTTEST-08 — Retrieval trace is recorded in session
After a successful chat turn with retrieval, `SessionManager.get_retrieval_traces(session_id)` is
non-empty and contains the correct `result_count`.

---

## 3. Non-Functional Requirements

- NFR-INTTEST-01: No real Milvus or embedding provider instance is required.
- NFR-INTTEST-02: Use the same `httpx.AsyncClient`/`TestClient` pattern as existing integration tests.
- NFR-INTTEST-03: Test helpers may monkeypatch `backend.main._memory_service` directly.
- NFR-INTTEST-04: All tests must be deterministic and not depend on network availability.

---

## 4. Acceptance Criteria

| ID | Criterion |
|----|-----------|
| AC-INTTEST-01 | `test_memory_health_api.py` has 3 tests (disabled, healthy, degraded), all passing |
| AC-INTTEST-02 | `test_memory_retrieval_flow.py` has 2 tests (disabled no-op, enabled success), all passing |
| AC-INTTEST-03 | `test_memory_degraded_mode.py` has 2 tests (degraded retrieval, startup failure), all passing |
| AC-INTTEST-04 | All existing integration and unit tests continue to pass |
| AC-INTTEST-05 | `make test` passes with ≥ 562 backend + 141 frontend tests |
