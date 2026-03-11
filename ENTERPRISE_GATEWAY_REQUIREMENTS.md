# Enterprise LLM Gateway Integration - Requirements Document

**Project**: MCP Client Web Interface  
**Feature**: Enterprise LLM Gateway Support (Comcast-LLM)  
**Version**: 0.3.0-enterprise-gateway  
**Date**: March 10, 2026  
**Status**: Implemented (Initial v0.3.0 scope)  
**Parent Document**: REQUIREMENTS.md (v0.2.0-jsonrpc)

---

## 1. Executive Summary

This document describes the requirements for adding **Enterprise LLM Gateway** support to the MCP Client Web application. The feature introduces a gateway mode selector in the UI that allows users to switch between **Non-Enterprise** (standard OpenAI/Ollama) and **Enterprise** (Comcast-LLM) gateway modes. When Enterprise mode is selected, the system authenticates against a corporate OAuth token endpoint, caches the bearer token, and routes all LLM inference requests through the Comcast Model Gateway using an OpenAI-compatible `/chat/completions` API.

### 1.1 Implementation Alignment Notes

- Enterprise configuration is persisted through the existing `POST /api/llm/config` endpoint by extending the shared `LLMConfig` model, rather than introducing a separate LLM config endpoint.
- Enterprise mode is represented explicitly as `gateway_mode = enterprise` and `provider = enterprise` in saved configuration payloads.
- The enterprise model catalog and custom model extensions are managed in the frontend with `localStorage`; a dedicated backend `/api/enterprise/models` endpoint is not required in the current implementation.
- The Enterprise Gateway base URL is required in the saved UI configuration in v0.3.0. Backend environment-based fallback for an omitted UI value remains a future enhancement.

---

## 2. Scope

### 2.1 In Scope
- UI gateway mode selector (Enterprise / Non-Enterprise toggle)
- Comcast-LLM provider with predefined model catalog (AWS + Azure backed)
- OAuth 2.0 bearer token acquisition via `X-Client-Id` / `X-Client-Secret`
- Token caching in backend temporary storage (in-memory)
- LLM Gateway URL configuration (UI + environment variable)
- Backend API adapter for Comcast Model Gateway (OpenAI-compatible format)
- Model list management: defaults + user-extensible entries
- Secure credential handling for enterprise secrets

### 2.2 Out of Scope
- Token refresh / expiry management (Phase 2)
- Multi-tenant enterprise credential vaults
- Persistent token storage (database)
- Streaming responses from Enterprise Gateway
- Role-based access control for enterprise models

---

## 3. Functional Requirements

### 3.1 Gateway Mode Selection (UI)

#### FR-EG-1.1: Gateway Mode Selector
- **Priority**: P0 (Critical)
- **Description**: The LLM Configuration settings tab shall include a **Gateway Mode** selector allowing the user to choose between Non-Enterprise and Enterprise gateway modes.
- **UI Placement**: Top of the "LLM Config" settings tab, above existing provider fields
- **Options**:
  | Value | Label | Description |
  |-------|-------|-------------|
  | `standard` | Non-Enterprise Gateway | Existing behavior: OpenAI / Ollama |
  | `enterprise` | Enterprise Gateway | Routes to Comcast-LLM model gateway |
- **Default**: `standard` (preserves backward compatibility)
- **Behavior**:
  - Switching to `enterprise` hides standard provider fields (OpenAI/Ollama) and reveals Enterprise Gateway configuration panel
  - Switching back to `standard` restores the original provider selection UI
  - Selection persists to `localStorage` under key `llmGatewayMode`
- **Acceptance Criteria**:
  - Mode selector renders as a toggle or radio group clearly labelled
  - Switching mode updates visible configuration panels without page reload
  - Selected mode is saved on every change (no explicit save needed for mode itself)
  - Mode setting survives page reload via `localStorage`

---

### 3.2 Enterprise Gateway Configuration Panel (UI)

#### FR-EG-2.1: Enterprise Provider Identity
- **Priority**: P0 (Critical)
- **Description**: When Enterprise mode is active, the UI shall present a fixed provider label **"Comcast-LLM"** (non-editable) as the active LLM provider.
- **Acceptance Criteria**:
  - Label "Comcast-LLM" displayed as read-only field or badge
  - No free-text provider input shown in enterprise mode

