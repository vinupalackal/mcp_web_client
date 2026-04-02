"""
LLM Client - Adapters for OpenAI, Ollama, and Mock providers
Handles chat completions with function calling support
"""

import logging
import os
import json
import httpx
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from backend.models import LLMConfig, ChatMessage, ToolCall

logger_internal = logging.getLogger("mcp_client.internal")
logger_external = logging.getLogger("mcp_client.external")


def _transaction_label(target: str, operation: str) -> str:
    return f"******* MCP CLIENT to {target.upper()} {operation.upper()} TRANSACTION ******"


def _log_transaction_banner(target: str, operation: str, state: str) -> None:
    logger_external.info("%s %s", _transaction_label(target, operation), state.upper())


def _log_transaction_detail(logger: logging.Logger, message: str, *args: Any) -> None:
    logger.info(f"  {message}", *args)


class BaseLLMClient(ABC):
    """Base class for LLM providers"""
    
    def __init__(self, config: LLMConfig):
        self.config = config
        timeout_seconds = max(float(config.llm_timeout_ms) / 1000.0, 5.0)
        self.timeout = httpx.Timeout(
            connect=min(15.0, timeout_seconds),
            read=timeout_seconds,
            write=min(30.0, timeout_seconds),
            pool=5.0,
        )

    def _estimate_payload_bytes(self, payload: Dict[str, Any]) -> int:
        """Estimate payload size for diagnostics without changing request behavior."""
        try:
            return len(json.dumps(payload, default=str).encode("utf-8"))
        except Exception:
            return -1

    def _build_openai_compatible_payload(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        *,
        include_stream: bool,
        include_tool_choice: bool = True,
        include_parallel_tool_calls: bool = True,
    ) -> Dict[str, Any]:
        """Build a chat/completions payload shared by OpenAI-compatible providers."""
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }

        if include_stream:
            payload["stream"] = False

        if tools:
            payload["tools"] = tools
            if include_tool_choice:
                payload["tool_choice"] = "auto"
            if include_parallel_tool_calls:
                payload["parallel_tool_calls"] = True

        if self.config.max_tokens is not None:
            payload["max_tokens"] = self.config.max_tokens

        return payload

    async def _post_openai_compatible_with_fallback(
        self,
        *,
        provider_name: str,
        url: str,
        headers: Dict[str, str],
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        include_stream: bool,
    ) -> Dict[str, Any]:
        """Send an OpenAI-compatible request and retry once on strict 422 validation errors."""
        payload_variants = [
            (
                self._build_openai_compatible_payload(
                    messages,
                    tools,
                    include_stream=include_stream,
                ),
                [],
            )
        ]

        if tools:
            payload_variants.append(
                (
                    self._build_openai_compatible_payload(
                        messages,
                        tools,
                        include_stream=include_stream,
                        include_parallel_tool_calls=False,
                    ),
                    ["parallel_tool_calls"],
                )
            )
            payload_variants.append(
                (
                    self._build_openai_compatible_payload(
                        messages,
                        tools,
                        include_stream=include_stream,
                        include_tool_choice=False,
                        include_parallel_tool_calls=False,
                    ),
                    ["parallel_tool_calls", "tool_choice"],
                )
            )

        for attempt_index, (payload, omitted_fields) in enumerate(payload_variants, start=1):
            payload_bytes = self._estimate_payload_bytes(payload)

            try:
                _log_transaction_banner(provider_name, "chat", "start")
                _log_transaction_detail(logger_external, "→ POST %s (%s chat)", url, provider_name)

                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    result = response.json()

                _log_transaction_detail(
                    logger_external,
                    "← %s (%s response)",
                    response.status_code,
                    provider_name,
                )
                _log_transaction_detail(
                    logger_internal,
                    "%s tokens: %s",
                    provider_name,
                    result.get('usage', {}),
                )
                _log_transaction_banner(provider_name, "chat", "end")

                if omitted_fields:
                    logger_internal.warning(
                        "  %s request succeeded after omitting compatibility fields: %s",
                        provider_name,
                        ", ".join(omitted_fields),
                    )

                return result

            except httpx.TimeoutException as e:
                self._log_timeout(provider_name, url, e, payload_bytes, len(messages), len(tools))
                _log_transaction_banner(provider_name, "chat", "failed")
                raise Exception(self._format_timeout_error(e))
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code if e.response is not None else None
                response_body = e.response.text[:2000] if e.response is not None else ""

                if status_code == 422 and attempt_index < len(payload_variants):
                    next_omitted_fields = payload_variants[attempt_index][1]
                    logger_internal.warning(
                        "  %s returned 422 for %s. body=%s. Retrying with reduced compatibility fields: %s",
                        provider_name,
                        url,
                        response_body,
                        ", ".join(next_omitted_fields) if next_omitted_fields else "none",
                    )
                    continue

                logger_internal.error(
                    "  %s HTTP error: status=%s body=%s error=%s",
                    provider_name,
                    status_code,
                    response_body,
                    e,
                )
                _log_transaction_banner(provider_name, "chat", "failed")
                raise Exception(f"LLM HTTP error: {str(e)}")
            except httpx.HTTPError as e:
                logger_internal.error("  %s HTTP error: %s", provider_name, e)
                _log_transaction_banner(provider_name, "chat", "failed")
                raise Exception(f"LLM HTTP error: {str(e)}")

        raise Exception("LLM HTTP error: request failed after compatibility retries")

    def _timeout_phase(self, error: httpx.TimeoutException) -> str:
        """Classify the specific timeout stage when possible."""
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
        """Return the configured timeout for the given stage."""
        if phase == "connect":
            return float(self.timeout.connect)
        if phase == "write":
            return float(self.timeout.write)
        if phase == "pool":
            return float(self.timeout.pool)
        return float(self.timeout.read)

    def _format_timeout_error(self, error: httpx.TimeoutException) -> str:
        """Create a stable, user-facing timeout error message."""
        phase = self._timeout_phase(error)
        timeout_seconds = self._timeout_seconds_for_phase(phase)
        return f"LLM request timeout ({phase} timeout after {timeout_seconds:.1f}s)"

    def _log_timeout(
        self,
        provider_name: str,
        url: str,
        error: httpx.TimeoutException,
        payload_bytes: int,
        messages_count: int,
        tools_count: int,
    ) -> None:
        """Emit actionable timeout diagnostics for operators."""
        phase = self._timeout_phase(error)
        timeout_seconds = self._timeout_seconds_for_phase(phase)
        logger_internal.error(
            "  %s timeout: phase=%s timeout_s=%.1f model=%s url=%s messages=%s tools=%s payload_bytes=%s raw_error=%r",
            provider_name,
            phase,
            timeout_seconds,
            self.config.model,
            url,
            messages_count,
            tools_count,
            payload_bytes,
            error,
        )
    
    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Send chat completion request with tools"""
        pass
    
    @abstractmethod
    def format_tool_result(
        self,
        tool_call_id: Optional[str],
        content: str
    ) -> Dict[str, Any]:
        """Format tool result message for this provider"""
        pass


class OpenAIClient(BaseLLMClient):
    """OpenAI API client"""
    
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Call OpenAI chat completions API"""

        url = f"{self.config.base_url.rstrip('/')}/v1/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}"
        }

        try:
            return await self._post_openai_compatible_with_fallback(
                provider_name="OpenAI",
                url=url,
                headers=headers,
                messages=messages,
                tools=tools,
                include_stream=True,
            )
        except Exception as e:
            logger_internal.error(f"OpenAI error: {e}")
            raise
    
    def format_tool_result(
        self,
        tool_call_id: Optional[str],
        content: str
    ) -> Dict[str, Any]:
        """Format tool result with tool_call_id (OpenAI format)"""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        }


