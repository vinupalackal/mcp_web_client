"""
MCP Client Web - FastAPI Application
LibreChat-inspired interface for MCP server communication via JSON-RPC 2.0
"""

import logging
import os
import json
import httpx
from pathlib import Path as PathLib
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path, Body, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Optional
from datetime import datetime

from backend.models import (
    ServerConfig,
    LLMConfig,
    EnterpriseTokenRequest,
    EnterpriseTokenResponse,
    EnterpriseTokenStatusResponse,
    ChatMessage,
    ChatResponse,
    SessionConfig,
    SessionResponse,
    MessageListResponse,
    ToolSchema,
    ToolRefreshResponse,
    DeleteResponse,
    ErrorResponse,
    HealthResponse,
)

# Load environment variables from .env file
env_path = PathLib(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configure loggers (dual-logger pattern)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger_internal = logging.getLogger("mcp_client.internal")
logger_external = logging.getLogger("mcp_client.external")

# Import managers
from backend.mcp_manager import mcp_manager
from backend.llm_client import LLMClientFactory
from backend.session_manager import SessionManager

# Initialize managers
session_manager = SessionManager()

# In-memory storage
servers_storage: dict[str, ServerConfig] = {}
llm_config_storage: LLMConfig | None = None
enterprise_token_cache: dict[str, object] = {}
# Tools now managed by mcp_manager

# Persistent storage directory (credentials live here, not in the browser)
MCP_DATA_DIR = PathLib(os.getenv("MCP_DATA_DIR", "./data"))


def _save_llm_config_to_disk(config: LLMConfig) -> None:
    """Persist LLM config (including credentials) to server-side disk."""
    try:
        MCP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        (MCP_DATA_DIR / "llm_config.json").write_text(config.model_dump_json(indent=2))
        logger_internal.info(f"LLM config persisted to disk (provider={config.provider})")
    except Exception as e:
        logger_internal.error(f"Failed to persist LLM config to disk: {e}")


def _load_llm_config_from_disk() -> "LLMConfig | None":
    """Load LLM config from server-side disk on startup."""
    config_file = MCP_DATA_DIR / "llm_config.json"
    if not config_file.exists():
        return None
    try:
        config = LLMConfig.model_validate_json(config_file.read_text())
        logger_internal.info(f"Loaded LLM config from disk (provider={config.provider})")
        return config
    except Exception as e:
        logger_internal.warning(f"Failed to load LLM config from disk: {e}")
        return None


def _save_servers_to_disk() -> None:
    """Persist all MCP server configs (including tokens) to server-side disk."""
    try:
        MCP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        import json as _json
        servers_list = [_json.loads(s.model_dump_json()) for s in servers_storage.values()]
        (MCP_DATA_DIR / "servers.json").write_text(_json.dumps(servers_list, indent=2))
        logger_internal.info(f"Servers persisted to disk ({len(servers_storage)} servers)")
    except Exception as e:
        logger_internal.error(f"Failed to persist servers to disk: {e}")


def _load_servers_from_disk() -> "dict[str, ServerConfig]":
    """Load MCP server configs from server-side disk on startup."""
    servers_file = MCP_DATA_DIR / "servers.json"
    if not servers_file.exists():
        return {}
    try:
        import json as _json
        data = _json.loads(servers_file.read_text())
        loaded = {s["server_id"]: ServerConfig.model_validate(s) for s in data}
        logger_internal.info(f"Loaded {len(loaded)} servers from disk")
        return loaded
    except Exception as e:
        logger_internal.warning(f"Failed to load servers from disk: {e}")
        return {}


def _get_enterprise_token_status() -> EnterpriseTokenStatusResponse:
    """Return current enterprise token cache status."""
    if not enterprise_token_cache.get("access_token"):
        return EnterpriseTokenStatusResponse(
            token_cached=False,
            cached_at=None,
            expires_in=None
        )

    return EnterpriseTokenStatusResponse(
        token_cached=True,
        cached_at=enterprise_token_cache.get("cached_at"),
        expires_in=enterprise_token_cache.get("expires_in")
    )


def _get_cached_enterprise_token() -> str | None:
    """Get cached enterprise token if available."""
    access_token = enterprise_token_cache.get("access_token")
    return access_token if isinstance(access_token, str) and access_token else None


def _redacted_token_request_curl(token_request: EnterpriseTokenRequest) -> str:
    """Build a redacted curl equivalent for enterprise token acquisition logs."""
    return (
        "curl --location --request POST "
        f"'{token_request.token_endpoint_url}' \\\n+  --header 'Content-Type: application/json' \\\n+  --header 'X-Client-Id: [REDACTED]' \\\n+  --header 'X-Client-Secret: [REDACTED]' \\\n+  --data ''"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    global llm_config_storage
    logger_internal.info("🚀 MCP Client Web starting up")
    logger_internal.info(f"Environment: MCP_ALLOW_HTTP_INSECURE={os.getenv('MCP_ALLOW_HTTP_INSECURE', 'false')}")
    logger_internal.info(f"Data directory: {MCP_DATA_DIR.resolve()}")

    # Load persisted credentials and configs from server-side disk
    loaded_config = _load_llm_config_from_disk()
    if loaded_config:
        llm_config_storage = loaded_config
    loaded_servers = _load_servers_from_disk()
    if loaded_servers:
        servers_storage.update(loaded_servers)

    yield
    logger_internal.info("👋 MCP Client Web shutting down")


# Initialize FastAPI app
app = FastAPI(
    title="MCP Client Web API",
    version="0.2.0-jsonrpc",
    description="LibreChat-inspired MCP client with JSON-RPC 2.0 support for distributed tool execution",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS middleware (configure for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Health Check
# ============================================================================

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="API health check",
    description="Check if the API is running and responsive"
)
async def health_check() -> HealthResponse:
    """Get API health status and version information"""
    return HealthResponse(
        status="healthy",
        version="0.2.0-jsonrpc",
        timestamp=datetime.utcnow()
    )


# ============================================================================
# MCP Server Management
# ============================================================================

@app.get(
    "/api/servers",
    response_model=List[ServerConfig],
    tags=["MCP Servers"],
    summary="List all MCP servers",
    description="Retrieve all configured MCP servers from backend storage",
    responses={
        200: {"description": "List of configured servers"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)
async def list_servers() -> List[ServerConfig]:
    """Get all configured MCP servers"""
    logger_external.info("→ GET /api/servers")
    servers = list(servers_storage.values())
    logger_external.info(f"← 200 OK (found {len(servers)} servers)")
    return servers


@app.post(
    "/api/servers",
    response_model=ServerConfig,
    status_code=status.HTTP_201_CREATED,
    tags=["MCP Servers"],
    summary="Register new MCP server",
    description="Add a new MCP server configuration for tool discovery and execution",
    responses={
        201: {"description": "Server created successfully"},
        400: {"model": ErrorResponse, "description": "Invalid configuration or duplicate alias"},
        422: {"model": ErrorResponse, "description": "Validation error"}
    }
)
async def create_server(
    server: ServerConfig = Body(
        ...,
        description="MCP server configuration",
        openapi_examples={
            "local": {
                "summary": "Local MCP server",
                "value": {
                    "alias": "local_tools",
                    "base_url": "http://localhost:3000",
                    "auth_type": "none",
                    "timeout_ms": 15000
                }
            },
            "remote": {
                "summary": "Remote MCP server with auth",
                "value": {
                    "alias": "weather_api",
                    "base_url": "http://192.168.1.100:3000",
                    "auth_type": "bearer",
                    "bearer_token": "secret-token",
                    "timeout_ms": 20000
                }
            }
        }
    )
) -> ServerConfig:
    """
    Register a new MCP server for tool discovery and execution.
    
    The server will be initialized via JSON-RPC handshake and tools
    will be discovered automatically.
    """
    logger_external.info(f"→ POST /api/servers (alias={server.alias})")
    
    # Check for duplicate server_id (for sync from localStorage)
    if server.server_id and server.server_id in servers_storage:
        logger_internal.info(f"Server already exists: {server.alias} ({server.server_id})")
        logger_external.info(f"← 409 Conflict (already exists)")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Server '{server.server_id}' already exists"
        )
    
    # Check for duplicate alias
    if any(s.alias == server.alias for s in servers_storage.values()):
        logger_internal.warning(f"Duplicate alias rejected: {server.alias}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Server with alias '{server.alias}' already exists"
        )
    
    # Validate HTTPS in production
    if not server.base_url.startswith("https://"):
        if os.getenv("MCP_ALLOW_HTTP_INSECURE", "false").lower() != "true":
            logger_internal.warning(f"HTTP URL rejected (production mode): {server.base_url}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="HTTP URLs not allowed in production. Set MCP_ALLOW_HTTP_INSECURE=true for development."
            )
    
    # Store server
    servers_storage[server.server_id] = server
    logger_internal.info(f"Server registered: {server.alias} ({server.server_id})")
    logger_external.info(f"← 201 Created")
    _save_servers_to_disk()
    
    # TODO: Initialize MCP server connection
    # await mcp_manager.initialize_server(server)
    
    return server


@app.put(
    "/api/servers/{server_id}",
    response_model=ServerConfig,
    tags=["MCP Servers"],
    summary="Update MCP server configuration",
    responses={
        200: {"description": "Server updated successfully"},
        404: {"model": ErrorResponse, "description": "Server not found"},
        422: {"model": ErrorResponse, "description": "Validation error"}
    }
)
async def update_server(
    server_id: str = Path(..., description="Server UUID to update"),
    server: ServerConfig = Body(..., description="Updated server configuration")
) -> ServerConfig:
    """Update an existing MCP server configuration"""
    logger_external.info(f"→ PUT /api/servers/{server_id}")
    
    if server_id not in servers_storage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found"
        )
    
    # Preserve server_id from path
    server.server_id = server_id
    servers_storage[server_id] = server
    logger_internal.info(f"Server updated: {server.alias} ({server_id})")
    logger_external.info(f"← 200 OK")
    _save_servers_to_disk()
    
    return server


@app.delete(
    "/api/servers/{server_id}",
    response_model=DeleteResponse,
    status_code=status.HTTP_200_OK,
    tags=["MCP Servers"],
    summary="Delete MCP server",
    responses={
        200: {"description": "Server deleted successfully"},
        404: {"model": ErrorResponse, "description": "Server not found"}
    }
)
async def delete_server(
    server_id: str = Path(..., description="Server UUID to delete")
) -> DeleteResponse:
    """Delete an MCP server configuration and its associated tools"""
    logger_external.info(f"→ DELETE /api/servers/{server_id}")
    
    if server_id not in servers_storage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Server {server_id} not found"
        )
    
    server = servers_storage.pop(server_id)
    logger_internal.info(f"Server deleted: {server.alias} ({server_id})")
    
    # Remove associated tools from mcp_manager
    tools_to_remove = [
        tool_id for tool_id, tool in mcp_manager.tools.items()
        if tool.server_alias == server.alias
    ]
    for tool_id in tools_to_remove:
        del mcp_manager.tools[tool_id]
    logger_internal.info(f"Removed {len(tools_to_remove)} tools for {server.alias}")
    
    logger_external.info(f"← 200 OK")
    _save_servers_to_disk()
    return DeleteResponse(
        success=True,
        message=f"Server '{server.alias}' deleted successfully"
    )


@app.post(
    "/api/servers/refresh-tools",
    response_model=ToolRefreshResponse,
    tags=["MCP Servers"],
    summary="Refresh tool discovery",
    description="Discover tools from all configured MCP servers via JSON-RPC",
    responses={
        200: {"description": "Tools refreshed successfully"},
        500: {"model": ErrorResponse, "description": "Refresh failed"}
    }
)
async def refresh_tools() -> ToolRefreshResponse:
    """Discover tools from all configured MCP servers"""
    logger_external.info("→ POST /api/servers/refresh-tools")
    
    servers = list(servers_storage.values())
    
    if not servers:
        logger_internal.warning("No servers configured for tool refresh")
        return ToolRefreshResponse(
            total_tools=0,
            servers_refreshed=0,
            errors=["No MCP servers configured"]
        )
    
    logger_internal.info(f"Tool refresh initiated for {len(servers)} servers")
    
    # Use MCP Manager to discover tools
    total_tools, servers_refreshed, errors = await mcp_manager.discover_all_tools(servers)

    error_aliases = {
        error.split(":", 1)[0].strip()
        for error in errors
        if ":" in error
    }
    checked_at = datetime.utcnow()
    for server in servers:
        server.last_health_check = checked_at
        server.health_status = "unhealthy" if server.alias in error_aliases else "healthy"
    
    logger_internal.info(
        f"Tool refresh complete: {total_tools} tools from {servers_refreshed}/{len(servers)} servers"
    )
    logger_external.info(f"← 200 OK (discovered {total_tools} tools)")
    
    return ToolRefreshResponse(
        total_tools=total_tools,
        servers_refreshed=servers_refreshed,
        errors=errors
    )


# ============================================================================
# Tool Management
# ============================================================================

@app.get(
    "/api/tools",
    response_model=List[ToolSchema],
    tags=["Tools"],
    summary="List all discovered tools",
    description="Get all tools discovered from MCP servers with namespaced IDs",
    responses={
        200: {"description": "List of discovered tools"}
    }
)
async def list_tools() -> List[ToolSchema]:
    """Get all discovered tools from MCP servers"""
    logger_external.info("→ GET /api/tools")
    tools = mcp_manager.get_all_tools()
    logger_external.info(f"← 200 OK (found {len(tools)} tools)")
    return tools


# ============================================================================
# LLM Configuration
# ============================================================================

@app.get(
    "/api/llm/config",
    response_model=LLMConfig,
    tags=["LLM"],
    summary="Get LLM configuration",
    responses={
        200: {"description": "Current LLM configuration"},
        404: {"model": ErrorResponse, "description": "No configuration set"}
    }
)
async def get_llm_config() -> LLMConfig:
    """Get current LLM provider configuration"""
    logger_external.info("→ GET /api/llm/config")
    
    if llm_config_storage is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LLM configuration not set"
        )
    
    logger_external.info(f"← 200 OK (provider={llm_config_storage.provider})")
    return llm_config_storage


@app.post(
    "/api/llm/config",
    response_model=LLMConfig,
    tags=["LLM"],
    summary="Save LLM configuration",
    description="Configure LLM provider (OpenAI, Ollama, Mock, or Enterprise Gateway)",
    responses={
        200: {"description": "Configuration saved successfully"},
        422: {"model": ErrorResponse, "description": "Validation error"}
    }
)
async def save_llm_config(
    config: LLMConfig = Body(..., description="LLM provider configuration")
) -> LLMConfig:
    """Save LLM provider configuration"""
    global llm_config_storage
    
    logger_external.info(f"→ POST /api/llm/config (provider={config.provider})")
    logger_internal.info(f"LLM config saved: {config.provider} / {config.model}")

    if config.provider == "enterprise":
        previous_enterprise = llm_config_storage if llm_config_storage and llm_config_storage.provider == "enterprise" else None
        if previous_enterprise and (
            previous_enterprise.client_id != config.client_id
            or previous_enterprise.token_endpoint_url != config.token_endpoint_url
            or previous_enterprise.base_url != config.base_url
        ):
            enterprise_token_cache.clear()
            logger_internal.info("Cleared enterprise token cache due to configuration change")
    
    llm_config_storage = config
    logger_external.info(f"← 200 OK")
    _save_llm_config_to_disk(config)
    
    return config


@app.post(
    "/api/enterprise/token",
    response_model=EnterpriseTokenResponse,
    tags=["LLM"],
    summary="Acquire enterprise bearer token",
    description="Request an OAuth bearer token for Enterprise Gateway usage and cache it in memory",
    responses={
        200: {"description": "Token acquired successfully"},
        422: {"model": ErrorResponse, "description": "Validation error"},
        502: {"model": ErrorResponse, "description": "Upstream token endpoint failure"}
    }
)
async def acquire_enterprise_token(
    token_request: EnterpriseTokenRequest = Body(..., description="Enterprise token request")
) -> EnterpriseTokenResponse:
    """Acquire and cache enterprise OAuth token."""
    logger_external.info("→ POST /api/enterprise/token")
    logger_external.debug("[enterprise] token request curl equivalent:\n%s", _redacted_token_request_curl(token_request))

    timeout = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
    headers = {
        "Content-Type": "application/json",
        "X-Client-Id": token_request.client_id,
        "X-Client-Secret": token_request.client_secret,
    }

    try:
        logger_external.info(f"→ POST {token_request.token_endpoint_url}")
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(token_request.token_endpoint_url, content="", headers=headers)
            response.raise_for_status()
            payload = response.json()
        logger_external.info(f"← {response.status_code} OK")

        access_token = payload.get("access_token")
        if not access_token:
            logger_internal.error("Enterprise token endpoint response missing access_token")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Token endpoint response missing access_token"
            )

        cached_at = datetime.utcnow()
        enterprise_token_cache.clear()
        enterprise_token_cache.update({
            "access_token": access_token,
            "cached_at": cached_at,
            "expires_in": payload.get("expires_in")
        })

        logger_external.info("← 200 OK (enterprise token cached)")
        return EnterpriseTokenResponse(
            token_acquired=True,
            expires_in=payload.get("expires_in"),
            cached_at=cached_at,
            error=None
        )
    except HTTPException:
        raise
    except httpx.TimeoutException:
        logger_internal.error("Enterprise token endpoint timeout")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Token endpoint request timed out"
        )
    except httpx.HTTPStatusError as e:
        logger_internal.error(f"Enterprise token endpoint HTTP error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Token endpoint returned {e.response.status_code}"
        )
    except httpx.HTTPError as e:
        logger_internal.error(f"Enterprise token endpoint error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to reach token endpoint"
        )


