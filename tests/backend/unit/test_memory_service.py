"""Unit tests for retrieval orchestration service (TC-MEM-*)."""

import asyncio

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
    def __init__(self, *, search_results=None, search_error=None, collections=None, list_error=None):
        self.search_results = search_results or {}
        self.search_error = search_error
        self.collections = collections or ["mcp_client_code_memory_v1", "mcp_client_doc_memory_v1"]
        self.list_error = list_error
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

    def upsert(self, *, collection_key, generation, records):
        self.upsert_calls.append(
            {"collection_key": collection_key, "generation": generation, "records": records}
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
    async def test_record_turn_skipped_without_user_id(self):
        """TC-CONV-02: record_turn is a no-op when user_id is empty (anonymous)."""
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

        assert store.upsert_calls == []
        assert persistence.turn_calls == []

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
    async def test_enrich_for_turn_skips_conversation_memory_without_user_id(self):
        """TC-CONV-06: cross-user blocking — no conversation_memory search when user_id empty."""
        store = _FakeUpsertMilvusStore(
            search_results={"code_memory": [], "doc_memory": [], "conversation_memory": []}
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
            user_id="",  # anonymous — must NOT search conversation memory
        )

        collections_searched = [c["collection_key"] for c in store.search_calls]
        assert "conversation_memory" not in collections_searched

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

    def test_build_conversation_filter_no_user_blocks_all(self):
        """TC-CONV-09: empty user_id produces a blocking filter."""
        service = MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakeMemoryPersistence(),
        )
        expr = service._build_conversation_filter_expression(user_id="", workspace_scope="")
        assert "__none__" in expr


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

    def _make_service(self, *, allowlist=("get_weather",), ttl_s=3600.0, enabled=True):
        return MemoryService(
            embedding_service=_FakeEmbeddingService(),
            milvus_store=_FakeMilvusStore(),
            memory_persistence=_FakePersistenceWithCache(),
            config=MemoryServiceConfig(
                enabled=True,
                enable_tool_cache=enabled,
                tool_cache_ttl_s=ttl_s,
                tool_cache_allowlist=tuple(allowlist),
            ),
        )

    def test_lookup_returns_no_hit_when_cache_disabled(self):
        """TC-CACHE-01: lookup_tool_cache returns no hit when enable_tool_cache=False."""
        service = self._make_service(enabled=False)
        result = service.lookup_tool_cache(
            tool_name="get_weather", arguments={"city": "London"}, user_id="u1"
        )
        assert result.hit is False
        assert result.approved is False

    def test_lookup_returns_no_hit_when_allowlist_empty(self):
        """TC-CACHE-02: lookup_tool_cache returns no hit when allowlist is empty."""
        service = self._make_service(allowlist=())
        result = service.lookup_tool_cache(
            tool_name="get_weather", arguments={"city": "London"}, user_id="u1"
        )
        assert result.hit is False
        assert result.approved is False

    def test_lookup_returns_no_hit_for_tool_not_in_allowlist(self):
        """TC-CACHE-03: similarity alone cannot authorize a cache hit — non-allowlisted tool returns miss."""
        service = self._make_service(allowlist=("safe_tool_only",))
        result = service.lookup_tool_cache(
            tool_name="dangerous_tool", arguments={}, user_id="u1"
        )
        assert result.hit is False
        assert result.approved is False

    def test_record_and_lookup_roundtrip(self):
        """TC-CACHE-04: record_tool_cache stores entry; lookup_tool_cache returns it."""
        service = self._make_service(allowlist=("get_weather",))
        service.record_tool_cache(
            tool_name="get_weather",
            arguments={"city": "London"},
            result_text='{"temp": 15}',
            user_id="u1",
        )
        # Inject is_cacheable so fake returns it
        pers = service.memory_persistence
        key = list(pers.cache_entries.keys())[0]
        pers.cache_entries[key]["is_cacheable"] = True

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
        service.record_tool_cache(
            tool_name="get_weather",
            arguments={"city": "London"},
            result_text="result-for-A",
            user_id="user-A",
        )
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

        service.record_tool_cache(
            tool_name="get_weather",
            arguments={"city": "London"},
            result_text="result",
            user_id="",  # anonymous
        )
        pers = service.memory_persistence
        for key in pers.cache_entries:
            pers.cache_entries[key]["is_cacheable"] = True

        result = service.lookup_tool_cache(
            tool_name="get_weather", arguments={"city": "London"}, user_id="real-user"
        )
        assert result.hit is False

    def test_record_cache_no_op_for_non_allowlisted_tool(self):
        """TC-CACHE-07: record_tool_cache does nothing for tools not on the allowlist."""
        service = self._make_service(allowlist=("safe_tool",))
        service.record_tool_cache(
            tool_name="dangerous_tool",
            arguments={},
            result_text="secret output",
            user_id="u1",
        )
        assert service.memory_persistence.cache_record_calls == []

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
            milvus_store=_FakeMilvusStore(),
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
        service.record_tool_cache(tool_name="my_tool", arguments={}, result_text="r", user_id="u")

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
