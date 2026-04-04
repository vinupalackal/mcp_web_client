# AQL Phase 7 — Split-Phase Chunk Reordering: Requirements

**Feature**: AQL Phase 7 — Split-Phase Chunk Reordering  
**Version**: 0.1.0  
**Date**: April 4, 2026  
**Status**: Requirements Approved  
**Parent Requirements**: `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`  
**HLD**: `docs/AQL-P7-SPLIT-PHASE-CHUNK-REORDERING-HLD.md`  
**Implementation Spec**: `docs/AQL-P7-SPLIT-PHASE-CHUNK-REORDERING-IMPLEMENTATION-SPEC.md`  
**Prerequisites**: AQL Phases 1–6 fully implemented and validated

---

## 1. Context

Phase 6 introduced affinity routing as a guarded soft prior that can narrow the
tool catalog before the LLM chooses tools. Phase 7 targets the remaining split-phase
fallback path: when the request still needs multiple tool chunks, affinity history
should improve chunk ordering without changing chunk size or bypassing the LLM.

---

## 2. Functional Requirements

### 2.1 Activation

#### FR-AQL-P7-01 — Split-phase fallback only
Chunk reordering shall only be attempted on the existing split-phase fallback path.
It shall not run when a direct route, memory route, or applied affinity route has
already narrowed the catalog.

#### FR-AQL-P7-02 — Adaptive-learning guard
Chunk reordering shall only be attempted when `_memory_service` is available and
`enable_adaptive_learning = true`.

#### FR-AQL-P7-03 — Confidence threshold
Chunk reordering shall only apply when an available `AffinityRouteResult` has
`confidence >= aql_chunk_reorder_threshold`.

### 2.2 Reordering Behavior

#### FR-AQL-P7-04 — Affinity tools moved to front
When chunk reordering applies, affinity-recommended tools shall be moved to the
front of the domain-filtered tool list before chunking.

#### FR-AQL-P7-05 — Non-affinity order preserved
Tools not present in the affinity recommendation shall preserve their original
relative order.

#### FR-AQL-P7-06 — Chunk size preserved
Chunk reordering shall not change `tools_split_limit`, chunk count, or the
existing `mcp_repeated_exec` handling rules.

### 2.3 Logging and Failure Handling

#### FR-AQL-P7-07 — Applied logging
When chunk reordering is applied, the system shall log the moved tool names,
the number of tools moved, confidence, and threshold.

#### FR-AQL-P7-08 — Skip logging
When a split-phase request has an affinity result but reordering does not qualify,
the system shall log the skip reason at info level.

#### FR-AQL-P7-09 — Failure isolation
If chunk reordering cannot be applied, the request shall continue with the
existing split-phase ordering behavior and shall not surface an error to the user.

---

## 3. Non-Functional Requirements

#### NFR-AQL-P7-01 — Additive only
Phase 7 shall preserve all existing API contracts, tool-call message shapes,
and split-phase execution behavior apart from tool ordering.

#### NFR-AQL-P7-02 — Small-surface change
Implementation shall extend the existing `backend/main.py` split-phase catalog
preparation path rather than introducing a parallel routing subsystem.

---

## 4. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-AQL-P7-01 | Split-phase tool catalogs move affinity-recommended tools into chunk 1 when confidence meets `aql_chunk_reorder_threshold` |
| AC-AQL-P7-02 | Non-affinity tools preserve their original order after reordering |
| AC-AQL-P7-03 | Chunk sizes remain unchanged after reordering |
| AC-AQL-P7-04 | Reordering is skipped when confidence is below threshold or when affinity routing already applied |
| AC-AQL-P7-05 | `make test` passes with new Phase 7 unit and integration coverage |
