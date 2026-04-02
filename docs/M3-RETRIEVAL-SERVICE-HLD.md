# M3 Issue #9 — Retrieval Orchestration Service HLD

**Issue**: #9 — M3: Implement retrieval orchestration service  
**Milestone**: M3 - Chat Integration  
**Requirements**: `docs/M3-RETRIEVAL-SERVICE-REQUIREMENTS.md`  
**Parent HLD**: `docs/MILVUS_MCP_INTEGRATION_HLD.md` §4.1, §6.1  
**New File**: `backend/memory_service.py`

---

## 1. Scope

`backend/memory_service.py` is the sole new module introduced by this issue.  It coordinates
`EmbeddingService`, `MilvusStore`, and `MemoryPersistence` into a single async retrieval call that
is safe to invoke from the chat path.

No changes to `backend/main.py`, `backend/session_manager.py`, or any existing module are part of
this issue.  Those integrations are covered by issues #10 and #11.

---

## 2. Class Design

```
MemoryService
├── __init__(embedding_service, milvus_store, memory_persistence, config)
├── async enrich_for_turn(user_message, session_id, repo_id) → RetrievalResult
├── async health_status() → dict
└── _build_retrieval_query(user_message) → str      # may strip noise / truncate
```

### 2.1 RetrievalResult dataclass

```python
@dataclass
class RetrievalResult:
    blocks: list[RetrievalBlock]   # ordered, capped to max_results
    degraded: bool                 # True if embedding or search failed
    degraded_reason: str           # human-readable failure summary or ""
    latency_ms: float
```

### 2.2 RetrievalBlock dataclass

```python
@dataclass
class RetrievalBlock:
    payload_ref: str
    collection: str        # "code_memory" | "doc_memory"
    score: float           # similarity score from Milvus (lower = better for COSINE)
    snippet: str           # truncated summary or chunk text, ≤ 500 chars
    source_path: str       # relative path from store record
```

---

## 3. enrich_for_turn() Flow

```
1. Check enabled flag → return empty RetrievalResult(degraded=False) if disabled
2. Record start time
3. Build query text from user_message (truncate to 512 chars)
4. Call EmbeddingService.embed_texts([query_text])
   → on failure: log, return RetrievalResult(degraded=True, reason=...)
5. Search MilvusStore for "code_memory" with repo_id filter + generation
6. Search MilvusStore for "doc_memory" with repo_id filter + generation
   → on any search failure: log, return RetrievalResult(degraded=True, reason=...)
7. Merge and sort results by score (ascending for COSINE distance)
8. Cap to max_results
9. Build RetrievalBlock list from raw Milvus result dicts
10. Record provenance via memory_persistence.record_retrieval_provenance(...)
11. Return RetrievalResult(blocks=..., degraded=False, latency_ms=...)
```

**Timeout**: wrap steps 4–6 in `asyncio.wait_for(..., timeout=retrieval_timeout_s)`.  On
`asyncio.TimeoutError`, treat as degraded.

---

## 4. health_status() Design

Returns a plain dict so it can be serialized into the existing `HealthResponse` without coupling to new
Pydantic models:

```python
{
    "enabled": bool,
    "healthy": bool,
    "degraded": bool,
    "active_collections": ["code_memory_v1", "doc_memory_v1"],
    "last_failure_reason": str | None,
}
```

Health check performs lightweight `MilvusStore.list_collections()` and embedding-provider ping if
`enabled=True`.  If either fails, `healthy=False`, `degraded=True`.

---

## 5. Configuration

`MemoryServiceConfig` dataclass (constructed from env vars in `backend/main.py` later):

```python
@dataclass
class MemoryServiceConfig:
    enabled: bool = False
    repo_id: str = ""
    collection_generation: str = "v1"
    max_results: int = 5
    retrieval_timeout_s: float = 5.0
```

---

## 6. Error Handling

| Failure | Behavior |
|---------|----------|
| `EmbeddingServiceError` | `degraded=True`, log warning, return empty |
| `MilvusStoreError` | `degraded=True`, log warning, return empty |
| `asyncio.TimeoutError` | `degraded=True`, log warning at WARNING level |
| Unexpected exception | `degraded=True`, log error, return empty — never propagate |

---

## 7. Dependencies

| Dependency | Direction |
|------------|-----------|
| `backend/embedding_service.py` | consumes `EmbeddingService` |
| `backend/milvus_store.py` | consumes `MilvusStore` |
| `backend/memory_persistence.py` | consumes `MemoryPersistence` |
| `backend/models.py` | reads `MemoryFeatureFlags` for enabled check |

`backend/main.py` will import and construct `MemoryService` in a later issue (#10).

---

## 8. Test Strategy

New file: `tests/backend/unit/test_memory_service.py`

| Test | Scenario |
|------|---------|
| TC-MEM-01 | `enabled=False` → no embedding/store calls, empty result |
| TC-MEM-02 | Happy path → embed, search both collections, capped result, provenance recorded |
| TC-MEM-03 | Embedding failure → degraded=True, empty blocks |
| TC-MEM-04 | Milvus search failure → degraded=True, empty blocks |
| TC-MEM-05 | Timeout → degraded=True, empty blocks |
| TC-MEM-06 | `health_status()` when enabled and Milvus reachable → healthy=True |
| TC-MEM-07 | `health_status()` when Milvus unreachable → healthy=False, degraded=True |
| TC-MEM-08 | Result capping: > max_results Milvus hits → only max_results blocks returned |
| TC-MEM-09 | repo_id filter is passed to both store.search() calls |

---

## 9. Definition of Done

- `backend/memory_service.py` exists with `MemoryService`, `RetrievalResult`, `RetrievalBlock`, and
  `MemoryServiceConfig`.
- `tests/backend/unit/test_memory_service.py` contains TC-MEM-01 through TC-MEM-09, all passing.
- `make test` passes with no regressions.
