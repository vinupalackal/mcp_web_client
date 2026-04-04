# Adaptive Query Learning (AQL) — Implementation Spec

**Feature**: Adaptive Query Learning  
**Version**: 0.1.0  
**Date**: April 3, 2026  
**Status**: Implementation Ready  
**HLD**: `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`  
**Requirements**: `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`  
**Baseline Tag**: `v0.9.0-adaptive-cache-routing`

**Per-phase companion docs**:
- `docs/AQL-P1-SCHEMA-CONFIG-STORE-REQUIREMENTS.md`
- `docs/AQL-P1-SCHEMA-CONFIG-STORE-HLD.md`
- `docs/AQL-P1-SCHEMA-CONFIG-STORE-IMPLEMENTATION-SPEC.md`
- `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-REQUIREMENTS.md`
- `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-HLD.md`
- `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-IMPLEMENTATION-SPEC.md`
- `docs/AQL-P3-CORRECTION-PATCHING-REQUIREMENTS.md`
- `docs/AQL-P3-CORRECTION-PATCHING-HLD.md`
- `docs/AQL-P3-CORRECTION-PATCHING-IMPLEMENTATION-SPEC.md`
- `docs/AQL-P4-QUALITY-REPORT-API-REQUIREMENTS.md`
- `docs/AQL-P4-QUALITY-REPORT-API-HLD.md`
- `docs/AQL-P4-QUALITY-REPORT-API-IMPLEMENTATION-SPEC.md`
- `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-REQUIREMENTS.md`
- `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-HLD.md`
- `docs/AQL-P5-AFFINITY-LOOKUP-ENGINE-IMPLEMENTATION-SPEC.md`

**Per-phase execution workflow**:
- Treat each AQL phase as a doc-backed mini-project: requirements → HLD → implementation spec → implementation → test development → focused validation → full test execution.
- Do not treat a phase as complete after docs alone; the expected execution order is phase docs, code implementation, test updates/additions, focused test runs, and then full regression execution.
- For Phase 2 and later, do not start code from only the parent AQL docs when the repo is following a per-phase documentation workflow.

---

## 1. Files Changed

| File | Change Type | Purpose |
|------|-------------|---------|
| `backend/models.py` | Update | Add AQL config fields and admin response models |
| `backend/milvus_store.py` | Update | Create/manage `tool_execution_quality_v1`, counts, cleanup hooks |
| `backend/memory_service.py` | Update | Add quality recorder, correction patch, affinity lookup, reporting |
| `backend/main.py` | Update | Wire post-response write, correction detection, affinity routing, admin APIs |
| `tests/backend/unit/test_memory_service.py` | Update | Add AQL service-level unit tests |
| `tests/backend/unit/test_main_runtime.py` | Update | Add routing and endpoint unit tests |
| `tests/backend/integration/test_chat_api.py` | Update | Add end-to-end AQL behavior coverage |
| `data/milvus_config.json` | Optional update | Add default AQL config keys when feature is enabled in dev |

---

## 2. Implementation Order

Implementation must proceed in seven phases. Phases 1–4 are passive or read-only and must land before any routing behavior changes. Phases 5–7 are gated by `enable_adaptive_learning` and confidence thresholds.

Each phase must follow the same execution order before moving to the next one:
1. Create or update that phase's requirements, HLD, and implementation spec docs.
2. Implement the phase code in the repo.
3. Develop or update focused test coverage for the new behavior.
4. Run focused validation first, then broader integration coverage if applicable, then the full backend regression suite.

```
Phase 1  Schema + Config + Store plumbing
Phase 2  Passive quality recording
Phase 3  Correction detection + retroactive patch
Phase 4  Admin reporting endpoints
Phase 5  Affinity lookup engine
Phase 6  Routing integration
Phase 7  Split-phase chunk reordering
```

---

## 3. New / Updated Types

### 3.1 `backend/models.py`

Add the following fields to `MilvusConfig`:

