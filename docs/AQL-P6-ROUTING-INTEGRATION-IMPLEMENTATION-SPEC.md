# AQL Phase 6 — Routing Integration: Implementation Spec

**Feature**: AQL Phase 6 — Routing Integration  
**Version**: 0.1.0  
**Date**: April 4, 2026  
**Status**: Implementation Ready  
**Requirements**: `docs/AQL-P6-ROUTING-INTEGRATION-REQUIREMENTS.md`  
**HLD**: `docs/AQL-P6-ROUTING-INTEGRATION-HLD.md`

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

Add the affinity route integration inside `send_message()`:

- compute heuristic `request_mode_details` early enough to extract `domains`
- initialize `affinity_route_result = AffinityRouteResult()` and `affinity_route_applied = False`
- after the existing memory route attempt returns no tool list, call
  `resolve_tools_from_quality_history(query=message.content, domain_tags=domains)`
- if the result meets `aql_affinity_confidence_threshold`:
  - set `allowed_tool_names`
  - set `include_virtual_repeated = False`
  - set `affinity_route_applied = True`
  - log applied-route details
- if it does not meet threshold, log the skip and continue unchanged

Also update the local routing-mode helper used by the execution-quality payload
so it returns `"affinity"` when `affinity_route_applied` is true.

### 2.2 Parent docs

Add the three Phase 6 companion docs to the parent AQL companion-doc lists.

### 2.3 `tests/backend/unit/test_main_runtime.py`

Add four focused tests:
- `test_affinity_route_applies_when_enabled_and_confident`
- `test_affinity_route_skips_when_confidence_below_threshold`
- `test_affinity_route_skips_when_direct_route_exists`
- `test_affinity_route_skips_when_memory_route_already_confident`

### 2.4 `tests/backend/integration/test_chat_api.py`

Add one end-to-end test that captures the LLM request payload and asserts that
only the affinity-recommended tools are sent when the affinity route applies.

---

## 3. Focused Validation

```bash
pytest tests/backend/unit/test_main_runtime.py -k "affinity_route" -v
pytest tests/backend/integration/test_chat_api.py -k "affinity" -v
```

---

## 4. Full Regression

```bash
make test
```

---

## 5. Deliverable

A focused Phase 6 commit covering:
- `backend/main.py`
- `tests/backend/unit/test_main_runtime.py`
- `tests/backend/integration/test_chat_api.py`
- parent AQL doc updates
- the 3 new Phase 6 docs

The commit may also include the pending Phase 5 test-case expansion in
`tests/backend/unit/test_memory_service.py` if it remains uncommitted.
