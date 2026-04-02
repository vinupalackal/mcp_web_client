"""Unit tests for ingestion pipeline service (TR-ING-*)."""

import pytest

from backend.ingestion_service import IngestionService


class _FakeEmbeddingResult:
    def __init__(self, count, dimensions=3):
        self.dimensions = dimensions
        self.vectors = [[float(index + 1), 0.1, 0.2] for index in range(count)]


class _FakeEmbeddingService:
    def __init__(self):
        self.calls = []

    async def embed_texts(self, texts, expected_dimensions=None):
        self.calls.append(list(texts))
        return _FakeEmbeddingResult(len(texts))


class _FakeMilvusStore:
    def __init__(self):
        self.upsert_calls = []
        self.delete_calls = []

    def upsert(self, *, collection_key, generation, dimension, records):
        self.upsert_calls.append(
            {
                "collection_key": collection_key,
                "generation": generation,
                "dimension": dimension,
                "records": records,
            }
        )
        return {"upsert_count": len(records)}

    def delete_by_ids(self, *, collection_key, generation, ids):
        self.delete_calls.append(
            {
                "collection_key": collection_key,
                "generation": generation,
                "ids": ids,
            }
        )
        return {"delete_count": len(ids)}


class _Row:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeMemoryPersistence:
    def __init__(self):
        self.job_counter = 0
        self.jobs = {}
        self.payload_refs = {}
        self.deleted_payload_refs = []

    def create_ingestion_job(self, **fields):
        self.job_counter += 1
        job = _Row(job_id=f"job-{self.job_counter}", **fields)
        self.jobs[job.job_id] = job
        return job

    def update_ingestion_job(self, job_id, **fields):
        job = self.jobs[job_id]
        for key, value in fields.items():
            setattr(job, key, value)
        return job

    def upsert_payload_ref(self, **fields):
        row = _Row(**fields)
        self.payload_refs[fields["payload_ref"]] = row
        return row

    def list_payload_refs(self, *, collection_key=None, repo_id=None, source_path=None, payload_kind=None):
        rows = list(self.payload_refs.values())
        if collection_key is not None:
            rows = [row for row in rows if getattr(row, "collection_key", None) == collection_key]
        if repo_id is not None:
            rows = [row for row in rows if getattr(row, "repo_id", None) == repo_id]
        if source_path is not None:
            rows = [row for row in rows if getattr(row, "source_path", None) == source_path]
        if payload_kind is not None:
            rows = [row for row in rows if getattr(row, "payload_kind", None) == payload_kind]
        return rows

    def delete_payload_refs(self, payload_refs):
        for payload_ref in payload_refs:
            self.payload_refs.pop(payload_ref, None)
            self.deleted_payload_refs.append(payload_ref)
        return len(payload_refs)


