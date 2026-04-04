# AQL Phase 1 — Schema, Config, and Store Plumbing HLD

**Feature:** Adaptive Query Learning (AQL) — Phase 1  
**Application:** MCP Client Web  
**Date:** April 3, 2026  
**Status:** Design Ready  
**Parent Docs:** `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`, `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`

---

## 1. Executive Summary

Phase 1 introduces the structural foundation for Adaptive Query Learning (AQL) without activating any learning behavior.

This phase adds three things:
1. **Configuration surface** — AQL flags and thresholds become part of `MilvusConfig` and runtime memory-service config.
2. **Persistence schema** — Milvus learns a new collection key, `tool_execution_quality`, and the concrete backing collection `mcp_client_tool_execution_quality_v1`.
3. **Store diagnostics plumbing** — row counts, snapshot printing, and expiry-cleanup support include the new collection.

The design is intentionally passive. No new routing path, no quality-record writes, and no user-visible behavior changes are introduced in Phase 1.

---

## 2. Design Goals

1. Prepare the codebase for later AQL phases without revisiting config or store plumbing.
2. Keep AQL disabled by default.
3. Preserve all current chat, cache, and routing behavior.
4. Reuse the existing Milvus collection-management and diagnostics patterns.
5. Keep startup and degraded-mode behavior consistent with the current memory subsystem.

---

## 3. Component Delta

| Component | Change | Description |
|---|---|---|
| `backend/models.py` | Extended | Adds AQL config fields and admin report response models |
| `backend/milvus_store.py` | Extended | Adds `tool_execution_quality` collection metadata and lifecycle support |
| `backend/main.py` | Extended | Wires env defaults, memory-service config plumbing, and snapshot support |
| `backend/memory_service.py` | Constructor/config only | Accepts AQL config values now, business logic later |
| `tests/backend/unit/test_main_runtime.py` | Extended | Covers env/config/store-plumbing behavior |
| `tests/backend/unit/test_memory_service.py` | Extended | Covers runtime config initialization |

---

## 4. Configuration Design

### 4.1 `MilvusConfig` Additions

Phase 1 adds the following configuration fields:

```text
MilvusConfig
├── enable_adaptive_learning: bool = False
├── aql_quality_retention_days: int = 30
├── aql_min_records_for_routing: int = 20
├── aql_affinity_confidence_threshold: float = 0.65
├── aql_chunk_reorder_threshold: float = 0.70
├── aql_affinity_weights: Dict[str, float]
└── aql_correction_patterns: List[str]
```

These are added now because later AQL phases depend on them, and Phase 1 is the safest point to establish the schema and validation contract.

### 4.2 Runtime Config Flow

Configuration flows through the existing memory initialization path:

```text
Environment variables
        │
        ▼
_default_milvus_config_from_env()
        │
        ▼
MilvusConfig (Pydantic)
        │
        ▼
_initialize_memory_service()
        │
        ▼
MemoryServiceConfig (runtime dataclass)
```

No business logic consumes the AQL values yet. The goal is simply to make them available.

---

## 5. Milvus Store Design

### 5.1 New Collection Key

Phase 1 adds a new logical collection key:

```text
tool_execution_quality
```

This key must integrate into the same internal registry / abstraction layer used by:
- `code_memory`
- `doc_memory`
- `conversation_memory`
- `tool_cache`

### 5.2 Physical Collection

The physical collection name follows the existing naming convention:

```text
mcp_client_tool_execution_quality_v1
```

### 5.3 Schema Intent

The schema is designed for **future** AQL writes and ANN lookup, so it must be fully defined in Phase 1 even though no records are written yet.

Suggested field groups:
- **Identity**: `id`, `query_hash`, `session_id`
- **Vector**: `vector` (4096-d embedding)
- **Routing metadata**: `domain_tags`, `issue_type`, `routing_mode`
- **Tool outcome arrays**: `tools_selected`, `tools_succeeded`, `tools_failed`, `tools_bypassed`, `tools_cache_hit`
- **Execution metrics**: `chunk_yields`, `llm_turn_count`, `synthesis_tokens`, `follow_up_gap_s`
- **Learning label**: `user_corrected`
- **Lifecycle**: `timestamp`, `expires_at`

### 5.4 Reuse Strategy

Phase 1 must reuse generic Milvus store primitives wherever possible:
- collection create/init
- generic upsert path
- generic search path
- generic count path
- generic delete-by-filter path

No special-case AQL store class is introduced.

---

## 6. Diagnostics and Snapshot Design

### 6.1 Row Counts

The existing row-count and snapshot helper is extended to include:

```text
tool_execution_quality
```

### 6.2 Snapshot Output

The Milvus DB snapshot block should eventually render like:

```text
┌─── MILVUS DATABASE SNAPSHOT ─── AFTER QUERY  request_id=...
│  code_memory                               0 rows
│  doc_memory                                0 rows
│  conversation_memory                      12 rows
│  tool_cache                                3 rows
│  tool_execution_quality                    0 rows
└────────────────────────────────────────────────────────────────
```

Phase 1 only guarantees the snapshot helper knows about this collection and can count it when present.

### 6.3 Expiry Cleanup Readiness

Even though Phase 1 writes no quality records, the collection must be wired for the same expiry-cleanup pattern used elsewhere:
- delete-by-filter on `expires_at < now`
- log START / END boundaries
- degrade safely if Milvus is unavailable

---

## 7. API Model Design

Phase 1 introduces only schema-layer readiness for later admin endpoints. It adds response models for:
- per-tool frequency stats,
- freshness candidates,
- quality-report summaries.

No endpoints are added in Phase 1; only models are created so later phases can expose them without reopening the schema contract.

---

## 8. Compatibility Strategy

### 8.1 Backward Compatibility

Phase 1 must not:
- modify existing request/response contracts,
- alter chat/session endpoint behavior,
- change current direct-route, memory-route, or split-phase logic,
- or enable any new feature by default.

### 8.2 Degraded Mode Compatibility

If Milvus is disabled or unavailable, the new collection should follow the same degraded-mode rules as the rest of the memory subsystem. No special failure path is introduced.

---

## 9. Implementation Notes

- Follow existing `backend/models.py` style using `Field(...)` descriptions and examples where useful.
- Keep `aql_affinity_weights` normalized and predictable so later phases can read it without branching on missing keys.
- Use the same collection-prefix + generation naming strategy already used elsewhere.
- Prefer extending current registries and helpers over introducing separate AQL-specific plumbing.

---

## 10. Validation

Phase 1 is successful when:
- app startup accepts AQL config fields,
- the new collection key is recognized,
- collection creation/count/snapshot plumbing includes `tool_execution_quality`,
- and the full regression suite still passes with no behavior change.
