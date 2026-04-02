"""Provider-agnostic embedding generation for optional memory features."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import httpx

from backend.models import LLMConfig

logger_internal = logging.getLogger("mcp_client.internal")
logger_external = logging.getLogger("mcp_client.external")


class EmbeddingServiceError(Exception):
    """Base error for embedding-service failures."""


class EmbeddingConfigurationError(EmbeddingServiceError):
    """Raised when embedding configuration is incomplete or invalid."""


class EmbeddingProviderError(EmbeddingServiceError):
    """Raised when a provider request fails."""


class EmbeddingDimensionError(EmbeddingServiceError):
    """Raised when returned vectors do not match expected dimensions."""


@dataclass(frozen=True)
class EmbeddingResult:
    """Normalized embedding response returned by the service."""

    provider: str
    model: str
    dimensions: int
    vectors: List[List[float]]

    @property
    def input_count(self) -> int:
        return len(self.vectors)


class EmbeddingService:
    """Generate embeddings using a provider-normalized interface."""

    def __init__(self, config: LLMConfig, enterprise_access_token: Optional[str] = None):
        self.config = config
        self.enterprise_access_token = enterprise_access_token
        timeout_seconds = max(float(config.llm_timeout_ms) / 1000.0, 5.0)
        self.timeout = httpx.Timeout(
            connect=min(15.0, timeout_seconds),
            read=timeout_seconds,
            write=min(30.0, timeout_seconds),
            pool=5.0,
        )

    async def embed_texts(
        self,
        texts: Sequence[str] | str,
        *,
        expected_dimensions: Optional[int] = None,
    ) -> EmbeddingResult:
        """Return normalized embeddings for one or more texts."""
        normalized_texts = self._normalize_inputs(texts)

        if self.config.provider == "openai":
            vectors = await self._embed_openai(normalized_texts)
        elif self.config.provider == "ollama":
            vectors = await self._embed_ollama(normalized_texts)
        elif self.config.provider == "enterprise":
            vectors = await self._embed_enterprise(normalized_texts)
        elif self.config.provider == "mock":
            vectors = self._embed_mock(normalized_texts)
        else:
            raise EmbeddingConfigurationError(
                f"Unsupported embedding provider: {self.config.provider}"
            )

        dimensions = self._validate_vectors(vectors, expected_dimensions=expected_dimensions)

        return EmbeddingResult(
            provider=self.config.provider,
            model=self.config.model,
            dimensions=dimensions,
            vectors=vectors,
        )

    def _normalize_inputs(self, texts: Sequence[str] | str) -> List[str]:
        if isinstance(texts, str):
            normalized_texts = [texts]
        else:
            normalized_texts = list(texts)

        if not normalized_texts:
            raise EmbeddingConfigurationError("Embedding input texts must not be empty")

        invalid_items = [item for item in normalized_texts if not isinstance(item, str)]
        if invalid_items:
            raise EmbeddingConfigurationError("Embedding input texts must all be strings")

        return normalized_texts

    def _estimate_payload_bytes(self, payload: Dict[str, Any]) -> int:
        try:
            return len(json.dumps(payload, default=str).encode("utf-8"))
        except Exception:
            return -1

    def _timeout_phase(self, error: httpx.TimeoutException) -> str:
        if isinstance(error, httpx.ConnectTimeout):
            return "connect"
        if isinstance(error, httpx.ReadTimeout):
            return "read"
        if isinstance(error, httpx.WriteTimeout):
            return "write"
        if isinstance(error, httpx.PoolTimeout):
            return "pool"
        return "request"

    def _timeout_seconds_for_phase(self, phase: str) -> float:
        if phase == "connect":
            return float(self.timeout.connect)
        if phase == "write":
            return float(self.timeout.write)
        if phase == "pool":
            return float(self.timeout.pool)
        return float(self.timeout.read)

    def _format_timeout_error(self, error: httpx.TimeoutException) -> str:
        phase = self._timeout_phase(error)
        timeout_seconds = self._timeout_seconds_for_phase(phase)
        return f"Embedding request timeout ({phase} timeout after {timeout_seconds:.1f}s)"

    def _log_timeout(
        self,
        provider_name: str,
        url: str,
        error: httpx.TimeoutException,
        payload_bytes: int,
        input_count: int,
    ) -> None:
        phase = self._timeout_phase(error)
        timeout_seconds = self._timeout_seconds_for_phase(phase)
        logger_internal.error(
            "%s timeout: phase=%s timeout_s=%.1f model=%s url=%s inputs=%s payload_bytes=%s raw_error=%r",
            provider_name,
            phase,
            timeout_seconds,
            self.config.model,
            url,
            input_count,
            payload_bytes,
            error,
        )

    async def _post_embeddings_request(
        self,
        *,
        provider_name: str,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload_bytes = self._estimate_payload_bytes(payload)
        input_count = len(payload.get("input", [])) if isinstance(payload.get("input"), list) else 1

        try:
            logger_external.info(f"→ POST {url} ({provider_name})")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                result = response.json()
            logger_external.info(f"← {response.status_code} ({provider_name} response)")
            return result
        except httpx.TimeoutException as error:
            self._log_timeout(provider_name, url, error, payload_bytes, input_count)
            raise EmbeddingProviderError(self._format_timeout_error(error))
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code if error.response is not None else None
            response_body = error.response.text[:2000] if error.response is not None else ""
            logger_internal.error(
                "%s HTTP error: status=%s body=%s error=%s",
                provider_name,
                status_code,
                response_body,
                error,
            )
            raise EmbeddingProviderError(f"Embedding HTTP error: {str(error)}")
        except httpx.HTTPError as error:
            logger_internal.error("%s HTTP error: %s", provider_name, error)
            raise EmbeddingProviderError(f"Embedding HTTP error: {str(error)}")

    async def _embed_openai(self, texts: List[str]) -> List[List[float]]:
        if not self.config.api_key:
            raise EmbeddingConfigurationError("OpenAI embedding provider requires api_key")

        url = f"{self.config.base_url.rstrip('/')}/v1/embeddings"
        payload = {
            "model": self.config.model,
            "input": texts,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

        result = await self._post_embeddings_request(
            provider_name="OpenAI embeddings",
            url=url,
            headers=headers,
            payload=payload,
        )
        return self._extract_openai_vectors(result)

    async def _embed_enterprise(self, texts: List[str]) -> List[List[float]]:
        if not self.enterprise_access_token:
            raise EmbeddingConfigurationError(
                "Enterprise embedding provider requires a cached access token"
            )

        url = f"{self.config.base_url.rstrip('/')}/embeddings"
        payload = {
            "model": self.config.model,
            "input": texts,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.enterprise_access_token}",
        }

        result = await self._post_embeddings_request(
            provider_name="Enterprise embeddings",
            url=url,
            headers=headers,
            payload=payload,
        )
        return self._extract_openai_vectors(result)

    async def _embed_ollama(self, texts: List[str]) -> List[List[float]]:
        url = f"{self.config.base_url.rstrip('/')}/api/embed"
        payload = {
            "model": self.config.model,
            "input": texts,
        }
        headers = {"Content-Type": "application/json"}

        result = await self._post_embeddings_request(
            provider_name="Ollama embeddings",
            url=url,
            headers=headers,
            payload=payload,
        )
        return self._extract_ollama_vectors(result)

    def _embed_mock(self, texts: List[str]) -> List[List[float]]:
        logger_internal.info("Mock embedding service: generating deterministic vectors")
        return [self._mock_vector(text) for text in texts]

    def _extract_openai_vectors(self, result: Dict[str, Any]) -> List[List[float]]:
        data = result.get("data")
        if not isinstance(data, list):
            raise EmbeddingProviderError("Embedding provider returned invalid response shape")

        vectors: List[List[float]] = []
        for item in data:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if embedding is None:
                raise EmbeddingProviderError("Embedding provider returned missing embedding data")
            vectors.append(self._coerce_vector(embedding))
        return vectors

    def _extract_ollama_vectors(self, result: Dict[str, Any]) -> List[List[float]]:
        if isinstance(result.get("embeddings"), list):
            return [self._coerce_vector(vector) for vector in result["embeddings"]]
        if isinstance(result.get("embedding"), list):
            return [self._coerce_vector(result["embedding"])]
        raise EmbeddingProviderError("Embedding provider returned invalid response shape")

    def _coerce_vector(self, vector: Any) -> List[float]:
        if not isinstance(vector, list) or not vector:
            raise EmbeddingProviderError("Embedding provider returned an empty or invalid vector")
        try:
            return [float(value) for value in vector]
        except (TypeError, ValueError) as error:
            raise EmbeddingProviderError("Embedding provider returned non-numeric vector values") from error

    def _validate_vectors(
        self,
        vectors: List[List[float]],
        *,
        expected_dimensions: Optional[int],
    ) -> int:
        if not vectors:
            raise EmbeddingProviderError("Embedding provider returned no vectors")

        dimensions = len(vectors[0])
        if dimensions == 0:
            raise EmbeddingProviderError("Embedding provider returned an empty vector")

        for index, vector in enumerate(vectors[1:], start=1):
            if len(vector) != dimensions:
                raise EmbeddingDimensionError(
                    f"Embedding vector at index {index} has dimension {len(vector)}; expected {dimensions}"
                )

        if expected_dimensions is not None and dimensions != expected_dimensions:
            raise EmbeddingDimensionError(
                f"Embedding dimension mismatch: expected {expected_dimensions}, received {dimensions}"
            )

        return dimensions

    def _mock_vector(self, text: str, dimensions: int = 8) -> List[float]:
        vector: List[float] = []
        seed = text.encode("utf-8")
        for index in range(dimensions):
            digest = hashlib.sha256(seed + f":{index}".encode("utf-8")).digest()
            value = int.from_bytes(digest[:4], "big") / 4294967295.0
            vector.append(round(value, 6))
        return vector
