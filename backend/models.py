"""
Pydantic models for MCP Client Web API.
These models serve as the source of truth for OpenAPI specification.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional, List, Dict, Any
from datetime import datetime
import uuid


class ServerConfig(BaseModel):
    """MCP server configuration"""
    
    server_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique server identifier (UUID)"
    )
    alias: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Human-readable server name (must be unique)"
    )
    base_url: str = Field(
        ...,
        description="MCP server base URL (HTTP/HTTPS)",
        pattern=r"^https?://.+"
    )
    auth_type: Literal["none", "bearer", "api_key"] = Field(
        default="none",
        description="Authentication method"
    )
    bearer_token: Optional[str] = Field(
        None,
        description="Bearer token for authentication"
    )
    api_key: Optional[str] = Field(
        None,
        description="API key for authentication"
    )
    timeout_ms: int = Field(
        default=20000,
        ge=1000,
        le=60000,
        description="Request timeout in milliseconds"
    )
    health_status: Optional[str] = Field(
        None,
        description="Last health check status"
    )
    last_health_check: Optional[datetime] = Field(
        None,
        description="Timestamp of last health check"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "server_id": "550e8400-e29b-41d4-a716-446655440000",
                    "alias": "weather_api",
                    "base_url": "http://192.168.1.100:3000",
                    "auth_type": "bearer",
                    "bearer_token": "secret-token-123",
                    "timeout_ms": 20000,
                    "health_status": "healthy"
                },
                {
                    "alias": "local_tools",
                    "base_url": "http://localhost:3000",
                    "auth_type": "none",
                    "timeout_ms": 15000
                }
            ]
        }


class LLMConfig(BaseModel):
    """LLM provider configuration"""
    
    provider: Literal["openai", "ollama", "mock"] = Field(
        ...,
        description="LLM provider type"
    )
    model: str = Field(
        ...,
        description="Model name/identifier"
    )
    base_url: str = Field(
        ...,
        description="Provider API base URL"
    )
    api_key: Optional[str] = Field(
        None,
        description="API key for authentication (if required)"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for response generation"
    )
    max_tokens: Optional[int] = Field(
        None,
        ge=1,
        description="Maximum tokens in response"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "provider": "ollama",
                    "model": "llama3.1",
                    "base_url": "http://192.168.1.50:11434",
                    "temperature": 0.7
                },
                {
                    "provider": "openai",
                    "model": "gpt-4",
                    "base_url": "https://api.openai.com",
                    "api_key": "sk-...",
                    "temperature": 0.7,
                    "max_tokens": 2000
                }
            ]
        }


class FunctionCall(BaseModel):
    """Function call details in tool execution"""
    
    name: str = Field(
        ...,
        description="Namespaced tool name (format: server_alias__tool_name)"
    )
    arguments: str = Field(
        ...,
        description="JSON-encoded function arguments"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "name": "weather_api__get_weather",
                    "arguments": '{"city": "NYC", "units": "fahrenheit"}'
                }
            ]
        }


class ToolCall(BaseModel):
    """Tool execution request from LLM"""
    
    id: str = Field(
        ...,
        description="Unique tool call identifier"
    )
    type: str = Field(
        default="function",
        description="Call type (currently only 'function' supported)"
    )
    function: FunctionCall = Field(
        ...,
        description="Function call details"
    )


class ChatMessage(BaseModel):
    """Chat message in conversation"""
    
    role: Literal["user", "assistant", "tool", "system"] = Field(
        ...,
        description="Message role in conversation"
    )
    content: str = Field(
        ...,
        description="Message content"
    )
    tool_call_id: Optional[str] = Field(
        None,
        description="Tool call ID for tool result messages (OpenAI format)"
    )
    tool_calls: Optional[List[ToolCall]] = Field(
        None,
        description="Tool calls requested by assistant"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "role": "user",
                    "content": "What's the weather in NYC?"
                },
                {
                    "role": "assistant",
                    "content": "Let me check the weather for you.",
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "weather_api__get_weather",
                                "arguments": '{"city": "NYC"}'
                            }
                        }
                    ]
                },
                {
                    "role": "tool",
                    "content": '{"temperature": 72, "condition": "Partly Cloudy"}',
                    "tool_call_id": "call_abc123"
                }
            ]
        }


class ToolSchema(BaseModel):
    """MCP tool schema with server context"""
    
    namespaced_id: str = Field(
        ...,
        description="Namespaced tool identifier (server_alias__tool_name)"
    )
    server_alias: str = Field(
        ...,
        description="Server alias this tool belongs to"
    )
    name: str = Field(
        ...,
        description="Original tool name from MCP server"
    )
    description: str = Field(
        ...,
        description="Tool description for LLM"
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for tool parameters"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "namespaced_id": "weather_api__get_weather",
                    "server_alias": "weather_api",
                    "name": "get_weather",
                    "description": "Get current weather for a city",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "city": {
                                "type": "string",
                                "description": "City name"
                            },
                            "units": {
                                "type": "string",
                                "enum": ["celsius", "fahrenheit"],
                                "default": "fahrenheit"
                            }
                        },
                        "required": ["city"]
                    }
                }
            ]
        }


class SessionConfig(BaseModel):
    """Session configuration"""
    
    llm_config: LLMConfig = Field(
        ...,
        description="LLM provider configuration for this session"
    )
    enabled_servers: List[str] = Field(
        default_factory=list,
        description="List of server aliases enabled for this session"
    )


class Session(BaseModel):
    """Chat session with state"""
    
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique session identifier"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Session creation timestamp"
    )
    config: SessionConfig = Field(
        ...,
        description="Session configuration"
    )
    messages: List[ChatMessage] = Field(
        default_factory=list,
        description="Conversation message history"
    )
    trace_events: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Tool execution trace events for debugging"
    )


class ChatResponse(BaseModel):
    """Response from chat endpoint"""
    
    session_id: str = Field(
        ...,
        description="Session identifier"
    )
    message: ChatMessage = Field(
        ...,
        description="Assistant's response message"
    )
    tool_executions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Tool execution details from this turn"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "session_id": "550e8400-e29b-41d4-a716-446655440000",
                    "message": {
                        "role": "assistant",
                        "content": "The current weather in NYC is 72°F and partly cloudy."
                    },
                    "tool_executions": [
                        {
                            "tool": "weather_api__get_weather",
                            "duration_ms": 1234,
                            "status": "success"
                        }
                    ]
                }
            ]
        }


class SessionResponse(BaseModel):
    """Response from session creation"""
    
    session_id: str = Field(
        ...,
        description="Created session identifier"
    )
    created_at: datetime = Field(
        ...,
        description="Session creation timestamp"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "session_id": "550e8400-e29b-41d4-a716-446655440000",
                    "created_at": "2026-03-07T12:00:00Z"
                }
            ]
        }


class MessageListResponse(BaseModel):
    """Response with list of messages"""
    
    session_id: str = Field(
        ...,
        description="Session identifier"
    )
    messages: List[ChatMessage] = Field(
        ...,
        description="List of messages in conversation"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "session_id": "550e8400-e29b-41d4-a716-446655440000",
                    "messages": [
                        {
                            "role": "user",
                            "content": "What's the weather?"
                        },
                        {
                            "role": "assistant",
                            "content": "72°F and partly cloudy."
                        }
                    ]
                }
            ]
        }


class ToolRefreshResponse(BaseModel):
    """Response from tool refresh operation"""
    
    total_tools: int = Field(
        ...,
        description="Total number of tools discovered"
    )
    servers_refreshed: int = Field(
        ...,
        description="Number of servers successfully refreshed"
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Error messages from failed servers"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "total_tools": 8,
                    "servers_refreshed": 2,
                    "errors": []
                }
            ]
        }


class DeleteResponse(BaseModel):
    """Response from delete operations"""
    
    success: bool = Field(
        ...,
        description="Whether deletion was successful"
    )
    message: str = Field(
        ...,
        description="Status message"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "success": True,
                    "message": "Server deleted successfully"
                }
            ]
        }


class ErrorResponse(BaseModel):
    """Standard error response"""
    
    detail: str = Field(
        ...,
        description="Human-readable error message"
    )
    error_code: Optional[str] = Field(
        None,
        description="Machine-readable error code"
    )
    context: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional error context"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "detail": "MCP server unreachable",
                    "error_code": "MCP_CONNECTION_FAILED",
                    "context": {
                        "server_alias": "weather_api",
                        "base_url": "http://192.168.1.100:3000"
                    }
                }
            ]
        }


class HealthResponse(BaseModel):
    """API health check response"""
    
    status: str = Field(
        ...,
        description="Health status"
    )
    version: str = Field(
        ...,
        description="API version"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Current server time"
    )
    
    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "status": "healthy",
                    "version": "0.2.0-jsonrpc",
                    "timestamp": "2026-03-07T12:00:00Z"
                }
            ]
        }
