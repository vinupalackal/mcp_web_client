"""
Unit tests for Pydantic models (TR-MODEL-*)
"""

import pytest
from pydantic import ValidationError
from backend.models import (
    ServerConfig,
    LLMConfig,
    ChatMessage,
    ToolSchema,
    FunctionCall,
    ToolCall,
)


# ============================================================================
# TR-MODEL-1: ServerConfig
# ============================================================================

class TestServerConfig:

    def test_valid_minimal_creates_uuid(self):
        """TC-MODEL-01: Valid minimal config auto-generates server_id."""
        s = ServerConfig(alias="svc", base_url="https://host.com")
        assert s.server_id  # UUID generated
        assert len(s.server_id) == 36

    def test_alias_max_length_64_accepted(self):
        """TC-MODEL-02a: Alias exactly 64 chars is valid."""
        ServerConfig(alias="a" * 64, base_url="https://host.com")

    def test_alias_length_65_rejected(self):
        """TC-MODEL-02b: Alias 65 chars raises ValidationError."""
        with pytest.raises(ValidationError):
            ServerConfig(alias="a" * 65, base_url="https://host.com")

    def test_alias_min_length_1(self):
        """TC-MODEL-03: Empty alias raises ValidationError."""
        with pytest.raises(ValidationError):
            ServerConfig(alias="", base_url="https://host.com")

    def test_base_url_invalid_pattern_rejected(self):
        """TC-MODEL-04a: Non-URL string rejected."""
        with pytest.raises(ValidationError):
            ServerConfig(alias="svc", base_url="not-a-url")

    def test_base_url_http_accepted(self):
        """TC-MODEL-04b: http:// URL accepted by model (HTTPS enforced at API layer)."""
        s = ServerConfig(alias="svc", base_url="http://host.com")
        assert s.base_url == "http://host.com"

    def test_base_url_https_accepted(self):
        """TC-MODEL-04c: https:// URL accepted."""
        s = ServerConfig(alias="svc", base_url="https://host.com")
        assert s.base_url == "https://host.com"

    def test_auth_type_valid_values(self):
        """TC-MODEL-05a: Valid auth_type values accepted."""
        for val in ("none", "bearer", "api_key"):
            s = ServerConfig(alias="svc", base_url="https://host.com", auth_type=val)
            assert s.auth_type == val

    def test_auth_type_invalid_rejected(self):
        """TC-MODEL-05b: Unknown auth_type raises ValidationError."""
        with pytest.raises(ValidationError):
            ServerConfig(alias="svc", base_url="https://host.com", auth_type="jwt")

    def test_timeout_ms_default(self):
        """TC-MODEL-06a: Default timeout_ms is 20000."""
        s = ServerConfig(alias="svc", base_url="https://host.com")
        assert s.timeout_ms == 20000

    def test_timeout_ms_boundary_min(self):
        """TC-MODEL-06b: timeout_ms=1000 accepted; 999 rejected."""
        ServerConfig(alias="svc", base_url="https://host.com", timeout_ms=1000)
        with pytest.raises(ValidationError):
            ServerConfig(alias="svc", base_url="https://host.com", timeout_ms=999)

    def test_timeout_ms_boundary_max(self):
        """TC-MODEL-06c: timeout_ms=60000 accepted; 60001 rejected."""
        ServerConfig(alias="svc", base_url="https://host.com", timeout_ms=60000)
        with pytest.raises(ValidationError):
            ServerConfig(alias="svc", base_url="https://host.com", timeout_ms=60001)


# ============================================================================
# TR-MODEL-2: LLMConfig
# ============================================================================

