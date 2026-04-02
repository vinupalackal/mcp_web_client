# M3 Issue #9 — Retrieval Orchestration Service Implementation Spec

**Issue**: #9 — M3: Implement retrieval orchestration service  
**Milestone**: M3 - Chat Integration  
**HLD**: `docs/M3-RETRIEVAL-SERVICE-HLD.md`  
**Requirements**: `docs/M3-RETRIEVAL-SERVICE-REQUIREMENTS.md`

---

## 1. Files Changed

| File | Change | Notes |
|------|--------|-------|
| `backend/memory_service.py` | New | Full implementation |
| `tests/backend/unit/test_memory_service.py` | New | TC-MEM-01 through TC-MEM-09 |

---

## 2. Module Layout

```python
"""Retrieval orchestration service for memory-augmented chat turns."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.embedding_service import EmbeddingServiceError
from backend.milvus_store import MilvusStoreError

logger_internal = logging.getLogger("mcp_client.internal")


@dataclass
class MemoryServiceConfig:
    enabled: bool = False
    repo_id: str = ""
    collection_generation: str = "v1"
    max_results: int = 5
    retrieval_timeout_s: float = 5.0


@dataclass
class RetrievalBlock:
    payload_ref: str
    collection: str
    score: float
    snippet: str
    source_path: str


@dataclass
class RetrievalResult:
    blocks: list[RetrievalBlock] = field(default_factory=list)
    degraded: bool = False
    degraded_reason: str = ""
    latency_ms: float = 0.0


class MemoryService:
    def __init__(
        self,
        *,
        embedding_service: Any,
        milvus_store: Any,
        memory_persistence: Any,
        config: Optional[MemoryServiceConfig] = None,
    ): ...

    async def enrich_for_turn(
        self,
        *,
        user_message: str,
        session_id: str,
        repo_id: Optional[str] = None,
    ) -> RetrievalResult: ...

    async def health_status(self) -> dict[str, Any]: ...

    def _build_query(self, text: str) -> str: ...
    def _make_filter(self, repo_id: str) -> str: ...
    def _normalize_block(self, hit: dict, collection: str) -> RetrievalBlock: ...
```

---

## 3. enrich_for_turn() Implementation Notes

- `repo_id` param overrides config `repo_id` when provided.
- Build Milvus filter: `f'repo_id == "{effective_repo_id}"'` (empty string = no filter).
- Search both `code_memory` and `doc_memory` with the same query vector.
- Merge raw hit lists, sort by `distance` ascending (smaller = closer for COSINE).
- Slice to `config.max_results`.
- Build `RetrievalBlock` from each hit's output fields: `payload_ref`, `source_path`/`relative_path`,
  `summary` (use as snippet, truncate to 500 chars).
- Call `memory_persistence.record_retrieval_provenance(...)` only when `blocks` is non-empty.
- Wrap entire async body in `try/except` to guarantee no exception escapes.

### Provenance record fields

```python
memory_persistence.record_retrieval_provenance(
    session_id=session_id,
    query_hash=hashlib.sha256(query_text.encode()).hexdigest()[:16],
    collection_keys=["code_memory", "doc_memory"],
    result_count=len(blocks),
    generation=config.collection_generation,
    latency_ms=latency_ms,
)
```

---

## 4. health_status() Implementation Notes

```python
async def health_status(self) -> dict:
    if not self.config.enabled:
        return {"enabled": False, "healthy": True, "degraded": False,
                "active_collections": [], "last_failure_reason": None}
    try:
        collections = self.milvus_store.list_collections()
        return {
            "enabled": True,
            "healthy": True,
            "degraded": False,
            "active_collections": collections,
            "last_failure_reason": None,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "healthy": False,
            "degraded": True,
            "active_collections": [],
            "last_failure_reason": str(exc),
        }
```

---

## 5. Test File Layout

```python
"""Unit tests for MemoryService retrieval orchestration (TC-MEM-*)."""

import asyncio
import pytest
from backend.memory_service import MemoryService, MemoryServiceConfig

class _FakeEmbeddingService: ...
class _FakeEmbeddingServiceFailing: ...
class _FakeMilvusStore: ...
class _FakeMilvusStoreFailing: ...
class _FakeMemoryPersistence: ...

class TestMemoryService:
    # TC-MEM-01 through TC-MEM-09
```

---

## 6. How to See the Before / After Difference

**Before**: `backend/memory_service.py` does not exist; retrieval is not possible.

**After**:
```bash
python -c "from backend.memory_service import MemoryService, MemoryServiceConfig; print('MemoryService importable')"
pytest tests/backend/unit/test_memory_service.py -v
```
