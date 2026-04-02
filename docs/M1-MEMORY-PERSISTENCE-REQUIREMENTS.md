# M1 Memory Persistence Adapter Requirements

**Feature:** M1 - Memory Persistence Adapter  
**Application:** MCP Client Web  
**Date:** March 30, 2026  
**Related Issue:** #5  
**Target Files:** `backend/memory_persistence.py`, `tests/backend/unit/test_memory_persistence.py`

---

## 1. Purpose

This document defines the issue-level requirements for M1 issue #5: adding a **memory persistence adapter** that wraps the new SQLAlchemy sidecar tables introduced for Milvus integration.

This issue prepares the backend for:
- durable payload-ref resolution,
- ingestion-job status tracking,
- collection generation activation metadata,
- and retrieval provenance persistence,

without forcing future Milvus or retrieval code to manipulate ORM rows directly.

This issue is limited to the adapter layer and its tests. It does not require Milvus search, ingestion parsing, or chat-path retrieval integration.

---

## 2. Scope

### In Scope

- Add `backend/memory_persistence.py` as a focused adapter over `backend/database.py` sidecar tables.
- Persist and resolve payload references.
- Create and update ingestion-job records.
- Persist collection version metadata and activate a chosen generation.
- Persist retrieval provenance summaries.
- Support SQLite development mode cleanly.
- Add focused unit tests for all core adapter responsibilities.

### Out of Scope

- Milvus collection CRUD.
- Ingestion orchestration.
- Retrieval orchestration.
- Conversation-memory persistence.
- Tool-cache audit persistence.

---

## 3. Requirements Mapping

| ID | Requirement | How this issue addresses it |
|---|---|---|
| DATA-02 | Payload references stored in Milvus must resolve to a durable backing store. | Adapter provides payload-ref upsert and lookup helpers. |
| DATA-03 | Audit records for ingestion jobs, cache decisions, and retrieval provenance should use the existing SQLAlchemy-backed database layer where practical. | Adapter centralizes writes to ingestion-job and retrieval-provenance tables. |
| DATA-04 | Embedding/index version must be tracked per collection generation. | Adapter persists collection generation/version metadata. |
| DATA-05 | Multiple collection generations may coexist while one is marked active. | Adapter supports activating one generation and retiring prior active rows for a collection key. |
| FR-RET-07 | The system must record retrieval provenance, including which chunks were selected and why. | Adapter records provenance rows with selected refs and rationale summaries. |
| ALN-06 | Existing SQLAlchemy DB layer should be reused instead of adding a second persistence stack. | Adapter is built directly on `backend/database.py` and `SessionLocal`. |
| NFR-MAIN-01 | New memory functionality must be implemented as focused modules. | Persistence logic is isolated in `backend/memory_persistence.py`. |

---

## 4. Required Capabilities

### 4.1 Payload Reference Persistence

The adapter must:
- create or update payload-ref rows,
- preserve the stable `payload_ref` identifier,
- and allow callers to resolve a `payload_ref` back to its durable payload record.

### 4.2 Ingestion Job Tracking

The adapter must support:
- creating ingestion jobs,
- updating status/count/error fields,
- and retrieving job state for later diagnostics.

### 4.3 Collection Version Metadata

The adapter must support:
- persisting collection generation metadata,
- listing collection versions,
- and marking one generation active for a logical collection key while deactivating prior active rows.

### 4.4 Retrieval Provenance Recording

The adapter must support recording request-level provenance including:
- request/session/user/repo scope,
- selected refs,
- and rationale summaries.

---

## 5. Design Constraints

- Keep the adapter additive and independent from chat/session contracts.
- Use the existing SQLAlchemy session factory and ORM row definitions.
- Keep JSON-bearing fields easy for callers to pass as dict/list or pre-serialized string where practical.
- Preserve SQLite compatibility and predictable behavior in tests.

---

## 6. Acceptance Criteria

- `backend/memory_persistence.py` exists and wraps the sidecar tables.
- Payload refs can be stored and resolved by stable identifier.
- Ingestion jobs can be created and updated.
- Collection versions can be stored and activated cleanly.
- Retrieval provenance can be recorded.
- Focused persistence tests pass.
- Existing backend regression remains green.

---

## 7. Validation

```bash
source venv/bin/activate
pytest tests/backend/unit/test_memory_persistence.py -q
pytest tests/backend/unit/test_database.py -q
pytest tests/backend/ -q
```