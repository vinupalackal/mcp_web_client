"""Unit tests for retrieval orchestration service (TC-MEM-*)."""

import asyncio
import logging

import pytest

from backend.memory_service import (
    MemoryService,
    MemoryServiceConfig,
    ToolCacheResult,
)


class _FakeEmbeddingResult:
    def __init__(self, vectors):
        self.vectors = vectors
        self.dimensions = len(vectors[0]) if vectors else 0


class _FakeEmbeddingService:
    def __init__(self, *, vectors=None, delay_s=0.0, error=None):
        self.vectors = vectors or [[0.1, 0.2, 0.3]]
        self.delay_s = delay_s
        self.error = error
        self.calls = []

    async def embed_texts(self, texts, expected_dimensions=None):
        self.calls.append({"texts": list(texts), "expected_dimensions": expected_dimensions})
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.error is not None:
            raise self.error
        return _FakeEmbeddingResult(self.vectors)


class _FakeMilvusStore:
    def __init__(self, *, search_results=None, search_error=None, collections=None, list_error=None, record_counts=None):
        self.search_results = search_results or {}
        self.search_error = search_error
        self.collections = collections or ["mcp_client_code_memory_v1", "mcp_client_doc_memory_v1"]
        self.list_error = list_error
        self.record_counts = record_counts or {}
        self.search_calls = []
        self.delete_calls = []

    def search(self, *, collection_key, generation, query_vectors, limit=5, filter_expression="", output_fields=None, search_params=None):
        self.search_calls.append(
            {
                "collection_key": collection_key,
                "generation": generation,
                "query_vectors": query_vectors,
                "limit": limit,
                "filter_expression": filter_expression,
                "output_fields": output_fields,
                "search_params": search_params,
            }
        )
        if self.search_error is not None:
            raise self.search_error
        return self.search_results.get(collection_key, [[]])

    def list_collections(self):
        if self.list_error is not None:
            raise self.list_error
        return list(self.collections)

    def get_record_count(self, *, collection_key, generation):
        value = self.record_counts.get(collection_key, 0)
        if isinstance(value, list):
            if len(value) > 1:
                return value.pop(0)
            return value[0]
        return value

    def build_collection_name(self, collection_key, generation):
        return f"mcp_client_{collection_key}_{generation}"

    def delete_by_filter(self, *, collection_key, generation, filter_expression):
        self.delete_calls.append(
            {
                "collection_key": collection_key,
                "generation": generation,
                "filter_expression": filter_expression,
            }
        )
        return {"delete_count": 0}


class _FakeMemoryPersistence:
    def __init__(self, *, error=None):
        self.error = error
        self.provenance_calls = []
        self.expire_conversation_calls = []
        self.expire_tool_cache_calls = []

    def record_retrieval_provenance(self, **fields):
        self.provenance_calls.append(fields)
        if self.error is not None:
            raise self.error
        return fields

    def expire_conversation_turns(self, **fields):
        self.expire_conversation_calls.append(fields)
        if self.error is not None:
            raise self.error
        return 0

    def expire_tool_cache_entries(self, **fields):
        self.expire_tool_cache_calls.append(fields)
        if self.error is not None:
            raise self.error
        return 0


