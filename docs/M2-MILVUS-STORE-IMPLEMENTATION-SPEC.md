# M2 Milvus Store Abstraction Implementation Spec

**Feature:** M2 - Milvus Store Abstraction  
**Application:** MCP Client Web  
**Date:** March 31, 2026  
**Related Issue:** #6  
**Primary File:** `backend/milvus_store.py`

---

## 1. Implementation Intent

This document translates the issue-level requirements and HLD for issue #6 into a practical implementation spec for the repository.

The objective is to add the minimum useful Milvus store boundary needed before ingestion and retrieval wiring begin.

---

## 2. Target Additions

### 2.1 `MilvusStore`

Suggested responsibilities:
- manage versioned collection names,
- create missing collections with explicit schema + index metadata,
- expose upsert/search/delete operations,
- and surface configuration errors clearly.

### 2.2 Collection Specs

Keep named specs for:
- `code_memory`
- `doc_memory`
- `conversation_memory`
- `tool_cache`

with Phase 1 methods focused on the first two while remaining structurally ready for later phases.

### 2.3 Client Injection

Allow an injected client and client factory so:
- unit tests can avoid a live Milvus server,
- the module remains deterministic under test,
- and direct `pymilvus` setup is still available in real usage.

---

## 3. Recommended Methods

Suggested method set:
- `build_collection_name(...)`
- `ensure_collection(...)`
- `describe_collection(...)`
- `upsert(...)`
- `search(...)`
- `delete_by_ids(...)`
- `delete_by_filter(...)`
- `drop_collection(...)`
- `list_collections()`

---

## 4. Error and Validation Rules

- Unsupported collection keys should raise a clear configuration error.
- Missing or invalid generation markers should fail fast.
- Upsert records should validate presence of `id` and embedding dimension.
- Search requests should reject empty query-vector lists.
- Filter-based deletes should reject empty filter expressions.

---

## 5. Recommended Test Coverage

Add `tests/backend/unit/test_milvus_store.py` to validate:
- collection naming,
- schema/index creation,
- upsert forwarding,
- search forwarding,
- delete-by-id and delete-by-filter behavior,
- and collection drop behavior.

---

## 6. Expected Outcome

After this issue:
- the repository has a concrete Milvus store abstraction,
- later ingestion code can write vectors through one module,
- and later retrieval code can query vectors without embedding direct `pymilvus` calls into business logic.

---

## 7. How To See The Before / After Difference

Before issue `#6`, the repo had Milvus dependencies installed but no store module encapsulating collection and vector operations.

After issue `#6`, the repo includes:
- `backend/milvus_store.py`
- `tests/backend/unit/test_milvus_store.py`

That means Milvus lifecycle and vector operations now have a tested backend boundary instead of needing direct client calls in future ingestion/retrieval modules.

---

## 8. Validation Commands

```bash
source venv/bin/activate
pytest tests/backend/unit/test_milvus_store.py -q
pytest tests/backend/ -q
```