# M1 Memory Persistence Adapter HLD

**Feature:** M1 - Memory Persistence Adapter  
**Application:** MCP Client Web  
**Date:** March 30, 2026  
**Status:** Design Ready  
**Related Issue:** #5  
**Parent Docs:** `Milvus_MCP_Integration_Requirements.md`, `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`

---

## 1. Executive Summary

This HLD defines the design for issue #5.

The purpose of this work is to introduce a focused persistence adapter that sits between future memory modules and the SQLAlchemy sidecar schema, so higher-level code can perform stable payload/job/provenance operations without open-coding session and ORM logic everywhere.

The design keeps persistence support phase-safe:
- no retrieval or ingestion orchestration is wired in this issue,
- no frontend or public API contract changes are required,
- and only the existing SQLAlchemy database layer is used.

---

## 2. Design Goals

1. Wrap sidecar-table access in one focused backend module.
2. Make payload-ref resolution stable and straightforward for future Milvus records.
3. Support collection-generation activation semantics explicitly.
4. Keep testability high by allowing session-factory injection.
5. Preserve SQLite-friendly behavior for local development and tests.

---

## 3. Component Delta

| Component | Change | Description |
|---|---|---|
| `backend/memory_persistence.py` | New | Adapter around payload refs, ingestion jobs, collection versions, and retrieval provenance |
| `tests/backend/unit/test_memory_persistence.py` | New | Focused coverage for adapter behavior |
| `backend/database.py` | Reused | Provides the ORM rows introduced by issue #2 |
| `backend/main.py` | Unchanged in this issue | Future consumer only |

---

## 4. Proposed Structure

### 4.1 Adapter Boundary

Recommended composition:

```text
MemoryPersistence
├── upsert/get payload refs
├── create/update/get ingestion jobs
├── create/list/activate collection versions
└── record/list retrieval provenance
```

The adapter should expose small, purpose-specific methods instead of a generic CRUD abstraction.

### 4.2 Session Strategy

The adapter should default to using `backend.database.SessionLocal`, while allowing a session factory to be injected for tests.

This keeps the module:
- easy to test with in-memory SQLite,
- aligned with current repo patterns,
- and decoupled from global DB state where needed.

### 4.3 JSON Field Handling

Several sidecar columns are stored as JSON text (`metadata_json`, `scope_json`, `schema_json`, `selected_refs_json`, `rationale_json`).

Recommended adapter behavior:
- accept either Python dict/list structures or already-serialized strings,
- normalize them to JSON strings on write,
- and return ORM rows with stored values intact.

---

## 5. Collection Activation Semantics

Collection version activation is the most stateful behavior in this issue.

Recommended activation behavior:
- select all versions for a `collection_key`,
- set the target `version_id` active,
- set all others inactive,
- populate `activated_at` on the newly active row if not already set,
- and optionally populate `retired_at` for rows that were previously active and are being superseded.

This makes generation switches explicit and auditable.

---

## 6. Failure Modeling

The adapter should fail clearly for:
- missing required identifiers (such as unknown `payload_ref` or `job_id` when updating),
- malformed JSON-serializable inputs,
- and attempts to activate a non-existent collection version.

Preferred behavior:
- raise `ValueError` for caller/input mistakes,
- avoid silently creating ambiguous state,
- and keep DB-layer exceptions visible when they indicate real persistence problems.

---

## 7. Validation

- `pytest tests/backend/unit/test_memory_persistence.py -q`
- `pytest tests/backend/unit/test_database.py -q`
- `pytest tests/backend/ -q`

Primary verification goals:
- payload refs round-trip cleanly,
- job status updates persist,
- collection activation behaves deterministically,
- retrieval provenance rows are recorded as expected.