class TestMemoryService:

    def test_memory_service_config_accepts_aql_defaults(self):
        """TC-AQL-P1-CFG-03: runtime config should expose passive AQL defaults in Phase 1."""
        config = MemoryServiceConfig()

        assert config.enable_adaptive_learning is False
        assert config.aql_quality_retention_days == 30
        assert config.aql_min_records_for_routing == 20
        assert config.aql_affinity_confidence_threshold == 0.65
        assert config.aql_chunk_reorder_threshold == 0.70
        assert config.aql_affinity_weights["similarity"] == 0.5
        assert r"\bwrong\b" in config.aql_correction_patterns

    def test_memory_service_config_accepts_custom_aql_values(self):
        """TC-AQL-P1-CFG-04: runtime config should accept custom Phase 1 AQL values."""
        config = MemoryServiceConfig(
            enable_adaptive_learning=True,
            aql_quality_retention_days=14,
            aql_min_records_for_routing=9,
            aql_affinity_confidence_threshold=0.55,
            aql_chunk_reorder_threshold=0.66,
            aql_affinity_weights={"similarity": 0.8},
            aql_correction_patterns=(r"\bwrong\b",),
        )

        assert config.enable_adaptive_learning is True
        assert config.aql_quality_retention_days == 14
        assert config.aql_min_records_for_routing == 9
        assert config.aql_affinity_confidence_threshold == 0.55
        assert config.aql_chunk_reorder_threshold == 0.66
        assert config.aql_affinity_weights == {"similarity": 0.8}
        assert config.aql_correction_patterns == (r"\bwrong\b",)

    @pytest.mark.asyncio
    async def test_disabled_service_returns_empty_without_dependency_calls(self):
        """TC-MEM-01: Disabled service returns empty blocks and does not touch deps."""
        embedding = _FakeEmbeddingService()
        store = _FakeMilvusStore()
        persistence = _FakeMemoryPersistence()
        service = MemoryService(
            embedding_service=embedding,
            milvus_store=store,
            memory_persistence=persistence,
            config=MemoryServiceConfig(enabled=False),
        )

        result = await service.enrich_for_turn(
            user_message="find main",
            session_id="sess-1",
            repo_id="repo-1",
        )

        assert result.blocks == []
        assert result.degraded is False
        assert embedding.calls == []
        assert store.search_calls == []
        assert persistence.provenance_calls == []

    @pytest.mark.asyncio
    async def test_empty_collections_skips_embedding_call(self):
        """TC-MEM-SC-01: When collections_to_search is empty, the embedding call is skipped.

        Scenario: anonymous user (user_id='') with include_code_memory=False AND
        enable_conversation_memory=False.
        - code_memory / doc_memory excluded by include_code_memory=False
        - conversation_memory excluded because enable_conversation_memory=False
        → nothing to search; embed_texts must NOT be called.
        """
        embedding = _FakeEmbeddingService()
        store = _FakeMilvusStore()
        persistence = _FakeMemoryPersistence()
        service = MemoryService(
            embedding_service=embedding,
            milvus_store=store,
            memory_persistence=persistence,
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=False,  # disabled → conversation_memory excluded
                collection_keys=("code_memory", "doc_memory"),
            ),
        )

        result = await service.enrich_for_turn(
            user_message="how long has this been running?",
            session_id="sess-anon",
            user_id="",              # anonymous
            include_code_memory=False,  # planning phase
        )

        # No embedding call made
        assert embedding.calls == [], "embed_texts must not be called when collections_to_search is empty"
        # No Milvus search made
        assert store.search_calls == []
        # Result is empty and non-degraded
        assert result.blocks == []
        assert result.degraded is False
        assert result.latency_ms == 0.0

    @pytest.mark.asyncio
    async def test_empty_collections_skips_embedding_logged(self, caplog):
        """TC-MEM-SC-02: Short-circuit path emits an info log with the correct fields."""
        embedding = _FakeEmbeddingService()
        service = MemoryService(
            embedding_service=embedding,
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=False,
                collection_keys=("code_memory", "doc_memory"),
            ),
        )

        with caplog.at_level(logging.INFO, logger="mcp_client.internal"):
            await service.enrich_for_turn(
                user_message="any query",
                session_id="sess-1",
                request_id="req-skip-42",
                user_id="",
                include_code_memory=False,
            )

        assert "Memory retrieval skipped" in caplog.text
        assert "no collections to search" in caplog.text
        assert embedding.calls == []

    @pytest.mark.asyncio
    async def test_non_empty_collections_still_embeds(self):
        """TC-MEM-SC-03: When collections_to_search is non-empty the embedding call IS made."""
        embedding = _FakeEmbeddingService()
        service = MemoryService(
            embedding_service=embedding,
            milvus_store=_FakeMilvusStore(
                search_results={"code_memory": [[]], "doc_memory": [[]]}
            ),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                collection_keys=("code_memory", "doc_memory"),
            ),
        )

        await service.enrich_for_turn(
            user_message="find something",
            session_id="sess-1",
            user_id="user-1",
            include_code_memory=True,
        )

        # Embedding must be called since code_memory + doc_memory are in scope
        assert len(embedding.calls) == 1

    @pytest.mark.asyncio
    async def test_anonymous_with_code_memory_true_still_embeds(self):
        """TC-MEM-SC-04: Anonymous user with include_code_memory=True (synthesis phase)
        still embeds because code/doc collections are in scope."""
        embedding = _FakeEmbeddingService()
        service = MemoryService(
            embedding_service=embedding,
            milvus_store=_FakeMilvusStore(
                search_results={"code_memory": [[]], "doc_memory": [[]]}
            ),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=True,
                collection_keys=("code_memory", "doc_memory"),
            ),
        )

        await service.enrich_for_turn(
            user_message="explain the result",
            session_id="sess-1",
            user_id="",              # anonymous
            include_code_memory=True,  # synthesis phase — code/doc still searched
        )

        assert len(embedding.calls) == 1

    @pytest.mark.asyncio
    async def test_anonymous_planning_phase_embeds_for_conversation_memory(self):
        """TC-MEM-SC-04b: Anonymous user with include_code_memory=False still embeds
        because conversation_memory is now included via the __anonymous__ scope.

        This is the key change from the anonymous-mode fix: previously this would
        short-circuit and skip the Ollama embed call entirely; now it searches
        conversation_memory for past anonymous turns.
        """
        embedding = _FakeEmbeddingService()
        service = MemoryService(
            embedding_service=embedding,
            milvus_store=_FakeMilvusStore(
                search_results={"conversation_memory": [[]]}
            ),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=True,
                collection_keys=("code_memory", "doc_memory"),
            ),
        )

        await service.enrich_for_turn(
            user_message="follow up question",
            session_id="sess-anon",
            user_id="",              # anonymous
            include_code_memory=False,  # planning phase
        )

        # conversation_memory is now in scope, so embedding IS needed
        assert len(embedding.calls) == 1

    @pytest.mark.asyncio
    async def test_known_user_planning_phase_still_embeds_for_conversation_memory(self):
        """TC-MEM-SC-05: Known user with include_code_memory=False still embeds because
        conversation_memory is in scope."""
        embedding = _FakeEmbeddingService()
        service = MemoryService(
            embedding_service=embedding,
            milvus_store=_FakeMilvusStore(
                search_results={
                    "code_memory": [[]],
                    "doc_memory": [[]],
                    "conversation_memory": [[]],
                }
            ),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=True,
                collection_keys=("code_memory", "doc_memory"),
            ),
        )

        await service.enrich_for_turn(
            user_message="follow up question",
            session_id="sess-1",
            user_id="user-known",    # known user → conversation_memory included
            include_code_memory=False,  # planning phase
        )

        # conversation_memory is in scope so embedding is needed
        assert len(embedding.calls) == 1

    @pytest.mark.asyncio
    async def test_enrich_for_turn_logs_transaction_metadata(self, caplog):
        """TC-MEM-01b: Retrieval logging includes request, message, and result metadata."""
        embedding = _FakeEmbeddingService(vectors=[[0.1, 0.2, 0.3]])
        store = _FakeMilvusStore(
            search_results={
                "code_memory": [[{"entity": {"payload_ref": "chunk-1", "relative_path": "src/main.py", "summary": "main entry"}, "distance": 0.01}]],
                "doc_memory": [[]],
            }
        )
        persistence = _FakeMemoryPersistence()
        service = MemoryService(
            embedding_service=embedding,
            milvus_store=store,
            memory_persistence=persistence,
            config=MemoryServiceConfig(enabled=True),
        )

        with caplog.at_level(logging.INFO, logger="mcp_client.internal"):
            result = await service.enrich_for_turn(
                user_message="find the main entry point",
                session_id="sess-1",
                request_id="chat-123",
                user_id="user-1",
            )

        assert len(result.blocks) == 1
        assert "Memory retrieval transaction started" in caplog.text
        assert "chat-123" in caplog.text
        assert "find the main entry point" in caplog.text
        assert "Memory retrieval transaction completed" in caplog.text
        assert "result_count=1" in caplog.text

    @pytest.mark.asyncio
    async def test_happy_path_embeds_searches_caps_and_records_provenance(self):
        """TC-MEM-02: Happy path searches both collections, caps results, and records provenance."""
        embedding = _FakeEmbeddingService()
        store = _FakeMilvusStore(
            search_results={
                "code_memory": [[
                    {
                        "payload_ref": "payload://code/repo/src/main.c#main",
                        "relative_path": "src/main.c",
                        "summary": "main entry point",
                        "distance": 0.04,
                    },
                    {
                        "payload_ref": "payload://code/repo/src/util.c#util",
                        "relative_path": "src/util.c",
                        "summary": "utility function",
                        "distance": 0.20,
                    },
                ]],
                "doc_memory": [[
                    {
                        "payload_ref": "payload://doc/repo/README.md#usage",
                        "source_path": "README.md",
                        "summary": "usage instructions",
                        "distance": 0.10,
                    }
                ]],
            }
        )
        persistence = _FakeMemoryPersistence()
        service = MemoryService(
            embedding_service=embedding,
            milvus_store=store,
            memory_persistence=persistence,
            config=MemoryServiceConfig(enabled=True, repo_id="repo-main", max_results=2),
        )

        result = await service.enrich_for_turn(
            user_message="how does startup work",
            session_id="sess-1",
        )

        assert result.degraded is False
        assert len(result.blocks) == 2
        assert [block.payload_ref for block in result.blocks] == [
            "payload://code/repo/src/main.c#main",
            "payload://doc/repo/README.md#usage",
        ]
        assert len(embedding.calls) == 1
        assert len(store.search_calls) == 2
        assert persistence.provenance_calls[0]["session_id"] == "sess-1"
        assert persistence.provenance_calls[0]["selected_count"] == 2
        assert persistence.provenance_calls[0]["selected_refs_json"] == [
            "payload://code/repo/src/main.c#main",
            "payload://doc/repo/README.md#usage",
        ]

    @pytest.mark.asyncio
    async def test_embedding_failure_returns_degraded_empty_result(self):
        """TC-MEM-03: Embedding errors fail open with degraded result."""
        embedding = _FakeEmbeddingService(error=RuntimeError("embedding unavailable"))
        service = MemoryService(
            embedding_service=embedding,
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=True),
        )

        result = await service.enrich_for_turn(
            user_message="find init",
            session_id="sess-1",
        )

        assert result.blocks == []
        assert result.degraded is True
        assert "embedding unavailable" in result.degraded_reason

    @pytest.mark.asyncio
    async def test_store_search_failure_returns_degraded_empty_result(self):
        """TC-MEM-04: Milvus/store failures fail open with degraded result."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(search_error=RuntimeError("milvus down")),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=True),
        )

        result = await service.enrich_for_turn(
            user_message="find docs",
            session_id="sess-1",
        )

        assert result.blocks == []
        assert result.degraded is True
        assert "milvus down" in result.degraded_reason

    @pytest.mark.asyncio
    async def test_timeout_returns_degraded_empty_result(self):
        """TC-MEM-05: Retrieval timeout is converted into degraded fallback."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(delay_s=0.05),
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=True, retrieval_timeout_s=0.01),
        )

        result = await service.enrich_for_turn(
            user_message="find startup",
            session_id="sess-1",
        )

        assert result.blocks == []
        assert result.degraded is True
        assert "timeout" in result.degraded_reason.lower()

    @pytest.mark.asyncio
    async def test_health_status_reports_healthy_when_enabled_and_store_reachable(self):
        """TC-MEM-06: Health reports healthy when store is reachable."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(collections=["mcp_client_code_memory_v1"]),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=True),
        )

        result = await service.health_status()

        assert result["enabled"] is True
        assert result["healthy"] is True
        assert result["degraded"] is False
        assert result["status"] == "healthy"
        assert result["active_collections"] == ["mcp_client_code_memory_v1"]

    @pytest.mark.asyncio
    async def test_health_status_reports_degraded_when_store_unreachable(self):
        """TC-MEM-07: Health reports degraded when Milvus/store calls fail."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(list_error=RuntimeError("cannot connect")),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=True),
        )

        result = await service.health_status()

        assert result["enabled"] is True
        assert result["healthy"] is False
        assert result["degraded"] is True
        assert result["status"] == "degraded"
        assert "cannot connect" in result["reason"]

    @pytest.mark.asyncio
    async def test_result_capping_limits_merged_hits(self):
        """TC-MEM-08: Merged results are globally capped by max_results."""
        store = _FakeMilvusStore(
            search_results={
                "code_memory": [[
                    {"payload_ref": "p://1", "relative_path": "a.c", "summary": "a", "distance": 0.30},
                    {"payload_ref": "p://2", "relative_path": "b.c", "summary": "b", "distance": 0.10},
                ]],
                "doc_memory": [[
                    {"payload_ref": "p://3", "source_path": "README.md", "summary": "c", "distance": 0.20},
                ]],
            }
        )
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=True, max_results=2),
        )

        result = await service.enrich_for_turn(
            user_message="find docs",
            session_id="sess-1",
        )

        assert [block.payload_ref for block in result.blocks] == ["p://2", "p://3"]

    @pytest.mark.asyncio
    async def test_repo_filter_propagates_to_both_search_calls(self):
        """TC-MEM-09: repo_id scope is forwarded to each collection search filter."""
        store = _FakeMilvusStore(
            search_results={
                "code_memory": [[]],
                "doc_memory": [[]],
            }
        )
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=True, repo_id="workspace-123"),
        )

        await service.enrich_for_turn(
            user_message="find repo data",
            session_id="sess-1",
        )

        assert len(store.search_calls) == 2
        for call in store.search_calls:
            assert call["filter_expression"] == 'repo_id == "workspace-123"'

    @pytest.mark.asyncio
    async def test_provenance_failure_does_not_fail_successful_retrieval(self):
        """TC-MEM-10: Provenance write failures are logged but do not degrade retrieval results."""
        store = _FakeMilvusStore(
            search_results={
                "code_memory": [[
                    {
                        "payload_ref": "payload://code/repo/src/main.c#main",
                        "relative_path": "src/main.c",
                        "summary": "main entry point",
                        "distance": 0.04,
                    }
                ]],
                "doc_memory": [[]],
            }
        )
        persistence = _FakeMemoryPersistence(error=RuntimeError("db temporarily unavailable"))
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=persistence,
            config=MemoryServiceConfig(enabled=True, repo_id="repo-main"),
        )

        result = await service.enrich_for_turn(
            user_message="find startup",
            session_id="sess-1",
        )

        assert result.degraded is False
        assert [block.payload_ref for block in result.blocks] == [
            "payload://code/repo/src/main.c#main"
        ]
        assert len(persistence.provenance_calls) == 1

    @pytest.mark.asyncio
    async def test_nested_entity_hits_are_normalized_for_paths_and_payload_refs(self):
        """TC-MEM-11: Nested Milvus hit entities normalize payload refs, paths, and snippets."""
        store = _FakeMilvusStore(
            search_results={
                "code_memory": [[
                    {
                        "distance": 0.03,
                        "entity": {
                            "payload_ref": "payload://code/repo/src/lib.c#init",
                            "relative_path": "src/lib.c",
                            "summary": "initialize library subsystem",
                        },
                    }
                ]],
                "doc_memory": [[
                    {
                        "distance": 0.06,
                        "entity": {
                            "payload_ref": "payload://doc/repo/docs/guide.md#setup",
                            "source_path": "docs/guide.md",
                            "summary": "setup guide for local development",
                        },
                    }
                ]],
            }
        )
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=True, max_results=2),
        )

        result = await service.enrich_for_turn(
            user_message="how do I initialize locally",
            session_id="sess-1",
        )

        assert [(block.collection, block.payload_ref, block.source_path) for block in result.blocks] == [
            ("code_memory", "payload://code/repo/src/lib.c#init", "src/lib.c"),
            ("doc_memory", "payload://doc/repo/docs/guide.md#setup", "docs/guide.md"),
        ]
        assert result.blocks[0].snippet == "initialize library subsystem"
        assert result.blocks[1].snippet == "setup guide for local development"


