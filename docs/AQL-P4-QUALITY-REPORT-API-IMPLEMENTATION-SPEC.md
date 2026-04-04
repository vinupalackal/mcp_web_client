# AQL Phase 4 — Quality Report API: Implementation Spec

**Feature**: AQL Phase 4 — Quality Report and Freshness Candidates Admin Endpoints  
**Version**: 0.1.0  
**Date**: April 4, 2026  
**Status**: Implementation Ready  
**Requirements**: `docs/AQL-P4-QUALITY-REPORT-API-REQUIREMENTS.md`  
**HLD**: `docs/AQL-P4-QUALITY-REPORT-API-HLD.md`

---

## 1. Per-Phase Execution Workflow

1. ✅ Requirements doc created  
2. ✅ HLD doc created  
3. ✅ Implementation spec created  
4. ⬜ Code implementation  
5. ⬜ Test development  
6. ⬜ Focused test run (`pytest -k Phase4`)  
7. ⬜ Full regression (`make test`)

---

## 2. File Changes

### 2.1 `backend/memory_service.py`

**Add after `patch_correction_signal` (Phase 3) and before `lookup_tool_cache`:**

New method `get_quality_report(days, domain)`:

```python
async def get_quality_report(
    self,
    *,
    days: int = 7,
    domain: Optional[str] = None,
) -> "QualityReportResponse":
```

Implementation notes:
- Guard: `if not self.config.enabled or not self.config.enable_adaptive_learning` → return `_empty_quality_report()`
- Build `since_ts = int(time.time()) - max(int(days), 1) * 86400`
- Build filter: `filter_expr = f"timestamp >= {since_ts}"`
- If `domain` is a non-empty string: append `f" AND domain_tags like '%{domain.replace(\"'\", \"\")}%'"`
- `output_fields` = `["tools_selected", "tools_succeeded", "tools_failed", "tools_bypassed", "tools_cache_hit", "llm_turn_count", "synthesis_tokens", "routing_mode", "user_corrected"]`
- Call `self.milvus_store.query(collection_key="tool_execution_quality", generation=..., filter_expression=..., output_fields=..., limit=None)` wrapped in try/except
- If exception: log WARNING, return empty report
- If empty list: return empty report
- Aggregate using `Counter` and list comprehensions (see HLD §4.2 and §4.3)
- Helper `_parse_json_list(value)` → returns `list[str]`, safe against `None` / malformed JSON
- Helper `_tool_basename(namespaced_name)` → strips `__`-prefix server alias if present
- Helper `_empty_quality_report()` → returns zero-value `QualityReportResponse`

New imports needed at top of file (only if not already imported):
- `from collections import Counter`
- `from statistics import mean` (or manual mean)

Return type import — add to the `TYPE_CHECKING` block or inline:
- `from backend.models import QualityReportResponse, ToolFrequencyStat, FreshnessCandidate`
  (already imported via existing `models` import at top of file — verify)

---

### 2.2 `backend/main.py`

**Add after the `admin_memory_row_counts` endpoint and before the `# Health Check` block:**

Two new endpoints (import `Query` from fastapi if not already imported):

```python
@app.get(
    "/api/admin/memory/quality-report",
    response_model=QualityReportResponse,
    tags=["Admin"],
    summary="AQL execution quality report (admin only)",
    responses={
        200: {"description": "Quality report returned"},
        403: {"description": "Admin role required"},
        503: {"description": "AQL reporting not available"},
    },
)
async def admin_quality_report(
    request: Request,
    days: int = Query(default=7, ge=1, le=365, description="Lookback window in days"),
    domain: Optional[str] = Query(default=None, description="Optional domain tag filter"),
) -> QualityReportResponse:
    ...

@app.get(
    "/api/admin/memory/freshness-candidates",
    response_model=FreshnessCandidatesResponse,
    tags=["Admin"],
    summary="AQL freshness keyword candidates (admin only)",
    responses={
        200: {"description": "Freshness candidates returned"},
        403: {"description": "Admin role required"},
        503: {"description": "AQL reporting not available"},
    },
)
async def admin_freshness_candidates(
    request: Request,
) -> FreshnessCandidatesResponse:
    ...
```

503 condition: `_memory_service is None or not getattr(_get_effective_milvus_config(), "enable_adaptive_learning", False)`

Logging: follow dual-logger pattern:
```python
logger_external.info("→ GET /api/admin/memory/quality-report (days=%s domain=%s)", days, domain)
logger_external.info("← 200 OK (total_turns=%s)", report.total_turns)
```

