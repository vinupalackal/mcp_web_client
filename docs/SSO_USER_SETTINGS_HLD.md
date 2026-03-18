# High-Level Design Document
## SSO Authentication & Per-User Settings

**Project**: MCP Client Web  
**Feature**: SSO Login and Per-User Settings  
**Version**: 0.4.0-sso-user-settings  
**Date**: March 15, 2026  
**Status**: Design Phase  
**Parent HLD**: HLD.md (v0.2.0-jsonrpc), ENTERPRISE_GATEWAY_HLD.md (v0.3.0-enterprise-gateway)  
**Requirements**: SSO_USER_SETTINGS_REQUIREMENTS.md (v0.4.0)

---

## 1. Executive Summary

This document describes the high-level design for introducing **multi-user support** into the MCP Client Web application via **OIDC-based SSO authentication** and **per-user data isolation**. Currently the application is a single-user tool with all state stored globally in-memory on the backend and in a shared `localStorage` on the frontend.

The design introduces four new structural layers on top of the v0.3.0 system:

1. **Auth layer** — OIDC Authorization Code Flow with PKCE; JWT session cookie; middleware guard on every `/api/*` route
2. **User identity layer** — persistent `users` table; `UserProfile` context attached to every request
3. **Per-user data isolation** — all existing in-memory stores (`llm_config_storage`, `servers_storage`, `mcp_manager.tools`) move to per-user keyed DB-backed stores
4. **Per-user UI preferences** — new `UserSettings` model; backend source of truth with `localStorage` as a read-ahead cache

### 1.1 Design Principles
- **Additive, non-breaking**: Standard and Enterprise LLM code paths are untouched; only their storage scoping changes
- **Stateless JWT sessions**: No server-side session store needed; `app_token` cookie carries all claims
- **Thin DB layer**: SQLite default (Postgres-ready); only user identity, configs, and preferences are persisted — chat message history remains in-memory
- **PKCE mandatory**: No implicit flow; `state` and `nonce` validated on every callback

---

## 2. Architecture Overview

