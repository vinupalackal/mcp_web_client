# Milvus Integration Implementation Plan
## File-by-File Delivery Plan for MCP Client Web

**Project**: MCP Client Web  
**Feature**: Milvus Retrieval, Memory, and Safe Caching  
**Date**: March 30, 2026  
**Status**: Planning Ready  
**Requirements**: ../Milvus_MCP_Integration_Requirements.md  
**HLD**: MILVUS_MCP_INTEGRATION_HLD.md

---

## 1. Purpose

This document converts the Milvus requirements and HLD into a concrete, file-by-file implementation plan for this repository.

The plan is intentionally phased to reduce integration risk:

- **Phase 1**: retrieval enrichment only,
- **Phase 2**: same-user conversation memory,
- **Phase 3**: safe allowlisted tool cache,
- **Phase 4**: optimization, migration, and operations hardening.

The initial coding target is to integrate Milvus **behind the existing chat/session flow** without changing the external chat API contract.

---

## 2. Planning Assumptions

### 2.1 Guardrails

- Existing `POST /api/sessions` and `POST /api/sessions/{session_id}/messages` remain the primary chat entrypoints.
- `backend/session_manager.py` continues to own active session runtime state.
- `backend/mcp_manager.py` remains the MCP tool execution boundary.
- Milvus is optional and feature-flagged.
- Retrieval failure must degrade gracefully to current behavior.
- No semantic tool caching is enabled in Phase 1.

### 2.2 Recommended Delivery Order

1. Add configuration and health plumbing.
2. Add memory abstractions and persistence scaffolding.
3. Add embedding abstraction.
4. Add Milvus store and collection lifecycle support.
5. Add code/doc ingestion pipeline.
6. Integrate retrieval into chat orchestration.
7. Add tests and operator docs.
8. Defer conversation memory and tool cache until Phase 1 is stable.

---

## 3. Phase 1 Overview - Retrieval Enrichment

### 3.1 Phase 1 Deliverable

At the end of Phase 1, the application should:

- start successfully with memory features disabled,
- optionally connect to Milvus when enabled,
- ingest code and documentation into versioned collections,
- enrich existing chat turns with retrieved code/doc context,
- log provenance and degraded fallback behavior,
- and keep existing frontend and backend APIs compatible.

### 3.2 Phase 1 Files

#### Existing files to update
- `backend/main.py`
- `backend/models.py`
- `backend/llm_client.py`
- `backend/database.py`
- `backend/session_manager.py`
- `backend/static/app.js` (optional Phase 1 UI visibility)
- `requirements.txt`
- `README.md`

#### New backend files
- `backend/memory_service.py`
- `backend/milvus_store.py`
- `backend/embedding_service.py`
- `backend/ingestion_service.py`
- `backend/memory_persistence.py`

#### New or updated test files
- `tests/backend/unit/test_embedding_service.py`
- `tests/backend/unit/test_milvus_store.py`
- `tests/backend/unit/test_ingestion_service.py`
- `tests/backend/unit/test_memory_service.py`
- `tests/backend/integration/test_memory_health_api.py`
- `tests/backend/integration/test_memory_retrieval_flow.py`
- `tests/backend/integration/test_memory_degraded_mode.py`
- `tests/backend/integration/test_memory_sso_scope.py`

---

## 4. File-by-File Plan

## 4.1 `backend/main.py`

### Role in Milvus Integration
Primary integration point for startup configuration, health reporting, and chat-turn retrieval orchestration.

### Planned Changes

#### Phase 1
- Read new memory-related environment variables.
- Initialize optional memory services during application startup.
- Extend health reporting to include memory subsystem status.
- Integrate retrieval enrichment into the existing `send_message()` flow.
- Add graceful fallback when memory services fail during a request.
- Record retrieval trace summaries and log metadata.

#### Phase 2
- Add long-term conversation recall during chat-turn processing.
- Persist summarized conversation memories after successful turns.

#### Phase 3
- Add feature-flagged allowlisted tool cache checks around approved tool classes only.

### Dependencies
- `backend/memory_service.py`
- `backend/embedding_service.py`
- `backend/milvus_store.py`
- `backend/memory_persistence.py`

### Acceptance Checks
- Chat flow unchanged when memory disabled.
- Retrieval enrichment invoked only when enabled and healthy.
- Retrieval failures do not break `ChatResponse`.

---

## 4.2 `backend/models.py`

### Role in Milvus Integration
Defines configuration, API diagnostics, ingestion/admin payloads, and any structured memory-related responses.

### Planned Changes

#### Phase 1
- Add `MemoryStatus` or equivalent health/diagnostic model.
- Add optional models for memory diagnostics and ingestion job status.
- Add feature-flag/config models if memory settings are surfaced through API.
- Keep OpenAPI documentation aligned with any new `/api/memory/*` endpoints if added.

