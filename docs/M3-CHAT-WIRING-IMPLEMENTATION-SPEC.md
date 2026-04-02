# M3 Issue #10 — Wire Retrieval into Chat Flow Implementation Spec

**Issue**: #10 — M3: Wire retrieval into `backend/main.py` chat flow  
**Milestone**: M3 - Chat Integration  
**HLD**: `docs/M3-CHAT-WIRING-HLD.md`  
**Requirements**: `docs/M3-CHAT-WIRING-REQUIREMENTS.md`

---

## 1. Files Changed

| File | Change Type | Summary |
|------|-------------|---------|
| `backend/main.py` | Edit | App state, lifespan, health, chat handler |
| `backend/models.py` | Edit | `HealthResponse` gains optional `memory` field |

---

## 2. backend/models.py Change

Locate `HealthResponse` (or the health response dict pattern).  Add:

```python
class HealthResponse(BaseModel):
    ...
    memory: Optional[dict] = Field(None, description="Memory subsystem status (optional)")
```

If `HealthResponse` is constructed as a plain dict, no model change is needed — just include the key.

---

## 3. backend/main.py Change Locations

### 3.1 Imports (top of file, inside the try/except lazy-import block or top-level)
No new top-level imports.  All memory imports are done lazily inside `lifespan()` to keep them
optional and avoid import-time failures when the memory packages are missing.

### 3.2 Module-level state (alongside existing storage globals)
```python
_memory_service: Optional[Any] = None   # MemoryService instance or None
```

### 3.3 lifespan() — add memory block after existing `_load_servers_from_disk()` call

See HLD §3 for the full code block.  Key points:
- use `_get_bool_env("MEMORY_ENABLED", False)` (helper already exists)
- use `_get_int_env` / `_get_float_env` (helpers already exist)
- catch all exceptions; on failure set `_memory_service = None` and log error

### 3.4 health_check() endpoint

Add two lines after building the base response dict and before the return:
```python
if _memory_service is not None:
    response_dict["memory"] = await _memory_service.health_status()
else:
    response_dict["memory"] = {"enabled": False}
```

### 3.5 Chat handler (send_message / messages endpoint)

Find the call site `await llm_client.complete(...)` (or equivalent final synthesis invocation).
Insert the retrieval block and `_format_retrieval_context()` helper immediately before it.
See HLD §5 for the full code.

Add the private helper function `_format_retrieval_context(blocks: list) -> str` near the other
private helpers.

---

## 4. Context Injection Format

```
## Retrieved context

### src/main.c (code_memory)
<snippet text up to 500 chars>

### docs/README.md (doc_memory)
<snippet text up to 500 chars>
```

This block is prepended to the system message on a shallow copy of the message list.  Example:

```python
messages_with_context = list(messages_for_llm)  # shallow copy
if context_blocks:
    context_section = _format_retrieval_context(context_blocks)
    if messages_with_context and messages_with_context[0]["role"] == "system":
        messages_with_context[0] = {
            **messages_with_context[0],
            "content": messages_with_context[0]["content"] + "\n\n" + context_section,
        }
    else:
        messages_with_context.insert(0, {"role": "system", "content": context_section})
# pass messages_with_context to llm_client.complete(...)
```

---

## 5. How to See the Before / After Difference

**Before**: `/health` has no `memory` key; chat turns make no retrieval calls.

**After**:
```bash
# With memory disabled (default):
curl -s http://localhost:8000/health | python3 -m json.tool | grep memory
# → "memory": {"enabled": false}

# With memory enabled (requires running Milvus):
MEMORY_ENABLED=true MEMORY_MILVUS_URI=http://localhost:19530 uvicorn backend.main:app
curl -s http://localhost:8000/health | python3 -m json.tool | grep -A5 memory
```
