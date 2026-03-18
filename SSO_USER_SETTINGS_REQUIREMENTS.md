# SSO Authentication & Per-User Settings - Requirements Document

**Project**: MCP Client Web Interface  
**Feature**: SSO Login and Per-User Settings  
**Version**: 0.4.0-sso-user-settings  
**Date**: March 15, 2026  
**Status**: Draft  
**Parent Document**: REQUIREMENTS.md (v0.2.0-jsonrpc), ENTERPRISE_GATEWAY_REQUIREMENTS.md (v0.3.0-enterprise-gateway)

---

## 1. Executive Summary

This document defines the requirements for introducing **multi-user support** to the MCP Client Web application via **SSO (Single Sign-On) authentication** and **per-user settings isolation**. Currently the application is a single-user tool with no authentication and all configuration shared globally. This feature adds OIDC-based SSO login, a persistent user identity model, and full per-user isolation of LLM configuration, MCP server configurations, and UI preferences. Users signing in via an enterprise SSO provider will see only their own servers and settings; administrators gain a management view across all users.

---

## 2. Scope

### 2.1 In Scope
- OIDC-based SSO authentication (OpenID Connect with OAuth 2.0 Authorization Code Flow)
- Support for at least two identity providers: **Azure AD / Entra ID** and **Google Workspace**
- Pluggable provider architecture for future IdP additions
- JWT-based backend session tokens (stateless, RS256 or HS256)
- User identity model: `user_id`, `email`, `display_name`, `avatar_url`, `roles`
- Login page / SSO redirect flow
- Logout (local + optional IdP logout)
- Per-user isolation for:
  - LLM configuration (provider, model, credentials)
  - MCP server list
  - UI preferences (theme, message density, tool panel visibility)
  - Chat session history
- User settings API (`/api/users/me/settings`)
- Basic role model: `user` (default) and `admin`
- Admin-only: list all users, view/reset user settings
- Persistent user data storage (SQLite default; pluggable for Postgres)
- Session cookie with `HttpOnly`, `Secure`, `SameSite=Strict`
- CSRF protection for all state-mutating endpoints

### 2.2 Out of Scope
- SAML 2.0 provider support (Phase 2)
- Multi-tenant / organisation-level data isolation (Phase 2)
- Password-based local accounts (SSO-only in this version)
- Fine-grained RBAC beyond `user` / `admin` roles (Phase 2)
- User invitation / provisioning workflow
- Audit log retention and export
- SCIM provisioning from IdP
- SSO session token auto-refresh beyond a single silent renew

---

## 3. Functional Requirements

### 3.1 Authentication — Login Flow

#### FR-SSO-1.1: SSO Provider Selection
- **Priority**: P0 (Critical)
- **Description**: The application shall present a login screen with one button per configured SSO provider. Clicking a provider button initiates the OIDC Authorization Code Flow with PKCE.
- **Supported Providers (initial)**:
  | Provider Key | Label | Protocol |
  |---|---|---|
  | `azure_ad` | Sign in with Microsoft | OIDC (Azure Entra ID) |
  | `google` | Sign in with Google | OIDC (Google Workspace) |
- **UI**:
  - Full-screen centred login card
  - Application logo / name at the top
  - One styled button per enabled provider
  - "By signing in you accept the Terms of Use" footer
- **Acceptance Criteria**:
  - Only providers configured via environment variables are displayed
  - Clicking a provider button redirects to that provider's authorisation URL within 300 ms
  - PKCE code verifier is generated client-side and stored in `sessionStorage` (never persisted to `localStorage`)
  - Unauthenticated access to any app route redirects to the login page

#### FR-SSO-1.2: OIDC Callback Handling
- **Priority**: P0 (Critical)
- **Description**: The backend shall handle the OIDC redirect callback, exchange the authorisation code for tokens, validate the ID token, upsert the user record, and issue an application session token.
- **Callback Endpoint**: `GET /auth/callback/{provider}`
- **Processing Steps**:
  1. Verify `state` parameter matches the value stored in the browser `sessionStorage`
  2. Exchange `code` for `id_token` + `access_token` at the IdP token endpoint
  3. Validate `id_token` signature (JWKS), `iss`, `aud`, `exp`, `nonce`
  4. Extract claims: `sub`, `email`, `name`, `picture`
  5. Upsert user row in `users` table (insert on first login, update `last_login_at` on subsequent)
  6. Issue a signed application JWT (`app_token`) with: `user_id`, `email`, `roles`, `iat`, `exp`
  7. Set `app_token` as `HttpOnly; Secure; SameSite=Strict` cookie; max-age = configured session TTL
  8. Redirect browser to `/?sso=ok`
