# M3 Issue #10 — Wire Retrieval into Chat Flow Requirements

**Issue**: #10 — M3: Wire retrieval into `backend/main.py` chat flow  
**Milestone**: M3 - Chat Integration  
**Parent Docs**: `Milvus_MCP_Integration_Requirements.md`, `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`  
**HLD**: `docs/MILVUS_MCP_INTEGRATION_HLD.md` §6.1, §8  
**Depends On**: Issue #9 (`MemoryService`)  
**Files Changed**: `backend/main.py`

---

## 1. Context

Issue #9 delivers `MemoryService` as a standalone module.  This issue wires it into the application:

1. **Startup** — read memory env vars, construct `MemoryService` if enabled, store in app state.
2. **Health endpoint** — include memory subsystem status in `/health` response without breaking the
   existing `HealthResponse` contract.
3. **Chat turn** — call `MemoryService.enrich_for_turn()` after tool execution and before final LLM
   synthesis; inject retrieved context blocks into the system/context message.

No new public API endpoints are introduced by this issue.

---

## 2. Functional Requirements

### FR-WIRE-01 — Optional startup initialization
`MemoryService` is initialized during application lifespan only when `MEMORY_ENABLED=true`.  When
disabled, the app starts exactly as before with no memory objects in scope.

### FR-WIRE-02 — Health endpoint extension
The existing `/health` response dict must gain a `memory` sub-key when memory is initialized:
```json
{
  "status": "healthy",
  ...,
  "memory": {
    "enabled": true,
    "healthy": true,
    "degraded": false,
    "active_collections": ["mcp_client_code_memory_v1"]
  }
}
```
When memory is disabled, `"memory": {"enabled": false}` is acceptable.  The top-level `status` field
must remain `"healthy"` even when memory is `degraded` (memory is optional).

### FR-WIRE-03 — Pre-synthesis retrieval call
In the existing `send_message()` / chat endpoint handler, after MCP tool calls and before the final
`LLMClient.complete()` call, invoke `await memory_service.enrich_for_turn(...)`.

### FR-WIRE-04 — Context injection into synthesis
Retrieved context blocks are formatted as a concise context section appended to the system prompt or
injected as a leading assistant/context message.  The existing message list structure must not be
mutated; a copy is used.

### FR-WIRE-05 — Zero-change path when disabled
When `memory_service` is `None` (not initialized), the chat path must be byte-for-byte identical to
the current path with no branches or overhead.

### FR-WIRE-06 — Degraded result does not fail the request
If `enrich_for_turn()` returns `degraded=True`, the chat turn continues with an empty context
injection.  The `ChatResponse` contract is unchanged.

### FR-WIRE-07 — Retrieval latency is logged
Log retrieval latency at DEBUG level per turn.  Log a WARNING when retrieval is degraded.

### FR-WIRE-08 — No new required environment variables
`MEMORY_ENABLED` defaults to `false`; all other memory env vars have safe defaults.  Existing
deployments require no configuration changes.

---

## 3. Non-Functional Requirements

- NFR-WIRE-01: Retrieval adds at most `MEMORY_RETRIEVAL_TIMEOUT_S` (default 5 s) to turn latency;
  timeout is enforced inside `MemoryService`, not in `main.py`.
- NFR-WIRE-02: `MemoryService` is constructed once per startup and reused across requests (singleton
  app-state pattern matching `llm_config_storage` and `servers_storage`).
- NFR-WIRE-03: No direct `pymilvus` or embedding provider imports in `backend/main.py`.  All Milvus
  interaction stays behind `MemoryService`.

---

## 4. Environment Variables Added

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_ENABLED` | `false` | Enable memory subsystem |
| `MEMORY_REPO_ID` | `""` | Default repo scope for retrieval |
| `MEMORY_MILVUS_URI` | `""` | Milvus URI (e.g. `http://localhost:19530`) |
| `MEMORY_EMBEDDING_MODEL` | `""` | Embedding model identifier (passed to EmbeddingService) |
| `MEMORY_COLLECTION_GENERATION` | `v1` | Active collection generation |
| `MEMORY_MAX_RESULTS` | `5` | Max retrieved blocks per turn |
| `MEMORY_RETRIEVAL_TIMEOUT_S` | `5.0` | Per-turn retrieval timeout |

---

## 5. Acceptance Criteria

| ID | Criterion |
|----|-----------|
| AC-WIRE-01 | App starts with `MEMORY_ENABLED=false` (default) with no errors and no memory objects |
| AC-WIRE-02 | App starts with `MEMORY_ENABLED=true` and valid Milvus URI without errors |
| AC-WIRE-03 | `/health` returns `memory.enabled=false` when disabled |
| AC-WIRE-04 | `/health` returns `memory.enabled=true, memory.healthy=true` when enabled and Milvus reachable |
| AC-WIRE-05 | Chat turn returns valid `ChatResponse` when memory disabled |
| AC-WIRE-06 | Chat turn returns valid `ChatResponse` when memory enabled and retrieval degraded |
| AC-WIRE-07 | Chat turn appends non-empty context section when retrieval succeeds |
| AC-WIRE-08 | All existing chat API integration tests pass unchanged |
| AC-WIRE-09 | `make test` passes with ≥ 562 backend tests |
