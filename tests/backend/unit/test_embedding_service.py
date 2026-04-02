"""Unit tests for provider-agnostic embedding support (TR-EMB-*)."""

import httpx
import pytest
import respx

from backend.embedding_service import (
    EmbeddingConfigurationError,
    EmbeddingDimensionError,
    EmbeddingProviderError,
    EmbeddingService,
)
from backend.models import LLMConfig


@pytest.fixture
def openai_config():
    return LLMConfig(
        provider="openai",
        model="text-embedding-3-small",
        base_url="https://api.openai.com",
        api_key="sk-test",
        temperature=0.0,
    )


@pytest.fixture
def ollama_config():
    return LLMConfig(
        provider="ollama",
        model="nomic-embed-text",
        base_url="http://127.0.0.1:11434",
        temperature=0.0,
    )


@pytest.fixture
def mock_config():
    return LLMConfig(
        provider="mock",
        model="mock-embedding-model",
        base_url="http://localhost",
        temperature=0.0,
    )


@pytest.fixture
def enterprise_config():
    return LLMConfig(
        gateway_mode="enterprise",
        provider="enterprise",
        model="text-embedding-3-small",
        base_url="https://llm-gateway.internal/modelgw/models/openai/v1",
        auth_method="bearer",
        client_id="enterprise-client",
        client_secret="enterprise-secret",
        token_endpoint_url="https://auth.internal/v2/oauth/token",
        temperature=0.0,
    )


_OPENAI_EMBED_RESPONSE = {
    "data": [
        {"index": 0, "embedding": [0.1, 0.2, 0.3]},
        {"index": 1, "embedding": [0.4, 0.5, 0.6]},
    ]
}

_OLLAMA_EMBED_RESPONSE = {
    "embeddings": [
        [0.11, 0.22, 0.33, 0.44],
        [0.55, 0.66, 0.77, 0.88],
    ]
}


class TestEmbeddingService:

    @respx.mock
    @pytest.mark.asyncio
    async def test_openai_embeddings_are_normalized(self, openai_config):
        """TR-EMB-01: OpenAI embeddings return a normalized result with preserved order."""
        route = respx.post("https://api.openai.com/v1/embeddings").mock(
            return_value=httpx.Response(200, json=_OPENAI_EMBED_RESPONSE)
        )

        service = EmbeddingService(openai_config)
        result = await service.embed_texts(["alpha", "beta"])

        assert route.called
        assert result.provider == "openai"
        assert result.model == "text-embedding-3-small"
        assert result.dimensions == 3
        assert result.input_count == 2
        assert result.vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

        payload = route.calls.last.request.read().decode("utf-8")
        assert '"model": "text-embedding-3-small"' in payload
        assert '"input": ["alpha", "beta"]' in payload
        assert route.calls.last.request.headers["authorization"] == "Bearer sk-test"

    @pytest.mark.asyncio
    async def test_openai_requires_api_key(self, openai_config):
        """TR-EMB-02: OpenAI embedding requests fail fast without an API key."""
        openai_config.api_key = None
        service = EmbeddingService(openai_config)

        with pytest.raises(EmbeddingConfigurationError, match="requires api_key"):
            await service.embed_texts(["alpha"])

    @respx.mock
    @pytest.mark.asyncio
    async def test_ollama_embeddings_are_normalized(self, ollama_config):
        """TR-EMB-03: Ollama embeddings normalize multi-vector responses."""
        route = respx.post("http://127.0.0.1:11434/api/embed").mock(
            return_value=httpx.Response(200, json=_OLLAMA_EMBED_RESPONSE)
        )

        service = EmbeddingService(ollama_config)
        result = await service.embed_texts(["alpha", "beta"])

        assert route.called
        assert result.provider == "ollama"
        assert result.dimensions == 4
        assert result.vectors[0] == [0.11, 0.22, 0.33, 0.44]
        assert result.vectors[1] == [0.55, 0.66, 0.77, 0.88]
        assert "authorization" not in route.calls.last.request.headers

    @pytest.mark.asyncio
    async def test_mock_embeddings_are_deterministic_without_http(self, mock_config):
        """TR-EMB-04: Mock provider returns deterministic vectors and makes no HTTP calls."""
        service = EmbeddingService(mock_config)

        with respx.mock(assert_all_mocked=False) as router:
            result_one = await service.embed_texts(["alpha", "beta"])
            result_two = await service.embed_texts(["alpha", "beta"])

        assert len(router.calls) == 0
        assert result_one.dimensions == 8
        assert result_one.vectors == result_two.vectors
        assert result_one.vectors[0] != result_one.vectors[1]

    @respx.mock
    @pytest.mark.asyncio
    async def test_enterprise_embeddings_require_access_token(self, enterprise_config):
        """TR-EMB-05: Enterprise provider requires a cached access token."""
        service = EmbeddingService(enterprise_config)

        with pytest.raises(EmbeddingConfigurationError, match="cached access token"):
            await service.embed_texts(["alpha"])

    @respx.mock
    @pytest.mark.asyncio
    async def test_enterprise_embeddings_use_bearer_token(self, enterprise_config):
        """TR-EMB-06: Enterprise embeddings use the cached bearer token and OpenAI-like response normalization."""
        route = respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/embeddings"
        ).mock(return_value=httpx.Response(200, json={"data": [{"embedding": [1.0, 2.0]}]}))

        service = EmbeddingService(enterprise_config, enterprise_access_token="enterprise-token")
        result = await service.embed_texts(["alpha"])

        assert route.called
        assert result.vectors == [[1.0, 2.0]]
        assert route.calls.last.request.headers["authorization"] == "Bearer enterprise-token"

    @respx.mock
    @pytest.mark.asyncio
    async def test_dimension_mismatch_raises(self, openai_config):
        """TR-EMB-07: Expected dimension mismatches fail clearly."""
        respx.post("https://api.openai.com/v1/embeddings").mock(
            return_value=httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2, 0.3]}]})
        )

        service = EmbeddingService(openai_config)

        with pytest.raises(EmbeddingDimensionError, match="expected 4, received 3"):
            await service.embed_texts(["alpha"], expected_dimensions=4)

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_raises_provider_error_with_phase_and_duration(self, openai_config):
        """TR-EMB-08: Timeout errors surface phase-specific timeout details."""
        openai_config.llm_timeout_ms = 42000
        respx.post("https://api.openai.com/v1/embeddings").mock(
            side_effect=httpx.ReadTimeout("read timed out")
        )

        service = EmbeddingService(openai_config)

        with pytest.raises(EmbeddingProviderError, match=r"read timeout after 42\.0s"):
            await service.embed_texts(["alpha"])

    @pytest.mark.asyncio
    async def test_empty_input_rejected(self, mock_config):
        """TR-EMB-09: Empty input sequences are rejected explicitly."""
        service = EmbeddingService(mock_config)

        with pytest.raises(EmbeddingConfigurationError, match="must not be empty"):
            await service.embed_texts([])