- **Acceptance Criteria**:
  - Invalid `state` or failed token exchange returns HTTP 401 with a user-facing error page
  - Expired or invalid `id_token` returns HTTP 401
  - Successful login sets the session cookie and loads the chat UI
  - First-time login creates a user record; repeat login updates `last_login_at` only

#### FR-SSO-1.3: Session Validation Middleware
- **Priority**: P0 (Critical)
- **Description**: All `/api/*` endpoints (except `/api/health`) shall require a valid session token. The middleware shall extract and validate the `app_token` cookie on every request.
- **Validation Steps**:
  1. Extract `app_token` from the request cookie header
  2. Verify JWT signature and expiry
  3. Load user record from DB; reject if user is `disabled`
  4. Attach `current_user` context to the request state
- **Acceptance Criteria**:
  - Missing or invalid token returns HTTP 401 `{"error": "Unauthorized"}`
  - Expired token returns HTTP 401 `{"error": "Session expired"}`
  - Disabled user returns HTTP 403 `{"error": "Account disabled"}`
  - Valid token allows the request to proceed with `current_user` populated

#### FR-SSO-1.4: Logout
- **Priority**: P1 (High)
- **Description**: Users shall be able to log out of the application session. An optional IdP front-channel logout may be triggered.
- **Endpoint**: `POST /auth/logout`
- **Actions**:
  1. Clear the `app_token` cookie (set `Max-Age=0`)
  2. Optionally redirect to the IdP's `end_session_endpoint` if configured
  3. Redirect browser to `/login`
- **UI**: "Sign out" option in the user menu (see FR-SSO-5.1)
- **Acceptance Criteria**:
  - After logout, accessing any app route redirects to `/login`
  - Session cookie is cleared in the browser
  - No user data from the previous session is visible in the new unauthenticated state

---

### 3.2 User Identity Model

#### FR-SSO-2.1: User Record
- **Priority**: P0 (Critical)
- **Description**: The backend shall maintain a persistent user table with the following attributes:

  | Column | Type | Description |
  |---|---|---|
  | `user_id` | `UUID` (PK) | Immutable internal identifier |
  | `provider` | `VARCHAR(32)` | SSO provider key (`azure_ad`, `google`) |
  | `provider_sub` | `VARCHAR(256)` | Immutable subject claim from IdP (`sub`) |
  | `email` | `VARCHAR(256)` | Primary email (unique index) |
  | `display_name` | `VARCHAR(256)` | Full name from IdP |
  | `avatar_url` | `TEXT` | Profile picture URL from IdP claims |
  | `roles` | `JSON` | List of roles e.g. `["user"]` or `["user", "admin"]` |
  | `is_active` | `BOOLEAN` | Soft-disable without deleting the record |
  | `created_at` | `TIMESTAMP` | First login |
  | `last_login_at` | `TIMESTAMP` | Most recent successful login |

- **Acceptance Criteria**:
  - `(provider, provider_sub)` pair is unique — prevents duplicate accounts across providers for the same real user
  - `email` uniqueness enforced at DB level
  - `user_id` is never exposed in the browser URL; used only in API payloads and cookies

#### FR-SSO-2.2: Current User Endpoint
- **Priority**: P1 (High)
- **Description**: The API shall expose a `GET /api/users/me` endpoint returning the authenticated user's profile.
- **Response Schema**:
  ```json
  {
    "user_id": "550e8400-e29b-41d4-a716-446655440001",
    "email": "alice@example.com",
    "display_name": "Alice Smith",
    "avatar_url": "https://lh3.googleusercontent.com/a/...",
    "roles": ["user"],
    "created_at": "2026-03-01T09:00:00Z",
    "last_login_at": "2026-03-15T08:45:00Z"
  }
  ```
