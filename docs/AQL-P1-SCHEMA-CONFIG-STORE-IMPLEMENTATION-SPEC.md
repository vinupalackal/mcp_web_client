# AQL Phase 1 — Schema, Config, and Store Plumbing Implementation Spec

**Feature:** Adaptive Query Learning (AQL) — Phase 1  
**Application:** MCP Client Web  
**Date:** April 3, 2026  
**Status:** Implementation Ready  
**Requirements:** `docs/AQL-P1-SCHEMA-CONFIG-STORE-REQUIREMENTS.md`  
**HLD:** `docs/AQL-P1-SCHEMA-CONFIG-STORE-HLD.md`  
**Parent Spec:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-IMPLEMENTATION-SPEC.md`

---

## 1. Implementation Intent

This spec translates the AQL Phase 1 requirements into concrete file-level work.

Phase 1 must land as a **plumbing-only** change set. The implementation must prepare the codebase for later AQL phases while preserving all current runtime behavior.

---

## 2. Files Changed

| File | Change | Notes |
|------|--------|-------|
| `backend/models.py` | Update | Add AQL config fields and future admin response models |
| `backend/milvus_store.py` | Update | Add `tool_execution_quality` collection metadata and lifecycle support |
| `backend/main.py` | Update | Add env-default wiring, memory-service config wiring, and snapshot support |
| `backend/memory_service.py` | Update | Extend `MemoryServiceConfig` to accept AQL fields |
| `tests/backend/unit/test_main_runtime.py` | Update | Add config and snapshot-plumbing tests |
| `tests/backend/unit/test_memory_service.py` | Update | Add runtime config tests |

---

## 3. `backend/models.py` Changes

### 3.1 `MilvusConfig` field additions

Add the following fields exactly:

```python
enable_adaptive_learning: bool = Field(default=False, description="Enable Adaptive Query Learning (AQL).")
aql_quality_retention_days: int = Field(default=30, ge=1, le=365, description="Retention window for AQL quality records in days.")
aql_min_records_for_routing: int = Field(default=20, ge=1, le=1000, description="Minimum quality records required before affinity routing activates.")
aql_affinity_confidence_threshold: float = Field(default=0.65, ge=0.0, le=1.0, description="Minimum confidence required to apply affinity routing.")
aql_chunk_reorder_threshold: float = Field(default=0.70, ge=0.0, le=1.0, description="Minimum confidence required to reorder split-phase chunks.")
aql_affinity_weights: Dict[str, float] = Field(default_factory=lambda: {
    "similarity": 0.5,
    "success_rate": 0.3,
    "bypass_rate": -0.1,
    "corrected_penalty": -0.3,
}, description="Weight map used by AQL affinity scoring.")
aql_correction_patterns: List[str] = Field(default_factory=lambda: [
    r"\bwrong\b",
    r"\bincorrect\b",
    r"\bactually\b",
    r"\bnot right\b",
    r"\bthat's not\b",
    r"\bthat is not\b",
    r"\bnot what I\b",
    r"\bno[,.]\b",
], description="Regex patterns used to detect corrective follow-up messages.")
```

### 3.2 Validation / normalization

Extend the existing config validator to:
- strip blank correction patterns,
- fall back to default weights when an empty mapping is provided,
- ensure all required affinity weight keys are present even if the caller supplies a partial map.

Suggested helper logic:

```python
def _default_aql_affinity_weights() -> Dict[str, float]: ...
```

Then merge user-supplied weights into defaults.

### 3.3 Response models

Add:

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

These models are additive only; they are not wired to endpoints in Phase 1.

---

## 4. `backend/memory_service.py` Changes

### 4.1 `MemoryServiceConfig` additions

Add passive AQL config fields to the runtime dataclass:

```python
enable_adaptive_learning: bool = False
aql_quality_retention_days: int = 30
aql_min_records_for_routing: int = 20
aql_affinity_confidence_threshold: float = 0.65
aql_chunk_reorder_threshold: float = 0.70
aql_affinity_weights: Dict[str, float] = field(default_factory=lambda: {
    "similarity": 0.5,
    "success_rate": 0.3,
    "bypass_rate": -0.1,
    "corrected_penalty": -0.3,
})
aql_correction_patterns: Tuple[str, ...] = (
    r"\bwrong\b",
    r"\bincorrect\b",
    r"\bactually\b",
    r"\bnot right\b",
    r"\bthat's not\b",
    r"\bthat is not\b",
    r"\bnot what I\b",
    r"\bno[,.]\b",
)
```

No business logic may consume these fields yet.

---

## 5. `backend/milvus_store.py` Changes

### 5.1 Collection registry

Add a new collection entry for `tool_execution_quality` using the existing pattern for collection metadata / schema registration.

Expected physical collection name pattern:

```python
f"{collection_prefix}_tool_execution_quality_{generation}"
```

### 5.2 Schema fields

Add schema fields sufficient for later phases:
- `id`
- `vector`
- `query_hash`
- `domain_tags`
- `issue_type`
- `tools_selected`
- `tools_succeeded`
- `tools_failed`
- `tools_bypassed`
- `tools_cache_hit`
- `chunk_yields`
- `llm_turn_count`
- `synthesis_tokens`
- `routing_mode`
- `user_corrected`
- `follow_up_gap_s`
- `session_id`
- `timestamp`
- `expires_at`

If the store abstraction uses JSON-string fields for lists, keep that approach consistent.

### 5.3 Count and cleanup helpers

Update:
- collection-key validation
- record-count lookup
- any collection iteration utilities
- expiry cleanup loops / maps

to include `tool_execution_quality`.

No AQL-specific custom path should be introduced if the generic path already supports this.

---

## 6. `backend/main.py` Changes

### 6.1 `_default_milvus_config_from_env()`

Add env parsing for:

```python
enable_adaptive_learning = os.getenv("AQL_ENABLE", "false").lower() == "true"
aql_quality_retention_days = int(os.getenv("AQL_QUALITY_RETENTION_DAYS", "30"))
aql_min_records_for_routing = int(os.getenv("AQL_MIN_RECORDS", "20"))
aql_affinity_confidence_threshold = float(os.getenv("AQL_AFFINITY_THRESHOLD", "0.65"))
```

Use the repo’s existing env-parsing style; do not introduce a new parser helper unless the current module already abstracts this.

### 6.2 `_initialize_memory_service()`

Pass all AQL fields through to `MemoryServiceConfig`:

```python
enable_adaptive_learning=effective_config.enable_adaptive_learning,
aql_quality_retention_days=effective_config.aql_quality_retention_days,
aql_min_records_for_routing=effective_config.aql_min_records_for_routing,
aql_affinity_confidence_threshold=effective_config.aql_affinity_confidence_threshold,
aql_chunk_reorder_threshold=effective_config.aql_chunk_reorder_threshold,
aql_affinity_weights=dict(effective_config.aql_affinity_weights),
aql_correction_patterns=tuple(effective_config.aql_correction_patterns),
```

### 6.3 `_print_milvus_db_snapshot()`

Extend the collection loop / row-count lookup so `tool_execution_quality` appears in the snapshot when the memory subsystem is active.

No new endpoint or routing logic is added in Phase 1.

---

## 7. Tests

### 7.1 `tests/backend/unit/test_main_runtime.py`

Add tests:

```python
def test_default_milvus_config_from_env_parses_aql_fields(...): ...
def test_initialize_memory_service_passes_aql_config_fields(...): ...
def test_milvus_snapshot_includes_tool_execution_quality_count(...): ...
```

### 7.2 `tests/backend/unit/test_memory_service.py`

Add tests:

```python
def test_memory_service_config_accepts_aql_defaults(...): ...
def test_memory_service_config_accepts_custom_aql_values(...): ...
```

### 7.3 Optional model-focused test file

If the repo already has a dedicated models test file, it is acceptable to also add:

```python
def test_milvus_config_normalizes_aql_fields(...): ...
def test_quality_report_response_model_instantiates(...): ...
def test_freshness_candidates_response_model_instantiates(...): ...
```

---

## 8. Test IDs

Use the following IDs in docstrings:

| Area | IDs |
|------|-----|
| Config parsing | `TC-AQL-P1-CFG-01` … `TC-AQL-P1-CFG-03` |
| Store plumbing | `TC-AQL-P1-STORE-01` … `TC-AQL-P1-STORE-03` |
| Snapshot / counts | `TC-AQL-P1-DIAG-01` … `TC-AQL-P1-DIAG-02` |

---

## 9. Expected Outcome

After Phase 1:
- the app understands AQL configuration,
- the Milvus store knows how to manage `tool_execution_quality`,
- diagnostics can count and display the new collection,
- and no user-visible behavior has changed.

---

## 10. Validation Commands

```bash
source venv/bin/activate
pytest tests/backend/unit/test_main_runtime.py -q
pytest tests/backend/unit/test_memory_service.py -q
python -m pytest -q
```

Success means all new Phase 1 tests pass and the full regression suite remains green.
