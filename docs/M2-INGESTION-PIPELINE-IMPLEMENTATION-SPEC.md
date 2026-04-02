# M2 Ingestion Pipeline Implementation Spec

**Feature:** M2 - Code and Documentation Ingestion Pipeline  
**Application:** MCP Client Web  
**Date:** March 31, 2026  
**Related Issue:** #7  
**Primary File:** `backend/ingestion_service.py`

---

## 1. Implementation Intent

This document translates the issue-level requirements and HLD for issue #7 into a practical implementation spec for the repository.

The objective is to add the first ingestion pipeline slice that can index code/doc roots through the already-added embedding, store, and persistence abstractions.

---

## 2. Target Additions

### 2.1 `IngestionService`

Suggested responsibilities:
- scan roots,
- chunk code/docs,
- call embedding generation,
- write sidecar payload refs,
- upsert Milvus records,
- remove stale chunks,
- and update ingestion-job state.

### 2.2 Code Chunking

- Use tree-sitter-backed symbol extraction for C/C++ where practical.
- Fall back to file-level chunking when semantic extraction is not available.
- Split oversized chunks predictably.

### 2.3 Document Chunking

- Use headings/sections where available.
- Fall back to a document-level chunk when needed.

---

## 3. Expected Outcome

After this issue:
- the repository has a first ingestion pipeline,
- code/doc content can be indexed through the new abstractions,
- and stale payload/vector cleanup is handled explicitly.

---

## 4. Validation Commands

```bash
source venv/bin/activate
pytest tests/backend/unit/test_ingestion_service.py -q
pytest tests/backend/ -q
```