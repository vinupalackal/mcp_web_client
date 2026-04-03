"""
Unit tests for LLM client adapters and factory (TR-LLMC-*)
Uses respx to mock outbound httpx requests.
"""

import pytest
import respx
import httpx
from backend.llm_client import (
    OpenAIClient,
    OllamaClient,
    EnterpriseLLMClient,
    MockLLMClient,
    LLMClientFactory,
)
from backend.models import LLMConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def openai_config():
    return LLMConfig(
        provider="openai",
        model="gpt-4o-mini",
        base_url="https://api.openai.com",
        api_key="sk-test",
        temperature=0.7,
    )


@pytest.fixture
def ollama_config():
    return LLMConfig(
        provider="ollama",
        model="llama3.2",
        base_url="http://127.0.0.1:11434",
        temperature=0.5,
    )


@pytest.fixture
def mock_config():
    return LLMConfig(
        provider="mock",
        model="mock-model",
        base_url="http://localhost",
        temperature=0.7,
    )


@pytest.fixture
def enterprise_config():
    return LLMConfig(
        gateway_mode="enterprise",
        provider="enterprise",
        model="gpt-4o",
        base_url="https://llm-gateway.internal/modelgw/models/openai/v1",
        auth_method="bearer",
        client_id="enterprise-client",
        client_secret="enterprise-secret",
        token_endpoint_url="https://auth.internal/v2/oauth/token",
        temperature=0.2,
    )