- **Acceptance Criteria**:
  - Returns 200 with the authenticated user's profile
  - `client_secret`, `api_key`, and any credential fields are never included in this response
  - Returns 401 when unauthenticated

---

### 3.3 Per-User LLM Configuration

#### FR-SSO-3.1: User-Scoped LLM Config Storage
- **Priority**: P0 (Critical)
- **Description**: Each user shall have an independent copy of LLM configuration (provider, model, credentials, temperature, etc.). The shared in-memory `llm_config_storage` shall be replaced with a per-user store keyed by `user_id`.
- **Storage**: `user_llm_configs` table (SQLite/Postgres) with `user_id` FK
- **Existing API Endpoints** (updated to be user-scoped):
  - `GET /api/llm/config` — returns calling user's config
  - `POST /api/llm/config` — saves or updates calling user's config
  - `DELETE /api/llm/config` — clears calling user's config
- **Acceptance Criteria**:
  - User A's LLM config is completely invisible to User B
  - Saving a new config replaces the previous config for that user only
  - Deleting config removes only the calling user's record
  - First-time access with no saved config returns `null` / 404

#### FR-SSO-3.2: Credential Isolation
- **Priority**: P0 (Critical)
- **Description**: API keys, client secrets, and enterprise credentials stored in user LLM config must be isolated and only returned to the owning user.
- **Security Rules**:
  - `api_key` and `client_secret` values are **never logged** (backend or browser console)
  - Sensitive fields are stored encrypted at rest using AES-256-GCM with a server-managed key (`SECRET_KEY` env var)
  - API responses mask credentials: return `"api_key": "sk-...****"` (last 4 visible) to confirm presence without exposing the full value
  - Full credential value is never returned via GET; only re-submitted via POST to update
- **Acceptance Criteria**:
  - GET `/api/llm/config` returns `api_key: "sk-...****"` format, not the full key
  - POST `/api/llm/config` with a non-null credential field updates the stored value
  - POST `/api/llm/config` where the credential field is absent/null leaves the existing credential unchanged
  - Encrypted credential values are unreadable in the raw DB without the server key

---

### 3.4 Per-User MCP Server Configuration

#### FR-SSO-4.1: User-Scoped Server List
- **Priority**: P0 (Critical)
- **Description**: MCP server registrations shall be per-user. Each user maintains their own list of MCP servers and discovered tools; one user's servers are not visible to another.
- **Storage**: `user_servers` table with `user_id` FK replacing the shared in-memory `servers_storage` dict
- **Existing API Endpoints** (updated to be user-scoped):
  - `GET /api/servers` — returns only the calling user's servers
  - `POST /api/servers` — creates a server for the calling user
  - `PUT /api/servers/{server_id}` — updates only if calling user owns the server
  - `DELETE /api/servers/{server_id}` — deletes only if calling user owns the server
- **Acceptance Criteria**:
  - Cross-user server access returns HTTP 403
  - Server IDs are still UUIDs; no `user_id` prefix required
  - `GET /api/tools` returns only tools from the calling user's connected servers

#### FR-SSO-4.2: Tool Discovery Scope
- **Priority**: P1 (High)
- **Description**: Tool discovery (`GET /api/tools`, `POST /api/tools/refresh`) shall operate within the calling user's server scope only.
- **Acceptance Criteria**:
  - Refreshing tools for one user does not affect another user's tool cache
  - Namespaced tool IDs remain in `{server_alias}__{tool_name}` format
  - Tool execution in chat uses only the tools visible to the calling user's session

---

### 3.5 Per-User UI Preferences

#### FR-SSO-5.1: User Menu
- **Priority**: P1 (High)
- **Description**: The chat UI header shall include a **user avatar** and dropdown menu for the authenticated user.
- **User Menu Items**:
  | Item | Action |
  |---|---|
  | Avatar + Display Name | Static identity display |
  | Email | Static, greyed-out |
  | My Settings | Opens the Settings modal pre-navigated to "My Account" tab |
  | Sign Out | Calls `POST /auth/logout` |
