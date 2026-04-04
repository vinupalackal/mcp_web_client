# AQL Phase 4 — Quality Report API: Requirements

**Feature**: AQL Phase 4 — Quality Report and Freshness Candidates Admin Endpoints  
**Version**: 0.1.0  
**Date**: April 4, 2026  
**Status**: Requirements Approved  
**Parent Requirements**: `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`  
**HLD**: `docs/AQL-P4-QUALITY-REPORT-API-HLD.md`  
**Implementation Spec**: `docs/AQL-P4-QUALITY-REPORT-API-IMPLEMENTATION-SPEC.md`  
**Prerequisite**: AQL Phase 2 (passive quality recording) fully implemented and committed

---

## 1. Context

Phase 2 established passive recording of execution-quality history to the
`tool_execution_quality_v1` Milvus collection.  Phase 3 retroactively patches
`user_corrected = true` for turns followed by a correction message.

Phase 4 makes that accumulated history operationally visible through two
read-only admin API endpoints.  No routing or recording behaviour is modified.
Both endpoints are gated by the existing `_require_admin` guard and return 503
when Milvus is unreachable.

---

## 2. Functional Requirements

### 2.1 Quality Report Endpoint

#### FR-AQL-P4-01 — Quality report endpoint
The system shall expose `GET /api/admin/memory/quality-report` accepting optional
query parameters `days` (integer, default 7) and `domain` (string, optional).

#### FR-AQL-P4-02 — Quality report response shape
The response shall conform to `QualityReportResponse` (already defined in
`backend/models.py`) and include all of the following:
- `total_turns` — count of quality records in the time window
- `avg_tools_per_turn` — mean number of tools selected across all turns
- `avg_llm_turns` — mean `llm_turn_count` across all turns
- `avg_synthesis_tokens` — mean `synthesis_tokens` across all turns
- `correction_rate` — fraction of turns where `user_corrected = true`
- `top_succeeded_tools` — top-10 most frequently succeeding tools (descending)
- `top_failed_tools` — top-10 most frequently failing tools (descending)
- `freshness_keyword_candidates` — tools that meet freshness-candidate signal thresholds
- `routing_distribution` — fractional distribution across `direct`, `affinity`, `memory`, `llm_fallback`

#### FR-AQL-P4-03 — Time-window filter
The endpoint shall filter quality records to those whose `timestamp` field falls
within the last `days` calendar days at query time (i.e. `timestamp ≥ now − days × 86400`).

#### FR-AQL-P4-04 — Domain filter
When `domain` is supplied, the endpoint shall restrict results to records whose
`domain_tags` JSON field contains the supplied string (case-insensitive substring
match using a Milvus filter expression).

#### FR-AQL-P4-05 — Empty collection response
When no records exist (collection empty or outside the time window), the endpoint
shall return a valid `QualityReportResponse` with all counts and rates at zero,
all lists empty, and `routing_distribution` as an empty dict.  It shall not return
an error.

#### FR-AQL-P4-06 — Admin guard
The endpoint shall call `_require_admin(request)`.  Requests without admin
role shall receive a 403 response.

#### FR-AQL-P4-07 — Milvus availability guard
The endpoint shall return `503 Service Unavailable` with a descriptive message
when `_memory_service is None` or when `enable_adaptive_learning = false`.

---

### 2.2 Freshness Candidates Endpoint

#### FR-AQL-P4-08 — Freshness candidates endpoint
The system shall expose `GET /api/admin/memory/freshness-candidates` with no
required query parameters.

#### FR-AQL-P4-09 — Freshness candidates response shape
The response shall conform to `FreshnessCandidatesResponse` (already defined in
`backend/models.py`) and include:
- `candidates` — ranked list of `FreshnessCandidate` objects (pattern, signal, score)
- `current_keywords` — current `tool_cache_freshness_keywords` from the active
  `MilvusConfig`

#### FR-AQL-P4-10 — Candidate derivation
Freshness candidates shall be derived from quality records over the last 30 days
(configurable via `days=` in the underlying report call) using the following signals:
- **bypass_rate**: tool appears in `tools_bypassed` in > 60% of turns where it was selected
- **cache_stale**: tool appears in `tools_failed` in > 30% of turns AND `tools_cache_hit`
  contains the same tool for those turns