class EnterpriseLLMClient(BaseLLMClient):
    """Enterprise gateway client using OpenAI-compatible chat completions."""

    def __init__(self, config: LLMConfig, access_token: str):
        super().__init__(config)
        self.access_token = access_token

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Call enterprise gateway chat completions API."""

        url = f"{self.config.base_url.rstrip('/')}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

        try:
            return await self._post_openai_compatible_with_fallback(
                provider_name="Enterprise gateway",
                url=url,
                headers=headers,
                messages=messages,
                tools=tools,
                include_stream=True,
            )
        except Exception as e:
            logger_internal.error(f"Enterprise gateway error: {e}")
            raise

    def format_tool_result(
        self,
        tool_call_id: Optional[str],
        content: str
    ) -> Dict[str, Any]:
        """Format tool result using OpenAI-compatible tool_call_id field."""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        }


class OllamaClient(BaseLLMClient):
    """Ollama API client"""
    
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Call Ollama chat API and normalize response to OpenAI format"""
        
        url = f"{self.config.base_url.rstrip('/')}/api/chat"
        
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.config.temperature
            }
        }
        
        if tools:
            payload["tools"] = tools
        
        headers = {"Content-Type": "application/json"}
        payload_bytes = self._estimate_payload_bytes(payload)
        
        try:
            _log_transaction_banner("Ollama", "chat", "start")
            _log_transaction_detail(logger_external, "→ POST %s (Ollama chat)", url)
            _log_transaction_detail(
                logger_internal,
                "Ollama payload: %s messages, %s tools, %s bytes",
                len(messages),
                len(tools),
                payload_bytes,
            )
            
            # Log each message for debugging
            for i, msg in enumerate(messages):
                _log_transaction_detail(
                    logger_internal,
                    "Message %s: role=%s, content_length=%s, has_tool_calls=%s, has_tool_call_id=%s",
                    i,
                    msg.get('role'),
                    len(str(msg.get('content', ''))),
                    'tool_calls' in msg,
                    'tool_call_id' in msg,
                )
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                ollama_result = response.json()
            
            _log_transaction_detail(logger_external, "← %s (Ollama response)", response.status_code)
            
            # Normalize Ollama response to OpenAI format
            # Ollama format: {"message": {...}, "done": true, ...}
            # OpenAI format: {"choices": [{"message": {...}, "finish_reason": "..."}], ...}
            
            normalized_result = {
                "choices": [{
                    "message": ollama_result.get("message", {}),
                    "finish_reason": "stop" if ollama_result.get("done") else "length"
                }],
                "usage": {
                    "prompt_tokens": ollama_result.get("prompt_eval_count", 0),
                    "completion_tokens": ollama_result.get("eval_count", 0),
                    "total_tokens": ollama_result.get("prompt_eval_count", 0) + ollama_result.get("eval_count", 0)
                }
            }
            
            # Check if Ollama returned tool calls
            message = ollama_result.get("message", {})
            if "tool_calls" in message:
                normalized_result["choices"][0]["finish_reason"] = "tool_calls"

            _log_transaction_detail(
                logger_internal,
                "Ollama tokens: %s",
                normalized_result.get("usage", {}),
            )
            _log_transaction_banner("Ollama", "chat", "end")
            
            return normalized_result
            
        except httpx.HTTPStatusError as e:
            logger_internal.error("  Ollama HTTP error: %s", e)
            logger_internal.error("  Request payload keys: %s", list(payload.keys()))
            logger_internal.error("  Number of messages: %s", len(messages))
            if messages:
                logger_internal.error("  Last message role: %s", messages[-1].get('role'))
                logger_internal.error("  Last message keys: %s", list(messages[-1].keys()))
                # Dump all messages for debugging
                for i, msg in enumerate(messages):
                    logger_internal.error("  Message %s: %s", i, msg)
            logger_internal.error("  Response status: %s", e.response.status_code)
            logger_internal.error("  Response body: %s", e.response.text)
            _log_transaction_banner("Ollama", "chat", "failed")
            raise Exception(f"LLM HTTP error: {str(e)}")
        except httpx.TimeoutException as e:
            self._log_timeout("Ollama", url, e, payload_bytes, len(messages), len(tools))
            _log_transaction_banner("Ollama", "chat", "failed")
            raise Exception(self._format_timeout_error(e))
        except httpx.HTTPError as e:
            logger_internal.error("  Ollama HTTP error: %s", e)
            _log_transaction_banner("Ollama", "chat", "failed")
            raise Exception(f"LLM HTTP error: {str(e)}")
        except Exception as e:
            logger_internal.error("  Ollama error: %s", e)
            _log_transaction_banner("Ollama", "chat", "failed")
            raise
    
    def format_tool_result(
        self,
        tool_call_id: Optional[str],
        content: str
    ) -> Dict[str, Any]:
        """Format tool result without tool_call_id (Ollama format)"""
        return {
            "role": "tool",
            "content": content
        }