_OPENAI_RESPONSE = {
    "choices": [
        {
            "message": {"role": "assistant", "content": "Hello!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
}

_OLLAMA_RESPONSE = {
    "message": {"role": "assistant", "content": "Hi there!"},
    "done": True,
    "prompt_eval_count": 5,
    "eval_count": 4,
}

_OLLAMA_TOOL_RESPONSE = {
    "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "svc__ping", "arguments": {"host": "x"}}}
        ],
    },
    "done": True,
    "prompt_eval_count": 5,
    "eval_count": 4,
}


# ============================================================================
# TR-LLMC-1: OpenAIClient
# ============================================================================

class TestOpenAIClient:

    def test_timeout_uses_configured_llm_timeout(self, openai_config):
        """TC-LLMC-00: Base client timeout derives from llm_timeout_ms and llm_connect_timeout_ms."""
        openai_config.llm_timeout_ms = 180000
        openai_config.llm_connect_timeout_ms = 30000  # default
        client = OpenAIClient(openai_config)
        assert client.timeout.read == 180.0
        assert client.timeout.connect == 30.0   # now driven by llm_connect_timeout_ms
        assert client.timeout.write == 30.0

    def test_connect_timeout_is_independent_of_read_timeout(self, openai_config):
        """TC-LLMC-00b: llm_connect_timeout_ms controls connect independently of llm_timeout_ms."""
        openai_config.llm_timeout_ms = 180000
        openai_config.llm_connect_timeout_ms = 60000
        client = OpenAIClient(openai_config)
        assert client.timeout.read == 180.0
        assert client.timeout.connect == 60.0  # independent of read

    def test_connect_timeout_default_is_30s(self, openai_config):
        """TC-LLMC-00c: Default llm_connect_timeout_ms yields a 30s connect timeout."""
        from backend.models import LLMConfig
        cfg = LLMConfig(provider="openai", model="gpt-4o", base_url="https://api.openai.com")
        client = OpenAIClient(cfg)
        assert client.timeout.connect == 30.0

    @respx.mock
    @pytest.mark.asyncio
    async def test_successful_completion(self, openai_config):
        """TC-LLMC-01: Successful response returns parsed dict."""
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        client = OpenAIClient(openai_config)
        result = await client.chat_completion([{"role": "user", "content": "hi"}], [])
        assert result["choices"][0]["message"]["role"] == "assistant"

    @respx.mock
    @pytest.mark.asyncio
    async def test_tools_included_in_payload(self, openai_config):
        """TC-LLMC-02: Tools list included with tool_choice=auto and parallel_tool_calls=True."""
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        client = OpenAIClient(openai_config)
        tools = [{"type": "function", "function": {"name": "ping"}}]
        await client.chat_completion([{"role": "user", "content": "hi"}], tools)
        body = route.calls.last.request.read()
        import json
        payload = json.loads(body)
        assert "tools" in payload
        assert payload["tool_choice"] == "auto"
        assert payload["parallel_tool_calls"] is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_parallel_tool_calls_absent_when_no_tools(self, openai_config):
        """TC-LLMC-02a: parallel_tool_calls not sent when tools list is empty."""
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        client = OpenAIClient(openai_config)
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        import json
        payload = json.loads(route.calls.last.request.read())
        assert "parallel_tool_calls" not in payload

    @respx.mock
    @pytest.mark.asyncio
    async def test_no_tools_key_when_empty(self, openai_config):
        """TC-LLMC-03: tools key omitted when tools list is empty."""
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        client = OpenAIClient(openai_config)
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        import json
        payload = json.loads(route.calls.last.request.read())
        assert "tools" not in payload

    @respx.mock
    @pytest.mark.asyncio
    async def test_max_tokens_included(self, openai_config):
        """TC-LLMC-04: max_tokens sent when set in config."""
        openai_config.max_tokens = 500
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        client = OpenAIClient(openai_config)
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        import json
        payload = json.loads(route.calls.last.request.read())
        assert payload["max_tokens"] == 500

    @respx.mock
    @pytest.mark.asyncio
    async def test_max_tokens_omitted_when_none(self, openai_config):
        """TC-LLMC-05: max_tokens absent when config.max_tokens is None."""
        openai_config.max_tokens = None
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        client = OpenAIClient(openai_config)
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        import json
        payload = json.loads(route.calls.last.request.read())
        assert "max_tokens" not in payload

    @respx.mock
    @pytest.mark.asyncio
    async def test_stream_false_included(self, openai_config):
        """TC-LLMC-05a: OpenAI-compatible requests set stream=false."""
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        client = OpenAIClient(openai_config)
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        import json
        payload = json.loads(route.calls.last.request.read())
        assert payload["stream"] is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_422_retries_without_parallel_tool_fields(self, openai_config):
        """TC-LLMC-05b: 422 retries strip strict compatibility fields for OpenAI-compatible gateways."""
        call_payloads = []

        def capture(request):
            import json
            payload = json.loads(request.content)
            call_payloads.append(payload)
            if len(call_payloads) == 1:
                return httpx.Response(422, json={"detail": "parallel_tool_calls not permitted"})
            return httpx.Response(200, json=_OPENAI_RESPONSE)

        respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=capture)
        client = OpenAIClient(openai_config)
        tools = [{"type": "function", "function": {"name": "ping"}}]

        result = await client.chat_completion([{"role": "user", "content": "hi"}], tools)

        assert result["choices"][0]["message"]["role"] == "assistant"
        assert len(call_payloads) == 2
        assert call_payloads[0]["parallel_tool_calls"] is True
        assert "parallel_tool_calls" not in call_payloads[1]
        assert call_payloads[1]["tool_choice"] == "auto"

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_raises_exception(self, openai_config):
        """TC-LLMC-06: TimeoutException mapped to Exception('LLM request timeout')."""
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        client = OpenAIClient(openai_config)
        with pytest.raises(Exception, match="LLM request timeout"):
            await client.chat_completion([{"role": "user", "content": "hi"}], [])

    @respx.mock
    @pytest.mark.asyncio
    async def test_http_500_raises_exception(self, openai_config):
        """TC-LLMC-07: HTTP 500 raises Exception."""
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(500, text="Server Error")
        )
        client = OpenAIClient(openai_config)
        with pytest.raises(Exception):
            await client.chat_completion([{"role": "user", "content": "hi"}], [])

    @respx.mock
    @pytest.mark.asyncio
    async def test_url_construction(self, openai_config):
        """TC-LLMC-08: Request sent to {base_url}/v1/chat/completions."""
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        client = OpenAIClient(openai_config)
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_auth_header(self, openai_config):
        """TC-LLMC-09: Authorization: Bearer {api_key} header sent."""
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        client = OpenAIClient(openai_config)
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        auth = route.calls.last.request.headers["authorization"]
        assert auth == "Bearer sk-test"

    def test_format_tool_result(self, openai_config):
        """TC-LLMC-10: OpenAI format_tool_result includes tool_call_id."""
        client = OpenAIClient(openai_config)
        result = client.format_tool_result("call_1", "pong")
        assert result == {"role": "tool", "tool_call_id": "call_1", "content": "pong"}


# ============================================================================
# TR-LLMC-2: OllamaClient
# ============================================================================

