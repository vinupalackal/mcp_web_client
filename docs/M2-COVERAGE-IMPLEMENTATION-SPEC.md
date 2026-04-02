# M2 Issue #8 — Ingestion and Store Test Coverage Implementation Spec

**Issue**: #8 — M2: Add ingestion and store test coverage  
**Milestone**: M2 - Milvus + Ingestion  
**HLD**: docs/M2-COVERAGE-HLD.md  
**Requirements**: docs/M2-COVERAGE-REQUIREMENTS.md

---

## 1. Files Changed

| File | Change Type | Summary |
|------|-------------|---------|
| `tests/backend/unit/test_milvus_store.py` | Append | 4 new test classes covering key coverage, generation isolation, input validation, and drop no-op |
| `tests/backend/unit/test_ingestion_service.py` | Append | 4 new test cases covering excluded dirs, empty workspace, cross-run hash stability, generation propagation |
| `tests/backend/unit/test_ingestion_store_integration.py` | New | Integration tests wiring IngestionService + MilvusStore with fake Milvus client |

---

## 2. test_milvus_store.py — New Classes

### TestMilvusStoreCollectionKeys

```python
class TestMilvusStoreCollectionKeys:

    @pytest.mark.parametrize("key,expected_suffix", [
        ("code_memory", "code_memory"),
        ("doc_memory", "doc_memory"),
        ("conversation_memory", "conversation_memory"),
        ("tool_cache", "tool_cache"),
    ])
    def test_all_known_collection_keys_produce_valid_names(self, key, expected_suffix):
        store = MilvusStore(milvus_uri="http://milvus.local", client=_FakeMilvusClient(), ...)
        name = store.build_collection_name(key, "v1")
        assert name == f"mcp_client_{expected_suffix}_v1"

    def test_unknown_collection_key_raises(self):
        store = ...
        with pytest.raises(MilvusCollectionConfigError):
            store.build_collection_name("nonexistent_key", "v1")
```

### TestMilvusStoreGenerationIsolation

```python
class TestMilvusStoreGenerationIsolation:

    def test_two_generations_produce_distinct_collections(self): ...
    def test_upsert_to_v2_does_not_touch_v1(self): ...
    def test_drop_v2_leaves_v1_intact(self): ...
```

### TestMilvusStoreInputValidation

```python
class TestMilvusStoreInputValidation:

    def test_zero_dimension_raises(self): ...
    def test_negative_dimension_raises(self): ...
    def test_empty_records_raises(self): ...
    def test_wrong_embedding_length_raises(self): ...
    def test_missing_record_id_raises(self): ...
```

### TestMilvusStoreDropNoOp

```python
class TestMilvusStoreDropNoOp:

    def test_drop_non_existent_collection_is_silent(self): ...
```

---

## 3. test_ingestion_service.py — New Test Cases

Added to `TestIngestionService`:

```python
async def test_excluded_dirs_are_not_scanned(self, tmp_path): ...
async def test_empty_workspace_produces_completed_zero_chunks(self, tmp_path): ...
async def test_unchanged_file_not_in_stale_list_on_second_run(self, tmp_path): ...
async def test_collection_generation_propagates_to_store_calls(self, tmp_path): ...
```

---

## 4. test_ingestion_store_integration.py — Full Design

```python
"""Integration tests wiring IngestionService + MilvusStore (fake Milvus client).

Tests ensure the collection_generation set on IngestionService reaches the
Milvus collection name, and that stale cleanup targets the correct generation.
"""

class TestIngestionStoreCrossGeneration:

    @pytest.mark.asyncio
    async def test_v1_generation_creates_v1_collection(self, tmp_path): ...

    @pytest.mark.asyncio
    async def test_v2_generation_creates_v2_not_v1(self, tmp_path): ...

    @pytest.mark.asyncio
    async def test_stale_cleanup_targets_correct_generation(self, tmp_path): ...

    @pytest.mark.asyncio
    async def test_payload_refs_consistent_between_persistence_and_store(self, tmp_path): ...
```

---

## 5. How to See the Before / After Difference

**Before issue #8**: run the following and observe the test counts:
```bash
pytest tests/backend/unit/test_milvus_store.py -v --collect-only 2>&1 | grep "test session starts" -A 100 | grep "<Function"
pytest tests/backend/unit/test_ingestion_service.py -v --collect-only 2>&1 | grep "<Function"
```

**After issue #8**: the same commands show additional test IDs:
- `TestMilvusStoreCollectionKeys::test_all_known_collection_keys_*`
- `TestMilvusStoreGenerationIsolation::*`
- `TestMilvusStoreInputValidation::*`
- `TestMilvusStoreDropNoOp::*`
- `TestIngestionService::test_excluded_dirs_*`
- `TestIngestionService::test_empty_workspace_*`
- `TestIngestionService::test_unchanged_file_*`
- `TestIngestionService::test_collection_generation_*`
- `TestIngestionStoreCrossGeneration::*` (new file)
