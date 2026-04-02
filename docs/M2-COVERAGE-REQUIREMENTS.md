# M2 Issue #8 — Ingestion and Store Test Coverage Requirements

**Issue**: #8 — M2: Add ingestion and store test coverage  
**Milestone**: M2 - Milvus + Ingestion  
**Parent Docs**: `Milvus_MCP_Integration_Requirements.md`, `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`  
**Related Implementations**: `backend/milvus_store.py`, `backend/ingestion_service.py`

---

## 1. Context

Issues #6 and #7 delivered the `MilvusStore` abstraction and the `IngestionService` pipeline respectively.
Each was validated with a focused happy-path test suite.  Issue #8 fills the remaining coverage gaps before
M2 is considered complete:

- **Generation rollover**: multiple collection generations can coexist; writing to a new generation does not
  pollute the previous one; dropping a generation cleans up only its own collection.
- **Cross-run incremental refresh**: re-ingesting the same workspace after content changes embeds only the
  changed chunk and does not duplicate unchanged refs.
- **Exclusion rules**: paths inside `excluded_dirs` are never ingested.
- **Empty workspace**: a workspace with no scannable files produces a `completed` job with zero chunks.
- **Store + ingestion integration**: `IngestionService` passes the configured `collection_generation` to
  `MilvusStore`; stale refs are cleaned up against the correct generation.

---

## 2. Functional Requirements

### FR-COV-01 — Store collection key coverage
All four collection keys (`code_memory`, `doc_memory`, `conversation_memory`, `tool_cache`) must produce
correctly prefixed, generation-suffixed names via `MilvusStore.build_collection_name`.

### FR-COV-02 — Generation isolation in store
Calling `ensure_collection` with `generation="v1"` and then `generation="v2"` creates two distinct
collections.  Upserting into `v2` does not touch `v1`.

### FR-COV-03 — Idempotent ensure_collection per generation
Repeated calls to `ensure_collection` with the same `(collection_key, generation)` invoke
`client.create_collection` exactly once.

### FR-COV-04 — Input validation at store boundary
`MilvusStore` raises `MilvusCollectionConfigError` for:
- non-positive dimension,
- unknown collection key in `build_collection_name`,
- empty records in `upsert`,
- records with wrong embedding dimensions,
- missing record `id`.

### FR-COV-05 — drop_collection is a no-op for absent collections
`drop_collection` on a collection that has never been created completes without error and makes no client
call.

### FR-COV-06 — Incremental re-ingestion (cross-run)
On a second `ingest_workspace_async` call against the same `repo_id`, if a file has not changed (same
content hash) the chunk is re-emitted with the same `payload_ref` and therefore is NOT in the stale list.
If the file was deleted, its ref is removed from current refs and `_remove_stale_chunks` deletes it.

### FR-COV-07 — Excluded directories
Files under directories listed in `excluded_dirs` are never opened, chunked, or embedded.

### FR-COV-08 — Empty workspace
Running `ingest_workspace_async` with no repo/doc roots (or roots containing zero scannable files)
produces `status="completed"`, `chunk_count=0`, `deleted_count=0`.

### FR-COV-09 — collection_generation propagation
The `collection_generation` passed to `IngestionService.__init__` reaches every `MilvusStore.upsert`
and `delete_by_ids` call.

### FR-COV-10 — Generation rollover integration
Running `IngestionService` with `collection_generation="v1"` then again with `collection_generation="v2"`
creates separate Milvus collections; the `v1` collection is unaffected by the `v2` run.

---

## 3. Non-Functional Requirements

- NFR-COV-01: All new tests run under `pytest` with `pytest-asyncio`; no real Milvus instance is required.
- NFR-COV-02: Test helpers reuse the fake-client pattern already established in `test_milvus_store.py`.
- NFR-COV-03: No new production code is added; this issue is coverage-only.
- NFR-COV-04: Full `make test` regression continues to pass after the additions.

---

## 4. Acceptance Criteria

| ID | Criterion |
|----|-----------|
| AC-COV-01 | `test_milvus_store.py` covers all 4 collection keys, generation isolation, idempotence, and all input-validation guards |
| AC-COV-02 | `test_ingestion_service.py` covers excluded dirs, empty workspace, cross-run hash stability, and `collection_generation` propagation |
| AC-COV-03 | New `test_ingestion_store_integration.py` covers the two-generation rollover scenario wiring both layers together |
| AC-COV-04 | `make test` reports the same or higher pass count than after issue #7 (539 backend) |