class TestOllamaClient:

    @respx.mock
    @pytest.mark.asyncio
    async def test_response_normalized(self, ollama_config):
        """TC-LLMC-11: Ollama response normalized to OpenAI choices format."""
        respx.post("http://127.0.0.1:11434/api/chat").mock(
            return_value=httpx.Response(200, json=_OLLAMA_RESPONSE)
        )
        client = OllamaClient(ollama_config)
        result = await client.chat_completion([{"role": "user", "content": "hi"}], [])
        assert "choices" in result
        assert result["choices"][0]["message"]["role"] == "assistant"

    @respx.mock
    @pytest.mark.asyncio
    async def test_done_true_maps_to_stop(self, ollama_config):
        """TC-LLMC-12: Ollama done=true → finish_reason='stop'."""
        respx.post("http://127.0.0.1:11434/api/chat").mock(
            return_value=httpx.Response(200, json=_OLLAMA_RESPONSE)
        )
        client = OllamaClient(ollama_config)
        result = await client.chat_completion([{"role": "user", "content": "hi"}], [])
        assert result["choices"][0]["finish_reason"] == "stop"

    @respx.mock
    @pytest.mark.asyncio
    async def test_tool_calls_detected(self, ollama_config):
        """TC-LLMC-13: Ollama tool_calls in message → finish_reason='tool_calls'."""
        respx.post("http://127.0.0.1:11434/api/chat").mock(
            return_value=httpx.Response(200, json=_OLLAMA_TOOL_RESPONSE)
        )
        client = OllamaClient(ollama_config)
        result = await client.chat_completion([{"role": "user", "content": "hi"}], [])
        assert result["choices"][0]["finish_reason"] == "tool_calls"

    @respx.mock
    @pytest.mark.asyncio
    async def test_url_construction(self, ollama_config):
        """TC-LLMC-14: Request sent to {base_url}/api/chat."""
        route = respx.post("http://127.0.0.1:11434/api/chat").mock(
            return_value=httpx.Response(200, json=_OLLAMA_RESPONSE)
        )
        client = OllamaClient(ollama_config)
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_no_authorization_header(self, ollama_config):
        """TC-LLMC-15: Ollama requests have no Authorization header."""
        route = respx.post("http://127.0.0.1:11434/api/chat").mock(
            return_value=httpx.Response(200, json=_OLLAMA_RESPONSE)
        )
        client = OllamaClient(ollama_config)
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        headers = route.calls.last.request.headers
        assert "authorization" not in headers

    def test_format_tool_result_no_tool_call_id(self, ollama_config):
        """TC-LLMC-16: Ollama format_tool_result omits tool_call_id."""
        client = OllamaClient(ollama_config)
        result = client.format_tool_result("call_1", "pong")
        assert result == {"role": "tool", "content": "pong"}
        assert "tool_call_id" not in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_stream_false_in_payload(self, ollama_config):
        """TC-LLMC-17: Payload always contains stream: false."""
        route = respx.post("http://127.0.0.1:11434/api/chat").mock(
            return_value=httpx.Response(200, json=_OLLAMA_RESPONSE)
        )
        client = OllamaClient(ollama_config)
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        import json
        payload = json.loads(route.calls.last.request.read())
        assert payload["stream"] is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_raises_exception(self, ollama_config):
        """TC-LLMC-18: Timeout maps to Exception('LLM request timeout')."""
        respx.post("http://127.0.0.1:11434/api/chat").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        client = OllamaClient(ollama_config)
        with pytest.raises(Exception, match="LLM request timeout"):
            await client.chat_completion([{"role": "user", "content": "hi"}], [])

    @respx.mock
    @pytest.mark.asyncio
    async def test_read_timeout_includes_phase_and_duration(self, ollama_config):
        """TC-LLMC-18b: Read timeout includes phase and configured timeout in the surfaced error."""
        ollama_config.llm_timeout_ms = 42000
        respx.post("http://127.0.0.1:11434/api/chat").mock(
            side_effect=httpx.ReadTimeout("read timed out")
        )
        client = OllamaClient(ollama_config)
        with pytest.raises(Exception, match=r"read timeout after 42\.0s"):
            await client.chat_completion([{"role": "user", "content": "hi"}], [])

    @respx.mock
    @pytest.mark.asyncio
    async def test_http_400_raises_exception(self, ollama_config):
        """TC-LLMC-19: HTTP 400 raises Exception."""
        respx.post("http://127.0.0.1:11434/api/chat").mock(
            return_value=httpx.Response(400, text="Bad Request")
        )
        client = OllamaClient(ollama_config)
        with pytest.raises(Exception):
            await client.chat_completion([{"role": "user", "content": "hi"}], [])


# ============================================================================
# TR-LLMC-3: MockLLMClient
# ============================================================================

