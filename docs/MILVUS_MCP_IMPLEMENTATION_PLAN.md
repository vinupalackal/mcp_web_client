# Milvus Integration Implementation Plan
## File-by-File Delivery Plan for MCP Client Web

**Project**: MCP Client Web  
**Feature**: Milvus Retrieval, Memory, and Safe Caching  
**Date**: March 30, 2026  
**Last Updated**: April 2, 2026  
**Status**: Phase 1–3 Complete · All Milestones Closed · Phase 4 Hardening Started  
**Requirements**: ../Milvus_MCP_Integration_Requirements.md  
**HLD**: MILVUS_MCP_INTEGRATION_HLD.md

---

## 0. GitHub Milestone Status

| # | Milestone | Issues | Status | Completed |
|---|-----------|--------|--------|-----------|
| M1 | Foundations | #1 #2 #3 #4 #5 | ✅ Closed | 5 / 5 |
| M2 | Milvus + Ingestion | #6 #7 #8 | ✅ Closed | 3 / 3 |
| M3 | Chat Integration | #9 #10 #11 #12 | ✅ Closed | 4 / 4 |
| M4 | Phase 1 Release | #13 #14 | ✅ Closed | 2 / 2 |
| M5 | Conversation Memory | #15 #16 | ✅ Closed | 2 / 2 |
| M6 | Safe Tool Cache | #17 #18 | ✅ Closed | 2 / 2 |

### Phase 4 Progress

- ✅ Expiry cleanup implemented for expired conversation-memory sidecar rows and vector rows.
- ✅ Expiry cleanup implemented for expired tool-cache sidecar rows and vector rows.
- ✅ Manual admin maintenance endpoint added for on-demand cleanup runs.
- ✅ Operational documentation added for cleanup cadence, retention, TTL, and health visibility.

---

## 0.1 Before / After: Code Changes and Feature Differences

This section summarises what changed in each delivered milestone compared to the
pre-Milvus baseline.

### Baseline (pre-M1)
- Chat flow: `POST /api/sessions/{id}/messages` → LLM → tool calls → response.
- No vector storage, no semantic retrieval, no conversation memory.
- `backend/database.py` held only user/settings/server tables.
- `backend/session_manager.py` held only message history.
- No `backend/memory_service.py`, `backend/milvus_store.py`, `backend/embedding_service.py`, or `backend/memory_persistence.py`.
- `ChatResponse` had no `context_sources` field.
- Frontend showed no retrieval indicator.

---

### M1 – Foundations (Issues #1–#5)  ✅

**Files added / changed**

| File | Before | After |
|------|--------|-------|
| `backend/embedding_service.py` | *(new)* | Provider-normalized embedding with batching, dimension validation, and timeout handling |
| `backend/milvus_store.py` | *(new)* | Collection lifecycle, upsert, search, delete-by-id/filter for `code_memory`, `doc_memory`, `conversation_memory`, `tool_cache` |
| `backend/memory_persistence.py` | *(new)* | SQLAlchemy adapter for 4 sidecar tables (payload refs, ingestion jobs, collection versions, retrieval provenance) |
| `backend/memory_service.py` | *(new)* | `MemoryService` scaffold with `MemoryServiceConfig`, `RetrievalResult`, `RetrievalBlock`; Phase 1 retrieval orchestration stub |
| `backend/database.py` | 4 user/settings tables | + `memory_payload_refs`, `memory_ingestion_jobs`, `memory_collection_versions`, `memory_retrieval_provenance` |
| `backend/main.py` | No memory config | `MILVUS_*` env-var config plumbing; `_memory_service` module-level handle; health endpoint reports `disabled`/`healthy`/`degraded` |

**Feature difference**: Milvus subsystem is wired but entirely feature-flagged off by default. All existing behavior is unchanged.

---

### M2 – Milvus + Ingestion (Issues #6–#8)  ✅

**Files added / changed**

| File | Before | After |
|------|--------|-------|
| `backend/ingestion_service.py` | *(new)* | Background scan of repo/doc roots; tree-sitter symbol parsing; semantic chunking; content-hash manifest; stale deletion |
| `backend/milvus_store.py` | Struct only | Validated schema + index creation; `ensure_collection` idempotent; `delete_by_filter` for incremental refresh |
| `backend/memory_persistence.py` | Stubs | `create_ingestion_job`, `update_ingestion_job`, `create_collection_version`, `activate_collection_version` fully implemented |

**Feature difference**: Operators can run ingestion via background task; `code_memory_v1` and `doc_memory_v1` collections are populated and version-tracked.

---

### M3 – Chat Integration (Issues #9–#12)  ✅