- **Placement**: Top-right of the header bar, replacing the current "Settings" gear icon
- **Acceptance Criteria**:
  - Avatar image loaded from IdP `picture` claim; falls back to initials-based placeholder if URL is empty or fails to load
  - User menu opens on click; closes on outside click or Escape key
  - "Sign Out" completes within 1 second and redirects to `/login`

#### FR-SSO-5.2: Per-User UI Preferences Storage
- **Priority**: P2 (Medium)
- **Description**: User interface preferences shall be persisted per-user in the backend rather than only in `localStorage`. `localStorage` remains the fast-access cache; the backend is the source of truth on login.
- **Preference Keys**:
  | Key | Type | Default | Description |
  |---|---|---|---|
  | `theme` | `"light" \| "dark" \| "system"` | `"system"` | Colour scheme |
  | `message_density` | `"compact" \| "comfortable"` | `"comfortable"` | Chat bubble spacing |
  | `tool_panel_visible` | `boolean` | `true` | Show/hide tool execution panel |
  | `sidebar_collapsed` | `boolean` | `false` | Collapse left sidebar |
  | `default_llm_model` | `string \| null` | `null` | Quick-start model override |
- **API Endpoints**:
  - `GET /api/users/me/settings` — returns all preference keys
  - `PATCH /api/users/me/settings` — partial update; only provided keys are changed
- **Acceptance Criteria**:
  - Preferences load from backend on login and hydrate `localStorage`
  - Any preference change calls `PATCH /api/users/me/settings` within 500 ms (debounced)
  - On next login from a different browser, preferences are restored from backend
  - Unknown keys in `PATCH` body are ignored (forward compatibility)

#### FR-SSO-5.3: Settings Modal — "My Account" Tab
- **Priority**: P1 (High)
- **Description**: A new **"My Account"** tab shall be added as the first tab in the Settings modal, showing the signed-in user's identity and preference controls.
- **Tab Sections**:
  1. **Profile**: Read-only display of avatar, display name, email, SSO provider badge, member since date
  2. **Appearance**: Theme toggle (Light / Dark / System), message density selector
  3. **Chat Defaults**: Default tool panel visibility toggle
- **Acceptance Criteria**:
  - Tab renders for all authenticated users
  - Profile section data comes from `GET /api/users/me`; no edit controls in v0.4.0 (profile edit is Phase 2)
  - Preference changes in the UI are saved immediately (no explicit Save button needed)

---

### 3.6 Session Management (User-Scoped)

#### FR-SSO-6.1: Chat Sessions Tied to User Identity
- **Priority**: P0 (Critical)
- **Description**: Chat sessions (currently backend in-memory, keyed by `session_id`) shall be associated with `user_id`. A user can only read and write their own sessions.
- **Updated Endpoints**:
  - `POST /api/sessions` — creates a session owned by the calling user
  - `GET /api/sessions/{session_id}/messages` — returns 403 if calling user does not own the session
  - `POST /api/sessions/{session_id}/messages` — returns 403 if calling user does not own the session
- **Acceptance Criteria**:
  - Guessing another user's `session_id` returns HTTP 403
  - Sessions are still in-memory in v0.4.0; user-scoping is enforced in the session manager layer without requiring DB persistence of messages

#### FR-SSO-6.2: Session TTL and Inactivity Timeout
- **Priority**: P2 (Medium)
- **Description**: Application session tokens shall expire. The user shall be prompted to re-authenticate when the token expires.
- **Behaviour**:
  - Session TTL: configurable via `SSO_SESSION_TTL_HOURS` (default: 8 hours)
  - On expiry: any API call returns HTTP 401; the frontend catches this and redirects to `/login` with a `?reason=session_expired` parameter
  - Login page shows a banner: "Your session expired. Please sign in again."
- **Acceptance Criteria**:
  - Token with `exp` in the past is rejected by middleware
  - Frontend detects 401 responses and redirects to `/login` within 2 seconds
  - No partial data from the expired session is accessible after redirect

---

### 3.7 Admin Capabilities

