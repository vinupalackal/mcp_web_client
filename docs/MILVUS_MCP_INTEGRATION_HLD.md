# High-Level Design Document
## Milvus Integration for MCP Client Web

**Project**: MCP Client Web  
**Feature**: Milvus Retrieval, Memory, and Safe Caching  
**Version**: 0.4.0-milvus-hld  
**Date**: March 30, 2026  
**Status**: Design Ready  
**Parent HLD**: HLD.md (v0.2.0-jsonrpc)  
**Requirements**: ../Milvus_MCP_Integration_Requirements.md (v2.0)  
**Related Analysis**: MILVUS_MCP_INTEGRATION_GAP_ANALYSIS.md

---

## 1. Executive Summary

This document describes the high-level design for integrating Milvus into the existing MCP Client Web application as an **optional memory subsystem**.

The design preserves the current architecture and user experience:

- the browser SPA remains the primary user interface,
- the FastAPI backend remains the orchestration boundary,
- the existing session/message APIs remain the public chat contract,
- the MCP manager remains the tool execution boundary,
- and Milvus is introduced as a supporting retrieval layer rather than a replacement runtime.

The first implementation phase focuses on **retrieval enrichment only**. The system will ingest selected code and documentation into Milvus, retrieve relevant context during chat synthesis, and degrade cleanly if Milvus is unavailable. Same-user conversation memory is designed but deferred to a later phase. Tool caching is intentionally postponed until explicit safety controls are in place.

### 1.1 Design Principles

- **Additive, non-breaking**: Existing chat behavior stays intact when memory is disabled.
- **Optional by configuration**: Milvus can be enabled, disabled, or rolled back without removing the feature code.
- **Retrieval first**: Start with low-risk enrichment before introducing long-term memory or cache reuse.
- **Scope-aware memory**: Same-user and workspace boundaries are mandatory for memory retrieval.
- **Hybrid storage**: Milvus stores vectors and light metadata; large raw payloads may live in sidecar storage.
- **Graceful degradation**: Core chat remains operational when Milvus or embeddings fail.

### 1.2 Design Intent

This HLD intentionally does **not** introduce:

- a second chat server,
- a mandatory WebSocket-only flow,
- cross-user memory recall,
- semantic-only tool-plan reuse,
- or Milvus as the primary runtime store for sessions.

---

## 2. Architecture Overview