#### FR-EG-2.2: Model Catalog with Defaults
- **Priority**: P0 (Critical)
- **Description**: The Enterprise Gateway panel shall display a **model selection dropdown** pre-populated with the following default models:

  | Type | Model ID | Backend Provider |
  |------|----------|-----------------|
  | LLM | `claude-3-7-sonnet` | AWS |
  | LLM | `claude-4-5-haiku` | AWS |
  | LLM | `claude-4-5-sonnet` | AWS |
  | LLM | `claude-4-6-sonnet` | AWS |
  | LLM | `claude-4-sonnet` | AWS |
  | LLM | `nova-lite` | AWS |
  | LLM | `nova-micro` | AWS |
  | LLM | `nova-pro` | AWS |
  | LLM | `gpt-41` | Azure |
  | LLM | `gpt-4o` | Azure |
  | LLM | `gpt-5-1` | Azure |
  | LLM | `gpt-5-2` | Azure |
  | LLM | `gpt-5-mini` | Azure |
  | LLM | `gpt-5-nano` | Azure |
  | LLM | `o4-mini` | Azure |
  | Embedding | `text-embedding-3-large` | Azure |

- **Default Selected Model**: `gpt-4o` (Azure)
- **Display Format**: Dropdown entries show `<model-id> (<provider>)` e.g. `gpt-4o (Azure)`
- **Acceptance Criteria**:
  - Dropdown renders all 16 default models on first load
  - Selected model persists to `localStorage`
  - Only LLM-type models are used for chat completions (Embedding type models shown but labelled as non-chat)
  - Default selection is `gpt-4o` on first use

#### FR-EG-2.3: User-Extensible Model List
- **Priority**: P1 (High)
- **Description**: Users shall be able to add custom model entries beyond the defaults.
- **UI**:
  - "Add Model" button below the model dropdown
  - Inline form with fields: `Model ID` (text), `Provider` (text, e.g. Azure/AWS/Other), `Type` (LLM / Embedding)
  - "Save" and "Cancel" buttons on the inline form
  - Custom entries appear at the bottom of the dropdown, visually distinguished (e.g. italic or badge)
- **Acceptance Criteria**:
  - Custom models persist to `localStorage` under `enterpriseCustomModels`
  - Custom models merge with defaults at runtime (defaults always present)
  - Duplicate model IDs are rejected with an inline error
  - Custom models can be removed via a delete (×) icon in the model list management view

#### FR-EG-2.4: LLM Gateway URL Configuration
- **Priority**: P0 (Critical)
- **Description**: The Enterprise Gateway panel shall include a text input for the **LLM Gateway Base URL**.
- **Field Label**: `LLM Gateway URL`
- **Placeholder**: `https://<LLM-GATEWAY-HOST>/modelgw/models/openai/v1`
- **Validation**: Must be a valid HTTPS URL
- **Environment Variable Override**: Deferred in current implementation; the UI-saved value is required and used as the source of truth in v0.3.0.
- **Acceptance Criteria**:
  - Field is required when saving Enterprise Gateway configuration
  - Value persists to `localStorage`
  - Empty or invalid URL prevents saving with an inline error message
  - Backend falls back to `ENTERPRISE_LLM_GATEWAY_URL` env var if UI value absent

---

### 3.3 Enterprise Authentication Configuration (UI)

#### FR-EG-3.1: Authentication Method Selection
- **Priority**: P0 (Critical)
- **Description**: The Enterprise Gateway panel shall include an **Authentication Method** selector.
- **Supported Methods**:
  | Value | Label |
  |-------|-------|
  | `bearer` | Bearer Token (OAuth) |
- **Note**: Only `bearer` is in scope for v0.3.0. The selector is included to allow future extension (e.g. mTLS, API Key).
- **Acceptance Criteria**:
  - Default selection is `bearer`
  - Selecting `bearer` reveals the Bearer Token credential fields (FR-EG-3.2)

#### FR-EG-3.2: Bearer Token Credential Fields
- **Priority**: P0 (Critical)
- **Description**: When `bearer` authentication is selected, the following credential fields shall be shown:

  | Field Label | Field Name | Input Type | Required |
  |------------|------------|------------|----------|
  | `X-Client-Id` | `clientId` | `text` | Yes |
  | `X-Client-Secret` | `clientSecret` | `password` | Yes |
  | `Token Endpoint URL` | `tokenEndpointUrl` | `text` | Yes |

- **Security**:
  - `X-Client-Secret` rendered as `type="password"` (masked by default)
  - Credentials **must not** appear in any log output (backend or browser console)
  - Credentials stored in `localStorage` with acknowledgement that this is plaintext (display a one-time security notice)
- **Token Endpoint URL**:
  - Placeholder: `https://<TOKEN-ENDPOINT-HOST>/v2/oauth/token`
  - Must be a valid HTTPS URL
- **Acceptance Criteria**:
  - All three fields are required; saving without them shows inline validation errors
  - `X-Client-Secret` is masked; toggle-to-reveal icon (eye icon) optional
  - Values persist to `localStorage` after saving
  - Backend receives credentials via `POST /api/llm/config` as part of the extended `LLMConfig`