```python
enable_adaptive_learning: bool = Field(
    default=False,
    description="Enable Adaptive Query Learning (AQL) feedback capture and routing hints.",
)
aql_quality_retention_days: int = Field(
    default=30,
    ge=1,
    le=365,
    description="Retention window for tool_execution_quality records in days.",
)
aql_min_records_for_routing: int = Field(
    default=20,
    ge=1,
    le=1000,
    description="Minimum quality-history records required before affinity routing activates.",
)
aql_affinity_confidence_threshold: float = Field(
    default=0.65,
    ge=0.0,
    le=1.0,
    description="Minimum confidence required to apply affinity-based routing.",
)
aql_chunk_reorder_threshold: float = Field(
    default=0.70,
    ge=0.0,
    le=1.0,
    description="Minimum confidence required to reorder split-phase tool chunks.",
)
aql_affinity_weights: Dict[str, float] = Field(
    default_factory=lambda: {
        "similarity": 0.5,
        "success_rate": 0.3,
        "bypass_rate": -0.1,
        "corrected_penalty": -0.3,
    },
    description="Weight map used to compute AQL affinity scores.",
)
aql_correction_patterns: List[str] = Field(
    default_factory=lambda: [
        r"\bwrong\b",
        r"\bincorrect\b",
        r"\bactually\b",
        r"\bnot right\b",
        r"\bthat's not\b",
        r"\bthat is not\b",
        r"\bnot what I\b",
        r"\bno[,.]\b",
    ],
    description="Regex patterns used to detect corrective user follow-up messages.",
)
```

Add new response models:

```python
class ToolFrequencyStat(BaseModel):
    tool: str
    count: int

class FreshnessCandidate(BaseModel):
    pattern: str
    signal: str
    score: float

class QualityReportResponse(BaseModel):
    total_turns: int
    avg_tools_per_turn: float
    avg_llm_turns: float
    avg_synthesis_tokens: float
    correction_rate: float
    top_succeeded_tools: List[ToolFrequencyStat]
    top_failed_tools: List[ToolFrequencyStat]
    freshness_keyword_candidates: List[FreshnessCandidate]
    routing_distribution: Dict[str, float]

class FreshnessCandidatesResponse(BaseModel):
    candidates: List[FreshnessCandidate]
    current_keywords: List[str]
```

### 3.2 `backend/memory_service.py`

Add / update dataclasses:

```python
@dataclass
class AffinityRouteResult:
    tool_names: List[str] = field(default_factory=list)
    confidence: float = 0.0
    record_count: int = 0

@dataclass
class QualityRecord:
    record_id: str
    query_hash: str
    vector: List[float]
    domain_tags: List[str]
    issue_type: str
    tools_selected: List[str]
    tools_succeeded: List[str]
    tools_failed: List[str]
    tools_bypassed: List[str]
    tools_cache_hit: List[str]
    chunk_yields: List[Dict[str, int]]
    llm_turn_count: int
    synthesis_tokens: int
    routing_mode: str
    user_corrected: bool
    follow_up_gap_s: int
    session_id: str
    timestamp: int
    expires_at: int

@dataclass
class QualityReport:
    total_turns: int = 0
    avg_tools_per_turn: float = 0.0
    avg_llm_turns: float = 0.0
    avg_synthesis_tokens: float = 0.0
    correction_rate: float = 0.0
    top_succeeded_tools: List[Dict[str, Any]] = field(default_factory=list)
    top_failed_tools: List[Dict[str, Any]] = field(default_factory=list)
    freshness_keyword_candidates: List[Dict[str, Any]] = field(default_factory=list)
    routing_distribution: Dict[str, float] = field(default_factory=dict)
```

---

## 4. Phase-by-Phase Implementation

## Phase 1 — Schema + Config + Store Plumbing

Companion docs:
- `docs/AQL-P1-SCHEMA-CONFIG-STORE-REQUIREMENTS.md`
- `docs/AQL-P1-SCHEMA-CONFIG-STORE-HLD.md`
- `docs/AQL-P1-SCHEMA-CONFIG-STORE-IMPLEMENTATION-SPEC.md`

### Objective
Introduce all AQL configuration and persistence primitives with **no runtime behavior change**.

### File-level tasks

#### `backend/models.py`
- Add the seven `MilvusConfig` fields listed in §3.1.
- Extend config normalization validator to:
  - coerce empty / missing `aql_affinity_weights` to defaults,
  - trim string values in `aql_correction_patterns`,
  - drop blank correction regexes,
  - enforce lowercase keys for `aql_affinity_weights` where appropriate.
