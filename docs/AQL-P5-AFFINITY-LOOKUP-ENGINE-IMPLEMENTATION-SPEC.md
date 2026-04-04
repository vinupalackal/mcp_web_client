# AQL Phase 5 — Affinity Lookup Engine: Implementation Spec

**Feature**: AQL Phase 5 — Affinity Lookup Engine  
**Version**: 0.1.0  
**Date**: April 4, 2026  
**Status**: Implementation Ready  
**Requirements**: `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-REQUIREMENTS.md`  
**HLD**: `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-HLD.md`

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

### 2.1 `backend/memory_service.py`

Add a new dataclass near the existing retrieval/cache result dataclasses:

```python
@dataclass(frozen=True)
class AffinityRouteResult:
    tool_names: list[str] = field(default_factory=list)
    confidence: float = 0.0
    record_count: int = 0
```

Add `resolve_tools_from_quality_history()` to `MemoryService` after the Phase 4
reporting method and before `lookup_tool_cache()`.

Implementation details:
- Normalize query with `_build_query()`
- Return empty result when:
  - memory service disabled
  - adaptive learning disabled
  - normalized query empty
  - embedding fails
  - Milvus search fails
- Run Milvus ANN search against `tool_execution_quality`
- Search filter should exclude corrected records where possible
- Output fields should include `domain_tags`, `tools_selected`, `tools_succeeded`,
  `tools_bypassed`, and `user_corrected`
- Flatten search results with `_flatten_hits()`
- Parse `domain_tags` JSON strings and keep only overlapping records
- Guard on `aql_min_records_for_routing`
- Score records with `_score_quality_record()`
- Aggregate tools with `_aggregate_affinity_tools()`
- Compute confidence as the mean of positive affinity scores, clamped to `[0.0, 1.0]`

Helpers to add:

```python
def _score_quality_record(self, record: dict[str, Any], similarity: float) -> float

def _aggregate_affinity_tools(self, records: list[tuple[dict[str, Any], float]]) -> list[str]

def _has_domain_overlap(self, record_domains: list[str], query_domains: list[str]) -> bool

def _normalized_similarity(self, hit: dict[str, Any]) -> float
```

### 2.2 Parent docs alignment

Update the parent AQL docs to:
- add the three Phase 5 companion docs to the companion-doc list
- align the parent HLD phase table so Phase 4 represents the already-implemented
  reporting APIs and Phase 5 represents the affinity lookup engine

---

## 3. Test Specifications

### 3.1 `tests/backend/unit/test_memory_service.py`

Add a new `TestAdaptiveQueryLearningPhase5` class with:

- `test_resolve_tools_from_quality_history_returns_empty_below_min_record_threshold`
- `test_resolve_tools_from_quality_history_excludes_corrected_records`
- `test_resolve_tools_from_quality_history_scores_and_ranks_tools`
- `test_resolve_tools_from_quality_history_returns_zero_confidence_on_embedding_failure`
- `test_resolve_tools_from_quality_history_returns_zero_confidence_on_search_failure`

Test data notes:
- Use `_FakeUpsertMilvusStore.search_results["tool_execution_quality"]`
- Use small `distance` values to represent higher-similarity hits
- Use JSON-encoded strings for `domain_tags`, `tools_selected`, `tools_succeeded`, and `tools_bypassed`

---

## 4. Focused Validation

```bash
pytest tests/backend/unit/test_memory_service.py -k "Phase5 or resolve_tools_from_quality_history" -v
```

Expected:
- all new Phase 5 tests pass
- no existing MemoryService tests regress

---

## 5. Full Regression

```bash
make test
```

Expected:
- full suite stays green
- no routing behavior changes occur yet

---

## 6. Deliverable

A single focused Phase 5 commit containing:
- `backend/memory_service.py`
- `tests/backend/unit/test_memory_service.py`
- parent AQL doc alignment updates
- 3 new Phase 5 docs

No changes to `backend/main.py` in this phase.