---

### 3.4 Token Acquisition (Backend)

#### FR-EG-4.1: OAuth Bearer Token API
- **Priority**: P0 (Critical)
- **Description**: The backend shall expose an endpoint to trigger token acquisition from the enterprise OAuth server and cache the result.

- **Endpoint**: `POST /api/enterprise/token`
- **Request Body**:
  ```json
  {
    "token_endpoint_url": "https://test.tv.test.net/v2/oauth/token",
    "client_id": "<X-Client-Id>",
    "client_secret": "<X-Client-Secret>"
  }
  ```
- **Backend Action**: Issues the following HTTP request to the token endpoint:
  ```
  POST <token_endpoint_url>
  Content-Type: application/json
  X-Client-Id: <client_id>
  X-Client-Secret: <client_secret>
  Body: (empty / {})
  ```
  Equivalent curl:
  ```bash
  curl --location --request POST '<TOKEN_ENDPOINT_URL>/v2/oauth/token' \
    --header 'Content-Type: application/json' \
    --header 'X-Client-Id: <X-Client-Id>' \
    --header 'X-Client-Secret: <X-Client-Secret>' \
    --data ''
  ```
- **Response** (success):
  ```json
  {
    "token_acquired": true,
    "expires_in": 3600,
    "cached_at": "2026-03-10T12:00:00Z"
  }
  ```
- **Response** (failure):
  ```json
  {
    "token_acquired": false,
    "error": "Token endpoint returned 401 Unauthorized"
  }
  ```
- **Acceptance Criteria**:
  - Uses `httpx.AsyncClient` with `httpx.Timeout` object (connect=5, read=20, write=5, pool=5)
  - Raw token value is **never** returned in the API response (only metadata)
  - HTTP 200 on success; HTTP 502 on upstream failure; HTTP 422 on validation error
  - Logs directional arrows using `logger_external`: `→ POST <token_endpoint_host>`, `← 200 OK`
  - Logs a **redacted curl equivalent** of the token request at `DEBUG` level using `logger_external`, with all secret values replaced by `[REDACTED]`:
    ```
    [enterprise] token request curl equivalent:
    curl --location --request POST 'https://<TOKEN_ENDPOINT_HOST>/v2/oauth/token' \
      --header 'Content-Type: application/json' \
      --header 'X-Client-Id: [REDACTED]' \
      --header 'X-Client-Secret: [REDACTED]' \
      --data ''
    ```
  - The `X-Client-Id` value and `X-Client-Secret` value are **always** replaced with `[REDACTED]` in this log line — the literal header names are logged, not their values

#### FR-EG-4.2: Token Caching (In-Memory)
- **Priority**: P0 (Critical)
- **Description**: Acquired bearer tokens shall be cached in backend in-memory storage for reuse across LLM requests within the same process lifetime.
- **Cache Structure**:
  ```python
  enterprise_token_cache = {
      "access_token": "<raw_token>",
      "cached_at": datetime,
      "expires_in": int  # seconds, from token response
  }
  ```
- **Cache Key**: Single global cache (single-user application)
- **Cache Invalidation**: Cache is cleared on:
  - Application restart
  - Explicit `DELETE /api/enterprise/token` request
  - Token acquisition of a new token (overwrite)
- **Token Reuse**: Before each LLM request, backend checks if a cached token exists. If yes, reuses it. If no, returns HTTP 401-like error prompting UI to trigger token acquisition first.
- **Acceptance Criteria**:
  - Token not stored in any file or database
  - Token not returned via any API endpoint (opaque cache)
  - UI can check cache status via `GET /api/enterprise/token/status`

#### FR-EG-4.3: Token Status Endpoint
- **Priority**: P1 (High)
- **Description**: Provide a status endpoint so the UI can indicate whether a valid token is cached.
- **Endpoint**: `GET /api/enterprise/token/status`
- **Response**:
  ```json
  {
    "token_cached": true,
    "cached_at": "2026-03-10T12:00:00Z",
    "expires_in": 3600
  }
  ```
- **Acceptance Criteria**:
  - Returns `token_cached: false` when no token is in memory
  - Raw token value never included in response
  - UI polls this endpoint after triggering token acquisition to confirm success

---

### 3.5 LLM Request Routing (Backend)