- Add `QualityReportResponse`, `FreshnessCandidatesResponse`, `ToolFrequencyStat`, `FreshnessCandidate`.

#### `backend/milvus_store.py`
- Add collection metadata entry for `tool_execution_quality` in the same registry used for:
  - `conversation_memory`
  - `tool_cache`
  - `code_memory`
  - `doc_memory`
- Implement collection creation for:
  - vector dimension = existing embedding dimension (4096)
  - scalar fields required by HLD (§3.1)
- Update any collection-key validation helpers to accept `tool_execution_quality`.
- Update `get_record_count()` and related helpers so admin row-count APIs can include the new collection.
- Update expiry cleanup helper(s) to accept TTL cleanup for the new collection by `expires_at`.

#### `backend/main.py`
- Update `_default_milvus_config_from_env()` to read:
  - `AQL_ENABLE`
  - `AQL_QUALITY_RETENTION_DAYS`
  - `AQL_MIN_RECORDS`
  - `AQL_AFFINITY_THRESHOLD`
- Update `_initialize_memory_service()` to pass all AQL config fields into `MemoryServiceConfig`.
- Update `_print_milvus_db_snapshot()` so it prints `tool_execution_quality` row counts when available.

#### `tests/backend/unit/test_main_runtime.py`
- Add config parsing tests:
  - env vars flow into `MilvusConfig`
  - invalid AQL values fail validation when appropriate
  - snapshot count helper includes the new collection key

#### `tests/backend/unit/test_memory_service.py`
- Add fixture coverage for a `MemoryServiceConfig` with AQL fields set / unset.

### Deliverable
- App starts with AQL config available.
- No routing logic uses it yet.
- No writes occur yet.

---

## Phase 2 — Passive Quality Recording

Companion docs:
- `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-REQUIREMENTS.md`
- `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-HLD.md`
- `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-IMPLEMENTATION-SPEC.md`

### Objective
Capture execution-quality signals after every completed turn, asynchronously and without affecting the response path.

### File-level tasks

#### `backend/memory_service.py`
Add:

```python
async def record_execution_quality(
    self,
    *,
    query: str,
    session_id: str,
    domain_tags: List[str],
    issue_type: str,
    tools_selected: List[str],
    tools_succeeded: List[str],
    tools_failed: List[str],
    tools_bypassed: List[str],
    tools_cache_hit: List[str],
    chunk_yields: List[Dict[str, int]],
    llm_turn_count: int,
    synthesis_tokens: int,
    routing_mode: str,
    follow_up_gap_s: int = -1,
) -> None: ...
```

Implementation notes:
- Reuse existing embedding service (`embed_texts([query])`).
- Build `query_hash = sha256(normalized_query.encode()).hexdigest()[:16]`.
- Build `record_id = f"quality-{query_hash}-{timestamp:x}"`.
- Compute `expires_at = now + retention_days * 86400`.
- Serialize list fields as JSON strings if the Milvus layer expects scalar string payloads.
- Use `milvus_store.upsert_records(collection_key="tool_execution_quality", ...)`.
- Log START / END boundaries using the external logger.

Add helper methods:

```python
def _normalize_quality_query(self, text: str) -> str: ...
def _make_quality_record(... ) -> Dict[str, Any]: ...
```

#### `backend/main.py`
After the final assistant response is produced — in the same block where conversation memory is recorded — add async post-response scheduling:

```python
if _memory_service and effective_config.enable_adaptive_learning:
    asyncio.create_task(
        _memory_service.record_execution_quality(...)
    )
```

Inputs must be built from existing local state in `send_message()`:
- `message.content`
- `session_id`
- `domain_tags`
- `issue_classification or ""`
- selected tools from `tool_executions`
- success/failure split from `tool_executions`
- cache-hit tool names collected during execution
- freshness-bypassed tool names collected during execution
- `chunk_yields` from split-phase path (empty list otherwise)
- `turn + 1` as LLM turn count
- synthesis token count from final `llm_response["usage"]`
- `routing_mode`

**Important:** if current code does not preserve `tools_bypassed`, `tools_cache_hit`, or `chunk_yields`, introduce local accumulators in `send_message()` and populate them where decisions already happen.

