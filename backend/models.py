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
    llm_connect_timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=120000,
        description=(
            "TCP connect timeout for LLM requests in milliseconds. "
            "Increase this when the LLM server is on a remote or slow network "
            "(e.g. a multi-machine LAN deployment where the initial TCP handshake "
            "may take longer than the default 30 s). "
            "This is independent of llm_timeout_ms which controls the read/write phase."
        ),
    )
    max_tokens: Optional[int] = Field(
        None,
        ge=1,
        description="Maximum tokens in response"
    )
    tools_split_enabled: bool = Field(
        default=False,
        description=(
            "Enable split-phase tool querying. When True and the total discovered "
            "tool count exceeds tools_split_limit (or MCP_MAX_TOOLS_PER_REQUEST), "
            "the tool catalog is split into chunks and the LLM is queried per "
            "chunk according to tools_split_mode. All tool calls collected across "
            "chunks are then executed together. Has no effect when False (default)."
        ),
    )
    tools_split_mode: Literal["sequential", "concurrent"] = Field(
        default="concurrent",
        description=(
            "Execution mode for split-phase LLM chunk requests. "
            "'concurrent': all chunk requests are fired simultaneously via "
            "asyncio.gather() — fastest, but increases parallel load on the gateway. "
            "'sequential': chunk requests are sent one after another — slower "
            "(total latency \u2248 N \u00d7 LLM latency) but easier to debug and "
            "gentler on rate-limited gateways. Only used when tools_split_enabled=True."
        ),
    )
    tools_split_limit: Optional[int] = Field(
        None,
        ge=1,
        le=512,
        description=(
            "Maximum number of tools sent to the LLM in a single request. "
            "When the total discovered tool count exceeds this value, tools are "
            "automatically split into multiple chunks and the LLM is queried once "
            "per chunk (split-phase mode). All tool calls collected across every "
            "chunk are then executed together before a final synthesis call. "
            "Overrides the MCP_MAX_TOOLS_PER_REQUEST environment variable when set. "
            "Leave unset to use the environment default (128)."
        ),
    )
    tiny_llm_mode_classifier_enabled: Optional[bool] = Field(
        default=None,
        description=(
            "Override for the tiny LLM request-mode classifier. "
            "Set true/false to override the server default, or null to use the environment default."
        ),
    )
    tiny_llm_mode_classifier_min_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Override heuristic-confidence threshold below which the tiny mode-classifier runs. "
            "Null uses the server default."
        ),
    )
    tiny_llm_mode_classifier_min_score_gap: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description=(
            "Override heuristic score-gap threshold below which the tiny mode-classifier runs. "
            "Null uses the server default."
        ),
    )
    tiny_llm_mode_classifier_accept_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Override minimum tiny-classifier confidence required to replace heuristic routing. "
            "Null uses the server default."
        ),
    )
    tiny_llm_mode_classifier_max_tokens: Optional[int] = Field(
        default=None,
        ge=32,
        le=512,
        description=(
            "Override max tokens reserved for the tiny mode-classifier response. "
            "Null uses the server default."
        ),
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
                    "max_tokens": 2000,
                    "tiny_llm_mode_classifier_enabled": None,
                    "tiny_llm_mode_classifier_min_confidence": None,
                    "tiny_llm_mode_classifier_min_score_gap": None,
                    "tiny_llm_mode_classifier_accept_confidence": None,
                    "tiny_llm_mode_classifier_max_tokens": None
                }
            ]
        }
    )


