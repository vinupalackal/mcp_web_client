# M3 Issue #10 — Wire Retrieval into Chat Flow HLD

**Issue**: #10 — M3: Wire retrieval into `backend/main.py` chat flow  
**Milestone**: M3 - Chat Integration  
**Requirements**: `docs/M3-CHAT-WIRING-REQUIREMENTS.md`  
**Parent HLD**: `docs/MILVUS_MCP_INTEGRATION_HLD.md` §6.1  
**Depends On**: `backend/memory_service.py` (issue #9)

---

## 1. Scope

Three change sites in `backend/main.py`:

| Site | Change |
|------|--------|
| Module-level app state | Add `_memory_service: Optional[MemoryService] = None` |
| `lifespan()` startup | Construct `MemoryService` when `MEMORY_ENABLED=true` |
| `health_check()` | Append `memory` key to response dict |
| Chat handler (post-tool, pre-synthesis) | Call `enrich_for_turn()`, inject context |

No other files are changed by this issue.

---

## 2. App State Addition

```python
# Module-level, alongside llm_config_storage and servers_storage
_memory_service: Optional["MemoryService"] = None
```

---

## 3. Lifespan Startup Changes

```python
async def lifespan(app: FastAPI):
    global _memory_service
    ...
    # --- NEW: optional memory subsystem ---
    if _get_bool_env("MEMORY_ENABLED", False):
        try:
            from backend.memory_service import MemoryService, MemoryServiceConfig
            from backend.embedding_service import EmbeddingService
            from backend.milvus_store import MilvusStore
            from backend.memory_persistence import MemoryPersistence

            db_session = _get_db_session()   # existing helper
            persistence = MemoryPersistence(db_session)
            store = MilvusStore(milvus_uri=os.getenv("MEMORY_MILVUS_URI", ""))
            embedding = EmbeddingService(llm_config=llm_config_storage)
            config = MemoryServiceConfig(
                enabled=True,
                repo_id=os.getenv("MEMORY_REPO_ID", ""),
                collection_generation=os.getenv("MEMORY_COLLECTION_GENERATION", "v1"),
                max_results=_get_int_env("MEMORY_MAX_RESULTS", 5),
                retrieval_timeout_s=_get_float_env("MEMORY_RETRIEVAL_TIMEOUT_S", 5.0),
            )
            _memory_service = MemoryService(
                embedding_service=embedding,
                milvus_store=store,
                memory_persistence=persistence,
                config=config,
            )
            logger_internal.info("Memory subsystem initialized (enabled)")
        except Exception as exc:
            logger_internal.error(f"Memory subsystem failed to initialize: {exc}")
            _memory_service = None
    else:
        logger_internal.info("Memory subsystem disabled")
    ...
```

---

## 4. Health Endpoint Changes

```python
@app.get("/health", ...)
async def health_check() -> HealthResponse:
    response = {"status": "healthy", ...}   # existing fields unchanged
    if _memory_service is not None:
        response["memory"] = await _memory_service.health_status()
    else:
        response["memory"] = {"enabled": False}
    return response
```

The `HealthResponse` Pydantic model must either accept extra fields (use `model_config =
ConfigDict(extra="allow")`) or gain an explicit `memory: Optional[dict]` field.

---

## 5. Chat Turn Integration

Locate the existing final synthesis call site.  Insert:

```python
# --- memory retrieval enrichment (optional, non-blocking) ---
context_blocks: list = []
if _memory_service is not None:
    retrieval_result = await _memory_service.enrich_for_turn(
        user_message=user_content,
        session_id=session_id,
        repo_id=None,   # uses MemoryServiceConfig.repo_id
    )
    if not retrieval_result.degraded and retrieval_result.blocks:
        context_blocks = retrieval_result.blocks
        logger_internal.debug(
            "Retrieval: %d blocks, %.0f ms",
            len(context_blocks),
            retrieval_result.latency_ms,
        )
    elif retrieval_result.degraded:
        logger_internal.warning(
            "Retrieval degraded: %s", retrieval_result.degraded_reason
        )
```

### Context injection

Build a context section string from `context_blocks`:

```python
def _format_retrieval_context(blocks: list) -> str:
    lines = ["## Retrieved context\n"]
    for block in blocks:
        lines.append(f"### {block.source_path} ({block.collection})\n")
        lines.append(block.snippet + "\n")
    return "\n".join(lines)
```

Prepend this to the system message (or inject as a separate leading context message) on a **copy** of
the message list.  Do not mutate the session history.

---

## 6. Failure Safety Checklist

| Scenario | Outcome |
|----------|---------|
| `_memory_service is None` | No retrieval, no overhead, chat proceeds |
| `enrich_for_turn` returns `degraded=True` | Warning logged, `context_blocks=[]`, chat proceeds |
| `enrich_for_turn` raises (unexpected) | Caught in `MemoryService` itself; never reaches `main.py` |
| Memory startup fails | `_memory_service = None`, startup succeeds, chat works without memory |

---

## 7. Test Strategy

No new unit tests are added in this issue; the changes in `main.py` are covered by:

1. Existing integration tests in `tests/backend/integration/test_chat_api.py` (must still pass).
2. New integration tests added in issue #12 (`test_memory_health_api.py`,
   `test_memory_retrieval_flow.py`, `test_memory_degraded_mode.py`).

---

## 8. Definition of Done

- `backend/main.py` starts with `MEMORY_ENABLED=false` (default) with zero changes to chat behavior.
- `backend/main.py` starts with `MEMORY_ENABLED=true` and a mock/real Milvus URI without crashing.
- `/health` response includes `memory` key.
- Chat responses still satisfy existing `ChatResponse` schema.
- All existing integration tests pass.