#### `tests/backend/unit/test_memory_service.py`
Add tests:
- `test_record_execution_quality_writes_expected_payload`
- `test_record_execution_quality_skips_when_disabled`
- `test_record_execution_quality_logs_and_swallows_embedding_failure`
- `test_record_execution_quality_logs_and_swallows_milvus_failure`

#### `tests/backend/unit/test_main_runtime.py`
Add tests:
- `test_completed_turn_schedules_quality_record_task_when_enabled`
- `test_completed_turn_does_not_schedule_quality_record_when_disabled`

### Deliverable
- Every completed turn writes one quality record.
- Failure to write never breaks chat.

---

## Phase 3 — Correction Detection + Retroactive Patch

Companion docs:
- `docs/AQL-P3-CORRECTION-PATCHING-REQUIREMENTS.md`
- `docs/AQL-P3-CORRECTION-PATCHING-HLD.md`
- `docs/AQL-P3-CORRECTION-PATCHING-IMPLEMENTATION-SPEC.md`

### Objective
Mark poor prior answers when the next user message looks like a correction.

### File-level tasks

#### `backend/memory_service.py`
Add:

```python
async def patch_correction_signal(
    self,
    *,
    session_id: str,
    query_hash: str,
) -> None: ...
```

Implementation notes:
- Search `tool_execution_quality` filtered by `session_id` and `query_hash`.
- If a record is found, upsert the same record with `user_corrected=True`.
- Preserve all other fields.
- Log patched record id.

Add helper:

```python
def is_correction_message(self, text: str) -> bool: ...
```

This should compile the regexes from config once (cache compiled patterns on the service instance).

#### `backend/main.py`
At the start of `send_message()`, before route selection:
- ask session manager for metadata about the previous turn.
- if previous turn exists and the new message matches correction patterns, schedule:

```python
asyncio.create_task(
    _memory_service.patch_correction_signal(
        session_id=session_id,
        query_hash=previous_turn_query_hash,
    )
)
```

To support this, add lightweight previous-turn metadata capture if not already available.

#### `backend/session_manager.py` *(only if needed)*
If current session manager cannot retrieve previous-turn metadata, add a minimal helper such as:

```python
def get_last_turn_metadata(self, session_id: str) -> Optional[dict[str, Any]]: ...
```

This helper should return the last assistant turn's stored `query_hash` or equivalent metadata tracked at response time.

If query-hash metadata is not currently stored in session state, store it in-memory only; do not change public API responses.

#### `tests/backend/unit/test_memory_service.py`
Add tests:
- `test_is_correction_message_matches_configured_patterns`
- `test_patch_correction_signal_sets_user_corrected_true`
- `test_patch_correction_signal_noops_when_record_missing`

#### `tests/backend/unit/test_main_runtime.py`
Add tests:
- `test_correction_message_schedules_patch_for_previous_quality_record`
- `test_non_correction_message_does_not_schedule_patch`

### Deliverable
- AQL can now distinguish accepted turns from corrected turns.

---

## Phase 4 — Admin Reporting Endpoints

### Objective
Expose read-only reporting before routing starts using the data.

### File-level tasks

#### `backend/memory_service.py`
Add:

```python
async def get_quality_report(self, *, days: int = 7, domain: Optional[str] = None) -> QualityReport: ...
async def get_freshness_candidates(self, *, days: int = 7, domain: Optional[str] = None) -> List[Dict[str, Any]]: ...
```

Implementation notes:
- Search `tool_execution_quality` with timestamp filter `timestamp >= now - days*86400`.
- Optional domain filter checks whether `domain_tags` contains the requested tag.
- Aggregate:
  - total turns
  - avg tools per turn
  - avg llm turns
  - avg synthesis tokens
  - correction rate
  - top succeeded / failed tools by frequency
  - routing mode distribution
- `get_freshness_candidates()` uses the thresholds defined in the requirements.

#### `backend/main.py`
Add endpoints:

```python
@app.get("/api/admin/memory/quality-report", response_model=QualityReportResponse, ...)
async def admin_quality_report(days: int = 7, domain: Optional[str] = None) -> QualityReportResponse: ...

@app.get("/api/admin/memory/freshness-candidates", response_model=FreshnessCandidatesResponse, ...)
async def admin_freshness_candidates(days: int = 7, domain: Optional[str] = None) -> FreshnessCandidatesResponse: ...
```

