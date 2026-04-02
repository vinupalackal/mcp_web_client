"""Unit tests for Milvus store abstraction (TR-MVS-*)."""

from backend.milvus_store import MilvusCollectionConfigError, MilvusStore


class _FakeSchema:
    def __init__(self):
        self.fields = []

    def add_field(self, field_name, datatype, **kwargs):
        self.fields.append({"field_name": field_name, "datatype": datatype, **kwargs})


class _FakeIndexParams:
    def __init__(self):
        self.indexes = []

    def add_index(self, field_name, index_type="", index_name="", **kwargs):
        self.indexes.append(
            {
                "field_name": field_name,
                "index_type": index_type,
                "index_name": index_name,
                **kwargs,
            }
        )


class _FakeMilvusClientFactory:
    @staticmethod
    def create_schema(**kwargs):
        return _FakeSchema()

    @staticmethod
    def prepare_index_params():
        return _FakeIndexParams()


class _FakeMilvusClient:
    def __init__(self):
        self.collections = {}
        self.created_calls = []
        self.upsert_calls = []
        self.search_calls = []
        self.delete_calls = []
        self.drop_calls = []

    def has_collection(self, collection_name, timeout=None, **kwargs):
        return collection_name in self.collections

    def create_collection(self, **kwargs):
        collection_name = kwargs["collection_name"]
        self.created_calls.append(kwargs)
        self.collections[collection_name] = kwargs

    def describe_collection(self, collection_name, timeout=None, **kwargs):
        return self.collections[collection_name]

    def upsert(self, collection_name, data, timeout=None, partition_name="", **kwargs):
        self.upsert_calls.append({"collection_name": collection_name, "data": data})
        return {"upsert_count": len(data)}

    def search(self, collection_name, data, filter="", limit=10, output_fields=None, search_params=None, timeout=None, partition_names=None, anns_field=None, **kwargs):
        self.search_calls.append(
            {
                "collection_name": collection_name,
                "data": data,
                "filter": filter,
                "limit": limit,
                "output_fields": output_fields,
                "search_params": search_params,
                "anns_field": anns_field,
            }
        )
        return [[{"id": "chunk-1", "distance": 0.01}]]

    def delete(self, collection_name, ids=None, timeout=None, filter=None, partition_name=None, **kwargs):
        self.delete_calls.append({"collection_name": collection_name, "ids": ids, "filter": filter})
        return {"delete_count": len(ids or []) if ids is not None else 1}

    def drop_collection(self, collection_name, timeout=None, **kwargs):
        self.drop_calls.append(collection_name)
        self.collections.pop(collection_name, None)

    def list_collections(self, **kwargs):
        return list(self.collections.keys())


