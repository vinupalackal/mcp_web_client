# M1 Memory Persistence Adapter Implementation Spec

**Feature:** M1 - Memory Persistence Adapter  
**Application:** MCP Client Web  
**Date:** March 30, 2026  
**Related Issue:** #5  
**Primary File:** `backend/memory_persistence.py`

---

## 1. Implementation Intent

This document translates the issue-level requirements and HLD for issue #5 into a practical implementation spec for the repository.

The objective is to add the minimum useful persistence adapter that later ingestion and retrieval work can call without manipulating sidecar ORM tables directly throughout the codebase.

---

## 2. Target Additions

### 2.1 `MemoryPersistence`

Suggested responsibilities:
- accept an optional session factory,
- write and resolve payload refs,
- create and update ingestion jobs,
- persist collection versions and activate one generation,
- record retrieval provenance summaries.

### 2.2 JSON Normalization Helpers

The module should include small helpers that:
- accept Python dict/list structures,
- serialize them for JSON text columns,
- and avoid duplicated JSON handling across methods.

### 2.3 Return Strategy

Implementation may return detached ORM rows or another repo-consistent object shape.

Preferred rule:
- keep returned data easy for tests and future callers to inspect,
- avoid requiring the caller to manage the session lifecycle manually.

---

## 3. Recommended Methods

Suggested method set:
- `upsert_payload_ref(...)`
- `get_payload_ref(payload_ref)`
- `create_ingestion_job(...)`
- `update_ingestion_job(job_id, **fields)`
- `get_ingestion_job(job_id)`
- `create_collection_version(...)`
- `list_collection_versions(collection_key=None)`
- `activate_collection_version(collection_key, version_id)`
- `record_retrieval_provenance(...)`
- `list_retrieval_provenance(request_id=None, session_id=None)`

The exact method names may vary if the final module remains equally clear and focused.

---

## 4. Error and Validation Rules

- Unknown `job_id` updates should raise a clear error.
- Unknown `version_id` activation should raise a clear error.
- Empty or invalid `payload_ref` identifiers should be rejected.
- Non-JSON-serializable dict/list inputs should surface a stable error.

---

## 5. Recommended Test Coverage

Add `tests/backend/unit/test_memory_persistence.py` to validate:
- payload-ref upsert and resolution,
- ingestion-job create/update flows,
- collection-version persistence and activation switching,
- retrieval-provenance recording and query filtering,
- caller-facing error behavior for unknown IDs.

---

## 6. Backward Compatibility Rules

- Do not change existing public chat/session API contracts.
- Do not alter current user-store DB behavior.
- Keep the adapter additive and only consumed by future memory modules unless explicitly wired later.

---

## 7. Expected Outcome

After this issue:
- the repository has a concrete persistence adapter ready for future Milvus ingestion and retrieval work,
- later modules can store and resolve payload refs cleanly,
- and collection activation/provenance behavior is testable before request-path wiring begins.

---

## 8. How To See The Before / After Difference

Issue `#5` is a **backend adapter-layer change**, so the difference is visible in the new persistence module and its focused tests rather than in the UI.

### Before Issue #5

The repository has:
- sidecar ORM tables in `backend/database.py`,
- no dedicated adapter for payload/job/version/provenance persistence,
- and no focused tests for sidecar persistence workflows.

### After Issue #5

The repository is expected to include:
- `backend/memory_persistence.py`
- `tests/backend/unit/test_memory_persistence.py`

### Where To Look In The Repo

1. Open `backend/memory_persistence.py`
   - Look for payload/job/version/provenance helper methods.
2. Open `tests/backend/unit/test_memory_persistence.py`
   - Look for round-trip and activation-path coverage.
3. Open `backend/database.py`
   - Compare the adapter methods to the sidecar rows added in issue #2.

---

## 9. Validation Commands

```bash
source venv/bin/activate
pytest tests/backend/unit/test_memory_persistence.py -q
pytest tests/backend/unit/test_database.py -q
pytest tests/backend/ -q
```