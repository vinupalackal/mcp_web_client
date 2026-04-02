# M1 Provider-Agnostic Embedding Support Implementation Spec

**Feature:** M1 - Provider-Agnostic Embedding Support  
**Application:** MCP Client Web  
**Date:** March 30, 2026  
**Related Issue:** #4  
**Primary Files:** `backend/embedding_service.py`, `backend/llm_client.py`

---

## 1. Implementation Intent

This document translates the issue-level requirements and HLD for issue #4 into a practical implementation spec for the repository.

The objective is to add the minimum useful embedding abstraction that future ingestion and retrieval work can call without embedding provider logic directly into Milvus or chat orchestration modules.

---

## 2. Target Additions

### 2.1 `backend/embedding_service.py`

Suggested responsibilities:
- expose a small service/class for embedding generation,
- accept provider/model configuration and one-or-more texts,
- route to the appropriate provider adapter,
- normalize embedding vectors into a consistent shape,
- validate optional expected dimensions.

### 2.2 Provider Request Helpers

Implementation may either:
- add provider-specific embedding helpers to existing `backend/llm_client.py` clients, or
- keep provider-specific embedding request code inside `backend/embedding_service.py`.

Preferred rule:
- reuse existing timeout/logging conventions,
- but do not contort the chat-completions abstraction to fit embeddings.

### 2.3 Normalized Return Contract

Suggested result fields:
- `provider`
- `model`
- `dimensions`
- `vectors`

Optional future-friendly fields:
- `input_count`
- provider response metadata if safe and useful

---

## 3. Provider-Specific Expectations

### 3.1 OpenAI

Suggested endpoint:
- `POST {base_url}/v1/embeddings`

Expected request fields:
- `model`
- `input`

Expected normalization:
- extract `data[*].embedding`
- preserve input order

### 3.2 Enterprise Gateway

If enterprise deployments expose embeddings through an OpenAI-compatible or gateway-specific endpoint, normalize them through the same result contract.

If the gateway does not support embeddings in the current deployment model, fail with a clear unsupported-provider error rather than guessing.

### 3.3 Ollama

Suggested handling:
- call the appropriate Ollama embedding endpoint,
- normalize the returned vector(s),
- keep provider-specific response envelope hidden from callers.

### 3.4 Mock

Provide deterministic vectors suitable for unit tests.

Goals:
- no network dependency,
- stable dimension count,
- reproducible assertions in tests.

---

## 4. Error and Validation Rules

- Empty input list should either return an empty vector list or raise a clear validation error; choose one behavior and test it explicitly.
- Missing provider/model/base URL/auth requirements should fail early and clearly.
- Timeout exceptions should preserve the repo’s phase-specific timeout messaging style.
- Dimension mismatches should fail with a stable, caller-actionable error.

---

## 5. Recommended Test Coverage

Add `tests/backend/unit/test_embedding_service.py` to validate:
- provider routing for supported providers,
- normalization of provider responses,
- batching behavior and order preservation,
- deterministic mock embeddings,
- timeout handling,
- dimension mismatch handling,
- unsupported provider behavior.

If `backend/llm_client.py` gains reusable helpers, extend `tests/backend/unit/test_llm_client.py` only for the helper logic added by this issue.

---

## 6. Backward Compatibility Rules

- Do not change current chat-completion API contracts.
- Do not change existing provider selection behavior for chat requests.
- Keep embedding support additive and only used by future memory modules unless explicitly wired later.

---

## 7. Expected Outcome

After this issue:
- the repository has a concrete embedding abstraction ready for Milvus-backed features,
- future ingestion work can request embeddings without provider-specific branching,
- and provider/timeout failure behavior is testable before retrieval wiring begins.

---

## 8. How To See The Before / After Difference

Issue `#4` is primarily a **backend service-layer change**, so the implementation difference will be visible in new backend module structure and focused tests rather than in the UI.

### Before Issue #4

The repository has:
- provider-specific chat support in `backend/llm_client.py`,
- no dedicated embedding service module,
- no normalized embedding result contract for future memory features,
- and no focused embedding-service unit tests.

### After Issue #4

The repository is expected to include:
- `backend/embedding_service.py`
- optional provider helper additions in `backend/llm_client.py`
- focused tests in `tests/backend/unit/test_embedding_service.py`

### Where To Look In The Repo

To inspect the implementation delta directly:

1. Open `backend/embedding_service.py`
   - Look for provider routing, normalization, and dimension validation.
2. Open `backend/llm_client.py`
   - Look for any provider-specific embedding helpers or shared timeout/logging reuse.
3. Open `tests/backend/unit/test_embedding_service.py`
   - Look for provider routing, timeout, and dimension mismatch coverage.

---

## 9. Validation Commands

```bash
source venv/bin/activate
pytest tests/backend/unit/test_embedding_service.py -q
pytest tests/backend/unit/test_llm_client.py -q
pytest tests/backend/ -q
```