#### FR-EG-5.1: Enterprise LLM Config Model
- **Priority**: P0 (Critical)
- **Description**: Extend the `LLMConfig` Pydantic model to accommodate enterprise gateway settings alongside existing standard provider fields.
- **New Fields**:
  ```python
  class LLMConfig(BaseModel):
      # Existing fields (unchanged)
      provider: str                     # "openai" | "ollama" | "mock" | "enterprise"
      model: str
      base_url: Optional[str]
      api_key: Optional[str]
      
      # New enterprise fields
      gateway_mode: str = "standard"    # "standard" | "enterprise"
      enterprise_gateway_url: Optional[str]       # LLM Gateway base URL
      enterprise_token_endpoint: Optional[str]    # OAuth token endpoint URL
      enterprise_client_id: Optional[str]         # X-Client-Id
      enterprise_client_secret: Optional[str]     # X-Client-Secret (masked in logs)
      enterprise_auth_method: str = "bearer"      # "bearer" (extensible)
  ```
- **Acceptance Criteria**:
  - Existing LLM config endpoints remain backward compatible
  - `enterprise_client_secret` excluded from all log output
  - OpenAPI schema updated at `/docs`

#### FR-EG-5.2: Enterprise LLM Client Adapter
- **Priority**: P0 (Critical)
- **Description**: Implement a new `EnterpriseLLMClient` class in `llm_client.py` that routes inference requests to the Comcast Model Gateway.
- **Endpoint Pattern**:
  ```
  POST {ENTERPRISE_LLM_GATEWAY_URL}/chat/completions
  ```
  Full example:
  ```
  POST https://<LLM-GATEWAY-HOST>/modelgw/models/openai/v1/chat/completions
  ```
- **Request Format** (OpenAI-compatible):
  ```json
  {
    "model": "<selected-model-id>",
    "messages": [ { "role": "user", "content": "<prompt>" } ],
    "tools": [ ... ],
    "max_tokens": 4096,
    "stream": false
  }
  ```
  Equivalent curl (where `<SELECTED-MODEL>` is the model chosen in the Enterprise UI dropdown):
  ```bash
  curl https://<LLM-GATEWAY-URL>/modelgw/models/openai/v1/chat/completions -X POST \
    -H 'Content-Type: application/json' \
    -H 'Authorization: Bearer <TOKEN>' \
    -d '{
      "model": "<SELECTED-MODEL>",
      "messages": [{"role": "user", "content": "<PROMPT>"}],
      "max_tokens": 4096,
      "stream": false
    }'
  ```
- **Model Source**: The `model` field in every request **must** be set to the value of `enterpriseSelectedModel` from the active session's LLM config — i.e. whatever model the user has chosen in the Enterprise Gateway UI dropdown. It must **never** be hardcoded.
- **Authentication Header**: `Authorization: Bearer <cached_token>`
- **Tool Calling**: Uses OpenAI tool-calling format (same as standard OpenAI adapter). `tool_call_id` used in responses.
- **Response Parsing**: Identical to existing OpenAI response parser (OpenAI-compatible response schema).
- **Error Handling**:
  - HTTP 401 from gateway → surface as "Token expired or invalid. Re-acquire token." with prompt to re-authenticate
  - HTTP 429 → surface as "Rate limit exceeded"
  - HTTP 5xx → surface as "Enterprise gateway error: <status>"
- **Acceptance Criteria**:
  - `EnterpriseLLMClient` implements the same base interface as `OpenAILLMClient`
  - The `model` field in the request payload is always read from `LLMConfig.model` (populated from the UI dropdown selection) — never hardcoded
  - Changing the model in the Enterprise UI dropdown and saving immediately affects the next LLM request without restart
  - Bearer token injected from in-memory cache (never from request parameters)
  - `Authorization` header value **never** logged (replaced with `[REDACTED]`)
  - Falls back to descriptive error message if token cache is empty
  - Uses `httpx.Timeout(connect=5.0, read=60.0, write=5.0, pool=5.0)` (higher read timeout for enterprise latency)
  - Logs a **redacted curl equivalent** of every LLM gateway request at `DEBUG` level using `logger_external`, with the bearer token replaced by `[REDACTED]` and message content truncated to 200 chars:
    ```
    [enterprise] LLM request curl equivalent:
    curl 'https://<LLM-GATEWAY-HOST>/modelgw/models/openai/v1/chat/completions' -X POST \
      -H 'Content-Type: application/json' \
      -H 'Authorization: Bearer [REDACTED]' \
      -d '{ "model": "<SELECTED-MODEL>", "messages": [{"role": "user", "content": "<first 200 chars>..."}], "max_tokens": 4096, "stream": false }'
    ```
  - `<SELECTED-MODEL>` in the log is the actual model ID from the UI selection (not redacted — model name is not sensitive)
  - Full message body (with all messages and tools) is logged at `DEBUG` level separately, also with the token redacted

