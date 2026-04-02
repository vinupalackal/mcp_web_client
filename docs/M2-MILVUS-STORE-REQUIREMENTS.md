# M2 Milvus Store Abstraction Requirements

**Feature:** M2 - Milvus Store Abstraction  
**Application:** MCP Client Web  
**Date:** March 31, 2026  
**Related Issue:** #6  
**Target Files:** `backend/milvus_store.py`, `tests/backend/unit/test_milvus_store.py`

---

## 1. Purpose

This document defines the issue-level requirements for M2 issue #6: adding a **Milvus store abstraction** that encapsulates direct Milvus collection management and vector operations for the memory subsystem.

This issue prepares the backend for:
- versioned collection creation and naming,
- vector upsert and search operations,
- delete-by-id and delete-by-filter support,
- and future ingestion/retrieval code that should not call `pymilvus` directly.

This issue is limited to the store abstraction and unit tests. It does not require ingestion parsing or chat-path retrieval integration.

---

## 2. Scope

### In Scope

- Add `backend/milvus_store.py` as the direct Milvus wrapper.
- Support versioned collection naming for `code_memory_v1` and `doc_memory_v1` style collections.
- Create collections with schema and index metadata.
- Support upsert, search, delete-by-id, and delete-by-filter operations.
- Keep collection-key support ready for Phase 2/3 collections.
- Add focused unit tests for collection lifecycle and vector operations.

### Out of Scope

- Ingestion pipeline implementation.
- Retrieval orchestration or prompt-context formatting.
- Memory-persistence sidecar writes.
- FastAPI route wiring.

---

## 3. Requirements Mapping

| ID | Requirement | How this issue addresses it |
|---|---|---|
| DATA-04 | Embedding/index version must be tracked per collection generation. | Store uses explicit generation-aware collection naming and index metadata setup. |
| DATA-05 | The system must support reindexing into a new versioned collection without requiring immediate deletion of the old collection. | Collection naming is versioned rather than hard-coded. |
| FR-RET-01 | Retrieval should optionally retrieve relevant code and documentation context before synthesis. | Store provides the search primitive future retrieval orchestration needs. |
| FR-RET-06 | Retrieval failure must degrade gracefully. | Store isolates Milvus failures from higher-level retrieval logic. |
| NFR-MAIN-01 | New memory functionality must be implemented as focused modules. | Direct Milvus access is isolated in `backend/milvus_store.py`. |
| NFR-MAIN-02 | Collection schemas and embedding versions must be explicit and documented. | Collection specs and naming rules are explicit in the module. |

---

## 4. Required Capabilities

### 4.1 Versioned Collection Naming

The store must construct deterministic collection names from:
- a configured collection prefix,
- a logical collection key,
- and a generation/version marker.

### 4.2 Collection Lifecycle Support

The store must support:
- checking whether a collection exists,
- creating it when missing,
- describing it,
- and dropping it when required.

### 4.3 Vector Operations

The store must support:
- upsert for one or more records,
- vector search with optional filter expressions,
- delete by ID,
- and delete by filter.

### 4.4 Schema and Index Metadata

The store must define explicit collection specs for:
- `code_memory`
- `doc_memory`

and remain structurally ready for:
- `conversation_memory`
- `tool_cache`

---

## 5. Design Constraints

- Keep direct `pymilvus` calls inside this module.
- Make the store testable with an injected fake client.
- Keep collection and vector validation deterministic and caller-visible.
- Avoid coupling the module to FastAPI or session runtime state.

---

## 6. Acceptance Criteria

- `backend/milvus_store.py` exists as the Milvus wrapper.
- Versioned collection names are deterministic and explicit.
- Collection creation uses explicit schema and index metadata.
- Upsert, search, and delete helpers are covered by focused tests.
- The abstraction is unit-testable without a live Milvus server.
- Existing backend regression remains green.

---

## 7. Validation

```bash
source venv/bin/activate
pytest tests/backend/unit/test_milvus_store.py -q
pytest tests/backend/unit/test_embedding_service.py tests/backend/unit/test_memory_persistence.py -q
pytest tests/backend/ -q
```