**Files added / changed**

| File | Before | After |
|------|--------|-------|
| `backend/memory_service.py` | Scaffold | `enrich_for_turn()` fully implemented: embed query → vector search across code/doc collections → cap → normalize blocks → record provenance |
| `backend/session_manager.py` | Message history only | + `add_retrieval_trace()`, `get_retrieval_traces()` |
| `backend/main.py` | No retrieval in chat | `enrich_for_turn()` called before LLM; context injected into `messages_for_llm`; retrieval trace recorded per turn |
| `tests/backend/integration/` | No retrieval tests | `test_memory_retrieval_flow.py`, `test_memory_degraded_mode.py`, `test_memory_health_api.py` added |

**Feature difference**: Chat responses are now optionally enriched with relevant code/doc snippets from Milvus. Retrieval failures degrade gracefully without breaking the response path.

---

### M4 – Phase 1 Release (Issues #13–#14)  ✅

**Files added / changed**

| File | Before | After |
|------|--------|-------|
| `backend/models.py` | `ChatResponse` had no `context_sources` | Added `context_sources: Optional[List[Dict[str, Any]]] = None` |
| `backend/main.py` | `ChatResponse` did not include retrieval metadata | Builds `retrieval_sources` list from `RetrievalBlock` fields; passes as `context_sources` in all `ChatResponse` returns |
| `backend/static/app.js` | `addMessage()` had no retrieval parameter | Added `contextSources` param; renders collapsible `<details class="retrieval-sources-details">` when sources are present |
| `backend/static/style.css` | No retrieval classes | Added `.retrieval-sources-details`, `.retrieval-source-item`, `.retrieval-source-collection`, `.retrieval-source-path` with light/dark/teal theme variants |
| `README.md` | No Milvus section | Added `## Memory-Augmented Retrieval (Optional)` with prerequisites, quick-start, env var table, and frontend indicator note |
| `tests/frontend/test_chat_ui.test.js` | No retrieval indicator tests | Added TC-FE-RETRIEVAL-01 through TC-FE-RETRIEVAL-04 |

**Feature difference**: The frontend now shows a collapsible "Sources" indicator below assistant messages when retrieval was used. API consumers receive `context_sources` in `ChatResponse`.

---

### M5 – Conversation Memory (Issues #15–#16)  ✅

**Files added / changed**

| File | Before | After |
|------|--------|-------|
| `backend/database.py` | 4 sidecar tables | + `memory_conversation_turns` with `user_id`, `session_id`, `workspace_scope`, `turn_number`, `user_message`, `assistant_summary`, `tool_names_json`, `expires_at` |
| `backend/memory_persistence.py` | No conversation methods | + `record_conversation_turn()`, `get_conversation_turns()` (user/scope/expiry filters), `expire_conversation_turns()` |
| `backend/memory_service.py` | `MemoryServiceConfig` had no conversation fields; `enrich_for_turn()` had no user context; no `record_turn()` | + `enable_conversation_memory`, `conversation_retention_days` config fields; `enrich_for_turn()` accepts `user_id` + `workspace_scope`; adds `conversation_memory` to search when enabled; `record_turn()` embeds + upserts turn post-response; `_build_conversation_filter_expression()` always scopes to same `user_id` |
| `backend/main.py` | `enrich_for_turn()` called without `user_id`; no post-response recording | Passes `user_id=user_id or ""`; calls `record_turn()` after both successful `ChatResponse` assembly points |
| `tests/backend/unit/test_memory_service.py` | Phase 1 tests only | + 9 TC-CONV-* cases (record_turn, same-user recall, cross-user blocking, filter correctness) |
| `tests/backend/unit/test_conversation_memory.py` | *(new)* | 12 TC-CMEM-* retention and scope tests (expiry, same-user, cross-user, workspace isolation, limit, safety guards) |

**Feature difference**: Authenticated users' conversation exchanges are embedded and stored in the `conversation_memory` Milvus collection after each turn. Future turns for the same user automatically recall relevant prior context. Cross-user recall is architecturally impossible: the Milvus filter expression always includes `user_id == "<caller>"` and an empty user ID produces a blocking filter (`user_id == "__none__"`). Anonymous sessions are silently skipped.

---

### M6 – Safe Tool Cache (Issues #17–#18)  ✅

**Files added / changed**

