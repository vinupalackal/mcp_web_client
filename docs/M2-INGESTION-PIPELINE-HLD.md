# M2 Ingestion Pipeline HLD

**Feature:** M2 - Code and Documentation Ingestion Pipeline  
**Application:** MCP Client Web  
**Date:** March 31, 2026  
**Status:** Design Ready  
**Related Issue:** #7  
**Parent Docs:** `Milvus_MCP_Integration_Requirements.md`, `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`

---

## 1. Executive Summary

This HLD defines the design for issue #7.

The ingestion pipeline coordinates file scanning, semantic/doc chunking, embedding generation, Milvus upserts, sidecar persistence, and stale-record cleanup through focused backend modules.

---

## 2. Design Goals

1. Keep ingestion orchestration isolated from FastAPI and chat logic.
2. Reuse the embedding, Milvus store, and memory persistence modules added in earlier issues.
3. Support partial-failure tolerance.
4. Make stale-chunk cleanup explicit and testable.
5. Preserve deterministic behavior with injected dependencies in unit tests.

---

## 3. Component Delta

| Component | Change | Description |
|---|---|---|
| `backend/ingestion_service.py` | New | Orchestrates code/doc scanning, chunking, embedding, store writes, and cleanup |
| `tests/backend/unit/test_ingestion_service.py` | New | Focused coverage for happy-path ingestion, non-fatal failure handling, and stale cleanup |
| `backend/memory_persistence.py` | Extended | Supports payload-ref listing/deletion used by stale cleanup |

---

## 4. Proposed Flow

```text
repo/doc roots
  → file scan
  → code/doc chunk extraction
  → embedding generation
  → payload-ref persistence
  → Milvus upsert
  → stale-chunk reconciliation
  → ingestion-job status update
```

---

## 5. Validation

- `pytest tests/backend/unit/test_ingestion_service.py -q`
- `pytest tests/backend/ -q`