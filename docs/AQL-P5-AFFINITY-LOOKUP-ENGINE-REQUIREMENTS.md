# AQL Phase 5 — Affinity Lookup Engine: Requirements

**Feature**: AQL Phase 5 — Affinity Lookup Engine  
**Version**: 0.1.0  
**Date**: April 4, 2026  
**Status**: Requirements Approved  
**Parent Requirements**: `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`  
**HLD**: `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-HLD.md`  
**Implementation Spec**: `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-IMPLEMENTATION-SPEC.md`  
**Prerequisites**: AQL Phases 1–4 fully implemented and validated

---

## 1. Context

Phases 2–4 established the passive execution-quality history collection and the
admin reporting surfaces that let operators inspect the stored records. Phase 5
is the first read path that turns that history into a runtime recommendation,
but only in isolation: it computes an affinity recommendation without yet
changing live routing.

The deliverable for this phase is a `MemoryService.resolve_tools_from_quality_history()`
method that returns an `AffinityRouteResult` containing:
- a confidence-scored list of recommended tool names,
- the count of quality-history records used, and
- a confidence value in the range `[0.0, 1.0]`.

Phase 5 must remain additive. It does not modify `send_message()` or activate
AQL routing on live requests; that remains Phase 6.

---

## 2. Functional Requirements

### 2.1 Public API

#### FR-AQL-P5-01 — Affinity lookup method
`MemoryService` shall expose:

```python
async def resolve_tools_from_quality_history(
    self,
    *,
    query: str,
    domain_tags: List[str],
) -> AffinityRouteResult
```

#### FR-AQL-P5-02 — Return shape
`AffinityRouteResult` shall include:
- `tool_names: List[str]`
- `confidence: float`
- `record_count: int`

All fields shall have safe empty defaults.

---

### 2.2 Retrieval and Filtering

#### FR-AQL-P5-03 — AQL gate
When `enable_adaptive_learning = false` or `enabled = false`, the method shall
return an empty `AffinityRouteResult` immediately without querying Milvus.

#### FR-AQL-P5-04 — Query embedding
The input query shall be normalized using the existing query-normalization helper
and embedded using the existing `EmbeddingService`.

#### FR-AQL-P5-05 — ANN search
The method shall perform a Milvus ANN search against the `tool_execution_quality`
collection using the embedded query vector.

#### FR-AQL-P5-06 — Corrected records excluded
Records where `user_corrected = true` shall be excluded from affinity scoring.
This may be done in the Milvus filter expression, in Python after retrieval, or both.

#### FR-AQL-P5-07 — Domain overlap filter
Only records whose `domain_tags` overlap the input `domain_tags` shall contribute
to the final affinity result. If the input `domain_tags` list is empty, the
method may treat all non-corrected records as eligible.

#### FR-AQL-P5-08 — Minimum-record guard
When the number of eligible records is below
`config.aql_min_records_for_routing`, the method shall return an empty
`AffinityRouteResult` with `confidence = 0.0`, populate `record_count` with the
actual eligible count, and log a warning.

---

### 2.3 Scoring and Aggregation

#### FR-AQL-P5-09 — Affinity score formula
Each eligible record shall be scored using:

$$
\text{affinity} =
(w_{sim} \cdot \text{similarity}) +
(w_{success} \cdot \text{success\_rate}) +
(w_{bypass} \cdot \text{bypass\_rate}) +
(w_{corrected} \cdot \mathbb{1}[\text{user\_corrected}])
$$

with defaults sourced from `MilvusConfig.aql_affinity_weights`:
- `similarity = 0.5`
- `success_rate = 0.3`
- `bypass_rate = -0.1`
- `corrected_penalty = -0.3`

Because corrected records are excluded before scoring, the corrected penalty
still exists for formula completeness but normally contributes zero.

#### FR-AQL-P5-10 — Similarity normalization
The Milvus hit distance/score shall be normalized to a bounded similarity value
in `[0.0, 1.0]` before being used in the scoring formula.

#### FR-AQL-P5-11 — Tool vote aggregation
Recommended tools shall be aggregated by weighted vote across the scored
records. The tool set should prefer `tools_succeeded` when available and may
fall back to `tools_selected` when a record has no successful-tool list.

#### FR-AQL-P5-12 — Confidence calculation
The final `confidence` shall be the mean of the positive affinity scores used in
the recommendation, clamped to `[0.0, 1.0]`.

#### FR-AQL-P5-13 — Recommendation ordering
`tool_names` shall be ordered from highest aggregated affinity weight to lowest.
Results may be capped at a reasonable maximum (for example, top 10 tools).

---

### 2.4 Failure Handling

#### FR-AQL-P5-14 — Embedding failure isolation
If query embedding fails, the method shall log a warning and return an empty
`AffinityRouteResult`.

#### FR-AQL-P5-15 — Search failure isolation
If the Milvus ANN search fails, the method shall log a warning and return an
empty `AffinityRouteResult`.

#### FR-AQL-P5-16 — No user-visible errors
No Phase 5 failure shall surface to end users. All failures shall degrade to the
existing non-AQL behavior by returning an empty result.

---

## 3. Non-Functional Requirements

#### NFR-AQL-P5-01 — No routing changes
Phase 5 shall not modify `backend/main.py` request routing behavior.

#### NFR-AQL-P5-02 — Additive only
The phase shall not change any existing API shapes or current chat behavior.

#### NFR-AQL-P5-03 — Testability
The affinity lookup implementation shall be unit-testable with fake embedding and
Milvus search responses, without requiring a live Milvus instance.

#### NFR-AQL-P5-04 — Logging
The minimum-record guard and failure paths shall log warning-level messages.
Successful lookup paths may log info-level summaries of eligible record count,
confidence, and recommended tool count.

---

## 4. Constraints and Assumptions

- The existing `EmbeddingService` and `MilvusStore.search()` APIs are reused as-is.
- `domain_tags`, `tools_selected`, `tools_succeeded`, and `tools_bypassed` remain
  stored as JSON-encoded string arrays in the quality-history collection.
- Phase 5 does not add new endpoints; the lookup engine is an internal service API only.
- Live routing integration is deferred to Phase 6.

---

## 5. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-AQL-P5-01 | `resolve_tools_from_quality_history()` returns an empty result when AQL is disabled |
| AC-AQL-P5-02 | Returns an empty result with a warning when eligible record count is below `aql_min_records_for_routing` |
| AC-AQL-P5-03 | Corrected records are excluded from the eligible record set |
| AC-AQL-P5-04 | Recommended tools are ranked by weighted affinity vote |
| AC-AQL-P5-05 | Embedding failure returns zero-confidence empty result without raising |
| AC-AQL-P5-06 | Search failure returns zero-confidence empty result without raising |
| AC-AQL-P5-07 | `record_count` reports the eligible record count used for the min-threshold decision |
| AC-AQL-P5-08 | `make test` passes with the new affinity-lookup unit tests |
