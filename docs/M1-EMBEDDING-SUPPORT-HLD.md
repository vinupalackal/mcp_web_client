# M1 Provider-Agnostic Embedding Support HLD

**Feature:** M1 - Provider-Agnostic Embedding Support  
**Application:** MCP Client Web  
**Date:** March 30, 2026  
**Status:** Design Ready  
**Related Issue:** #4  
**Parent Docs:** `Milvus_MCP_Integration_Requirements.md`, `docs/MILVUS_MCP_IMPLEMENTATION_PLAN.md`

---

## 1. Executive Summary

This HLD defines the design for issue #4.

The purpose of this work is to introduce a focused backend module that provides **provider-normalized embedding generation** for future Milvus ingestion and retrieval flows, while preserving the repository’s current chat-completion behavior and provider abstractions.

The design keeps embedding support phase-safe:
- no retrieval-path behavior is wired in this issue,
- no frontend/API contract changes are required,
- and no Milvus dependency is introduced into existing chat paths.

---

## 2. Design Goals

1. Provide a single embedding entry point for future memory modules.
2. Reuse existing provider configuration patterns where practical.
3. Keep chat completions and embeddings logically separate even when they share providers.
4. Normalize provider-specific embedding responses into one stable shape.
5. Make provider and timeout failures explicit and diagnosable.

---

## 3. Component Delta

| Component | Change | Description |
|---|---|---|
| `backend/embedding_service.py` | New | Embedding abstraction and provider routing layer |
| `backend/llm_client.py` | Extended | May expose provider-specific embedding request helpers reused by the embedding service |
| `tests/backend/unit/test_embedding_service.py` | New | Focused coverage for provider routing, normalization, and failure cases |
| `tests/backend/unit/test_llm_client.py` | Possibly extended | Optional provider-helper coverage if llm_client gains reusable embedding helpers |
| `backend/main.py` | Unchanged in this issue | Future consumer only |

---

## 4. Proposed Structure

### 4.1 Service Boundary

Recommended composition:

```text
EmbeddingService
├── accepts provider/model/text inputs
├── routes to provider-specific adapter/helper
├── normalizes vectors into one result shape
└── validates optional expected dimension
```

This keeps the service reusable by:
- `backend/ingestion_service.py`
- `backend/memory_service.py`
- future diagnostics or health checks

### 4.2 Provider Adapter Strategy

The service should isolate provider-specific behavior behind small helpers rather than branching throughout future Milvus code.

Suggested provider handling:
- **OpenAI**: call the embeddings endpoint using configured API key and model
- **Enterprise**: use enterprise gateway embedding endpoint if supported by deployment contract
- **Ollama**: call Ollama’s embedding endpoint and normalize response shape
- **Mock**: return deterministic test vectors without network calls

### 4.3 Normalized Result Shape

The caller-facing result should be stable regardless of provider.

Suggested shape:

```text
EmbeddingResult
├── provider
├── model
├── dimensions
└── vectors: list[list[float]]
```

The implementation may express this as a dataclass, typed dict, or another repo-consistent structure.

---

## 5. Provider Integration Strategy

### 5.1 Relationship to `backend/llm_client.py`

Current `backend/llm_client.py` already centralizes:
- provider selection,
- `httpx.Timeout` construction,
- external/internal logging patterns,
- and provider-specific chat handling.

Issue #4 should reuse those conventions where helpful, but should avoid forcing embedding callers through the chat-completion API.

Preferred options:
- add provider-specific embedding helper methods alongside current clients, or
- keep provider HTTP logic inside `backend/embedding_service.py` while mirroring the same timeout/logging/error patterns.

Either option is acceptable if the public embedding boundary stays clean.

### 5.2 Unsupported Provider Handling

If a provider lacks a supported embedding endpoint in this phase, the implementation should fail clearly with an explicit configuration/runtime error rather than silently substituting chat completions.

---

## 6. Failure Modeling

The design must explicitly model:
- timeout failures,
- HTTP/transport failures,
- misconfiguration (missing provider/model/base URL/API key as applicable),
- and vector-dimension mismatch.

Recommended behavior:
- raise clear, typed or stable exceptions,
- keep Milvus errors separate from embedding errors,
- log enough context for operators without leaking secrets.

---

## 7. Batching and Performance

- Accept multiple texts in one call where the provider supports batching.
- Preserve input ordering in returned vectors.
- Avoid prematurely optimizing around large-scale ingestion in this issue.
- Keep the abstraction simple enough for Phase 1 while not blocking future batch tuning.

---

## 8. Security and Logging

- Do not log raw API keys or auth tokens.
- Avoid logging full input texts unless debugging explicitly requires it later.
- Log provider name, model, batch count, timeout context, and dimension mismatches.
- Keep external logs aligned with the repo’s directional request/response pattern.

---

## 9. Validation

- `pytest tests/backend/unit/test_embedding_service.py -q`
- `pytest tests/backend/unit/test_llm_client.py -q`
- `pytest tests/backend/ -q`

Primary verification goals:
- provider routing correctness,
- normalized result stability,
- deterministic mock coverage,
- failure-path clarity.