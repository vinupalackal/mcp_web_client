# M2 Issue #8 — Ingestion and Store Test Coverage HLD

**Issue**: #8 — M2: Add ingestion and store test coverage  
**Milestone**: M2 - Milvus + Ingestion  
**Requirements**: docs/M2-COVERAGE-REQUIREMENTS.md  
**Parent Docs**: `Milvus_MCP_Integration_Requirements.md`, `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`

---

## 1. Scope

This document describes the high-level design of the test additions for M2 issue #8.  No production code
changes are made.  Three test files are affected:

| File | Change |
|------|--------|
| `tests/backend/unit/test_milvus_store.py` | Append new test classes |
| `tests/backend/unit/test_ingestion_service.py` | Append new test cases to existing class |
| `tests/backend/unit/test_ingestion_store_integration.py` | New file |

---

## 2. test_milvus_store.py additions

### 2.1 TestMilvusStoreCollectionKeys
Verify that `build_collection_name` produces the expected string for all four collection keys
(`code_memory`, `doc_memory`, `conversation_memory`, `tool_cache`).  Also verify that an unknown key
raises `MilvusCollectionConfigError`.

### 2.2 TestMilvusStoreGenerationIsolation
1. `ensure_collection("code_memory", "v1")` then `ensure_collection("code_memory", "v2")` both succeed and
   produce two different collection names.
2. `upsert` into `v2` reaches only the `v2` collection name; the `v1` collection is unaffected.
3. `drop_collection("code_memory", "v2")` removes only the `v2` collection; `v1` remains.

### 2.3 TestMilvusStoreInputValidation
Cover all guards in `_validate_records` and `build_collection_name`:
- zero dimension → `MilvusCollectionConfigError`
- negative dimension → `MilvusCollectionConfigError`
- empty record list → `MilvusCollectionConfigError`
- wrong embedding length → `MilvusCollectionConfigError`
- missing record id → `MilvusCollectionConfigError`
- unknown collection key → `MilvusCollectionConfigError`

### 2.4 TestMilvusStoreDropNoOp
Calling `drop_collection` on a key/generation that was never created completes silently and makes no
`client.drop_collection` call.

---

## 3. test_ingestion_service.py additions

### 3.1 Test: excluded dirs are never scanned
`IngestionService` configured with `excluded_dirs={"build"}` does not open any file under a `build/`
subdirectory, and the file count in the result reflects only the non-excluded files.

### 3.2 Test: empty workspace produces completed status
An `IngestionService` with no `repo_roots` / `doc_roots` (or roots with no scannable files) returns
`{"status": "completed", "chunk_count": 0, "deleted_count": 0, "error_count": 0}`.

### 3.3 Test: unchanged file is not in stale list on second run
A first run writes chunk A for `main.c`.  The second run re-ingests the same `main.c` (same content).
Since `main.c`'s payload_ref is in `current_payload_refs`, `_remove_stale_chunks` does NOT include it in
the stale list.  `store.delete_calls` remains empty.

### 3.4 Test: collection_generation propagates to store calls
An `IngestionService` constructed with `collection_generation="v2"` passes `generation="v2"` in every
`milvus_store.upsert` and `milvus_store.delete_by_ids` call.

---

## 4. test_ingestion_store_integration.py (new)

### 4.1 Design
Wire a real `IngestionService` to a real `MilvusStore` backed by a `_FakeMilvusClient`.  This validates
that the generation string set on `IngestionService` reaches the Milvus collection name.

### 4.2 Tests

#### TC-INT-01: ingest with v1 generation creates v1 collection
`IngestionService(collection_generation="v1")` → after ingestion, `client.collections` contains
`mcp_client_code_memory_v1` (and/or `mcp_client_doc_memory_v1`).

#### TC-INT-02: switching to v2 generation creates v2 collection, not v1
`IngestionService(collection_generation="v2")` on the same workspace creates `mcp_client_code_memory_v2`;
the `v1` collection key is never passed to the client.

#### TC-INT-03: stale cleanup in v1 does not affect v2 collection
After a v2 ingestion run, any stale-chunk removal calls reference the `v2` collection name.

#### TC-INT-04: provenance payload_refs are consistent
The `payload_ref` stored in the fake `MemoryPersistence` matches the `payload_ref` field in the record
passed to `MilvusStore.upsert`.

---

## 5. Dependencies and Risks

| Item | Notes |
|------|-------|
| No new production imports | All new code is in test files |
| pytest-asyncio | Already used in existing ingestion tests |
| Fake client reuse | `_FakeMilvusClient` pattern established in test_milvus_store.py is duplicated in the integration test file for isolation |

---

## 6. Definition of Done

- All three test files pass in isolation with `pytest -v`.
- `make test` passes with ≥ 539 backend tests.
- No previously passing tests are broken.
