"""Integration tests wiring IngestionService + MilvusStore with a fake Milvus client.

These tests verify that the `collection_generation` configured on `IngestionService`
reaches the correct Milvus collection name, and that stale-chunk cleanup always
targets the right generation.  No real Milvus instance is required.

Test IDs: TC-INT-01 through TC-INT-04.
"""

from __future__ import annotations

import pytest

from backend.ingestion_service import IngestionService
from backend.milvus_store import MilvusStore


# ---------------------------------------------------------------------------
# Fake Milvus client (mirrors the one in test_milvus_store.py for isolation)
# ---------------------------------------------------------------------------

class _FakeSchema:
    def __init__(self):
        self.fields = []

    def add_field(self, field_name, datatype, **kwargs):
        self.fields.append({"field_name": field_name, "datatype": datatype, **kwargs})


class _FakeIndexParams:
    def __init__(self):
        self.indexes = []

    def add_index(self, field_name, index_type="", index_name="", **kwargs):
        self.indexes.append({"field_name": field_name, "index_type": index_type, "index_name": index_name, **kwargs})


class _FakeMilvusClientFactory:
    @staticmethod
    def create_schema(**kwargs):
        return _FakeSchema()

    @staticmethod
    def prepare_index_params():
        return _FakeIndexParams()


class _FakeMilvusClient:
    def __init__(self):
        self.collections: dict = {}
        self.created_calls: list = []
        self.upsert_calls: list = []
        self.search_calls: list = []
        self.delete_calls: list = []
        self.drop_calls: list = []

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

    def search(self, collection_name, data, filter="", limit=10, output_fields=None,
               search_params=None, timeout=None, partition_names=None, anns_field=None, **kwargs):
        self.search_calls.append({"collection_name": collection_name})
        return [[{"id": "chunk-1", "distance": 0.01}]]

    def delete(self, collection_name, ids=None, timeout=None, filter=None,
               partition_name=None, **kwargs):
        self.delete_calls.append({"collection_name": collection_name, "ids": ids, "filter": filter})
        return {"delete_count": len(ids or []) if ids is not None else 1}

    def drop_collection(self, collection_name, timeout=None, **kwargs):
        self.drop_calls.append(collection_name)
        self.collections.pop(collection_name, None)

    def list_collections(self, **kwargs):
        return list(self.collections.keys())


# ---------------------------------------------------------------------------
# Fake embedding service
# ---------------------------------------------------------------------------

class _FakeEmbeddingResult:
    def __init__(self, count, dimensions=3):
        self.dimensions = dimensions
        self.vectors = [[float(i + 1), 0.1, 0.2] for i in range(count)]


class _FakeEmbeddingService:
    async def embed_texts(self, texts, expected_dimensions=None):
        return _FakeEmbeddingResult(len(texts))


# ---------------------------------------------------------------------------
# Fake memory persistence (minimal, for integration scope)
# ---------------------------------------------------------------------------

class _Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeMemoryPersistence:
    def __init__(self):
        self.job_counter = 0
        self.jobs: dict = {}
        self.payload_refs: dict = {}
        self.deleted_payload_refs: list = []

    def create_ingestion_job(self, **fields):
        self.job_counter += 1
        job = _Row(job_id=f"job-{self.job_counter}", **fields)
        self.jobs[job.job_id] = job
        return job

    def update_ingestion_job(self, job_id, **fields):
        job = self.jobs[job_id]
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    def upsert_payload_ref(self, **fields):
        row = _Row(**fields)
        self.payload_refs[fields["payload_ref"]] = row
        return row

    def list_payload_refs(self, *, collection_key=None, repo_id=None,
                          source_path=None, payload_kind=None):
        rows = list(self.payload_refs.values())
        if collection_key is not None:
            rows = [r for r in rows if getattr(r, "collection_key", None) == collection_key]
        if repo_id is not None:
            rows = [r for r in rows if getattr(r, "repo_id", None) == repo_id]
        return rows

    def delete_payload_refs(self, payload_refs):
        for ref in payload_refs:
            self.payload_refs.pop(ref, None)
            self.deleted_payload_refs.append(ref)
        return len(payload_refs)


# ---------------------------------------------------------------------------
# Helper: build a service wired to a real MilvusStore + fake Milvus client
# ---------------------------------------------------------------------------

