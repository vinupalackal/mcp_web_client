# M1 Memory Config and Diagnostics HLD

**Feature:** M1 - Memory Config and Diagnostics Models  
**Application:** MCP Client Web  
**Date:** March 30, 2026  
**Status:** Design Ready  
**Related Issue:** #3  
**Parent Docs:** `Milvus_MCP_Integration_Requirements.md`, `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`

---

## 1. Executive Summary

This HLD defines the model-layer design for issue #3.

The purpose of this work is to introduce a small, explicit set of **Pydantic API models** in `backend/models.py` that can support future memory configuration, health, and diagnostics flows without altering existing public chat/session contracts.

The design keeps memory support optional and phase-safe:
- no new runtime dependencies are introduced,
- no existing request/response payloads are broken,
- and no Phase 2 / Phase 3 behavior is required.

---

## 2. Design Goals

1. Represent memory subsystem state in a structured, OpenAPI-friendly way.
2. Preserve existing `GET /health` core semantics.
3. Support future `/api/memory/*` diagnostics without redesigning models later.
4. Expose feature flags and config in a safe, non-secret-bearing form.
5. Keep the design additive and backward-compatible.

---

## 3. Component Delta

| Component | Change | Description |
|---|---|---|
| `backend/models.py` | Extended | Adds config, diagnostics, and ingestion status models for the memory subsystem |
| `backend/main.py` | Unchanged in this issue | May consume the new models later for health or diagnostics routes |
| `backend/memory_persistence.py` | Future consumer | Will later emit ingestion and collection diagnostic payloads |
| `backend/static/*` | Unchanged | No direct UI changes in this issue |

---

## 4. Model Families

### 4.1 Feature Flags Model

Represents effective feature toggles for the optional memory subsystem.

Suggested responsibilities:
- expose `enabled`, `retrieval_enabled`, `conversation_enabled`, `tool_cache_enabled`, `ingestion_enabled`, and `degraded_mode` flags,
- serve as a reusable nested object for diagnostics or admin endpoints,
- make phased rollout explicit.

### 4.2 Config Summary Model

Represents a safe, structured summary of effective memory configuration.

Suggested responsibilities:
- carry non-secret configuration values,
- include collection prefix, embedding provider/model, thresholds, limits, and retention,
- expose whether a Milvus URI is configured without echoing secrets directly.

### 4.3 Memory Status Model

Represents the top-level subsystem state.

Suggested responsibilities:
- use a constrained status enum/string such as `disabled`, `healthy`, `degraded`,
- expose a short status reason or warning list,
- summarize Milvus reachability and embedding availability,
- integrate cleanly into future health responses.

### 4.4 Collection Diagnostic Model

Represents active collection metadata.

Suggested responsibilities:
- describe collection key, version/generation, embedding metadata, and active flag,
- avoid exposing raw schema internals beyond what diagnostics need,
- support version-aware operations and admin visibility.

### 4.5 Ingestion Job Status Model

Represents ingestion job summaries.

Suggested responsibilities:
- expose job identifiers and status values,
- include counts and errors,
- expose timestamps and collection association.

---

## 5. Proposed Data Shape

### 5.1 Nested Structure

Recommended composition:

```text
MemoryDiagnosticsResponse
├── feature_flags: MemoryFeatureFlags
├── config: MemoryConfigSummary
├── status: MemoryStatus
├── collections: list[MemoryCollectionStatus]
└── ingestion_jobs: list[MemoryIngestionJobStatus]
```

This keeps the design modular:
- smaller models remain reusable,
- diagnostics can be partial when some data is unavailable,
- future endpoints can return subsets without redefining shape.

---

## 6. API Compatibility Strategy

### 6.1 Existing Health Contract

Current `HealthResponse` is minimal. Issue #3 should not require changing the existing health route contract immediately.

Preferred strategy:
- add memory-specific health/diagnostic models now,
- let a later implementation issue decide whether to extend `HealthResponse` or add a dedicated `/api/memory/health` response model,
- preserve backward compatibility for existing health consumers.

### 6.2 Optional Memory Endpoints

If memory-specific endpoints are later added, they should live under `/api/memory/*` and consume the new models without requiring another schema redesign.

---

## 7. Security and Exposure Rules

- Do not expose raw payload bodies in diagnostics models.
- Do not expose unmasked secrets such as full Milvus credentials or provider tokens.
- Prefer booleans, masked indicators, and summaries over raw connection strings.
- Warnings and reasons should be diagnostic, not secret-bearing.

---

## 8. Failure and Degraded-State Modeling

The model layer must explicitly support:
- memory disabled by configuration,
- memory enabled but Milvus unreachable,
- embedding provider unavailable,
- partial diagnostics available with some unknown fields.

Recommended approach:
- nullable nested details,
- clear `status` field,
- optional `warnings` list,
- optional `reason` string.

---

## 9. Implementation Notes

- Follow current `backend/models.py` style with `Field` descriptions and `ConfigDict` examples.
- Use explicit `Literal[...]` where status/flag values are bounded.
- Keep examples realistic and aligned with the env vars defined in the requirements doc.
- Avoid coupling these models to SQLAlchemy rows directly.

---

## 10. Validation

- `pytest tests/backend/unit/test_models.py -q`
- `pytest tests/backend/ -q`
- Confirm models appear correctly in generated OpenAPI when later wired into endpoints.