class TestMilvusStore:

    def test_build_collection_name_uses_prefix_key_and_generation(self):
        """TR-MVS-01: Versioned collection names are prefixed and keyed consistently."""
        store = MilvusStore(
            milvus_uri="http://milvus.local",
            client=_FakeMilvusClient(),
            client_factory=_FakeMilvusClientFactory,
        )

        assert store.build_collection_name("code_memory", "v1") == "mcp_client_code_memory_v1"

    def test_ensure_collection_creates_schema_and_index_once(self):
        """TR-MVS-02: ensure_collection creates missing collections with schema + index metadata."""
        client = _FakeMilvusClient()
        store = MilvusStore(
            milvus_uri="http://milvus.local",
            client=client,
            client_factory=_FakeMilvusClientFactory,
        )

        collection_name = store.ensure_collection(
            collection_key="code_memory",
            generation="v1",
            dimension=1536,
        )
        store.ensure_collection(
            collection_key="code_memory",
            generation="v1",
            dimension=1536,
        )

        assert collection_name == "mcp_client_code_memory_v1"
        assert len(client.created_calls) == 1
        created = client.created_calls[0]
        assert created["primary_field_name"] == "id"
        assert created["vector_field_name"] == "embedding"
        assert created["metric_type"] == "COSINE"
        schema_fields = created["schema"].fields
        vector_field = next(field for field in schema_fields if field["field_name"] == "embedding")
        assert vector_field["dim"] == 1536
        index = created["index_params"].indexes[0]
        assert index["field_name"] == "embedding"
        assert index["index_type"] == "AUTOINDEX"

    def test_upsert_validates_dimension_and_calls_client(self):
        """TR-MVS-03: Upsert validates embeddings and forwards records to the target collection."""
        client = _FakeMilvusClient()
        store = MilvusStore(
            milvus_uri="http://milvus.local",
            client=client,
            client_factory=_FakeMilvusClientFactory,
        )

        result = store.upsert(
            collection_key="doc_memory",
            generation="v1",
            dimension=3,
            records=[
                {
                    "id": "doc-1",
                    "embedding": [0.1, 0.2, 0.3],
                    "source_path": "README.md",
                    "payload_ref": "payload://doc/repo/README.md#intro",
                }
            ],
        )

        assert result == {"upsert_count": 1}
        assert client.upsert_calls[0]["collection_name"] == "mcp_client_doc_memory_v1"

    def test_upsert_rejects_bad_embedding_dimension(self):
        """TR-MVS-04: Invalid record vectors fail before reaching the client."""
        store = MilvusStore(
            milvus_uri="http://milvus.local",
            client=_FakeMilvusClient(),
            client_factory=_FakeMilvusClientFactory,
        )

        try:
            store.upsert(
                collection_key="code_memory",
                generation="v1",
                dimension=3,
                records=[{"id": "chunk-1", "embedding": [0.1, 0.2]}],
            )
        except MilvusCollectionConfigError as error:
            assert "dimension 3" in str(error)
        else:
            raise AssertionError("Expected MilvusCollectionConfigError")

    def test_search_forwards_filter_and_output_fields(self):
        """TR-MVS-05: Search passes query vectors, filter, and output-field selection through the wrapper."""
        client = _FakeMilvusClient()
        store = MilvusStore(
            milvus_uri="http://milvus.local",
            client=client,
            client_factory=_FakeMilvusClientFactory,
        )
        store.ensure_collection(collection_key="code_memory", generation="v1", dimension=3)

        result = store.search(
            collection_key="code_memory",
            generation="v1",
            query_vectors=[[0.1, 0.2, 0.3]],
            filter_expression='repo_id == "repo1"',
            output_fields=["id", "payload_ref"],
            limit=4,
        )

        assert result[0][0]["id"] == "chunk-1"
        search_call = client.search_calls[0]
        assert search_call["collection_name"] == "mcp_client_code_memory_v1"
        assert search_call["filter"] == 'repo_id == "repo1"'
        assert search_call["output_fields"] == ["id", "payload_ref"]
        assert search_call["anns_field"] == "embedding"

    def test_delete_by_ids_and_filter_forward_to_client(self):
        """TR-MVS-06: Delete helpers cover both id-based and filter-based removal."""
        client = _FakeMilvusClient()
        store = MilvusStore(
            milvus_uri="http://milvus.local",
            client=client,
            client_factory=_FakeMilvusClientFactory,
        )
        store.ensure_collection(collection_key="doc_memory", generation="v1", dimension=2)

        by_ids = store.delete_by_ids(
            collection_key="doc_memory",
            generation="v1",
            ids=["doc-1", "doc-2"],
        )
        by_filter = store.delete_by_filter(
            collection_key="doc_memory",
            generation="v1",
            filter_expression='source_hash == "abc"',
        )

        assert by_ids["delete_count"] == 2
        assert by_filter["delete_count"] == 1
        assert client.delete_calls[0]["ids"] == ["doc-1", "doc-2"]
        assert client.delete_calls[1]["filter"] == 'source_hash == "abc"'

    def test_drop_collection_removes_existing_collection(self):
        """TR-MVS-07: drop_collection only targets known versioned collections."""
        client = _FakeMilvusClient()
        store = MilvusStore(
            milvus_uri="http://milvus.local",
            client=client,
            client_factory=_FakeMilvusClientFactory,
        )
        store.ensure_collection(collection_key="code_memory", generation="v1", dimension=3)

        before = store.list_collections()
        store.drop_collection(collection_key="code_memory", generation="v1")
        after = store.list_collections()

        assert before == ["mcp_client_code_memory_v1"]
        assert after == []
        assert client.drop_calls == ["mcp_client_code_memory_v1"]


class TestMilvusStoreCollectionKeys:
    """TR-MVS-08: All four known collection keys produce valid, correctly-suffixed names."""

    def _make_store(self):
        return MilvusStore(
            milvus_uri="http://milvus.local",
            client=_FakeMilvusClient(),
            client_factory=_FakeMilvusClientFactory,
        )

    def test_code_memory_name(self):
        store = self._make_store()
        assert store.build_collection_name("code_memory", "v1") == "mcp_client_code_memory_v1"

    def test_doc_memory_name(self):
        store = self._make_store()
        assert store.build_collection_name("doc_memory", "v1") == "mcp_client_doc_memory_v1"

    def test_conversation_memory_name(self):
        store = self._make_store()
        assert store.build_collection_name("conversation_memory", "v1") == "mcp_client_conversation_memory_v1"

    def test_tool_cache_name(self):
        store = self._make_store()
        assert store.build_collection_name("tool_cache", "v1") == "mcp_client_tool_cache_v1"

    def test_unknown_collection_key_raises(self):
        """TR-MVS-09: Unknown collection keys are rejected at the naming boundary."""
        store = self._make_store()
        try:
            store.build_collection_name("unknown_collection", "v1")
        except MilvusCollectionConfigError:
            pass
        else:
            raise AssertionError("Expected MilvusCollectionConfigError for unknown collection key")