# ---------------------------------------------------------------------------
# Phase 2: conversation memory tests (TC-CONV-*)
# ---------------------------------------------------------------------------


class _FakeUpsertMilvusStore(_FakeMilvusStore):
    """Extended fake that also records upsert() calls."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.upsert_calls = []

    def upsert(self, *, collection_key, generation, dimension, records):
        self.upsert_calls.append(
            {
                "collection_key": collection_key,
                "generation": generation,
                "dimension": dimension,
                "records": records,
            }
        )


class _FakePersistenceWithTurns(_FakeMemoryPersistence):
    """Extended fake that records conversation turn calls."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.turn_calls = []

    def record_conversation_turn(self, **fields):
        self.turn_calls.append(fields)
        if self.error is not None:
            raise self.error
        return fields


class TestConversationMemoryPhase2:

    @pytest.mark.asyncio
    async def test_record_turn_skipped_when_conversation_memory_disabled(self):
        """TC-CONV-01: record_turn is a no-op when enable_conversation_memory=False."""
        store = _FakeUpsertMilvusStore()
        persistence = _FakePersistenceWithTurns()
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=persistence,
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=False,
            ),
        )

        await service.record_turn(
            user_message="hello",
            assistant_response="hi there",
            session_id="sess-1",
            user_id="user-1",
        )

        assert store.upsert_calls == []
        assert persistence.turn_calls == []

    @pytest.mark.asyncio
    async def test_record_turn_stores_under_anonymous_scope_when_no_user_id(self):
        """TC-CONV-02: record_turn with empty user_id stores under '__anonymous__'
        instead of being silently discarded.

        This enables anonymous (single-user, no SSO) deployments to build up
        conversation history that is later retrieved during enrich_for_turn.
        """
        store = _FakeUpsertMilvusStore()
        persistence = _FakePersistenceWithTurns()
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=persistence,
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=True,
            ),
        )

        await service.record_turn(
            user_message="what is x?",
            assistant_response="x is 42",
            session_id="sess-anon",
            user_id="",  # anonymous
        )

        # Upsert must have happened (not skipped)
        assert len(store.upsert_calls) == 1, (
            "record_turn silently discarded the anonymous turn — "
            "it should store under '__anonymous__' instead"
        )
        record = store.upsert_calls[0]["records"][0]
        assert record["user_id"] == "__anonymous__", (
            f"Expected user_id='__anonymous__', got '{record['user_id']}'"
        )
        assert record["session_id"] == "sess-anon"
        assert "what is x" in record["user_message"]

        # Persistence must also be called with the synthetic user id
        assert len(persistence.turn_calls) == 1
        assert persistence.turn_calls[0]["user_id"] == "__anonymous__"

    @pytest.mark.asyncio
    async def test_record_turn_upserts_to_conversation_memory(self):
        """TC-CONV-03: record_turn embeds, upserts to Milvus, and records in persistence."""
        store = _FakeUpsertMilvusStore()
        persistence = _FakePersistenceWithTurns()
        embedding = _FakeEmbeddingService(vectors=[[0.1, 0.9]])
        service = MemoryService(
            embedding_service=embedding,
            milvus_store=store,
            memory_persistence=persistence,
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=True,
                conversation_retention_days=3,
            ),
        )

        await service.record_turn(
            user_message="where is the config file?",
            assistant_response="It is in /etc/app/config.yaml",
            session_id="sess-42",
            user_id="user-xyz",
            workspace_scope="ws-main",
            tool_names=["read_file"],
            turn_number=1,
        )

        # Milvus upsert happened
        assert len(store.upsert_calls) == 1
        call = store.upsert_calls[0]
        assert call["collection_key"] == "conversation_memory"
        assert call["dimension"] == 2
        record = call["records"][0]
        assert record["user_id"] == "user-xyz"
        assert record["session_id"] == "sess-42"
        assert record["workspace_scope"] == "ws-main"
        assert record["turn_number"] == 1
        assert "config file" in record["user_message"]
        assert "config.yaml" in record["assistant_summary"]

        # Persistence record happened
        assert len(persistence.turn_calls) == 1
        turn = persistence.turn_calls[0]
        assert turn["user_id"] == "user-xyz"
        assert turn["session_id"] == "sess-42"

    @pytest.mark.asyncio
    async def test_record_turn_silently_ignores_upsert_errors(self):
        """TC-CONV-04: record_turn does not raise when Milvus upsert fails."""

        class _FailingUpsertStore(_FakeUpsertMilvusStore):
            def upsert(self, **kwargs):
                raise RuntimeError("upsert failed")

        store = _FailingUpsertStore()
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=_FakePersistenceWithTurns(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=True,
            ),
        )

        # Must not raise
        await service.record_turn(
            user_message="test",
            assistant_response="ok",
            session_id="s",
            user_id="u",
        )

    @pytest.mark.asyncio
    async def test_enrich_for_turn_includes_conversation_memory_collection(self):
        """TC-CONV-05: enrich_for_turn searches conversation_memory when enabled and user_id set."""
        conv_hit = {
            "distance": 0.95,
            "entity": {
                "payload_ref": "turn-abc",
                "session_id": "sess-old",
                "turn_number": 0,
                "assistant_summary": "You asked about the config file earlier",
                "user_message": "where is config?",
                "user_id": "user-1",
                "workspace_scope": "",
            },
        }
        store = _FakeUpsertMilvusStore(
            search_results={
                "code_memory": [],
                "doc_memory": [],
                "conversation_memory": [[conv_hit]],
            }
        )
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=True,
                collection_keys=("code_memory", "doc_memory"),
            ),
        )

        result = await service.enrich_for_turn(
            user_message="tell me about the config again",
            session_id="sess-new",
            user_id="user-1",
        )

        collections_searched = [c["collection_key"] for c in store.search_calls]
        assert "conversation_memory" in collections_searched

        conv_blocks = [b for b in result.blocks if b.collection == "conversation_memory"]
        assert len(conv_blocks) == 1
        assert conv_blocks[0].payload_ref == "turn-abc"
        assert "conversation:" in conv_blocks[0].source_path

    @pytest.mark.asyncio
    async def test_enrich_for_turn_searches_conversation_memory_for_anonymous_user(self):
        """TC-CONV-06: anonymous user now searches conversation_memory under __anonymous__ scope.

        Previously this was blocked entirely (no user_id → skip).  After the fix,
        anonymous sessions use '__anonymous__' as a stable synthetic identity so
        their own past turns are retrievable.
        """
        store = _FakeUpsertMilvusStore(
            search_results={"code_memory": [[]], "doc_memory": [[]], "conversation_memory": [[]]}
        )
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=True,
            ),
        )

        await service.enrich_for_turn(
            user_message="a question",
            session_id="sess-1",
            user_id="",  # anonymous
        )

        collections_searched = [c["collection_key"] for c in store.search_calls]
        assert "conversation_memory" in collections_searched, (
            "Anonymous user must search conversation_memory via __anonymous__ scope, "
            "not be silently excluded"
        )
        # The filter expression must use __anonymous__, not __none__
        conv_calls = [c for c in store.search_calls if c["collection_key"] == "conversation_memory"]
        assert all('__anonymous__' in c["filter_expression"] for c in conv_calls)

    def test_build_conversation_filter_includes_user_id(self):
        """TC-CONV-07: filter expression for conversation memory always includes user_id."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(),
        )
        expr = service._build_conversation_filter_expression(
            user_id="user-42", workspace_scope=""
        )
        assert 'user_id == "user-42"' in expr
        assert "workspace_scope" not in expr

    def test_build_conversation_filter_includes_workspace_when_set(self):
        """TC-CONV-08: filter expression includes workspace_scope when provided."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(),
        )
        expr = service._build_conversation_filter_expression(
            user_id="user-42", workspace_scope="ws-prod"
        )
        assert 'user_id == "user-42"' in expr
        assert 'workspace_scope == "ws-prod"' in expr

    def test_build_conversation_filter_empty_user_scopes_to_anonymous(self):
        """TC-CONV-09: empty user_id produces a filter scoped to '__anonymous__', not '__none__'."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(),
        )
        expr = service._build_conversation_filter_expression(user_id="", workspace_scope="")
        assert '__anonymous__' in expr
        assert '__none__' not in expr

    @pytest.mark.asyncio
    async def test_record_count_retry_waits_for_post_upsert_stats_to_catch_up(self):
        """TC-CONV-09b: post-upsert count checks retry briefly instead of reporting stale zero rows."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(record_counts={"conversation_memory": [0, 0, 1]}),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=True, enable_conversation_memory=True),
        )

        count = await service._get_record_count_with_retry(
            collection_key="conversation_memory",
            minimum_expected=1,
            attempts=3,
            delay_s=0.0,
        )

        assert count == 1