| File | Before | After |
|------|--------|-------|
| `backend/database.py` | 5 sidecar tables | + `memory_tool_cache` with `tool_name`, `normalized_params_hash`, `scope_hash`, `result_text`, `is_cacheable`, `expires_at`; unique constraint on `(tool_name, params_hash, scope_hash)` |
| `backend/memory_persistence.py` | No tool cache methods | + `record_tool_cache_entry()` (upsert), `get_tool_cache_entry()` (with expiry filter), `expire_tool_cache_entries()` (by tool/scope/age; safety guard requires ≥1 filter) |
| `backend/memory_service.py` | No cache config or methods | + `enable_tool_cache`, `tool_cache_ttl_s`, `tool_cache_allowlist` in `MemoryServiceConfig`; `ToolCacheResult` dataclass; `lookup_tool_cache()` (pure hash lookup, no vector search); `record_tool_cache()` (fails silently); `_build_params_hash()` (sorted-JSON SHA-256); `_build_cache_scope_hash()` (user+workspace SHA-256; anonymous → `__anonymous__`) |
| `backend/main.py` | No cache env vars or wiring | `MEMORY_TOOL_CACHE_ENABLED`, `MEMORY_TOOL_CACHE_TTL_S`, `MEMORY_TOOL_CACHE_ALLOWLIST` wired into lifespan; cache lookup before `execute_tool()`; `record_tool_cache()` called after successful execution |
| `tests/backend/unit/test_memory_service.py` | Phase 1–2 tests | + 12 TC-CACHE-* service-layer policy tests |
| `tests/backend/unit/test_tool_cache.py` | *(new)* | 12 TC-TCACHE-* persistence-layer tests (round-trip, expiry, scope isolation, upsert, safety guards) |

**Feature difference**: Tool results for explicitly allowlisted tools are cached in the `tool_cache` Milvus collection after successful execution. Future calls with the same tool name, identical normalized arguments, and same user/workspace scope receive the cached result immediately — skipping MCP server round-trips. Similarity is never used to authorize a cache hit; only an exact `(tool_name, params_hash, scope_hash)` triple matches. Non-allowlisted tools are never cached regardless of any other configuration.

---

### Phase 4 – Operations Hardening (ongoing)  ✅ partial

**Files added / changed**

| File | Before | After |
|------|--------|-------|
| `backend/memory_service.py` | Expired rows depended on opportunistic reads/manual deletion | Added `run_expiry_cleanup_if_due()` with interval gating, startup cleanup, request-time cleanup, and cleanup status in health payload |
| `backend/memory_persistence.py` | Cleanup only by age filters | Added `expired_as_of` support for direct expiry-based deletion in both conversation-memory and tool-cache cleanup methods |
| `backend/main.py` | No manual maintenance API | Added admin-only `POST /api/admin/memory/maintenance` endpoint with selective cleanup targets and `force` support |
| `backend/models.py` | No maintenance endpoint models | Added `MemoryMaintenanceRequest` and `MemoryMaintenanceResponse` for OpenAPI-driven admin operations |
| `README.md` | Cleanup documented only as automatic background behavior | Added explicit operator docs for the manual maintenance endpoint |
| `tests/backend/integration/test_memory_maintenance_api.py` | *(new)* | Added 5 endpoint tests covering 503, success, 401, 403, and admin success |

**Feature difference**: Operators can now trigger expiry cleanup on demand through a typed admin API instead of waiting for the periodic cleanup interval. This makes retention changes and incident-response cleanup immediate and observable, while still preserving fail-open behavior for the normal chat path.

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

### Related References
- See `docs/M3-CHAT-WIRING-REQUIREMENTS.md` for the issue-level requirements.
- See `docs/M3-CHAT-WIRING-HLD.md` for the chat-wiring design.
- See `docs/M3-CHAT-WIRING-IMPLEMENTATION-SPEC.md` for the implementation-ready integration breakdown.

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

### Related References
- See `docs/M1-MEMORY-CONFIG-DIAGNOSTICS-REQUIREMENTS.md` for the issue-level requirements.
- See `docs/M1-MEMORY-CONFIG-DIAGNOSTICS-HLD.md` for the model-layer design.
- See `docs/M1-MEMORY-CONFIG-DIAGNOSTICS-IMPLEMENTATION-SPEC.md` for the implementation-ready model breakdown.
- See `docs/PYDANTIC-VS-SQLALCHEMY-IN-THIS-REPO.md` for a repo-specific explanation of the API-schema vs database-model split.

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

### Related Reference
- See `docs/M1-SIDECAR-SCHEMA-DELTA.md` for the before/after table inventory and schema delta summary introduced by M1 issue #2.

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

### Related References
- See `docs/M3-TRACE-HELPERS-REQUIREMENTS.md` for the issue-level requirements.
- See `docs/M3-TRACE-HELPERS-HLD.md` for the trace-helper design.
- See `docs/M3-TRACE-HELPERS-IMPLEMENTATION-SPEC.md` for the implementation-ready method breakdown.

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

