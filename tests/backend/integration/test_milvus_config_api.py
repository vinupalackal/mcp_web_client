"""
Integration tests — Milvus Configuration endpoints (TR-MILVUS-CONFIG-*)
"""

import json

import pytest

import backend.main as main_module
from backend.models import LLMConfig, MilvusConfig


class TestGetMilvusConfig:

    def test_returns_default_config_when_unset(self, client):
        """TC-MILVUS-CONFIG-01: GET returns effective defaults when no config is saved."""
        response = client.get("/api/milvus/config")

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        assert data["milvus_uri"] == ""
        assert data["collection_prefix"] == "mcp_client"

    def test_returns_saved_config(self, client, milvus_config_payload):
        """TC-MILVUS-CONFIG-02: Saved Milvus config can be retrieved."""
        client.post("/api/milvus/config", json=milvus_config_payload)

        response = client.get("/api/milvus/config")

        assert response.status_code == 200
        assert response.json()["milvus_uri"] == milvus_config_payload["milvus_uri"]

    def test_response_schema(self, client, milvus_config_payload):
        """TC-MILVUS-CONFIG-03: Response matches MilvusConfig schema."""
        client.post("/api/milvus/config", json=milvus_config_payload)
        response = client.get("/api/milvus/config")

        MilvusConfig(**response.json())

    def test_all_default_fields_present_in_response(self, client):
        """TC-MILVUS-CONFIG-03b: GET response contains every documented field."""
        response = client.get("/api/milvus/config")
        data = response.json()

        expected_fields = {
            "enabled", "milvus_uri", "collection_prefix", "repo_id",
            "collection_generation", "max_results", "retrieval_timeout_s",
            "degraded_mode", "enable_conversation_memory", "conversation_retention_days",
            "enable_tool_cache", "tool_cache_ttl_s", "tool_cache_allowlist",
            "enable_expiry_cleanup", "expiry_cleanup_interval_s",
        }
        assert expected_fields.issubset(data.keys())


class TestSaveMilvusConfig:

    def test_save_config_returns_200(self, client, milvus_config_payload):
        """TC-MILVUS-CONFIG-04: Valid Milvus config saves successfully."""
        response = client.post("/api/milvus/config", json=milvus_config_payload)

        assert response.status_code == 200
        assert response.json()["enabled"] is True

    def test_enabled_without_uri_returns_422(self, client, milvus_config_payload):
        """TC-MILVUS-CONFIG-05: Enabled config without Milvus URI is rejected."""
        bad_payload = {**milvus_config_payload, "milvus_uri": ""}

        response = client.post("/api/milvus/config", json=bad_payload)

        assert response.status_code == 422

    def test_config_persisted_to_server_disk(self, client, milvus_config_payload):
        """TC-MILVUS-CONFIG-06: Saving config writes milvus_config.json under MCP_DATA_DIR."""
        response = client.post("/api/milvus/config", json=milvus_config_payload)
        assert response.status_code == 200

        config_file = main_module.MCP_DATA_DIR / "milvus_config.json"
        assert config_file.exists()
        text = config_file.read_text()
        assert '"milvus_uri": "http://127.0.0.1:19530"' in text
        assert '"collection_generation": "v1"' in text

    def test_load_milvus_config_from_disk_helper(self, client, milvus_config_payload):
        """TC-MILVUS-CONFIG-07: _load_milvus_config_from_disk reconstructs saved config."""
        client.post("/api/milvus/config", json=milvus_config_payload)

        main_module.milvus_config_storage = None
        loaded = main_module._load_milvus_config_from_disk()

        assert loaded is not None
        assert loaded.milvus_uri == milvus_config_payload["milvus_uri"]
        assert loaded.enable_tool_cache is True

    def test_save_reinitializes_memory_service(self, client, milvus_config_payload, monkeypatch):
        """TC-MILVUS-CONFIG-08: Saving config re-runs memory-service initialization."""
        main_module.llm_config_storage = LLMConfig(
            provider="mock",
            model="mock-model",
            base_url="http://localhost",
        )
        calls = {}

        def fake_initialize_memory_service(config=None):
            calls["config"] = config
            main_module._memory_service = {"status": "initialized"}
            return main_module._memory_service

        monkeypatch.setattr(main_module, "_initialize_memory_service", fake_initialize_memory_service)

        response = client.post("/api/milvus/config", json=milvus_config_payload)

        assert response.status_code == 200
        assert calls["config"] is not None
        assert calls["config"].milvus_uri == milvus_config_payload["milvus_uri"]

    def test_save_disabled_config_with_empty_uri_accepted(self, client):
        """TC-MILVUS-CONFIG-09: enabled=False with an empty URI is valid and returns 200."""
        response = client.post("/api/milvus/config", json={"enabled": False, "milvus_uri": ""})

        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert response.json()["milvus_uri"] == ""

    def test_save_updates_global_milvus_config_storage(self, client, milvus_config_payload):
        """TC-MILVUS-CONFIG-10: Successful POST updates the in-process milvus_config_storage global."""
        client.post("/api/milvus/config", json=milvus_config_payload)

        stored = main_module.milvus_config_storage
        assert stored is not None
        assert stored.milvus_uri == milvus_config_payload["milvus_uri"]
        assert stored.max_results == milvus_config_payload["max_results"]

    def test_save_config_allowlist_roundtrip(self, client, milvus_config_payload):
        """TC-MILVUS-CONFIG-11: Tool-cache allowlist is stored and retrieved intact."""
        client.post("/api/milvus/config", json=milvus_config_payload)
        response = client.get("/api/milvus/config")

        returned = response.json()["tool_cache_allowlist"]
        assert set(returned) == set(milvus_config_payload["tool_cache_allowlist"])

    def test_invalid_max_results_returns_422(self, client, milvus_config_payload):
        """TC-MILVUS-CONFIG-12: max_results=0 fails Pydantic validation and returns 422."""
        bad_payload = {**milvus_config_payload, "max_results": 0}
        response = client.post("/api/milvus/config", json=bad_payload)

        assert response.status_code == 422

    def test_invalid_retrieval_timeout_returns_422(self, client, milvus_config_payload):
        """TC-MILVUS-CONFIG-13: retrieval_timeout_s=0.0 fails validation and returns 422."""
        bad_payload = {**milvus_config_payload, "retrieval_timeout_s": 0.0}
        response = client.post("/api/milvus/config", json=bad_payload)

        assert response.status_code == 422

    def test_response_echoes_saved_values(self, client, milvus_config_payload):
        """TC-MILVUS-CONFIG-14: POST response body reflects the stored values, not stale defaults."""
        response = client.post("/api/milvus/config", json=milvus_config_payload)

        data = response.json()
        assert data["repo_id"] == milvus_config_payload["repo_id"]
        assert data["collection_generation"] == milvus_config_payload["collection_generation"]
        assert data["conversation_retention_days"] == milvus_config_payload["conversation_retention_days"]


