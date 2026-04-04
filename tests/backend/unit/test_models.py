"""
Unit tests for Pydantic models (TR-MODEL-*)
"""

import pytest
from pydantic import ValidationError
from datetime import datetime, timezone

from backend.models import (
    ServerConfig,
    LLMConfig,
    MilvusConfig,
    ChatMessage,
    ToolSchema,
    FunctionCall,
    ToolCall,
    EnterpriseTokenRequest,
    EnterpriseTokenResponse,
    EnterpriseTokenStatusResponse,
    ExecutionHints,
    ExecutionHintsSampling,
    RepeatedExecRunResult,
    RepeatedExecSummary,
    UserProfile,
    UserSettings,
    UserSettingsPatch,
    AdminUserPatch,
    UserListResponse,
    MemoryFeatureFlags,
    MemoryConfigSummary,
    MemoryStatus,
    MemoryCollectionStatus,
    MemoryIngestionJobStatus,
    MemoryDiagnosticsResponse,
    MemoryCollectionRowCount,
    MemoryRowCountsResponse,
    ToolFrequencyStat,
    FreshnessCandidate,
    QualityReportResponse,
    FreshnessCandidatesResponse,
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

    def test_llm_timeout_ms_default(self):
        """TC-MODEL-07b: Default llm_timeout_ms is 180000."""
        cfg = LLMConfig(provider="mock", model="m", base_url="https://x.com")
        assert cfg.llm_timeout_ms == 180000

    def test_llm_timeout_ms_boundaries(self):
        """TC-MODEL-07c: llm_timeout_ms accepts 5000..600000 and rejects out of range values."""
        LLMConfig(provider="mock", model="m", base_url="https://x.com", llm_timeout_ms=5000)
        LLMConfig(provider="mock", model="m", base_url="https://x.com", llm_timeout_ms=600000)
        with pytest.raises(ValidationError):
            LLMConfig(provider="mock", model="m", base_url="https://x.com", llm_timeout_ms=4999)
        with pytest.raises(ValidationError):
            LLMConfig(provider="mock", model="m", base_url="https://x.com", llm_timeout_ms=600001)

    def test_provider_valid_values(self):
        """TC-MODEL-08a: All valid providers accepted."""
        for p in ("openai", "ollama", "mock"):
            LLMConfig(provider=p, model="m", base_url="https://x.com")

    def test_enterprise_provider_valid_config(self):
        """TC-MODEL-08c: Enterprise provider accepted with required gateway fields."""
        cfg = LLMConfig(
            gateway_mode="enterprise",
            provider="enterprise",
            model="gpt-4o",
            base_url="https://llm-gateway.internal/modelgw/models/openai/v1",
            auth_method="bearer",
            client_id="enterprise-client",
            client_secret="enterprise-secret",
            token_endpoint_url="https://auth.internal/v2/oauth/token",
        )
        assert cfg.provider == "enterprise"

    def test_enterprise_provider_missing_token_endpoint_rejected(self):
        """TC-MODEL-08d: Enterprise provider requires token_endpoint_url."""
        with pytest.raises(ValidationError):
            LLMConfig(
                gateway_mode="enterprise",
                provider="enterprise",
                model="gpt-4o",
                base_url="https://llm-gateway.internal/modelgw/models/openai/v1",
                auth_method="bearer",
                client_id="enterprise-client",
                client_secret="enterprise-secret",
            )

    def test_enterprise_provider_missing_client_id_rejected(self):
        """TC-MODEL-08e: Enterprise provider without client_id raises ValidationError."""
        with pytest.raises(ValidationError):
            LLMConfig(
                gateway_mode="enterprise",
                provider="enterprise",
                model="gpt-4o",
                base_url="https://llm-gateway.internal/modelgw/models/openai/v1",
                auth_method="bearer",
                client_secret="enterprise-secret",
                token_endpoint_url="https://auth.internal/v2/oauth/token",
            )

    def test_enterprise_provider_missing_client_secret_rejected(self):
        """TC-MODEL-08f: Enterprise provider without client_secret raises ValidationError."""
        with pytest.raises(ValidationError):
            LLMConfig(
                gateway_mode="enterprise",
                provider="enterprise",
                model="gpt-4o",
                base_url="https://llm-gateway.internal/modelgw/models/openai/v1",
                auth_method="bearer",
                client_id="enterprise-client",
                token_endpoint_url="https://auth.internal/v2/oauth/token",
            )

    def test_enterprise_provider_http_base_url_rejected(self):
        """TC-MODEL-08g: Enterprise provider with HTTP base_url raises ValidationError."""
        with pytest.raises(ValidationError):
            LLMConfig(
                gateway_mode="enterprise",
                provider="enterprise",
                model="gpt-4o",
                base_url="http://llm-gateway.internal/modelgw/models/openai/v1",
                auth_method="bearer",
                client_id="enterprise-client",
                client_secret="enterprise-secret",
                token_endpoint_url="https://auth.internal/v2/oauth/token",
            )

    def test_enterprise_provider_http_token_endpoint_rejected(self):
        """TC-MODEL-08h: Enterprise provider with HTTP token_endpoint_url raises ValidationError."""
        with pytest.raises(ValidationError):
            LLMConfig(
                gateway_mode="enterprise",
                provider="enterprise",
                model="gpt-4o",
                base_url="https://llm-gateway.internal/modelgw/models/openai/v1",
                auth_method="bearer",
                client_id="enterprise-client",
                client_secret="enterprise-secret",
                token_endpoint_url="http://auth.internal/v2/oauth/token",
            )

    def test_enterprise_provider_missing_auth_method_rejected(self):
        """TC-MODEL-08i: Enterprise provider without auth_method raises ValidationError."""
        with pytest.raises(ValidationError):
            LLMConfig(
                gateway_mode="enterprise",
                provider="enterprise",
                model="gpt-4o",
                base_url="https://llm-gateway.internal/modelgw/models/openai/v1",
                client_id="enterprise-client",
                client_secret="enterprise-secret",
                token_endpoint_url="https://auth.internal/v2/oauth/token",
            )

    def test_gateway_mode_enterprise_with_non_enterprise_provider_rejected(self):
        """TC-MODEL-08j: gateway_mode='enterprise' with provider='openai' raises ValidationError."""
        with pytest.raises(ValidationError):
            LLMConfig(
                gateway_mode="enterprise",
                provider="openai",
                model="gpt-4o",
                base_url="https://api.openai.com",
                api_key="sk-test",
            )

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


# ============================================================================
# TR-MODEL-2b: MilvusConfig
# ============================================================================

class TestMilvusConfig:

    def test_disabled_config_allows_blank_uri(self):
        """TC-MODEL-09c: Disabled Milvus config can keep an empty URI."""
        cfg = MilvusConfig(enabled=False)
        assert cfg.enabled is False
        assert cfg.milvus_uri == ""

    def test_enabled_config_requires_uri(self):
        """TC-MODEL-09d: Enabled Milvus config without URI is rejected."""
        with pytest.raises(ValidationError):
            MilvusConfig(enabled=True, milvus_uri="")

    def test_allowlist_is_trimmed_and_empty_values_removed(self):
        """TC-MODEL-09e: Tool-cache allowlist is normalized on input."""
        cfg = MilvusConfig(
            enabled=True,
            milvus_uri=" http://127.0.0.1:19530 ",
            tool_cache_allowlist=[" github__get_issue ", "", "  ", "weather__get_forecast"],
        )
        assert cfg.milvus_uri == "http://127.0.0.1:19530"
        assert cfg.tool_cache_allowlist == ["github__get_issue", "weather__get_forecast"]

    def test_numeric_boundaries_enforced(self):
        """TC-MODEL-09f: Milvus numeric fields enforce documented bounds."""
        MilvusConfig(
            enabled=True,
            milvus_uri="http://127.0.0.1:19530",
            max_results=50,
            retrieval_timeout_s=60.0,
            conversation_retention_days=365,
            tool_cache_ttl_s=2592000.0,
            expiry_cleanup_interval_s=86400.0,
        )
        with pytest.raises(ValidationError):
            MilvusConfig(enabled=True, milvus_uri="http://127.0.0.1:19530", max_results=0)

    def test_default_values_match_spec(self):
        """TC-MODEL-09g: Default MilvusConfig matches documented default spec."""
        cfg = MilvusConfig()
        assert cfg.enabled is False
        assert cfg.milvus_uri == ""
        assert cfg.collection_prefix == "mcp_client"
        assert cfg.repo_id == ""
        assert cfg.collection_generation == "v1"
        assert cfg.max_results == 5
        assert cfg.retrieval_timeout_s == 5.0
        assert cfg.degraded_mode is True
        assert cfg.enable_conversation_memory is False
        assert cfg.conversation_retention_days == 7
        assert cfg.enable_tool_cache is False
        assert cfg.tool_cache_ttl_s == 3600.0
        assert cfg.tool_cache_allowlist == []
        assert cfg.enable_adaptive_learning is False
        assert cfg.aql_quality_retention_days == 30
        assert cfg.aql_min_records_for_routing == 20
        assert cfg.aql_affinity_confidence_threshold == 0.65
        assert cfg.aql_chunk_reorder_threshold == 0.70
        assert cfg.aql_affinity_weights == {
            "similarity": 0.5,
            "success_rate": 0.3,
            "bypass_rate": -0.1,
            "corrected_penalty": -0.3,
        }
        assert r"\bwrong\b" in cfg.aql_correction_patterns
        assert cfg.enable_expiry_cleanup is True
        assert cfg.expiry_cleanup_interval_s == 300.0

    def test_aql_correction_patterns_trim_blank_values(self):
        """TC-AQL-P1-MODEL-01: correction-pattern list is normalized and blank entries are removed."""
        cfg = MilvusConfig(
            aql_correction_patterns=["  ", r"\bwrong\b", " actually ", ""],
        )

        assert cfg.aql_correction_patterns == [r"\bwrong\b", "actually"]

    def test_aql_affinity_weights_merge_with_defaults(self):
        """TC-AQL-P1-MODEL-02: partial AQL affinity weight maps merge into the default set."""
        cfg = MilvusConfig(aql_affinity_weights={"similarity": 0.8, "success_rate": 0.25})

        assert cfg.aql_affinity_weights == {
            "similarity": 0.8,
            "success_rate": 0.25,
            "bypass_rate": -0.1,
            "corrected_penalty": -0.3,
        }

    def test_aql_numeric_boundaries_enforced(self):
        """TC-AQL-P1-MODEL-03: AQL numeric fields enforce documented bounds."""
        MilvusConfig(
            aql_quality_retention_days=365,
            aql_min_records_for_routing=1000,
            aql_affinity_confidence_threshold=1.0,
            aql_chunk_reorder_threshold=0.0,
        )
        with pytest.raises(ValidationError):
            MilvusConfig(aql_quality_retention_days=0)
        with pytest.raises(ValidationError):
            MilvusConfig(aql_min_records_for_routing=0)
        with pytest.raises(ValidationError):
            MilvusConfig(aql_affinity_confidence_threshold=1.1)
        with pytest.raises(ValidationError):
            MilvusConfig(aql_chunk_reorder_threshold=-0.01)

    def test_enabled_with_valid_uri_accepted(self):
        """TC-MODEL-09h: Enabled config with a non-empty URI constructs without error."""
        cfg = MilvusConfig(enabled=True, milvus_uri="http://127.0.0.1:19530")
        assert cfg.enabled is True
        assert cfg.milvus_uri == "http://127.0.0.1:19530"

    def test_collection_prefix_whitespace_stripped(self):
        """TC-MODEL-09i: Leading/trailing whitespace is stripped from collection_prefix."""
        cfg = MilvusConfig(collection_prefix="  my_prefix  ")
        assert cfg.collection_prefix == "my_prefix"

    def test_collection_prefix_empty_rejected(self):
        """TC-MODEL-09j: Literal empty string for collection_prefix is rejected (min_length=1)."""
        with pytest.raises(ValidationError):
            MilvusConfig(collection_prefix="")

    def test_collection_prefix_max_length_boundary(self):
        """TC-MODEL-09k: collection_prefix of exactly 64 chars is valid; 65 chars is rejected."""
        MilvusConfig(collection_prefix="a" * 64)
        with pytest.raises(ValidationError):
            MilvusConfig(collection_prefix="a" * 65)

    def test_repo_id_whitespace_stripped(self):
        """TC-MODEL-09l: Leading/trailing whitespace is stripped from repo_id."""
        cfg = MilvusConfig(repo_id="  owner/repo  ")
        assert cfg.repo_id == "owner/repo"

    def test_repo_id_max_length_boundary(self):
        """TC-MODEL-09m: repo_id of exactly 256 chars is valid; 257 chars is rejected."""
        MilvusConfig(repo_id="a" * 256)
        with pytest.raises(ValidationError):
            MilvusConfig(repo_id="a" * 257)

    def test_collection_generation_empty_rejected(self):
        """TC-MODEL-09n: Empty collection_generation is rejected (min_length=1)."""
        with pytest.raises(ValidationError):
            MilvusConfig(collection_generation="")

    def test_max_results_min_boundary(self):
        """TC-MODEL-09o: max_results=1 is valid; max_results=0 is rejected."""
        MilvusConfig(max_results=1)
        with pytest.raises(ValidationError):
            MilvusConfig(max_results=0)

    def test_max_results_max_boundary(self):
        """TC-MODEL-09p: max_results=50 is valid; max_results=51 is rejected."""
        MilvusConfig(max_results=50)
        with pytest.raises(ValidationError):
            MilvusConfig(max_results=51)

    def test_retrieval_timeout_min_boundary(self):
        """TC-MODEL-09q: retrieval_timeout_s=0.1 is valid; 0.09 is rejected."""
        MilvusConfig(retrieval_timeout_s=0.1)
        with pytest.raises(ValidationError):
            MilvusConfig(retrieval_timeout_s=0.09)

    def test_retrieval_timeout_max_boundary(self):
        """TC-MODEL-09r: retrieval_timeout_s=60.0 is valid; 60.1 is rejected."""
        MilvusConfig(retrieval_timeout_s=60.0)
        with pytest.raises(ValidationError):
            MilvusConfig(retrieval_timeout_s=60.1)

    def test_conversation_retention_days_min_boundary(self):
        """TC-MODEL-09s: conversation_retention_days=1 is valid; 0 is rejected."""
        MilvusConfig(conversation_retention_days=1)
        with pytest.raises(ValidationError):
            MilvusConfig(conversation_retention_days=0)

    def test_conversation_retention_days_max_boundary(self):
        """TC-MODEL-09t: conversation_retention_days=365 is valid; 366 is rejected."""
        MilvusConfig(conversation_retention_days=365)
        with pytest.raises(ValidationError):
            MilvusConfig(conversation_retention_days=366)

    def test_tool_cache_ttl_min_boundary(self):
        """TC-MODEL-09u: tool_cache_ttl_s=1.0 is valid; 0.9 is rejected."""
        MilvusConfig(tool_cache_ttl_s=1.0)
        with pytest.raises(ValidationError):
            MilvusConfig(tool_cache_ttl_s=0.9)

    def test_tool_cache_ttl_max_boundary(self):
        """TC-MODEL-09v: tool_cache_ttl_s=2592000 is valid; 2592001 is rejected."""
        MilvusConfig(tool_cache_ttl_s=2592000.0)
        with pytest.raises(ValidationError):
            MilvusConfig(tool_cache_ttl_s=2592001.0)

    def test_expiry_cleanup_interval_min_boundary(self):
        """TC-MODEL-09w: expiry_cleanup_interval_s=1.0 is valid; 0.9 is rejected."""
        MilvusConfig(expiry_cleanup_interval_s=1.0)
        with pytest.raises(ValidationError):
            MilvusConfig(expiry_cleanup_interval_s=0.9)

    def test_expiry_cleanup_interval_max_boundary(self):
        """TC-MODEL-09x: expiry_cleanup_interval_s=86400.0 is valid; 86400.1 is rejected."""
        MilvusConfig(expiry_cleanup_interval_s=86400.0)
        with pytest.raises(ValidationError):
            MilvusConfig(expiry_cleanup_interval_s=86400.1)

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

    def test_tiny_mode_classifier_override_fields_are_optional(self):
        """Tiny classifier override fields default to None when omitted."""
        cfg = LLMConfig(provider="mock", model="m", base_url="https://x.com")
        assert cfg.tiny_llm_mode_classifier_enabled is None
        assert cfg.tiny_llm_mode_classifier_min_confidence is None
        assert cfg.tiny_llm_mode_classifier_min_score_gap is None
        assert cfg.tiny_llm_mode_classifier_accept_confidence is None
        assert cfg.tiny_llm_mode_classifier_max_tokens is None

    def test_tiny_mode_classifier_override_bounds(self):
        """Tiny classifier override fields validate numeric ranges."""
        LLMConfig(
            provider="mock",
            model="m",
            base_url="https://x.com",
            tiny_llm_mode_classifier_min_confidence=0.5,
            tiny_llm_mode_classifier_min_score_gap=3,
            tiny_llm_mode_classifier_accept_confidence=0.6,
            tiny_llm_mode_classifier_max_tokens=64,
        )
        with pytest.raises(ValidationError):
            LLMConfig(provider="mock", model="m", base_url="https://x.com", tiny_llm_mode_classifier_min_confidence=1.1)
        with pytest.raises(ValidationError):
            LLMConfig(provider="mock", model="m", base_url="https://x.com", tiny_llm_mode_classifier_accept_confidence=-0.1)
        with pytest.raises(ValidationError):
            LLMConfig(provider="mock", model="m", base_url="https://x.com", tiny_llm_mode_classifier_max_tokens=16)


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
# TR-MODEL-AQL: Adaptive Query Learning response models
# ============================================================================

class TestAdaptiveQueryLearningModels:

    def test_memory_row_counts_response_instantiates(self):
        """TC-AQL-P1-MODEL-04: MemoryRowCountsResponse accepts the additive row-count payload shape."""
        response = MemoryRowCountsResponse(
            success=True,
            generation="v1",
            counts=[
                MemoryCollectionRowCount(
                    collection_key="tool_execution_quality",
                    collection_name="mcp_client_tool_execution_quality_v1",
                    row_count=0,
                    available=True,
                )
            ],
        )

        assert response.success is True
        assert response.generation == "v1"
        assert response.counts[0].collection_key == "tool_execution_quality"

    def test_quality_report_response_instantiates(self):
        """TC-AQL-P1-MODEL-05: QualityReportResponse supports the future AQL admin summary payload."""
        response = QualityReportResponse(
            total_turns=10,
            avg_tools_per_turn=2.5,
            avg_llm_turns=1.4,
            avg_synthesis_tokens=1800.0,
            correction_rate=0.1,
            top_succeeded_tools=[ToolFrequencyStat(tool="svc__get_memory_info", count=4)],
            top_failed_tools=[ToolFrequencyStat(tool="svc__device_processor_speed", count=2)],
            freshness_keyword_candidates=[
                FreshnessCandidate(pattern="loadavg", signal="bypass_rate", score=0.82)
            ],
            routing_distribution={"llm_fallback": 0.7, "direct": 0.3},
        )

        assert response.total_turns == 10
        assert response.top_succeeded_tools[0].tool == "svc__get_memory_info"
        assert response.freshness_keyword_candidates[0].pattern == "loadavg"

    def test_freshness_candidates_response_instantiates(self):
        """TC-AQL-P1-MODEL-06: FreshnessCandidatesResponse supports read-only recommendation payloads."""
        response = FreshnessCandidatesResponse(
            candidates=[FreshnessCandidate(pattern="cpu_stats", signal="cache_stale", score=0.61)],
            current_keywords=["uptime", "health"],
        )

        assert response.candidates[0].pattern == "cpu_stats"
        assert response.current_keywords == ["uptime", "health"]


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


# ============================================================================
# TR-MODEL-5: EnterpriseTokenRequest
# ============================================================================

class TestEnterpriseTokenRequest:

    def test_valid_token_request(self):
        """TC-MODEL-18: Valid enterprise token request accepted."""
        req = EnterpriseTokenRequest(
            token_endpoint_url="https://auth.internal/v2/oauth/token",
            client_id="enterprise-client",
            client_secret="enterprise-secret",
        )
        assert req.client_id == "enterprise-client"
        assert req.token_endpoint_url == "https://auth.internal/v2/oauth/token"

    def test_http_token_endpoint_rejected(self):
        """TC-MODEL-19: HTTP token_endpoint_url rejected (must be HTTPS)."""
        with pytest.raises(ValidationError):
            EnterpriseTokenRequest(
                token_endpoint_url="http://auth.internal/v2/oauth/token",
                client_id="enterprise-client",
                client_secret="enterprise-secret",
            )

    def test_empty_client_id_rejected(self):
        """TC-MODEL-20: Empty client_id rejected by min_length constraint."""
        with pytest.raises(ValidationError):
            EnterpriseTokenRequest(
                token_endpoint_url="https://auth.internal/v2/oauth/token",
                client_id="",
                client_secret="enterprise-secret",
            )

    def test_empty_client_secret_rejected(self):
        """TC-MODEL-21: Empty client_secret rejected by min_length constraint."""
        with pytest.raises(ValidationError):
            EnterpriseTokenRequest(
                token_endpoint_url="https://auth.internal/v2/oauth/token",
                client_id="enterprise-client",
                client_secret="",
            )

    def test_missing_token_endpoint_url_rejected(self):
        """TC-MODEL-21b: Missing token_endpoint_url raises ValidationError."""
        with pytest.raises(ValidationError):
            EnterpriseTokenRequest(
                client_id="enterprise-client",
                client_secret="enterprise-secret",
            )


# ============================================================================
# TR-MODEL-6: EnterpriseTokenResponse
# ============================================================================

class TestEnterpriseTokenResponse:

    def test_successful_response(self):
        """TC-MODEL-22: Successful token response with all fields."""
        now = datetime.utcnow()
        resp = EnterpriseTokenResponse(
            token_acquired=True,
            expires_in=3600,
            cached_at=now,
            error=None,
        )
        assert resp.token_acquired is True
        assert resp.expires_in == 3600
        assert resp.cached_at == now
        assert resp.error is None

    def test_failure_response(self):
        """TC-MODEL-23: Failed token response with error field and no metadata."""
        resp = EnterpriseTokenResponse(
            token_acquired=False,
            error="Token endpoint returned 401",
        )
        assert resp.token_acquired is False
        assert resp.error == "Token endpoint returned 401"
        assert resp.cached_at is None
        assert resp.expires_in is None

    def test_access_token_field_absent(self):
        """TC-MODEL-23b: EnterpriseTokenResponse has no access_token field."""
        resp = EnterpriseTokenResponse(token_acquired=True, expires_in=3600)
        assert not hasattr(resp, "access_token")


# ============================================================================
# TR-MODEL-7: EnterpriseTokenStatusResponse
# ============================================================================

class TestEnterpriseTokenStatusResponse:

    def test_not_cached_status(self):
        """TC-MODEL-24: Not-cached status has token_cached=False and no metadata."""
        status = EnterpriseTokenStatusResponse(token_cached=False)
        assert status.token_cached is False
        assert status.cached_at is None
        assert status.expires_in is None

    def test_cached_status_with_metadata(self):
        """TC-MODEL-25: Cached status includes cached_at and expires_in."""
        ts = datetime.utcnow()
        status = EnterpriseTokenStatusResponse(
            token_cached=True,
            cached_at=ts,
            expires_in=3600,
        )
        assert status.token_cached is True
        assert status.cached_at == ts
        assert status.expires_in == 3600


# ============================================================================
# TR-MODEL-8: ExecutionHints + ExecutionHintsSampling
# ============================================================================

class TestExecutionHints:

    def test_fully_populated_hints(self):
        """TC-MODEL-26: All fields parse correctly."""
        hints = ExecutionHints(
            defaultTimeoutMs=30000,
            maxTimeoutMs=120000,
            estimatedRuntimeMs=11000,
            clientWaitMarginMs=5000,
            mode="sampling",
            sampling=ExecutionHintsSampling(
                defaultSampleCount=6,
                defaultIntervalMs=2000,
            ),
        )
        assert hints.mode == "sampling"
        assert hints.sampling.defaultSampleCount == 6
        assert hints.sampling.defaultIntervalMs == 2000

    def test_all_fields_optional_except_sampling_count(self):
        """TC-MODEL-27: ExecutionHints with no fields except mode=oneShot is valid."""
        hints = ExecutionHints(mode="oneShot")
        assert hints.defaultTimeoutMs is None
        assert hints.sampling is None

    def test_recommended_wait_ms_full(self):
        """TC-MODEL-28: recommended_wait_ms = max(default,estimated) + margin."""
        hints = ExecutionHints(
            defaultTimeoutMs=30000,
            estimatedRuntimeMs=11000,
            clientWaitMarginMs=5000,
        )
        # max(30000, 11000) + 5000 = 35000
        assert hints.recommended_wait_ms() == 35000

    def test_recommended_wait_ms_estimated_wins(self):
        """TC-MODEL-29: estimated > default → estimated used as base."""
        hints = ExecutionHints(
            defaultTimeoutMs=10000,
            estimatedRuntimeMs=50000,
            clientWaitMarginMs=2000,
        )
        assert hints.recommended_wait_ms() == 52000

    def test_recommended_wait_ms_all_none(self):
        """TC-MODEL-30: All fields absent → recommended_wait_ms() returns 0."""
        hints = ExecutionHints()
        assert hints.recommended_wait_ms() == 0

    def test_recommended_wait_ms_no_margin(self):
        """TC-MODEL-31: Missing clientWaitMarginMs treated as 0."""
        hints = ExecutionHints(defaultTimeoutMs=20000, estimatedRuntimeMs=5000)
        assert hints.recommended_wait_ms() == 20000

    def test_unknown_fields_ignored(self):
        """TC-MODEL-32: Unknown fields inside executionHints are silently ignored (CR-EXEC-003)."""
        hints = ExecutionHints.model_validate({
            "defaultTimeoutMs": 30000,
            "unknownFutureField": "value",
            "anotherUnknown": {"nested": True},
        })
        assert hints.defaultTimeoutMs == 30000
        assert not hasattr(hints, "unknownFutureField")

    def test_mode_invalid_value_rejected(self):
        """TC-MODEL-33: mode must be 'sampling' or 'oneShot'."""
        with pytest.raises(ValidationError):
            ExecutionHints(mode="streaming")

    def test_sampling_default_interval_ms_optional(self):
        """TC-MODEL-34: defaultIntervalMs absent for oneShot tools is valid."""
        s = ExecutionHintsSampling(defaultSampleCount=1)
        assert s.defaultIntervalMs is None

    def test_tool_schema_with_hints(self):
        """TC-MODEL-35: ToolSchema accepts execution_hints without error."""
        tool = ToolSchema(
            namespaced_id="debug__proc_cpu_spin_diagnose",
            server_alias="debug",
            name="proc_cpu_spin_diagnose",
            description="Detect CPU spin",
            execution_hints=ExecutionHints(
                defaultTimeoutMs=30000,
                estimatedRuntimeMs=11000,
                clientWaitMarginMs=5000,
                mode="sampling",
            ),
        )
        assert tool.execution_hints.mode == "sampling"
        assert tool.execution_hints.recommended_wait_ms() == 35000

    def test_tool_schema_without_hints_still_valid(self):
        """TC-MODEL-36: ToolSchema with no execution_hints is fully backward-compatible."""
        tool = ToolSchema(
            namespaced_id="weather__get_weather",
            server_alias="weather",
            name="get_weather",
            description="Get weather",
        )
        assert tool.execution_hints is None


# ============================================================================
# TR-MODEL-9: RepeatedExecRunResult
# ============================================================================

class TestRepeatedExecRunResult:

    def test_successful_run(self):
        """TC-MODEL-37: Successful run stores result and no error."""
        r = RepeatedExecRunResult(
            run_index=1,
            timestamp_utc="2026-03-17T14:32:01Z",
            duration_ms=11432,
            success=True,
            result={"threads": []},
            error=None,
            file_path="/tmp/run1.txt",
        )
        assert r.success is True
        assert r.result == {"threads": []}
        assert r.error is None
        assert r.file_path == "/tmp/run1.txt"

    def test_failed_run(self):
        """TC-MODEL-38: Failed run stores error and null result."""
        r = RepeatedExecRunResult(
            run_index=2,
            timestamp_utc="2026-03-17T14:32:13Z",
            duration_ms=100,
            success=False,
            result=None,
            error="Timeout executing proc_cpu_spin_diagnose",
            file_path=None,
        )
        assert r.success is False
        assert r.result is None
        assert "Timeout" in r.error
        assert r.file_path is None

    def test_run_index_required(self):
        """TC-MODEL-39: Missing run_index raises ValidationError."""
        with pytest.raises(ValidationError):
            RepeatedExecRunResult(
                timestamp_utc="2026-03-17T14:32:01Z",
                duration_ms=1000,
                success=True,
            )

    def test_serialises_to_dict(self):
        """TC-MODEL-40: model_dump() returns expected keys for file persistence."""
        r = RepeatedExecRunResult(
            run_index=1, timestamp_utc="2026-03-17T14:32:01Z",
            duration_ms=5000, success=True, result={"x": 1},
            error=None, file_path="/tmp/f.txt",
        )
        d = r.model_dump()
        for key in ("run_index", "timestamp_utc", "duration_ms",
                    "success", "result", "error", "file_path"):
            assert key in d


# ============================================================================
# TR-MODEL-10: RepeatedExecSummary
# ============================================================================

class TestRepeatedExecSummary:

    def _run(self, idx, success=True):
        return RepeatedExecRunResult(
            run_index=idx,
            timestamp_utc="2026-03-17T14:32:01Z",
            duration_ms=1000,
            success=success,
            result={"ok": True} if success else None,
            error=None if success else "err",
            file_path=None,
        )

    def test_summary_counts(self):
        """TC-MODEL-41: success_count and failure_count reflect run outcomes."""
        runs = [self._run(1, True), self._run(2, False), self._run(3, True)]
        s = RepeatedExecSummary(
            device_id="host", target_tool="srv__tool", tool_name="tool",
            tool_arguments={}, repeat_count=3, interval_ms=1000,
            output_dir="data/runs", runs=runs,
            total_duration_ms=5000, success_count=2, failure_count=1,
        )
        assert s.success_count == 2
        assert s.failure_count == 1

    def test_summary_runs_ordered(self):
        """TC-MODEL-42: runs list preserves insertion order."""
        runs = [self._run(i) for i in range(1, 6)]
        s = RepeatedExecSummary(
            device_id="host", target_tool="srv__tool", tool_name="tool",
            tool_arguments={}, repeat_count=5, interval_ms=500,
            output_dir="data/runs", runs=runs,
            total_duration_ms=10000, success_count=5, failure_count=0,
        )
        assert [r.run_index for r in s.runs] == [1, 2, 3, 4, 5]

    def test_summary_serialises_to_json(self):
        """TC-MODEL-43: model_dump() produces JSON-serialisable structure for session trace."""
        import json
        runs = [self._run(1)]
        s = RepeatedExecSummary(
            device_id="host", target_tool="srv__t", tool_name="t",
            tool_arguments={}, repeat_count=1, interval_ms=0,
            output_dir="data/runs", runs=runs,
            total_duration_ms=1000, success_count=1, failure_count=0,
        )
        dumped = s.model_dump()
        # Should round-trip through json without error
        json.dumps(dumped, default=str)

    def test_empty_runs_list(self):
        """TC-MODEL-44: Summary with no runs is valid (edge case: all skipped)."""
        s = RepeatedExecSummary(
            device_id="host", target_tool="srv__t", tool_name="t",
            tool_arguments={}, repeat_count=0, interval_ms=0,
            output_dir="data/runs", runs=[],
            total_duration_ms=0, success_count=0, failure_count=0,
        )
        assert s.runs == []
        assert s.success_count == 0


# ============================================================================
# TR-MODEL-SSO: SSO / Auth models  (v0.4.0-sso-user-settings)
# ============================================================================

def _valid_profile_kwargs(**overrides):
    base = {
        "user_id": "550e8400-e29b-41d4-a716-446655440001",
        "email": "alice@example.com",
        "display_name": "Alice Smith",
        "avatar_url": None,
        "roles": ["user"],
        "created_at": datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
        "last_login_at": datetime(2026, 3, 18, 8, 45, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


class TestUserProfile:

    def test_valid_construction(self):
        """TC-MODEL-SSO-01: Valid UserProfile constructs without error."""
        p = UserProfile(**_valid_profile_kwargs())
        assert p.email == "alice@example.com"
        assert p.display_name == "Alice Smith"

    def test_avatar_url_is_optional_none(self):
        """TC-MODEL-SSO-02: avatar_url accepts None."""
        p = UserProfile(**_valid_profile_kwargs(avatar_url=None))
        assert p.avatar_url is None

    def test_avatar_url_accepts_url_string(self):
        """TC-MODEL-SSO-03: avatar_url accepts a non-null URL string."""
        p = UserProfile(**_valid_profile_kwargs(avatar_url="https://cdn.example.com/pic.jpg"))
        assert "cdn.example.com" in p.avatar_url

    def test_roles_list_with_admin(self):
        """TC-MODEL-SSO-04: roles list can contain both 'user' and 'admin'."""
        p = UserProfile(**_valid_profile_kwargs(roles=["user", "admin"]))
        assert "admin" in p.roles

    def test_missing_user_id_raises(self):
        """TC-MODEL-SSO-05: Missing user_id raises ValidationError."""
        kwargs = _valid_profile_kwargs()
        del kwargs["user_id"]
        with pytest.raises(ValidationError):
            UserProfile(**kwargs)

    def test_missing_email_raises(self):
        """TC-MODEL-SSO-06: Missing email raises ValidationError."""
        kwargs = _valid_profile_kwargs()
        del kwargs["email"]
        with pytest.raises(ValidationError):
            UserProfile(**kwargs)

    def test_missing_created_at_raises(self):
        """TC-MODEL-SSO-07: Missing created_at raises ValidationError."""
        kwargs = _valid_profile_kwargs()
        del kwargs["created_at"]
        with pytest.raises(ValidationError):
            UserProfile(**kwargs)

    def test_missing_last_login_at_raises(self):
        """TC-MODEL-SSO-08: Missing last_login_at raises ValidationError."""
        kwargs = _valid_profile_kwargs()
        del kwargs["last_login_at"]
        with pytest.raises(ValidationError):
            UserProfile(**kwargs)


class TestUserSettings:

    def test_default_theme_is_system(self):
        """TC-MODEL-SSO-09: Default theme is 'system'."""
        assert UserSettings().theme == "system"

    def test_default_message_density_is_comfortable(self):
        """TC-MODEL-SSO-10: Default message_density is 'comfortable'."""
        assert UserSettings().message_density == "comfortable"

    def test_default_tool_panel_visible_is_true(self):
        """TC-MODEL-SSO-11: Default tool_panel_visible is True."""
        assert UserSettings().tool_panel_visible is True

    def test_default_sidebar_collapsed_is_false(self):
        """TC-MODEL-SSO-12: Default sidebar_collapsed is False."""
        assert UserSettings().sidebar_collapsed is False

    def test_default_llm_model_is_none(self):
        """TC-MODEL-SSO-13: Default default_llm_model is None."""
        assert UserSettings().default_llm_model is None

    def test_valid_theme_values(self):
        """TC-MODEL-SSO-14: All three valid theme literals are accepted."""
        for theme in ("light", "dark", "system"):
            s = UserSettings(theme=theme)
            assert s.theme == theme

    def test_invalid_theme_raises(self):
        """TC-MODEL-SSO-15: Unknown theme value raises ValidationError."""
        with pytest.raises(ValidationError):
            UserSettings(theme="solarized")

    def test_valid_density_values(self):
        """TC-MODEL-SSO-16: Both valid message_density literals are accepted."""
        for density in ("compact", "comfortable"):
            s = UserSettings(message_density=density)
            assert s.message_density == density

    def test_invalid_density_raises(self):
        """TC-MODEL-SSO-17: Unknown message_density raises ValidationError."""
        with pytest.raises(ValidationError):
            UserSettings(message_density="wide")

    def test_default_llm_model_accepts_string(self):
        """TC-MODEL-SSO-18: default_llm_model accepts a non-null model string."""
        s = UserSettings(default_llm_model="gpt-4o")
        assert s.default_llm_model == "gpt-4o"


class TestUserSettingsPatch:

    def test_all_none_is_valid(self):
        """TC-MODEL-SSO-19: UserSettingsPatch with all None fields is valid."""
        p = UserSettingsPatch()
        assert p.theme is None
        assert p.message_density is None
        assert p.tool_panel_visible is None
        assert p.sidebar_collapsed is None
        assert p.default_llm_model is None

    def test_partial_patch_only_sets_supplied_fields(self):
        """TC-MODEL-SSO-20: Supplying one field leaves others as None."""
        p = UserSettingsPatch(theme="dark")
        assert p.theme == "dark"
        assert p.message_density is None

    def test_invalid_theme_in_patch_raises(self):
        """TC-MODEL-SSO-21: Invalid theme in UserSettingsPatch raises ValidationError."""
        with pytest.raises(ValidationError):
            UserSettingsPatch(theme="invalid-theme")

    def test_invalid_density_in_patch_raises(self):
        """TC-MODEL-SSO-22: Invalid message_density in UserSettingsPatch raises ValidationError."""
        with pytest.raises(ValidationError):
            UserSettingsPatch(message_density="ultra-wide")


class TestAdminUserPatch:

    def test_is_active_true(self):
        """TC-MODEL-SSO-23: AdminUserPatch with is_active=True is valid."""
        p = AdminUserPatch(is_active=True)
        assert p.is_active is True

    def test_is_active_false(self):
        """TC-MODEL-SSO-24: AdminUserPatch with is_active=False is valid."""
        p = AdminUserPatch(is_active=False)
        assert p.is_active is False

    def test_missing_is_active_raises(self):
        """TC-MODEL-SSO-25: Omitting is_active raises ValidationError."""
        with pytest.raises(ValidationError):
            AdminUserPatch()


class TestUserListResponse:

    def test_valid_construction_empty_list(self):
        """TC-MODEL-SSO-26: UserListResponse constructs with empty user list."""
        r = UserListResponse(users=[], total=0, limit=50, offset=0)
        assert r.total == 0
        assert r.users == []

    def test_pagination_fields_preserved(self):
        """TC-MODEL-SSO-27: limit and offset values are preserved as provided."""
        r = UserListResponse(users=[], total=100, limit=10, offset=20)
        assert r.limit == 10
        assert r.offset == 20
        assert r.total == 100

    def test_users_list_with_profiles(self):
        """TC-MODEL-SSO-28: users list can contain UserProfile instances."""
        profile = UserProfile(**_valid_profile_kwargs())
        r = UserListResponse(users=[profile], total=1, limit=50, offset=0)
        assert len(r.users) == 1
        assert r.users[0].email == "alice@example.com"


# ============================================================================
# TR-MODEL-MEM: Memory config and diagnostics models
# ============================================================================

class TestMemoryFeatureFlags:

    def test_defaults_match_optional_memory_baseline(self):
        flags = MemoryFeatureFlags()
        assert flags.enabled is False
        assert flags.retrieval_enabled is False
        assert flags.conversation_enabled is False
        assert flags.tool_cache_enabled is False
        assert flags.ingestion_enabled is False
        assert flags.degraded_mode is True


class TestMemoryConfigSummary:

    def test_defaults_match_requirement_baseline(self):
        config = MemoryConfigSummary()
        assert config.milvus_uri_configured is False
        assert config.collection_prefix == "mcp_client"
        assert config.max_code_results == 5
        assert config.max_doc_results == 5
        assert config.max_conversation_results == 3
        assert config.code_threshold == 0.72
        assert config.doc_threshold == 0.68
        assert config.conversation_threshold == 0.82
        assert config.retention_days == 30
        assert config.repo_roots == []
        assert config.doc_roots == []

    def test_threshold_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            MemoryConfigSummary(code_threshold=1.1)

        with pytest.raises(ValidationError):
            MemoryConfigSummary(doc_threshold=-0.01)


class TestMemoryStatus:

    def test_valid_status_literals(self):
        for value in ("disabled", "healthy", "degraded"):
            status = MemoryStatus(status=value)
            assert status.status == value

    def test_invalid_status_literal_rejected(self):
        with pytest.raises(ValidationError):
            MemoryStatus(status="unknown")


class TestMemoryDiagnosticsResponse:

    def test_nested_diagnostics_payload_constructs(self):
        diagnostics = MemoryDiagnosticsResponse(
            feature_flags=MemoryFeatureFlags(enabled=True, retrieval_enabled=True),
            config=MemoryConfigSummary(
                milvus_uri_configured=True,
                embedding_provider="openai",
                embedding_model="text-embedding-3-small",
                repo_roots=["/workspace/src"],
                doc_roots=["/workspace/docs"],
            ),
            status=MemoryStatus(
                status="healthy",
                milvus_reachable=True,
                embedding_available=True,
            ),
            collections=[
                MemoryCollectionStatus(
                    collection_key="code_memory",
                    collection_name="mcp_client_code_memory_v1_20260330",
                    generation="20260330",
                    embedding_provider="openai",
                    embedding_model="text-embedding-3-small",
                    embedding_dimension=1536,
                    index_version="hnsw-v1",
                    is_active=True,
                )
            ],
            ingestion_jobs=[
                MemoryIngestionJobStatus(
                    job_id="job-001",
                    job_type="code_ingestion",
                    status="completed",
                    collection_key="code_memory",
                    repo_id="workspace-main",
                    source_count=12,
                    chunk_count=48,
                    error_count=0,
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            ],
        )

        assert diagnostics.feature_flags.enabled is True
        assert diagnostics.status.status == "healthy"
        assert diagnostics.collections[0].is_active is True
        assert diagnostics.ingestion_jobs[0].chunk_count == 48
