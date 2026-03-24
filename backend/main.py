"""
MCP Client Web - FastAPI Application
LibreChat-inspired interface for MCP server communication via JSON-RPC 2.0
"""

import logging
import os
import json
import re
import sys
import httpx
from pathlib import Path as PathLib
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path, Body, status, Request, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Any, List, Optional, Dict
from datetime import datetime


CURRENT_DIR = PathLib(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
    ToolTestPrompt,
    ToolTestOutputRequest,
    ToolTestOutputResponse,
    ToolRefreshResponse,
    ServerHealthRefreshResponse,
    DeleteResponse,
    ErrorResponse,
    HealthResponse,
    RepeatedExecSummary,
    UserProfile,
    UserSettings,
    UserSettingsPatch,
    AdminUserPatch,
    UserListResponse,
)

# SSO imports (v0.4.0-sso-user-settings)
try:
    from backend.database import init_db, upsert_user, get_user_by_id
    from backend.database import UserRow, SessionLocal
except ModuleNotFoundError as exc:
    if exc.name == "sqlalchemy":
        raise RuntimeError(
            "Missing required dependency 'sqlalchemy'. Activate the project's virtual "
            "environment and install dependencies with 'python -m pip install -r requirements.txt'. "
            "If you launch via uvicorn, prefer 'python -m uvicorn backend.main:app --reload'."
        ) from exc
    raise

from backend.user_store import (
    UserScopedLLMConfigStore,
    UserScopedServerStore,
    UserSettingsStore,
)
from backend.auth.jwt_utils import issue_app_token, verify_app_token
from backend.auth.pkce import generate_pkce_pair, generate_state_token

# Conditionally import SSO providers (only if configured)
_sso_providers: Dict[str, object] = {}

def _load_sso_providers() -> None:
    """Load whichever OIDC providers have all required env vars configured."""
    try:
        from backend.auth.azure_ad import AzureADProvider
        if AzureADProvider.is_configured():
            _sso_providers["azure_ad"] = AzureADProvider()
            logger_internal.info("SSO: Azure AD provider loaded")
    except Exception as exc:
        logger_internal.debug(f"Azure AD provider not loaded: {exc}")

    try:
        from backend.auth.google import GoogleProvider
        if GoogleProvider.is_configured():
            _sso_providers["google"] = GoogleProvider()
            logger_internal.info("SSO: Google provider loaded")
    except Exception as exc:
        logger_internal.debug(f"Google provider not loaded: {exc}")


def _sso_enabled() -> bool:
    """Return True when SSO is fully configured (SECRET_KEY + at least one IdP)."""
    return bool(os.getenv("SECRET_KEY")) and bool(_sso_providers)


# Per-user store singletons (used when SSO is active)
_llm_store = UserScopedLLMConfigStore()
_server_store = UserScopedServerStore()
_settings_store = UserSettingsStore()

# In-memory PKCE state store: state_token → {nonce, code_verifier, provider}
# (per-process; cleared on restart — PKCE flows are short-lived)
_pkce_state: Dict[str, dict] = {}

# Admin emails allowlist (comma-separated in env)
def _get_admin_emails() -> list:
    raw = os.getenv("SSO_ADMIN_EMAILS", "")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]

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
llm_config_storage: Optional[LLMConfig] = None
enterprise_token_cache: dict[str, object] = {}
# Tools now managed by mcp_manager

# Persistent storage directory (credentials live here, not in the browser)
MCP_DATA_DIR = PathLib(os.getenv("MCP_DATA_DIR", "./data"))
USAGE_EXAMPLES_PATH = PROJECT_ROOT / "docs" / "USAGE-EXAMPLES.md"


def _load_tool_test_prompts() -> List[ToolTestPrompt]:
    """Parse documented example user prompts from USAGE-EXAMPLES.md."""
    if not USAGE_EXAMPLES_PATH.exists():
        logger_internal.warning("Usage examples file not found: %s", USAGE_EXAMPLES_PATH)
        return []

    try:
        lines = USAGE_EXAMPLES_PATH.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger_internal.error("Failed to read usage examples file: %s", exc)
        return []

    prompts: List[ToolTestPrompt] = []
    seen_tool_names: set[str] = set()
    current_tool_name: Optional[str] = None
    heading_pattern = re.compile(r"^##+\s+.*`([^`]+)`\s*$")

    line_index = 0
    while line_index < len(lines):
        stripped_line = lines[line_index].strip()
        heading_match = heading_pattern.match(stripped_line)
        if heading_match:
            current_tool_name = heading_match.group(1).strip()
            line_index += 1
            continue

        if stripped_line == "**User prompt**" and current_tool_name:
            prompt_start = line_index + 1
            while prompt_start < len(lines) and not lines[prompt_start].lstrip().startswith(">"):
                if lines[prompt_start].strip() and not lines[prompt_start].lstrip().startswith(">"):
                    break
                prompt_start += 1

            prompt_lines: List[str] = []
            while prompt_start < len(lines):
                prompt_line = lines[prompt_start].lstrip()
                if not prompt_line.startswith(">"):
                    break
                prompt_lines.append(prompt_line[1:].lstrip())
                prompt_start += 1

            prompt_text = "\n".join(prompt_lines).strip()
            if prompt_text and current_tool_name not in seen_tool_names:
                prompts.append(ToolTestPrompt(tool_name=current_tool_name, prompt=prompt_text))
                seen_tool_names.add(current_tool_name)

            current_tool_name = None
            line_index = prompt_start
            continue

        line_index += 1

    return prompts


def _write_tool_test_output(content: str) -> ToolTestOutputResponse:
    """Persist Tool Tester results to data/output.txt."""
    MCP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MCP_DATA_DIR / "output.txt"
    normalized_content = content.rstrip() + "\n"
    output_path.write_text(normalized_content, encoding="utf-8")
    updated_at = datetime.utcnow()
    try:
        relative_path = output_path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        relative_path = output_path
    return ToolTestOutputResponse(
        file_path=str(relative_path),
        bytes_written=len(normalized_content.encode("utf-8")),
        updated_at=updated_at,
    )


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


def _get_cached_enterprise_token() -> Optional[str]:
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

    # Initialise DB schema (creates tables if not present)
    try:
        init_db()
    except Exception as exc:
        logger_internal.error(f"DB init failed: {exc}")

    # Load SSO providers
    _load_sso_providers()
    if _sso_enabled():
        logger_internal.info(
            f"SSO enabled with providers: {list(_sso_providers.keys())}"
        )
    else:
        logger_internal.info("SSO not configured — running in single-user mode")

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


# ---------------------------------------------------------------------------
# Auth middleware — validates app_token cookie on /api/* routes when SSO is on
# ---------------------------------------------------------------------------