class TestLoadMilvusConfigFromDisk:

    def test_returns_none_when_file_is_missing(self, tmp_path, monkeypatch):
        """TC-MILVUS-CONFIG-15: _load_milvus_config_from_disk returns None when no file exists."""
        monkeypatch.setattr(main_module, "MCP_DATA_DIR", tmp_path)

        result = main_module._load_milvus_config_from_disk()

        assert result is None

    def test_returns_none_on_corrupted_json(self, tmp_path, monkeypatch):
        """TC-MILVUS-CONFIG-16: Corrupted milvus_config.json is handled gracefully."""
        monkeypatch.setattr(main_module, "MCP_DATA_DIR", tmp_path)
        (tmp_path / "milvus_config.json").write_text("{ not valid json }")

        result = main_module._load_milvus_config_from_disk()

        assert result is None

    def test_reconstructs_saved_config(self, tmp_path, monkeypatch):
        """TC-MILVUS-CONFIG-17: Valid JSON file is deserialized into a MilvusConfig."""
        monkeypatch.setattr(main_module, "MCP_DATA_DIR", tmp_path)
        config = MilvusConfig(enabled=True, milvus_uri="http://milvus.internal:19530", max_results=10)
        (tmp_path / "milvus_config.json").write_text(config.model_dump_json())

        loaded = main_module._load_milvus_config_from_disk()

        assert loaded is not None
        assert loaded.milvus_uri == "http://milvus.internal:19530"
        assert loaded.max_results == 10


class TestDefaultMilvusConfigFromEnv:

    def test_reads_memory_enabled_env_var(self, monkeypatch):
        """TC-MILVUS-CONFIG-18: MEMORY_ENABLED=true sets enabled=True in defaults."""
        monkeypatch.setenv("MEMORY_ENABLED", "true")
        monkeypatch.setenv("MEMORY_MILVUS_URI", "http://env-milvus:19530")

        config = main_module._default_milvus_config_from_env()

        assert config.enabled is True
        assert config.milvus_uri == "http://env-milvus:19530"

    def test_reads_numeric_env_vars(self, monkeypatch):
        """TC-MILVUS-CONFIG-19: MEMORY_MAX_RESULTS and MEMORY_RETRIEVAL_TIMEOUT_S are parsed."""
        monkeypatch.setenv("MEMORY_MAX_RESULTS", "12")
        monkeypatch.setenv("MEMORY_RETRIEVAL_TIMEOUT_S", "8.5")

        config = main_module._default_milvus_config_from_env()

        assert config.max_results == 12
        assert config.retrieval_timeout_s == 8.5

    def test_reads_allowlist_env_var(self, monkeypatch):
        """TC-MILVUS-CONFIG-20: MEMORY_TOOL_CACHE_ALLOWLIST is split on commas and stripped."""
        monkeypatch.setenv("MEMORY_TOOL_CACHE_ALLOWLIST", " tool_a , tool_b , ")

        config = main_module._default_milvus_config_from_env()

        assert config.tool_cache_allowlist == ["tool_a", "tool_b"]

    def test_falls_back_to_disabled_defaults_on_invalid_env(self, monkeypatch):
        """TC-MILVUS-CONFIG-21: Unparseable env values cause a safe fallback to disabled defaults."""
        monkeypatch.setenv("MEMORY_ENABLED", "true")
        monkeypatch.setenv("MEMORY_MILVUS_URI", "")  # URI empty → validator will fail → fallback

        config = main_module._default_milvus_config_from_env()

        # The validator raises because enabled=True + milvus_uri="" → fallback returns MilvusConfig()
        assert config.enabled is False


class TestGetEffectiveMilvusConfig:

    def test_returns_stored_config_when_set(self, monkeypatch):
        """TC-MILVUS-CONFIG-22: Returns milvus_config_storage when it holds a value."""
        stored = MilvusConfig(enabled=True, milvus_uri="http://stored:19530")
        monkeypatch.setattr(main_module, "milvus_config_storage", stored)

        result = main_module._get_effective_milvus_config()

        assert result is stored
        assert result.milvus_uri == "http://stored:19530"

    def test_falls_back_to_env_defaults_when_none(self, monkeypatch):
        """TC-MILVUS-CONFIG-23: Returns env-derived defaults when storage is None."""
        monkeypatch.setattr(main_module, "milvus_config_storage", None)
        monkeypatch.setenv("MEMORY_ENABLED", "false")

        result = main_module._get_effective_milvus_config()

        assert isinstance(result, MilvusConfig)
        assert result.enabled is False