class TestMockLLMClient:

    @pytest.mark.asyncio
    async def test_returns_assistant_response(self, mock_config):
        """TC-LLMC-20: Mock returns assistant message."""
        client = MockLLMClient(mock_config)
        result = await client.chat_completion([{"role": "user", "content": "hi"}], [])
        assert result["choices"][0]["message"]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_finish_reason_stop(self, mock_config):
        """TC-LLMC-21: Mock always returns finish_reason='stop'."""
        client = MockLLMClient(mock_config)
        result = await client.chat_completion([], [])
        assert result["choices"][0]["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_no_http_calls(self, mock_config):
        """TC-LLMC-22: Mock makes no outbound HTTP requests."""
        with respx.mock(assert_all_mocked=False) as rx:
            client = MockLLMClient(mock_config)
            await client.chat_completion([{"role": "user", "content": "hi"}], [])
            assert len(rx.calls) == 0


# ============================================================================
# TR-LLMC-4: EnterpriseLLMClient
# ============================================================================

class TestEnterpriseLLMClient:

    @respx.mock
    @pytest.mark.asyncio
    async def test_successful_completion(self, enterprise_config):
        """TC-LLMC-23: Enterprise response returns parsed dict."""
        respx.post("https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        result = await client.chat_completion([{"role": "user", "content": "hi"}], [])
        assert result["choices"][0]["message"]["role"] == "assistant"

    @respx.mock
    @pytest.mark.asyncio
    async def test_bearer_auth_header(self, enterprise_config):
        """TC-LLMC-24: Enterprise requests use cached bearer token."""
        route = respx.post("https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
        )
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        assert route.calls.last.request.headers["authorization"] == "Bearer enterprise-token"

    @respx.mock
    @pytest.mark.asyncio
    async def test_url_construction(self, enterprise_config):
        """TC-LLMC-29: Request sent to {base_url}/chat/completions (NOT /v1/chat/completions)."""
        route = respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions"
        ).mock(return_value=httpx.Response(200, json=_OPENAI_RESPONSE))
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        assert route.called
        assert "/v1/chat/completions" in str(route.calls.last.request.url)
        # Enterprise appends /chat/completions directly to base_url, not /v1/
        assert "/modelgw/models/openai/v1/chat/completions" in str(route.calls.last.request.url)

    @respx.mock
    @pytest.mark.asyncio
    async def test_tools_included_in_payload(self, enterprise_config):
        """TC-LLMC-30: Tools list included with tool_choice=auto and parallel_tool_calls=True."""
        route = respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions"
        ).mock(return_value=httpx.Response(200, json=_OPENAI_RESPONSE))
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        tools = [{"type": "function", "function": {"name": "ping"}}]
        await client.chat_completion([{"role": "user", "content": "hi"}], tools)
        import json
        payload = json.loads(route.calls.last.request.read())
        assert "tools" in payload
        assert payload["tool_choice"] == "auto"
        assert payload["parallel_tool_calls"] is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_parallel_tool_calls_absent_when_no_tools(self, enterprise_config):
        """TC-LLMC-30a: parallel_tool_calls not sent when tools list is empty."""
        route = respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions"
        ).mock(return_value=httpx.Response(200, json=_OPENAI_RESPONSE))
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        import json
        payload = json.loads(route.calls.last.request.read())
        assert "parallel_tool_calls" not in payload

    @respx.mock
    @pytest.mark.asyncio
    async def test_no_tools_key_when_empty(self, enterprise_config):
        """TC-LLMC-31: tools key omitted when tools list is empty."""
        route = respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions"
        ).mock(return_value=httpx.Response(200, json=_OPENAI_RESPONSE))
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        import json
        payload = json.loads(route.calls.last.request.read())
        assert "tools" not in payload

    @respx.mock
    @pytest.mark.asyncio
    async def test_max_tokens_included(self, enterprise_config):
        """TC-LLMC-32: max_tokens sent when set in config."""
        enterprise_config.max_tokens = 1000
        route = respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions"
        ).mock(return_value=httpx.Response(200, json=_OPENAI_RESPONSE))
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        import json
        payload = json.loads(route.calls.last.request.read())
        assert payload["max_tokens"] == 1000

    @respx.mock
    @pytest.mark.asyncio
    async def test_max_tokens_omitted_when_none(self, enterprise_config):
        """TC-LLMC-33: max_tokens absent when config.max_tokens is None."""
        enterprise_config.max_tokens = None
        route = respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions"
        ).mock(return_value=httpx.Response(200, json=_OPENAI_RESPONSE))
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        import json
        payload = json.loads(route.calls.last.request.read())
        assert "max_tokens" not in payload

    @respx.mock
    @pytest.mark.asyncio
    async def test_stream_false_included(self, enterprise_config):
        """TC-LLMC-33a: Enterprise gateway requests set stream=false."""
        route = respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions"
        ).mock(return_value=httpx.Response(200, json=_OPENAI_RESPONSE))
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        await client.chat_completion([{"role": "user", "content": "hi"}], [])
        import json
        payload = json.loads(route.calls.last.request.read())
        assert payload["stream"] is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_422_retries_without_parallel_tool_fields(self, enterprise_config):
        """TC-LLMC-33b: Enterprise gateway retries without strict tool compatibility fields on 422."""
        call_payloads = []

        def capture(request):
            import json
            payload = json.loads(request.content)
            call_payloads.append(payload)
            if len(call_payloads) == 1:
                return httpx.Response(422, json={"detail": "parallel_tool_calls not permitted"})
            return httpx.Response(200, json=_OPENAI_RESPONSE)

        respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions"
        ).mock(side_effect=capture)
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        tools = [{"type": "function", "function": {"name": "ping"}}]

        result = await client.chat_completion([{"role": "user", "content": "hi"}], tools)

        assert result["choices"][0]["message"]["role"] == "assistant"
        assert len(call_payloads) == 2
        assert call_payloads[0]["parallel_tool_calls"] is True
        assert "parallel_tool_calls" not in call_payloads[1]
        assert call_payloads[1]["tool_choice"] == "auto"

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_raises_exception(self, enterprise_config):
        """TC-LLMC-34: TimeoutException mapped to Exception('LLM request timeout')."""
        respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions"
        ).mock(side_effect=httpx.TimeoutException("timed out"))
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        with pytest.raises(Exception, match="LLM request timeout"):
            await client.chat_completion([{"role": "user", "content": "hi"}], [])

    @respx.mock
    @pytest.mark.asyncio
    async def test_http_500_raises_exception(self, enterprise_config):
        """TC-LLMC-35: HTTP 500 raises Exception."""
        respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions"
        ).mock(return_value=httpx.Response(500, text="Server Error"))
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        with pytest.raises(Exception):
            await client.chat_completion([{"role": "user", "content": "hi"}], [])

    def test_format_tool_result(self, enterprise_config):
        """TC-LLMC-36: Enterprise format_tool_result uses OpenAI-compatible tool_call_id."""
        client = EnterpriseLLMClient(enterprise_config, "enterprise-token")
        result = client.format_tool_result("call_1", "pong")
        assert result == {"role": "tool", "tool_call_id": "call_1", "content": "pong"}


