# AQL Phase 1 — Schema, Config, and Store Plumbing Requirements

**Feature:** Adaptive Query Learning (AQL) — Phase 1  
**Application:** MCP Client Web  
**Date:** April 3, 2026  
**Status:** Requirements Ready  
**Parent Requirements:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`  
**Parent HLD:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`  
**Parent Implementation Spec:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-IMPLEMENTATION-SPEC.md`

---

## 1. Purpose

This document defines the detailed requirements for **Phase 1** of Adaptive Query Learning (AQL): adding the schema, configuration, and Milvus store plumbing needed to support later AQL phases.

Phase 1 is intentionally **non-behavioral**. It introduces the configuration surface, persistence schema, and startup/store hooks required by later phases, but it must not change routing decisions, cache behavior, tool execution, or user-visible chat responses.

---

## 2. Scope

### In Scope

- Add AQL configuration fields to `MilvusConfig` in `backend/models.py`.
- Add AQL-related admin response models in `backend/models.py`.
- Add Milvus store support for a new collection key: `tool_execution_quality`.
- Define and create the backing Milvus collection `mcp_client_tool_execution_quality_v1`.
- Extend row-count and snapshot plumbing so the new collection can be counted and displayed.
- Extend expiry-cleanup plumbing so the new collection can be cleaned by `expires_at` in later phases.
- Extend environment-default config builders so AQL settings can be populated from env vars.
- Pass AQL config fields into `MemoryServiceConfig` during memory-service initialization.

### Out of Scope

- Writing any quality records.
- Reading quality records for routing.
- Correction detection.
- Affinity scoring.
- Split-phase chunk reordering.
- New routing paths or behavior changes.
- New admin report business logic beyond model/schema readiness.

---

## 3. Functional Requirements

### FR-AQL-P1-01 — Config fields in `MilvusConfig`
`backend/models.py` shall add the following fields to `MilvusConfig`:
- `enable_adaptive_learning: bool = False`
- `aql_quality_retention_days: int = 30`
- `aql_min_records_for_routing: int = 20`
- `aql_affinity_confidence_threshold: float = 0.65`
- `aql_chunk_reorder_threshold: float = 0.70`
- `aql_affinity_weights: Dict[str, float]`
- `aql_correction_patterns: List[str]`

### FR-AQL-P1-02 — Field validation
The new `MilvusConfig` fields shall enforce safe bounds:
- retention days ≥ 1
- min records ≥ 1
- thresholds within `[0.0, 1.0]`
- correction patterns exclude blank strings
- affinity weight map falls back to defaults when omitted or empty

### FR-AQL-P1-03 — Admin response models
`backend/models.py` shall define additive, OpenAPI-friendly response models for:
- quality report summary
- freshness candidate summary
- per-tool frequency stats

### FR-AQL-P1-04 — New Milvus collection key
`backend/milvus_store.py` shall accept `tool_execution_quality` as a valid collection key alongside:
- `code_memory`
- `doc_memory`
- `conversation_memory`
- `tool_cache`

### FR-AQL-P1-05 — Collection creation
On startup / initialization, the Milvus store shall create the physical collection for the new key using:
- existing embedding dimension (4096)
- a vector field for query embeddings
- scalar fields needed by later phases (`query_hash`, `domain_tags`, `issue_type`, `tools_selected`, `tools_succeeded`, `tools_failed`, `tools_bypassed`, `tools_cache_hit`, `chunk_yields`, `llm_turn_count`, `synthesis_tokens`, `routing_mode`, `user_corrected`, `follow_up_gap_s`, `session_id`, `timestamp`, `expires_at`)

### FR-AQL-P1-06 — Store row counts
The Milvus store row-count logic shall include the `tool_execution_quality` collection so admin diagnostics and debug snapshots can report its size.

### FR-AQL-P1-07 — Expiry-cleanup readiness
The Milvus delete-by-filter / expiry-cleanup plumbing shall accept the `tool_execution_quality` collection key and support future cleanup by `expires_at`, even if no records are written yet.

### FR-AQL-P1-08 — Environment defaults
`backend/main.py` shall extend `_default_milvus_config_from_env()` to support:
- `AQL_ENABLE`
- `AQL_QUALITY_RETENTION_DAYS`
- `AQL_MIN_RECORDS`
- `AQL_AFFINITY_THRESHOLD`

Phase 1 does not require env vars for every AQL field; only the baseline activation and thresholds listed above are required.

### FR-AQL-P1-09 — Memory service initialization
`backend/main.py` shall pass all new AQL fields into the runtime `MemoryServiceConfig` during `_initialize_memory_service()` so later phases do not require another config-plumbing pass.

### FR-AQL-P1-10 — Snapshot visibility
The Milvus DB snapshot helper shall display `tool_execution_quality` row counts when the collection exists.

### FR-AQL-P1-11 — No runtime behavior change
Phase 1 shall not:
- write any quality records,
- change route selection,
- change tool-cache decisions,
- change split-phase tool selection,
- or add any new user-visible API behavior.

---

## 4. Non-Functional Requirements

### NFR-AQL-P1-01 — Additive only
Phase 1 changes shall be additive and must not break existing models, OpenAPI schemas, or endpoint contracts.

### NFR-AQL-P1-02 — Startup-safe
If the new collection cannot be created, the failure must degrade consistently with the existing memory subsystem behavior and must not crash the core application when memory is optional / degraded.

### NFR-AQL-P1-03 — Logging consistency
All new Milvus collection create / search / count / delete-by-filter support for `tool_execution_quality` shall follow the existing dual-logger pattern.

### NFR-AQL-P1-04 — No new dependencies
Phase 1 shall reuse existing Milvus, Pydantic, and FastAPI infrastructure. No new third-party packages are introduced.

### NFR-AQL-P1-05 — Testability
All Phase 1 changes shall be unit-testable without a live Milvus server.

---

## 5. Constraints and Assumptions

- The embedding dimension remains 4096 and is reused for the new collection.
- `tool_execution_quality` is introduced as a collection key only; business semantics are implemented in later phases.
- AQL remains disabled by default.
- Existing memory initialization may already run in degraded mode; Phase 1 must respect that pattern.

---

## 6. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-AQL-P1-01 | `MilvusConfig` includes all required AQL fields with defaults and validation |
| AC-AQL-P1-02 | New response models import cleanly and are OpenAPI-ready |
| AC-AQL-P1-03 | `tool_execution_quality` is accepted as a valid Milvus collection key |
| AC-AQL-P1-04 | The new Milvus collection is created with the expected schema |
| AC-AQL-P1-05 | Row-count logic includes `tool_execution_quality` |
| AC-AQL-P1-06 | Expiry-cleanup plumbing accepts `tool_execution_quality` |
| AC-AQL-P1-07 | Env defaults populate AQL config fields correctly |
| AC-AQL-P1-08 | `_initialize_memory_service()` passes AQL config into runtime config |
| AC-AQL-P1-09 | Snapshot logging includes `tool_execution_quality` when present |
| AC-AQL-P1-10 | Existing routing and chat behavior remain unchanged after Phase 1 |

---

## 7. Validation

```bash
source venv/bin/activate
pytest tests/backend/unit/test_main_runtime.py -q
pytest tests/backend/unit/test_memory_service.py -q
python -m pytest -q
```

Validation expectations:
- new config fields validate cleanly,
- store plumbing accepts the new collection key,
- startup and row-count logic remain green,
- and the existing full regression suite still passes.
