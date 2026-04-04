# AQL Phase 4 — Quality Report API: High-Level Design

**Feature**: AQL Phase 4 — Quality Report and Freshness Candidates Admin Endpoints  
**Version**: 0.1.0  
**Date**: April 4, 2026  
**Status**: Design Ready  
**Parent HLD**: `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`  
**Requirements**: `docs/AQL-P4-QUALITY-REPORT-API-REQUIREMENTS.md`  
**Implementation Spec**: `docs/AQL-P4-QUALITY-REPORT-API-IMPLEMENTATION-SPEC.md`

---

## 1. Executive Summary

Phase 4 exposes the passive quality history accumulated by Phase 2 through two
read-only admin API endpoints.  It introduces one new `MemoryService` method
(`get_quality_report`) and two new FastAPI route handlers.  No routing, recording,
or session management behaviour is changed.

---

## 2. Architecture Placement

```
Admin client (curl / UI)
        │
        ▼
GET /api/admin/memory/quality-report          (NEW)
GET /api/admin/memory/freshness-candidates    (NEW)
        │
        ▼
┌─────────────────────────────────────────────┐
│  MemoryService.get_quality_report()  (NEW)  │
│                                             │
│  1. Build timestamp filter expression       │
│  2. Optionally add domain substring filter  │
│  3. MilvusStore.query() — scalar scan only  │
│  4. Aggregate records into report shape     │
│  5. Compute freshness keyword candidates    │
└─────────────────────────────────────────────┘
        │
        ▼
  mcp_client_tool_execution_quality_v1
  (existing Milvus collection — read-only path)
```

The two route handlers call `get_quality_report()` and project its result:

- `/quality-report` → full `QualityReportResponse`
- `/freshness-candidates` → `FreshnessCandidatesResponse` using
  `candidates` and `current_keywords` extracted from config

---

## 3. Data Flow

### 3.1 Quality Report

```
Request: GET /api/admin/memory/quality-report?days=7&domain=cpu

1. _require_admin(request)
2. Check _memory_service / enable_adaptive_learning → 503 if unavailable
3. Call: await _memory_service.get_quality_report(days=7, domain="cpu")
   a. since_ts = int(time.time()) - 7 * 86400
   b. filter = "timestamp >= {since_ts} AND domain_tags like '%cpu%'"
   c. milvus_store.query(collection_key="tool_execution_quality", filter=..., output_fields=[...])
   d. Parse tools_selected / tools_succeeded / tools_failed / tools_bypassed /
         tools_cache_hit / routing_mode / user_corrected / llm_turn_count /
         synthesis_tokens from each record (JSON decode array fields)
   e. Aggregate → totals, averages, frequency counts, routing distribution
   f. Compute freshness candidates
4. Return QualityReportResponse
```

### 3.2 Freshness Candidates

```
Request: GET /api/admin/memory/freshness-candidates

1. _require_admin(request)
2. Check _memory_service / enable_adaptive_learning → 503 if unavailable
3. Call: await _memory_service.get_quality_report(days=30, domain=None)
4. Extract candidates from report.freshness_keyword_candidates
5. Load current_keywords from active MilvusConfig
6. Return FreshnessCandidatesResponse(candidates=..., current_keywords=...)
```

---

## 4. Component Design

### 4.1 `MemoryService.get_quality_report()`

```
Inputs:
  days: int = 7
  domain: Optional[str] = None

Guard:
  if not config.enabled or not config.enable_adaptive_learning:
      return empty QualityReportResponse

Steps:
  1. since_ts = int(time.time()) - days * 86400
  2. Build filter:
       filter_expr = f"timestamp >= {since_ts}"
       if domain:
           filter_expr += f" AND domain_tags like '%{domain}%'"
  3. output_fields = [
       "tools_selected", "tools_succeeded", "tools_failed",
       "tools_bypassed", "tools_cache_hit",
       "llm_turn_count", "synthesis_tokens",
       "routing_mode", "user_corrected"
     ]
  4. records = milvus_store.query(
         collection_key="tool_execution_quality",
         generation=config.collection_generation,
         filter_expression=filter_expr,
         output_fields=output_fields,
     )
     Catch: any exception → log WARNING, return empty report
  5. Aggregate (see §4.2)
  6. Compute freshness candidates (see §4.3)
  7. Return QualityReportResponse
```

### 4.2 Aggregation Logic

```python
total_turns = len(records)

# Per-turn list unpacking
selected_lists  = [_parse_json_list(r.get("tools_selected"))  for r in records]
succeeded_lists = [_parse_json_list(r.get("tools_succeeded")) for r in records]
failed_lists    = [_parse_json_list(r.get("tools_failed"))    for r in records]
bypassed_lists  = [_parse_json_list(r.get("tools_bypassed"))  for r in records]
cache_hit_lists = [_parse_json_list(r.get("tools_cache_hit")) for r in records]

avg_tools_per_turn    = mean(len(s) for s in selected_lists)
avg_llm_turns         = mean(r.get("llm_turn_count", 0) for r in records)
avg_synthesis_tokens  = mean(r.get("synthesis_tokens", 0) for r in records)
correction_rate       = sum(1 for r in records if r.get("user_corrected")) / total_turns

# Tool frequency counts
top_succeeded = Counter(tool for lst in succeeded_lists for tool in lst).most_common(10)
top_failed    = Counter(tool for lst in failed_lists    for tool in lst).most_common(10)

# Routing distribution
mode_counts = Counter(r.get("routing_mode", "llm_fallback") for r in records)
routing_distribution = {mode: count / total_turns for mode, count in mode_counts.items()}
```