@app.get(
    "/api/enterprise/token/status",
    response_model=EnterpriseTokenStatusResponse,
    tags=["LLM"],
    summary="Get enterprise token cache status",
    responses={
        200: {"description": "Token cache status returned successfully"}
    }
)
async def get_enterprise_token_status() -> EnterpriseTokenStatusResponse:
    """Get enterprise token cache status."""
    logger_external.info("→ GET /api/enterprise/token/status")
    status_response = _get_enterprise_token_status()
    logger_external.info(f"← 200 OK (cached={status_response.token_cached})")
    return status_response


@app.delete(
    "/api/enterprise/token",
    response_model=DeleteResponse,
    tags=["LLM"],
    summary="Clear cached enterprise token",
    responses={
        200: {"description": "Token cache cleared successfully"}
    }
)
async def delete_enterprise_token() -> DeleteResponse:
    """Clear cached enterprise token metadata and token value."""
    logger_external.info("→ DELETE /api/enterprise/token")
    enterprise_token_cache.clear()
    logger_external.info("← 200 OK")
    return DeleteResponse(success=True, message="Enterprise token cache cleared")


# ============================================================================
# Session & Chat Management
# ============================================================================

@app.post(
    "/api/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Chat"],
    summary="Create new chat session",
    description="Initialize a new conversation session with LLM and MCP configuration",
    responses={
        201: {"description": "Session created successfully"},
        400: {"model": ErrorResponse, "description": "Invalid configuration"}
    }
)
async def create_session(
    config: Optional[SessionConfig] = Body(None, description="Session configuration (optional)")
) -> SessionResponse:
    """Create a new chat session"""
    logger_external.info("→ POST /api/sessions")
    
    # Create session via SessionManager
    session = session_manager.create_session()
    
    logger_internal.info(f"Session created: {session.session_id}")
    logger_external.info(f"← 201 Created")
    
    return SessionResponse(
        session_id=session.session_id,
        created_at=session.created_at
    )


