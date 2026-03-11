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
            "%s timeout: phase=%s timeout_s=%.1f model=%s url=%s messages=%s tools=%s payload_bytes=%s raw_error=%r",
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
        
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = True
        
        if self.config.max_tokens:
            payload["max_tokens"] = self.config.max_tokens
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}"
        }
        payload_bytes = self._estimate_payload_bytes(payload)
        
        try:
            logger_external.info(f"→ POST {url} (OpenAI chat)")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                result = response.json()
            
            logger_external.info(f"← {response.status_code} (OpenAI response)")
            logger_internal.info(f"OpenAI tokens: {result.get('usage', {})}")
            
            return result
            
        except httpx.TimeoutException as e:
            self._log_timeout("OpenAI", url, e, payload_bytes, len(messages), len(tools))
            raise Exception(self._format_timeout_error(e))
        except httpx.HTTPError as e:
            logger_internal.error(f"OpenAI HTTP error: {e}")
            raise Exception(f"LLM HTTP error: {str(e)}")
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

        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = True

        if self.config.max_tokens:
            payload["max_tokens"] = self.config.max_tokens

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }
        payload_bytes = self._estimate_payload_bytes(payload)

        try:
            logger_external.info(f"→ POST {url} (Enterprise chat)")

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                result = response.json()

            logger_external.info(f"← {response.status_code} (Enterprise response)")
            logger_internal.info(f"Enterprise tokens: {result.get('usage', {})}")

            return result

        except httpx.TimeoutException as e:
            self._log_timeout("Enterprise gateway", url, e, payload_bytes, len(messages), len(tools))
            raise Exception(self._format_timeout_error(e))
        except httpx.HTTPError as e:
            logger_internal.error(f"Enterprise gateway HTTP error: {e}")
            raise Exception(f"LLM HTTP error: {str(e)}")
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
            logger_external.info(f"→ POST {url} (Ollama chat)")
            logger_internal.info(f"Ollama payload: {len(messages)} messages, {len(tools)} tools, {payload_bytes} bytes")
            
            # Log each message for debugging
            for i, msg in enumerate(messages):
                logger_internal.info(f"Message {i}: role={msg.get('role')}, content_length={len(str(msg.get('content', '')))}, has_tool_calls={'tool_calls' in msg}, has_tool_call_id={'tool_call_id' in msg}")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                ollama_result = response.json()
            
            logger_external.info(f"← {response.status_code} (Ollama response)")
            
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
            
            return normalized_result
            
        except httpx.HTTPStatusError as e:
            logger_internal.error(f"Ollama HTTP error: {e}")
            logger_internal.error(f"Request payload keys: {list(payload.keys())}")
            logger_internal.error(f"Number of messages: {len(messages)}")
            if messages:
                logger_internal.error(f"Last message role: {messages[-1].get('role')}")
                logger_internal.error(f"Last message keys: {list(messages[-1].keys())}")
                # Dump all messages for debugging
                for i, msg in enumerate(messages):
                    logger_internal.error(f"Message {i}: {msg}")
            logger_internal.error(f"Response status: {e.response.status_code}")
            logger_internal.error(f"Response body: {e.response.text}")
            raise Exception(f"LLM HTTP error: {str(e)}")
        except httpx.TimeoutException as e:
            self._log_timeout("Ollama", url, e, payload_bytes, len(messages), len(tools))
            raise Exception(self._format_timeout_error(e))
        except httpx.HTTPError as e:
            logger_internal.error(f"Ollama HTTP error: {e}")
            raise Exception(f"LLM HTTP error: {str(e)}")
        except Exception as e:
            logger_internal.error(f"Ollama error: {e}")
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
