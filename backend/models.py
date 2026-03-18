"""
Pydantic models for MCP Client Web API.
These models serve as the source of truth for OpenAPI specification.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal, Optional, List, Dict, Any
from datetime import datetime
import uuid


# ---------------------------------------------------------------------------
# SSO / Auth models  (v0.4.0-sso-user-settings)
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    """Authenticated user's public profile (returned by GET /api/users/me)."""

    user_id: str = Field(..., description="Immutable UUID")
    email: str = Field(..., description="Primary email address")
    display_name: str = Field(..., description="Full name from IdP")
    avatar_url: Optional[str] = Field(None, description="Profile picture URL from IdP")
    roles: List[str] = Field(..., description="List of assigned roles, e.g. ['user'] or ['user','admin']")
    created_at: datetime = Field(..., description="Timestamp of first login")
    last_login_at: datetime = Field(..., description="Timestamp of most recent login")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440001",
                "email": "alice@example.com",
                "display_name": "Alice Smith",
                "avatar_url": "https://lh3.googleusercontent.com/a/...",
                "roles": ["user"],
                "created_at": "2026-03-01T09:00:00Z",
                "last_login_at": "2026-03-18T08:45:00Z",
            }
        }
    )


class UserSettings(BaseModel):
    """Per-user UI and application preferences."""

    theme: Literal["light", "dark", "system"] = Field(
        default="system", description="Colour scheme preference"
    )
    message_density: Literal["compact", "comfortable"] = Field(
        default="comfortable", description="Chat bubble spacing"
    )
    tool_panel_visible: bool = Field(
        default=True, description="Show the tool execution panel in the chat UI"
    )
    sidebar_collapsed: bool = Field(
        default=False, description="Collapse the left sidebar"
    )
    default_llm_model: Optional[str] = Field(
        default=None, description="Quick-start model override (null = no override)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "theme": "dark",
                "message_density": "comfortable",
                "tool_panel_visible": True,
                "sidebar_collapsed": False,
                "default_llm_model": None,
            }
        }
    )


class UserSettingsPatch(BaseModel):
    """Partial update payload for PATCH /api/users/me/settings.

    Only supplied (non-null) keys are updated; omitted keys are left unchanged.
    """

    theme: Optional[Literal["light", "dark", "system"]] = None
    message_density: Optional[Literal["compact", "comfortable"]] = None
    tool_panel_visible: Optional[bool] = None
    sidebar_collapsed: Optional[bool] = None
    default_llm_model: Optional[str] = None


class AdminUserPatch(BaseModel):
    """Payload for PATCH /api/admin/users/{user_id} — toggle is_active."""

    is_active: bool = Field(..., description="Set to false to disable the user")


class UserListResponse(BaseModel):
    """Paginated user list for GET /api/admin/users."""

    users: List[UserProfile]
    total: int
    limit: int
    offset: int


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


class RepeatedExecRunResult(BaseModel):
    """Result of a single run within a repeated tool execution sequence."""

    run_index: int = Field(
        ...,
        description="1-based index of this run within the sequence"
    )
    timestamp_utc: str = Field(
        ...,
        description="ISO 8601 compact UTC timestamp when this run started (YYYYMMDDTHHmmssZ)"
    )
    duration_ms: int = Field(
        ...,
        description="Wall-clock duration of this run in milliseconds"
    )
    success: bool = Field(
        ...,
        description="Whether this run completed without error"
    )
    result: Optional[Dict[str, Any]] = Field(
        None,
        description="Tool result payload (None on failure)"
    )
    error: Optional[str] = Field(
        None,
        description="Error message (None on success)"
    )
    file_path: Optional[str] = Field(
        None,
        description="Path of the run output file written to disk (None if file write failed)"
    )


class RepeatedExecSummary(BaseModel):
    """Aggregated result of a full repeated tool execution sequence."""

    device_id: str = Field(
        ...,
        description="Device identifier used as file name prefix"
    )
    target_tool: str = Field(
        ...,
        description="Namespaced MCP tool ID that was repeated (server_alias__tool_name)"
    )
    tool_name: str = Field(
        ...,
        description="Bare tool name without server alias prefix"
    )
    tool_arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments passed to the target tool on every run"
    )
    repeat_count: int = Field(
        ...,
        description="Total number of runs requested"
    )
    interval_ms: int = Field(
        ...,
        description="Configured interval between runs in milliseconds"
    )
    output_dir: str = Field(
        ...,
        description="Directory where per-run files were written"
    )
    runs: List["RepeatedExecRunResult"] = Field(
        default_factory=list,
        description="Per-run results in execution order"
    )
    total_duration_ms: int = Field(
        ...,
        description="Total wall-clock duration covering all runs and intervals in milliseconds"
    )
    success_count: int = Field(
        ...,
        description="Number of runs that completed successfully"
    )
    failure_count: int = Field(
        ...,
        description="Number of runs that failed"
    )


