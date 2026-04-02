# M3 Issue #9 — Retrieval Orchestration Service Requirements

**Issue**: #9 — M3: Implement retrieval orchestration service  
**Milestone**: M3 - Chat Integration  
**Parent Docs**: `Milvus_MCP_Integration_Requirements.md`, `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`  
**HLD**: `docs/MILVUS_MCP_INTEGRATION_HLD.md` §4.1  
**New File**: `backend/memory_service.py`

---

## 1. Context

M1 and M2 produced all the supporting layers: embedding service, Milvus store abstraction, ingestion
pipeline, and sidecar persistence adapter.  M3 now builds the top-level orchestration service that
coordinates those layers during a live chat turn, providing contextually relevant code and documentation
snippets to the LLM before final synthesis.

The `MemoryService` is the **only** new coupling point between the retrieval stack and the chat path.
All other modules remain unchanged by this issue.

---

## 2. Functional Requirements

### FR-RET-01 — Enable/disable guard
`MemoryService` must check a feature-flag at construction time (or per-call).  When the memory feature is
disabled it returns an empty result immediately without touching the embedding or Milvus layers.

### FR-RET-02 — Query embedding
`MemoryService.enrich_for_turn()` must embed the user message using `EmbeddingService` before searching.

### FR-RET-03 — Dual-collection search
`enrich_for_turn()` must search both `code_memory` and `doc_memory` collections via `MilvusStore` and
merge results into a unified ranked list.

### FR-RET-04 — Result capping
The number of returned context blocks must be bounded by a configurable `max_results` (default 5).

### FR-RET-05 — Provenance record
For every call that returns results, `MemoryService` must record retrieval provenance via
`MemoryPersistence.record_retrieval_provenance()`, including the session_id, query hash, collection keys
used, and result count.

### FR-RET-06 — Degraded fallback
If the embedding or Milvus operation raises any exception, `enrich_for_turn()` must:
- log the failure with reason and latency,
- return an empty result list (not raise),
- and set a `degraded=True` flag on the returned result object.

### FR-RET-07 — Health check
`MemoryService.health_status()` must return a `MemoryStatus`-compatible dict (or model) with at least:
`enabled`, `healthy`, `degraded`, and `active_collections`.

### FR-RET-08 — Workspace/repo scope filter
Searches must be filtered to the configured `repo_id` or workspace scope so cross-workspace results are
never returned.

### FR-RET-09 — Result normalization
Each returned context block must include at minimum: `payload_ref`, `score`, `collection`, `snippet`
(truncated payload or summary).

### FR-RET-10 — No FastAPI dependency
`MemoryService` must be instantiable and testable without starting a FastAPI application.

---

## 3. Non-Functional Requirements

- NFR-RET-01: Retrieval round-trip (embed + search + normalize) must not block the chat path for more
  than a configurable timeout (default `MEMORY_RETRIEVAL_TIMEOUT_S = 5.0`).
- NFR-RET-02: All async operations use `httpx.AsyncClient` patterns consistent with existing code.
- NFR-RET-03: Logging follows the dual-logger pattern (`mcp_client.internal` / `mcp_client.external`).
- NFR-RET-04: The service is covered by unit tests using fakes; no real Milvus or embedding provider
  is required.

---

## 4. Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_ENABLED` | `false` | Master on/off switch for the memory subsystem |
| `MEMORY_REPO_ID` | `""` | Default workspace/repo scope for retrieval |
| `MEMORY_COLLECTION_GENERATION` | `v1` | Active collection generation to search |
| `MEMORY_MAX_RESULTS` | `5` | Maximum context blocks returned per turn |
| `MEMORY_RETRIEVAL_TIMEOUT_S` | `5.0` | Per-turn retrieval timeout in seconds |

---

## 5. Acceptance Criteria

| ID | Criterion |
|----|-----------|
| AC-RET-01 | `MemoryService(enabled=False).enrich_for_turn(...)` returns empty results without calling embedding or store |
| AC-RET-02 | Happy-path call embeds message, searches both collections, returns ≤ max_results blocks |
| AC-RET-03 | Embedding failure triggers degraded=True and empty result, does not raise |
| AC-RET-04 | Milvus search failure triggers degraded=True and empty result, does not raise |
| AC-RET-05 | `health_status()` returns enabled/healthy when both deps are reachable |
| AC-RET-06 | Results are filtered to the configured repo_id scope |
| AC-RET-07 | Provenance is recorded for every successful retrieval |
| AC-RET-08 | `make test` passes with ≥ 562 backend tests after implementation |