# ============================================================================
# TR-LLMC-5: LLMClientFactory
# ============================================================================

class TestLLMClientFactory:

    def test_openai_factory(self):
        """TC-LLMC-37: provider='openai' returns OpenAIClient."""
        cfg = LLMConfig(provider="openai", model="gpt-4o", base_url="https://api.openai.com")
        assert isinstance(LLMClientFactory.create(cfg), OpenAIClient)

    def test_ollama_factory(self):
        """TC-LLMC-38: provider='ollama' returns OllamaClient."""
        cfg = LLMConfig(provider="ollama", model="llama3", base_url="http://localhost:11434")
        assert isinstance(LLMClientFactory.create(cfg), OllamaClient)

    def test_mock_factory(self):
        """TC-LLMC-39: provider='mock' returns MockLLMClient."""
        cfg = LLMConfig(provider="mock", model="mock", base_url="http://localhost")
        assert isinstance(LLMClientFactory.create(cfg), MockLLMClient)

    def test_enterprise_factory_requires_token(self, enterprise_config):
        """TC-LLMC-40: enterprise provider requires cached token."""
        with pytest.raises(ValueError, match="cached access token"):
            LLMClientFactory.create(enterprise_config)

    def test_enterprise_factory(self, enterprise_config):
        """TC-LLMC-41: provider='enterprise' returns EnterpriseLLMClient."""
        assert isinstance(
            LLMClientFactory.create(enterprise_config, enterprise_access_token="enterprise-token"),
            EnterpriseLLMClient,
        )

    def test_unknown_provider_raises_value_error(self):
        """TC-LLMC-42: Unknown provider raises ValueError."""
        # Bypass Pydantic validation with a direct config mutation
        cfg = LLMConfig(provider="mock", model="m", base_url="http://localhost")
        object.__setattr__(cfg, "provider", "unknown")
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            LLMClientFactory.create(cfg)
