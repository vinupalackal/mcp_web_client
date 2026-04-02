# M1 Memory Config and Diagnostics Implementation Spec

**Feature:** M1 - Memory Config and Diagnostics Models  
**Application:** MCP Client Web  
**Date:** March 30, 2026  
**Related Issue:** #3  
**Primary File:** `backend/models.py`

---

## 1. Implementation Intent

This document translates the issue-level requirements and HLD for issue #3 into a practical implementation spec for `backend/models.py`.

The objective is to add the minimum useful set of models that later memory health/admin endpoints can reuse without revisiting the model structure.

---

## 2. Target Additions

### 2.1 `MemoryFeatureFlags`

Suggested fields:
- `enabled: bool`
- `retrieval_enabled: bool`
- `conversation_enabled: bool`
- `tool_cache_enabled: bool`
- `ingestion_enabled: bool`
- `degraded_mode: bool`

Purpose:
- represent effective toggle state,
- keep feature rollout explicit,
- reuse inside diagnostics responses.

### 2.2 `MemoryConfigSummary`

Suggested fields:
- `milvus_uri_configured: bool`
- `collection_prefix: str`
- `embedding_provider: Optional[str]`
- `embedding_model: Optional[str]`
- `max_code_results: int`
- `max_doc_results: int`
- `max_conversation_results: int`
- `code_threshold: float`
- `doc_threshold: float`
- `conversation_threshold: float`
- `retention_days: int`
- `repo_roots: List[str]`
- `doc_roots: List[str]`

Purpose:
- expose effective configuration safely,
- avoid returning raw secrets,
- provide structured admin/diagnostic visibility.

### 2.3 `MemoryStatus`

Suggested fields:
- `status: Literal["disabled", "healthy", "degraded"]`
- `reason: Optional[str]`
- `warnings: List[str]`
- `milvus_reachable: Optional[bool]`
- `embedding_available: Optional[bool]`

Purpose:
- represent subsystem health explicitly,
- support future `GET /health` integration or `/api/memory/health`.

### 2.4 `MemoryCollectionStatus`

Suggested fields:
- `collection_key: str`
- `collection_name: str`
- `generation: str`
- `embedding_provider: Optional[str]`
- `embedding_model: Optional[str]`
- `embedding_dimension: Optional[int]`
- `index_version: Optional[str]`
- `is_active: bool`

Purpose:
- summarize currently known collection versions,
- support diagnostics and version awareness.

### 2.5 `MemoryIngestionJobStatus`

Suggested fields:
- `job_id: str`
- `job_type: str`
- `status: str`
- `collection_key: Optional[str]`
- `repo_id: Optional[str]`
- `source_count: int`
- `chunk_count: int`
- `error_count: int`
- `error_summary: Optional[str]`
- `started_at: Optional[datetime]`
- `finished_at: Optional[datetime]`
- `updated_at: Optional[datetime]`

Purpose:
- expose ingestion diagnostics in a structured way,
- map cleanly from `memory_ingestion_jobs` rows later.

### 2.6 `MemoryDiagnosticsResponse`

Suggested fields:
- `feature_flags: MemoryFeatureFlags`
- `config: MemoryConfigSummary`
- `status: MemoryStatus`
- `collections: List[MemoryCollectionStatus]`
- `ingestion_jobs: List[MemoryIngestionJobStatus]`

Purpose:
- define a future-ready aggregate diagnostics payload,
- avoid repeatedly composing ad hoc dictionaries in later issues.

---

## 3. Pydantic Conventions

Each new model should:
- use `Field(..., description=...)` for all public fields,
- include `ConfigDict(json_schema_extra={...})` example payloads where useful,
- use bounded `Literal` values for status enums where stable,
- prefer explicit list defaults via `default_factory=list` when mutable,
- avoid one-off validators unless a real invariant is needed.

---

## 4. Backward Compatibility Rules

- Do not rename or change existing public models in this issue.
- Do not modify existing `HealthResponse` contract yet unless absolutely necessary.
- Keep the new models independent so later routes can opt into them gradually.

---

## 5. Recommended Test Coverage

Add or update tests in `tests/backend/unit/test_models.py` to validate:
- default values,
- accepted status literals,
- example-safe instantiation,
- nested diagnostics response creation,
- backward compatibility of existing models.

---

## 6. Expected Outcome

After this issue:
- `backend/models.py` has a complete model set for memory config and diagnostics,
- later issues can add endpoints or health integration with minimal schema churn,
- current API behavior remains unchanged unless explicitly extended later.

---

## 6.1 How To See The Before / After Difference

Issue `#3` is a **model-layer change**, so the difference is easiest to see in code, tests, and future OpenAPI readiness rather than in the UI.

### Before Issue #3

In `backend/models.py`, the repository had:
- existing user/auth/settings models,
- existing chat and tool-related request/response models,
- a minimal `HealthResponse`,
- no dedicated memory config model family,
- no dedicated memory diagnostics response model,
- no dedicated ingestion-job diagnostics model for memory features.

### After Issue #3

In `backend/models.py`, the repository now includes additive memory-focused models:
- `MemoryFeatureFlags`
- `MemoryConfigSummary`
- `MemoryStatus`
- `MemoryCollectionStatus`
- `MemoryIngestionJobStatus`
- `MemoryDiagnosticsResponse`

These additions prepare the API/model layer for future memory health and diagnostics work without changing existing chat contracts.

### Where To Look In The Repo

To inspect the implementation delta directly:

1. Open `backend/models.py`
	- Look for the new `Memory*` model classes near the health/response model section.
2. Open `tests/backend/unit/test_models.py`
	- Look for the new tests covering defaults, status literals, thresholds, and aggregate diagnostics payload construction.
3. Open the issue-specific docs:
	- `docs/M1-MEMORY-CONFIG-DIAGNOSTICS-REQUIREMENTS.md`
	- `docs/M1-MEMORY-CONFIG-DIAGNOSTICS-HLD.md`
	- `docs/M1-MEMORY-CONFIG-DIAGNOSTICS-IMPLEMENTATION-SPEC.md`

### How To Verify Locally

Run the focused model tests:

```bash
source venv/bin/activate
pytest tests/backend/unit/test_models.py -q
```

Run the backend regression suite:

```bash
source venv/bin/activate
pytest tests/backend/ -q
```

### What You Will See vs What You Will Not See

You **will** see:
- new Pydantic model classes in `backend/models.py`,
- new unit tests in `tests/backend/unit/test_models.py`,
- issue `#3` docs and tracker updates.

You **will not** see yet:
- a UI change,
- a new visible frontend control,
- a changed public chat contract,
- or a new memory diagnostics page.

Those will come only when later issues wire these models into actual endpoints and runtime memory behavior.

---

## 7. Validation Commands

```bash
source venv/bin/activate
pytest tests/backend/unit/test_models.py -q
pytest tests/backend/ -q
```
