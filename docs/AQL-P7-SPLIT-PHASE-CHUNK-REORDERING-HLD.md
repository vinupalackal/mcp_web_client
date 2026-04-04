# AQL Phase 7 — Split-Phase Chunk Reordering: High-Level Design

**Feature**: AQL Phase 7 — Split-Phase Chunk Reordering  
**Version**: 0.1.0  
**Date**: April 4, 2026  
**Status**: Design Ready  
**Parent HLD**: `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`  
**Requirements**: `docs/AQL-P7-SPLIT-PHASE-CHUNK-REORDERING-REQUIREMENTS.md`  
**Implementation Spec**: `docs/AQL-P7-SPLIT-PHASE-CHUNK-REORDERING-IMPLEMENTATION-SPEC.md`

---

## 1. Executive Summary

Phase 7 reuses the affinity lookup result already gathered during live routing
to improve the ordering of split-phase tool catalogs. Instead of narrowing the
tool set, it reorders the domain-filtered fallback catalog so historically
useful tools appear in chunk 1 first.

---

## 2. Placement in `send_message()`

Current Phase 6 behavior:

```
direct route → memory route → affinity route (optional) → tool catalog prep → split-phase
```

Phase 7 behavior:

```
direct route
   ↓
memory route
   ↓
affinity lookup produces result
   ↓
if affinity route applied: keep narrowed catalog
else if split-phase needed and confidence >= chunk reorder threshold:
    reorder fallback tool list
   ↓
existing rechunk + split-phase dispatch
```

---

## 3. Component Design

### 3.1 Reorder helper

`backend/main.py` adds a small helper:

```python
def _reorder_tools_by_affinity(
    tools_for_llm: List[dict],
    preferred_tool_names: List[str],
) -> List[dict]:
    ...
```

Behavior:
- keep only tool names that exist in the current catalog,
- move those tools to the front in affinity order,
- preserve original order of all other tools,
- preserve reserved virtual-tool handling.

### 3.2 Runtime integration

During split-phase catalog preparation, the runtime checks:
- split-phase is needed,
- AQL is enabled,
- `affinity_route_applied` is false,
- an `AffinityRouteResult` is available,
- confidence meets `aql_chunk_reorder_threshold`.

When true, `tools_for_llm` is reordered before `_rechunk_llm_tool_catalog()` is called.

### 3.3 Logging

Two outcomes are logged:
- **Applied**: moved names, confidence, threshold
- **Skipped**: confidence below threshold when split-phase fallback remains active

---

## 4. Testing Strategy

### 4.1 Unit coverage

Add runtime coverage for:
- helper ordering behavior,
- split-phase request reordering when threshold is met,
- skip behavior when confidence is below threshold,
- chunk-size preservation.

### 4.2 Integration coverage

Add one end-to-end chat test that:
- enables split-phase with a small chunk limit,
- returns an affinity result that is high enough for reorder but below the routing threshold,
- captures the first LLM tool payload,
- verifies chunk 1 starts with affinity-preferred tools while chunk size remains unchanged.

---

## 5. Files Changed

| File | Change |
|---|---|
| `backend/main.py` | Add reorder helper and apply it on the split-phase fallback path |
| `tests/backend/unit/test_main_runtime.py` | Add Phase 7 helper/runtime tests |
| `tests/backend/integration/test_chat_api.py` | Add one Phase 7 end-to-end split-phase reorder scenario |
| `docs/AQL-P7-SPLIT-PHASE-CHUNK-REORDERING-REQUIREMENTS.md` | New |
| `docs/AQL-P7-SPLIT-PHASE-CHUNK-REORDERING-HLD.md` | New |
| `docs/AQL-P7-SPLIT-PHASE-CHUNK-REORDERING-IMPLEMENTATION-SPEC.md` | New |
