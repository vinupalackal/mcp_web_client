# AQL Phase 6 — Routing Integration: Requirements

**Feature**: AQL Phase 6 — Routing Integration  
**Version**: 0.1.0  
**Date**: April 4, 2026  
**Status**: Requirements Approved  
**Parent Requirements**: `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`  
**HLD**: `docs/AQL-P6-ROUTING-INTEGRATION-HLD.md`  
**Implementation Spec**: `docs/AQL-P6-ROUTING-INTEGRATION-IMPLEMENTATION-SPEC.md`  
**Prerequisites**: AQL Phases 1–5 fully implemented and validated

---

## 1. Context

Phase 5 added an isolated affinity lookup engine that can recommend likely
useful tools for a query based on stored execution-quality history. Phase 6 is
where that recommendation becomes part of the live routing path.

The integration must remain conservative:
- direct single-tool routing keeps absolute priority,
- the existing memory route keeps priority over affinity,
- affinity narrows the candidate tool set but does not bypass the LLM,
- low-confidence affinity results must degrade to the existing LLM fallback path.

---

## 2. Functional Requirements

### 2.1 Routing Order

#### FR-AQL-P6-01 — Preserve routing precedence
The live routing decision order shall remain:
1. direct single-tool route,
2. existing memory route,
3. AQL affinity route,
4. existing LLM fallback / split-phase selection.

#### FR-AQL-P6-02 — Direct route precedence
If `direct_tool_route` matches, the affinity route shall not be evaluated.

#### FR-AQL-P6-03 — Memory route precedence
If the existing memory route returns a non-empty tool list and is applied, the
affinity route shall not be evaluated.

---

### 2.2 Affinity Activation

#### FR-AQL-P6-04 — Activation guard
Affinity routing shall only be attempted when all of the following are true:
- `_memory_service` is available,
- `enable_adaptive_learning = true`,
- no direct route matched,
- no memory route was applied.

#### FR-AQL-P6-05 — Domain tags input
The affinity lookup shall be invoked with domain tags derived from the existing
request-mode classification heuristics for the current user message.

#### FR-AQL-P6-06 — Confidence threshold
The affinity result shall only apply when
`affinity_result.confidence >= aql_affinity_confidence_threshold`.

#### FR-AQL-P6-07 — Tool narrowing only
When applied, affinity routing shall set `allowed_tool_names` to the affinity
result’s tool list and preserve the existing downstream LLM selection path.
The LLM still receives the narrowed tool catalog and makes the final tool call
selection.

#### FR-AQL-P6-08 — Include-virtual flag
When affinity routing applies, `include_virtual_repeated` shall be set to `False`
so the narrowed catalog behaves consistently with the existing memory route.

---

### 2.3 Logging and State

#### FR-AQL-P6-09 — Routing-mode tracking
When affinity routing applies, the quality-record payload and runtime logging
shall identify the routing mode as `affinity`.

#### FR-AQL-P6-10 — Applied-route logging
The system shall log an info-level message when affinity routing is applied,
including confidence, record count, and selected tool names.

#### FR-AQL-P6-11 — Low-confidence logging
When affinity lookup runs but does not meet threshold, the system shall log that
it was skipped due to low confidence.

---

### 2.4 Failure Handling

#### FR-AQL-P6-12 — Affinity failure isolation
If affinity lookup throws or returns an empty result, the request shall continue
through the existing LLM fallback path without surfacing an error to the user.

#### FR-AQL-P6-13 — No route bypass
Affinity integration shall not bypass the LLM or directly execute tools.

---

## 3. Non-Functional Requirements

#### NFR-AQL-P6-01 — Additive only
Phase 6 shall preserve all existing API contracts and message shapes.

#### NFR-AQL-P6-02 — Direct-route safety
All existing direct-route tests shall continue to pass unchanged.

#### NFR-AQL-P6-03 — Memory-route safety
All existing memory-route behavior shall continue to work unchanged when it
already returns a confident tool list.

---

## 4. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-AQL-P6-01 | A confident affinity result narrows the LLM tool catalog to the recommended tools |
| AC-AQL-P6-02 | Low-confidence affinity results fall back to the existing full/filtered catalog |
| AC-AQL-P6-03 | Direct-route matches skip affinity lookup entirely |
| AC-AQL-P6-04 | Existing memory-route matches skip affinity lookup entirely |
| AC-AQL-P6-05 | Runtime quality payload reports `routing_mode="affinity"` when affinity is applied |
| AC-AQL-P6-06 | End-to-end chat flow still calls the LLM, with the narrowed catalog, rather than bypassing it |
| AC-AQL-P6-07 | `make test` passes with new Phase 6 unit and integration coverage |