#### Phase 2
- Add models for conversation memory summaries if surfaced in diagnostics.

#### Phase 3
- Add cache diagnostics models if cache observability endpoints are introduced.

### Dependencies
- `backend/main.py`
- `backend/memory_persistence.py`

### Acceptance Checks
- New models are backward-compatible.
- OpenAPI schema remains valid.

---

## 4.3 `backend/llm_client.py`

### Role in Milvus Integration
Provides or exposes embedding-capable provider behavior without conflating embeddings with chat completions.

### Planned Changes

#### Phase 1
- Add a provider-agnostic embedding entrypoint or helper.
- Normalize embedding requests across OpenAI-, Ollama-, and enterprise-style providers where practical.
- Reuse existing timeout/error-handling patterns.
- Keep chat completion behavior unchanged.

#### Phase 2+
- Support future conversation summarization helpers if implemented near the LLM boundary.

### Dependencies
- `backend/embedding_service.py`

### Acceptance Checks
- Existing chat completion tests continue passing.
- Embedding requests return normalized vectors or actionable errors.

---

## 4.4 `backend/database.py`

### Role in Milvus Integration
Provides sidecar persistence for payload refs, ingestion jobs, collection metadata, and provenance/audit data.

### Planned Changes

#### Phase 1
- Add ORM models for payload references.
- Add ORM models for ingestion job tracking.
- Add ORM models for collection version metadata and activation state.
- Add ORM models for retrieval provenance or lightweight audit records if needed.
- Add schema initialization support for the new tables.

#### Phase 2
- Add storage for conversation-memory sidecar payloads if required.

#### Phase 3
- Add cache provenance rows and explicit cache policy metadata.

### Dependencies
- `backend/memory_persistence.py`
- `backend/ingestion_service.py`
- `backend/main.py`

### Acceptance Checks
- Schema initializes cleanly in SQLite.
- New tables do not affect existing user/config tables.

---

## 4.5 `backend/session_manager.py`

### Role in Milvus Integration
Maintains active runtime session state; optionally exposes retrieval traces to current-session diagnostics.

### Planned Changes

#### Phase 1
- Add optional trace helpers for retrieval events.
- Keep active history and session ownership behavior unchanged.

#### Phase 2
- Add helper methods for deriving compact turn summaries if conversation memory is generated from session history.

### Dependencies
- `backend/main.py`
- `backend/memory_service.py`

### Acceptance Checks
- No change to current session lifecycle behavior.
- Retrieval traces do not break existing message flow.

---

## 4.6 `backend/mcp_manager.py`

### Role in Milvus Integration
Remains intentionally stable as the MCP tool execution boundary.

### Planned Changes

#### Phase 1
- No functional retrieval changes expected.
- Optional metadata access helpers may be added only if retrieval wants structured tool-output hints from executed tools.

#### Phase 3
- If safe cache is introduced, cache policy checks may wrap around calls before/after dispatch, but execution semantics remain unchanged.

### Acceptance Checks
- Tool discovery and tool execution behavior remain stable.
- No Milvus-specific logic should be embedded directly here unless strictly required.

---

## 4.7 `backend/memory_service.py` (new)

### Role in Milvus Integration
Top-level orchestration service for retrieval enrichment, future conversation recall, and fallback handling.

### Planned Responsibilities

#### Phase 1
- Determine whether retrieval is enabled.
- Build retrieval queries from the current user message and optional turn hints.
- Request embeddings from `EmbeddingService`.
- Query code/doc collections via `MilvusStore`.
- Cap and normalize retrieved context blocks.
- Produce provenance metadata.
- Fail open to degraded behavior when needed.

#### Phase 2
- Recall same-user conversation memory within workspace scope.
- Persist summarized turn memories through persistence/store layers.

#### Phase 3
- Coordinate allowlisted cache lookups without making cache decisions based on similarity alone.

### Dependencies
- `backend/embedding_service.py`
- `backend/milvus_store.py`
- `backend/memory_persistence.py`

### Acceptance Checks
- Retrieval service is unit-testable without FastAPI.
- Fallback behavior is deterministic and observable.

---

## 4.8 `backend/milvus_store.py` (new)

### Role in Milvus Integration
Encapsulates all direct Milvus interactions.

### Planned Responsibilities

#### Phase 1
- Connection handling.
- Collection existence and schema checks.
- Search and upsert APIs for `code_memory_v1` and `doc_memory_v1`.
- Delete-by-id and delete-by-filter support needed for incremental reindexing.
- Versioned collection naming conventions.
- Index metadata validation.

#### Phase 2
- Support `conversation_memory_v1` operations.

#### Phase 3
- Support `tool_cache_v1` operations and provenance fields.