_SSO_SKIP_PREFIXES = (
    "/auth/",
    "/static/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/login",
    "/api/health",
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Attach current_user to request.state when SSO is active."""
    if not _sso_enabled():
        request.state.current_user = None
        return await call_next(request)

    path = request.url.path
    if any(path.startswith(p) for p in _SSO_SKIP_PREFIXES):
        request.state.current_user = None
        return await call_next(request)

    token = request.cookies.get("app_token")
    if not token:
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )
        return RedirectResponse(url="/login", status_code=302)

    import jwt as _jwt
    try:
        claims = verify_app_token(token)
    except _jwt.ExpiredSignatureError:
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Session expired"},
            )
        return RedirectResponse(url="/login?reason=session_expired", status_code=302)
    except _jwt.InvalidTokenError:
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )
        return RedirectResponse(url="/login", status_code=302)

    user = get_user_by_id(claims["sub"])
    if user is None or not user.is_active:
        if path.startswith("/api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "Account disabled"},
            )
        return RedirectResponse(url="/login", status_code=302)

    request.state.current_user = user
    return await call_next(request)


# ---------------------------------------------------------------------------
# FastAPI dependency helpers
# ---------------------------------------------------------------------------

def _get_current_user(request: Request) -> Optional[UserRow]:
    """Return current_user or None (no-op in single-user mode)."""
    return getattr(request.state, "current_user", None)


def _require_user(request: Request) -> UserRow:
    """Raise 401 if not authenticated (only enforced when SSO is enabled)."""
    user = getattr(request.state, "current_user", None)
    if _sso_enabled() and user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user  # type: ignore[return-value]


def _require_admin(request: Request) -> UserRow:
    """Raise 403 if user is not an admin."""
    user = _require_user(request)
    if user is not None:
        import json as _json
        roles = _json.loads(user.roles) if isinstance(user.roles, str) else (user.roles or [])
        if "admin" not in roles:
            raise HTTPException(status_code=403, detail="Admin role required")
    return user  # type: ignore[return-value]


def _user_id_or_none(request: Request) -> Optional[str]:
    user = getattr(request.state, "current_user", None)
    return user.user_id if user else None


def _make_user_profile(row: UserRow) -> UserProfile:
    import json as _json
    roles = _json.loads(row.roles) if isinstance(row.roles, str) else (row.roles or ["user"])
    return UserProfile(
        user_id=row.user_id,
        email=row.email,
        display_name=row.display_name,
        avatar_url=row.avatar_url,
        roles=roles,
        created_at=row.created_at,
        last_login_at=row.last_login_at,
    )


# Helper: resolve servers — per-user when SSO, global dict otherwise
def _get_user_servers(user_id: Optional[str]) -> List[ServerConfig]:
    if user_id:
        return _server_store.list(user_id)
    return list(servers_storage.values())


def _get_user_llm_config(user_id: Optional[str]) -> Optional[LLMConfig]:
    if user_id:
        return _llm_store.get_full(user_id)
    return llm_config_storage


# ============================================================================
# Login page route
# ============================================================================

@app.get("/login", include_in_schema=False)
async def login_page():
    """Serve the SSO login page."""
    login_html = PathLib(__file__).parent / "static" / "login.html"
    if login_html.exists():
        return FileResponse(str(login_html))
    return HTMLResponse("<h1>SSO not configured</h1>", status_code=503)


# ============================================================================
# Auth endpoints (OIDC flow)
# ============================================================================

@app.get("/auth/login/{provider}", tags=["Auth"], summary="Initiate OIDC login")
async def auth_login(provider: str) -> RedirectResponse:
    """Build OIDC authorisation URL and redirect the browser to the IdP."""
    p = _sso_providers.get(provider)
    if p is None:
        raise HTTPException(status_code=404, detail=f"SSO provider '{provider}' not configured")

    from backend.auth.pkce import generate_pkce_pair, generate_state_token
    code_verifier, code_challenge = generate_pkce_pair()
    state = generate_state_token()
    nonce = generate_state_token()

    _pkce_state[state] = {
        "nonce": nonce,
        "code_verifier": code_verifier,
        "provider": provider,
    }

    auth_url = p.build_authorisation_url(state=state, nonce=nonce, code_challenge=code_challenge)
    return RedirectResponse(url=auth_url, status_code=302)


@app.get("/auth/callback/{provider}", tags=["Auth"], summary="Handle OIDC redirect callback")
async def auth_callback(
    provider: str,
    request: Request,
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
) -> RedirectResponse:
    """Exchange authorisation code for tokens; issue app session cookie."""
    if error:
        return RedirectResponse(url=f"/login?reason={error}", status_code=302)

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    pkce = _pkce_state.pop(state, None)
    if pkce is None:
        raise HTTPException(status_code=401, detail="Invalid or expired state — possible CSRF")

    if pkce["provider"] != provider:
        raise HTTPException(status_code=401, detail="Provider mismatch")

    p = _sso_providers.get(provider)
    if p is None:
        raise HTTPException(status_code=404, detail=f"SSO provider '{provider}' not configured")

    try:
        token_response = await p.exchange_code(code=code, code_verifier=pkce["code_verifier"])
        id_token = token_response.get("id_token")
        if not id_token:
            raise ValueError("No id_token in token response")
        user_info = await p.validate_id_token(id_token=id_token, nonce=pkce["nonce"])
    except Exception as exc:
        logger_internal.warning(f"OIDC callback failed ({provider}): {exc}")
        return RedirectResponse(url="/login?reason=auth_failed", status_code=302)

    user_row = upsert_user(
        provider=provider,
        provider_sub=user_info.sub,
        email=user_info.email,
        display_name=user_info.display_name,
        avatar_url=user_info.avatar_url,
        admin_emails=_get_admin_emails(),
    )

    import json as _json
    roles = _json.loads(user_row.roles) if isinstance(user_row.roles, str) else (user_row.roles or ["user"])
    ttl = int(os.getenv("SSO_SESSION_TTL_HOURS", "8"))
    app_token = issue_app_token(
        user_id=user_row.user_id,
        email=user_row.email,
        roles=roles,
        ttl_hours=ttl,
    )

    redirect = RedirectResponse(url="/?sso=ok", status_code=302)
    redirect.set_cookie(
        key="app_token",
        value=app_token,
        httponly=True,
        samesite="strict",
        max_age=ttl * 3600,
        path="/",
    )
    logger_internal.info(f"SSO login success: {user_row.email} ({provider})")
    return redirect


@app.post("/auth/logout", tags=["Auth"], summary="Log out and clear session cookie")
async def auth_logout() -> RedirectResponse:
    """Clear the app_token session cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key="app_token", path="/")
    return response


