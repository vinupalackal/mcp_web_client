# M2 Ingestion Pipeline Requirements

**Feature:** M2 - Code and Documentation Ingestion Pipeline  
**Application:** MCP Client Web  
**Date:** March 31, 2026  
**Related Issue:** #7  
**Target Files:** `backend/ingestion_service.py`, `tests/backend/unit/test_ingestion_service.py`

---

## 1. Purpose

This document defines the issue-level requirements for M2 issue #7: adding an ingestion pipeline that scans configured code and documentation roots, chunks content, generates embeddings, writes vectors to Milvus, and persists payload refs plus job state in the sidecar store.

---

## 2. Scope

### In Scope

- Scan repo and doc roots.
- Exclude generated/vendor/build directories.
- Parse C/C++ files with tree-sitter or equivalent AST-aware parsing.
- Chunk code by semantic boundaries and split oversized chunks.
- Chunk docs by structural sections/headings.
- Compute stable content hashes and identifiers.
- Write payload refs to sidecar persistence.
- Write vectors + metadata to Milvus.
- Remove stale chunks from active collections.
- Record ingestion job status, chunk counts, and non-fatal errors.

### Out of Scope

- Chat-path retrieval wiring.
- Milvus health/admin endpoints.
- Conversation-memory ingestion.
- Tool-cache ingestion.

---

## 3. Requirements Mapping

| ID | Requirement | How this issue addresses it |
|---|---|---|
| FR-ING-01 | Support C and C++ source/header files from configured roots. | Ingestion scans configured repo roots for supported code extensions. |
| FR-ING-02 | Preferred parsing strategy is tree-sitter or equivalent AST-aware parsing. | Tree-sitter-backed parsing is used for code chunk extraction. |
| FR-ING-03 | Code must be chunked at semantic boundaries first, then subdivided when a symbol is too large. | Code chunking starts from parser nodes and splits oversized chunks. |
| FR-ING-04 | Each chunk must capture workspace-relative path, symbol metadata, and stable source hash. | Chunk metadata includes source path, symbol fields, and hashes. |
| FR-ING-06 | Incremental reindexing must use content hashes or manifest state. | Stable chunk/source hashes drive stale-chunk reconciliation. |
| FR-ING-07 | Detect deletions and remove stale chunks from active indexes. | Ingestion compares current payload refs against persisted refs and deletes stale ones. |
| FR-ING-08 | File-level ingestion failures must not abort the whole job. | Per-file exceptions are recorded as non-fatal job errors. |
| FR-DOC-01 | Support Markdown, plaintext, and other configured document sources. | Initial implementation supports Markdown/plaintext-style docs. |
| FR-DOC-02 | Documents must be chunked by structural boundaries such as headings. | Markdown headings are used to define doc chunks. |
| FR-DOC-03 | Each doc chunk must capture path, source type, section, content hash, and payload ref. | Doc chunk metadata includes those fields. |
| FR-DOC-04 | Documentation ingestion must support incremental refresh and stale deletion. | Same stale-chunk cleanup path applies to doc chunks. |
| FR-OPS-03 | Ingestion jobs should expose status, duration, chunk counts, and error counts. | Ingestion job rows are created and updated through the pipeline. |
| NFR-REL-04 | The system must tolerate partial ingestion failures. | Remaining files continue processing after individual failures. |

---

## 4. Acceptance Criteria

- `backend/ingestion_service.py` exists.
- Code and docs are scanned from configured roots.
- Chunks are embedded and written through the Milvus store abstraction.
- Payload refs and ingestion-job state are persisted.
- Stale chunks are removed.
- Focused ingestion tests pass.
- Existing backend regression remains green.

---

## 5. Validation

```bash
source venv/bin/activate
pytest tests/backend/unit/test_ingestion_service.py -q
pytest tests/backend/unit/test_milvus_store.py tests/backend/unit/test_memory_persistence.py -q
pytest tests/backend/ -q
```