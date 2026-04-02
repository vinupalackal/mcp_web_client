# M1 Provider-Agnostic Embedding Support Requirements

**Feature:** M1 - Provider-Agnostic Embedding Support  
**Application:** MCP Client Web  
**Date:** March 30, 2026  
**Related Issue:** #4  
**Target Files:** `backend/embedding_service.py`, `backend/llm_client.py`, `tests/backend/unit/test_embedding_service.py`

---

## 1. Purpose

This document defines the issue-level requirements for M1 issue #4: adding a **provider-agnostic embedding layer** that can generate vectors for memory ingestion and retrieval without coupling the Milvus integration directly to any one LLM provider.

This issue prepares the backend for:
- embedding generation across OpenAI, Ollama, enterprise-compatible providers, and controlled test doubles,
- future ingestion and retrieval modules that need a normalized embedding interface,
- explicit embedding configuration independent from chat model behavior,
- and clean degraded behavior when an embedding provider is unavailable.

This issue is limited to the embedding abstraction and related tests. It does not require Milvus search, ingestion orchestration, or chat-path retrieval wiring.

---

## 2. Scope

### In Scope

- Add a provider-normalized embedding service interface.
- Support explicit embedding provider and model selection separate from chat completion behavior.
- Normalize embedding responses into a consistent vector/result shape.
- Support batching of input texts.
- Surface provider failures and timeout behavior clearly.
- Validate embedding dimension consistency when the caller provides an expected vector size.
- Add focused unit tests for provider routing, normalization, and error handling.

### Out of Scope

- Milvus collection creation and search logic.
- Ingestion pipeline implementation.
- Retrieval orchestration in `backend/main.py`.
- Frontend settings UI changes for embedding configuration.
- Automatic embedding-provider discovery beyond configured values.

---

## 3. Requirements Mapping

| ID | Requirement | How this issue addresses it |
|---|---|---|
| FR-CFG-05 | Embedding configuration must be explicit and independent from chat model selection when necessary. | Embedding service accepts provider/model config independently of chat use. |
| FR-OPS-04 | Health checks should report Milvus reachability and embedding provider availability without collapsing core app health. | Embedding service failure modes remain distinguishable and can later feed diagnostics. |
| NFR-MAIN-01 | New memory functionality must be implemented as focused modules rather than expanding all logic directly into `backend/main.py`. | Embedding behavior is isolated in `backend/embedding_service.py`. |
| NFR-MAIN-02 | Collection schemas and embedding versions must be explicit and documented. | Embedding model/provider and vector dimension expectations are explicit in the service contract. |
| ARC-06 | New memory features must be feature-flagged to allow phased rollout and rollback. | Embedding support is prepared as a standalone backend module and can be invoked only when memory paths are enabled. |
| FR-RET-01 | Retrieval should optionally retrieve relevant code/docs context before synthesis. | This issue provides the embedding prerequisite for future retrieval queries. |
| FR-RET-06 | Retrieval failure must degrade gracefully. | Embedding errors are surfaced cleanly so future callers can degrade instead of crashing. |

---

## 4. Required Capabilities

### 4.1 Provider-Normalized Entry Point

The implementation must expose a single service/API that callers can use without needing provider-specific request shapes.

Expected responsibilities:
- accept one or more input texts,
- accept an embedding provider and model identifier,
- return embeddings in a stable list-of-vectors format,
- and hide provider-specific response envelopes from callers.

### 4.2 Provider Routing

The implementation must support current repository provider families:
- `openai`
- `ollama`
- `enterprise`
- `mock`

Provider differences may exist internally, but the public embedding-service contract should remain uniform.

### 4.3 Timeout and Error Semantics

Embedding requests must:
- reuse the repository’s granular `httpx.Timeout` behavior,
- emit actionable internal diagnostics,
- and distinguish provider/HTTP/timeout errors from later Milvus-layer failures.

### 4.4 Dimension Validation

When an expected dimension is supplied by the caller, the service should validate returned vectors against that dimension and fail fast with a clear error if mismatched.

### 4.5 Testability

The embedding layer must be testable without real remote providers.

Preferred mechanisms include:
- dependency isolation behind a small provider adapter boundary,
- mock provider behavior,
- and HTTP response stubbing for provider-specific implementations.

---

## 5. Design Constraints

- Keep the embedding layer additive and independent of existing chat-completion contracts.
- Do not break `backend/llm_client.py` chat behavior while extending provider capabilities.
- Do not assume all providers use OpenAI-compatible embedding endpoints.
- Avoid leaking secrets or provider credentials into logs.
- Keep the service usable by both future ingestion and future retrieval code.

---

## 6. Acceptance Criteria

- A provider-agnostic embedding module exists in `backend/embedding_service.py`.
- The implementation supports provider routing for configured provider types or explicitly rejects unsupported configurations with a clear error.
- Embedding responses are normalized into a consistent result shape.
- Timeout and HTTP failure behavior are covered with focused unit tests.
- Dimension mismatch behavior is validated when expected dimensions are provided.
- Existing backend tests remain green.

---

## 7. Validation

```bash
source venv/bin/activate
pytest tests/backend/unit/test_embedding_service.py -q
pytest tests/backend/unit/test_llm_client.py -q
pytest tests/backend/ -q
```

Validation expectations:
- provider routing behaves as designed,
- normalization is stable across supported providers,
- timeout/error cases are explicit,
- and backend regression remains green.