### 4.3 Freshness Candidate Logic

```python
# Per-tool statistics across all records
tool_selected_count = Counter(tool for lst in selected_lists for tool in lst)
tool_bypassed_count = Counter(tool for lst in bypassed_lists  for tool in lst)
tool_failed_count   = Counter(tool for lst in failed_lists    for tool in lst)

# cache_stale: failed and cache-hit in the same turn
cache_stale_count: Counter[str] = Counter()
for sel, fail, hit in zip(selected_lists, failed_lists, cache_hit_lists):
    for tool in fail:
        if tool in hit:
            cache_stale_count[tool] += 1

candidates: list[FreshnessCandidate] = []

for tool, sel_count in tool_selected_count.items():
    if sel_count == 0:
        continue
    bypass_rate = tool_bypassed_count.get(tool, 0) / sel_count
    stale_rate  = cache_stale_count.get(tool, 0)   / sel_count

    if bypass_rate > 0.60:
        candidates.append(FreshnessCandidate(
            pattern=_tool_basename(tool),
            signal="bypass_rate",
            score=round(bypass_rate, 4),
        ))
    elif stale_rate > 0.30:
        candidates.append(FreshnessCandidate(
            pattern=_tool_basename(tool),
            signal="cache_stale",
            score=round(stale_rate, 4),
        ))

# De-duplicate by pattern, keep highest score; sort descending
seen: dict[str, FreshnessCandidate] = {}
for c in candidates:
    if c.pattern not in seen or c.score > seen[c.pattern].score:
        seen[c.pattern] = c
candidates = sorted(seen.values(), key=lambda c: c.score, reverse=True)[:10]
```

`_tool_basename(tool)` strips the `server_alias__` prefix, leaving just the bare
tool name fragment as the suggested keyword pattern.

### 4.4 Admin Endpoints

```python
@app.get("/api/admin/memory/quality-report",
         response_model=QualityReportResponse,
         tags=["Admin"],
         summary="AQL quality report (admin only)",
         responses={200: ..., 403: ..., 503: ...})
async def admin_quality_report(
    request: Request,
    days: int = Query(default=7, ge=1, le=365),
    domain: Optional[str] = Query(default=None),
) -> QualityReportResponse:
    _require_admin(request)
    if _memory_service is None or not getattr(milvus_config, "enable_adaptive_learning", False):
        raise HTTPException(status_code=503, detail="AQL memory reporting not available")
    return await _memory_service.get_quality_report(days=days, domain=domain)


@app.get("/api/admin/memory/freshness-candidates",
         response_model=FreshnessCandidatesResponse,
         tags=["Admin"],
         summary="AQL freshness keyword candidates (admin only)",
         responses={200: ..., 403: ..., 503: ...})
async def admin_freshness_candidates(
    request: Request,
) -> FreshnessCandidatesResponse:
    _require_admin(request)
    if _memory_service is None or not getattr(milvus_config, "enable_adaptive_learning", False):
        raise HTTPException(status_code=503, detail="AQL memory reporting not available")
    report = await _memory_service.get_quality_report(days=30, domain=None)
    config = _get_effective_milvus_config()
    return FreshnessCandidatesResponse(
        candidates=report.freshness_keyword_candidates,
        current_keywords=list(config.tool_cache_freshness_keywords),
    )
```

---

## 5. Milvus Transaction Logging

Both endpoints produce query-only Milvus operations:

```
******* MCP CLIENT to MILVUS QUERY TOOL_EXECUTION_QUALITY TRANSACTION ****** START
  Milvus query start: collection=mcp_client_tool_execution_quality_v1 filter=...
******* MILVUS to MCP CLIENT QUERY TOOL_EXECUTION_QUALITY TRANSACTION ****** END
```

(Banner format handled by existing `milvus_store.query()` implementation.)

---

## 6. Degradation and Safety

| Failure | Behaviour |
|---|---|
| `_memory_service is None` | 503 with "AQL memory reporting not available" |
| `enable_adaptive_learning = false` | 503 with same message |
| Empty quality collection | Empty `QualityReportResponse` (200), no error |
| Milvus query raises exception | Log WARNING, return empty report (200) |
| `days < 1` or `days > 365` | FastAPI 422 validation error |

No failure path affects routing, recording, or session behaviour.

---

## 7. Files Changed

| File | Change |
|---|---|
| `backend/memory_service.py` | Add `get_quality_report()` method |
| `backend/main.py` | Add `GET /api/admin/memory/quality-report` and `GET /api/admin/memory/freshness-candidates` |
| `tests/backend/unit/test_memory_service.py` | Add `TestAdaptiveQueryLearningPhase4` |
| `tests/backend/unit/test_main_runtime.py` | Add admin endpoint Phase 4 tests |
| `docs/AQL-P4-QUALITY-REPORT-API-REQUIREMENTS.md` | New |
| `docs/AQL-P4-QUALITY-REPORT-API-HLD.md` | New |
| `docs/AQL-P4-QUALITY-REPORT-API-IMPLEMENTATION-SPEC.md` | New |
