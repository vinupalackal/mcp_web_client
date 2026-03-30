# Milvus Integration Requirements for MCP Client Web
## Repo-Aligned Requirements for Retrieval, Memory, and Safe Caching

---

| Field | Value |
|---|---|
| Document Version | 2.0 |
| Status | Implementation Ready |
| Date | March 30, 2026 |
| System | MCP Client Web + Optional Milvus Memory Layer |
| Primary Repo | `mcp_client` |
| Runtime Alignment | Existing FastAPI backend + vanilla JavaScript SPA |

---

## Table of Contents

1. [Purpose and Goals](#1-purpose-and-goals)
2. [Current System Alignment](#2-current-system-alignment)
3. [Scope Boundaries](#3-scope-boundaries)
4. [Target Architecture](#4-target-architecture)
5. [Storage and Data Model Requirements](#5-storage-and-data-model-requirements)
6. [Functional Requirements](#6-functional-requirements)
7. [Non-Functional Requirements](#7-non-functional-requirements)
8. [Configuration Requirements](#8-configuration-requirements)
9. [Implementation File Plan](#9-implementation-file-plan)
10. [Phased Delivery Plan](#10-phased-delivery-plan)
11. [Acceptance and Test Requirements](#11-acceptance-and-test-requirements)
12. [Glossary](#12-glossary)

---

## 1. Purpose and Goals

This document defines the implementation-ready requirements for integrating Milvus into the existing MCP Client Web repository as an **optional retrieval, memory, and cache subsystem**.

This version replaces the earlier greenfield design assumptions with requirements that fit the current application architecture:

- FastAPI backend in `backend/main.py`
- in-memory session runtime in `backend/session_manager.py`
- JSON-RPC MCP execution in `backend/mcp_manager.py`
- LLM provider adapters in `backend/llm_client.py`
- optional relational persistence through `backend/database.py`
- vanilla JavaScript SPA in `backend/static/`

### 1.1 Primary Goals

- **Improve answer quality** by retrieving relevant code and documentation context.
- **Preserve existing chat behavior** by integrating behind current session/message APIs.
- **Add bounded long-term memory** with explicit user and workspace scoping.
- **Reduce repeated work safely** through conservative, policy-driven caching.
- **Degrade gracefully** when Milvus or embedding services are unavailable.

### 1.2 Non-Goals for Initial Implementation

- Replacing the current session manager with Milvus.
- Replacing the current chat flow with a new standalone chat server.
- Making WebSocket chat mandatory.
- Caching all tools by default.
- Allowing cross-user semantic memory retrieval.
- Storing all large raw artifacts directly in Milvus as the sole source of truth.

---

## 2. Current System Alignment

The requirements in this document are constrained by the current repository behavior and must not introduce a second parallel application architecture.

### 2.1 Existing Application Shape

| Area | Current Implementation | Requirement Constraint |
|---|---|---|
| Chat entrypoints | Session-based APIs in `backend/main.py` | Milvus must integrate behind existing APIs first |
| Session runtime | In-memory `SessionManager` | Milvus augments retrieval, not primary runtime state |
| Tool execution | JSON-RPC via `mcp_manager.py` | MCP manager remains the tool execution boundary |
| LLM providers | OpenAI, Ollama, Mock, Enterprise-compatible flows | Embedding support must respect provider differences |
| User scope | Single-user and SSO-backed user-aware flows | Memory retrieval must honor user boundaries |
| Persistence | JSON files + SQLAlchemy-backed database helpers | Raw payload metadata and audit records may use existing DB layer |

### 2.2 Mandatory Alignment Rules

| ID | Requirement | Priority |
|---|---|---|
| ALN-01 | The primary user chat flow must continue to use `POST /api/sessions` and `POST /api/sessions/{session_id}/messages`. | Must Have |
| ALN-02 | Existing frontend chat behavior in `backend/static/app.js` must continue to function without requiring WebSocket transport. | Must Have |
| ALN-03 | Milvus integration must be optional and controlled by configuration. | Must Have |
| ALN-04 | If Milvus is disabled or unavailable, the application must continue operating with current non-Milvus behavior. | Must Have |
| ALN-05 | The integration must not introduce a second standalone chat server inside this repository. | Must Have |
| ALN-06 | New persistence for audit records or payload references should reuse the existing SQLAlchemy database layer in `backend/database.py` where practical. | Should Have |

---

## 3. Scope Boundaries

### 3.1 In Scope for Initial Delivery

- Milvus-backed semantic retrieval for code memory and document memory.
- Optional same-user conversation memory retrieval.
- Background ingestion pipeline for selected code and documentation roots.
- Retrieval enrichment in the existing LLM synthesis flow.
- Health reporting and graceful fallback when retrieval is unavailable.
- Conservative cache design interfaces for future tool caching.

### 3.2 Deferred Scope

- Semantic tool plan reuse that skips planning automatically.
- Semantic tool output reuse for all tools.
- Cross-user memory retrieval.
- Mandatory WebSocket-first chat flow.
- Hard dependency on Ubuntu-only deployment.
- Milvus cluster deployment or multi-tenant isolation inside Milvus.

### 3.3 Delivery Priorities

| Phase | Capability | Priority |
|---|---|---|
| Phase 1 | Code/doc retrieval enrichment | Must Have |
| Phase 2 | Same-user conversation memory | Should Have |
| Phase 3 | Safe, allowlisted tool cache | Future |
| Phase 4 | Evaluation-driven optimization and migration tooling | Future |

---

## 4. Target Architecture

Milvus is a supporting subsystem, not the center of the runtime architecture.

### 4.1 High-Level Architecture

| Layer | Component | Current/Proposed | Role |
|---|---|---|---|
| Presentation | Browser SPA (`backend/static/`) | Current | Chat UI, settings UI, optional retrieval/source display |
| API | FastAPI (`backend/main.py`) | Current | Session creation, message processing, health, admin APIs |
| Orchestration | Chat/message processing in backend | Current + extended | Coordinates history, MCP tool execution, retrieval, and LLM calls |
| Retrieval | Milvus-backed memory service | Proposed | Semantic search over code/docs/conversation memory |
| Metadata / audit | SQLAlchemy-backed sidecar storage | Current + extended | Payload refs, provenance, audit trails, ingestion jobs |
| MCP execution | `backend/mcp_manager.py` | Current | Tool discovery and execution |
| LLM / embeddings | `backend/llm_client.py` + embedding adapter | Current + extended | Chat completions and embeddings |

### 4.2 Architectural Principles

| ID | Requirement | Priority |
|---|---|---|
| ARC-01 | Retrieval must be invoked from the existing chat orchestration flow, not from a parallel server. | Must Have |
| ARC-02 | Milvus must store vectors and lightweight retrieval metadata; large raw payloads should be referenced via sidecar storage when practical. | Must Have |
| ARC-03 | MCP tool execution must remain the responsibility of the existing MCP manager. | Must Have |
| ARC-04 | LLM synthesis must remain the responsibility of the existing LLM client flow. | Must Have |
| ARC-05 | Retrieval and caching decisions must be observable through backend logs and optional session trace events. | Must Have |
| ARC-06 | New memory features must be feature-flagged to allow phased rollout and rollback. | Must Have |

### 4.3 API Boundary Requirements

| ID | Requirement | Priority |
|---|---|---|
| API-01 | `POST /api/sessions` request and response contracts must remain backward compatible. | Must Have |
| API-02 | `POST /api/sessions/{session_id}/messages` request and response contracts must remain backward compatible. | Must Have |
| API-03 | `GET /health` must continue to report core app health even when Milvus is degraded or disabled. | Must Have |
| API-04 | If additional memory-specific endpoints are added, they must be optional administrative or diagnostic endpoints under `/api/memory/*`. | Should Have |
| API-05 | Initial implementation must not require a new public `POST /chat` endpoint. | Must Have |
| API-06 | Initial implementation must not require a new public `WS /ws/{session_id}` endpoint. | Must Have |

---

## 5. Storage and Data Model Requirements

### 5.1 Storage Strategy

The storage model must be split by responsibility.

| Data Type | Required Store | Notes |
|---|---|---|
| Embeddings + retrieval metadata | Milvus | Primary vector similarity store |
| Raw code/doc payloads | File system or SQL sidecar | Chunks may be stored outside Milvus if large |
| Runtime session state | Existing in-memory session manager | No replacement in Phase 1 |
| Audit/provenance records | Existing SQLAlchemy DB layer or equivalent | Used for cache safety, debug, and ingestion state |
| User/server/LLM config | Existing repo mechanisms | No second configuration system |

### 5.2 Milvus Collection Requirements

The initial implementation must use versioned collection names instead of hard-coding permanent schema names.

| Collection | Purpose | Phase |
|---|---|---|
| `code_memory_v1` | Semantic retrieval of indexed code chunks | Phase 1 |
| `doc_memory_v1` | Semantic retrieval of indexed documentation chunks | Phase 1 |
| `conversation_memory_v1` | Same-user long-term conversation recall | Phase 2 |
| `tool_cache_v1` | Allowlisted tool cache candidates with provenance | Phase 3 |

### 5.3 Milvus Schema Requirements

#### `code_memory_v1`

| Field | Type | Description |
|---|---|---|
| `id` | VARCHAR / primary identifier | Stable chunk identifier |
| `embedding` | FLOAT_VECTOR | Embedding vector for retrieval |
| `repo_id` | VARCHAR | Logical repository or workspace identifier |
| `relative_path` | VARCHAR | Workspace-relative source path |
| `symbol_name` | VARCHAR | Function/class/struct/enum identifier |
| `symbol_kind` | VARCHAR | `function`, `class`, `struct`, `enum`, `namespace`, `method` |
| `language` | VARCHAR | `c` or `cpp` |
| `namespace` | VARCHAR | Namespace chain if available |
| `signature` | VARCHAR | Symbol declaration or signature text |
| `summary` | VARCHAR | Compact retrieval summary |
| `payload_ref` | VARCHAR | Reference to full raw chunk payload |
| `source_hash` | VARCHAR | Stable content hash for change detection |
| `start_line` | INT64 | Start line |
| `end_line` | INT64 | End line |
| `updated_at` | INT64 | Last indexed timestamp |

#### `doc_memory_v1`

| Field | Type | Description |
|---|---|---|
| `id` | VARCHAR / primary identifier | Stable chunk identifier |
| `embedding` | FLOAT_VECTOR | Embedding vector |
| `repo_id` | VARCHAR | Logical repository or workspace identifier |
| `source_type` | VARCHAR | `readme`, `requirements`, `architecture`, `runbook`, `guide`, `other` |
| `source_path` | VARCHAR | Workspace-relative path or logical source identifier |
| `section` | VARCHAR | Heading or section label |
| `summary` | VARCHAR | Compact retrieval summary |
| `payload_ref` | VARCHAR | Reference to full raw text |
| `source_hash` | VARCHAR | Stable content hash |
| `updated_at` | INT64 | Last indexed timestamp |

#### `conversation_memory_v1`

| Field | Type | Description |
|---|---|---|
| `id` | VARCHAR / primary identifier | Turn memory identifier |
| `embedding` | FLOAT_VECTOR | Embedding of summarized user intent / turn |
| `user_id` | VARCHAR | Owning user identifier |
| `session_id` | VARCHAR | Origin session identifier |
| `workspace_scope` | VARCHAR | Repo/workspace scope |
| `turn_number` | INT64 | Order within session |
| `user_message` | VARCHAR | Original user message or compact form |
| `assistant_summary` | VARCHAR | Short summary of the assistant response |
| `tool_names` | VARCHAR | Comma-separated or normalized tool list |
| `payload_ref` | VARCHAR | Reference to optional full turn payload |
| `created_at` | INT64 | Creation timestamp |
| `expires_at` | INT64 | Optional expiry timestamp |

#### `tool_cache_v1` (Future Scope)

| Field | Type | Description |
|---|---|---|
| `id` | VARCHAR / primary identifier | Cache entry identifier |
| `embedding` | FLOAT_VECTOR | Optional semantic ranking vector |
| `tool_name` | VARCHAR | Executed tool name |
| `server_alias` | VARCHAR | Source MCP server alias |
| `normalized_params_hash` | VARCHAR | Deterministic hash of normalized arguments |
| `scope_hash` | VARCHAR | Hash of cache scope context |
| `payload_ref` | VARCHAR | Reference to cached output |
| `created_at` | INT64 | Creation time |
| `expires_at` | INT64 | TTL expiry |
| `source_version` | VARCHAR | Tool/server/provenance version |
| `is_cacheable` | BOOL | Explicit allowlist outcome |

### 5.4 Sidecar Persistence Requirements

| ID | Requirement | Priority |
|---|---|---|
| DATA-01 | Full raw payloads for code/doc chunks may be stored outside Milvus when size or update behavior makes Milvus storage inefficient. | Must Have |
| DATA-02 | Payload references stored in Milvus must resolve to a durable backing store. | Must Have |
| DATA-03 | Audit records for ingestion jobs, cache decisions, and retrieval provenance should use the existing SQLAlchemy-backed database layer where practical. | Should Have |
| DATA-04 | Embedding/index version must be tracked per collection generation. | Must Have |
| DATA-05 | The system must support reindexing into a new versioned collection without requiring immediate deletion of the old collection. | Must Have |

---

## 6. Functional Requirements

### 6.1 Configuration and Startup

| ID | Requirement | Priority |
|---|---|---|
| FR-CFG-01 | Milvus memory features must be disabled by default via configuration. | Must Have |
| FR-CFG-02 | When memory is disabled, the application must start and behave as it does today. | Must Have |
| FR-CFG-03 | When memory is enabled but Milvus is unreachable at startup, the application must enter degraded mode instead of refusing to start. | Must Have |
| FR-CFG-04 | Health reporting must expose memory subsystem status as `disabled`, `healthy`, or `degraded`. | Must Have |
| FR-CFG-05 | Embedding configuration must be explicit and independent from chat model selection when necessary. | Must Have |
| FR-CFG-06 | Memory features must be independently toggleable: `retrieval`, `conversation_memory`, `tool_cache`, and `ingestion`. | Should Have |

### 6.2 Retrieval Enrichment

| ID | Requirement | Priority |
|---|---|---|
| FR-RET-01 | Before final synthesis, the backend should optionally retrieve relevant code and documentation context from Milvus when memory retrieval is enabled. | Must Have |
| FR-RET-02 | Retrieval must be driven by the current user query plus optional tool-output-derived hints from the current turn. | Must Have |
| FR-RET-03 | Code retrieval must support metadata filtering by `repo_id`, `relative_path`, `language`, and `symbol_kind` where available. | Must Have |
| FR-RET-04 | Document retrieval must support metadata filtering by `repo_id` and `source_type`. | Must Have |
| FR-RET-05 | Retrieved context must be bounded by configurable limits to control prompt size. | Must Have |
| FR-RET-06 | If retrieval fails, synthesis must continue without retrieved memory rather than failing the user request. | Must Have |
| FR-RET-07 | The system must record retrieval provenance, including which chunks were selected and why. | Should Have |

### 6.3 Conversation Memory

| ID | Requirement | Priority |
|---|---|---|
| FR-CONV-01 | The current session history remains sourced from the existing in-memory session manager. | Must Have |
| FR-CONV-02 | Long-term conversation recall, if enabled, must be same-user only by default. | Must Have |
| FR-CONV-03 | Long-term conversation recall must support additional workspace or repository scoping when available. | Must Have |
| FR-CONV-04 | Cross-user memory retrieval must be disallowed unless a future explicit policy and access model are implemented. | Must Have |
| FR-CONV-05 | Retrieved conversation memories must be capped by count and token budget. | Must Have |
| FR-CONV-06 | Conversation memories must support retention and expiry policies. | Should Have |
| FR-CONV-07 | When SSO is disabled and no stable user identity exists, the implementation may restrict long-term memory to session-only or explicitly configured anonymous scope. | Must Have |

### 6.4 Code Ingestion

| ID | Requirement | Priority |
|---|---|---|
| FR-ING-01 | The ingestion pipeline must support C and C++ source/header files from configured roots. | Must Have |
| FR-ING-02 | Preferred parsing strategy is tree-sitter or equivalent AST-aware parsing. | Must Have |
| FR-ING-03 | Code must be chunked at semantic boundaries first, then subdivided when a symbol is too large for effective retrieval. | Must Have |
| FR-ING-04 | Each chunk must capture workspace-relative path, symbol metadata, and stable source hash. | Must Have |
| FR-ING-05 | The pipeline must skip generated and irrelevant directories such as `.git/`, `build/`, `dist/`, `vendor/`, `third_party/`, `_deps/`, and `CMakeFiles/` by default. | Must Have |
| FR-ING-06 | The pipeline must support incremental reindexing using content hashes or manifest state; file mtime alone is insufficient as the sole source of truth. | Must Have |
| FR-ING-07 | The pipeline must detect deletions and remove stale chunks from active indexes. | Must Have |
| FR-ING-08 | Ingestion failures must be logged with file path and parser reason without aborting the entire ingestion job. | Must Have |
| FR-ING-09 | Oversized chunks must be summarized or split to protect retrieval precision and prompt size. | Should Have |

### 6.5 Document Ingestion

| ID | Requirement | Priority |
|---|---|---|
| FR-DOC-01 | The ingestion pipeline must support Markdown, plaintext, and other configured document sources relevant to the repository. | Must Have |
| FR-DOC-02 | Documents must be chunked by structural boundaries such as headings or sections where possible. | Must Have |
| FR-DOC-03 | Each chunk must capture source path, source type, section name, content hash, and payload reference. | Must Have |
| FR-DOC-04 | Documentation ingestion must support incremental refresh and deletion of stale chunks. | Must Have |

### 6.6 Chat Orchestration Integration

| ID | Requirement | Priority |
|---|---|---|
| FR-CHAT-01 | The backend message-processing flow must be able to call retrieval services during assistant response generation. | Must Have |
| FR-CHAT-02 | Retrieval should be invoked after the user message is accepted and before the final synthesis call. | Must Have |
| FR-CHAT-03 | Tool outputs from the current turn may contribute retrieval hints, but tool execution semantics must remain unchanged in Phase 1. | Must Have |
| FR-CHAT-04 | Retrieval enrichment must not change the externally visible request/response format of the existing chat endpoints. | Must Have |
| FR-CHAT-05 | Session trace events should include retrieval usage summaries when memory is enabled. | Should Have |

### 6.7 Safe Tool Cache (Future Scope)

Tool caching is intentionally constrained because semantic similarity alone is not a safe authorization mechanism for reusing executable outcomes.

| ID | Requirement | Priority |
|---|---|---|
| FR-CACHE-01 | No tool may be cached unless it is explicitly marked cacheable by policy. | Must Have |
| FR-CACHE-02 | Cache eligibility must consider deterministic scope data including tool name, normalized arguments, server alias, and relevant environment context. | Must Have |
| FR-CACHE-03 | Semantic similarity may rank candidate cache entries but must not alone authorize reuse. | Must Have |
| FR-CACHE-04 | Cache entries must record provenance including source version and expiry. | Must Have |
| FR-CACHE-05 | Tool cache rollout must be feature-flagged independently from retrieval rollout. | Must Have |
| FR-CACHE-06 | Volatile or side-effecting tools must never be cached. | Must Have |
| FR-CACHE-07 | Read-only tools that depend on mutable external state must remain non-cacheable unless explicit freshness rules are defined. | Must Have |

### 6.8 Security and Privacy

| ID | Requirement | Priority |
|---|---|---|
| FR-SEC-01 | Stored tool outputs, code chunks, and conversation memories must be treated as potentially sensitive. | Must Have |
| FR-SEC-02 | Secrets and credentials must not be persisted in memory payloads or logs when they can be redacted or omitted. | Must Have |
| FR-SEC-03 | Retrieval and memory storage must honor user ownership when SSO is enabled. | Must Have |
| FR-SEC-04 | Memory deletion workflows must support removal by source deletion, session deletion, or user deletion where applicable. | Should Have |
| FR-SEC-05 | Administrative or diagnostic memory endpoints must not expose raw sensitive payloads by default. | Must Have |

### 6.9 Observability and Operations

| ID | Requirement | Priority |
|---|---|---|
| FR-OPS-01 | Retrieval, cache, and ingestion operations must be logged through the existing backend logging pattern. | Must Have |
| FR-OPS-02 | Retrieval decisions should record hit counts, selected chunk identifiers, latency, and fallback reasons. | Should Have |
| FR-OPS-03 | Ingestion jobs should expose status, duration, chunk counts, and error counts. | Should Have |
| FR-OPS-04 | Health checks should report Milvus reachability and embedding provider availability without collapsing core app health into failure when the feature is optional. | Must Have |

---

## 7. Non-Functional Requirements

### 7.1 Performance

The following values are implementation targets, not fixed guarantees. They must be validated through testing.

| ID | Requirement | Target |
|---|---|---|
| NFR-PERF-01 | Code/doc retrieval round-trip from Milvus | < 150 ms median in local/dev deployment |
| NFR-PERF-02 | Added latency from retrieval enrichment on a normal chat turn | < 300 ms median when Milvus is healthy |
| NFR-PERF-03 | Ingestion throughput | Measured and reported; no hardcoded claim before benchmark |
| NFR-PERF-04 | Degraded-mode fallback | Retrieval failure must not add more than 1 second before fallback |

### 7.2 Reliability

| ID | Requirement | Priority |
|---|---|---|
| NFR-REL-01 | The application must continue serving chat requests when Milvus is unavailable and memory features are optional. | Must Have |
| NFR-REL-02 | Failed retrievals must not corrupt session state or message history. | Must Have |
| NFR-REL-03 | Reindexing into a new collection version must not require deleting the currently active collection first. | Must Have |
| NFR-REL-04 | The system must tolerate partial ingestion failures and continue processing remaining files. | Must Have |

### 7.3 Compatibility

| ID | Requirement | Value |
|---|---|---|
| NFR-COMP-01 | Backend Python version | 3.10 or newer |
| NFR-COMP-02 | Development platforms | macOS and Linux supported for application development |
| NFR-COMP-03 | Deployment platforms | Linux preferred for containerized production deployment |
| NFR-COMP-04 | Milvus connectivity | Local or remote Milvus reachable by configured URI |
| NFR-COMP-05 | Existing MCP transports | Preserve current MCP client behavior and configured transports |

### 7.4 Maintainability

| ID | Requirement | Priority |
|---|---|---|
| NFR-MAIN-01 | New memory functionality must be implemented as focused modules rather than expanding all logic directly into `backend/main.py`. | Must Have |
| NFR-MAIN-02 | Collection schemas and embedding versions must be explicit and documented. | Must Have |
| NFR-MAIN-03 | The implementation must support feature-flagged rollback without schema destruction. | Must Have |

---

## 8. Configuration Requirements

Configuration must follow the current repository pattern of environment-driven backend settings rather than introducing a top-level standalone `config.py` as the sole source of truth.

### 8.1 Required Configuration Parameters

| Parameter | Default | Description |
|---|---|---|
| `MCP_MEMORY_ENABLED` | `false` | Master flag for Milvus-backed memory features |
| `MCP_MEMORY_MILVUS_URI` | empty | Milvus connection URI |
| `MCP_MEMORY_COLLECTION_PREFIX` | `mcp_client` | Prefix for versioned collection names |
| `MCP_MEMORY_EMBEDDING_PROVIDER` | empty | Embedding backend provider (`openai`, `ollama`, `enterprise`, etc.) |
| `MCP_MEMORY_EMBEDDING_MODEL` | empty | Embedding model identifier |
| `MCP_MEMORY_RETRIEVAL_ENABLED` | `true` when memory enabled | Enables code/doc retrieval |
| `MCP_MEMORY_CONVERSATION_ENABLED` | `false` | Enables long-term conversation memory |
| `MCP_MEMORY_TOOL_CACHE_ENABLED` | `false` | Enables allowlisted tool cache logic |
| `MCP_MEMORY_MAX_CODE_RESULTS` | `5` | Max code chunks injected per turn |
| `MCP_MEMORY_MAX_DOC_RESULTS` | `5` | Max doc chunks injected per turn |
| `MCP_MEMORY_MAX_CONVERSATION_RESULTS` | `3` | Max recalled conversation memories |
| `MCP_MEMORY_CODE_THRESHOLD` | `0.72` | Initial code retrieval threshold, subject to tuning |
| `MCP_MEMORY_DOC_THRESHOLD` | `0.68` | Initial doc retrieval threshold, subject to tuning |
| `MCP_MEMORY_CONVERSATION_THRESHOLD` | `0.82` | Initial conversation retrieval threshold, subject to tuning |
| `MCP_MEMORY_DEGRADED_MODE` | `true` | Continue serving without retrieval if memory backend fails |
| `MCP_MEMORY_INGESTION_ENABLED` | `false` | Enables ingestion jobs |
| `MCP_MEMORY_REPO_ROOTS` | empty | Comma-separated roots to ingest |
| `MCP_MEMORY_DOC_ROOTS` | empty | Comma-separated documentation roots to ingest |
| `MCP_MEMORY_RETENTION_DAYS` | `30` | Default retention for long-term memory where applicable |

### 8.2 Configuration Rules

| ID | Requirement | Priority |
|---|---|---|
| CFG-01 | Enabling memory features without a valid Milvus URI must produce a clear startup warning or validation error. | Must Have |
| CFG-02 | Embedding configuration must validate dimension compatibility with the active collection version. | Must Have |
| CFG-03 | Thresholds are implementation defaults and must remain configurable without code edits. | Must Have |
| CFG-04 | Feature flags for retrieval, conversation memory, and tool cache must be independently controllable. | Must Have |

---

## 9. Implementation File Plan

This section defines the expected repository-aligned implementation footprint.

### 9.1 Existing Files Expected to Change

| File | Expected Role |
|---|---|
| `backend/main.py` | Wire retrieval/memory services into existing startup, health, and message flow |
| `backend/models.py` | Add models for memory config, diagnostics, or ingestion/admin APIs if needed |
| `backend/llm_client.py` | Add or expose embedding request support if not already separated |
| `backend/session_manager.py` | Optionally emit retrieval trace metadata while keeping session state in memory |
| `backend/database.py` | Add sidecar tables for payload refs, ingestion jobs, and audit/provenance as needed |
| `backend/static/app.js` | Optional UI display for sources or retrieval status without breaking current chat UX |

### 9.2 Proposed New Backend Modules

| File | Purpose |
|---|---|
| `backend/memory_service.py` | Orchestrates retrieval, recall, and fallback behavior |
| `backend/milvus_store.py` | Encapsulates Milvus connection, collection management, and search/upsert APIs |
| `backend/embedding_service.py` | Normalizes embedding calls across providers |
| `backend/ingestion_service.py` | Handles code/doc ingestion and incremental refresh |
| `backend/memory_persistence.py` | Sidecar persistence for payload refs, jobs, and audit records |

### 9.3 Implementation Rules

| ID | Requirement | Priority |
|---|---|---|
| IMP-01 | Memory logic should be encapsulated in dedicated modules, not implemented as large inline blocks in `backend/main.py`. | Must Have |
| IMP-02 | New modules must expose narrow interfaces suitable for unit testing. | Must Have |
| IMP-03 | Integration must preserve current behavior when memory flags are off. | Must Have |

---

## 10. Phased Delivery Plan

### Phase 1 - Retrieval Enrichment

- Add Milvus connectivity, versioned collections, and embedding support.
- Implement code/doc ingestion for configured roots.
- Integrate retrieval into the existing chat synthesis path.
- Add degraded-mode health reporting and fallback behavior.

### Phase 2 - Same-User Conversation Memory

- Persist bounded conversation summaries.
- Enable same-user, workspace-scoped recall.
- Add retention and deletion support.

### Phase 3 - Safe Tool Cache

- Add allowlisted cache policy model.
- Add deterministic scope hashing and provenance checks.
- Use semantic similarity only as candidate ranking assistance.

### Phase 4 - Optimization and Migration

- Add evaluation datasets and tuning workflow.
- Add collection version migration and cutover tooling.
- Add richer observability and admin workflows.

---

## 11. Acceptance and Test Requirements

### 11.1 Core Acceptance Criteria

| ID | Acceptance Criterion |
|---|---|
| ACC-01 | With `MCP_MEMORY_ENABLED=false`, chat behavior matches current application behavior. |
| ACC-02 | With retrieval enabled and Milvus healthy, code/doc context can be injected into synthesis without changing public chat API contracts. |
| ACC-03 | With retrieval enabled and Milvus unavailable, the user still receives a normal chat response through degraded fallback. |
| ACC-04 | Same-user conversation recall never returns other users' memories in SSO mode. |
| ACC-05 | Tool caching remains disabled unless explicitly enabled and policy-approved. |

### 11.2 Test Coverage Requirements

| Area | Required Test Type |
|---|---|
| Memory feature flags | Unit + integration |
| Milvus degraded fallback | Integration |
| Retrieval enrichment path | Integration |
| Ingestion change detection | Unit + integration |
| SSO ownership boundaries for memory | Integration |
| Cache eligibility policy | Unit |

### 11.3 Benchmarking Requirements

Before tool cache rollout or threshold hardening, the project must collect:

- retrieval precision samples,
- false-positive retrieval cases,
- prompt-size impact data,
- degraded-mode latency data,
- and cache safety validation for each cacheable tool class.

---

## 12. Glossary

| Term | Definition |
|---|---|
| **Milvus** | Vector database used for similarity search over embeddings. |
| **Memory Layer** | The optional retrieval subsystem backed by Milvus and sidecar persistence. |
| **Sidecar Persistence** | Non-Milvus storage for raw payloads, audit records, or ingestion metadata. |
| **Payload Reference** | A stable pointer to full content stored outside a Milvus vector record. |
| **Workspace Scope** | The repository or working set boundary used to constrain retrieval relevance. |
| **Degraded Mode** | Operating mode where retrieval is unavailable but the core chat system still functions. |
| **Allowlisted Tool Cache** | Cache system that only permits explicitly approved tools to reuse outputs. |
| **Embedding Version** | A version marker tying stored vectors to a specific model and index generation. |