Behavior:
- return `503` if memory service unavailable or Milvus degraded.
- return current configured freshness keywords alongside candidates.

#### `tests/backend/unit/test_main_runtime.py`
Add tests:
- `test_quality_report_endpoint_returns_aggregated_payload`
- `test_freshness_candidates_endpoint_returns_ranked_candidates`
- `test_quality_report_endpoint_returns_503_when_memory_service_unavailable`
- `test_freshness_candidates_endpoint_returns_503_when_memory_service_unavailable`

#### `tests/backend/unit/test_memory_service.py`
Add aggregation tests using fake Milvus hits.

### Deliverable
- Operators can inspect data before turning on affinity routing.

---

## Phase 5 — Affinity Lookup Engine

### Objective
Compute a confidence-scored recommended tool set for semantically similar future queries.

### File-level tasks

#### `backend/memory_service.py`
Add:

```python
async def resolve_tools_from_quality_history(
    self,
    *,
    query: str,
    domain_tags: List[str],
) -> AffinityRouteResult: ...
```

Helper methods:

```python
def _score_quality_record(self, record: Dict[str, Any], similarity: float) -> float: ...
def _aggregate_affinity_tools(self, records: List[Tuple[Dict[str, Any], float]]) -> List[str]: ...
def _has_domain_overlap(self, record_domains: List[str], query_domains: List[str]) -> bool: ...
```

Implementation notes:
- embed query
- Milvus ANN search on `tool_execution_quality`
- filter out `user_corrected == True`
- filter by overlapping `domain_tags`
- if `record_count < config.aql_min_records_for_routing`, return empty result and log warning
- compute score per record
- aggregate tool votes weighted by score
- confidence = mean of top scored records clamped to `[0.0, 1.0]`

#### `tests/backend/unit/test_memory_service.py`
Add tests:
- `test_resolve_tools_from_quality_history_returns_empty_below_min_record_threshold`
- `test_resolve_tools_from_quality_history_excludes_corrected_records`
- `test_resolve_tools_from_quality_history_scores_and_ranks_tools`
- `test_resolve_tools_from_quality_history_returns_zero_confidence_on_embedding_failure`
- `test_resolve_tools_from_quality_history_returns_zero_confidence_on_search_failure`

### Deliverable
- Affinity recommendations work in isolation but are not yet wired into routing.

---

## Phase 6 — Routing Integration

### Objective
Use affinity results as a soft prior in live requests.

### File-level tasks

#### `backend/main.py`
Insert AQL routing block after direct-route and existing memory-route checks, before split-phase tool selection:

```python
affinity_route = AffinityRouteResult()
if (
    _memory_service is not None
    and effective_config.enable_adaptive_learning
    and direct_tool_route is None
    and memory_route_confidence < MEMORY_ROUTE_CONFIDENCE_THRESHOLD
):
    affinity_route = await _memory_service.resolve_tools_from_quality_history(
        query=message.content,
        domain_tags=domain_tags,
    )
    if affinity_route.confidence >= effective_config.aql_affinity_confidence_threshold:
        allowed_tool_names = affinity_route.tool_names
        routing_mode = "affinity"
        logger_internal.info(...)
```

Behavior rules:
- affinity never overrides an existing direct single-tool route.
- affinity never bypasses the LLM.
- affinity only narrows the candidate tool list sent downstream.
- if affinity returns low confidence, continue current flow unchanged.

#### `tests/backend/unit/test_main_runtime.py`
Add tests:
- `test_affinity_route_applies_when_enabled_and_confident`
- `test_affinity_route_skips_when_confidence_below_threshold`
- `test_affinity_route_skips_when_direct_route_exists`
- `test_affinity_route_skips_when_memory_route_already_confident`

#### `tests/backend/integration/test_chat_api.py`
Add end-to-end scenario:
- first query records quality data,
- second semantically similar query uses affinity route,
- LLM receives narrowed tool list,
- no existing direct-route behavior regresses.

### Deliverable
- AQL begins influencing live routing under guardrails.

---

## Phase 7 — Split-Phase Chunk Reordering

### Objective
Exploit quality history to move historically useful tools into chunk 1 and reduce extra LLM calls.

### File-level tasks

