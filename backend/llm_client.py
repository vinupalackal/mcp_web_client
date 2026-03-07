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
        self.timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=5.0)
    
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
        
        if self.config.max_tokens:
            payload["max_tokens"] = self.config.max_tokens
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}"
        }
        
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
            logger_internal.error(f"OpenAI timeout: {e}")
            raise Exception("LLM request timeout")
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
        
        try:
            logger_external.info(f"→ POST {url} (Ollama chat)")
            
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
            
        except httpx.TimeoutException as e:
            logger_internal.error(f"Ollama timeout: {e}")
            raise Exception("LLM request timeout")
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
    def create(config: LLMConfig) -> BaseLLMClient:
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
        else:
            raise ValueError(f"Unknown LLM provider: {config.provider}")