Model imports — add to the existing models import block in `main.py`:
- `QualityReportResponse`, `FreshnessCandidatesResponse` (already in models.py — verify import)

---

## 3. Test Specifications

### 3.1 `tests/backend/unit/test_memory_service.py`

Add `TestAdaptiveQueryLearningPhase4` class after the existing Phase 3 class.

Required fake store extension:
- `_FakeUpsertMilvusStore` already has `query_results` and `query_error` attributes from Phase 3; extend if needed.

#### TC-AQL-P4-01 — Empty collection returns zero report

```python
def test_quality_report_empty_collection(self):
    # query returns []
    # assert report.total_turns == 0
    # assert report.correction_rate == 0.0
    # assert report.routing_distribution == {}
```

#### TC-AQL-P4-02 — Aggregation is correct with known records

```python
def test_quality_report_aggregates_correctly(self):
    # Provide 3 synthetic records with known field values
    # Assert total_turns == 3, correction_rate == 1/3, avg_tools_per_turn correct,
    # routing_distribution sums to 1.0
```

#### TC-AQL-P4-03 — bypass_rate freshness candidate detected

```python
def test_freshness_candidate_bypass_rate(self):
    # 4 records: tool X in tools_selected, tools_bypassed for 3 of them (> 60%)
    # Assert FreshnessCandidate with signal="bypass_rate" for X in candidates
```

#### TC-AQL-P4-04 — cache_stale freshness candidate detected

```python
def test_freshness_candidate_cache_stale(self):
    # 4 records: tool Y failed AND cache_hit for 2 of them (> 30%)
    # Assert FreshnessCandidate with signal="cache_stale" for Y in candidates
```

#### TC-AQL-P4-05 — Milvus query error returns empty report

```python
def test_quality_report_milvus_error_returns_empty(self):
    # query raises RuntimeError
    # assert report.total_turns == 0  (no exception raised to caller)
```

#### TC-AQL-P4-06 — AQL disabled returns empty report

```python
def test_quality_report_disabled_returns_empty(self):
    # config.enable_adaptive_learning = False
    # assert report.total_turns == 0  (no Milvus call made)
```

---

### 3.2 `tests/backend/unit/test_main_runtime.py`

Add Phase 4 admin endpoint tests after the existing Phase 3 tests.

#### TC-AQL-P4-RT-01 — quality-report 503 when memory service is None

```python
def test_admin_quality_report_503_when_no_memory_service(self):
    # _memory_service = None → expect 503
```

#### TC-AQL-P4-RT-02 — freshness-candidates 503 when AQL disabled

```python
def test_admin_freshness_candidates_503_when_aql_disabled(self):
    # enable_adaptive_learning = False → expect 503
```

---

## 4. Imports Checklist

### `backend/memory_service.py`
- `from collections import Counter` — add if not present
- `QualityReportResponse`, `ToolFrequencyStat`, `FreshnessCandidate` — already in `backend/models.py`, verify top-level import

### `backend/main.py`
- `from fastapi import Query` — verify already imported (used by existing endpoints)
- `QualityReportResponse`, `FreshnessCandidatesResponse` — verify in models import line

---

## 5. Regression Validation

```bash
# Focused Phase 4 tests
pytest tests/backend/unit/test_memory_service.py -k Phase4 -v
pytest tests/backend/unit/test_main_runtime.py  -k Phase4 -v

# Full regression
make test
```

Expected: all existing tests pass + 8 new Phase 4 tests pass.

---

## 6. Deliverable

A single focused commit covering:
- `backend/memory_service.py` (+`get_quality_report` method)
- `backend/main.py` (+2 admin endpoints)
- `tests/backend/unit/test_memory_service.py` (+Phase 4 test class)
- `tests/backend/unit/test_main_runtime.py` (+Phase 4 RT tests)
- `docs/AQL-P4-QUALITY-REPORT-API-REQUIREMENTS.md` (new)
- `docs/AQL-P4-QUALITY-REPORT-API-HLD.md` (new)
- `docs/AQL-P4-QUALITY-REPORT-API-IMPLEMENTATION-SPEC.md` (new)

---

## 7. Deferred

- Pearson correlation signal for freshness candidates (FR-AQL-20 from parent) — Phase 5+
- `days` parameter for freshness-candidates endpoint — hardcoded to 30 this phase
- Admin UI integration — frontend out of scope for Phase 4