@app.get("/auth/providers", tags=["Auth"], summary="List configured SSO providers", include_in_schema=False)
async def auth_providers():
    """Return the list of configured provider keys for the login page."""
    from fastapi.responses import JSONResponse
    return JSONResponse({"providers": list(_sso_providers.keys())})


# ============================================================================
# User endpoints
# ============================================================================

@app.get(
    "/api/users/me",
    response_model=UserProfile,
    tags=["Users"],
    summary="Get current user profile",
    responses={
        200: {"description": "User profile"},
        401: {"description": "Unauthorized"},
    },
)
async def get_me(request: Request) -> UserProfile:
    """Return the authenticated user's profile."""
    user = _require_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return _make_user_profile(user)


@app.get(
    "/api/users/me/settings",
    response_model=UserSettings,
    tags=["Users"],
    summary="Get current user UI preferences",
    responses={
        200: {"description": "User settings"},
        401: {"description": "Unauthorized"},
    },
)
async def get_my_settings(request: Request) -> UserSettings:
    user = _require_user(request)
    if user is None:
        return UserSettings()
    return _settings_store.get(user.user_id)


@app.patch(
    "/api/users/me/settings",
    response_model=UserSettings,
    tags=["Users"],
    summary="Partial update current user UI preferences",
    responses={
        200: {"description": "Updated settings"},
        401: {"description": "Unauthorized"},
    },
)
async def patch_my_settings(
    request: Request,
    updates: UserSettingsPatch = Body(...),
) -> UserSettings:
    user = _require_user(request)
    if user is None:
        return UserSettings()
    return _settings_store.patch(user.user_id, updates)


# ============================================================================
# Admin endpoints
# ============================================================================