#### FR-EG-5.3: Provider Routing
- **Priority**: P0 (Critical)
- **Description**: The LLM client factory in `llm_client.py` shall route to `EnterpriseLLMClient` when `gateway_mode == "enterprise"` or `provider == "enterprise"`.
- **Acceptance Criteria**:
  - `get_llm_client(config)` factory returns `EnterpriseLLMClient` for enterprise mode
  - Standard providers (`openai`, `ollama`, `mock`) unaffected
  - Session creation validates that a cached token exists before allowing enterprise chat

---

### 3.6 UI Enterprise Panel — Interaction Flows

#### FR-EG-6.1: "Fetch Token" Button
- **Priority**: P0 (Critical)
- **Description**: The Enterprise Gateway configuration panel shall include a **"Fetch Token"** button that triggers token acquisition.
- **Button States**:
  | State | Label | Style |
  |-------|-------|-------|
  | Idle (no token) | `Fetch Token` | Primary button |
  | Loading | `Fetching…` | Disabled, spinner |
  | Success | `Token Active ✓` | Green, disabled |
  | Error | `Fetch Failed ✗` | Red, re-clickable |
- **Action**: Calls `POST /api/enterprise/token` with credentials from form fields
- **On Success**: Shows token status badge with `cached_at` timestamp
- **On Failure**: Displays error message inline below the button
- **Acceptance Criteria**:
  - Button disabled while fetching
  - Success state shows timestamp: `Token active since 12:00 PM`
  - Error message clears on next fetch attempt
  - Token status checked via `GET /api/enterprise/token/status` on settings modal open

#### FR-EG-6.2: Save Enterprise Configuration
- **Priority**: P0 (Critical)
- **Description**: A **"Save Enterprise Config"** button shall persist all enterprise settings.
- **Saved Fields**:
  - LLM Gateway URL
  - Token Endpoint URL
  - X-Client-Id
  - X-Client-Secret
  - Selected Model
  - Auth Method
- **Action**: Calls `PUT /api/llm-config` with updated `LLMConfig` payload
- **Acceptance Criteria**:
  - All required fields validated before save
  - Inline validation errors per field on missing/invalid values
  - Success toast notification on save
  - Settings modal remains open after save
  - `localStorage` updated on successful API response

#### FR-EG-6.3: One-Time Security Notice
- **Priority**: P1 (High)
- **Description**: On first save of enterprise credentials, display a dismissible security notice.
- **Notice Text**: `"Enterprise credentials (X-Client-Id and X-Client-Secret) are stored in your browser's localStorage in plaintext. Do not use this application on shared or untrusted devices."`
- **Acceptance Criteria**:
  - Notice shown once per browser session (tracked via `sessionStorage`)
  - User must click "I Understand" to dismiss
  - Notice not shown again after dismissal within the session

---

## 4. Non-Functional Requirements

### 4.1 Security

#### NFR-EG-1.1: Credential Protection
- **Priority**: P0 (Critical)
- **Requirements**:
  - `X-Client-Secret` and bearer tokens **never** appear in any log (backend or browser console)
  - `X-Client-Secret` rendered as `type="password"` in all UI inputs
  - Token value excluded from all API response payloads
  - HTTPS required for both token endpoint and LLM gateway URLs (no HTTP allowed)
- **Acceptance Criteria**:
  - Grep of all log output shows no token or secret values
  - All credential fields use `type="password"` in HTML
  - All enterprise endpoint URLs validated against `^https://` pattern

#### NFR-EG-1.2: Token Isolation
- **Priority**: P0 (Critical)
- **Requirements**:
  - Token stored only in Python in-memory dict (not disk, not DB, not response body)
  - Token cleared on application restart
  - Token not accessible via any GET endpoint
- **Acceptance Criteria**:
  - `GET /api/enterprise/token/status` returns metadata only (no token value)
  - No endpoint returns `access_token` field

#### NFR-EG-1.3: Redacted Request Logging
- **Priority**: P1 (High)
- **Description**: The backend shall log a human-readable, curl-equivalent representation of every outbound enterprise HTTP request (both token acquisition and LLM gateway calls) to aid debugging, while ensuring all sensitive values are redacted.
- **Requirements**:
  - Every token acquisition request logged as a curl command with `X-Client-Id` and `X-Client-Secret` values replaced by `[REDACTED]`
  - Every LLM gateway request logged as a curl command with the bearer token value replaced by `[REDACTED]`
  - Log level: `DEBUG` via `logger_external` (suppressed in production by default; enabled by setting log level to DEBUG)
  - The literal header **names** (`X-Client-Id`, `X-Client-Secret`, `Authorization`) are always printed — only the **values** are redacted
  - Message `content` fields in LLM request logs are truncated to 200 characters to avoid flooding logs
  - Tool definitions in LLM request logs are summarised as `"tools": [<N tools>]` rather than the full schema