#### FR-SSO-7.1: Admin Role Assignment
- **Priority**: P1 (High)
- **Description**: The `admin` role shall be assignable to users via an environment variable allowlist (`SSO_ADMIN_EMAILS`). Any user whose email matches the list is promoted to `admin` on every login.
- **Configuration**:
  ```
  SSO_ADMIN_EMAILS=alice@example.com,bob@corp.com
  ```
- **Acceptance Criteria**:
  - Admin role is re-evaluated at each login (adding/removing from env var takes effect without DB migration)
  - Non-admin users receive HTTP 403 when accessing any `/api/admin/*` endpoint

#### FR-SSO-7.2: User Management API (Admin Only)
- **Priority**: P1 (High)
- **Description**: Admins shall have access to endpoints for viewing and managing users.
- **Endpoints**:

  | Method | Path | Description |
  |---|---|---|
  | `GET` | `/api/admin/users` | List all users (paginated) |
  | `GET` | `/api/admin/users/{user_id}` | Get a specific user's profile |
  | `PATCH` | `/api/admin/users/{user_id}` | Enable/disable user (`is_active`) |
  | `DELETE` | `/api/admin/users/{user_id}/settings` | Reset user's LLM config and UI preferences |

- **Acceptance Criteria**:
  - All endpoints return 403 for non-admin callers
  - `DELETE /api/admin/users/{user_id}/settings` does not delete the user record, only their settings
  - Disabled users (`is_active=false`) are blocked at middleware (FR-SSO-1.3)
  - Pagination uses `limit` + `offset` query parameters; default `limit=50`

---

## 4. Non-Functional Requirements

### 4.1 Security

| ID | Requirement |
|---|---|
| NFR-SEC-1 | All SSO redirect URIs must be registered in the IdP application; unregistered URIs are rejected |
| NFR-SEC-2 | PKCE (`S256`) is mandatory; implicit flow is not supported |
| NFR-SEC-3 | `state` parameter validated on every callback to prevent CSRF on the OIDC flow |
| NFR-SEC-4 | Session cookie is `HttpOnly; Secure; SameSite=Strict`; not accessible from JavaScript |
| NFR-SEC-5 | CSRF token required as `X-CSRF-Token` header on all mutating API requests |
| NFR-SEC-6 | Credentials (API keys, client secrets) encrypted at rest; AES-256-GCM, key from `SECRET_KEY` env var |
| NFR-SEC-7 | Credential values are never returned in full from any GET endpoint |
| NFR-SEC-8 | JWKS public keys cached with a TTL of 1 hour; forced refresh on validation failure |
| NFR-SEC-9 | IdP `nonce` claim validated in `id_token` to prevent replay attacks |
| NFR-SEC-10 | All `http://` SSO endpoints rejected; HTTPS enforced for all IdP and token URLs |

### 4.2 Performance

| ID | Requirement |
|---|---|
| NFR-PERF-1 | OIDC callback to chat UI load: ≤ 2 seconds (P95) on LAN |
| NFR-PERF-2 | `GET /api/users/me` response: ≤ 100 ms (P95) |
| NFR-PERF-3 | `PATCH /api/users/me/settings` response: ≤ 200 ms (P95) |
| NFR-PERF-4 | Session middleware adds ≤ 5 ms overhead per request |
| NFR-PERF-5 | JWKS fetch cached; no live JWKS call on the hot request path |

### 4.3 Compatibility

| ID | Requirement |
|---|---|
| NFR-COMPAT-1 | Existing `REQUIREMENTS.md` v0.2.0 APIs remain unchanged for authenticated users |
| NFR-COMPAT-2 | `ENTERPRISE_GATEWAY_REQUIREMENTS.md` v0.3.0 enterprise token flow unaffected; enterprise token is still per-server-session in v0.4.0 |
| NFR-COMPAT-3 | `localStorage` keys from v0.2.0 / v0.3.0 migrated on first login: prefixed with `user:{user_id}:` to avoid cross-user contamination on shared browsers |

---

## 5. API Contract Changes

### 5.1 New Auth Endpoints

| Method | Path | Auth Required | Description |
|---|---|---|---|
| `GET` | `/auth/login` | No | Render login page |
| `GET` | `/auth/login/{provider}` | No | Initiate OIDC flow for a given provider |
| `GET` | `/auth/callback/{provider}` | No | Handle OIDC redirect callback |
| `POST` | `/auth/logout` | Yes | Clear session and redirect to `/login` |