class TestMilvusStoreGenerationIsolation:
    """TR-MVS-10: Different generations produce distinct, non-interfering collections."""

    def _make_store_and_client(self):
        client = _FakeMilvusClient()
        store = MilvusStore(
            milvus_uri="http://milvus.local",
            client=client,
            client_factory=_FakeMilvusClientFactory,
        )
        return store, client

    def test_two_generations_produce_distinct_collections(self):
        store, client = self._make_store_and_client()

        name_v1 = store.ensure_collection(collection_key="code_memory", generation="v1", dimension=3)
        name_v2 = store.ensure_collection(collection_key="code_memory", generation="v2", dimension=3)

        assert name_v1 == "mcp_client_code_memory_v1"
        assert name_v2 == "mcp_client_code_memory_v2"
        assert len(client.created_calls) == 2
        names_created = [call["collection_name"] for call in client.created_calls]
        assert "mcp_client_code_memory_v1" in names_created
        assert "mcp_client_code_memory_v2" in names_created

    def test_upsert_to_v2_does_not_touch_v1(self):
        """TR-MVS-11: Upsert into v2 collection leaves v1 untouched."""
        store, client = self._make_store_and_client()
        store.ensure_collection(collection_key="doc_memory", generation="v1", dimension=3)

        store.upsert(
            collection_key="doc_memory",
            generation="v2",
            dimension=3,
            records=[{"id": "doc-v2", "embedding": [0.1, 0.2, 0.3], "source_path": "README.md", "payload_ref": "p://doc/r/README.md#s"}],
        )

        assert len(client.upsert_calls) == 1
        assert client.upsert_calls[0]["collection_name"] == "mcp_client_doc_memory_v2"

    def test_drop_v2_leaves_v1_intact(self):
        """TR-MVS-12: Dropping one generation does not affect another."""
        store, client = self._make_store_and_client()
        store.ensure_collection(collection_key="code_memory", generation="v1", dimension=3)
        store.ensure_collection(collection_key="code_memory", generation="v2", dimension=3)

        store.drop_collection(collection_key="code_memory", generation="v2")

        remaining = store.list_collections()
        assert "mcp_client_code_memory_v1" in remaining
        assert "mcp_client_code_memory_v2" not in remaining

    def test_ensure_collection_idempotent_per_generation(self):
        """TR-MVS-13: Repeated ensure_collection calls for same (key, generation) create exactly one collection."""
        store, client = self._make_store_and_client()

        for _ in range(5):
            store.ensure_collection(collection_key="tool_cache", generation="v1", dimension=8)

        assert len(client.created_calls) == 1


class TestMilvusStoreInputValidation:
    """TR-MVS-14: Store rejects malformed inputs at the earliest opportunity."""

    def _make_store(self):
        return MilvusStore(
            milvus_uri="http://milvus.local",
            client=_FakeMilvusClient(),
            client_factory=_FakeMilvusClientFactory,
        )

    def test_zero_dimension_raises(self):
        store = self._make_store()
        try:
            store.ensure_collection(collection_key="code_memory", generation="v1", dimension=0)
        except MilvusCollectionConfigError as error:
            assert "dimension" in str(error).lower()
        else:
            raise AssertionError("Expected MilvusCollectionConfigError for zero dimension")

    def test_negative_dimension_raises(self):
        store = self._make_store()
        try:
            store.ensure_collection(collection_key="code_memory", generation="v1", dimension=-1)
        except MilvusCollectionConfigError as error:
            assert "dimension" in str(error).lower()
        else:
            raise AssertionError("Expected MilvusCollectionConfigError for negative dimension")

    def test_empty_records_raises(self):
        store = self._make_store()
        try:
            store.upsert(collection_key="code_memory", generation="v1", dimension=3, records=[])
        except MilvusCollectionConfigError as error:
            assert "records" in str(error).lower() or "empty" in str(error).lower()
        else:
            raise AssertionError("Expected MilvusCollectionConfigError for empty records")

    def test_wrong_embedding_length_raises(self):
        store = self._make_store()
        try:
            store.upsert(
                collection_key="code_memory",
                generation="v1",
                dimension=4,
                records=[{"id": "x", "embedding": [0.1, 0.2, 0.3]}],  # dim=3 but declared=4
            )
        except MilvusCollectionConfigError as error:
            assert "dimension 4" in str(error)
        else:
            raise AssertionError("Expected MilvusCollectionConfigError for wrong embedding length")

    def test_missing_record_id_raises(self):
        store = self._make_store()
        try:
            store.upsert(
                collection_key="code_memory",
                generation="v1",
                dimension=3,
                records=[{"embedding": [0.1, 0.2, 0.3]}],  # no "id"
            )
        except MilvusCollectionConfigError as error:
            assert "id" in str(error).lower()
        else:
            raise AssertionError("Expected MilvusCollectionConfigError for missing record id")


class TestMilvusStoreDropNoOp:
    """TR-MVS-15: drop_collection on a non-existent collection is silently ignored."""

    def test_drop_non_existent_collection_is_silent(self):
        client = _FakeMilvusClient()
        store = MilvusStore(
            milvus_uri="http://milvus.local",
            client=client,
            client_factory=_FakeMilvusClientFactory,
        )

        # Should not raise even though the collection was never created
        store.drop_collection(collection_key="code_memory", generation="v99")

        assert client.drop_calls == []
