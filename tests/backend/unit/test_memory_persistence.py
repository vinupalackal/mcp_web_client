"""Unit tests for memory sidecar persistence adapter (TR-MP-*)."""

import json

import pytest

from backend.memory_persistence import MemoryPersistence


class TestMemoryPersistence:

    def test_upsert_payload_ref_persists_and_updates_metadata(self, sso_db):
        """TR-MP-01: Payload refs round-trip and update by stable payload_ref."""
        persistence = MemoryPersistence(session_factory=sso_db)

        created = persistence.upsert_payload_ref(
            payload_ref="payload://code/repo1/src/main.c#main",
            payload_kind="code_chunk",
            payload_text="int main() { return 0; }",
            collection_key="code_memory",
            metadata_json={"language": "c", "symbol": "main"},
            source_hash="sha256:abc",
        )

        updated = persistence.upsert_payload_ref(
            payload_ref=created.payload_ref,
            payload_kind="code_chunk",
            payload_text="int main() { return 42; }",
            metadata_json={"language": "c", "symbol": "main", "updated": True},
        )
        resolved = persistence.get_payload_ref(created.payload_ref)

        assert created.payload_ref == updated.payload_ref
        assert resolved is not None
        assert resolved.payload_text == "int main() { return 42; }"
        assert json.loads(resolved.metadata_json)["updated"] is True

    def test_create_and_update_ingestion_job(self, sso_db):
        """TR-MP-02: Ingestion jobs can be created and updated by job_id."""
        persistence = MemoryPersistence(session_factory=sso_db)

        job = persistence.create_ingestion_job(
            job_type="code_ingestion",
            status="pending",
            repo_id="repo1",
            scope_json={"paths": ["src/"]},
            collection_key="code_memory",
        )

        updated = persistence.update_ingestion_job(
            job.job_id,
            status="completed",
            source_count=12,
            chunk_count=48,
            error_count=0,
        )
        loaded = persistence.get_ingestion_job(job.job_id)

        assert updated.status == "completed"
        assert loaded is not None
        assert loaded.chunk_count == 48
        assert json.loads(loaded.scope_json)["paths"] == ["src/"]

    def test_update_unknown_ingestion_job_raises(self, sso_db):
        """TR-MP-03: Unknown job updates fail clearly."""
        persistence = MemoryPersistence(session_factory=sso_db)

        with pytest.raises(ValueError, match="Unknown ingestion job"):
            persistence.update_ingestion_job("missing-job", status="failed")

    def test_collection_version_activation_switches_active_generation(self, sso_db):
        """TR-MP-04: Activating a version marks exactly one generation active per collection key."""
        persistence = MemoryPersistence(session_factory=sso_db)

        first = persistence.create_collection_version(
            collection_key="code_memory",
            collection_name="mcp_client_code_memory_v1_20260330",
            generation="20260330",
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_dimension=1536,
            is_active=True,
            schema_json={"payload_ref": "VARCHAR"},
        )
        second = persistence.create_collection_version(
            collection_key="code_memory",
            collection_name="mcp_client_code_memory_v1_20260331",
            generation="20260331",
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_dimension=1536,
            is_active=False,
            schema_json={"payload_ref": "VARCHAR"},
        )

        activated = persistence.activate_collection_version(
            collection_key="code_memory",
            version_id=second.version_id,
        )
        versions = persistence.list_collection_versions("code_memory")

        assert activated.version_id == second.version_id
        assert [row.version_id for row in versions] == [first.version_id, second.version_id]
        old_row = next(row for row in versions if row.version_id == first.version_id)
        new_row = next(row for row in versions if row.version_id == second.version_id)
        assert old_row.is_active is False
        assert old_row.retired_at is not None
        assert new_row.is_active is True
        assert new_row.activated_at is not None

    def test_activate_unknown_collection_version_raises(self, sso_db):
        """TR-MP-05: Unknown collection activations fail clearly."""
        persistence = MemoryPersistence(session_factory=sso_db)
        persistence.create_collection_version(
            collection_key="doc_memory",
            collection_name="mcp_client_doc_memory_v1_20260330",
            generation="20260330",
        )

        with pytest.raises(ValueError, match="not found"):
            persistence.activate_collection_version(
                collection_key="doc_memory",
                version_id="missing-version",
            )

    def test_record_and_filter_retrieval_provenance(self, sso_db):
        """TR-MP-06: Retrieval provenance rows are recorded and filterable."""
        persistence = MemoryPersistence(session_factory=sso_db)

        row_one = persistence.record_retrieval_provenance(
            request_id="req-1",
            session_id="sess-1",
            user_id="user-1",
            repo_id="repo-1",
            retrieval_scope="workspace",
            query_text="find the entry point",
            selected_count=2,
            selected_refs_json=[
                "payload://code/repo1/src/main.c#main",
                "payload://doc/repo1/README.md#build",
            ],
            rationale_json={"reason": "top semantic matches"},
        )
        persistence.record_retrieval_provenance(
            request_id="req-2",
            session_id="sess-2",
            query_text="find build docs",
            selected_count=1,
            selected_refs_json=["payload://doc/repo1/README.md#build"],
            rationale_json={"reason": "doc similarity"},
        )

        filtered = persistence.list_retrieval_provenance(request_id="req-1")

        assert row_one.request_id == "req-1"
        assert len(filtered) == 1
        assert filtered[0].session_id == "sess-1"
        assert json.loads(filtered[0].selected_refs_json)[0].startswith("payload://code/")

    def test_non_serializable_json_input_raises(self, sso_db):
        """TR-MP-07: Non-JSON-serializable payload metadata fails clearly."""
        persistence = MemoryPersistence(session_factory=sso_db)

        with pytest.raises(ValueError, match="JSON-serializable"):
            persistence.upsert_payload_ref(
                payload_ref="payload://code/repo1/src/main.c#main",
                payload_kind="code_chunk",
                payload_text="int main() { return 0; }",
                metadata_json={"bad": {1, 2, 3}},
            )