### 5.2 New User Endpoints

| Method | Path | Auth Required | Description |
|---|---|---|---|
| `GET` | `/api/users/me` | User | Get own profile |
| `GET` | `/api/users/me/settings` | User | Get own UI preferences |
| `PATCH` | `/api/users/me/settings` | User | Partial update of own UI preferences |

### 5.3 New Admin Endpoints

| Method | Path | Auth Required | Description |
|---|---|---|---|
| `GET` | `/api/admin/users` | Admin | List all users (paginated) |
| `GET` | `/api/admin/users/{user_id}` | Admin | Get user profile |
| `PATCH` | `/api/admin/users/{user_id}` | Admin | Enable or disable user |
| `DELETE` | `/api/admin/users/{user_id}/settings` | Admin | Reset user settings |

### 5.4 Modified Existing Endpoints (User-Scoped)

All existing `/api/*` endpoints below gain implicit user scoping — no URL changes, only middleware context:

| Endpoint | Change |
|---|---|
| `GET /api/llm/config` | Returns calling user's config only |
| `POST /api/llm/config` | Saves to calling user's record |
| `GET /api/servers` | Returns calling user's servers only |
| `POST /api/servers` | Assigns server to calling user |
| `PUT /api/servers/{server_id}` | 403 if not owner |
| `DELETE /api/servers/{server_id}` | 403 if not owner |
| `GET /api/tools` | Tools from calling user's servers only |
| `POST /api/sessions` | Session owned by calling user |
| `POST /api/sessions/{id}/messages` | 403 if session not owned by calling user |
| `GET /api/sessions/{id}/messages` | 403 if session not owned by calling user |

---

## 6. Data Model

### 6.1 Database Schema (SQLite / Postgres compatible)

```sql
-- Users table
CREATE TABLE users (
    user_id       TEXT PRIMARY KEY,          -- UUID
    provider      TEXT NOT NULL,             -- 'azure_ad' | 'google'
    provider_sub  TEXT NOT NULL,             -- IdP subject claim
    email         TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL DEFAULT '',
    avatar_url    TEXT,
    roles         TEXT NOT NULL DEFAULT '["user"]',  -- JSON array
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (provider, provider_sub)
);

-- Per-user LLM configurations
CREATE TABLE user_llm_configs (
    user_id       TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    config_json   TEXT NOT NULL,             -- Encrypted JSON blob (LLMConfig)
    updated_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Per-user MCP server registrations
CREATE TABLE user_servers (
    server_id     TEXT NOT NULL,             -- UUID
    user_id       TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    config_json   TEXT NOT NULL,             -- JSON blob (ServerConfig)
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (server_id),
    UNIQUE (user_id, server_id)
);

-- Per-user UI preferences
CREATE TABLE user_settings (
    user_id                TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    theme                  TEXT NOT NULL DEFAULT 'system',
    message_density        TEXT NOT NULL DEFAULT 'comfortable',
    tool_panel_visible     BOOLEAN NOT NULL DEFAULT TRUE,
    sidebar_collapsed      BOOLEAN NOT NULL DEFAULT FALSE,
    default_llm_model      TEXT,
    updated_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 6.2 New Pydantic Models

```python
class UserProfile(BaseModel):
    """Authenticated user profile"""
    user_id: str
    email: str
    display_name: str
    avatar_url: Optional[str]
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

class SSOProviderConfig(BaseModel):
    """SSO Identity Provider configuration"""
    provider_key: str           # 'azure_ad' | 'google'
    client_id: str
    client_secret: str          # Loaded from env only; never stored in DB
    discovery_url: str          # OIDC discovery doc URL
    redirect_uri: str           # Must match IdP registration
    scopes: List[str] = ["openid", "email", "profile"]