- **Log Format — Token Request**:
  ```
  [enterprise] → token request (redacted):
  curl --location --request POST '<TOKEN_ENDPOINT_URL>' \
    --header 'Content-Type: application/json' \
    --header 'X-Client-Id: [REDACTED]' \
    --header 'X-Client-Secret: [REDACTED]' \
    --data ''
  ```
- **Log Format — LLM Gateway Request**:
  ```
  [enterprise] → LLM request (redacted):
  curl '<GATEWAY_URL>/chat/completions' -X POST \
    -H 'Content-Type: application/json' \
    -H 'Authorization: Bearer [REDACTED]' \
      -d '{ "model": "<UI-selected-model-id>", "messages": [{"role": "<role>", "content": "<first 200 chars>..."}], "tools": [<N tools>], "max_tokens": <N>, "stream": false }'
  ```
- **Acceptance Criteria**:
  - Grep of log output for `[REDACTED]` confirms all curl log lines are present
  - Grep of log output for any known secret value returns zero matches
  - Curl-equivalent log lines appear **before** the request is sent (pre-flight log)
  - Log lines are machine-grep-friendly: each curl block starts with `[enterprise] →` prefix
  - Disabling DEBUG level suppresses curl logs without affecting INFO-level directional arrow logs

### 4.2 Performance

#### NFR-EG-2.1: Token Acquisition Latency
- **Priority**: P1 (High)
- **Requirements**:
  - Token fetch completes within 10 seconds
  - LLM Gateway requests use `read` timeout of 60 seconds (enterprise network latency)
- **Acceptance Criteria**:
  - `httpx.Timeout(connect=5.0, read=60.0, write=5.0, pool=5.0)` for enterprise calls
  - Token fetch timeout: `httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)`

### 4.3 Backward Compatibility

#### NFR-EG-3.1: Standard Mode Unaffected
- **Priority**: P0 (Critical)
- **Requirements**:
  - Existing OpenAI and Ollama integrations continue to work when `gateway_mode == "standard"`
  - No breaking changes to existing API endpoints
  - Default `gateway_mode` is `standard`
- **Acceptance Criteria**:
  - All existing acceptance tests pass without modification
  - Existing `localStorage` keys (`llmConfig`, `serverList`) unmodified

---

## 5. Technical Requirements

### 5.1 New Backend Components

#### TR-EG-1.1: New Pydantic Models
```python
class EnterpriseTokenRequest(BaseModel):
    token_endpoint_url: str = Field(..., pattern=r"^https://", description="OAuth token endpoint URL")
    client_id: str = Field(..., min_length=1, description="X-Client-Id header value")
    client_secret: str = Field(..., min_length=1, description="X-Client-Secret header value")

class EnterpriseTokenStatus(BaseModel):
    token_cached: bool
    cached_at: Optional[str] = None   # ISO 8601 datetime string
    expires_in: Optional[int] = None  # seconds

class EnterpriseModelEntry(BaseModel):
    model_id: str = Field(..., description="Model identifier string")
    provider: str = Field(..., description="Backend provider (AWS, Azure, Other)")
    type: Literal["LLM", "Embedding"] = "LLM"
    is_default: bool = False
```

#### TR-EG-1.2: New API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/enterprise/token` | Acquire and cache bearer token |
| `GET` | `/api/enterprise/token/status` | Check token cache status |
| `DELETE` | `/api/enterprise/token` | Clear cached token |
| `GET` | `/api/enterprise/models` | List all models (defaults + custom) |

#### TR-EG-1.3: New Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENTERPRISE_LLM_GATEWAY_URL` | _(none)_ | Default LLM Gateway base URL |
| `ENTERPRISE_TOKEN_ENDPOINT_URL` | _(none)_ | Default OAuth token endpoint |
| `ENTERPRISE_CLIENT_ID` | _(none)_ | Default X-Client-Id (dev override) |
| `ENTERPRISE_CLIENT_SECRET` | _(none)_ | Default X-Client-Secret (dev override) |
| `ENTERPRISE_DEFAULT_MODEL` | `gpt-4o` | Default model selection |

### 5.2 Frontend Changes

#### TR-EG-2.1: New `localStorage` Keys