# ---------------------------------------------------------------------------
# Phase 3: safe tool cache tests (TC-CACHE-*)
# ---------------------------------------------------------------------------


class _FakePersistenceWithCache(_FakePersistenceWithTurns):
    """Extended fake that records tool cache calls."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cache_entries: dict = {}  # key=(tool_name, params_hash, scope_hash) → row dict
        self.cache_record_calls = []
        self.cache_lookup_calls = []

    def record_tool_cache_entry(
        self,
        *,
        tool_name,
        normalized_params_hash,
        scope_hash,
        result_text,
        **fields,
    ):
        key = (tool_name, normalized_params_hash, scope_hash)
        row = {
            "cache_id": f"cache-{len(self.cache_entries)}",
            "tool_name": tool_name,
            "normalized_params_hash": normalized_params_hash,
            "scope_hash": scope_hash,
            "result_text": result_text,
            "is_cacheable": fields.get("is_cacheable", False),
            "expires_at": fields.get("expires_at"),
        }
        self.cache_entries[key] = row
        self.cache_record_calls.append(row)

        class _Row:
            pass

        r = _Row()
        for k, v in row.items():
            setattr(r, k, v)
        return r

    def get_tool_cache_entry(
        self,
        *,
        tool_name,
        normalized_params_hash,
        scope_hash,
        not_expired_as_of=None,
    ):
        from datetime import datetime, timezone
        key = (tool_name, normalized_params_hash, scope_hash)
        self.cache_lookup_calls.append(key)
        row = self.cache_entries.get(key)
        if row is None:
            return None
        if not_expired_as_of is not None and row.get("expires_at") is not None:
            if row["expires_at"] < not_expired_as_of:
                return None

        class _Row:
            pass

        r = _Row()
        for k, v in row.items():
            setattr(r, k, v)
        return r


class TestSafeToolCachePhase3:

    def _make_service(self, *, allowlist=(""), ttl_s=3600.0, enabled=True, freshness_keywords=None):
        config_kwargs = dict(
            enabled=True,
            enable_tool_cache=enabled,
            tool_cache_ttl_s=ttl_s,
            tool_cache_allowlist=tuple(t for t in allowlist if t),
        )
        if freshness_keywords is not None:
            config_kwargs["tool_cache_freshness_keywords"] = tuple(freshness_keywords)
        return MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeUpsertMilvusStore(),
            memory_persistence=_FakePersistenceWithCache(),
            config=MemoryServiceConfig(**config_kwargs),
        )

    def test_lookup_returns_no_hit_when_cache_disabled(self):
        """TC-CACHE-01: lookup_tool_cache returns no hit when enable_tool_cache=False."""
        service = self._make_service(enabled=False)
        result = service.lookup_tool_cache(
            tool_name="get_weather", arguments={"city": "London"}, user_id="u1"
        )
        assert result.hit is False
        assert result.approved is False

    def test_lookup_is_eligible_when_allowlist_empty(self):
        """TC-CACHE-02: empty allowlist means all freshness-safe tools are eligible.

        The lookup returns a MISS (not a BYPASS) because no entry has been stored yet.
        """
        service = self._make_service(allowlist=())
        result = service.lookup_tool_cache(
            tool_name="get_weather", arguments={"city": "London"}, user_id="u1"
        )
        # Not a hit (nothing stored yet), but also not bypassed — the cache was consulted
        assert result.hit is False
        assert result.approved is False

    def test_lookup_returns_no_hit_for_tool_not_in_restriction_list(self):
        """TC-CACHE-03: when a non-empty restriction list is set, unlisted tools are bypassed."""
        service = self._make_service(allowlist=("safe_tool_only",))
        result = service.lookup_tool_cache(
            tool_name="other_tool", arguments={}, user_id="u1"
        )
        assert result.hit is False
        assert result.approved is False

    def test_record_and_lookup_roundtrip(self):
        """TC-CACHE-04: record_tool_cache stores entry; lookup_tool_cache returns it."""
        service = self._make_service(allowlist=("get_weather",))
        asyncio.run(service.record_tool_cache(
            tool_name="get_weather",
            arguments={"city": "London"},
            result_text='{"temp": 15}',
            user_id="u1",
        ))
        # Inject is_cacheable so fake returns it
        pers = service.memory_persistence
        key = list(pers.cache_entries.keys())[0]
        pers.cache_entries[key]["is_cacheable"] = True
        assert len(service.milvus_store.upsert_calls) == 1
        milvus_call = service.milvus_store.upsert_calls[0]
        assert milvus_call["collection_key"] == "tool_cache"
        assert milvus_call["dimension"] == 3
        assert milvus_call["records"][0]["tool_name"] == "get_weather"

        result = service.lookup_tool_cache(
            tool_name="get_weather", arguments={"city": "London"}, user_id="u1"
        )
        assert result.hit is True
        assert result.approved is True
        assert result.result_text == '{"temp": 15}'

    def test_lookup_scope_isolation_different_users(self):
        """TC-CACHE-05: different user_id produces different scope_hash — no cross-user cache hit."""
        service = self._make_service(allowlist=("get_weather",))

        # Store for user-A
        asyncio.run(service.record_tool_cache(
            tool_name="get_weather",
            arguments={"city": "London"},
            result_text="result-for-A",
            user_id="user-A",
        ))
        pers = service.memory_persistence
        # Mark stored entry cacheable
        for key in pers.cache_entries:
            pers.cache_entries[key]["is_cacheable"] = True

        # Lookup as user-B — must miss
        result_b = service.lookup_tool_cache(
            tool_name="get_weather", arguments={"city": "London"}, user_id="user-B"
        )
        assert result_b.hit is False

    def test_lookup_scope_isolation_anonymous_vs_user(self):
        """TC-CACHE-06: anonymous scope_hash never matches a user scope_hash."""
        service = self._make_service(allowlist=("get_weather",))

        asyncio.run(service.record_tool_cache(
            tool_name="get_weather",
            arguments={"city": "London"},
            result_text="result",
            user_id="",  # anonymous
        ))
        pers = service.memory_persistence
        for key in pers.cache_entries:
            pers.cache_entries[key]["is_cacheable"] = True

        result = service.lookup_tool_cache(
            tool_name="get_weather", arguments={"city": "London"}, user_id="real-user"
        )
        assert result.hit is False

    def test_record_cache_no_op_for_tool_blocked_by_restriction_list(self):
        """TC-CACHE-07: record_tool_cache skips tools excluded by a non-empty restriction list."""
        service = self._make_service(allowlist=("safe_tool",))
        asyncio.run(service.record_tool_cache(
            tool_name="other_tool",
            arguments={},
            result_text="some output",
            user_id="u1",
        ))
        assert service.memory_persistence.cache_record_calls == []
        assert service.milvus_store.upsert_calls == []

    def test_record_cache_stores_when_allowlist_empty(self):
        """TC-CACHE-07d: with empty restriction list any freshness-safe tool is cached."""
        service = self._make_service(allowlist=())
        asyncio.run(service.record_tool_cache(
            tool_name="get_weather",
            arguments={"city": "London"},
            result_text='{"temp": 15}',
            user_id="u1",
        ))
        assert len(service.memory_persistence.cache_record_calls) == 1
        assert service.memory_persistence.cache_record_calls[0]["tool_name"] == "get_weather"

    def test_custom_freshness_keyword_excludes_tool_from_cache(self, caplog):
        """TC-CACHE-07e: a custom freshness keyword added via config blocks a matching tool."""
        service = self._make_service(
            allowlist=(),
            freshness_keywords=("snapshot", "live_"),  # custom set
        )
        caplog.set_level(logging.INFO, logger="mcp_client.internal")

        # "get_snapshot" contains "snapshot" — should be bypassed
        asyncio.run(service.record_tool_cache(
            tool_name="svc__get_snapshot",
            arguments={},
            result_text="some data",
            user_id="u1",
        ))
        assert service.memory_persistence.cache_record_calls == []
        assert "freshness-sensitive tool" in caplog.text

        # "get_config" does not match any custom keyword — should be cached
        asyncio.run(service.record_tool_cache(
            tool_name="svc__get_config",
            arguments={},
            result_text="config data",
            user_id="u1",
        ))
        assert len(service.memory_persistence.cache_record_calls) == 1
        assert service.memory_persistence.cache_record_calls[0]["tool_name"] == "svc__get_config"

    def test_empty_freshness_keywords_falls_back_to_defaults(self):
        """TC-CACHE-07f: when no custom keywords are set, built-in defaults still apply."""
        # freshness_keywords=None → MemoryServiceConfig default tuple is used
        service = self._make_service(allowlist=(), freshness_keywords=None)
        # "get_system_uptime" contains built-in keyword "uptime" — must be blocked
        result = service.lookup_tool_cache(
            tool_name="svc__get_system_uptime", arguments={}, user_id="u1"
        )
        assert result.hit is False
        # "get_config" does NOT contain any built-in keyword — must proceed to MISS (not BYPASS)
        eligible = service._is_tool_cache_eligible("svc__get_config")
        assert eligible is True

    def test_lookup_bypasses_freshness_sensitive_tools_regardless_of_restriction_list(self, caplog):
        """TC-CACHE-07b: freshness-sensitive tools are excluded even with an empty restriction list."""
        service = self._make_service(allowlist=())  # no restriction — freshness check is sole gate
        caplog.set_level(logging.INFO, logger="mcp_client.internal")

        result = service.lookup_tool_cache(
            tool_name="home_mcp_server__get_system_uptime",
            arguments={},
            user_id="u1",
        )

        assert result.hit is False
        assert result.approved is False
        assert "Tool cache BYPASS: home_mcp_server__get_system_uptime (freshness-sensitive tool)" in caplog.text

    def test_record_cache_bypasses_freshness_sensitive_tools_regardless_of_restriction_list(self, caplog):
        """TC-CACHE-07c: freshness-sensitive tools are never written to cache regardless of restriction list."""
        service = self._make_service(allowlist=())  # no restriction — freshness check is sole gate
        caplog.set_level(logging.INFO, logger="mcp_client.internal")

        asyncio.run(service.record_tool_cache(
            tool_name="home_mcp_server__get_system_uptime",
            arguments={},
            result_text="live uptime",
            user_id="u1",
        ))

        assert service.memory_persistence.cache_record_calls == []
        assert service.milvus_store.upsert_calls == []
        assert "Tool cache BYPASS STORE: home_mcp_server__get_system_uptime (freshness-sensitive tool)" in caplog.text

    def test_params_hash_is_deterministic(self):
        """TC-CACHE-08: _build_params_hash produces same hash for same args regardless of key order."""
        service = self._make_service()
        h1 = service._build_params_hash("my_tool", {"b": 2, "a": 1})
        h2 = service._build_params_hash("my_tool", {"a": 1, "b": 2})
        assert h1 == h2

    def test_params_hash_differs_for_different_args(self):
        """TC-CACHE-09: different args produce different params_hash."""
        service = self._make_service()
        h1 = service._build_params_hash("tool", {"city": "London"})
        h2 = service._build_params_hash("tool", {"city": "Paris"})
        assert h1 != h2

    def test_scope_hash_anonymous_is_distinct(self):
        """TC-CACHE-10: empty user_id hashes to a different value than any real user_id."""
        service = self._make_service()
        h_anon = service._build_cache_scope_hash("", "")
        h_user = service._build_cache_scope_hash("user-1", "")
        assert h_anon != h_user

    def test_record_cache_fails_silently_on_persistence_error(self):
        """TC-CACHE-11: record_tool_cache does not raise on persistence errors."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeUpsertMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(error=RuntimeError("db down")),
            config=MemoryServiceConfig(
                enabled=True,
                enable_tool_cache=True,
                tool_cache_allowlist=("my_tool",),
            ),
        )
        # Override record_tool_cache_entry to raise
        def _fail(**kwargs):
            raise RuntimeError("db down")
        service.memory_persistence.record_tool_cache_entry = _fail
        # Must not raise
        asyncio.run(service.record_tool_cache(tool_name="my_tool", arguments={}, result_text="r", user_id="u"))

    def test_lookup_cache_fails_silently_on_persistence_error(self):
        """TC-CACHE-12: lookup_tool_cache returns no hit on persistence errors."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_tool_cache=True,
                tool_cache_allowlist=("my_tool",),
            ),
        )
        def _fail(**kwargs):
            raise RuntimeError("db down")
        service.memory_persistence.get_tool_cache_entry = _fail
        result = service.lookup_tool_cache(tool_name="my_tool", arguments={}, user_id="u")
        assert result.hit is False

    def test_expiry_cleanup_runs_and_deletes_expired_rows_and_vectors(self):
        """TC-CACHE-13: expiry cleanup deletes expired sidecar rows and Milvus rows."""
        store = _FakeMilvusStore()
        persistence = _FakeMemoryPersistence()
        persistence.expire_conversation_turns = lambda **kwargs: 2
        persistence.expire_tool_cache_entries = lambda **kwargs: 3
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=persistence,
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=True,
                enable_tool_cache=True,
                enable_expiry_cleanup=True,
                expiry_cleanup_interval_s=300.0,
            ),
        )

        result = service.run_expiry_cleanup_if_due(force=True)

        assert result["ran"] is True
        assert result["conversation_deleted"] == 2
        assert result["tool_cache_deleted"] == 3
        assert [call["collection_key"] for call in store.delete_calls] == [
            "conversation_memory",
            "tool_cache",
        ]
        assert "expires_at <" in store.delete_calls[0]["filter_expression"]

    def test_expiry_cleanup_skips_when_interval_not_elapsed(self):
        """TC-CACHE-14: cleanup is skipped until the configured interval elapses."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_expiry_cleanup=True,
                expiry_cleanup_interval_s=9999.0,
            ),
        )

        first = service.run_expiry_cleanup_if_due(force=True)
        second = service.run_expiry_cleanup_if_due()

        assert first["ran"] is True
        assert second["ran"] is False
        assert second["skipped"] is True

    def test_expiry_cleanup_can_be_disabled(self):
        """TC-CACHE-15: cleanup no-ops when disabled by configuration."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_expiry_cleanup=False,
            ),
        )

        result = service.run_expiry_cleanup_if_due()

        assert result["ran"] is False
        assert result["skipped"] is True

    def test_conversation_filter_includes_expiry_guard(self):
        """TC-CACHE-16: conversation-memory filter excludes already-expired rows."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(),
        )

        expr = service._build_conversation_filter_expression(
            user_id="user-42",
            workspace_scope="ws-prod",
        )

        assert 'user_id == "user-42"' in expr
        assert 'workspace_scope == "ws-prod"' in expr
        assert "expires_at >" in expr


