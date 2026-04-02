# M2 Milvus Store Abstraction HLD

**Feature:** M2 - Milvus Store Abstraction  
**Application:** MCP Client Web  
**Date:** March 31, 2026  
**Status:** Design Ready  
**Related Issue:** #6  
**Parent Docs:** `Milvus_MCP_Integration_Requirements.md`, `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`

---

## 1. Executive Summary

This HLD defines the design for issue #6.

The purpose of this work is to introduce a focused `MilvusStore` module that owns direct collection and vector operations, so later retrieval and ingestion layers can operate through a small, stable backend boundary.

---

## 2. Design Goals

1. Isolate direct Milvus client usage in one module.
2. Make collection naming and schema definitions explicit.
3. Support collection lifecycle and vector operations needed by later M2 work.
4. Keep the store unit-testable without a live Milvus server.
5. Preserve clear separation between Milvus storage and sidecar persistence.

---

## 3. Component Delta

| Component | Change | Description |
|---|---|---|
| `backend/milvus_store.py` | New | Encapsulates Milvus collection creation, upsert, search, and delete operations |
| `tests/backend/unit/test_milvus_store.py` | New | Focused coverage using a fake injected Milvus client |
| `backend/embedding_service.py` | Reused | Supplies vectors later but is not directly coupled in this issue |
| `backend/memory_persistence.py` | Reused separately | Tracks sidecar metadata outside Milvus |

---

## 4. Proposed Structure

### 4.1 Store Boundary

Recommended composition:

```text
MilvusStore
├── build collection names
├── ensure collection exists
├── describe/list/drop collections
├── upsert vector records
├── search vector records
└── delete by ids or filter
```

### 4.2 Collection Specs

The module should keep explicit collection-spec definitions for each logical collection key.

This keeps:
- schema fields documented in code,
- metric/index settings explicit,
- and future Phase 2/3 expansion straightforward.

### 4.3 Testability Strategy

The store should accept an injected client and client factory so tests can validate:
- collection naming,
- schema/index construction,
- and forwarded Milvus operations,

without requiring a real Milvus server.

---

## 5. Failure Modeling

The store should fail clearly for:
- unsupported collection keys,
- missing generation markers,
- invalid vector dimensions,
- empty search vectors,
- and malformed delete/filter requests.

Higher-level retrieval code can later decide whether these failures trigger degraded fallback.

---

## 6. Validation

- `pytest tests/backend/unit/test_milvus_store.py -q`
- `pytest tests/backend/unit/test_embedding_service.py tests/backend/unit/test_memory_persistence.py -q`
- `pytest tests/backend/ -q`