### Related References
- See `docs/M3-RETRIEVAL-SERVICE-REQUIREMENTS.md` for the issue-level requirements.
- See `docs/M3-RETRIEVAL-SERVICE-HLD.md` for the retrieval-service design.
- See `docs/M3-RETRIEVAL-SERVICE-IMPLEMENTATION-SPEC.md` for the implementation-ready module breakdown.

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

### Related References
- See `docs/M2-MILVUS-STORE-REQUIREMENTS.md` for the issue-level requirements.
- See `docs/M2-MILVUS-STORE-HLD.md` for the store-layer design.
- See `docs/M2-MILVUS-STORE-IMPLEMENTATION-SPEC.md` for the implementation-ready module breakdown.

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

### Related References
- See `docs/M1-EMBEDDING-SUPPORT-REQUIREMENTS.md` for the issue-level requirements.
- See `docs/M1-EMBEDDING-SUPPORT-HLD.md` for the embedding-layer design.
- See `docs/M1-EMBEDDING-SUPPORT-IMPLEMENTATION-SPEC.md` for the implementation-ready module breakdown.

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

### Related References
- See `docs/M2-INGESTION-PIPELINE-REQUIREMENTS.md` for the issue-level requirements.
- See `docs/M2-INGESTION-PIPELINE-HLD.md` for the ingestion-layer design.
- See `docs/M2-INGESTION-PIPELINE-IMPLEMENTATION-SPEC.md` for the implementation-ready pipeline breakdown.

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

### Related References
- See `docs/M1-MEMORY-PERSISTENCE-REQUIREMENTS.md` for the issue-level requirements.
- See `docs/M1-MEMORY-PERSISTENCE-HLD.md` for the adapter-layer design.
- See `docs/M1-MEMORY-PERSISTENCE-IMPLEMENTATION-SPEC.md` for the implementation-ready method breakdown.

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

**Issue #8 additions** — see `docs/M2-COVERAGE-REQUIREMENTS.md`, `docs/M2-COVERAGE-HLD.md`, `docs/M2-COVERAGE-IMPLEMENTATION-SPEC.md`:
- excluded dirs are never scanned
- empty workspace produces completed/zero-chunk status
- unchanged file is not stale on second run
- `collection_generation` propagates to every store call

#### `tests/backend/unit/test_ingestion_store_integration.py` (new, issue #8)
- generation rollover: v1 and v2 produce distinct collections
- stale cleanup targets the correct generation
- payload_refs are consistent between persistence and store layers

#### `tests/backend/unit/test_memory_service.py` (new)
- retrieval enable/disable behavior
- degraded fallback behavior
- provenance shaping
- result capping

**Issue #9 references** — see `docs/M3-RETRIEVAL-SERVICE-REQUIREMENTS.md`, `docs/M3-RETRIEVAL-SERVICE-HLD.md`, `docs/M3-RETRIEVAL-SERVICE-IMPLEMENTATION-SPEC.md`

### Integration Tests

#### `tests/backend/integration/test_memory_health_api.py` (new)
- health when memory disabled
- health when memory enabled and healthy
- health when memory enabled and degraded

**Issue #12 references** — see `docs/M3-INTEGRATION-TESTS-REQUIREMENTS.md`, `docs/M3-INTEGRATION-TESTS-HLD.md`, `docs/M3-INTEGRATION-TESTS-IMPLEMENTATION-SPEC.md`

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

### Issue-Level References
- Issue #9: `docs/M3-RETRIEVAL-SERVICE-REQUIREMENTS.md`, `docs/M3-RETRIEVAL-SERVICE-HLD.md`, `docs/M3-RETRIEVAL-SERVICE-IMPLEMENTATION-SPEC.md`
- Issue #10: `docs/M3-CHAT-WIRING-REQUIREMENTS.md`, `docs/M3-CHAT-WIRING-HLD.md`, `docs/M3-CHAT-WIRING-IMPLEMENTATION-SPEC.md`
- Issue #11: `docs/M3-TRACE-HELPERS-REQUIREMENTS.md`, `docs/M3-TRACE-HELPERS-HLD.md`, `docs/M3-TRACE-HELPERS-IMPLEMENTATION-SPEC.md`
- Issue #12: `docs/M3-INTEGRATION-TESTS-REQUIREMENTS.md`, `docs/M3-INTEGRATION-TESTS-HLD.md`, `docs/M3-INTEGRATION-TESTS-IMPLEMENTATION-SPEC.md`

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