@app.get(
    "/api/admin/users",
    response_model=UserListResponse,
    tags=["Admin"],
    summary="List all users (admin only)",
    responses={
        200: {"description": "Paginated user list"},
        403: {"description": "Admin role required"},
    },
)
async def admin_list_users(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> UserListResponse:
    _require_admin(request)
    from sqlalchemy import select, func
    with SessionLocal() as db:
        from backend.database import UserRow as _UserRow
        total_result = db.execute(select(func.count()).select_from(_UserRow))
        total = total_result.scalar_one()
        rows = db.execute(
            select(_UserRow).order_by(_UserRow.created_at.desc()).limit(limit).offset(offset)
        ).scalars().all()
    return UserListResponse(
        users=[_make_user_profile(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/api/admin/users/{user_id}",
    response_model=UserProfile,
    tags=["Admin"],
    summary="Get user profile (admin only)",
    responses={
        200: {"description": "User profile"},
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
    },
)
async def admin_get_user(
    request: Request,
    user_id: str = Path(..., description="Target user UUID"),
) -> UserProfile:
    _require_admin(request)
    row = get_user_by_id(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _make_user_profile(row)


@app.patch(
    "/api/admin/users/{user_id}",
    response_model=UserProfile,
    tags=["Admin"],
    summary="Enable or disable a user (admin only)",
    responses={
        200: {"description": "Updated user profile"},
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
    },
)
async def admin_patch_user(
    request: Request,
    user_id: str = Path(..., description="Target user UUID"),
    patch: AdminUserPatch = Body(...),
) -> UserProfile:
    _require_admin(request)
    from sqlalchemy import select
    with SessionLocal() as db:
        from backend.database import UserRow as _UserRow
        row = db.get(_UserRow, user_id)
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
        row.is_active = patch.is_active
        db.commit()
        db.refresh(row)
    return _make_user_profile(row)


@app.delete(
    "/api/admin/users/{user_id}/settings",
    response_model=DeleteResponse,
    tags=["Admin"],
    summary="Reset user LLM config and preferences (admin only)",
    responses={
        200: {"description": "Settings reset"},
        403: {"description": "Admin role required"},
        404: {"description": "User not found"},
    },
)
async def admin_reset_user_settings(
    request: Request,
    user_id: str = Path(..., description="Target user UUID"),
) -> DeleteResponse:
    _require_admin(request)
    row = get_user_by_id(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    _llm_store.delete(user_id)
    _settings_store.reset(user_id)
    return DeleteResponse(success=True, message=f"Settings reset for user {user_id}")


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
async def list_servers(request: Request) -> List[ServerConfig]:
    """Get all configured MCP servers"""
    logger_external.info("→ GET /api/servers")
    user_id = _user_id_or_none(request)
    servers = _get_user_servers(user_id)
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
    request: Request,
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
    user_id = _user_id_or_none(request)
    existing_servers = _get_user_servers(user_id)

    # Check for duplicate server_id (for sync from localStorage)
    if server.server_id and any(s.server_id == server.server_id for s in existing_servers):
        logger_internal.info(f"Server already exists: {server.alias} ({server.server_id})")
        logger_external.info(f"← 409 Conflict (already exists)")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Server '{server.server_id}' already exists"
        )

    # Check for duplicate alias
    if any(s.alias == server.alias for s in existing_servers):
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
    if user_id:
        _server_store.create(user_id, server)
    else:
        servers_storage[server.server_id] = server
        _save_servers_to_disk()

    logger_internal.info(f"Server registered: {server.alias} ({server.server_id})")
    logger_external.info(f"← 201 Created")
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
    request: Request,
    server_id: str = Path(..., description="Server UUID to update"),
    server: ServerConfig = Body(..., description="Updated server configuration")
) -> ServerConfig:
    """Update an existing MCP server configuration"""
    logger_external.info(f"→ PUT /api/servers/{server_id}")
    user_id = _user_id_or_none(request)

    if user_id:
        if not _server_store.owns(user_id, server_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        server.server_id = server_id
        _server_store.update(user_id, server_id, server)
    else:
        if server_id not in servers_storage:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Server {server_id} not found")
        server.server_id = server_id
        servers_storage[server_id] = server
        _save_servers_to_disk()

    logger_internal.info(f"Server updated: {server.alias} ({server_id})")
    logger_external.info(f"← 200 OK")
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
    request: Request,
    server_id: str = Path(..., description="Server UUID to delete")
) -> DeleteResponse:
    """Delete an MCP server configuration and its associated tools"""
    logger_external.info(f"→ DELETE /api/servers/{server_id}")
    user_id = _user_id_or_none(request)

    if user_id:
        server = _server_store.get(user_id, server_id)
        if server is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        _server_store.delete(user_id, server_id)
    else:
        if server_id not in servers_storage:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Server {server_id} not found")
        server = servers_storage.pop(server_id)
        _save_servers_to_disk()

    # Remove associated tools from mcp_manager
    tools_to_remove = [
        tool_id for tool_id, tool in mcp_manager.tools.items()
        if tool.server_alias == server.alias
    ]
    for tool_id in tools_to_remove:
        del mcp_manager.tools[tool_id]
    logger_internal.info(f"Removed {len(tools_to_remove)} tools for {server.alias}")

    logger_external.info(f"← 200 OK")
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
async def refresh_tools(request: Request) -> ToolRefreshResponse:
    """Discover tools from all configured MCP servers"""
    logger_external.info("→ POST /api/servers/refresh-tools")
    user_id = _user_id_or_none(request)
    servers = _get_user_servers(user_id)
    
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
    if not _user_id_or_none(request):
        _save_servers_to_disk()
    
    logger_internal.info(
        f"Tool refresh complete: {total_tools} tools from {servers_refreshed}/{len(servers)} servers"
    )
    logger_external.info(f"← 200 OK (discovered {total_tools} tools)")
    
    return ToolRefreshResponse(
        total_tools=total_tools,
        servers_refreshed=servers_refreshed,
        errors=errors
    )


@app.post(
    "/api/servers/refresh-health",
    response_model=ServerHealthRefreshResponse,
    tags=["MCP Servers"],
    summary="Refresh server health status",
    description="Check MCP server reachability via initialize handshake without refreshing tools",
    responses={
        200: {"description": "Server health refreshed successfully"},
        500: {"model": ErrorResponse, "description": "Health refresh failed"}
    }
)
async def refresh_server_health(request: Request) -> ServerHealthRefreshResponse:
    """Refresh health status for all configured MCP servers."""
    logger_external.info("→ POST /api/servers/refresh-health")
    user_id = _user_id_or_none(request)
    servers = _get_user_servers(user_id)

    if not servers:
        logger_internal.warning("No servers configured for health refresh")
        return ServerHealthRefreshResponse(
            servers_checked=0,
            healthy_servers=0,
            unhealthy_servers=0,
            errors=["No MCP servers configured"],
            servers=[]
        )

    checked_count, healthy_servers, errors = await mcp_manager.refresh_server_health(servers)

    error_aliases = {
        error.split(":", 1)[0].strip()
        for error in errors
        if ":" in error
    }
    checked_at = datetime.utcnow()
    for server in servers:
        server.last_health_check = checked_at
        server.health_status = "unhealthy" if server.alias in error_aliases else "healthy"

    if not _user_id_or_none(request):
        _save_servers_to_disk()
    unhealthy_servers = checked_count - healthy_servers

    logger_internal.info(
        f"Server health refresh complete: {healthy_servers}/{checked_count} healthy"
    )
    logger_external.info(f"← 200 OK (checked {checked_count} servers)")

    return ServerHealthRefreshResponse(
        servers_checked=checked_count,
        healthy_servers=healthy_servers,
        unhealthy_servers=unhealthy_servers,
        errors=errors,
        servers=servers
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


@app.get(
    "/api/tools/test-prompts",
    response_model=List[ToolTestPrompt],
    tags=["Tools"],
    summary="List documented tool test prompts",
    description="Get example user prompts parsed from USAGE-EXAMPLES.md for MCP tool testing via chat",
    responses={
        200: {"description": "List of documented tool test prompts"}
    }
)
async def list_tool_test_prompts() -> List[ToolTestPrompt]:
    """Return example chat prompts for MCP tool testing."""
    logger_external.info("→ GET /api/tools/test-prompts")
    prompts = _load_tool_test_prompts()
    logger_external.info(f"← 200 OK (found {len(prompts)} prompts)")
    return prompts


@app.post(
    "/api/tools/test-results-output",
    response_model=ToolTestOutputResponse,
    tags=["Tools"],
    summary="Persist Tool Tester output.txt snapshot",
    description="Write the current MCP Tool Tester results panel to data/output.txt on the server",
    responses={
        200: {"description": "Tool Tester output.txt updated"},
        500: {"model": ErrorResponse, "description": "Failed to write output.txt"}
    }
)
async def persist_tool_test_results_output(payload: ToolTestOutputRequest) -> ToolTestOutputResponse:
    """Persist the latest Tool Tester results snapshot to output.txt."""
    logger_external.info("→ POST /api/tools/test-results-output")
    try:
        result = _write_tool_test_output(payload.content)
    except OSError as exc:
        logger_internal.error("Failed to persist Tool Tester output: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to write Tool Tester output.txt"
        ) from exc

    logger_external.info("← 200 OK (%s, %s bytes)", result.file_path, result.bytes_written)
    return result


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
async def get_llm_config(request: Request) -> LLMConfig:
    """Get current LLM provider configuration"""
    logger_external.info("→ GET /api/llm/config")
    user_id = _user_id_or_none(request)

    if user_id:
        cfg = _llm_store.get_masked(user_id)
    else:
        cfg = llm_config_storage

    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LLM configuration not set"
        )

    logger_external.info(f"← 200 OK (provider={cfg.provider})")
    return cfg


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
    request: Request,
    config: LLMConfig = Body(..., description="LLM provider configuration")
) -> LLMConfig:
    """Save LLM provider configuration"""
    global llm_config_storage

    logger_external.info(f"→ POST /api/llm/config (provider={config.provider})")
    logger_internal.info(f"LLM config saved: {config.provider} / {config.model}")

    user_id = _user_id_or_none(request)
    if user_id:
        _llm_store.set(user_id, config)
        logger_external.info(f"← 200 OK")
        return _llm_store.get_masked(user_id) or config

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
    request: Request,
    config: Optional[SessionConfig] = Body(None, description="Session configuration (optional)")
) -> SessionResponse:
    """Create a new chat session"""
    logger_external.info("→ POST /api/sessions")
    user_id = _user_id_or_none(request)

    session = session_manager.create_session(
        config=config.model_dump() if config else {"include_history": True, "enabled_servers": []},
        user_id=user_id,
    )
    
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
    request: Request,
    session_id: str = Path(..., description="Session UUID"),
    message: ChatMessage = Body(..., description="User message")
) -> ChatResponse:
    """Process user message through LLM with tool execution"""
    logger_external.info(f"→ POST /api/sessions/{session_id}/messages")
    logger_internal.info(f"Processing message in session {session_id}: {message.content[:50] if message.content else ''}...")

    user_id = _user_id_or_none(request)

    # Ownership check when SSO is active
    if user_id and _sso_enabled():
        sess = session_manager.get_session(session_id)
        if sess and sess.user_id and sess.user_id != user_id:
            raise HTTPException(status_code=403, detail="Forbidden")

    if not message.content.strip():
        logger_internal.warning("Rejected empty message content")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message content must not be empty"
        )
    
    # Add user message to session
    existing_message_count = len(session_manager.get_messages(session_id))
    session_manager.add_message(session_id, message)
    
    # Check LLM config
    active_llm_config = _get_user_llm_config(user_id)
    if not active_llm_config:
        logger_internal.warning("No LLM config found")
        response_message = ChatMessage(
            role="assistant",
            content="Please configure an LLM provider in Settings."
        )
        session_manager.add_message(session_id, response_message)
        return ChatResponse(
            session_id=session_id,
            message=response_message,
            tool_executions=[],
            initial_llm_response=None
        )
    
    try:
        # Create LLM client
        enterprise_access_token = None
        if active_llm_config.provider == "enterprise":
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
                    tool_executions=[],
                    initial_llm_response=None
                )

        llm_client = LLMClientFactory.create(
            active_llm_config,
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
        
        session = session_manager.get_session(session_id)
        include_history = True
        if session and isinstance(session.config, dict):
            include_history = session.config.get("include_history", True)

        history_start_index = 0 if include_history else existing_message_count

        # Get conversation history (pass provider for correct message formatting)
        messages_for_llm = session_manager.get_messages_for_llm(
            session_id, 
            provider=llm_config_storage.provider,
            start_index=history_start_index
        )
        
        # Add system message to guide LLM behavior with tool results
        system_message = {
            "role": "system",
            "content": """You are a helpful AI assistant with access to MCP (Model Context Protocol) tools.

**Tool usage policy:**
1. If the user asks for current server, device, network, process, log, runtime, or system information, use a relevant tool instead of answering from general knowledge.
2. If a tool can fetch real-time or environment-specific data, call the tool first and then explain the result.
3. Do not guess server state, configuration, health, uptime, memory, routes, interfaces, or capabilities when a matching tool is available.

**IMPORTANT — Call multiple tools in a single response when needed:**
4. **For every new user question, always call the relevant tools to get fresh, up-to-date data.** Do NOT answer from tool results that are already in the conversation history — those results are from earlier in this session and may be stale. Always fetch current data by calling tools again.

**IMPORTANT — Call multiple tools in a single response when needed:**
- If the user's request requires data from more than one tool (e.g. "show CPU and memory", "list processes and disk usage", "show interface stats and uptime"), you MUST call ALL the relevant tools together in your first response as parallel function calls.
- Do NOT call one tool, wait for results, then call the next. Issue all independent tool calls simultaneously in a single response.
- Example: for "show CPU and memory information" → call `get_cpu_info` AND `get_memory_info` in the same response, not sequentially.

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
        
        def rebuild_messages_for_llm() -> List[dict]:
            provider_messages = session_manager.get_messages_for_llm(
                session_id,
                provider=llm_config_storage.provider,
                start_index=history_start_index
            )
            if not provider_messages or provider_messages[0].get("role") != "system":
                provider_messages.insert(0, system_message)
            return provider_messages

        def extract_tool_calls_from_content(content: str, turn_number: int) -> List[dict]:
            """Recover tool requests when a provider returns JSON in content instead of tool_calls."""
            raw_content = (content or "").strip()
            if not raw_content:
                return []

            available_tool_names = {
                tool["function"]["name"]
                for tool in tools_for_llm
                if tool.get("type") == "function" and tool.get("function", {}).get("name")
            }
            bare_tool_name_map: Dict[str, List[str]] = {}
            for available_tool_name in available_tool_names:
                bare_tool_name = available_tool_name.split("__", 1)[-1]
                bare_tool_name_map.setdefault(bare_tool_name, []).append(available_tool_name)

            def resolve_tool_name(candidate_tool_name: str) -> Optional[str]:
                if not candidate_tool_name:
                    return None
                if candidate_tool_name in available_tool_names:
                    return candidate_tool_name

                bare_matches = bare_tool_name_map.get(candidate_tool_name, [])
                if len(bare_matches) == 1:
                    return bare_matches[0]

                return None

            def build_recovered_tool_calls(parsed_payload: Any) -> List[dict]:
                candidate_calls = parsed_payload if isinstance(parsed_payload, list) else [parsed_payload]
                recovered_tool_calls = []

                for content_index, candidate in enumerate(candidate_calls, 1):
                    if not isinstance(candidate, dict):
                        return []

                    function_payload = candidate.get("function") if isinstance(candidate.get("function"), dict) else {}
                    tool_name = candidate.get("name") or function_payload.get("name")
                    resolved_tool_name = resolve_tool_name(tool_name)
                    if not resolved_tool_name:
                        return []

                    arguments = candidate.get("parameters")
                    if arguments is None:
                        arguments = candidate.get("arguments")
                    if arguments is None:
                        arguments = function_payload.get("arguments")
                    if arguments is None:
                        arguments = {}

                    if isinstance(arguments, str):
                        arguments_str = arguments
                    else:
                        arguments_str = json.dumps(arguments)

                    recovered_tool_calls.append({
                        "id": f"content_tool_call_{turn_number}_{content_index}",
                        "type": "function",
                        "function": {
                            "name": resolved_tool_name,
                            "arguments": arguments_str,
                        },
                    })

                return recovered_tool_calls

            def extract_json_payloads(text: str) -> List[Any]:
                candidates: List[Any] = []
                decoder = json.JSONDecoder()

                try:
                    candidates.append(json.loads(text))
                except (TypeError, json.JSONDecodeError):
                    pass

                for fenced_match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE):
                    fenced_content = fenced_match.group(1).strip()
                    if not fenced_content:
                        continue
                    try:
                        candidates.append(json.loads(fenced_content))
                    except (TypeError, json.JSONDecodeError):
                        continue

                for start_index, char in enumerate(text):
                    if char not in "[{":
                        continue
                    try:
                        parsed_payload, _ = decoder.raw_decode(text[start_index:])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed_payload, (dict, list)):
                        candidates.append(parsed_payload)

                return candidates

            cleaned_content = raw_content
            if cleaned_content.startswith("**") and cleaned_content.endswith("**"):
                cleaned_content = cleaned_content[2:-2].strip()
            if cleaned_content.startswith("`") and cleaned_content.endswith("`"):
                cleaned_content = cleaned_content.strip("`").strip()
            if cleaned_content.startswith("json"):
                cleaned_content = cleaned_content[4:].strip()

            for parsed_content in extract_json_payloads(cleaned_content):
                recovered_tool_calls = build_recovered_tool_calls(parsed_content)
                if recovered_tool_calls:
                    return recovered_tool_calls

            return []

        # Insert system message at the beginning if not already present
        if not messages_for_llm or messages_for_llm[0].get("role") != "system":
            messages_for_llm.insert(0, system_message)
        
        # Multi-turn loop for tool calling
        max_turns = int(os.getenv("MCP_MAX_TOOL_CALLS_PER_TURN", "8"))
        tool_executions = []
        initial_llm_response = None
        executed_tool_results: dict[str, dict] = {}
        
        for turn in range(max_turns):
            logger_internal.info(f"Turn {turn + 1}/{max_turns}")
            # Tools are sent only on the first request. Once any tool has executed,
            # subsequent requests omit the catalog so the model focuses on summarising
            # the results. The system prompt instructs the model to call all needed
            # tools in parallel in the first response.
            tools_for_request = tools_for_llm if not tool_executions else []
            
            # Log request to LLM
            logger_external.info(
                f"→ LLM Request: {len(messages_for_llm)} messages, {len(tools_for_request)} tools sent ({len(tools_for_llm)} available)"
            )
            logger_internal.info(f"Messages to LLM: {json.dumps(messages_for_llm, indent=2)}")
            if tools_for_request:
                logger_internal.info(f"Tools sent to LLM: {json.dumps(tools_for_request, indent=2)}")
            elif tools_for_llm:
                logger_internal.info(
                    "Skipping tool catalog for follow-up LLM request because tool results are already in context"
                )
            
            # Call LLM
            llm_response = await llm_client.chat_completion(
                messages=messages_for_llm,
                tools=tools_for_request
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
            assistant_tool_calls = assistant_msg.get("tool_calls") or []
            recovered_tool_calls_from_content = []
            if not assistant_tool_calls and assistant_msg.get("content"):
                recovered_tool_calls_from_content = extract_tool_calls_from_content(
                    assistant_msg.get("content", ""),
                    turn + 1,
                )
                if recovered_tool_calls_from_content:
                    assistant_tool_calls = recovered_tool_calls_from_content
                    logger_internal.warning(
                        "Recovered %s tool call(s) from assistant content because provider returned JSON content instead of tool_calls",
                        len(assistant_tool_calls),
                    )
            has_tool_calls = len(assistant_tool_calls) > 0

            if has_tool_calls:
                assistant_content = (assistant_msg.get("content") or "").strip()
                if assistant_content and initial_llm_response is None and not recovered_tool_calls_from_content:
                    initial_llm_response = assistant_content

                if finish_reason != "tool_calls":
                    logger_internal.info(
                        "LLM returned tool_calls with non-standard finish_reason=%s; continuing with tool execution",
                        finish_reason,
                    )

                num_tool_calls = len(assistant_tool_calls)
                logger_internal.info(f"LLM requested {num_tool_calls} tool call{'s' if num_tool_calls > 1 else ''}")
                
                if num_tool_calls > 1:
                    tool_names = [tc.get("function", {}).get("name", "") for tc in assistant_tool_calls]
                    logger_internal.info(f"Multiple tools will be executed: {', '.join(tool_names)}")
                
                # Store assistant message with tool calls
                from backend.models import ToolCall, FunctionCall
                tool_calls_models = []
                normalized_tool_calls = []
                for tool_call_index, tc in enumerate(assistant_tool_calls, 1):
                    function_payload = tc.get("function", {})
                    tool_call_id = tc.get("id") or f"tool_call_{turn + 1}_{tool_call_index}"

                    # Convert arguments to JSON string if it's a dict (Ollama format)
                    arguments = function_payload.get("arguments", {})
                    if isinstance(arguments, dict):
                        arguments = json.dumps(arguments)
                    elif not isinstance(arguments, str):
                        arguments = json.dumps(arguments or {})

                    normalized_tool_calls.append({
                        "id": tool_call_id,
                        "type": tc.get("type", "function"),
                        "function": {
                            "name": function_payload.get("name", ""),
                            "arguments": arguments,
                        },
                    })
                    
                    tool_calls_models.append(
                        ToolCall(
                            id=tool_call_id,
                            type="function",
                            function=FunctionCall(
                                name=function_payload.get("name", ""),
                                arguments=arguments
                            )
                        )
                    )
                
                assistant_message_obj = ChatMessage(
                    role="assistant",
                    content="" if recovered_tool_calls_from_content else (assistant_msg.get("content") or ""),
                    tool_calls=tool_calls_models
                )
                session_manager.add_message(session_id, assistant_message_obj)

                # --- E2E turn budget advisory ---
                # Compute the worst-case wall-clock budget for this entire turn:
                #   totalTurnBudgetMs = llm_call_1 + sum(tool_budgets) + llm_call_2
                # This is purely advisory: logged so operators can size upstream
                # proxy / nginx / client-side fetch timeouts accordingly.
                llm_timeout_ms = llm_config_storage.llm_timeout_ms
                tool_budget_parts = []
                for tc in normalized_tool_calls:
                    tc_name = tc["function"].get("name", "")
                    stored_tool = mcp_manager.tools.get(tc_name)
                    hints = stored_tool.execution_hints if stored_tool else None
                    if hints:
                        budget_ms = hints.recommended_wait_ms()
                    else:
                        # Fall back to the server-level timeout_ms for this tool's server
                        tc_server_alias = tc_name.split("__", 1)[0] if "__" in tc_name else ""
                        fallback_server = next(
                            (s for s in servers_storage.values() if s.alias == tc_server_alias), None
                        )
                        budget_ms = fallback_server.timeout_ms if fallback_server else int(
                            os.getenv("MCP_REQUEST_TIMEOUT_MS", "20000")
                        )
                    tool_budget_parts.append((tc_name, budget_ms))

                total_tool_budget_ms = sum(b for _, b in tool_budget_parts)
                # Two LLM calls: the one that produced these tool_calls + the follow-up synthesis call
                total_turn_budget_ms = (2 * llm_timeout_ms) + total_tool_budget_ms
                tool_budget_str = ", ".join(
                    f"{name.split('__', 1)[-1]}({b / 1000:.0f}s)" for name, b in tool_budget_parts
                )
                logger_internal.info(
                    "E2E turn budget advisory: "
                    f"2×LLM({llm_timeout_ms / 1000:.0f}s) + tools[{tool_budget_str}] "
                    f"= {total_turn_budget_ms / 1000:.0f}s total. "
                    "Ensure upstream proxy/client timeouts exceed this value."
                )

                # Execute tool calls
                for idx, tool_call in enumerate(normalized_tool_calls, 1):
                    tool_id = tool_call["id"]
                    namespaced_tool_name = tool_call["function"].get("name", "")
                    arguments_str = tool_call["function"].get("arguments", "{}")
                    
                    logger_internal.info(f"Executing tool {idx}/{num_tool_calls}: {namespaced_tool_name}")
                    
                    # Parse arguments
                    try:
                        arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
                    except json.JSONDecodeError:
                        arguments = {}

                    dedupe_key = json.dumps({
                        "tool": namespaced_tool_name,
                        "arguments": arguments,
                    }, sort_keys=True, default=str)

                    if dedupe_key in executed_tool_results:
                        cached_execution = executed_tool_results[dedupe_key]
                        logger_internal.info(
                            "Skipping duplicate tool call in same turn: %s with arguments=%s",
                            namespaced_tool_name,
                            arguments,
                        )
                        result_content = cached_execution["result_content"]

                        tool_result_msg = llm_client.format_tool_result(
                            tool_call_id=tool_id,
                            content=result_content
                        )

                        messages_for_llm.append(tool_result_msg)

                        tool_msg_obj = ChatMessage(
                            role="tool",
                            content=result_content
                        )
                        if "tool_call_id" in tool_result_msg:
                            tool_msg_obj.tool_call_id = tool_result_msg["tool_call_id"]
                        session_manager.add_message(session_id, tool_msg_obj)
                        continue
                    
                    # ---------------------------------------------------------
                    # mcp_repeated_exec intercept (virtual client-side tool)
                    # Must be checked BEFORE the __-split guard below.
                    # ---------------------------------------------------------
                    if namespaced_tool_name == "mcp_repeated_exec":
                        logger_internal.info("Intercepted mcp_repeated_exec virtual tool call")

                        # --- Parameter validation (FR-REP-001..005) ---
                        target_tool = arguments.get("target_tool", "") if isinstance(arguments, dict) else ""
                        repeat_count_raw = arguments.get("repeat_count") if isinstance(arguments, dict) else None
                        interval_ms_raw = arguments.get("interval_ms") if isinstance(arguments, dict) else None
                        tool_arguments_raw = arguments.get("tool_arguments", {}) if isinstance(arguments, dict) else {}
                        if not isinstance(tool_arguments_raw, dict):
                            tool_arguments_raw = {}

                        validation_error: Optional[str] = None

                        if repeat_count_raw is None or interval_ms_raw is None:
                            validation_error = (
                                "`mcp_repeated_exec` requires both `repeat_count` (integer 1\u201310) "
                                "and `interval_ms` (integer \u2265 0). "
                                "Please ask the user to re-send the request with both values specified."
                            )
                        elif not isinstance(repeat_count_raw, int) or not isinstance(interval_ms_raw, int):
                            validation_error = (
                                "`mcp_repeated_exec` requires both `repeat_count` (integer 1\u201310) "
                                "and `interval_ms` (integer \u2265 0). "
                                "Please ask the user to re-send the request with both values specified."
                            )
                        elif repeat_count_raw < 1 or repeat_count_raw > 10:
                            validation_error = (
                                f"`repeat_count` must be between 1 and 10. "
                                f"Value `{repeat_count_raw}` is not allowed."
                            )
                        elif interval_ms_raw < 0:
                            validation_error = (
                                "`interval_ms` must be a non-negative integer (\u2265 0)."
                            )
                        elif not target_tool or target_tool not in mcp_manager.tools:
                            validation_error = (
                                f"Target tool `{target_tool}` is not registered. "
                                "Please refresh tools and try again."
                            )

                        if validation_error:
                            logger_internal.warning(
                                f"mcp_repeated_exec: validation failed \u2014 {validation_error}"
                            )
                            result_content = validation_error

                            tool_result_msg = llm_client.format_tool_result(
                                tool_call_id=tool_id,
                                content=result_content
                            )
                            messages_for_llm.append(tool_result_msg)
                            tool_msg_obj = ChatMessage(role="tool", content=result_content)
                            if "tool_call_id" in tool_result_msg:
                                tool_msg_obj.tool_call_id = tool_result_msg["tool_call_id"]
                            session_manager.add_message(session_id, tool_msg_obj)
                            continue

                        # --- Resolve server for target tool ---
                        repeat_count: int = repeat_count_raw
                        interval_ms: int = interval_ms_raw
                        target_server_alias = target_tool.split("__", 1)[0]
                        target_tool_name = target_tool.split("__", 1)[1]
                        target_server = next(
                            (s for s in servers_storage.values() if s.alias == target_server_alias),
                            None
                        )
                        if not target_server:
                            validation_error = (
                                f"Server `{target_server_alias}` for tool `{target_tool}` "
                                "is not registered. Please check your server configuration."
                            )
                            logger_internal.warning(f"mcp_repeated_exec: {validation_error}")
                            result_content = validation_error
                            tool_result_msg = llm_client.format_tool_result(
                                tool_call_id=tool_id, content=result_content
                            )
                            messages_for_llm.append(tool_result_msg)
                            tool_msg_obj = ChatMessage(role="tool", content=result_content)
                            if "tool_call_id" in tool_result_msg:
                                tool_msg_obj.tool_call_id = tool_result_msg["tool_call_id"]
                            session_manager.add_message(session_id, tool_msg_obj)
                            continue

                        target_hints = mcp_manager.tools[target_tool].execution_hints

                        # --- Execute repeated runs ---
                        import time as _time
                        rep_start = _time.time()
                        summary: RepeatedExecSummary
                        written_files: list
                        summary, written_files = await mcp_manager.execute_repeated(
                            server=target_server,
                            tool_name=target_tool_name,
                            tool_arguments=tool_arguments_raw,
                            repeat_count=repeat_count,
                            interval_ms=interval_ms,
                            execution_hints=target_hints,
                        )
                        rep_duration_ms = int((_time.time() - rep_start) * 1000)

                        # --- Build synthesis prompt (FR-REP-018/019/020) ---
                        max_chars = int(os.getenv("MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM", "131072"))  # default 128 KB
                        header = (
                            f"Repeated execution of `{target_tool_name}` complete.\n"
                            f"Runs: {repeat_count} | "
                            f"Interval: {interval_ms / 1000:.1f}s | "
                            f"Successful: {summary.success_count} | "
                            f"Failed: {summary.failure_count}\n"
                            "Intermediate files written and deleted after aggregation.\n\n"
                        )
                        instruction = (
                            f"\nPlease analyse trends, anomalies, and changes across these "
                            f"{repeat_count} runs. Identify patterns, note any failed runs, "
                            "and provide a diagnostic conclusion."
                        )

                        # Budget chars for run blocks (header + instruction are protected)
                        reserved = len(header) + len(instruction)
                        budget_for_runs = max(0, max_chars - reserved)

                        run_blocks = []
                        for run in summary.runs:
                            run_status = "SUCCESS" if run.success else "FAILED"
                            result_str = json.dumps(run.result, default=str) if run.result else ""
                            err_str = run.error or ""
                            block = (
                                f"--- Run {run.run_index} ({run.timestamp_utc}, "
                                f"{run.duration_ms / 1000:.1f}s, {run_status}) ---\n"
                                + (result_str if run.success else f"Error: {err_str}")
                                + "\n\n"
                            )
                            run_blocks.append(block)

                        # Truncate run blocks proportionally if needed
                        total_run_chars = sum(len(b) for b in run_blocks)
                        if total_run_chars > budget_for_runs and run_blocks:
                            ratio = budget_for_runs / total_run_chars
                            run_blocks = [
                                b[: max(80, int(len(b) * ratio))] + "... [truncated]\n\n"
                                for b in run_blocks
                            ]
                            logger_internal.info(
                                f"Synthesis prompt truncated: "
                                f"{total_run_chars} -> ~{budget_for_runs} chars "
                                f"(limit {max_chars})"
                            )
                        else:
                            logger_internal.info(
                                f"Synthesis prompt: "
                                f"{total_run_chars + reserved} chars (limit {max_chars}), "
                                "no truncation needed"
                            )

                        result_content = header + "".join(run_blocks) + instruction

                        # --- Delete run files (FR-REP-017) ---
                        for fpath in written_files:
                            try:
                                fpath.unlink()
                                logger_internal.info(f"Run file deleted: {fpath}")
                            except Exception as del_exc:
                                logger_internal.warning(
                                    f"Failed to delete run file: {fpath} \u2014 {del_exc}"
                                )

                        # --- Track in tool_executions & session trace (FR-REP-021) ---
                        tool_executions.append({
                            "tool": "mcp_repeated_exec",
                            "arguments": arguments,
                            "result": summary.model_dump(),
                            "success": summary.success_count > 0,
                            "duration_ms": rep_duration_ms,
                        })
                        session_manager.add_tool_trace(
                            session_id=session_id,
                            tool_name="mcp_repeated_exec",
                            arguments=arguments,
                            result=summary.model_dump(),
                            success=summary.success_count > 0,
                        )

                        # --- Inject synthesis as tool result message ---
                        tool_result_msg = llm_client.format_tool_result(
                            tool_call_id=tool_id,
                            content=result_content
                        )
                        logger_internal.info(
                            "mcp_repeated_exec synthesis injected: "
                            f"{len(result_content)} chars, "
                            f"{repeat_count} runs, "
                            f"{summary.success_count} success / {summary.failure_count} failed"
                        )
                        messages_for_llm.append(tool_result_msg)
                        tool_msg_obj = ChatMessage(role="tool", content=result_content)
                        if "tool_call_id" in tool_result_msg:
                            tool_msg_obj.tool_call_id = tool_result_msg["tool_call_id"]
                        session_manager.add_message(session_id, tool_msg_obj)
                        continue
                    # ---------------------------------------------------------
                    # END mcp_repeated_exec intercept
                    # ---------------------------------------------------------

                    # Parse namespaced tool name (server_alias__tool_name)
                    if not namespaced_tool_name or "__" not in namespaced_tool_name:
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
                        # Look up advisory executionHints for this tool (CR-EXEC-001..014)
                        stored_tool = mcp_manager.tools.get(namespaced_tool_name)
                        execution_hints = stored_tool.execution_hints if stored_tool else None

                        # UX trace: warn when tool is long-running (CR-EXEC-009/010)
                        if execution_hints:
                            est_ms = execution_hints.estimatedRuntimeMs or 0
                            recommended_ms = execution_hints.recommended_wait_ms()
                            if execution_hints.mode == "sampling" or est_ms >= 5000:
                                logger_internal.info(
                                    f"Long-running diagnostic tool: {namespaced_tool_name} | "
                                    f"mode={execution_hints.mode}, "
                                    f"estimatedRuntime={est_ms / 1000:.1f}s, "
                                    f"clientWaitBudget={recommended_ms / 1000:.1f}s. "
                                    "This diagnostic samples data over time — client timeout extended accordingly."
                                )
                            else:
                                logger_internal.info(
                                    f"One-shot diagnostic tool: {namespaced_tool_name} | "
                                    f"mode={execution_hints.mode}, "
                                    f"estimatedRuntime={est_ms / 1000:.1f}s. "
                                    "Collecting snapshot."
                                )

                        # Execute tool
                        try:
                            import time
                            start_time = time.time()

                            tool_result = await mcp_manager.execute_tool(
                                server=server,
                                tool_name=actual_tool_name,
                                arguments=arguments,
                                execution_hints=execution_hints
                            )
                            
                            duration_ms = int((time.time() - start_time) * 1000)
                            
                            # Truncate large results
                            max_chars = int(os.getenv("MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM", "131072"))  # default 128 KB
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

                            executed_tool_results[dedupe_key] = {
                                "result_content": result_content,
                                "result": tool_result,
                                "success": True,
                            }
                            
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

                            executed_tool_results[dedupe_key] = {
                                "result_content": result_content,
                                "result": str(e),
                                "success": False,
                            }
                            
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
                    logger_internal.info(
                        "Prepared tool result for LLM: provider=%s tool=%s tool_call_id=%s content_preview=%s",
                        llm_config_storage.provider,
                        namespaced_tool_name,
                        tool_id,
                        result_content[:400],
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

                # Rebuild provider-specific message history before the next LLM turn.
                # This is required for Ollama, which cannot accept raw tool-role
                # messages or assistant tool_calls history in the same format as OpenAI.
                messages_for_llm = rebuild_messages_for_llm()
                tool_result_messages = [
                    msg for msg in messages_for_llm
                    if msg.get("role") == "tool"
                    or (
                        msg.get("role") == "user"
                        and isinstance(msg.get("content"), str)
                        and msg.get("content", "").startswith("Tool result:")
                    )
                ]
                if tool_result_messages:
                    latest_tool_result = tool_result_messages[-1]
                    logger_internal.info(
                        "Follow-up LLM request includes tool result message: role=%s content_preview=%s",
                        latest_tool_result.get("role"),
                        str(latest_tool_result.get("content", ""))[:400],
                    )
                
                # Continue loop to get next LLM response
                continue
            
            # No more tool calls - final response
            else:
                if tools_for_llm and not has_tool_calls:
                    logger_internal.warning(
                        "LLM returned final response without tool_calls despite %s tools being available. finish_reason=%s, response_preview=%s",
                        len(tools_for_llm),
                        finish_reason,
                        (assistant_msg.get("content", "")[:200] or "<empty>")
                    )

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
                    tool_executions=tool_executions,
                    initial_llm_response=initial_llm_response
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
            tool_executions=tool_executions,
            initial_llm_response=initial_llm_response
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
            tool_executions=[],
            initial_llm_response=None
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


@app.get("/tool-tester", include_in_schema=False)
async def serve_tool_tester():
    """Serve the dedicated MCP tool tester page."""
    tool_tester_path = os.path.join(static_dir, "tool-tester.html")
    if os.path.exists(tool_tester_path):
        return FileResponse(tool_tester_path)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Tool tester page not found"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