class TestResolveToolsFromMemory:
    """TC-MEM-TOOL-*: resolve_tools_from_memory selects tools from past turns."""

    def _make_conv_hit(self, tool_names_str: str, distance: float) -> dict:
        return {
            "id": "turn-1",
            "distance": distance,
            "entity": {
                "payload_ref": "conv://turn-1",
                "tool_names": tool_names_str,
                "user_message": "check status",
                "turn_number": 3,
            },
        }

    def _make_cache_hit(self, tool_name: str, server_alias: str, distance: float) -> dict:
        return {
            "id": "cache-1",
            "distance": distance,
            "entity": {
                "payload_ref": "cache://cache-1",
                "tool_name": tool_name,
                "server_alias": server_alias,
            },
        }

    @pytest.mark.asyncio
    async def test_returns_tools_from_similar_conversation_turn(self):
        """TC-MEM-TOOL-01: Tools from a similar past turn (distance < threshold) are returned."""
        hit = self._make_conv_hit("openwrt__get_memory,openwrt__get_cpu", distance=0.15)
        store = _FakeMilvusStore(
            search_results={"conversation_memory": [[hit]]}
        )
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=True,
                enable_tool_cache=False,
            ),
        )

        result = await service.resolve_tools_from_memory(
            user_message="show memory usage",
            user_id="user-1",
            available_tool_names=["openwrt__get_memory", "openwrt__get_cpu", "openwrt__get_disk"],
            request_id="chat-test",
        )

        assert result == ["openwrt__get_memory", "openwrt__get_cpu"]
        # Only conversation_memory should be searched — not code_memory or doc_memory.
        searched = [c["collection_key"] for c in store.search_calls]
        assert "code_memory" not in searched
        assert "doc_memory" not in searched
        assert "conversation_memory" in searched

    @pytest.mark.asyncio
    async def test_skips_hits_above_similarity_threshold(self):
        """TC-MEM-TOOL-02: Hits with distance > threshold are ignored."""
        hit = self._make_conv_hit("openwrt__get_memory", distance=0.50)  # too dissimilar
        store = _FakeMilvusStore(
            search_results={"conversation_memory": [[hit]]}
        )
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=True, enable_conversation_memory=True),
        )

        result = await service.resolve_tools_from_memory(
            user_message="show memory usage",
            user_id="user-1",
            available_tool_names=["openwrt__get_memory"],
            similarity_threshold=0.30,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_anonymous_user_can_resolve_tools_from_memory(self):
        """TC-MEM-TOOL-03: Anonymous sessions now resolve tools via the __anonymous__ scope.

        Previously an empty user_id caused an immediate empty return.  After the fix,
        '__anonymous__' is used as the effective user so past anonymous turns are searchable.
        """
        hit = self._make_conv_hit("openwrt__get_memory", distance=0.10)
        store = _FakeMilvusStore(
            search_results={"conversation_memory": [[hit]]}
        )
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=True, enable_conversation_memory=True),
        )

        result = await service.resolve_tools_from_memory(
            user_message="show memory usage",
            user_id="",  # anonymous
            available_tool_names=["openwrt__get_memory"],
        )

        # Must have searched conversation_memory (using __anonymous__ scope)
        assert len(store.search_calls) >= 1, "resolve_tools_from_memory must search for anonymous users"
        collections_searched = [c["collection_key"] for c in store.search_calls]
        assert "conversation_memory" in collections_searched
        # The filter must use __anonymous__ scope
        conv_calls = [c for c in store.search_calls if c["collection_key"] == "conversation_memory"]
        assert all('__anonymous__' in c["filter_expression"] for c in conv_calls)

    @pytest.mark.asyncio
    async def test_filters_out_unavailable_tool_names(self):
        """TC-MEM-TOOL-04: Tools not in available_tool_names are silently dropped."""
        hit = self._make_conv_hit("openwrt__old_tool,openwrt__get_memory", distance=0.10)
        store = _FakeMilvusStore(
            search_results={"conversation_memory": [[hit]]}
        )
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=True, enable_conversation_memory=True),
        )

        result = await service.resolve_tools_from_memory(
            user_message="show memory usage",
            user_id="user-1",
            available_tool_names=["openwrt__get_memory"],  # old_tool is not available
        )

        assert result == ["openwrt__get_memory"]

    @pytest.mark.asyncio
    async def test_tool_cache_hits_contribute_tool_names(self):
        """TC-MEM-TOOL-05: tool_cache vector hits provide tool names when tool_cache is enabled."""
        cache_hit = self._make_cache_hit("get_memory", "openwrt", distance=0.12)
        store = _FakeMilvusStore(
            search_results={"tool_cache": [[cache_hit]]}
        )
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=False,
                enable_tool_cache=True,
                tool_cache_allowlist=("get_memory",),
            ),
        )

        result = await service.resolve_tools_from_memory(
            user_message="show memory usage",
            user_id="user-1",
            available_tool_names=["openwrt__get_memory"],
        )

        # Namespaced form "openwrt__get_memory" should be resolved.
        assert result == ["openwrt__get_memory"]
        searched = [c["collection_key"] for c in store.search_calls]
        assert "tool_cache" in searched
        assert "code_memory" not in searched

    @pytest.mark.asyncio
    async def test_returns_empty_when_memory_disabled(self):
        """TC-MEM-TOOL-06: Disabled memory service always returns empty."""
        store = _FakeMilvusStore()
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=store,
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(enabled=False),
        )

        result = await service.resolve_tools_from_memory(
            user_message="show memory usage",
            user_id="user-1",
            available_tool_names=["openwrt__get_memory"],
        )

        assert result == []
        assert store.search_calls == []

    @pytest.mark.asyncio
    async def test_times_out_and_returns_empty(self):
        """TC-MEM-TOOL-07: resolve_tools_from_memory returns empty on timeout, never raises."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(delay_s=2.0),
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_conversation_memory=True,
                retrieval_timeout_s=0.05,  # 50 ms << 2s embedding delay
            ),
        )

        result = await service.resolve_tools_from_memory(
            user_message="show memory usage",
            user_id="user-1",
            available_tool_names=["openwrt__get_memory"],
        )

        assert result == []  # Timeout must not propagate as an exception.


# ---------------------------------------------------------------------------
# Unit tests for MemoryService private helpers (TC-MEM-HELPERS-*)
# ---------------------------------------------------------------------------

def _service(**config_kwargs):
    """Build a minimal MemoryService with fake dependencies for helper unit tests."""
    return MemoryService(
        embedding_service=_FakeEmbeddingService(),
        milvus_store=_FakeMilvusStore(),
        memory_persistence=_FakeMemoryPersistence(),
        config=MemoryServiceConfig(**{"enabled": True, **config_kwargs}),
    )


class TestCollectionsToSearch:

    def test_both_collections_included_by_default(self):
        """TC-MEM-COL-01: Both code_memory and doc_memory are returned when include_code_memory=True."""
        svc = _service(collection_keys=("code_memory", "doc_memory"))
        result = svc._collections_to_search("user-1", include_code_memory=True)
        assert "code_memory" in result
        assert "doc_memory" in result

    def test_code_doc_excluded_when_include_code_memory_false(self):
        """TC-MEM-COL-02: code_memory and doc_memory are excluded when include_code_memory=False."""
        svc = _service(collection_keys=("code_memory", "doc_memory"))
        result = svc._collections_to_search("user-1", include_code_memory=False)
        assert "code_memory" not in result
        assert "doc_memory" not in result

    def test_conversation_memory_added_when_enabled_and_user_known(self):
        """TC-MEM-COL-03: conversation_memory is appended when feature is on and user_id set."""
        svc = _service(
            collection_keys=("code_memory", "doc_memory"),
            enable_conversation_memory=True,
        )
        result = svc._collections_to_search("user-99", include_code_memory=True)
        assert "conversation_memory" in result

    def test_conversation_memory_included_for_anonymous_user(self):
        """TC-MEM-COL-04: conversation_memory IS added even when user_id is empty.

        Anonymous sessions use the '__anonymous__' synthetic scope so that
        single-user deployments without SSO still build up conversation history.
        """
        svc = _service(
            collection_keys=("code_memory", "doc_memory"),
            enable_conversation_memory=True,
        )
        result = svc._collections_to_search("", include_code_memory=True)
        assert "conversation_memory" in result

    def test_conversation_memory_absent_when_feature_disabled(self):
        """TC-MEM-COL-05: conversation_memory is NOT added when enable_conversation_memory=False."""
        svc = _service(
            collection_keys=("code_memory", "doc_memory"),
            enable_conversation_memory=False,
        )
        result = svc._collections_to_search("user-1", include_code_memory=True)
        assert "conversation_memory" not in result

    def test_anonymous_planning_phase_includes_conversation_memory(self):
        """TC-MEM-COL-06: Anonymous + planning phase includes conversation_memory.

        Previously this returned [] because user_id was required.  Now the
        __anonymous__ scope allows conversation retrieval even without an SSO id.
        """
        svc = _service(
            collection_keys=("code_memory", "doc_memory"),
            enable_conversation_memory=True,
        )
        result = svc._collections_to_search("", include_code_memory=False)
        assert result == ["conversation_memory"]

    def test_no_duplicate_conversation_memory_entry(self):
        """TC-MEM-COL-07: conversation_memory is not added twice even if already in collection_keys."""
        svc = _service(
            collection_keys=("code_memory", "conversation_memory"),
            enable_conversation_memory=True,
        )
        result = svc._collections_to_search("user-1", include_code_memory=True)
        assert result.count("conversation_memory") == 1


class TestBuildQuery:

    def test_collapses_whitespace(self):
        """TC-MEM-Q-01: Multiple spaces and newlines are collapsed to single spaces."""
        svc = _service()
        assert svc._build_query("  hello   world  ") == "hello world"

    def test_truncates_at_512_chars(self):
        """TC-MEM-Q-02: Queries longer than 512 chars are truncated."""
        svc = _service()
        long_text = "a " * 300   # 600 chars
        result = svc._build_query(long_text)
        assert len(result) <= 512

    def test_empty_string_returns_empty(self):
        """TC-MEM-Q-03: Empty or None input returns empty string."""
        svc = _service()
        assert svc._build_query("") == ""
        assert svc._build_query(None) == ""

    def test_short_query_unchanged(self):
        """TC-MEM-Q-04: Short query passes through without modification."""
        svc = _service()
        assert svc._build_query("find the main function") == "find the main function"


class TestQueryHash:

    def test_produces_16_char_hex_string(self):
        """TC-MEM-QH-01: Hash output is a 16-character hex string."""
        svc = _service()
        h = svc._query_hash("find main")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_input_same_hash(self):
        """TC-MEM-QH-02: Deterministic — same text produces same hash."""
        svc = _service()
        assert svc._query_hash("hello") == svc._query_hash("hello")

    def test_different_inputs_different_hash(self):
        """TC-MEM-QH-03: Different text produces different hash."""
        svc = _service()
        assert svc._query_hash("hello") != svc._query_hash("world")

    def test_empty_string_has_stable_hash(self):
        """TC-MEM-QH-04: Empty string produces a stable, non-empty hash."""
        svc = _service()
        h = svc._query_hash("")
        assert len(h) == 16


class TestBuildConversationFilterExpression:
    """Tests for _build_conversation_filter_expression with the __anonymous__ fix."""

    def test_known_user_scopes_to_that_user(self):
        """TC-MEM-CF-01: Known user_id produces a filter for that exact user."""
        svc = _service()
        expr = svc._build_conversation_filter_expression(user_id="user-abc", workspace_scope="")
        assert 'user_id == "user-abc"' in expr

    def test_empty_user_id_scopes_to_anonymous(self):
        """TC-MEM-CF-02: Empty user_id maps to '__anonymous__' instead of '__none__'.

        This is the core anonymous-mode fix: retrieval now queries the same
        synthetic scope that record_turn writes to for anonymous sessions.
        """
        svc = _service()
        expr = svc._build_conversation_filter_expression(user_id="", workspace_scope="")
        assert 'user_id == "__anonymous__"' in expr
        assert '__none__' not in expr

    def test_workspace_scope_added_when_present(self):
        """TC-MEM-CF-03: workspace_scope is appended when non-empty."""
        svc = _service()
        expr = svc._build_conversation_filter_expression(user_id="u", workspace_scope="ws-1")
        assert 'workspace_scope == "ws-1"' in expr

    def test_workspace_scope_omitted_when_empty(self):
        """TC-MEM-CF-04: workspace_scope clause is absent when workspace_scope is empty."""
        svc = _service()
        expr = svc._build_conversation_filter_expression(user_id="u", workspace_scope="")
        assert "workspace_scope" not in expr

    def test_expiry_guard_always_present(self):
        """TC-MEM-CF-05: expires_at > <now> guard is always included."""
        svc = _service()
        expr = svc._build_conversation_filter_expression(user_id="u", workspace_scope="")
        assert "expires_at >" in expr

    def test_quotes_in_user_id_are_escaped(self):
        """TC-MEM-CF-06: Double quotes in user_id are escaped to prevent injection."""
        svc = _service()
        expr = svc._build_conversation_filter_expression(user_id='user"bad', workspace_scope="")
        assert '\\"' in expr


class TestBuildFilterExpression:

    def test_empty_repo_id_returns_empty_string(self):
        """TC-MEM-FE-01: Empty repo_id produces no filter."""
        svc = _service()
        assert svc._build_filter_expression("") == ""

    def test_non_empty_repo_id_produces_equality_filter(self):
        """TC-MEM-FE-02: A repo_id is wrapped in a Milvus equality expression."""
        svc = _service()
        expr = svc._build_filter_expression("my-repo")
        assert 'repo_id == "my-repo"' == expr

    def test_quotes_in_repo_id_are_escaped(self):
        """TC-MEM-FE-03: Double quotes in repo_id are backslash-escaped so the
        resulting Milvus filter expression is syntactically valid."""
        svc = _service()
        expr = svc._build_filter_expression('repo"name')
        # The quote should be escaped as \" in the expression
        assert '\\"' in expr


class TestFlattenHits:

    def test_flat_list_of_dicts_passes_through(self):
        """TC-MEM-FH-01: A plain list of hit dicts is returned as-is."""
        svc = _service()
        hits = [{"distance": 0.1}, {"distance": 0.2}]
        assert svc._flatten_hits(hits) == hits

    def test_nested_list_of_lists_is_flattened(self):
        """TC-MEM-FH-02: A Milvus-style [[hit, hit], [hit]] structure is flattened."""
        svc = _service()
        hits = [[{"distance": 0.1}, {"distance": 0.2}], [{"distance": 0.3}]]
        result = svc._flatten_hits(hits)
        assert len(result) == 3

    def test_non_list_input_returns_empty(self):
        """TC-MEM-FH-03: Non-list input (e.g. None or a dict) returns empty list."""
        svc = _service()
        assert svc._flatten_hits(None) == []
        assert svc._flatten_hits({}) == []

    def test_nested_non_dicts_are_skipped(self):
        """TC-MEM-FH-04: Non-dict items inside a nested list are skipped."""
        svc = _service()
        result = svc._flatten_hits([["not-a-dict", None, {"distance": 0.5}]])
        assert result == [{"distance": 0.5}]


class TestScoreForHit:

    def test_reads_distance_field(self):
        """TC-MEM-SC-SH-01: 'distance' field is used as the score."""
        svc = _service()
        assert svc._score_for_hit({"distance": 0.42}) == pytest.approx(0.42)

    def test_reads_score_field_as_fallback(self):
        """TC-MEM-SC-SH-02: 'score' field is used when 'distance' is absent."""
        svc = _service()
        assert svc._score_for_hit({"score": 0.75}) == pytest.approx(0.75)

    def test_missing_fields_return_zero(self):
        """TC-MEM-SC-SH-03: Missing both fields returns 0.0."""
        svc = _service()
        assert svc._score_for_hit({}) == 0.0

    def test_non_dict_returns_zero(self):
        """TC-MEM-SC-SH-04: Non-dict input returns 0.0 without raising."""
        svc = _service()
        assert svc._score_for_hit(None) == 0.0
        assert svc._score_for_hit("string") == 0.0

    def test_string_score_is_cast_to_float(self):
        """TC-MEM-SC-SH-05: Numeric strings are coerced to float."""
        svc = _service()
        assert svc._score_for_hit({"distance": "0.33"}) == pytest.approx(0.33)

    def test_invalid_score_returns_zero(self):
        """TC-MEM-SC-SH-06: Non-numeric score value falls back to 0.0."""
        svc = _service()
        assert svc._score_for_hit({"distance": "nan_value"}) == 0.0


class TestNormalizeBlock:

    def test_code_memory_hit_with_entity_wrapper(self):
        """TC-MEM-NB-01: Nested entity dict is unwrapped for code_memory."""
        svc = _service()
        hit = {
            "distance": 0.05,
            "entity": {
                "payload_ref": "payload://code/repo/src/main.c#init",
                "relative_path": "src/main.c",
                "summary": "init function",
            },
        }
        block = svc._normalize_block(collection_key="code_memory", hit=hit)
        assert block.payload_ref == "payload://code/repo/src/main.c#init"
        assert block.source_path == "src/main.c"
        assert block.snippet == "init function"
        assert block.score == pytest.approx(0.05)
        assert block.collection == "code_memory"

    def test_doc_memory_hit_uses_source_path(self):
        """TC-MEM-NB-02: doc_memory uses source_path for the path field."""
        svc = _service()
        hit = {
            "distance": 0.10,
            "entity": {
                "payload_ref": "payload://doc/repo/README.md#usage",
                "source_path": "README.md",
                "summary": "usage instructions",
            },
        }
        block = svc._normalize_block(collection_key="doc_memory", hit=hit)
        assert block.source_path == "README.md"
        assert block.snippet == "usage instructions"

    def test_flat_hit_without_entity_wrapper(self):
        """TC-MEM-NB-03: Flat hit dict (no 'entity' key) is also normalised."""
        svc = _service()
        hit = {
            "payload_ref": "ref-flat",
            "relative_path": "src/util.c",
            "summary": "utility functions",
            "distance": 0.20,
        }
        block = svc._normalize_block(collection_key="code_memory", hit=hit)
        assert block.payload_ref == "ref-flat"
        assert block.source_path == "src/util.c"

    def test_conversation_memory_synthesises_source_path(self):
        """TC-MEM-NB-04: conversation_memory builds a synthetic source_path from session/turn."""
        svc = _service()
        hit = {
            "distance": 0.90,
            "entity": {
                "payload_ref": "turn-abc",
                "session_id": "sess-42",
                "turn_number": 3,
                "assistant_summary": "you asked about the config",
                "user_message": "where is config?",
                "user_id": "user-1",
            },
        }
        block = svc._normalize_block(collection_key="conversation_memory", hit=hit)
        assert "conversation:" in block.source_path
        assert "sess-42" in block.source_path
        assert block.snippet == "you asked about the config"

    def test_snippet_truncated_to_500_chars(self):
        """TC-MEM-NB-05: Summary longer than 500 chars is truncated in the snippet."""
        svc = _service()
        long_summary = "x" * 600
        hit = {"payload_ref": "ref", "summary": long_summary, "distance": 0.1}
        block = svc._normalize_block(collection_key="code_memory", hit=hit)
        assert len(block.snippet) == 500