### Dependencies
- Milvus Python client dependency.
- `backend/memory_service.py`
- `backend/ingestion_service.py`

### Acceptance Checks
- Search/upsert behavior isolated from business logic.
- Collection version activation logic is explicit.

---

## 4.9 `backend/embedding_service.py` (new)

### Role in Milvus Integration
Provides provider-normalized embedding generation.

### Planned Responsibilities

#### Phase 1
- Accept texts and embedding configuration.
- Route embedding requests via configured provider.
- Validate vector dimensions against active collection expectations.
- Support batching.
- Surface timeouts and provider failures cleanly.

### Dependencies
- `backend/llm_client.py`
- Possibly provider-specific config helpers in `backend/main.py`

### Acceptance Checks
- Embedding vectors are returned in a consistent shape.
- Provider failures are distinguishable from Milvus failures.

---

## 4.10 `backend/ingestion_service.py` (new)

### Role in Milvus Integration
Background indexing pipeline for code and docs.

### Planned Responsibilities

#### Phase 1
- Scan configured repo and doc roots.
- Exclude generated/vendor/build directories.
- Parse C/C++ symbols using tree-sitter or equivalent.
- Chunk code semantically and split oversized chunks.
- Chunk docs by section.
- Compute content hashes and manifest state.
- Write payload refs to persistence layer.
- Write vectors + metadata to Milvus.
- Remove stale records for deleted content.
- Record ingestion job status and errors.

#### Phase 2
- Optionally ingest conversation summaries if offline compaction is needed.

### Dependencies
- `backend/embedding_service.py`
- `backend/milvus_store.py`
- `backend/memory_persistence.py`

### Acceptance Checks
- Single-file parser failures do not abort full ingestion.
- Incremental refresh removes stale chunks reliably.

---

## 4.11 `backend/memory_persistence.py` (new)

### Role in Milvus Integration
Adapter around sidecar durable storage for payloads, jobs, provenance, and collection metadata.

### Planned Responsibilities

#### Phase 1
- Persist and resolve payload references.
- Persist ingestion job records.
- Persist collection activation metadata.
- Persist retrieval provenance summaries.

#### Phase 2
- Persist conversation memory payload refs.

#### Phase 3
- Persist cache provenance and audit rows.

### Dependencies
- `backend/database.py`

### Acceptance Checks
- Payload refs remain stable across retrieval requests.
- Persistence remains usable in SQLite development mode.

---

## 4.12 `backend/static/app.js`

### Role in Milvus Integration
Optional frontend surface for showing retrieval/source information without changing the chat contract.

### Planned Changes

#### Phase 1 (optional)
- Display a lightweight source/retrieval indicator when enriched context was used.
- Avoid exposing raw payloads unnecessarily.
- Keep current send/new-session behavior unchanged.

#### Phase 2+
- Optionally show recalled-memory badges or source panels if product decisions require them.

### Acceptance Checks
- No regression in chat submission flow.
- UI changes remain purely additive.

---

## 4.13 `requirements.txt`

### Role in Milvus Integration
Declares new Python dependencies.

### Planned Changes

#### Phase 1
- Add Milvus client library.
- Add tree-sitter and language bindings if chosen implementation requires them.
- Add any hashing/serialization helpers only if truly needed.

### Acceptance Checks
- Dependencies install cleanly in current repo environment.
- New packages do not replace or conflict with current chat/MCP stack.

---

## 4.14 `README.md`

### Role in Milvus Integration
Operator and developer onboarding.

### Planned Changes

#### Phase 1
- Add Milvus optional feature overview.
- Add new environment variables.
- Add degraded-mode behavior notes.
- Add indexing and health-check instructions.
- Clarify that the feature is optional and chat still works without it.

### Acceptance Checks
- Setup instructions are sufficient for local validation.

---

## 4.15 `docs/MILVUS_MCP_INTEGRATION_HLD.md`

### Role in Milvus Integration
Architecture source of truth.

### Planned Changes
- Keep updated if implementation choices around payload storage, ingestion workflow, or source display change.

---

## 4.16 `Milvus_MCP_Integration_Requirements.md`

### Role in Milvus Integration
Requirement source of truth.

### Planned Changes
- Update only when implementation decisions require requirement changes, not merely implementation details.

---

## 4.17 Test Files

### Unit Tests

#### `tests/backend/unit/test_embedding_service.py` (new)
- provider selection
- batch embedding behavior
- dimension validation
- timeout/error normalization

#### `tests/backend/unit/test_milvus_store.py` (new)
- collection naming
- search result normalization
- upsert/delete behavior
- version activation logic

#### `tests/backend/unit/test_ingestion_service.py` (new)
- path exclusion rules
- chunk splitting rules
- content hash change detection
- stale record removal logic