| Key | Value Type | Description |
|-----|-----------|-------------|
| `llmGatewayMode` | `"standard"` \| `"enterprise"` | Active gateway mode |
| `enterpriseGatewayUrl` | string | LLM Gateway base URL |
| `enterpriseTokenEndpoint` | string | OAuth token endpoint URL |
| `enterpriseClientId` | string | X-Client-Id |
| `enterpriseClientSecret` | string | X-Client-Secret (plaintext — see security notice) |
| `enterpriseSelectedModel` | string | Currently selected model ID |
| `enterpriseCustomModels` | JSON array | User-added model entries |
| `enterpriseAuthMethod` | `"bearer"` | Authentication method |

#### TR-EG-2.2: Modified Files

| File | Change Type | Description |
|------|-------------|-------------|
| `backend/models.py` | Extend | Add `EnterpriseTokenRequest`, `EnterpriseTokenStatus`, `EnterpriseModelEntry`; extend `LLMConfig` |
| `backend/llm_client.py` | New class | Add `EnterpriseLLMClient`; update factory function |
| `backend/main.py` | New endpoints | Add `/api/enterprise/*` routes; add in-memory token cache |
| `backend/static/settings.js` | Extend | Add gateway mode toggle, enterprise config panel, model dropdown |
| `backend/static/app.js` | Minor update | Pass `gateway_mode` in session creation payload |
| `backend/static/index.html` | Minor update | Any new HTML structure for enterprise panel if not fully dynamic |
| `backend/static/style.css` | Extend | Styles for enterprise panel, token status badge, security notice |

---

## 6. User Workflows

### UW-EG-1: First-Time Enterprise Gateway Setup
1. Open Settings modal → navigate to **LLM Config** tab
2. Switch **Gateway Mode** to `Enterprise Gateway`
3. Enterprise panel appears; standard provider fields hidden
4. Select a model from the **Model** dropdown (default: `gpt-4o`)
5. Enter **LLM Gateway URL** (e.g. `https://llm-gw.internal.net/modelgw/models/openai/v1`)
6. Under **Authentication**, confirm method is `Bearer Token (OAuth)`
7. Enter **X-Client-Id**, **X-Client-Secret**, and **Token Endpoint URL**
8. Click **"Save Enterprise Config"** — inline validation fires; security notice displayed on first save
9. Click **"Fetch Token"** — spinner shows; on success, `Token Active ✓` badge appears
10. Close settings modal
11. Type a message in the chat input and send
12. Backend uses cached bearer token to call the Comcast Model Gateway
13. Response displayed in chat as with standard providers

### UW-EG-2: Adding a Custom Model
1. Open Settings → LLM Config (Enterprise mode active)
2. Click **"Add Model"** below the model dropdown
3. Fill in: `Model ID` = `gemini-2-pro`, `Provider` = `Google`, `Type` = `LLM`
4. Click **Save** — custom model appears at bottom of dropdown with custom badge
5. Select the custom model from dropdown
6. Save Enterprise Config to persist selection

### UW-EG-3: Switching Back to Non-Enterprise
1. Open Settings → LLM Config
2. Switch **Gateway Mode** to `Non-Enterprise Gateway`
3. Standard provider fields (OpenAI / Ollama) are restored
4. Enterprise panel hidden (configuration values retained in `localStorage`)
5. Save LLM Configuration
6. Chat resumes using standard provider

### UW-EG-4: Re-fetching a Token
1. Open Settings → LLM Config (Enterprise mode)
2. `Token Active ✓` badge shows last token time
3. Click **"Fetch Token"** again to force re-acquisition
4. Old cached token overwritten with new one

---

## 7. API Contract Reference

### 7.1 Token Acquisition
```
POST /api/enterprise/token
Content-Type: application/json

{
  "token_endpoint_url": "https://test.tv.test.net/v2/oauth/token",
  "client_id": "my-client-id",
  "client_secret": "my-client-secret"
}

→ 200 OK
{
  "token_acquired": true,
  "expires_in": 3600,
  "cached_at": "2026-03-10T12:00:00Z"
}

→ 502 Bad Gateway
{
  "token_acquired": false,
  "error": "Token endpoint returned 401: Unauthorized"
}
```

### 7.2 Token Status
```
GET /api/enterprise/token/status

→ 200 OK (token present)
{
  "token_cached": true,
  "cached_at": "2026-03-10T12:00:00Z",
  "expires_in": 3600
}

→ 200 OK (no token)
{
  "token_cached": false,
  "cached_at": null,
  "expires_in": null
}
```

### 7.3 Internal LLM Gateway Call (Backend → Comcast Gateway)

> **Note**: The `model` field is always set to the model the user has selected in the Enterprise Gateway UI dropdown (persisted as `enterpriseSelectedModel` in localStorage and passed in `LLMConfig.model`). The example below uses `gpt-4o` for illustration only.

