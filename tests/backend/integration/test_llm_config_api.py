"""
Integration tests — LLM Configuration endpoints (TR-LLM-*)
"""

from pathlib import Path

import pytest

import backend.main as main_module


class TestGetLLMConfig:

    def test_not_found_when_unset(self, client):
        """TC-LLM-01: GET /api/llm/config returns 404 when not configured."""
        r = client.get("/api/llm/config")
        assert r.status_code == 404

    def test_returns_saved_config(self, client, llm_openai):
        """TC-LLM-02: Config retrieved after saving."""
        client.post("/api/llm/config", json=llm_openai)
        r = client.get("/api/llm/config")
        assert r.status_code == 200
        assert r.json()["model"] == llm_openai["model"]

    def test_response_schema(self, client, llm_mock):
        """TC-LLM-03: Response matches LLMConfig schema."""
        from backend.models import LLMConfig
        client.post("/api/llm/config", json=llm_mock)
        r = client.get("/api/llm/config")
        LLMConfig(**r.json())  # raises if schema mismatch


class TestSaveLLMConfig:

    def test_save_openai_config(self, client, llm_openai):
        """TC-LLM-04: OpenAI config saved, returns 200."""
        r = client.post("/api/llm/config", json=llm_openai)
        assert r.status_code == 200

    def test_save_ollama_config(self, client, llm_ollama):
        """TC-LLM-05: Ollama config saved, returns 200."""
        r = client.post("/api/llm/config", json=llm_ollama)
        assert r.status_code == 200

    def test_save_mock_config(self, client, llm_mock):
        """TC-LLM-06: Mock config saved, returns 200."""
        r = client.post("/api/llm/config", json=llm_mock)
        assert r.status_code == 200

    def test_save_enterprise_config(self, client, llm_enterprise):
        """TC-LLM-06b: Enterprise config saved, returns 200."""
        r = client.post("/api/llm/config", json=llm_enterprise)
        assert r.status_code == 200
        assert r.json()["provider"] == "enterprise"
        assert r.json()["gateway_mode"] == "enterprise"

    def test_invalid_provider_returns_422(self, client):
        """TC-LLM-07: Unknown provider returns 422."""
        r = client.post("/api/llm/config", json={
            "provider": "unknown", "model": "m", "base_url": "https://x.com"
        })
        assert r.status_code == 422

    def test_missing_provider_returns_422(self, client):
        """TC-LLM-08: Missing provider returns 422."""
        r = client.post("/api/llm/config", json={"model": "m", "base_url": "https://x.com"})
        assert r.status_code == 422

    def test_missing_model_returns_422(self, client):
        """TC-LLM-09: Missing model returns 422."""
        r = client.post("/api/llm/config", json={"provider": "mock", "base_url": "https://x.com"})
        assert r.status_code == 422

    def test_temperature_out_of_range_returns_422(self, client, llm_mock):
        """TC-LLM-10: Temperature 2.1 returns 422."""
        bad = {**llm_mock, "temperature": 2.1}
        r = client.post("/api/llm/config", json=bad)
        assert r.status_code == 422

    def test_temperature_valid_boundaries(self, client, llm_mock):
        """TC-LLM-11: temperature 0.0 and 2.0 both accepted."""
        for temp in (0.0, 2.0):
            r = client.post("/api/llm/config", json={**llm_mock, "temperature": temp})
            assert r.status_code == 200

    def test_llm_timeout_round_trips_in_config_api(self, client, llm_mock):
        """TC-LLM-11b: llm_timeout_ms saves and loads through the config API."""
        payload = {**llm_mock, "llm_timeout_ms": 240000}
        save = client.post("/api/llm/config", json=payload)
        assert save.status_code == 200
        assert save.json()["llm_timeout_ms"] == 240000

        fetch = client.get("/api/llm/config")
        assert fetch.status_code == 200
        assert fetch.json()["llm_timeout_ms"] == 240000

    def test_llm_timeout_out_of_range_returns_422(self, client, llm_mock):
        """TC-LLM-11c: llm_timeout_ms outside bounds returns 422."""
        r = client.post("/api/llm/config", json={**llm_mock, "llm_timeout_ms": 4000})
        assert r.status_code == 422

    def test_tiny_mode_classifier_overrides_round_trip_in_config_api(self, client, llm_mock):
        """Tiny classifier overrides save and load through the config API."""
        payload = {
            **llm_mock,
            "tiny_llm_mode_classifier_enabled": True,
            "tiny_llm_mode_classifier_min_confidence": 0.72,
            "tiny_llm_mode_classifier_min_score_gap": 5,
            "tiny_llm_mode_classifier_accept_confidence": 0.66,
            "tiny_llm_mode_classifier_max_tokens": 128,
        }
        save = client.post("/api/llm/config", json=payload)
        assert save.status_code == 200
        assert save.json()["tiny_llm_mode_classifier_enabled"] is True
        assert save.json()["tiny_llm_mode_classifier_min_confidence"] == pytest.approx(0.72)
        assert save.json()["tiny_llm_mode_classifier_min_score_gap"] == 5
        assert save.json()["tiny_llm_mode_classifier_accept_confidence"] == pytest.approx(0.66)
        assert save.json()["tiny_llm_mode_classifier_max_tokens"] == 128

        fetch = client.get("/api/llm/config")
        assert fetch.status_code == 200
        assert fetch.json()["tiny_llm_mode_classifier_enabled"] is True
        assert fetch.json()["tiny_llm_mode_classifier_max_tokens"] == 128

    def test_config_overwritten_on_second_save(self, client, llm_openai, llm_ollama):
        """TC-LLM-12: Second POST replaces first config."""
        client.post("/api/llm/config", json=llm_openai)
        client.post("/api/llm/config", json=llm_ollama)
        r = client.get("/api/llm/config")
        assert r.json()["provider"] == "ollama"

    def test_max_tokens_optional(self, client, llm_mock):
        """TC-LLM-13: max_tokens absent → defaults to None."""
        r = client.post("/api/llm/config", json=llm_mock)
        assert r.json().get("max_tokens") is None

    def test_api_key_optional(self, client, llm_ollama):
        """TC-LLM-14: api_key omitted → accepted."""
        r = client.post("/api/llm/config", json=llm_ollama)
        assert r.status_code == 200

    def test_enterprise_missing_token_endpoint_returns_422(self, client, llm_enterprise):
        """TC-LLM-15: Enterprise config without token endpoint rejected."""
        bad = {**llm_enterprise}
        bad.pop("token_endpoint_url")
        r = client.post("/api/llm/config", json=bad)
        assert r.status_code == 422

    def test_config_persisted_to_server_disk(self, client, llm_enterprise):
        """TC-LLM-16: Saving config writes llm_config.json under MCP_DATA_DIR."""
        r = client.post("/api/llm/config", json=llm_enterprise)
        assert r.status_code == 200

        config_file = main_module.MCP_DATA_DIR / "llm_config.json"
        assert config_file.exists()
        text = config_file.read_text()
        assert "enterprise-client" in text
        assert "enterprise-secret" in text

    def test_load_llm_config_from_disk_helper(self, client, llm_enterprise):
        """TC-LLM-17: _load_llm_config_from_disk reconstructs saved enterprise config."""
        client.post("/api/llm/config", json=llm_enterprise)

        main_module.llm_config_storage = None
        loaded = main_module._load_llm_config_from_disk()

        assert loaded is not None
        assert loaded.provider == "enterprise"
        assert loaded.client_id == "enterprise-client"