#### FR-AQL-P4-11 — Candidates are read-only
The freshness candidates endpoint shall never modify `tool_cache_freshness_keywords`
or any other configuration.  It is a recommendation surface only.

#### FR-AQL-P4-12 — Admin guard
The endpoint shall call `_require_admin(request)`.

#### FR-AQL-P4-13 — Milvus availability guard
The endpoint shall return `503 Service Unavailable` when `_memory_service is None`
or `enable_adaptive_learning = false`.

---

### 2.3 `MemoryService.get_quality_report()` Method

#### FR-AQL-P4-14 — Method signature
`MemoryService` shall expose:

```python
async def get_quality_report(
    self,
    *,
    days: int = 7,
    domain: Optional[str] = None,
) -> QualityReportResponse
```

#### FR-AQL-P4-15 — Scalar-only query
The method shall use `milvus_store.query()` with a time-window filter expression
to retrieve raw quality records.  No vector embedding is generated.

#### FR-AQL-P4-16 — Graceful degradation
When `milvus_store.query()` raises an exception, the method shall log a WARNING
and return an empty `QualityReportResponse`.

#### FR-AQL-P4-17 — AQL gate
When `enable_adaptive_learning = false`, the method shall return an empty
`QualityReportResponse` immediately without querying Milvus.

#### FR-AQL-P4-18 — Freshness candidate computation
The method shall compute `freshness_keyword_candidates` using the bypass_rate and
cache_stale signals defined in FR-AQL-P4-10.  Results shall be sorted by score
descending and capped at the top 10 candidates.

---

## 3. Non-Functional Requirements

#### NFR-AQL-P4-01 — Read-only
Phase 4 adds zero write paths.  No quality records are created or modified.

#### NFR-AQL-P4-02 — No routing changes
Phase 4 does not alter `send_message`, affinity routing, correction detection,
or any other runtime chat behaviour.

#### NFR-AQL-P4-03 — OpenAPI compliance
Both endpoints shall be fully documented via Pydantic response models, FastAPI
`response_model`, `tags`, `summary`, and documented response codes (200, 403, 503).

#### NFR-AQL-P4-04 — Logging
Both endpoints shall emit `→` / `←` external log lines following the established
dual-logger convention.

---

## 4. Constraints and Assumptions

- `QualityReportResponse`, `FreshnessCandidatesResponse`, `ToolFrequencyStat`, and
  `FreshnessCandidate` are already defined in `backend/models.py` and must not be
  modified.
- The Milvus `query()` method added in Phase 3 is available and used for scalar
  record retrieval.
- The `days` parameter for freshness candidates uses a fixed 30-day lookback to
  ensure sufficient signal volume; the quality-report endpoint exposes `days` as a
  caller-controlled parameter.
- Pearson correlation signal (FR-AQL-20 from parent) is deferred to a later phase.

---

## 5. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-AQL-P4-01 | `GET /api/admin/memory/quality-report` returns 200 with valid `QualityReportResponse` when AQL is enabled and records exist |
| AC-AQL-P4-02 | Response aggregates correct `total_turns`, `correction_rate`, `routing_distribution` from underlying records |
| AC-AQL-P4-03 | `days` and `domain` filters correctly narrow the returned record set |
| AC-AQL-P4-04 | Empty collection returns zero-value response, not an error |
| AC-AQL-P4-05 | Returns 503 when `_memory_service` is None |
| AC-AQL-P4-06 | Returns 503 when `enable_adaptive_learning = false` |
| AC-AQL-P4-07 | `GET /api/admin/memory/freshness-candidates` returns valid `FreshnessCandidatesResponse` |
| AC-AQL-P4-08 | Candidates include `current_keywords` from active `MilvusConfig` |
| AC-AQL-P4-09 | Bypass-rate candidates are identified correctly (> 60% threshold) |
| AC-AQL-P4-10 | Cache-stale candidates are identified correctly (> 30% failure + cache-hit) |
| AC-AQL-P4-11 | Neither endpoint modifies any configuration |
| AC-AQL-P4-12 | `make test` passes with all existing tests plus new Phase 4 unit tests |