```
POST {ENTERPRISE_LLM_GATEWAY_URL}/chat/completions
Authorization: Bearer <cached_token>
Content-Type: application/json

{
  "model": "<enterpriseSelectedModel>",   // e.g. "gpt-4o", "claude-4-6-sonnet", "nova-pro"
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the weather?"}
  ],
  "tools": [ ... ],
  "max_tokens": 4096,
  "stream": false
}
```

---

## 8. Acceptance Testing

### 8.1 Enterprise Gateway Tests

| Test ID | Description | Expected Result |
|---------|-------------|-----------------|
| AT-EG-01 | Switch to Enterprise mode | Enterprise panel shown; standard fields hidden |
| AT-EG-02 | Switch back to Standard mode | Standard fields restored; enterprise panel hidden |
| AT-EG-03 | Default model list | All 16 default models appear in dropdown |
| AT-EG-04 | Add custom model | Custom model appears in dropdown with badge |
| AT-EG-05 | Duplicate model ID rejected | Inline error: "Model ID already exists" |
| AT-EG-06 | Save without Gateway URL | Inline error: "LLM Gateway URL is required" |
| AT-EG-07 | Fetch token — success | `Token Active ✓` badge; `POST /api/enterprise/token` returns 200 |
| AT-EG-08 | Fetch token — bad credentials | `Fetch Failed ✗` with error message; HTTP 502 from backend |
| AT-EG-09 | Chat with valid token | LLM response received using enterprise model |
| AT-EG-10 | Chat without token | Error: "No enterprise token cached. Please fetch a token first." |
| AT-EG-11 | Token never in logs | Grep backend logs — no `access_token` or `Bearer sk-` pattern |
| AT-EG-12 | Secret never in logs | Grep backend logs — no `X-Client-Secret` value |
| AT-EG-13 | Settings persist on reload | Enterprise config restored from `localStorage` after page reload |
| AT-EG-14 | Standard mode unaffected | OpenAI/Ollama tests from v0.2.0 pass without change |
| AT-EG-15 | Security notice shown once | Notice appears on first enterprise credential save; not again in same session |
| AT-EG-16 | HTTPS enforcement | HTTP URL for gateway or token endpoint rejected with validation error |
| AT-EG-17 | Redacted token curl log | DEBUG log contains curl block with `[REDACTED]` for both `X-Client-Id` and `X-Client-Secret` values; actual credential values absent |
| AT-EG-18 | Redacted LLM curl log | DEBUG log contains curl block with `Authorization: Bearer [REDACTED]`; actual token value absent; message content truncated at 200 chars |

---

## 9. Constraints and Assumptions

### 9.1 Constraints
- Token expiry management (auto-refresh) is **out of scope** for v0.3.0 — users must manually re-fetch
- Enterprise model list defaults are hardcoded; runtime model discovery from gateway is **out of scope**
- Only `bearer` OAuth flow supported; client credentials flow (`grant_type`) not required by gateway
- `stream: false` only — streaming from enterprise gateway is **out of scope**
- Single cached token — no per-user or per-session token isolation

### 9.2 Assumptions
- The Comcast Model Gateway exposes an OpenAI-compatible `/chat/completions` endpoint
- The OAuth token endpoint accepts `X-Client-Id` and `X-Client-Secret` as **headers** (not body)
- Token endpoint returns a JSON body containing an `access_token` field (standard OAuth 2.0 response)
- Enterprise gateway is accessible from the machine running the FastAPI backend (not the browser)
- HTTPS is enforced for all enterprise endpoints (no HTTP exceptions)
- Token TTL provided in `expires_in` field of OAuth response

---

## 10. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| OQ-1 | What is the exact JSON field name for the bearer token in the OAuth response? (e.g. `access_token`) | Backend / Auth team | Open |
| OQ-2 | Does the token endpoint require an empty JSON body `{}` or truly empty body `''`? | Auth team | Open |
| OQ-3 | What is the token TTL? Is `expires_in` included in the token response? | Auth team | Open |
| OQ-4 | Are Embedding models (`text-embedding-3-large`) callable via the same `/chat/completions` route? | Gateway team | Open |
| OQ-5 | Is the model gateway path exactly `/modelgw/models/openai/v1/chat/completions` for all models? | Gateway team | Open |
| OQ-6 | Should `max_tokens` default to 4096 or be user-configurable for enterprise models? | Product | Open |

---

## 11. Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-03-10 | AI Assistant | Initial draft — enterprise gateway requirements |

**Review Checklist**

- [ ] Security review: credential handling and token isolation
- [ ] UI/UX review: enterprise panel layout and workflow
- [ ] Backend review: token caching and LLM client adapter
- [ ] QA review: acceptance test coverage
- [ ] Open questions resolved before implementation start