#### `tests/backend/unit/test_memory_service.py` (new)
- retrieval enable/disable behavior
- degraded fallback behavior
- provenance shaping
- result capping

### Integration Tests

#### `tests/backend/integration/test_memory_health_api.py` (new)
- health when memory disabled
- health when memory enabled and healthy
- health when memory enabled and degraded

#### `tests/backend/integration/test_memory_retrieval_flow.py` (new)
- retrieval inserted into existing chat flow
- no API contract changes to `ChatResponse`
- synthesis proceeds with retrieved context

#### `tests/backend/integration/test_memory_degraded_mode.py` (new)
- Milvus unavailable at startup
- Milvus unavailable during turn
- embedding provider unavailable during turn

#### `tests/backend/integration/test_memory_sso_scope.py` (new)
- same-user access allowed
- cross-user memory disallowed
- anonymous/no-SSO fallback scope handled safely

### Frontend Tests (only if UI surface added)

#### `tests/frontend/test_frontend_integration.test.js`
- retrieval indicator rendering
- no regression in chat send path

---

## 5. Phase-by-Phase Execution Plan

## Phase 1A - Foundations

### Target Files
- `requirements.txt`
- `backend/database.py`
- `backend/models.py`
- `backend/llm_client.py`
- `backend/embedding_service.py`
- `backend/memory_persistence.py`

### Outcome
- Dependency base installed.
- Embedding abstraction exists.
- Sidecar schema exists.
- Config and diagnostics models are ready.

## Phase 1B - Milvus and Ingestion

### Target Files
- `backend/milvus_store.py`
- `backend/ingestion_service.py`
- `backend/database.py`
- tests for store and ingestion

### Outcome
- Versioned collections can be created and indexed.
- Code/doc ingestion works incrementally.

## Phase 1C - Chat Integration

### Target Files
- `backend/memory_service.py`
- `backend/main.py`
- `backend/session_manager.py`
- integration tests for retrieval and degraded mode

### Outcome
- Retrieval enrichment works inside the current chat flow.
- Degraded fallback is in place.

## Phase 1D - Docs and Optional UI

### Target Files
- `README.md`
- `backend/static/app.js` (optional)
- frontend tests if UI changes

### Outcome
- Operators can enable, validate, and troubleshoot the feature.

## Phase 2 - Conversation Memory

### Target Files
- `backend/memory_service.py`
- `backend/milvus_store.py`
- `backend/memory_persistence.py`
- `backend/main.py`
- `backend/database.py`
- conversation-scope integration tests

### Outcome
- Same-user, workspace-scoped long-term memory added.

## Phase 3 - Safe Tool Cache

### Target Files
- `backend/memory_service.py`
- `backend/milvus_store.py`
- `backend/memory_persistence.py`
- `backend/main.py`
- cache policy unit tests

### Outcome
- Allowlisted, provenance-aware tool caching for explicitly approved tool classes only.

---

## 6. Dependency and Sequencing Notes

### 6.1 Hard Dependencies

| File | Depends On |
|---|---|
| `backend/main.py` memory integration | `memory_service.py`, `embedding_service.py`, config plumbing |
| `memory_service.py` | `embedding_service.py`, `milvus_store.py`, `memory_persistence.py` |
| `ingestion_service.py` | `embedding_service.py`, `milvus_store.py`, `memory_persistence.py` |
| `memory_persistence.py` | `database.py` |
| integration tests | stable unit-level abstractions first |

### 6.2 Suggested Commit Slices

1. Dependencies + schema + service interfaces
2. Embedding service + tests
3. Milvus store + tests
4. Ingestion service + tests
5. Main chat integration + degraded health + tests
6. README/docs + optional UI

---

## 7. Validation Checklist

### Phase 1 Exit Criteria
- Memory disabled path behaves exactly like current app.
- Health reports `disabled`, `healthy`, or `degraded` for memory subsystem.
- Retrieval enrichment works through current chat APIs.
- Retrieval failures do not break the user response path.
- Ingestion supports incremental refresh and stale deletion.
- New unit and integration tests pass.

### Phase 2 Exit Criteria
- Same-user recall works.
- Cross-user recall is blocked in SSO mode.
- Retention/expiry behavior is validated.

### Phase 3 Exit Criteria
- No tool cache hit occurs without explicit policy approval.
- Cache keys include deterministic scope data.
- Similarity alone cannot authorize reuse.

---

## 8. Recommended Immediate Next Step

Start with **Phase 1A** by scaffolding these files first:

- `backend/embedding_service.py`
- `backend/memory_persistence.py`
- `backend/milvus_store.py`
- `backend/memory_service.py`

Then wire health/config integration in `backend/main.py` before attempting ingestion or retrieval in the chat flow.

This sequence creates testable seams early and keeps risk out of the main request path until the underlying services are stable.