```

---

## 7. Environment Variable Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | Yes | — | 32-byte hex key for JWT signing and credential encryption |
| `SSO_SESSION_TTL_HOURS` | No | `8` | Application session token lifetime |
| `SSO_ADMIN_EMAILS` | No | `""` | Comma-separated list of admin email addresses |
| `AZURE_AD_CLIENT_ID` | If using Azure | — | Azure AD app registration client ID |
| `AZURE_AD_CLIENT_SECRET` | If using Azure | — | Azure AD app registration client secret |
| `AZURE_AD_TENANT_ID` | If using Azure | — | Azure AD tenant ID (used to form discovery URL) |
| `AZURE_AD_REDIRECT_URI` | If using Azure | — | Must match registered redirect URI in Azure |
| `GOOGLE_CLIENT_ID` | If using Google | — | Google OAuth 2.0 client ID |
| `GOOGLE_CLIENT_SECRET` | If using Google | — | Google OAuth 2.0 client secret |
| `GOOGLE_REDIRECT_URI` | If using Google | — | Must match registered redirect URI in Google Cloud Console |
| `DB_URL` | No | `sqlite:///./mcp_client.db` | SQLAlchemy database URL |
| `JWKS_CACHE_TTL_SECONDS` | No | `3600` | How long to cache IdP JWKS keys |

---

## 8. UI Changes Summary

### 8.1 New Pages / Routes

| Route | Description |
|---|---|
| `/login` | SSO provider selection page |
| `/auth/callback/{provider}` | Handled by backend; browser lands here then redirects to `/` |

### 8.2 Modified Components

| Component | Change |
|---|---|
| `index.html` | Adds login-guard: redirect to `/login` if no valid session cookie detected |
| `app.js` | Adds 401 response interceptor; calls `GET /api/users/me` on load to populate user context |
| `settings.js` | Adds "My Account" as first tab; all subsequent tabs remain unchanged |
| Header bar | Replaces gear icon with user avatar + dropdown menu |

### 8.3 localStorage Key Migration

On first authenticated load, v0.2.0 / v0.3.0 `localStorage` keys are migrated:

| Old Key | New Key Pattern |
|---|---|
| `mcpServers` | `user:{user_id}:mcpServers` |
| `llmConfig` | `user:{user_id}:llmConfig` (superseded by backend; kept as cache only) |
| `llmGatewayMode` | `user:{user_id}:llmGatewayMode` |
| `enterpriseCustomModels` | `user:{user_id}:enterpriseCustomModels` |

---

## 9. Acceptance Testing

| Test ID | Description | Expected Result |
|---|---|---|
| AT-SSO-01 | Unauthenticated access to `/` | Redirects to `/login` |
| AT-SSO-02 | Click "Sign in with Google" | Redirects to Google OIDC authorisation URL with `state`, `nonce`, `code_challenge` |
| AT-SSO-03 | Successful Google login | Session cookie set; chat UI loads; user avatar displayed |
| AT-SSO-04 | Successful Azure AD login | Session cookie set; chat UI loads with correct display name |
| AT-SSO-05 | Invalid OIDC `state` parameter | Callback returns 401; error page shown |
| AT-SSO-06 | Expired `id_token` | Callback returns 401; error page shown |
| AT-SSO-07 | Sign Out | Session cookie cleared; redirected to `/login`; accessing `/` redirects to login |
| AT-SSO-08 | Session expiry (API call after TTL) | Returns 401; frontend redirects to `/login?reason=session_expired`; banner shown |
| AT-SSO-09 | User A cannot read User B's servers | `GET /api/servers` returns only User A's servers |
| AT-SSO-10 | User A cannot access User B's session | `POST /api/sessions/{B_session_id}/messages` returns 403 |
| AT-SSO-11 | User A cannot read User B's LLM config | `GET /api/llm/config` returns only User A's config |
| AT-SSO-12 | API key not returned in full | `GET /api/llm/config` returns `api_key: "sk-...****"` not the full key |
| AT-SSO-13 | POST LLM config with no credential field | Existing credential unchanged |
| AT-SSO-14 | Admin lists all users | `GET /api/admin/users` returns all users for admin; 403 for regular user |
| AT-SSO-15 | Admin disables user | Disabled user's next API call returns 403 |
| AT-SSO-16 | Admin resets user settings | `DELETE /api/admin/users/{id}/settings` clears LLM config and preferences; user record intact |
| AT-SSO-17 | Preferences persist across logins | Change theme → log out → log in from different browser → theme restored |
| AT-SSO-18 | localStorage migration | After first login, old keys renamed with `user:{id}:` prefix; no data loss |
| AT-SSO-19 | CSRF token required on mutation | POST without `X-CSRF-Token` header returns 403 |
| AT-SSO-20 | Secret key never logged | Grep backend logs — no `client_secret` or `SECRET_KEY` value appears |
| AT-SSO-21 | Admin email promotion on login | Adding email to `SSO_ADMIN_EMAILS` → user gains admin role on next login |
| AT-SSO-22 | `GET /api/users/me` returns 401 unauthenticated | Response body: `{"error": "Unauthorized"}` |
| AT-SSO-23 | `PATCH /api/users/me/settings` partial update | Only the supplied keys change; others remain at previous values |
| AT-SSO-24 | Avatar fallback | Invalid `avatar_url` → initials placeholder shown in header |
| AT-SSO-25 | "My Account" tab visible | Settings modal first tab shows correct profile and preference controls |