class MockLLMClient(BaseLLMClient):
    """Mock LLM for testing"""
    
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Return mock response"""
        
        logger_internal.info("Mock LLM: Generating response")
        
        # Mock response structure
        return {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "This is a mock response. Configure a real LLM provider for actual conversations."
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 15,
                "total_tokens": 25
            }
        }
    
    def format_tool_result(
        self,
        tool_call_id: Optional[str],
        content: str
    ) -> Dict[str, Any]:
        """Format tool result (OpenAI-compatible)"""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        }


class LLMClientFactory:
    """Factory to create appropriate LLM client"""
    
    @staticmethod
    def create(config: LLMConfig, enterprise_access_token: Optional[str] = None) -> BaseLLMClient:
        """Create LLM client based on provider"""
        
        if config.provider == "openai":
            logger_internal.info(f"Creating OpenAI client: {config.model}")
            return OpenAIClient(config)
        elif config.provider == "ollama":
            logger_internal.info(f"Creating Ollama client: {config.model}")
            return OllamaClient(config)
        elif config.provider == "mock":
            logger_internal.info("Creating Mock LLM client")
            return MockLLMClient(config)
        elif config.provider == "enterprise":
            if not enterprise_access_token:
                raise ValueError("Enterprise provider requires a cached access token")
            logger_internal.info(f"Creating Enterprise gateway client: {config.model}")
            return EnterpriseLLMClient(config, enterprise_access_token)
        else:
            raise ValueError(f"Unknown LLM provider: {config.provider}")
