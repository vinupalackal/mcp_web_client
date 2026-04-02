# M3 Issue #12 — Memory Integration Test Coverage Implementation Spec

**Issue**: #12 — M3: Add memory integration test coverage  
**Milestone**: M3 - Chat Integration  
**HLD**: `docs/M3-INTEGRATION-TESTS-HLD.md`  
**Requirements**: `docs/M3-INTEGRATION-TESTS-REQUIREMENTS.md`

---

## 1. Files Changed

| File | Change Type | Summary |
|------|-------------|---------|
| `tests/backend/integration/test_memory_health_api.py` | New | TC-HEALTH-01–03 |
| `tests/backend/integration/test_memory_retrieval_flow.py` | New | TC-FLOW-01–03 |
| `tests/backend/integration/test_memory_degraded_mode.py` | New | TC-DEGRADE-01–02 |

---

## 2. Common Test Infrastructure

### Monkeypatching _memory_service

```python
import backend.main as main_module

@pytest.fixture
def with_memory(fake_service):
    original = main_module._memory_service
    main_module._memory_service = fake_service
    yield
    main_module._memory_service = original
```

This pattern is safe across concurrent tests because the integration test suite runs with `--runInBand`
(or sequential pytest).

### Accessing session_manager

```python
from backend.main import session_manager   # module-level singleton
```

---

## 3. test_memory_health_api.py Skeleton

```python
"""Integration tests for memory subsystem health reporting (TC-HEALTH-*)."""

import pytest
import backend.main as main_module
from tests.backend.conftest import client  # existing fixture

class _FakeMemoryService: ...   # see HLD §5

class TestMemoryHealthApi:

    def test_health_memory_disabled(self, client):
        """TC-HEALTH-01"""
        original = main_module._memory_service
        main_module._memory_service = None
        try:
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["memory"]["enabled"] is False
            assert data["status"] == "healthy"
        finally:
            main_module._memory_service = original

    def test_health_memory_enabled_healthy(self, client): ...   # TC-HEALTH-02

    def test_health_memory_enabled_degraded(self, client): ...  # TC-HEALTH-03
```

---

## 4. test_memory_retrieval_flow.py Skeleton

```python
"""Integration tests for retrieval enrichment in the chat flow (TC-FLOW-*)."""

import pytest
import backend.main as main_module
from backend.main import session_manager

class TestMemoryRetrievalFlow:

    def test_chat_memory_disabled(self, client, session_id): ...      # TC-FLOW-01

    def test_chat_memory_enabled_retrieval_success(self, client, session_id): ...  # TC-FLOW-02

    def test_chat_memory_enabled_empty_results(self, client, session_id): ...      # TC-FLOW-03
```

---

## 5. test_memory_degraded_mode.py Skeleton

```python
"""Integration tests for memory degraded-mode behavior (TC-DEGRADE-*)."""

class TestMemoryDegradedMode:

    def test_degraded_retrieval_does_not_fail_chat(self, client, session_id): ...  # TC-DEGRADE-01

    def test_memory_none_is_safe_for_health_and_chat(self, client, session_id): ...  # TC-DEGRADE-02
```

---

## 6. How to See the Before / After Difference

**Before**: No integration test exercises memory health reporting or retrieval flow behavior.

**After**:
```bash
pytest tests/backend/integration/test_memory_health_api.py \
       tests/backend/integration/test_memory_retrieval_flow.py \
       tests/backend/integration/test_memory_degraded_mode.py -v
```

Expected output shows TC-HEALTH-01–03, TC-FLOW-01–03, TC-DEGRADE-01–02 all passing.
