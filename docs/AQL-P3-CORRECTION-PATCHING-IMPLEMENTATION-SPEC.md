# AQL Phase 3 — Correction Detection and Retroactive Patching Implementation Spec

**Feature:** Adaptive Query Learning (AQL) — Phase 3  
**Application:** MCP Client Web  
**Date:** April 4, 2026  
**Status:** Implementation Ready  
**Requirements:** `docs/AQL-P3-CORRECTION-PATCHING-REQUIREMENTS.md`  
**HLD:** `docs/AQL-P3-CORRECTION-PATCHING-HLD.md`  
**Parent Spec:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-IMPLEMENTATION-SPEC.md`

---

## 1. Implementation Intent

Phase 3 adds correction detection and retroactive patching on top of Phase 2’s passive quality recording.

The implementation must remain **label-only**:
- detect corrective follow-up messages,
- patch the previous quality record,
- but do not yet consume corrected history for routing decisions.

---

## 2. Files Changed

| File | Change | Notes |
|------|--------|-------|
| `backend/memory_service.py` | Update | Add regex detection helper and quality-record patching |
| `backend/main.py` | Update | Trigger asynchronous correction patching at the start of `send_message()` |
| `backend/session_manager.py` | Optional update | Provide minimal previous-turn metadata lookup if current state is insufficient |
| `tests/backend/unit/test_memory_service.py` | Update | Add regex and patch behavior coverage |
| `tests/backend/unit/test_main_runtime.py` | Update | Add detection/scheduling coverage |

---

## 3. `backend/memory_service.py` Changes

### 3.1 Correction-pattern helper
Add a helper such as:

```python
def is_correction_message(self, text: str) -> bool: ...
```

Implementation notes:
- compile the configured regex patterns once and cache them on the service instance,
- match case-insensitively,
- return `False` on empty input,
- swallow regex compilation/runtime issues conservatively if needed.

### 3.2 `patch_correction_signal()`
Add:

```python
async def patch_correction_signal(
    self,
    *,
    session_id: str,
    query_hash: str,
) -> None:
    ...
```

Implementation notes:
- search `tool_execution_quality` for a matching record using `session_id` and `query_hash`,
- if no record is found, log and return,
- if found, re-upsert the record with `user_corrected=True`,
- preserve all other record fields,
- swallow Milvus failures with warning logs only.

### 3.3 Helper utilities
If needed, add small internal helpers for:
- compiling correction regexes,
- building the Milvus filter expression,
- hydrating a record for patch-upsert.

Keep the helper surface minimal and internal.

---

## 4. `backend/main.py` Changes

### 4.1 Pre-routing correction check
At the beginning of `send_message()`, before routing selection:
- retrieve metadata for the immediately previous turn,
- evaluate the current user message with `is_correction_message(...)`,
- if corrective and prior metadata exists, schedule `patch_correction_signal(...)` asynchronously.

### 4.2 Scheduling behavior
Use the same fire-and-forget approach already established for Phase 2 background work:
- schedule with `asyncio.create_task(...)`,
- attach a defensive done-callback if needed,
- do not block the request path.

### 4.3 Metadata source
Prefer existing in-memory session state. If current metadata is insufficient, add a minimal internal-only metadata helper rather than changing API responses.

---

## 5. `backend/session_manager.py` Changes (Only If Needed)

If there is no current way to obtain previous-turn quality-record metadata, add a small helper such as:

```python
def get_last_turn_metadata(self, session_id: str) -> Optional[dict[str, Any]]: ...
```

Expected fields may include:
- previous turn query hash,
- previous turn request id,
- or any equivalent identifier needed to locate the prior quality record.

Do not expose this through public API payloads.

---

## 6. Tests

### 6.1 `tests/backend/unit/test_memory_service.py`
Add tests:

```python
def test_is_correction_message_matches_configured_patterns(...): ...
def test_patch_correction_signal_sets_user_corrected_true(...): ...
def test_patch_correction_signal_noops_when_record_missing(...): ...
def test_patch_correction_signal_swallows_milvus_failures(...): ...
```

Coverage goals:
- configured regexes match expected corrective messages,
- a found record is patched to `user_corrected=True`,
- missing-record case is safe,
- Milvus failure is swallowed.

### 6.2 `tests/backend/unit/test_main_runtime.py`
Add tests:

```python
def test_send_message_schedules_correction_patch_for_corrective_follow_up(...): ...
def test_send_message_skips_correction_patch_when_not_corrective(...): ...
def test_send_message_skips_correction_patch_when_previous_metadata_missing(...): ...
```

Coverage goals:
- runtime scheduling occurs only when both detection and previous metadata are present,
- no new LLM call is introduced for correction detection,
- no-op cases remain silent and safe.

### 6.3 Regression validation
Run:

```bash
pytest tests/backend/unit/test_memory_service.py tests/backend/unit/test_main_runtime.py -q
pytest tests/backend/integration/test_chat_api.py -q
pytest -q
```

Expected result:
- focused Phase 3 tests pass,
- chat integration remains green,
- full backend regression stays green.

---

## 7. Deliverable

Phase 3 is complete when:
- corrective follow-up messages are detected via regex only,
- prior quality records are patched to `user_corrected=true` when available,
- missing-record and failure cases degrade silently,
- and no routing behavior changes occur yet.

---

## 8. Deferred to Later Phases

The following remain out of scope for Phase 3:
- excluding corrected records from affinity routing at runtime,
- affinity scoring,
- affinity route activation,
- admin quality reports,
- freshness-candidate reporting,
- split-phase chunk reordering.