### 2.1 Updated System Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              User's Browser                              │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                    Frontend (Vanilla JavaScript)                   │  │
│  │  ┌─────────────┐  ┌──────────────────────────┐  ┌──────────────┐  │  │
│  │  │   Chat UI   │  │     Settings Modal        │  │ localStorage │  │  │
│  │  │  (app.js)   │  │  [My Account]  ← NEW      │  │ user-scoped  │  │  │
│  │  │  401 guard  │  │  [MCP Servers]            │  │ cache only   │  │  │
│  │  │  ← NEW      │  │  [LLM Config]             │  │              │  │  │
│  │  └─────────────┘  │  [Tools]                  │  └──────────────┘  │  │
│  │  ┌─────────────┐  └──────────────────────────┘                     │  │
│  │  │  Login Page │  ← NEW  /login                                     │  │
│  │  │ (login.html)│                                                     │  │
│  │  └─────────────┘                                                     │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │ HTTP  (HttpOnly session cookie)
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          FastAPI Backend Server                          │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                  Auth Middleware  ← NEW                          │   │
│  │  • Validate app_token JWT cookie on every /api/* request         │   │
│  │  • Attach current_user to request.state                          │   │
│  │  • Return 401/403 for missing/expired/disabled users             │   │
│  └───────────────────────────────┬──────────────────────────────────┘   │
│                                  │                                       │
│  ┌───────────────────────────────┴────────────────────────────────────┐  │
│  │                     API Endpoints (main.py)                        │  │
│  │  /auth/login  /auth/callback/{provider}  /auth/logout  ← NEW      │  │
│  │  /api/users/me  /api/users/me/settings   ← NEW                    │  │
│  │  /api/admin/users  /api/admin/users/{id} ← NEW                    │  │
│  │  /api/sessions  /api/servers  /api/llm/config  (user-scoped)      │  │
│  └──────────┬───────────────────────────┬─────────────────────────────┘  │
│             │                           │                                 │
│  ┌──────────┴──────────┐   ┌────────────┴──────────────────────────────┐ │
│  │   Auth Service NEW  │   │       Per-User Store Layer  NEW           │ │
│  │  OIDCProvider ABC   │   │  UserScopedServerStore                    │ │
│  │  AzureADProvider    │   │  UserScopedLLMConfigStore                 │ │
│  │  GoogleProvider     │   │  UserScopedSessionManager                 │ │
│  │  JWKS cache         │   │  UserSettingsStore                        │ │
│  │  JWT issue/verify   │   └────────────────────────────────────────── ┘ │
│  └──────────┬──────────┘                                                 │
│             │                                                             │
│  ┌──────────┴──────────┐   ┌───────────────────────────────────────────┐ │
│  │  Database Layer NEW │   │   MCP Manager / LLM Client (unchanged)    │ │
│  │  SQLAlchemy         │   │   Tool execution, LLM adapters            │ │
│  │  SQLite (default)   │   │   now receive user-scoped config          │ │
│  │  Postgres-ready     │   └───────────────────────────────────────────┘ │
│  └─────────────────────┘                                                 │
└──────────────┬─────────────────────────┬────────────────────────────────┘
               │                         │
               ▼  JSON-RPC 2.0           ▼  HTTPS REST
┌──────────────────────────┐   ┌──────────────────────────────────────────┐
│   MCP Servers            │   │  External Services                       │
│  (unchanged)             │   │  ┌─────────────────┐  ┌───────────────┐  │
│                          │   │  │  IdP (Azure AD  │  │  LLM Provider │  │
│                          │   │  │  / Google)      │  │  OpenAI/Ollama│  │
│                          │   │  │  OIDC/JWKS      │  │  / Enterprise │  │
└──────────────────────────┘   │  └─────────────────┘  └───────────────┘  │
                               └──────────────────────────────────────────┘
```

### 2.2 Component Delta from v0.3.0

| Component | Change | Description |
|---|---|---|
| `backend/main.py` | Extended | New `/auth/*`, `/api/users/*`, `/api/admin/*` endpoints; auth middleware |
| `backend/models.py` | Extended | `UserProfile`, `UserSettings`, `SSOProviderConfig` models |
| `backend/auth/` | **New package** | OIDC providers, JWT utils, PKCE helpers, JWKS cache |
| `backend/user_store.py` | **New** | Per-user LLM config, server, settings stores |
| `backend/database.py` | **New** | SQLAlchemy engine, session factory, schema init |
| `backend/llm_client.py` | Minor | Now receives `LLMConfig` scoped to calling user; no logic change |
| `backend/mcp_manager.py` | Minor | `get_tools_for_llm()` and `execute_tool()` scoped to calling user |
| `backend/session_manager.py` | Extended | Sessions keyed by `(user_id, session_id)`; ownership check |
| `backend/static/app.js` | Extended | 401 interceptor; user menu; loads `GET /api/users/me` on init |
| `backend/static/settings.js` | Extended | New "My Account" tab (first tab); preference save calls |
| `backend/static/login.html` | **New** | SSO provider selection page |
| `backend/static/style.css` | Extended | Login page, user menu, avatar styles |
| `backend/mcp_manager.py` | Unchanged (logic) | MCP communication protocol unaffected |

---

## 3. Frontend Design

### 3.1 Login Page

```
┌──────────────────────────────────────────────────┐
│                                                  │
│                  MCP Client                      │
│                    ◉                             │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │                                          │   │
│  │   Sign in to continue                    │   │
│  │                                          │   │
│  │  ┌────────────────────────────────────┐  │   │
│  │  │  🔵  Sign in with Microsoft        │  │   │
│  │  └────────────────────────────────────┘  │   │
│  │                                          │   │
│  │  ┌────────────────────────────────────┐  │   │
│  │  │  🔴  Sign in with Google           │  │   │
│  │  └────────────────────────────────────┘  │   │
│  │                                          │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  By signing in you accept the Terms of Use       │
└──────────────────────────────────────────────────┘
```

- Route: `/login`  
- Only providers with all required env vars set are rendered as buttons  
- `?reason=session_expired` shows a banner: *"Your session expired. Please sign in again."*  
- No direct access to `/` without a valid `app_token` cookie — middleware redirects here

### 3.2 Updated Main UI Header

```
┌──────────────────────────────────────────────────────────────────┐
│  MCP Client              [New Chat]          [Avatar ▼]          │
│                                              │                   │
│                                              ▼                   │
│                                     ┌──────────────────┐        │
│                                     │  Alice Smith     │        │
│                                     │  alice@corp.com  │        │
│                                     │  ──────────────  │        │
│                                     │  My Settings     │        │
│                                     │  Sign Out        │        │
│                                     └──────────────────┘        │
└──────────────────────────────────────────────────────────────────┘
```

- Avatar image from IdP `picture` claim; falls back to initials circle (`AS`) if image load fails  
- Dropdown opens on click, closes on outside click or Escape  
- "My Settings" opens Settings modal pre-selected on "My Account" tab

### 3.3 Updated Settings Modal

```
┌──────────────────────────────────────────────────────────────────┐
│  Settings                                                   [×]  │
├──────────────────────────────────────────────────────────────────┤
│  [My Account]  [MCP Servers]  [LLM Config]  [Tools]             │
│  ← NEW (first)                                                   │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ── Profile ──────────────────────────────────────────────────  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  [Avatar]  Alice Smith                                   │   │
│  │            alice@corp.com                                │   │
│  │            Provider: Microsoft  [badge]                  │   │
│  │            Member since: March 1, 2026                   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ── Appearance ────────────────────────────────────────────── │
│  Theme:           ○ Light   ○ Dark   ● System                   │
│  Message density: ● Comfortable   ○ Compact                     │
│                                                                  │
│  ── Chat Defaults ─────────────────────────────────────────── │
│  Show tool panel:  [●  ON  ]                                     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

- Profile data sourced from `GET /api/users/me`; read-only in v0.4.0  
- Preference toggles call `PATCH /api/users/me/settings` debounced to 500 ms  
- All other existing tabs (MCP Servers, LLM Config, Tools) are unchanged

### 3.4 OIDC Login Flow (Browser Side)

```
Browser                        Backend                       IdP (Azure/Google)
──────                         ───────                       ──────────────────
Click "Sign in with Microsoft"
  │
  ├─ Generate code_verifier (random 64 bytes)
  ├─ Derive code_challenge = BASE64URL(SHA-256(verifier))
  ├─ Generate state (random 32 bytes)
  ├─ Generate nonce (random 32 bytes)
  ├─ Store {state, nonce, verifier} in sessionStorage
  │
  └─► GET /auth/login/azure_ad
        │
        ├─ Backend builds authorisation URL:
        │   ?response_type=code
        │   &client_id=...
        │   &redirect_uri=.../auth/callback/azure_ad
        │   &scope=openid email profile
        │   &state=<opaque>
        │   &nonce=<opaque>
        │   &code_challenge=<sha256>
        │   &code_challenge_method=S256
        │
        └─► 302 → IdP authorisation URL
                        │
                        ├─ User authenticates at IdP
                        │
                        └─► GET /auth/callback/azure_ad?code=...&state=...
                                  │
                                  ├─ Validate state matches session
                                  ├─ POST /token (code + verifier)
                                  ├─ Validate id_token (sig, iss, aud, exp, nonce)
                                  ├─ Upsert user in DB
                                  ├─ Issue app_token JWT
                                  ├─ Set HttpOnly cookie
                                  │
                                  └─► 302 → /?sso=ok
                                                │
                                                └─ Browser loads chat UI
```

### 3.5 Updated localStorage Schema

```javascript
// Keys are now namespaced per user_id to prevent cross-user contamination
// on shared-browser environments

// Auth / identity  (written by app.js on login)
localStorage["user:abc-123:profile"] = JSON.stringify({
  display_name: "Alice Smith",
  email: "alice@corp.com",
  avatar_url: "https://..."
});

// UI preferences cache (source of truth is backend)
localStorage["user:abc-123:settings"] = JSON.stringify({
  theme: "dark",
  message_density: "comfortable",
  tool_panel_visible: true,
  sidebar_collapsed: false
});

// Per-user config caches (written on settings save, read on load)
localStorage["user:abc-123:llmConfig"]         = JSON.stringify({ ... });
localStorage["user:abc-123:llmGatewayMode"]    = "enterprise";
localStorage["user:abc-123:mcpServers"]        = JSON.stringify([ ... ]);
localStorage["user:abc-123:enterpriseCustomModels"] = JSON.stringify([ ... ]);

// Legacy v0.2.0 / v0.3.0 keys are migrated on first authenticated load:
//   mcpServers              → user:{id}:mcpServers
//   llmConfig               → user:{id}:llmConfig
//   llmGatewayMode          → user:{id}:llmGatewayMode
//   enterpriseCustomModels  → user:{id}:enterpriseCustomModels
```

---

## 4. Backend Design

### 4.1 New Package: `backend/auth/`

```
backend/auth/
├── __init__.py
├── provider.py        # Abstract OIDCProvider base class
├── azure_ad.py        # AzureADProvider implementation
├── google.py          # GoogleProvider implementation
├── jwt_utils.py       # Issue / verify app_token JWT
├── pkce.py            # PKCE code_verifier / code_challenge helpers
└── jwks_cache.py      # JWKS public-key fetch with TTL cache
```

#### 4.1.1 OIDCProvider Base Class

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

@dataclass
class OIDCUserInfo:
    sub: str
    email: str
    display_name: str
    avatar_url: str | None

class OIDCProvider(ABC):
    """Abstract base for OIDC identity providers."""

    @property
    @abstractmethod
    def provider_key(self) -> str: ...          # 'azure_ad' | 'google'

    @abstractmethod
    def build_authorisation_url(
        self, state: str, nonce: str, code_challenge: str
    ) -> str: ...

    @abstractmethod
    async def exchange_code(
        self, code: str, code_verifier: str
    ) -> dict: ...                              # raw token response

    @abstractmethod
    async def validate_id_token(
        self, id_token: str, nonce: str
    ) -> OIDCUserInfo: ...
```

#### 4.1.2 JWT Utility

```python
# backend/auth/jwt_utils.py
import jwt, uuid
from datetime import datetime, timedelta, timezone

SECRET_KEY: str  # loaded from env SECRET_KEY

def issue_app_token(user_id: str, email: str, roles: list[str],
                    ttl_hours: int = 8) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "roles": roles,
        "iat": now,
        "exp": now + timedelta(hours=ttl_hours),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verify_app_token(token: str) -> dict:
    """Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError on failure."""
    return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
```

### 4.2 Auth Middleware

```python
# backend/main.py — applied to all /api/* routes
from fastapi import Request, HTTPException, status
from backend.auth.jwt_utils import verify_app_token
from backend.database import get_user_by_id

async def auth_middleware(request: Request, call_next):
    # Skip: health check, auth endpoints, static files, docs
    if request.url.path.startswith(("/auth/", "/static/", "/docs", "/redoc",
                                     "/openapi.json", "/api/health")):
        return await call_next(request)

    token = request.cookies.get("app_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail="Unauthorized")
    try:
        claims = verify_app_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail="Session expired")

    user = await get_user_by_id(claims["sub"])
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Account disabled")

    request.state.current_user = user
    return await call_next(request)
```

### 4.3 New Database Layer

```
backend/
└── database.py          # SQLAlchemy engine, Base, session factory, schema
```

```python
# backend/database.py
from sqlalchemy import create_engine, Column, String, Boolean, Text, DateTime
from sqlalchemy.orm import DeclarativeBase, sessionmaker
import os

DB_URL = os.getenv("DB_URL", "sqlite:///./mcp_client.db")
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

class Base(DeclarativeBase): pass

class UserRow(Base):
    __tablename__ = "users"
    user_id      = Column(String, primary_key=True)
    provider     = Column(String(32), nullable=False)
    provider_sub = Column(String(256), nullable=False)
    email        = Column(String(256), nullable=False, unique=True)
    display_name = Column(String(256), nullable=False, default="")
    avatar_url   = Column(Text)
    roles        = Column(Text, nullable=False, default='["user"]')
    is_active    = Column(Boolean, nullable=False, default=True)
    created_at   = Column(DateTime, nullable=False)
    last_login_at= Column(DateTime, nullable=False)

class UserLLMConfigRow(Base):
    __tablename__ = "user_llm_configs"
    user_id      = Column(String, primary_key=True)  # FK → users
    config_json  = Column(Text, nullable=False)       # AES-256-GCM encrypted
    updated_at   = Column(DateTime, nullable=False)

class UserServerRow(Base):
    __tablename__ = "user_servers"
    server_id    = Column(String, primary_key=True)
    user_id      = Column(String, nullable=False)    # FK → users
    config_json  = Column(Text, nullable=False)
    created_at   = Column(DateTime, nullable=False)

class UserSettingsRow(Base):
    __tablename__ = "user_settings"
    user_id           = Column(String, primary_key=True)
    theme             = Column(String(16), nullable=False, default="system")
    message_density   = Column(String(16), nullable=False, default="comfortable")
    tool_panel_visible= Column(Boolean, nullable=False, default=True)
    sidebar_collapsed = Column(Boolean, nullable=False, default=False)
    default_llm_model = Column(String(128))
    updated_at        = Column(DateTime, nullable=False)
```

### 4.4 Per-User Store Layer

The single global singletons from v0.2.0/v0.3.0 are replaced by store classes that scope every operation to the calling `user_id`.

```python
# backend/user_store.py

class UserScopedLLMConfigStore:
    """Replaces the global llm_config_storage dict."""
    async def get(self, user_id: str) -> LLMConfig | None: ...
    async def set(self, user_id: str, config: LLMConfig) -> None: ...
    async def delete(self, user_id: str) -> None: ...

class UserScopedServerStore:
    """Replaces the global servers_storage dict."""
    async def list(self, user_id: str) -> list[ServerConfig]: ...
    async def get(self, user_id: str, server_id: str) -> ServerConfig | None: ...
    async def create(self, user_id: str, config: ServerConfig) -> ServerConfig: ...
    async def update(self, user_id: str, server_id: str,
                     config: ServerConfig) -> ServerConfig: ...
    async def delete(self, user_id: str, server_id: str) -> None: ...

class UserSettingsStore:
    async def get(self, user_id: str) -> UserSettings: ...
    async def patch(self, user_id: str, updates: dict) -> UserSettings: ...
```

### 4.5 New Pydantic Models

```python
# backend/models.py additions

class UserProfile(BaseModel):
    """Authenticated user's public profile"""
    user_id: str = Field(..., description="Immutable UUID")
    email: str
    display_name: str
    avatar_url: Optional[str] = None
    roles: List[str]
    created_at: datetime
    last_login_at: datetime

class UserSettings(BaseModel):
    """Per-user UI and application preferences"""
    theme: Literal["light", "dark", "system"] = "system"
    message_density: Literal["compact", "comfortable"] = "comfortable"
    tool_panel_visible: bool = True
    sidebar_collapsed: bool = False
    default_llm_model: Optional[str] = None

class UserSettingsPatch(BaseModel):
    """Partial update payload for PATCH /api/users/me/settings"""
    theme: Optional[Literal["light", "dark", "system"]] = None
    message_density: Optional[Literal["compact", "comfortable"]] = None
    tool_panel_visible: Optional[bool] = None
    sidebar_collapsed: Optional[bool] = None
    default_llm_model: Optional[str] = None
```

### 4.6 Credential Encryption

API keys and enterprise secrets stored in `user_llm_configs.config_json` are encrypted at rest using AES-256-GCM before writing to the DB and decrypted on read. The encryption key is derived from the `SECRET_KEY` environment variable.

```
┌────────────────────────────────────────────────────────────────┐
│                    Credential Lifecycle                        │
│                                                                │
│  POST /api/llm/config                                          │
│  { "api_key": "sk-realvalue" }                                 │
│           │                                                    │
│           ▼                                                    │
│  encrypt_field("sk-realvalue", SECRET_KEY)                     │
│           │                                                    │
│           ▼                                                    │
│  DB stores: { "api_key": "enc:iv=...,tag=...,ct=..." }         │
│                                                                │
│  GET /api/llm/config                                           │
│           │                                                    │
│           ▼                                                    │
│  decrypt → mask: "sk-...****"  (last 4 visible)                │
│           │                                                    │
│           └─► Response never contains plaintext value          │
└────────────────────────────────────────────────────────────────┘
```

**Rules**:
- Credential fields encrypted: `api_key`, `client_secret`
- GET responses mask credentials: `"sk-...****"` — presence confirmed, value never returned
- POST with `null` or absent field leaves existing encrypted value unchanged
- Credentials never appear in any log line

---

## 5. API Design

### 5.1 New Auth Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/auth/login` | No | Redirect to `/login` |
| `GET` | `/auth/login/{provider}` | No | Build OIDC authorisation URL; redirect to IdP |
| `GET` | `/auth/callback/{provider}` | No | Handle OIDC redirect; issue session cookie |
| `POST` | `/auth/logout` | Yes | Clear cookie; redirect to `/login` |

### 5.2 New User Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/users/me` | User | Get own `UserProfile` |
| `GET` | `/api/users/me/settings` | User | Get own `UserSettings` |
| `PATCH` | `/api/users/me/settings` | User | Partial update own `UserSettings` |

### 5.3 New Admin Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/admin/users` | Admin | List all users (paginated: `limit`, `offset`) |
| `GET` | `/api/admin/users/{user_id}` | Admin | Get user's `UserProfile` |
| `PATCH` | `/api/admin/users/{user_id}` | Admin | Toggle `is_active` |
| `DELETE` | `/api/admin/users/{user_id}/settings` | Admin | Reset user's LLM config + preferences |

### 5.4 Modified Existing Endpoints (user-scoped, same URL)

No URL changes. All routing is driven by `request.state.current_user` injected by middleware.

| Endpoint | Scoping Change |
|---|---|
| `GET /api/llm/config` | Returns calling user's config from `UserScopedLLMConfigStore` |
| `POST /api/llm/config` | Saves to calling user's encrypted row |
| `GET /api/servers` | Returns only calling user's servers |
| `POST /api/servers` | Creates server owned by calling user |
| `PUT /api/servers/{id}` | 403 if `server.user_id ≠ current_user.user_id` |
| `DELETE /api/servers/{id}` | 403 if not owner |
| `GET /api/tools` | Tools from calling user's registered servers only |
| `POST /api/sessions` | Session tagged with `current_user.user_id` |
| `POST /api/sessions/{id}/messages` | 403 if session owner ≠ current user |
| `GET /api/sessions/{id}/messages` | 403 if session owner ≠ current user |

### 5.5 Complete Updated API Table

| Method | Path | New? | Auth |
|---|---|---|---|
| `GET` | `/` | — | Cookie guard (redirect to `/login`) |
| `GET` | `/login` | ✓ | No |
| `GET` | `/api/health` | — | No |
| `GET` | `/auth/login/{provider}` | ✓ | No |
| `GET` | `/auth/callback/{provider}` | ✓ | No |
| `POST` | `/auth/logout` | ✓ | Yes |
| `GET` | `/api/users/me` | ✓ | User |
| `GET` | `/api/users/me/settings` | ✓ | User |
| `PATCH` | `/api/users/me/settings` | ✓ | User |
| `GET` | `/api/admin/users` | ✓ | Admin |
| `GET` | `/api/admin/users/{user_id}` | ✓ | Admin |
| `PATCH` | `/api/admin/users/{user_id}` | ✓ | Admin |
| `DELETE` | `/api/admin/users/{user_id}/settings` | ✓ | Admin |
| `POST` | `/api/sessions` | Scoped | User |
| `POST` | `/api/sessions/{id}/messages` | Scoped | User |
| `GET` | `/api/sessions/{id}/messages` | Scoped | User |
| `GET` | `/api/servers` | Scoped | User |
| `POST` | `/api/servers` | Scoped | User |
| `PUT` | `/api/servers/{id}` | Scoped | User |
| `DELETE` | `/api/servers/{id}` | Scoped | User |
| `POST` | `/api/servers/refresh-tools` | Scoped | User |
| `GET` | `/api/tools` | Scoped | User |
| `POST` | `/api/llm/config` | Scoped | User |
| `GET` | `/api/llm/config` | Scoped | User |
| `DELETE` | `/api/llm/config` | Scoped | User |
| `POST` | `/api/enterprise/token` | Scoped | User |
| `GET` | `/api/enterprise/token/status` | Scoped | User |

---

## 6. Security Design

### 6.1 OIDC + PKCE Security Model

```
┌─────────────────────────────────────────────────────────────────────┐
│                     OIDC PKCE Attack Surface                        │
│                                                                     │
│  Threat: CSRF on callback (forged state)                            │
│  Mitigation: state stored in sessionStorage; validated in callback  │
│                                                                     │
│  Threat: Code interception (public client)                          │
│  Mitigation: PKCE S256 — code_verifier never leaves backend memory  │
│                                                                     │
│  Threat: Replay attack (reused id_token)                            │
│  Mitigation: nonce validated in id_token claims                     │
│                                                                     │
│  Threat: Token forgery (app_token)                                  │
│  Mitigation: HS256 signed with SECRET_KEY; exp enforced             │
│                                                                     │
│  Threat: Session fixation (session cookie)                          │
│  Mitigation: HttpOnly; Secure; SameSite=Strict                      │
│              Fresh JWT issued on each login                         │
│                                                                     │
│  Threat: XSS steals session token                                   │
│  Mitigation: HttpOnly cookie — inaccessible from JavaScript         │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 Cross-User Data Isolation Model

```
Request: POST /api/sessions/{session_id}/messages
  │
  ▼
Auth Middleware
  ├─ Validate app_token cookie
  └─ Attach current_user = { user_id: "abc-123", ... }
       │
       ▼
  Endpoint handler:
  session = session_manager.get_session(session_id)
       │
       ├─ session.user_id == current_user.user_id ?
       │     YES → proceed
       │     NO  → raise HTTP 403 "Forbidden"
       │
       ▼
  Scoped execution:
  config = llm_config_store.get(current_user.user_id)    ← user A's config only
  servers = server_store.list(current_user.user_id)      ← user A's servers only
  tools = mcp_manager.get_tools(current_user.user_id)   ← user A's tools only
```

### 6.3 Session Cookie Attributes

```
Set-Cookie: app_token=<jwt>;
  HttpOnly;
  Secure;
  SameSite=Strict;
  Max-Age=28800;       (8 hours default, SSO_SESSION_TTL_HOURS * 3600)
  Path=/
```

### 6.4 CSRF Protection

All state-mutating API requests (`POST`, `PATCH`, `PUT`, `DELETE`) require a CSRF token:

```
Client startup (app.js):
  GET /api/users/me  → response header includes  X-CSRF-Token: <token>

All mutation requests include:
  X-CSRF-Token: <token>   (request header)

Middleware validates header on every mutating request.
CSRF token is a HMAC of the session JWT's jti claim.
```

### 6.5 Admin Role Enforcement

```python
def require_admin(current_user = Depends(get_current_user)):
    if "admin" not in current_user.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Admin role required")
    return current_user
```

Admin role is re-evaluated at each login from `SSO_ADMIN_EMAILS` env var — no DB migration needed to promote/demote admins.

---

## 7. Data Flow

### 7.1 First-Time Login Flow

```
1. User visits /  →  no app_token cookie
2. Middleware redirects to /login
3. User clicks "Sign in with Microsoft"
4. Browser: generate PKCE verifier + challenge, state, nonce → sessionStorage
5. GET /auth/login/azure_ad
6. Backend builds OIDC auth URL, 302 → Azure AD
7. User authenticates at Azure AD
8. Azure AD 302 → GET /auth/callback/azure_ad?code=...&state=...
9. Backend:
   a. Validates state
   b. Exchanges code + verifier for id_token
   c. Validates id_token (sig, iss, aud, exp, nonce)
   d. Extracts: sub, email, name, picture
   e. INSERT INTO users (new row; is_active=true; roles='["user"]')
      (promote to admin if email in SSO_ADMIN_EMAILS)
   f. INSERT INTO user_settings (defaults)
   g. Issues app_token JWT
   h. Set-Cookie: app_token=...
10. 302 → /?sso=ok
11. app.js: GET /api/users/me  →  renders avatar + display name
12. app.js: GET /api/users/me/settings  →  hydrates localStorage + applies theme
```

### 7.2 Per-User Chat Message Flow

```
POST /api/sessions/{session_id}/messages
  │
  ├─ Auth middleware: validate app_token → current_user = Alice
  │
  ├─ session_manager.get_session(session_id)
  │   └─ assert session.user_id == "alice-uuid" → 403 if mismatch
  │
  ├─ llm_config_store.get("alice-uuid")
  │   └─ decrypt config_json → LLMConfig
  │
  ├─ server_store.list("alice-uuid")
  │   └─ only Alice's registered MCP servers
  │
  ├─ mcp_manager.get_tools_for_llm(user_id="alice-uuid")
  │   └─ tools namespaced from Alice's servers only
  │
  ├─ LLM client.chat_completion(messages, tools)
  │
  ├─ [tool execution loop — same as v0.3.0 but using Alice's tools]
  │
  └─ return ChatResponse
```

### 7.3 Preferences Sync Flow

```
User toggles theme to "Dark"
  │
  ├─ settings.js: localStorage["user:alice-uuid:settings"].theme = "dark"
  ├─ Apply CSS class immediately (instant visual feedback)
  │
  └─ (debounced 500 ms)
       PATCH /api/users/me/settings
       { "theme": "dark" }
         │
         ├─ DB: UPDATE user_settings SET theme='dark' WHERE user_id='alice-uuid'
         └─ 200 OK { full updated UserSettings }
```

---

## 8. Deployment Architecture

### 8.1 Multi-Machine Topology (Updated)

```
┌──────────────────────────────────────┐
│  User's Browser (Machine A)          │
│  - app_token cookie (HttpOnly)        │
│  - localStorage: user-scoped cache   │
│  - No direct DB or IdP access        │
└──────────────────┬───────────────────┘
                   │ HTTP (session cookie)
                   ▼
┌──────────────────────────────────────┐
│  FastAPI Backend (Machine B)         │
│  - Auth middleware                   │
│  - Per-user store layer              │
│  - JWT sign/verify (SECRET_KEY)      │
│  Env vars:                           │
│    SECRET_KEY=<32-byte-hex>          │
│    DB_URL=sqlite:///./mcp.db         │
│    SSO_ADMIN_EMAILS=alice@corp.com   │
│    AZURE_AD_CLIENT_ID=...            │
│    AZURE_AD_CLIENT_SECRET=...        │
│    AZURE_AD_TENANT_ID=...            │
│    GOOGLE_CLIENT_ID=...              │
│    GOOGLE_CLIENT_SECRET=...          │
└────────┬─────────────────┬──────────┘
         │                 │
         ▼ JSON-RPC        ▼ HTTPS
┌──────────────┐   ┌──────────────────────────────┐
│  MCP Servers │   │  External Services            │
│ (unchanged)  │   │  ┌────────────┐ ┌──────────┐  │
│              │   │  │ Azure AD   │ │ OpenAI / │  │
│              │   │  │ Google IdP │ │ Ollama / │  │
│              │   │  │ (OIDC)     │ │ Gateway  │  │
│              │   │  └────────────┘ └──────────┘  │
└──────────────┘   └──────────────────────────────┘
         ▲
         │ SQLite file (local) or Postgres URL (scaled)
┌──────────────┐
│  Database    │
│  users       │
│  user_llm_   │
│  configs     │
│  user_servers│
│  user_       │
│  settings    │
└──────────────┘
```

### 8.2 Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | **Yes** | — | 32-byte hex; JWT signing + credential encryption |
| `DB_URL` | No | `sqlite:///./mcp_client.db` | SQLAlchemy DB URL |
| `SSO_SESSION_TTL_HOURS` | No | `8` | Session cookie lifetime |
| `SSO_ADMIN_EMAILS` | No | `""` | Comma-separated admin email list |
| `AZURE_AD_CLIENT_ID` | If Azure | — | App registration client ID |
| `AZURE_AD_CLIENT_SECRET` | If Azure | — | App registration client secret |
| `AZURE_AD_TENANT_ID` | If Azure | — | Tenant ID (forms discovery URL) |
| `AZURE_AD_REDIRECT_URI` | If Azure | — | Must match IdP registered URI |
| `GOOGLE_CLIENT_ID` | If Google | — | OAuth 2.0 client ID |
| `GOOGLE_CLIENT_SECRET` | If Google | — | OAuth 2.0 client secret |
| `GOOGLE_REDIRECT_URI` | If Google | — | Must match Google Console URI |
| `JWKS_CACHE_TTL_SECONDS` | No | `3600` | IdP public key cache TTL |

---

## 9. Technology Stack Additions

| Component | Technology | Version | Purpose |
|---|---|---|---|
| OIDC / JWT | `python-jose` or `PyJWT` | ≥ 3.x | JWT sign / verify; JWKS validation |
| OIDC client | `httpx` (existing) | 0.27.0 | Token exchange, JWKS fetch |
| ORM | `SQLAlchemy` | ≥ 2.0 | DB abstraction (SQLite / Postgres) |
| Migrations | `alembic` | ≥ 1.13 | Schema versioning |
| Encryption | `cryptography` (AES-GCM) | ≥ 42.x | Credential encryption at rest |
| CSRF | Custom HMAC middleware | — | X-CSRF-Token header validation |

No new frontend dependencies — login page and user menu use vanilla JS + existing `style.css` extended with new classes.

---

## 10. Non-Functional Design

### 10.1 Backward Compatibility

```
v0.2.0 / v0.3.0 code paths:
  gateway_mode = "standard"   →  OpenAIClient / OllamaClient  (unchanged logic)
  gateway_mode = "enterprise" →  EnterpriseLLMClient           (unchanged logic)

Only the storage layer changes:
  Before:  llm_config_storage        (module-level dict, shared)
  After:   UserScopedLLMConfigStore  (per-user, DB-backed)

  Before:  servers_storage           (module-level dict, shared)
  After:   UserScopedServerStore     (per-user, DB-backed)

Existing frontend JS for tabs, tool execution, and chat is unchanged.
```

### 10.2 Performance

| Operation | Target P95 |
|---|---|
| Auth middleware overhead per request | ≤ 5 ms (JWT verify is CPU-only) |
| `GET /api/users/me` | ≤ 100 ms |
| `PATCH /api/users/me/settings` | ≤ 200 ms |
| OIDC callback end-to-end | ≤ 2 s (network-bound) |
| JWKS fetch | Cached; 0 ms on hot path |

### 10.3 Session Expiry Handling (Frontend)

```javascript
// app.js — global fetch wrapper
async function apiFetch(url, options = {}) {
  const res = await fetch(url, { credentials: "include", ...options });
  if (res.status === 401) {
    window.location.href = "/login?reason=session_expired";
    return;
  }
  return res;
}
```

---

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| IdP discovery endpoint unreachable at startup | OIDC flow broken | Cache JWKS; retry with exponential backoff; health endpoint reports IdP status |
| `SECRET_KEY` rotation | All active sessions invalidated | Planned maintenance window; rotate key, restart server |
| SQLite write contention under concurrent users | Slow writes | Switch to Postgres via `DB_URL`; SQLite suitable for ≤ 20 concurrent users |
| Cross-IdP account merging (same email, two providers) | Duplicate users | Covered by OQ-1; email uniqueness constraint in DB prevents silent merging |
| `SameSite=Strict` breaking IdP redirect | Callback cookie not sent | Covered by OQ-6; OIDC callback is a GET from IdP — first-party cookie, `Strict` is fine |
| localStorage migration failure (legacy keys) | Stale shared config visible | Migration runs once on first login; logs warnings; non-fatal (backend is source of truth) |
| Admin email allowlist out of sync | Wrong user promoted | Admin role re-evaluated every login; immediate effect after env var change + restart |
| Credential encryption key lost | Cannot decrypt stored secrets | Operators must back up `SECRET_KEY`; document in runbook |

---

## 12. Open Questions

| # | Question | Design Impact |
|---|---|---|
| OQ-1 | Account linking: same email across Azure AD + Google → one user or two? | Affects `(provider, provider_sub)` uniqueness constraint |
| OQ-2 | Local dev bypass (no SSO) — hard-coded dev user acceptable? | Affects `auth_middleware` skip logic |
| OQ-3 | Profile editable in-app, or always IdP-sourced? | Affects `UserProfile` write endpoints (not in v0.4.0 scope) |
| OQ-4 | Max concurrent users expected? | Determines whether SQLite or Postgres is needed from day one |
| OQ-5 | SAML 2.0 in v0.4.0 or v0.5.0? | Affects `OIDCProvider` abstraction scope |
| OQ-6 | `SameSite=Strict` vs `Lax` for IdP redirect cookie? | Cookie attribute on `app_token` |
| OQ-7 | `SECRET_KEY` from Vault/SSM vs plain env var? | Affects startup secrets loading |
| OQ-8 | GDPR / data-residency for email + avatar URL? | Affects `avatar_url` storage (store URL vs copy bytes) |

---

## 13. Document Control

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-03-15 | AI Assistant | Initial HLD for SSO authentication and per-user settings |

**Parent Documents**

| Document | Version | Relationship |
|---|---|---|
| HLD.md | 0.2.0 | Base system HLD |
| ENTERPRISE_GATEWAY_HLD.md | 0.3.0 | Enterprise gateway HLD (unchanged standard/enterprise LLM paths) |
| SSO_USER_SETTINGS_REQUIREMENTS.md | 0.4.0 | Feature requirements this HLD implements |

**Approval**

| Role | Name | Signature | Date |
|---|---|---|---|
| Architect | _______________ | _______________ | _______ |
| Security Lead | _______________ | _______________ | _______ |
| Tech Lead | _______________ | _______________ | _______ |