class MilvusConfig(BaseModel):
    """Milvus-backed memory subsystem configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable the optional Milvus-backed memory subsystem",
    )
    milvus_uri: str = Field(
        default="",
        description="Milvus connection URI. Required when the subsystem is enabled.",
    )
    collection_prefix: str = Field(
        default="mcp_client",
        min_length=1,
        max_length=64,
        description="Prefix used when naming Milvus collections",
    )
    repo_id: str = Field(
        default="",
        max_length=256,
        description="Repository or workspace identifier stored with indexed content",
    )
    collection_generation: str = Field(
        default="v1",
        min_length=1,
        max_length=64,
        description="Collection generation suffix used for active Milvus collections",
    )
    max_results: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum retrieval results returned per chat turn",
    )
    retrieval_timeout_s: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
        description="Timeout in seconds for retrieval enrichment",
    )
    degraded_mode: bool = Field(
        default=True,
        description="Return degraded memory responses instead of failing the chat turn",
    )
    enable_conversation_memory: bool = Field(
        default=False,
        description="Store completed chat turns in conversation memory",
    )
    conversation_retention_days: int = Field(
        default=7,
        ge=1,
        le=365,
        description="Retention period in days for stored conversation turns",
    )
    enable_tool_cache: bool = Field(
        default=False,
        description="Enable safe allowlisted tool result caching",
    )
    tool_cache_ttl_s: float = Field(
        default=3600.0,
        ge=1.0,
        le=2592000.0,
        description="Time-to-live in seconds for cached tool results",
    )
    tool_cache_allowlist: List[str] = Field(
        default_factory=list,
        description="Explicit tool names that are eligible for safe caching",
    )
    tool_cache_freshness_keywords: List[str] = Field(
        default_factory=list,
        description=(
            "Substring keywords matched against the bare tool name (lower-cased). "
            "Any tool whose name contains one of these strings is excluded from caching. "
            "When empty the built-in defaults are used "
            "(uptime, heartbeat, health, status, loadavg, telemetry, realtime, live_)."
        ),
    )
    enable_expiry_cleanup: bool = Field(
        default=True,
        description="Run expiry cleanup for conversation memory and tool cache records",
    )
    expiry_cleanup_interval_s: float = Field(
        default=300.0,
        ge=1.0,
        le=86400.0,
        description="Minimum interval in seconds between background expiry-cleanup passes",
    )
    repo_roots: List[str] = Field(
        default_factory=list,
        description="Filesystem paths scanned for code files during workspace ingestion",
    )
    doc_roots: List[str] = Field(
        default_factory=list,
        description="Filesystem paths scanned for documentation files during workspace ingestion",
    )

    @model_validator(mode="after")
    def validate_milvus_config(self):
        """Validate Milvus-specific runtime requirements and normalize allowlist entries."""
        self.milvus_uri = self.milvus_uri.strip()
        self.collection_prefix = self.collection_prefix.strip()
        self.repo_id = self.repo_id.strip()
        self.collection_generation = self.collection_generation.strip()
        self.tool_cache_allowlist = [
            tool.strip()
            for tool in self.tool_cache_allowlist
            if isinstance(tool, str) and tool.strip()
        ]
        self.tool_cache_freshness_keywords = [
            kw.strip().lower()
            for kw in self.tool_cache_freshness_keywords
            if isinstance(kw, str) and kw.strip()
        ]

        if self.enabled and not self.milvus_uri:
            raise ValueError("Milvus config requires milvus_uri when enabled=true")

        return self

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "enabled": True,
                    "milvus_uri": "http://127.0.0.1:19530",
                    "collection_prefix": "mcp_client",
                    "repo_id": "vinu/mcp-client",
                    "collection_generation": "v1",
                    "max_results": 5,
                    "retrieval_timeout_s": 5.0,
                    "degraded_mode": True,
                    "enable_conversation_memory": True,
                    "conversation_retention_days": 7,
                    "enable_tool_cache": True,
                    "tool_cache_ttl_s": 3600.0,
                    "tool_cache_allowlist": ["weather__get_forecast", "github__get_issue"],
                    "enable_expiry_cleanup": True,
                    "expiry_cleanup_interval_s": 300.0,
                },
                {
                    "enabled": False,
                    "milvus_uri": "",
                    "collection_prefix": "mcp_client",
                    "repo_id": "",
                    "collection_generation": "v1",
                    "max_results": 5,
                    "retrieval_timeout_s": 5.0,
                    "degraded_mode": True,
                    "enable_conversation_memory": False,
                    "conversation_retention_days": 7,
                    "enable_tool_cache": False,
                    "tool_cache_ttl_s": 3600.0,
                    "tool_cache_allowlist": [],
                    "enable_expiry_cleanup": True,
                    "expiry_cleanup_interval_s": 300.0,
                },
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


class ToolTestOutputRequest(BaseModel):
    """Payload used to persist Tool Tester output.txt snapshots."""

    content: str = Field(
        ...,
        description="Plain-text snapshot of the current Tool Tester results panel"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "content": "MCP Tool Tester Results\nStatus: Completed 2/2 tool tests.\n\n[System]\nFinished tool test batch: 2/2 succeeded."
                }
            ]
        }
    )


class ToolTestOutputResponse(BaseModel):
    """Metadata returned after persisting Tool Tester output.txt."""

    file_path: str = Field(
        ...,
        description="Server-side path of the generated Tool Tester output file"
    )
    bytes_written: int = Field(
        ...,
        ge=0,
        description="Number of UTF-8 bytes written to output.txt"
    )
    updated_at: datetime = Field(
        ...,
        description="Timestamp when output.txt was last updated"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "file_path": "data/output.txt",
                    "bytes_written": 184,
                    "updated_at": "2026-03-18T10:15:00Z"
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
    history_mode: str = Field(
        default="summary",
        description="How prior context should be sent to the LLM: 'summary', 'full', or 'latest'"
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
    transaction_id: Optional[str] = Field(
        default=None,
        description="Request-scoped chat transaction identifier for diagnostics correlation"
    )
    retrieval_trace: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Retrieval diagnostics for this chat turn when memory augmentation runs. "
            "Includes request_id, query_hash, collection_keys, result_count, degraded status, and latency."
        )
    )
    context_sources: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description=(
            "Retrieved context sources used to augment this response when the optional "
            "memory/retrieval feature is enabled. Each entry contains source_path, "
            "collection ('code_memory' or 'doc_memory'), and similarity score."
        )
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
                    "transaction_id": "chat-0d3b519a-20f2-467d-9a49-f1d50961f3c5",
                    "retrieval_trace": None,
                    "tool_executions": [
                        {
                            "tool": "weather_api__get_weather",
                            "duration_ms": 1234,
                            "status": "success"
                        }
                    ],
                    "context_sources": None
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
    memory: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional memory subsystem status",
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "healthy",
                    "version": "0.2.0-jsonrpc",
                    "timestamp": "2026-03-07T12:00:00Z",
                    "memory": {"enabled": False}
                }
            ]
        }
    )


class MemoryFeatureFlags(BaseModel):
    """Effective feature toggles for the optional memory subsystem."""

    enabled: bool = Field(
        default=False,
        description="Master enable flag for the memory subsystem",
    )
    retrieval_enabled: bool = Field(
        default=False,
        description="Enable code and document retrieval enrichment",
    )
    conversation_enabled: bool = Field(
        default=False,
        description="Enable long-term conversation memory",
    )
    tool_cache_enabled: bool = Field(
        default=False,
        description="Enable allowlisted tool cache behavior",
    )
    ingestion_enabled: bool = Field(
        default=False,
        description="Enable ingestion jobs",
    )
    degraded_mode: bool = Field(
        default=True,
        description="Continue serving without retrieval when the memory backend fails",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "enabled": True,
                "retrieval_enabled": True,
                "conversation_enabled": False,
                "tool_cache_enabled": False,
                "ingestion_enabled": False,
                "degraded_mode": True,
            }
        }
    )


class MemoryConfigSummary(BaseModel):
    """Safe, structured summary of effective memory configuration."""

    milvus_uri_configured: bool = Field(
        default=False,
        description="Whether a Milvus URI is configured without exposing its full value",
    )
    collection_prefix: str = Field(
        default="mcp_client",
        description="Prefix used for versioned collection names",
    )
    embedding_provider: Optional[str] = Field(
        default=None,
        description="Embedding backend provider identifier",
    )
    embedding_model: Optional[str] = Field(
        default=None,
        description="Embedding model identifier",
    )
    max_code_results: int = Field(
        default=5,
        ge=0,
        description="Maximum code chunks injected per turn",
    )
    max_doc_results: int = Field(
        default=5,
        ge=0,
        description="Maximum documentation chunks injected per turn",
    )
    max_conversation_results: int = Field(
        default=3,
        ge=0,
        description="Maximum long-term conversation memories recalled per turn",
    )
    code_threshold: float = Field(
        default=0.72,
        ge=0.0,
        le=1.0,
        description="Similarity threshold for code retrieval",
    )
    doc_threshold: float = Field(
        default=0.68,
        ge=0.0,
        le=1.0,
        description="Similarity threshold for documentation retrieval",
    )
    conversation_threshold: float = Field(
        default=0.82,
        ge=0.0,
        le=1.0,
        description="Similarity threshold for conversation memory retrieval",
    )
    retention_days: int = Field(
        default=30,
        ge=1,
        description="Default retention period for long-term memory when applicable",
    )
    repo_roots: List[str] = Field(
        default_factory=list,
        description="Configured repository roots for ingestion",
    )
    doc_roots: List[str] = Field(
        default_factory=list,
        description="Configured documentation roots for ingestion",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "milvus_uri_configured": True,
                "collection_prefix": "mcp_client",
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-3-small",
                "max_code_results": 5,
                "max_doc_results": 5,
                "max_conversation_results": 3,
                "code_threshold": 0.72,
                "doc_threshold": 0.68,
                "conversation_threshold": 0.82,
                "retention_days": 30,
                "repo_roots": ["/workspace/src"],
                "doc_roots": ["/workspace/docs"],
            }
        }
    )


class MemoryStatus(BaseModel):
    """Current status of the optional memory subsystem."""

    status: Literal["disabled", "healthy", "degraded"] = Field(
        ...,
        description="Memory subsystem status",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Short explanation for the current status",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Non-fatal warnings related to subsystem readiness",
    )
    milvus_reachable: Optional[bool] = Field(
        default=None,
        description="Whether Milvus is reachable when memory is enabled",
    )
    embedding_available: Optional[bool] = Field(
        default=None,
        description="Whether the configured embedding provider is available",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "disabled",
                    "reason": "Memory is disabled by configuration",
                    "warnings": [],
                    "milvus_reachable": None,
                    "embedding_available": None,
                },
                {
                    "status": "degraded",
                    "reason": "Milvus is unreachable; serving without retrieval",
                    "warnings": ["MCP_MEMORY_DEGRADED_MODE is active"],
                    "milvus_reachable": False,
                    "embedding_available": True,
                }
            ]
        }
    )


class MemoryCollectionStatus(BaseModel):
    """Summary of a known memory collection generation."""

    collection_key: str = Field(
        ...,
        description="Logical collection key, such as code_memory or doc_memory",
    )
    collection_name: str = Field(
        ...,
        description="Concrete versioned collection name",
    )
    generation: str = Field(
        ...,
        description="Generation or version marker for the collection",
    )
    embedding_provider: Optional[str] = Field(
        default=None,
        description="Embedding backend provider for this collection generation",
    )
    embedding_model: Optional[str] = Field(
        default=None,
        description="Embedding model used by this collection generation",
    )
    embedding_dimension: Optional[int] = Field(
        default=None,
        ge=1,
        description="Embedding vector dimension for this collection generation",
    )
    index_version: Optional[str] = Field(
        default=None,
        description="Index or schema version label for this collection generation",
    )
    is_active: bool = Field(
        default=False,
        description="Whether this generation is the active collection version",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "collection_key": "code_memory",
                "collection_name": "mcp_client_code_memory_v1_20260330",
                "generation": "20260330",
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-3-small",
                "embedding_dimension": 1536,
                "index_version": "hnsw-v1",
                "is_active": True,
            }
        }
    )


class MemoryIngestionJobStatus(BaseModel):
    """Structured ingestion job diagnostics summary."""

    job_id: str = Field(
        ...,
        description="Unique ingestion job identifier",
    )
    job_type: str = Field(
        ...,
        description="Ingestion job type",
    )
    status: str = Field(
        ...,
        description="Current ingestion job status",
    )
    collection_key: Optional[str] = Field(
        default=None,
        description="Logical collection key targeted by the job",
    )
    repo_id: Optional[str] = Field(
        default=None,
        description="Logical repository or workspace identifier",
    )
    source_count: int = Field(
        default=0,
        ge=0,
        description="Number of sources considered by the job",
    )
    chunk_count: int = Field(
        default=0,
        ge=0,
        description="Number of chunks produced by the job",
    )
    error_count: int = Field(
        default=0,
        ge=0,
        description="Number of errors recorded by the job",
    )
    error_summary: Optional[str] = Field(
        default=None,
        description="Short summary of ingestion failures, if any",
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="Job start timestamp",
    )
    finished_at: Optional[datetime] = Field(
        default=None,
        description="Job finish timestamp",
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Most recent job update timestamp",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440099",
                "job_type": "code_ingestion",
                "status": "completed",
                "collection_key": "code_memory",
                "repo_id": "workspace-main",
                "source_count": 12,
                "chunk_count": 48,
                "error_count": 0,
                "error_summary": None,
                "started_at": "2026-03-30T09:00:00Z",
                "finished_at": "2026-03-30T09:01:12Z",
                "updated_at": "2026-03-30T09:01:12Z",
            }
        }
    )


class MemoryDiagnosticsResponse(BaseModel):
    """Aggregate diagnostics payload for future memory admin endpoints."""

    feature_flags: MemoryFeatureFlags = Field(
        ...,
        description="Effective memory feature toggles",
    )
    config: MemoryConfigSummary = Field(
        ...,
        description="Safe summary of effective memory configuration",
    )
    status: MemoryStatus = Field(
        ...,
        description="Current memory subsystem health status",
    )
    collections: List[MemoryCollectionStatus] = Field(
        default_factory=list,
        description="Known memory collection generations",
    )
    ingestion_jobs: List[MemoryIngestionJobStatus] = Field(
        default_factory=list,
        description="Recent or active ingestion job summaries",
    )


class MemoryMaintenanceRequest(BaseModel):
    """Manual maintenance request for the optional memory subsystem."""

    force: bool = Field(
        default=True,
        description="Run cleanup immediately even if the normal cleanup interval has not elapsed",
    )
    cleanup_expired_conversation_memory: bool = Field(
        default=True,
        description="Delete expired conversation-memory sidecar rows and vector rows",
    )
    cleanup_expired_tool_cache: bool = Field(
        default=True,
        description="Delete expired tool-cache sidecar rows and vector rows",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "force": True,
                "cleanup_expired_conversation_memory": True,
                "cleanup_expired_tool_cache": True,
            }
        }
    )


class MemoryMaintenanceResponse(BaseModel):
    """Summary returned after a manual memory maintenance run."""

    success: bool = Field(
        ...,
        description="Whether the maintenance operation completed without endpoint-level errors",
    )
    message: str = Field(
        ...,
        description="Short human-readable summary",
    )
    summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed cleanup summary from the memory subsystem",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "message": "Memory maintenance completed",
                "summary": {
                    "ran": True,
                    "conversation_deleted": 2,
                    "tool_cache_deleted": 4,
                    "cleaned_at": "2026-04-02T10:15:00+00:00",
                },
            }
        }
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "feature_flags": {
                    "enabled": True,
                    "retrieval_enabled": True,
                    "conversation_enabled": False,
                    "tool_cache_enabled": False,
                    "ingestion_enabled": True,
                    "degraded_mode": True,
                },
                "config": {
                    "milvus_uri_configured": True,
                    "collection_prefix": "mcp_client",
                    "embedding_provider": "openai",
                    "embedding_model": "text-embedding-3-small",
                    "max_code_results": 5,
                    "max_doc_results": 5,
                    "max_conversation_results": 3,
                    "code_threshold": 0.72,
                    "doc_threshold": 0.68,
                    "conversation_threshold": 0.82,
                    "retention_days": 30,
                    "repo_roots": ["/workspace/src"],
                    "doc_roots": ["/workspace/docs"],
                },
                "status": {
                    "status": "healthy",
                    "reason": None,
                    "warnings": [],
                    "milvus_reachable": True,
                    "embedding_available": True,
                },
                "collections": [
                    {
                        "collection_key": "code_memory",
                        "collection_name": "mcp_client_code_memory_v1_20260330",
                        "generation": "20260330",
                        "embedding_provider": "openai",
                        "embedding_model": "text-embedding-3-small",
                        "embedding_dimension": 1536,
                        "index_version": "hnsw-v1",
                        "is_active": True,
                    }
                ],
                "ingestion_jobs": [
                    {
                        "job_id": "550e8400-e29b-41d4-a716-446655440099",
                        "job_type": "code_ingestion",
                        "status": "completed",
                        "collection_key": "code_memory",
                        "repo_id": "workspace-main",
                        "source_count": 12,
                        "chunk_count": 48,
                        "error_count": 0,
                        "error_summary": None,
                        "started_at": "2026-03-30T09:00:00Z",
                        "finished_at": "2026-03-30T09:01:12Z",
                        "updated_at": "2026-03-30T09:01:12Z",
                    }
                ],
            }
        }
    )


class MemoryIngestTriggerRequest(BaseModel):
    """Request body for the manual workspace ingestion trigger endpoint."""

    repo_id: str = Field(
        default="",
        max_length=256,
        description="Repository identifier stored with indexed chunks; falls back to the value in MilvusConfig",
    )
    repo_roots: List[str] = Field(
        default_factory=list,
        description="Override the repo roots from MilvusConfig for this ingestion run",
    )
    doc_roots: List[str] = Field(
        default_factory=list,
        description="Override the doc roots from MilvusConfig for this ingestion run",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "repo_id": "workspace-main",
                "repo_roots": ["/workspace/src"],
                "doc_roots": ["/workspace/docs"],
            }
        }
    )


class MemoryIngestTriggerResponse(BaseModel):
    """Result returned after triggering a workspace ingestion job."""

    success: bool = Field(..., description="Whether the ingestion job completed without endpoint-level errors")
    job_id: str = Field(..., description="Unique identifier for the completed ingestion job")
    status: str = Field(..., description="Final job status: completed | completed_with_errors | failed")
    source_count: int = Field(default=0, description="Total source files scanned")
    chunk_count: int = Field(default=0, description="Total chunks written to Milvus")
    deleted_count: int = Field(default=0, description="Stale chunks removed from Milvus")
    error_count: int = Field(default=0, description="Number of per-file errors encountered")
    errors: List[str] = Field(default_factory=list, description="Per-file error messages (truncated to first 10)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "job_id": "550e8400-e29b-41d4-a716-446655440099",
                "status": "completed",
                "source_count": 24,
                "chunk_count": 96,
                "deleted_count": 4,
                "error_count": 0,
                "errors": [],
            }
        }
    )


class MemoryCollectionRowCount(BaseModel):
    """Current row-count view for a single active Milvus memory collection."""

    collection_key: str = Field(
        ...,
        description="Logical collection key, such as code_memory or doc_memory",
    )
    collection_name: str = Field(
        ...,
        description="Concrete active Milvus collection name",
    )
    row_count: int = Field(
        ...,
        description="Current Milvus row count, or -1 when stats are unavailable",
    )
    available: bool = Field(
        ...,
        description="Whether the row count was readable from Milvus",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "collection_key": "code_memory",
                "collection_name": "mcp_client_code_memory_v1",
                "row_count": 128,
                "available": True,
            }
        }
    )


class MemoryRowCountsResponse(BaseModel):
    """Summary returned by the admin row-count diagnostics endpoint."""

    success: bool = Field(
        ...,
        description="Whether the endpoint completed without request-level errors",
    )
    generation: str = Field(
        ...,
        description="Active Milvus collection generation used for the reported counts",
    )
    counts: List[MemoryCollectionRowCount] = Field(
        default_factory=list,
        description="Per-collection row counts for the active memory collections",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "generation": "v1",
                "counts": [
                    {
                        "collection_key": "code_memory",
                        "collection_name": "mcp_client_code_memory_v1",
                        "row_count": 128,
                        "available": True,
                    },
                    {
                        "collection_key": "doc_memory",
                        "collection_name": "mcp_client_doc_memory_v1",
                        "row_count": 42,
                        "available": True,
                    },
                ],
            }
        }
    )