---

## 10. Constraints and Assumptions

### 10.1 Constraints
- IdP registration (redirect URIs, client IDs/secrets) must be completed before deployment; this is outside the application's scope
- Token encryption key (`SECRET_KEY`) must be rotated out-of-band; rotation invalidates all existing sessions
- SQLite is the default DB; horizontal scaling requires switching to Postgres and externalising session state
- Chat session history is still in-memory; it is lost on server restart regardless of user auth state (database-backed chat history is Phase 2)
- The OIDC discovery document endpoint must be publicly reachable from the FastAPI server at startup

### 10.2 Assumptions
- The enterprise IdP (Azure AD) supports OIDC Authorization Code Flow with PKCE
- Google Workspace accounts include `email` and `profile` scopes by default
- `picture` claim is included in the IdP `id_token` or `userinfo` response
- The backend and browser share the same origin (or CORS is configured for the specific frontend origin)
- A single deployment serves one organisation; multi-tenant namespace isolation is not required in v0.4.0

---

## 11. Open Questions

| # | Question | Owner | Status |
|---|---|---|---|
| OQ-1 | Should the `provider_sub` + `email` uniqueness allow account linking across IdPs (e.g. same person logs in via both Google and Azure)? | Product | Open |
| OQ-2 | Is a local dev mode (bypass SSO, hard-coded dev user) acceptable for developer environments? | Engineering | Open |
| OQ-3 | Should user profile fields (display name, avatar) be editable in the app, or always IdP-sourced? | Product | Open |
| OQ-4 | What is the expected max number of concurrent users? This affects the in-memory session design choice. | Product | Open |
| OQ-5 | Should SAML 2.0 be supported in v0.4.0 or deferred to v0.5.0? | Product | Open |
| OQ-6 | Is `SameSite=Strict` acceptable for the deployment topology, or is `SameSite=Lax` needed for IdP redirect back? | Security | Open |
| OQ-7 | Should the credential encryption key (`SECRET_KEY`) be stored in a secrets manager (Vault, AWS SSM) rather than an env var? | Security | Open |
| OQ-8 | Are there GDPR/data-residency requirements for storing user email and profile data? | Legal / Compliance | Open |

---

## 12. Document Control

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.1 | 2026-03-15 | AI Assistant | Initial draft — SSO authentication and per-user settings requirements |

**Review Checklist**

- [ ] Security review: PKCE flow, cookie flags, credential encryption, CSRF
- [ ] UI/UX review: login page, user menu, "My Account" tab
- [ ] Backend review: session middleware, user scoping, DB schema
- [ ] QA review: acceptance test coverage (AT-SSO-01 through AT-SSO-25)
- [ ] Legal / Compliance review: PII handling (email, avatar URL), GDPR implications
- [ ] Open questions resolved before implementation start

**Approval**

| Role | Name | Signature | Date |
|---|---|---|---|
| Product Owner | _______________ | _______________ | _______ |
| Technical Lead | _______________ | _______________ | _______ |
| Security Lead | _______________ | _______________ | _______ |
| QA Lead | _______________ | _______________ | _______ |