class TestLLMConfig:

    def test_valid_openai_config(self):
        """TC-MODEL-07: Valid OpenAI config creates without error."""
        cfg = LLMConfig(
            provider="openai",
            model="gpt-4o-mini",
            base_url="https://api.openai.com",
            api_key="sk-test",
            temperature=0.7,
        )
        assert cfg.provider == "openai"

    def test_provider_valid_values(self):
        """TC-MODEL-08a: All valid providers accepted."""
        for p in ("openai", "ollama", "mock"):
            LLMConfig(provider=p, model="m", base_url="https://x.com")

    def test_provider_invalid_rejected(self):
        """TC-MODEL-08b: Unknown provider raises ValidationError."""
        with pytest.raises(ValidationError):
            LLMConfig(provider="anthropic", model="m", base_url="https://x.com")

    def test_temperature_valid_boundaries(self):
        """TC-MODEL-09a: temperature 0.0 and 2.0 accepted."""
        LLMConfig(provider="mock", model="m", base_url="https://x.com", temperature=0.0)
        LLMConfig(provider="mock", model="m", base_url="https://x.com", temperature=2.0)

    def test_temperature_below_zero_rejected(self):
        """TC-MODEL-09b: temperature -0.1 rejected."""
        with pytest.raises(ValidationError):
            LLMConfig(provider="mock", model="m", base_url="https://x.com", temperature=-0.1)

    def test_temperature_above_two_rejected(self):
        """TC-MODEL-09c: temperature 2.1 rejected."""
        with pytest.raises(ValidationError):
            LLMConfig(provider="mock", model="m", base_url="https://x.com", temperature=2.1)

    def test_max_tokens_min_value(self):
        """TC-MODEL-10a: max_tokens=1 accepted; 0 rejected."""
        LLMConfig(provider="mock", model="m", base_url="https://x.com", max_tokens=1)
        with pytest.raises(ValidationError):
            LLMConfig(provider="mock", model="m", base_url="https://x.com", max_tokens=0)

    def test_max_tokens_none_accepted(self):
        """TC-MODEL-10b: max_tokens=None accepted."""
        cfg = LLMConfig(provider="mock", model="m", base_url="https://x.com", max_tokens=None)
        assert cfg.max_tokens is None

    def test_model_required(self):
        """TC-MODEL-11: Omitting model raises ValidationError."""
        with pytest.raises(ValidationError):
            LLMConfig(provider="mock", base_url="https://x.com")


# ============================================================================
# TR-MODEL-3: ChatMessage
# ============================================================================

class TestChatMessage:

    def test_valid_roles(self):
        """TC-MODEL-12a: All valid roles accepted."""
        for role in ("user", "assistant", "tool", "system"):
            ChatMessage(role=role, content="hello")

    def test_invalid_role_rejected(self):
        """TC-MODEL-12b: Unknown role rejected."""
        with pytest.raises(ValidationError):
            ChatMessage(role="bot", content="hello")

    def test_content_required(self):
        """TC-MODEL-13: Omitting content raises ValidationError."""
        with pytest.raises(ValidationError):
            ChatMessage(role="user")

    def test_tool_call_id_optional(self):
        """TC-MODEL-14: tool_call_id defaults to None."""
        msg = ChatMessage(role="tool", content="result")
        assert msg.tool_call_id is None

    def test_tool_call_id_stored(self):
        """TC-MODEL-14b: Provided tool_call_id is stored."""
        msg = ChatMessage(role="tool", content="result", tool_call_id="call_1")
        assert msg.tool_call_id == "call_1"

    def test_tool_calls_optional(self):
        """TC-MODEL-15: tool_calls defaults to None."""
        msg = ChatMessage(role="assistant", content="hi")
        assert msg.tool_calls is None


# ============================================================================
# TR-MODEL-4: ToolSchema
# ============================================================================

class TestToolSchema:

    def test_all_required_fields(self):
        """TC-MODEL-16: namespaced_id, server_alias, name, description required."""
        t = ToolSchema(
            namespaced_id="svc__ping",
            server_alias="svc",
            name="ping",
            description="Ping a host",
        )
        assert t.namespaced_id == "svc__ping"

    def test_parameters_default_empty_dict(self):
        """TC-MODEL-17: Omitting parameters defaults to {}."""
        t = ToolSchema(
            namespaced_id="svc__ping",
            server_alias="svc",
            name="ping",
            description="",
        )
        assert t.parameters == {}

    def test_missing_required_fields_rejected(self):
        """TC-MODEL-16b: Missing required fields raises ValidationError."""
        with pytest.raises(ValidationError):
            ToolSchema(server_alias="svc", name="ping", description="")
