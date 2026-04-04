# AQL Phase 7 — Split-Phase Chunk Reordering: Implementation Spec

**Feature**: AQL Phase 7 — Split-Phase Chunk Reordering  
**Version**: 0.1.0  
**Date**: April 4, 2026  
**Status**: Implementation Ready  
**Requirements**: `docs/AQL-P7-SPLIT-PHASE-CHUNK-REORDERING-REQUIREMENTS.md`  
**HLD**: `docs/AQL-P7-SPLIT-PHASE-CHUNK-REORDERING-HLD.md`

---

## 1. Per-Phase Execution Workflow

1. ✅ Requirements doc created  
2. ✅ HLD doc created  
3. ✅ Implementation spec created  
4. ⬜ Code implementation  
5. ⬜ Test development  
6. ⬜ Focused validation  
7. ⬜ Full regression

---

## 2. File Changes

### 2.1 `backend/main.py`

Implement split-phase chunk reordering by:

- adding `_reorder_tools_by_affinity()` near the existing tool-catalog helpers,
- initializing a default `affinity_route_result` before routing evaluation,
- reusing the Phase 6 affinity lookup result after domain narrowing,
- applying reorder only when:
  - split-phase is active,
  - affinity routing did not already apply,
  - confidence meets `aql_chunk_reorder_threshold`,
- recomputing chunks after reorder,
- logging both apply and skip outcomes.

### 2.2 Parent docs

Add the three Phase 7 companion docs to the parent AQL companion-doc lists.

### 2.3 `tests/backend/unit/test_main_runtime.py`

Add focused tests for:
- `_reorder_tools_by_affinity()` ordering semantics,
- runtime split-phase reorder application,
- runtime skip behavior below threshold,
- chunk-size preservation.

### 2.4 `tests/backend/integration/test_chat_api.py`

Add one end-to-end split-phase scenario that captures the LLM tool payload and
verifies chunk 1 receives reordered tools.

---

## 3. Focused Validation

```bash
pytest tests/backend/unit/test_main_runtime.py -k "chunk_reorder or reorder_tools_by_affinity" -v
pytest tests/backend/integration/test_chat_api.py -k "chunk_reorder" -v
```

---

## 4. Full Regression

```bash
make test
```

---

## 5. Deliverable

A focused Phase 7 change covering:
- `backend/main.py`
- `tests/backend/unit/test_main_runtime.py`
- `tests/backend/integration/test_chat_api.py`
- parent AQL doc updates
- the 3 new Phase 7 docs