def _make_wired_service(
    tmp_src_root,
    *,
    generation: str = "v1",
    persistence=None,
) -> tuple[IngestionService, _FakeMilvusClient, _FakeMemoryPersistence]:
    client = _FakeMilvusClient()
    store = MilvusStore(
        milvus_uri="http://milvus.local",
        client=client,
        client_factory=_FakeMilvusClientFactory,
    )
    if persistence is None:
        persistence = _FakeMemoryPersistence()
    service = IngestionService(
        embedding_service=_FakeEmbeddingService(),
        milvus_store=store,
        memory_persistence=persistence,
        repo_roots=[str(tmp_src_root)],
        collection_generation=generation,
    )
    return service, client, persistence


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestIngestionStoreCrossGeneration:

    @pytest.mark.asyncio
    async def test_v1_generation_creates_v1_collection(self, tmp_path):
        """TC-INT-01: Ingestion with generation='v1' creates mcp_client_code_memory_v1."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.c").write_text("int main() { return 0; }\n", encoding="utf-8")

        service, client, _ = _make_wired_service(src, generation="v1")
        result = await service.ingest_workspace_async(repo_id="workspace-int")

        assert result["status"] == "completed"
        collection_names = set(client.collections.keys())
        assert any("code_memory_v1" in name for name in collection_names), (
            f"Expected a v1 code_memory collection; got {collection_names}"
        )

    @pytest.mark.asyncio
    async def test_v2_generation_creates_v2_not_v1(self, tmp_path):
        """TC-INT-02: Ingestion with generation='v2' creates v2 collection without touching v1."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.c").write_text("int main() { return 0; }\n", encoding="utf-8")

        service, client, _ = _make_wired_service(src, generation="v2")
        await service.ingest_workspace_async(repo_id="workspace-int")

        collection_names = set(client.collections.keys())
        assert any("code_memory_v2" in name for name in collection_names), (
            f"Expected a v2 code_memory collection; got {collection_names}"
        )
        assert not any("code_memory_v1" in name for name in collection_names), (
            f"v1 collection should not exist when generation=v2; got {collection_names}"
        )

    @pytest.mark.asyncio
    async def test_stale_cleanup_targets_correct_generation(self, tmp_path):
        """TC-INT-03: Stale-chunk deletion calls use the same generation as the ingestion run."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.c").write_text("int main() { return 0; }\n", encoding="utf-8")

        # Pre-populate a stale ref for the same repo_id
        persistence = _FakeMemoryPersistence()
        persistence.payload_refs["payload://code/workspace-int/src/gone.c#file"] = _Row(
            payload_ref="payload://code/workspace-int/src/gone.c#file",
            collection_key="code_memory",
            repo_id="workspace-int",
            memory_id="stale-id",
            payload_kind="code_chunk",
            source_path="src/gone.c",
        )

        service, client, _ = _make_wired_service(src, generation="v3", persistence=persistence)
        result = await service.ingest_workspace_async(repo_id="workspace-int")

        assert result["deleted_count"] == 1

        # Every client.delete call must target the v3 collection name
        for delete_call in client.delete_calls:
            assert "v3" in delete_call["collection_name"], (
                f"Expected v3 in delete call but got: {delete_call['collection_name']}"
            )

    @pytest.mark.asyncio
    async def test_payload_refs_consistent_between_persistence_and_store(self, tmp_path):
        """TC-INT-04: payload_ref in sidecar persistence matches the payload_ref field in upserted records."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "api.c").write_text("int init_api(void) { return 0; }\n", encoding="utf-8")

        service, client, persistence = _make_wired_service(src, generation="v1")
        await service.ingest_workspace_async(repo_id="workspace-ref")

        # Collect all payload_refs written to persistence
        persisted_refs = set(persistence.payload_refs.keys())

        # Collect all payload_refs written to the Milvus store
        stored_refs: set[str] = set()
        for call in client.upsert_calls:
            for record in call["data"]:
                if "payload_ref" in record:
                    stored_refs.add(record["payload_ref"])

        # Every persisted ref should match a stored ref (1-to-1 for this single-file workspace)
        assert persisted_refs == stored_refs, (
            f"Persistence refs {persisted_refs} do not match store refs {stored_refs}"
        )