class ExecutionHintsSampling(BaseModel):
    """Sampling sub-object within executionHints"""

    defaultSampleCount: int = Field(
        ...,
        description="Default number of samples collected by the tool"
    )
    defaultIntervalMs: Optional[int] = Field(
        None,
        description="Default delay between samples in milliseconds (absent for one-shot tools)"
    )

    model_config = ConfigDict(extra="ignore")


class ExecutionHints(BaseModel):
    """Advisory runtime metadata published by the MCP server on proc tool entries.

    Used by the client to compute appropriate wait budgets and UX messaging.
    MUST NOT be treated as a replacement for inputSchema validation.
    """

    defaultTimeoutMs: Optional[int] = Field(
        None,
        description="Default server-side timeout budget (ms) when no override argument is supplied"
    )
    maxTimeoutMs: Optional[int] = Field(
        None,
        description="Maximum server-side timeout cap accepted for the tool (ms)"
    )
    estimatedRuntimeMs: Optional[int] = Field(
        None,
        description="Approximate expected runtime under default sampling behaviour (ms, advisory only)"
    )
    clientWaitMarginMs: Optional[int] = Field(
        None,
        description="Recommended extra client-side wait slack for transport and scheduling overhead (ms)"
    )
    mode: Optional[Literal["sampling", "oneShot"]] = Field(
        None,
        description="Execution pattern: 'sampling' collects multiple samples over time, 'oneShot' is a single bounded pass"
    )
    sampling: Optional[ExecutionHintsSampling] = Field(
        None,
        description="Sampling configuration details"
    )

    model_config = ConfigDict(extra="ignore")

    def recommended_wait_ms(self) -> int:
        """Compute recommended client-side MCP request wait budget (ms).

        Formula (CR-EXEC-005):
            recommendedWaitMs = max(defaultTimeoutMs, estimatedRuntimeMs) + clientWaitMarginMs
        Falls back gracefully when individual fields are absent.
        """
        base = max(
            self.defaultTimeoutMs or 0,
            self.estimatedRuntimeMs or 0
        )
        margin = self.clientWaitMarginMs or 0
        return base + margin


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
    execution_hints: Optional[ExecutionHints] = Field(
        None,
        description="Advisory runtime metadata from executionHints in tools/list (absent for non-proc tools)"
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
                },
                {
                    "namespaced_id": "debug_server__proc_cpu_spin_diagnose",
                    "server_alias": "debug_server",
                    "name": "proc_cpu_spin_diagnose",
                    "description": "Detect likely CPU spin threads for a process",
                    "parameters": {"type": "object", "properties": {}},
                    "execution_hints": {
                        "defaultTimeoutMs": 30000,
                        "maxTimeoutMs": 120000,
                        "estimatedRuntimeMs": 11000,
                        "clientWaitMarginMs": 5000,
                        "mode": "sampling",
                        "sampling": {
                            "defaultSampleCount": 6,
                            "defaultIntervalMs": 2000
                        }
                    }
                }
            ]
        }
    )


class ToolTestPrompt(BaseModel):
    """Example chat prompt used to exercise a documented MCP tool."""

    tool_name: str = Field(
        ...,
        description="Tool name as documented in USAGE-EXAMPLES.md"
    )
    prompt: str = Field(
        ...,
        min_length=1,
        description="User prompt example to send through chat for tool testing"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "tool_name": "server_info",
                    "prompt": "What version is the MCP server and what capabilities does it support?"
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
    include_history: bool = Field(
        default=True,
        description="Whether prior chat history should be sent with each new user query"
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
    initial_llm_response: Optional[str] = Field(
        default=None,
        description="Initial assistant response before any tool execution, if present"
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
                    "initial_llm_response": "I'll check the live weather and summarize it for you.",
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


class ServerHealthRefreshResponse(BaseModel):
    """Response from server health refresh operation"""

    servers_checked: int = Field(
        ...,
        description="Number of servers checked"
    )
    healthy_servers: int = Field(
        ...,
        description="Number of healthy servers"
    )
    unhealthy_servers: int = Field(
        ...,
        description="Number of unhealthy servers"
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Error messages from failed health checks"
    )
    servers: List[ServerConfig] = Field(
        default_factory=list,
        description="Updated server records including health metadata"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "servers_checked": 2,
                    "healthy_servers": 1,
                    "unhealthy_servers": 1,
                    "errors": ["weather_api: Timeout connecting to weather_api"],
                    "servers": []
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