#### `backend/main.py`
When `affinity_route.confidence >= effective_config.aql_chunk_reorder_threshold` and split-phase is active:
- reorder the domain-narrowed tool list so affinity tools appear first.
- preserve relative order of non-affinity tools.
- keep chunk sizes unchanged.
- log moved tool names.

Suggested helper:

```python
def _reorder_tools_by_affinity(
    tools_for_llm: List[dict],
    preferred_tool_names: List[str],
) -> List[dict]: ...
```

#### `tests/backend/unit/test_main_runtime.py`
Add tests:
- `test_chunk_reorder_moves_affinity_tools_to_front_when_threshold_met`
- `test_chunk_reorder_preserves_non_affinity_order`
- `test_chunk_reorder_skips_when_confidence_below_threshold`
- `test_chunk_reorder_does_not_change_chunk_size`

#### `tests/backend/integration/test_chat_api.py`
Add scenario showing:
- first similar query takes 2 chunks,
- second similar query fronts high-yield tools in chunk 1,
- chunk 1 requests more useful tools than before.

### Deliverable
- Split-phase selection becomes progressively more efficient for recurring query shapes.

---

## 5. `backend/milvus_store.py` Notes

The spec assumes the existing Milvus abstraction already supports generic record upsert/search by collection key. If not, add thin wrappers:

```python
def upsert_quality_records(self, records: List[Dict[str, Any]]) -> Dict[str, Any]: ...
def search_quality_records(self, *, vector: List[float], limit: int, filter_expr: Optional[str] = None, output_fields: Optional[List[str]] = None) -> List[Dict[str, Any]]: ...
```

Prefer reusing the generic implementation rather than creating a parallel special-case path.

---

## 6. Logging Requirements by File

### `backend/main.py`
Must log:
- when correction patch is scheduled
- when quality record task is scheduled
- when affinity route is applied / skipped
- when chunk reorder is applied / skipped

### `backend/memory_service.py`
Must log:
- quality upsert start/end
- correction patch search + upsert result
- affinity lookup record count and confidence
- quality report aggregation counts
- freshness candidate counts

### `backend/milvus_store.py`
Must log:
- create collection / upsert / search / delete-by-filter for `tool_execution_quality`
  using existing START / END patterns

---

## 7. Test Case IDs

Use the following IDs in new tests:

| Area | IDs |
|------|-----|
| Quality recording | `TC-AQL-REC-01` … `TC-AQL-REC-05` |
| Correction detection | `TC-AQL-COR-01` … `TC-AQL-COR-04` |
| Affinity scoring | `TC-AQL-AFF-01` … `TC-AQL-AFF-06` |
| Admin endpoints | `TC-AQL-API-01` … `TC-AQL-API-04` |
| Routing integration | `TC-AQL-ROUTE-01` … `TC-AQL-ROUTE-05` |
| Chunk reorder | `TC-AQL-CHUNK-01` … `TC-AQL-CHUNK-04` |

Add IDs in test docstrings to match the repo’s existing testing style.

---

## 8. Rollout Checklist

### Passive rollout (Phases 1–4)
- [ ] Config fields added and validated
- [ ] New Milvus collection created on startup
- [ ] Quality writes succeed post-response
- [ ] Correction patching works
- [ ] Admin endpoints usable
- [ ] Snapshot logging includes quality rows
- [ ] Existing test suite passes

### Active routing rollout (Phases 5–7)
- [ ] Affinity route returns stable scores in unit tests
- [ ] Affinity route gated behind confidence threshold
- [ ] Direct route precedence preserved
- [ ] Chunk reorder only applies when threshold met
- [ ] Existing direct-route and split-phase integration tests still pass

---

## 9. Suggested Command Sequence

```bash
# Phase 1–2 focused validation
pytest tests/backend/unit/test_memory_service.py tests/backend/unit/test_main_runtime.py -q

# Endpoint + integration validation
pytest tests/backend/integration/test_chat_api.py -q

# Full regression
python -m pytest -q
```

---

## 10. Definition of Done

AQL implementation is complete when all of the following are true:
- all fields and endpoints described in the requirements exist,
- `tool_execution_quality_v1` is created and populated during live turns,
- correction follow-ups retroactively mark the prior record,
- admin endpoints return useful aggregates,
- affinity routing activates only under configured thresholds,
- split-phase chunk reordering works without changing existing chunk size logic,
- the full test suite passes with new AQL coverage added.