class TestIngestionService:

    @pytest.mark.asyncio
    async def test_ingests_code_and_doc_roots_and_writes_chunks(self, tmp_path):
        """TR-ING-01: Code and docs are scanned, chunked, embedded, and written to store + persistence."""
        src_root = tmp_path / "src"
        docs_root = tmp_path / "docs"
        src_root.mkdir()
        docs_root.mkdir()
        (src_root / "main.c").write_text("int main() { return 0; }\n", encoding="utf-8")
        (docs_root / "README.md").write_text("# Intro\nHello world\n\n# Usage\nRun the app\n", encoding="utf-8")

        embedding = _FakeEmbeddingService()
        store = _FakeMilvusStore()
        persistence = _FakeMemoryPersistence()
        service = IngestionService(
            embedding_service=embedding,
            milvus_store=store,
            memory_persistence=persistence,
            repo_roots=[str(src_root)],
            doc_roots=[str(docs_root)],
        )

        result = await service.ingest_workspace_async(repo_id="workspace-main")

        assert result["status"] == "completed"
        assert result["source_count"] == 2
        assert result["chunk_count"] >= 3
        assert len(embedding.calls) == 2
        assert {call["collection_key"] for call in store.upsert_calls} == {"code_memory", "doc_memory"}
        assert any(row.payload_kind == "code_chunk" for row in persistence.payload_refs.values())
        assert any(row.payload_kind == "doc_chunk" for row in persistence.payload_refs.values())

    @pytest.mark.asyncio
    async def test_partial_file_failures_do_not_abort_job(self, tmp_path):
        """TR-ING-02: Per-file parse/read failures are recorded but remaining files still ingest."""
        src_root = tmp_path / "src"
        src_root.mkdir()
        (src_root / "good.c").write_text("int main() { return 0; }\n", encoding="utf-8")
        (src_root / "bad.c").write_bytes(b"\xff\xfe\x00\x00")

        embedding = _FakeEmbeddingService()
        store = _FakeMilvusStore()
        persistence = _FakeMemoryPersistence()
        service = IngestionService(
            embedding_service=embedding,
            milvus_store=store,
            memory_persistence=persistence,
            repo_roots=[str(src_root)],
        )

        result = await service.ingest_workspace_async(repo_id="workspace-main")

        assert result["status"] == "completed_with_errors"
        assert result["error_count"] == 1
        assert result["chunk_count"] >= 1
        assert store.upsert_calls[0]["collection_key"] == "code_memory"

    @pytest.mark.asyncio
    async def test_stale_chunks_are_removed_from_store_and_persistence(self, tmp_path):
        """TR-ING-03: Missing current payload refs trigger stale Milvus + sidecar cleanup."""
        src_root = tmp_path / "src"
        src_root.mkdir()
        (src_root / "main.c").write_text("int main() { return 0; }\n", encoding="utf-8")

        embedding = _FakeEmbeddingService()
        store = _FakeMilvusStore()
        persistence = _FakeMemoryPersistence()
        persistence.payload_refs["payload://code/workspace-main/src/old.c#file"] = _Row(
            payload_ref="payload://code/workspace-main/src/old.c#file",
            collection_key="code_memory",
            repo_id="workspace-main",
            memory_id="stale-chunk-id",
            payload_kind="code_chunk",
            source_path="src/old.c",
        )

        service = IngestionService(
            embedding_service=embedding,
            milvus_store=store,
            memory_persistence=persistence,
            repo_roots=[str(src_root)],
        )

        result = await service.ingest_workspace_async(repo_id="workspace-main")

        assert result["deleted_count"] == 1
        assert store.delete_calls[0]["ids"] == ["stale-chunk-id"]
        assert "payload://code/workspace-main/src/old.c#file" in persistence.deleted_payload_refs

    @pytest.mark.asyncio
    async def test_excluded_dirs_are_not_scanned(self, tmp_path):
        """TR-ING-04: Files under excluded_dirs are never opened, chunked, or embedded."""
        src_root = tmp_path / "src"
        build_dir = src_root / "build"
        build_dir.mkdir(parents=True)
        (src_root / "main.c").write_text("int main() { return 0; }\n", encoding="utf-8")
        (build_dir / "generated.c").write_text("// auto-generated\nint gen() { return 1; }\n", encoding="utf-8")

        embedding = _FakeEmbeddingService()
        store = _FakeMilvusStore()
        persistence = _FakeMemoryPersistence()
        service = IngestionService(
            embedding_service=embedding,
            milvus_store=store,
            memory_persistence=persistence,
            repo_roots=[str(src_root)],
            excluded_dirs={"build"},
        )

        result = await service.ingest_workspace_async(repo_id="workspace-excl")

        # Only main.c is scanned; generated.c is excluded
        assert result["source_count"] == 1
        assert result["chunk_count"] >= 1
        for ref in persistence.payload_refs:
            assert "generated" not in ref, f"excluded file reached persistence: {ref}"

    @pytest.mark.asyncio
    async def test_empty_workspace_produces_completed_zero_chunks(self, tmp_path):
        """TR-ING-05: A workspace with no scannable files returns completed status with zero counts."""
        empty_src = tmp_path / "empty_src"
        empty_src.mkdir()
        # Write a non-code, non-doc file that should not be ingested
        (empty_src / "notes.log").write_text("some log output", encoding="utf-8")

        embedding = _FakeEmbeddingService()
        store = _FakeMilvusStore()
        persistence = _FakeMemoryPersistence()
        service = IngestionService(
            embedding_service=embedding,
            milvus_store=store,
            memory_persistence=persistence,
            repo_roots=[str(empty_src)],
        )

        result = await service.ingest_workspace_async(repo_id="workspace-empty")

        assert result["status"] == "completed"
        assert result["chunk_count"] == 0
        assert result["deleted_count"] == 0
        assert result["error_count"] == 0
        assert store.upsert_calls == []

    @pytest.mark.asyncio
    async def test_unchanged_file_not_stale_on_second_run(self, tmp_path):
        """TR-ING-06: A file with unchanged content keeps its payload_ref; it is NOT stale on re-ingestion."""
        src_root = tmp_path / "src"
        src_root.mkdir()
        (src_root / "stable.c").write_text("int stable() { return 42; }\n", encoding="utf-8")

        embedding = _FakeEmbeddingService()
        store = _FakeMilvusStore()
        persistence = _FakeMemoryPersistence()
        service = IngestionService(
            embedding_service=embedding,
            milvus_store=store,
            memory_persistence=persistence,
            repo_roots=[str(src_root)],
        )

        # First run — ingests stable.c
        result1 = await service.ingest_workspace_async(repo_id="workspace-stable")
        assert result1["chunk_count"] >= 1
        refs_after_first = set(persistence.payload_refs.keys())

        # Second run — same file, same content
        result2 = await service.ingest_workspace_async(repo_id="workspace-stable")

        # The ref from the first run matches the ref produced in the second run, so deleted_count stays 0
        assert result2["deleted_count"] == 0
        assert store.delete_calls == []
        # The ref should still be present
        for ref in refs_after_first:
            assert ref in persistence.payload_refs

    @pytest.mark.asyncio
    async def test_collection_generation_propagates_to_store_calls(self, tmp_path):
        """TR-ING-07: The collection_generation kwarg reaches every store.upsert and store.delete_by_ids call."""
        src_root = tmp_path / "src"
        src_root.mkdir()
        (src_root / "main.c").write_text("int main() { return 0; }\n", encoding="utf-8")

        # Pre-populate a stale ref so _remove_stale_chunks also fires
        embedding = _FakeEmbeddingService()
        store = _FakeMilvusStore()
        persistence = _FakeMemoryPersistence()
        persistence.payload_refs["payload://code/workspace-gen/src/gone.c#file"] = _Row(
            payload_ref="payload://code/workspace-gen/src/gone.c#file",
            collection_key="code_memory",
            repo_id="workspace-gen",
            memory_id="old-id",
            payload_kind="code_chunk",
            source_path="src/gone.c",
        )

        service = IngestionService(
            embedding_service=embedding,
            milvus_store=store,
            memory_persistence=persistence,
            repo_roots=[str(src_root)],
            collection_generation="v3",
        )

        await service.ingest_workspace_async(repo_id="workspace-gen")

        for upsert_call in store.upsert_calls:
            assert upsert_call["generation"] == "v3", f"expected v3, got {upsert_call['generation']}"
        for delete_call in store.delete_calls:
            assert delete_call["generation"] == "v3", f"expected v3, got {delete_call['generation']}"
