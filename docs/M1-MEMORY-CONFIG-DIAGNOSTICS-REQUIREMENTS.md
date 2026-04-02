# M1 Memory Config and Diagnostics Requirements

**Feature:** M1 - Memory Config and Diagnostics Models  
**Application:** MCP Client Web  
**Date:** March 30, 2026  
**Related Issue:** #3  
**Target File:** `backend/models.py`

---

## 1. Purpose

This document defines the issue-level requirements for M1 issue #3: adding **Pydantic models** for memory configuration, health/diagnostics, and ingestion/admin status payloads.

These models are the schema layer that prepares the backend for:
- memory feature flag exposure,
- additive health reporting,
- optional `/api/memory/*` diagnostics,
- and structured ingestion status payloads.

This issue is limited to model definitions. It does not require full endpoint implementation or runtime memory orchestration.

---

## 2. Scope

### In Scope

- Add a memory subsystem status model or equivalent health/diagnostic model.
- Add models for memory feature flags and effective configuration if surfaced through API.
- Add models for ingestion job diagnostics/status summaries.
- Add optional diagnostics models for embedding provider, Milvus connectivity, and collection activation state.
- Keep the OpenAPI schema valid and aligned with current FastAPI model conventions.

### Out of Scope

- Full endpoint implementation for `/api/memory/*`.
- Milvus client connectivity logic.
- Embedding request execution.
- Retrieval orchestration or prompt injection.
- Conversation-memory and tool-cache diagnostics beyond placeholder readiness.

---

## 3. Requirements Mapping

| ID | Requirement | How this issue addresses it |
|---|---|---|
| FR-CFG-01 | Memory features must be disabled by default | Models must represent disabled/default state clearly |
| FR-CFG-02 | App behavior remains unchanged when memory is disabled | Models must be additive and optional |
| FR-CFG-03 | Degraded mode must be representable when Milvus is unreachable | Diagnostics models must encode `disabled`, `healthy`, or `degraded` |
| FR-CFG-04 | Health reporting must expose memory subsystem status | Add `MemoryStatus` / diagnostics response model |
| FR-CFG-05 | Embedding configuration must be explicit and independent | Config models must include embedding provider/model fields |
| FR-CFG-06 | Retrieval, conversation memory, tool cache, and ingestion must be independently toggleable | Feature-flag model must expose independent booleans |
| API-03 | `GET /health` must preserve core app health semantics | New models must extend health reporting without breaking current contracts |
| API-04 | Optional memory endpoints should live under `/api/memory/*` | Models should be usable by future memory-specific endpoints |
| FR-OPS-04 | Health should report Milvus and embedding availability without collapsing core health | Diagnostics models must separate subsystem state from core app status |
| FR-SEC-05 | Diagnostics endpoints must not expose raw sensitive payloads by default | Models must expose summaries/status rather than raw payload contents |
| CFG-01 | Invalid memory enablement without Milvus URI should be representable | Config/diagnostics models should carry validation or warning fields |
| CFG-04 | Feature flags must be independently controllable | Flags model must not collapse memory controls into a single boolean only |

---

## 4. Required Model Categories

### 4.1 Memory Feature Flags

Represents effective feature enablement state for:
- master memory enablement,
- retrieval,
- conversation memory,
- tool cache,
- ingestion,
- degraded mode.

### 4.2 Memory Configuration Summary

Represents a safe, structured view of effective memory configuration for diagnostics/admin APIs, including:
- Milvus URI presence or masked indicator,
- collection prefix,
- embedding provider/model,
- thresholds,
- result limits,
- retention days,
- repo/doc roots summary.

### 4.3 Memory Status / Health Diagnostics

Represents memory subsystem status using explicit states such as:
- `disabled`
- `healthy`
- `degraded`

And should optionally include:
- status reason,
- Milvus reachability,
- embedding provider status,
- active collection metadata,
- warnings.

### 4.4 Ingestion Job Diagnostics

Represents structured ingestion job state, including:
- job identifier,
- status,
- collection key,
- counts,
- error summary,
- timestamps.

### 4.5 Collection Diagnostics Summary

Represents currently active or known collection versions without exposing raw vector payloads, including:
- collection key,
- collection name,
- generation,
- embedding model/provider,
- embedding dimension,
- active flag.

---

## 5. Design Constraints

- New models must be backward-compatible with current API contracts.
- New models must follow existing `backend/models.py` conventions:
  - `Field(...)` descriptions,
  - `ConfigDict` examples,
  - explicit typing,
  - OpenAPI-ready schemas.
- Avoid exposing secrets or full raw payloads in diagnostic responses.
- Keep models phase-safe: conversation memory and tool cache may appear as flags/status fields but not require Phase 2/3 runtime behavior.

---

## 6. Acceptance Criteria

- `backend/models.py` contains memory config and diagnostics model definitions.
- New models are additive and do not break existing OpenAPI-backed payloads.
- Health/diagnostics models support `disabled`, `healthy`, and `degraded` semantics.
- Feature-flag models support independently toggleable memory capabilities.
- Ingestion job status has a structured response model.
- Tests validate the new models and existing model tests continue to pass.

---

## 7. Validation

```bash
source venv/bin/activate
pytest tests/backend/unit/test_models.py -q
pytest tests/backend/ -q
```

Validation expectations:
- new models import cleanly,
- examples and validation rules are accepted by Pydantic,
- existing model tests remain green,
- backend regression remains green.
