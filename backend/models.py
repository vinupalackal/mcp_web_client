"""
Pydantic models for MCP Client Web API.
These models serve as the source of truth for OpenAPI specification.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator
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
    
    model_config = ConfigDict(
        json_schema_extra={
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
    )


class LLMConfig(BaseModel):
    """LLM provider configuration"""
    
    gateway_mode: Literal["standard", "enterprise"] = Field(
        default="standard",
        description="Gateway routing mode"
    )
    provider: Literal["openai", "ollama", "mock", "enterprise"] = Field(
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
    auth_method: Optional[Literal["bearer"]] = Field(
        None,
        description="Enterprise authentication method"
    )
    client_id: Optional[str] = Field(
        None,
        description="Enterprise client identifier"
    )
    client_secret: Optional[str] = Field(
        None,
        description="Enterprise client secret"
    )
    token_endpoint_url: Optional[str] = Field(
        None,
        description="Enterprise OAuth token endpoint URL"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for response generation"
    )
    llm_timeout_ms: int = Field(
        default=180000,
        ge=5000,
        le=600000,
        description="LLM request timeout in milliseconds"
    )
    max_tokens: Optional[int] = Field(
        None,
        ge=1,
        description="Maximum tokens in response"
    )

    @model_validator(mode="after")
    def validate_gateway_mode(self):
        """Validate gateway-specific configuration requirements."""
        if self.provider == "enterprise":
            if self.gateway_mode != "enterprise":
                raise ValueError("Enterprise provider requires gateway_mode='enterprise'")
            if not self.base_url.startswith("https://"):
                raise ValueError("Enterprise gateway base_url must use HTTPS")
            if self.auth_method != "bearer":
                raise ValueError("Enterprise provider requires auth_method='bearer'")
            if not self.client_id:
                raise ValueError("Enterprise provider requires client_id")
            if not self.client_secret:
                raise ValueError("Enterprise provider requires client_secret")
            if not self.token_endpoint_url:
                raise ValueError("Enterprise provider requires token_endpoint_url")
            if not self.token_endpoint_url.startswith("https://"):
                raise ValueError("Enterprise token_endpoint_url must use HTTPS")
        elif self.gateway_mode == "enterprise":
            raise ValueError("gateway_mode='enterprise' requires provider='enterprise'")

        return self
    
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "gateway_mode": "enterprise",
                    "provider": "enterprise",
                    "model": "gpt-4o",
                    "base_url": "https://llm-gateway.internal/modelgw/models/openai/v1",
                    "auth_method": "bearer",
                    "client_id": "enterprise-client-id",
                    "client_secret": "super-secret",
                    "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                    "temperature": 0.2,
                    "llm_timeout_ms": 180000,
                    "max_tokens": 2000
                },
                {
                    "provider": "ollama",
                    "model": "llama3.1",
                    "base_url": "http://192.168.1.50:11434",
                    "temperature": 0.7,
                    "llm_timeout_ms": 180000
                },
                {
                    "provider": "openai",
                    "model": "gpt-4",
                    "base_url": "https://api.openai.com",
                    "api_key": "sk-...",
                    "temperature": 0.7,
                    "llm_timeout_ms": 180000,
                    "max_tokens": 2000
                }
            ]
        }
    )


class EnterpriseTokenRequest(BaseModel):
    """Enterprise OAuth token acquisition request"""

    token_endpoint_url: str = Field(
        ...,
        description="OAuth token endpoint URL",
        pattern=r"^https://.+"
    )
    client_id: str = Field(
        ...,
        min_length=1,
        description="Enterprise client identifier"
    )
    client_secret: str = Field(
        ...,
        min_length=1,
        description="Enterprise client secret"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                    "client_id": "enterprise-client-id",
                    "client_secret": "super-secret"
                }
            ]
        }
    )


class EnterpriseTokenResponse(BaseModel):
    """Enterprise token acquisition response metadata"""

    token_acquired: bool = Field(
        ...,
        description="Whether a token is currently cached"
    )
    expires_in: Optional[int] = Field(
        None,
        description="Token lifetime in seconds, if provided by upstream"
    )
    cached_at: Optional[datetime] = Field(
        None,
        description="Timestamp when the token was cached"
    )
    error: Optional[str] = Field(
        None,
        description="Failure reason when token acquisition fails"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "token_acquired": True,
                    "expires_in": 3600,
                    "cached_at": "2026-03-10T12:00:00Z"
                }
            ]
        }
    )


class EnterpriseTokenStatusResponse(BaseModel):
    """Enterprise token cache status"""

    token_cached: bool = Field(
        ...,
        description="Whether a token is currently cached in memory"
    )
    cached_at: Optional[datetime] = Field(
        None,
        description="Timestamp when the token was cached"
    )
    expires_in: Optional[int] = Field(
        None,
        description="Token lifetime in seconds, if available"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "token_cached": True,
                    "cached_at": "2026-03-10T12:00:00Z",
                    "expires_in": 3600
                },
                {
                    "token_cached": False,
                    "cached_at": None,
                    "expires_in": None
                }
            ]
        }
    )


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
    
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "weather_api__get_weather",
                    "arguments": '{"city": "NYC", "units": "fahrenheit"}'
                }
            ]
        }
    )


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
    
    model_config = ConfigDict(
        json_schema_extra={
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
    )


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
    
    model_config = ConfigDict(
        json_schema_extra={
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
    )


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
    
    model_config = ConfigDict(
        json_schema_extra={
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
    )


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
    
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "session_id": "550e8400-e29b-41d4-a716-446655440000",
                    "created_at": "2026-03-07T12:00:00Z"
                }
            ]
        }
    )


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
    
    model_config = ConfigDict(
        json_schema_extra={
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
    )


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
    
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "total_tools": 8,
                    "servers_refreshed": 2,
                    "errors": []
                }
            ]
        }
    )


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
    
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "success": True,
                    "message": "Server deleted successfully"
                }
            ]
        }
    )


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
    
    model_config = ConfigDict(
        json_schema_extra={
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
    )


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
    
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "healthy",
                    "version": "0.2.0-jsonrpc",
                    "timestamp": "2026-03-07T12:00:00Z"
                }
            ]
        }
    )
