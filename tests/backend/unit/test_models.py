"""
Unit tests for Pydantic models (TR-MODEL-*)
"""

import pytest
from pydantic import ValidationError
from datetime import datetime

from backend.models import (
    ServerConfig,
    LLMConfig,
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