### 2.1 Updated System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                User's Browser                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      Frontend (Vanilla JavaScript)                    │  │
│  │  ┌─────────────┐  ┌─────────────────────┐  ┌───────────────────────┐ │  │
│  │  │   Chat UI   │  │   Settings Modal    │  │   Optional Source UI  │ │  │
│  │  │  (app.js)   │  │   (settings.js)     │  │   retrieval badges    │ │  │
│  │  └─────────────┘  └─────────────────────┘  └───────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ HTTP REST
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FastAPI Backend Server                           │
│                                                                             │
│  ┌──────────────────────┐   ┌───────────────────────────────────────────┐  │
│  │ API Endpoints        │   │ Chat Orchestration Flow                   │  │
│  │ main.py              │   │ - session lookup                          │  │
│  │ /api/sessions        │   │ - message validation                      │  │
│  │ /api/sessions/*      │   │ - MCP tool execution                      │  │
│  │ /health              │   │ - retrieval enrichment (NEW)              │  │
│  └──────────────────────┘   │ - final synthesis                         │  │
│                             └───────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────┐   ┌───────────────────────────────────────────┐  │
│  │ Session Manager      │   │ Memory Service (NEW)                      │  │
│  │ in-memory runtime    │   │ - retrieval orchestration                 │  │
│  │ current session ctx  │   │ - conversation recall (future phase)      │  │
│  └──────────────────────┘   │ - fallback handling                       │  │
│                             │ - provenance capture                      │  │
│                             └───────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────┐   ┌───────────────────────────────────────────┐  │
│  │ MCP Manager          │   │ Embedding Service (NEW)                   │  │
│  │ JSON-RPC tool calls  │   │ - provider abstraction                    │  │
│  │ unchanged boundary   │   │ - dimension validation                    │  │
│  └──────────────────────┘   └───────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────┐   ┌───────────────────────────────────────────┐  │
│  │ LLM Client           │   │ Memory Persistence (NEW)                  │  │
│  │ synthesis models     │   │ - payload refs                            │  │
│  │ current providers    │   │ - ingestion jobs                          │  │
│  └──────────────────────┘   │ - audit/provenance                        │  │
│                             └───────────────────────────────────────────┘  │
└───────────────┬─────────────────────────┬───────────────────────────────────┘
                │                         │
                ▼                         ▼
┌─────────────────────────────┐   ┌─────────────────────────────────────────┐
│ MCP Servers                 │   │ Memory Infrastructure                    │
│ Existing JSON-RPC targets   │   │  ┌───────────────────────────────────┐  │
│ Tool discovery/execution    │   │  │ Milvus                            │  │
└─────────────────────────────┘   │  │ code_memory_v1                    │  │
                                  │  │ doc_memory_v1                     │  │
                                  │  │ conversation_memory_v1 (future)   │  │
                                  │  └───────────────────────────────────┘  │
                                  │  ┌───────────────────────────────────┐  │
                                  │  │ Sidecar Persistence               │  │
                                  │  │ SQLAlchemy + durable payload refs │  │
                                  │  └───────────────────────────────────┘  │
                                  └─────────────────────────────────────────┘
```

### 2.2 Component Delta from Base Application

| Component | Change | Description |
|-----------|--------|-------------|
| backend/main.py | Extended | Wires memory subsystem into startup, health, and chat orchestration |
| backend/session_manager.py | Extended | Optional retrieval trace summaries only; session runtime remains in memory |
| backend/llm_client.py | Extended | Embedding support exposed or reused via adapter |
| backend/database.py | Extended | Optional sidecar tables for payload refs, jobs, provenance |
| backend/mcp_manager.py | Unchanged | MCP communication remains the same |
| backend/static/app.js | Minor/optional | Source display or retrieval indicators only |
| backend/memory_service.py | New | Retrieval orchestration and fallback |
| backend/milvus_store.py | New | Milvus CRUD/search abstraction |
| backend/embedding_service.py | New | Embedding abstraction across providers |
| backend/ingestion_service.py | New | Code/doc indexing pipeline |
| backend/memory_persistence.py | New | Sidecar persistence and audit helpers |

---

## 3. Design Goals and Constraints

### 3.1 Functional Design Goals

1. Retrieve relevant code and documentation for synthesis.
2. Preserve current chat/session API contracts.
3. Support same-user, workspace-scoped long-term memory in a later phase.
4. Allow future safe caching without redesigning the architecture.
5. Provide clean fallback when the memory subsystem is unavailable.

### 3.2 Architectural Constraints

| Constraint | Source | Impact |
|---|---|---|
| Existing chat endpoints must remain primary | Current backend design | No new public-first chat protocol |
| Session state remains in memory | Current runtime | Milvus augments context, not session truth |
| MCP manager remains tool boundary | Existing codebase | Retrieval cannot bypass MCP execution semantics |
| SSO-aware ownership must be honored | Existing auth/user model | Memory must be user-scoped |
| localStorage and backend config patterns remain | Existing frontend/backend design | No second independent settings system |

### 3.3 Deferred-Risk Decisions

The following design decisions intentionally defer risk to later phases:

- conversation recall is same-user only,
- tool caching is not active in Phase 1,
- versioned collection cutover is used instead of destructive reindex,
- and semantic similarity is not treated as sufficient authority for cache reuse.

---

## 4. Component Design

### 4.1 Memory Service

The Memory Service is the backend-facing orchestration layer for retrieval features.

#### Responsibilities
- determine whether memory features are enabled,
- generate retrieval queries from user messages and optional tool-output hints,
- call the embedding service,
- run searches against Milvus via the Milvus store,
- assemble bounded retrieval results,
- record provenance and fallback reasons,
- and return normalized context blocks for synthesis.

#### Non-Responsibilities
- executing MCP tools,
- owning the active session state,
- formatting final assistant responses,
- or exposing a second public chat API.

#### Interface Sketch

```python
class MemoryService:
    async def enrich_for_turn(...):
        ...

    async def recall_conversation(...):
        ...

    async def health_status(...):
        ...
```

### 4.2 Milvus Store

The Milvus Store isolates all direct Milvus interaction from the rest of the backend.

#### Responsibilities
- connection lifecycle,
- collection existence checks,
- collection version selection,
- vector search,
- upsert/delete operations,
- index metadata awareness,
- and conversion between application models and Milvus records.

#### Design Rationale
- keeps Milvus-specific concerns out of `backend/main.py`,
- simplifies testing by allowing store mocking,
- and supports future collection version cutover logic in one place.

### 4.3 Embedding Service

The Embedding Service abstracts embedding generation away from chat completion logic.

#### Responsibilities
- provider-specific embedding API calls,
- model/dimension validation,
- batching behavior,
- timeout/error handling,
- and returning normalized embedding vectors.

#### Design Notes
- This abstraction is required because chat model selection and embedding model selection should not be assumed to be identical.
- It also creates a stable seam for future enterprise embedding backends.

### 4.4 Ingestion Service

The Ingestion Service is a background-oriented component for indexing code and documentation.

#### Responsibilities
- scanning configured roots,
- applying include/exclude policies,
- parsing code using tree-sitter or equivalent,
- chunking content,
- computing content hashes,
- generating payload references,
- requesting embeddings,
- and writing vectors plus metadata into Milvus.

#### Key Design Choice
Oversized semantic units are first identified structurally, then subdivided if necessary to improve retrieval precision and prompt efficiency.

### 4.5 Memory Persistence

The Memory Persistence layer stores artifacts that do not fit Milvus well.

#### Typical Sidecar Data
- raw chunk payloads,
- ingestion job records,
- retrieval provenance,
- cache provenance,
- and collection/version metadata.

#### Why Not Milvus for Everything
Milvus is a strong fit for vector search and lightweight filters, but not ideal as the only store for:

- large mutable payloads,
- audit records,
- administrative job state,
- or structured provenance queries.

---

## 5. Data Design

### 5.1 Storage Split

| Data | Primary Store | Why |
|---|---|---|
| Code/doc embeddings | Milvus | Fast semantic retrieval |
| Retrieval metadata | Milvus + sidecar | Lightweight filters in Milvus, richer audit in sidecar |
| Full chunk payloads | Sidecar persistence | Better update and size management |
| Session runtime state | Existing SessionManager | Preserves current chat flow |
| Conversation long-term summaries | Milvus + sidecar | Searchable memory with bounded raw storage |

### 5.2 Collection Versioning Strategy

The design uses **versioned collections** such as:

- `code_memory_v1`
- `doc_memory_v1`
- `conversation_memory_v1`
- `tool_cache_v1`

#### Rationale
- avoids drop-and-recreate downtime,
- supports safe migration to a new embedding model,
- allows shadow indexing before cutover,
- and supports rollback to a prior active version.

### 5.3 Payload Reference Strategy

Each indexed record stores a compact `payload_ref` instead of assuming the full raw body must live inside Milvus.

Possible backing implementations:

- SQL table rows,
- file-based blob store under a controlled data directory,
- or another durable structured store that the backend controls.

The HLD does not mandate one single payload backend for the first implementation, but it does require a stable dereference path and auditability.

---

## 6. Runtime Flows

### 6.1 Chat Turn with Retrieval Enrichment (Phase 1)

```
1. Browser sends user message to POST /api/sessions/{session_id}/messages
2. Backend validates session, user, and request body
3. Existing session history is gathered from SessionManager
4. MCP tools may execute as they do today
5. Before final synthesis, MemoryService checks feature flags
6. MemoryService builds retrieval query from user message + current-turn hints
7. EmbeddingService creates query embedding
8. MilvusStore searches code_memory_v1 and doc_memory_v1
9. MemoryService filters, caps, and formats retrieved context
10. LLM synthesis runs with session context + tool outputs + retrieved context
11. Response returns through existing ChatResponse contract
12. Retrieval provenance is logged and optionally added to session traces
```

### 6.2 Retrieval Failure Flow

```
1. Retrieval requested
2. Embedding or Milvus operation fails or times out
3. MemoryService marks retrieval as degraded for this turn
4. Backend continues synthesis without retrieved context
5. Response still returns successfully unless another non-memory failure occurs
6. Logs capture fallback reason and latency
```

### 6.3 Conversation Memory Flow (Phase 2)

```
1. Completed turn is summarized into a compact recallable representation
2. Summary is tagged with user_id, session_id, workspace_scope, and expiry
3. Summary embedding is written to conversation_memory_v1
4. On future turns, recall is limited to same-user scope by default
5. Returned memories are capped and injected as bounded synthesis context
```

### 6.4 Reindex Flow

```
1. Operator enables ingestion and points to configured roots
2. IngestionService scans and computes current manifest/hash state
3. New or changed chunks are embedded and written to target collection version
4. Deleted chunks are removed from the active target version
5. Validation confirms collection health and metadata counts
6. Active collection pointer is switched only after successful indexing
```

---

## 7. Detailed Design Decisions

### 7.1 Why Retrieval Is Placed Before Final Synthesis

Retrieval is intentionally placed after message acceptance and before the final synthesis call because:

- the current turn's user intent is already known,
- current-turn tool outputs can inform retrieval hints,
- and the existing orchestration structure can be extended without changing the public API.

This avoids building a separate planning service just to enable retrieval.

### 7.2 Why Session History Stays In-Memory

The current session manager already holds active conversational state and tool traces. Replacing it with Milvus would increase risk and create unnecessary coupling between ephemeral runtime state and long-term memory indexing.

The design therefore treats Milvus as a retrieval source, not the runtime authority for the active session.

### 7.3 Why Tool Cache Is Deferred

Tool outputs are often sensitive to:

- filesystem state,
- current repository state,
- external API freshness,
- active MCP server alias,
- user permissions,
- and request parameters that may look semantically similar but are not equivalent.

Because of this, Phase 1 excludes active tool caching and instead designs the extension points needed for a later safe implementation.

### 7.4 Why Cross-User Recall Is Disallowed

The current application already supports SSO-aware ownership. Cross-user memory reuse would require an explicit authorization model, audit requirements, and probably administrative controls. None of that is necessary for the first delivery.

The design therefore defaults to same-user recall only.

---

## 8. Failure Modes and Recovery

### 8.1 Failure Mode Matrix

| Failure | Expected Behavior | User Impact |
|---|---|---|
| Milvus unreachable at startup | Enter degraded mode if memory is optional | Chat still works |
| Milvus search timeout during turn | Fallback to no-retrieval synthesis | Slightly less enriched answer |
| Embedding provider failure | Skip retrieval for that turn | Chat still works |
| Ingestion parse failure on one file | Log and continue other files | Partial indexing only |
| Sidecar payload lookup failure | Omit affected context and log provenance issue | Partial retrieval degradation |
| Collection version mismatch | Reject activation or use last healthy version | No silent corruption |

### 8.2 Degraded Mode

Degraded mode is a first-class operating state, not an exceptional edge case.

#### In degraded mode:
- health reports memory as degraded,
- retrieval attempts are skipped or fail fast,
- chat endpoints still operate,
- and no user-facing contract change is required.

### 8.3 Recovery Design

Recovery paths include:

- automatic reuse of the last active healthy collection version,
- retryable ingestion jobs,
- explicit health visibility,
- and feature-flag rollback without schema destruction.

---

## 9. Security and Privacy Design

### 9.1 Ownership Boundaries

All long-term memory records must be scope-aware.

Minimum scope metadata:
- `user_id` when SSO/user identity exists,
- `session_id` for origin tracing,
- `workspace_scope` or equivalent repo boundary,
- and retention/expiry metadata where applicable.

### 9.2 Sensitive Data Handling

Potentially sensitive sources include:

- tool outputs,
- code snippets,
- user messages,
- documentation chunks,
- and model-enriched summaries.

#### Required controls
- avoid logging raw payloads by default,
- redact secrets when possible before persistence,
- keep diagnostic endpoints summary-first,
- and support deletion by source/session/user when implemented.

### 9.3 Administrative Exposure

If future `/api/memory/*` endpoints are added, they should:

- be diagnostic or administrative,
- avoid raw payload dumps by default,
- support pagination/filtering,
- and respect authentication/authorization when SSO is enabled.

---

## 10. Observability Design

### 10.1 Logging

The design uses the existing dual-logger backend pattern.

#### Internal logs should capture
- memory subsystem startup mode,
- retrieval latency,
- selected result counts,
- fallback reasons,
- ingestion job outcomes,
- and collection activation events.

#### External-style logs should capture
- diagnostic endpoint access where applicable,
- and health responses exposing subsystem status.

### 10.2 Trace and Audit Data

Optional trace/audit records may include:

- retrieval query metadata,
- selected chunk identifiers,
- collection version used,
- embedding model used,
- cache eligibility decisions,
- and degraded-mode reason codes.

### 10.3 Health Model

Health should expose at least:

- application core status,
- memory feature enabled/disabled state,
- Milvus reachability,
- embedding backend reachability,
- active collection version metadata.

The overall app health must remain healthy when the optional memory subsystem is degraded but the primary application is still functional.

---

## 11. Rollout Strategy

### 11.1 Phase 1 Rollout

Phase 1 introduces code/doc retrieval only.

#### Steps
1. Add feature flags and health status plumbing.
2. Implement Milvus connectivity and collection management.
3. Implement embedding service abstraction.
4. Add code/doc ingestion pipeline.
5. Integrate retrieval into the existing synthesis path.
6. Add logging and degraded fallback.
7. Run integration and performance validation.

### 11.2 Phase 2 Rollout

Phase 2 adds same-user conversation memory only after Phase 1 retrieval is stable.

### 11.3 Phase 3 Rollout

Phase 3 adds safe tool caching only for explicitly approved tool classes with deterministic scope and provenance.

### 11.4 Rollback Plan

Rollback is configuration-first:

- disable memory features,
- preserve indexed data and sidecar metadata,
- keep public APIs unchanged,
- and revert to current chat behavior without schema teardown.

---

## 12. Testing and Validation Strategy

### 12.1 Unit Test Focus

- Milvus store abstractions
- embedding service behavior
- retrieval result filtering and capping
- content hash / manifest change detection
- cache eligibility policy logic

### 12.2 Integration Test Focus

- retrieval enrichment through existing chat APIs
- degraded fallback when Milvus is unavailable
- SSO ownership boundaries for memory
- ingestion job behavior on mixed good/bad files
- health status reporting with memory enabled/disabled/degraded

### 12.3 Benchmark Focus

- retrieval latency contribution per turn
- prompt-size impact from injected context
- false-positive retrieval examples
- active collection cutover timing
- degraded fallback latency

---

## 13. Open Questions for Implementation

| ID | Question | Impact |
|---|---|---|
| OQ-01 | Should sidecar payload storage be SQL-only, file-backed, or hybrid in Phase 1? | Affects operational complexity |
| OQ-02 | Should source display be exposed in the UI in Phase 1 or backend-only first? | Affects frontend scope |
| OQ-03 | Which embedding backend should be primary for retrieval in enterprise mode? | Affects adapter scope |
| OQ-04 | What is the preferred operator workflow for ingestion: startup task, CLI command, admin endpoint, or background job? | Affects operational UX |
| OQ-05 | How should workspace scope be defined for non-SSO anonymous sessions? | Affects future conversation memory behavior |

---

## 14. Summary

The Milvus design for MCP Client Web is intentionally conservative.

It preserves the current application contract and introduces Milvus as a **supporting retrieval subsystem** rather than a new runtime core. The system starts with low-risk retrieval enrichment, keeps session runtime and tool execution boundaries intact, and prepares the architecture for later same-user memory and safe caching without forcing those risks into the first implementation.

That design makes Phase 1 implementable within the current repository while keeping rollback, observability, and ownership boundaries clear from the start.