@app.post(
    "/api/sessions/{session_id}/messages",
    response_model=ChatResponse,
    tags=["Chat"],
    summary="Send chat message",
    description="Send a user message and receive assistant response with tool execution",
    responses={
        200: {"description": "Message processed successfully"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        422: {"model": ErrorResponse, "description": "Validation error"}
    }
)
async def send_message(
    session_id: str = Path(..., description="Session UUID"),
    message: ChatMessage = Body(..., description="User message")
) -> ChatResponse:
    """Process user message through LLM with tool execution"""
    logger_external.info(f"→ POST /api/sessions/{session_id}/messages")
    logger_internal.info(f"Processing message in session {session_id}: {message.content[:50] if message.content else ''}...")

    if not message.content.strip():
        logger_internal.warning("Rejected empty message content")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message content must not be empty"
        )
    
    # Add user message to session
    session_manager.add_message(session_id, message)
    
    # Check LLM config
    if not llm_config_storage:
        logger_internal.warning("No LLM config found")
        response_message = ChatMessage(
            role="assistant",
            content="Please configure an LLM provider in Settings."
        )
        session_manager.add_message(session_id, response_message)
        return ChatResponse(
            session_id=session_id,
            message=response_message,
            tool_executions=[]
        )
    
    try:
        # Create LLM client
        enterprise_access_token = None
        if llm_config_storage.provider == "enterprise":
            enterprise_access_token = _get_cached_enterprise_token()
            if not enterprise_access_token:
                logger_internal.warning("Enterprise provider selected without cached token")
                response_message = ChatMessage(
                    role="assistant",
                    content="Please fetch an Enterprise Gateway token in Settings before sending messages."
                )
                session_manager.add_message(session_id, response_message)
                return ChatResponse(
                    session_id=session_id,
                    message=response_message,
                    tool_executions=[]
                )

        llm_client = LLMClientFactory.create(
            llm_config_storage,
            enterprise_access_token=enterprise_access_token
        )
        
        # Get available tools
        tools_for_llm = mcp_manager.get_tools_for_llm()
        logger_internal.info(f"Available tools for LLM: {len(tools_for_llm)} tools")
        if tools_for_llm:
            tool_names = [t["function"]["name"] for t in tools_for_llm]
            logger_internal.info(f"Tool names: {', '.join(tool_names)}")
        else:
            logger_internal.warning("No tools available! LLM will not be able to call any tools.")
        
        # Get conversation history (pass provider for correct message formatting)
        messages_for_llm = session_manager.get_messages_for_llm(
            session_id, 
            provider=llm_config_storage.provider
        )
        
        # Add system message to guide LLM behavior with tool results
        system_message = {
            "role": "system",
            "content": """You are a helpful AI assistant with access to MCP (Model Context Protocol) tools.

**When you receive tool execution results, always:**
1. **Explain what you found** - Describe the tool output in clear, understandable terms
2. **Provide context** - Explain what the data means and why it matters
3. **Highlight key information** - Point out important values, patterns, or anomalies
4. **Be specific** - Reference actual values and details from the tool output

**For errors or failures:**
1. Explain what went wrong based on the error message
2. Identify possible causes
3. Suggest specific next steps or alternative tools

**For successful results:**
- Don't just repeat raw data
- Interpret and explain what the information means
- Help the user understand the significance of the results
- Organize complex data in a readable format

Always aim to make technical information accessible and actionable."""
        }
        
        # Insert system message at the beginning if not already present
        if not messages_for_llm or messages_for_llm[0].get("role") != "system":
            messages_for_llm.insert(0, system_message)
        
        # Multi-turn loop for tool calling
        max_turns = int(os.getenv("MCP_MAX_TOOL_CALLS_PER_TURN", "8"))
        tool_executions = []
        
        for turn in range(max_turns):
            logger_internal.info(f"Turn {turn + 1}/{max_turns}")
            
            # Log request to LLM
            logger_external.info(f"→ LLM Request: {len(messages_for_llm)} messages, {len(tools_for_llm)} tools available")
            logger_internal.info(f"Messages to LLM: {json.dumps(messages_for_llm, indent=2)}")
            if tools_for_llm:
                logger_internal.info(f"Tools sent to LLM: {json.dumps(tools_for_llm, indent=2)}")
            
            # Call LLM
            llm_response = await llm_client.chat_completion(
                messages=messages_for_llm,
                tools=tools_for_llm
            )
            
            # Extract assistant message
            assistant_msg = llm_response["choices"][0]["message"]
            finish_reason = llm_response["choices"][0]["finish_reason"]
            
            # Log response from LLM
            logger_external.info(f"← LLM Response: finish_reason={finish_reason}, has_tool_calls={'tool_calls' in assistant_msg}")
            logger_internal.info(f"LLM Response: {json.dumps(llm_response, indent=2)}")
            logger_internal.info(f"LLM finish_reason: {finish_reason}")
            logger_internal.info(f"LLM message has tool_calls: {'tool_calls' in assistant_msg}")
            
            # Check if LLM wants to call tools
            if finish_reason == "tool_calls" and "tool_calls" in assistant_msg:
                num_tool_calls = len(assistant_msg['tool_calls'])
                logger_internal.info(f"LLM requested {num_tool_calls} tool call{'s' if num_tool_calls > 1 else ''}")
                
                if num_tool_calls > 1:
                    tool_names = [tc["function"]["name"] for tc in assistant_msg["tool_calls"]]
                    logger_internal.info(f"Multiple tools will be executed: {', '.join(tool_names)}")
                
                # Store assistant message with tool calls
                from backend.models import ToolCall, FunctionCall
                tool_calls_models = []
                for tc in assistant_msg["tool_calls"]:
                    # Convert arguments to JSON string if it's a dict (Ollama format)
                    arguments = tc["function"]["arguments"]
                    if isinstance(arguments, dict):
                        arguments = json.dumps(arguments)
                    
                    tool_calls_models.append(
                        ToolCall(
                            id=tc["id"],
                            type="function",
                            function=FunctionCall(
                                name=tc["function"]["name"],
                                arguments=arguments
                            )
                        )
                    )
                
                assistant_message_obj = ChatMessage(
                    role="assistant",
                    content=assistant_msg.get("content"),
                    tool_calls=tool_calls_models
                )
                session_manager.add_message(session_id, assistant_message_obj)
                messages_for_llm.append(assistant_msg)
                
                # Execute tool calls
                for idx, tool_call in enumerate(assistant_msg["tool_calls"], 1):
                    tool_id = tool_call["id"]
                    namespaced_tool_name = tool_call["function"]["name"]
                    arguments_str = tool_call["function"]["arguments"]
                    
                    logger_internal.info(f"Executing tool {idx}/{num_tool_calls}: {namespaced_tool_name}")
                    
                    # Parse arguments
                    try:
                        arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
                    except json.JSONDecodeError:
                        arguments = {}
                    
                    # Parse namespaced tool name (server_alias__tool_name)
                    if "__" not in namespaced_tool_name:
                        logger_internal.error(f"Invalid tool name format: {namespaced_tool_name}")
                        continue
                    
                    server_alias, actual_tool_name = namespaced_tool_name.split("__", 1)
                    
                    # Find server by alias
                    server = None
                    for s in servers_storage.values():
                        if s.alias == server_alias:
                            server = s
                            break
                    
                    if not server:
                        logger_internal.error(f"Server not found: {server_alias}")
                        result_content = f"Error: Server '{server_alias}' not found"
                    else:
                        # Execute tool
                        try:
                            import time
                            start_time = time.time()
                            
                            tool_result = await mcp_manager.execute_tool(
                                server=server,
                                tool_name=actual_tool_name,
                                arguments=arguments
                            )
                            
                            duration_ms = int((time.time() - start_time) * 1000)
                            
                            # Truncate large results
                            max_chars = int(os.getenv("MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM", "12000"))
                            result_str = json.dumps(tool_result)
                            if len(result_str) > max_chars:
                                result_str = result_str[:max_chars] + "... [truncated]"
                            
                            result_content = result_str
                            
                            # Track execution
                            tool_executions.append({
                                "tool": namespaced_tool_name,
                                "arguments": arguments,
                                "result": tool_result,
                                "success": True,
                                "duration_ms": duration_ms
                            })
                            
                            # Trace successful execution
                            session_manager.add_tool_trace(
                                session_id=session_id,
                                tool_name=namespaced_tool_name,
                                arguments=arguments,
                                result=tool_result,
                                success=True
                            )
                            
                        except Exception as e:
                            duration_ms = int((time.time() - start_time) * 1000) if 'start_time' in locals() else 0
                            logger_internal.error(f"Tool execution error: {e}")
                            result_content = f"Error: {str(e)}"
                            
                            # Track execution
                            tool_executions.append({
                                "tool": namespaced_tool_name,
                                "arguments": arguments,
                                "result": str(e),
                                "success": False,
                                "duration_ms": duration_ms
                            })
                            
                            # Trace failed execution
                            session_manager.add_tool_trace(
                                session_id=session_id,
                                tool_name=namespaced_tool_name,
                                arguments=arguments,
                                result=str(e),
                                success=False
                            )
                    
                    # Format tool result message
                    tool_result_msg = llm_client.format_tool_result(
                        tool_call_id=tool_id,
                        content=result_content
                    )
                    
                    # Add to messages
                    messages_for_llm.append(tool_result_msg)
                    
                    # Store in session
                    tool_msg_obj = ChatMessage(
                        role="tool",
                        content=result_content
                    )
                    if "tool_call_id" in tool_result_msg:
                        tool_msg_obj.tool_call_id = tool_result_msg["tool_call_id"]
                    session_manager.add_message(session_id, tool_msg_obj)
                
                # Continue loop to get next LLM response
                continue
            
            # No more tool calls - final response
            else:
                logger_internal.info(f"LLM gave final response (no tool calls). Response length: {len(assistant_msg.get('content', ''))}")
                logger_internal.info(f"=== FINAL LLM MESSAGE ===\n{assistant_msg.get('content', '')}\n========================")
                
                if tool_executions:
                    tools_summary = ', '.join([f"{te['tool']} ({'success' if te['success'] else 'failed'})" for te in tool_executions])
                    logger_internal.info(f"Tools executed in this turn ({len(tool_executions)}): {tools_summary}")
                
                final_response = ChatMessage(
                    role="assistant",
                    content=assistant_msg.get("content", "")
                )
                session_manager.add_message(session_id, final_response)
                logger_internal.info("Conversation turn completed")
                logger_external.info("← 200 OK")
                
                return ChatResponse(
                    session_id=session_id,
                    message=final_response,
                    tool_executions=tool_executions
                )
        
        # Max turns reached
        logger_internal.warning(f"Max tool call turns ({max_turns}) reached")
        fallback = ChatMessage(
            role="assistant",
            content="I've reached the maximum number of tool calls. Please start a new conversation."
        )
        session_manager.add_message(session_id, fallback)
        logger_external.info("← 200 OK")
        
        return ChatResponse(
            session_id=session_id,
            message=fallback,
            tool_executions=tool_executions
        )
        
    except Exception as e:
        logger_internal.error(f"Error processing message: {e}")
        error_response = ChatMessage(
            role="assistant",
            content=f"Sorry, I encountered an error: {str(e)}"
        )
        session_manager.add_message(session_id, error_response)
        logger_external.info("← 200 OK (error)")
        
        return ChatResponse(
            session_id=session_id,
            message=error_response,
            tool_executions=[]
        )


@app.get(
    "/api/sessions/{session_id}/messages",
    response_model=MessageListResponse,
    tags=["Chat"],
    summary="Get message history",
    description="Retrieve all messages in a session",
    responses={
        200: {"description": "Message history retrieved"},
        404: {"model": ErrorResponse, "description": "Session not found"}
    }
)
async def get_messages(
    session_id: str = Path(..., description="Session UUID")
) -> MessageListResponse:
    """Get conversation history for a session"""
    logger_external.info(f"→ GET /api/sessions/{session_id}/messages")
    
    # TODO: Get messages from SessionManager
    # messages = await session_manager.get_messages(session_id)
    
    logger_external.info(f"← 200 OK")
    
    return MessageListResponse(
        session_id=session_id,
        messages=[]
    )


# ============================================================================
# Static Files & Frontend
# ============================================================================

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
async def serve_frontend():
    """Serve the main frontend HTML"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        return {"message": "MCP Client Web API - Frontend not yet deployed. Access API docs at /docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
