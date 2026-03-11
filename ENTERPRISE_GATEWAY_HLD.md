# High-Level Design Document
## Enterprise LLM Gateway Integration (Comcast-LLM)

**Project**: MCP Client Web  
**Feature**: Enterprise LLM Gateway Support  
**Version**: 0.3.0-enterprise-gateway  
**Date**: March 10, 2026  
**Status**: Design Phase  
**Parent HLD**: HLD.md (v0.2.0-jsonrpc)  
**Requirements**: ENTERPRISE_GATEWAY_REQUIREMENTS.md (v0.3.0)

---

## 1. Executive Summary

This document describes the high-level design for adding **Enterprise LLM Gateway** support to the MCP Client Web application. The design introduces a dual-mode LLM routing architecture: the existing **Standard mode** (OpenAI / Ollama) remains fully intact, while a new **Enterprise mode** routes all LLM inference through the Comcast Model Gateway using OAuth 2.0 bearer token authentication.

The key design principles are:
- **Additive, non-breaking**: Enterprise mode is a new code path; standard provider adapters are untouched
- **Secure by design**: Bearer tokens and credentials never leave the backend memory or appear in logs
- **OpenAI-compatible gateway**: Enterprise gateway speaks the same `/chat/completions` protocol, minimising adapter complexity
- **UI-driven model selection**: Model identity flows from UI → localStorage → LLMConfig → backend request; never hardcoded

---

## 2. Architecture Overview

### 2.1 Updated System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              User's Browser                             │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Frontend (Vanilla JavaScript)                  │  │
│  │  ┌─────────────┐  ┌──────────────────────────┐  ┌─────────────┐ │  │
│  │  │   Chat UI   │  │     Settings Modal        │  │ localStorage│ │  │
│  │  │  (app.js)   │  │  [Gateway Mode Toggle]    │  │  - standard │ │  │
│  │  │             │  │  [Standard Panel]         │  │    config   │ │  │
│  │  │             │  │  [Enterprise Panel]  NEW  │  │  - enterprise│ │  │
│  │  └─────────────┘  └──────────────────────────┘  │    config   │ │  │
│  └──────────────────────────────────────────────────└─────────────┘─┘  │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ HTTP REST API
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          FastAPI Backend Server                         │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        API Endpoints (main.py)                  │   │
│  │  /api/sessions   /api/servers   /api/llm-config                │   │
│  │  /api/enterprise/token    ◄── NEW                              │   │
│  │  /api/enterprise/token/status  ◄── NEW                         │   │
│  │  /api/enterprise/models        ◄── NEW                         │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌───────────────────┐   ┌─────────────────────────────────────────┐   │
│  │   MCP Manager     │   │        LLM Client Factory               │   │
│  │  (JSON-RPC 2.0)   │   │  get_llm_client(config)                 │   │
│  │  (unchanged)      │   │  ┌──────────┬──────────┬─────────────┐ │   │
│  └───────────────────┘   │  │ OpenAI   │  Ollama  │  Enterprise │ │   │
│                           │  │ Client   │  Client  │  Client NEW │ │   │
│  ┌───────────────────┐   │  └──────────┴──────────┴─────────────┘ │   │
│  │  Enterprise Token │   └─────────────────────────────────────────┘   │
│  │  Cache  NEW       │                                                  │
│  │  (in-memory dict) │                                                  │
│  └───────────────────┘                                                  │
└──────────┬──────────────────────────┬──────────────────────────────────┘
           │                          │
           ▼ JSON-RPC 2.0             ▼ HTTPS REST
┌──────────────────────┐   ┌──────────────────────────────────────────┐
│   MCP Servers        │   │  LLM Providers                           │
│  (unchanged)         │   │  ┌──────────────┐  ┌───────────────────┐ │
│                      │   │  │  OpenAI /    │  │  Comcast Model    │ │
│                      │   │  │  Ollama      │  │  Gateway  NEW     │ │
│                      │   │  │  (standard)  │  │  /modelgw/...     │ │
│                      │   │  └──────────────┘  └───────────────────┘ │
│                      │   │                              ▲            │
└──────────────────────┘   │              ┌───────────────┘            │
                           │   ┌──────────────────────────────────┐   │
                           │   │  Enterprise OAuth Token Endpoint  │   │
                           │   │  POST /v2/oauth/token  NEW        │   │
                           │   └──────────────────────────────────┘   │
                           └──────────────────────────────────────────┘
```

### 2.2 Component Delta from v0.2.0

| Component | Change | Description |
|-----------|--------|-------------|
| `backend/main.py` | Extended | New `/api/enterprise/*` endpoints; in-memory token cache |
| `backend/models.py` | Extended | New Pydantic models; extended `LLMConfig` |
| `backend/llm_client.py` | Extended | New `EnterpriseLLMClient` class; updated factory |
| `backend/static/settings.js` | Extended | Gateway mode toggle; enterprise config panel |
| `backend/static/app.js` | Minor | Pass `gateway_mode` in session create payload |
| `backend/static/style.css` | Extended | Enterprise panel styles, token badge, security notice |
| `backend/static/index.html` | Minor | DOM hooks for enterprise panel (if not fully dynamic) |
| `backend/mcp_manager.py` | **Unchanged** | MCP communication unaffected |
| `backend/session_manager.py` | **Unchanged** | Session management unaffected |

---

## 3. Frontend Design

### 3.1 Updated LLM Config Tab Layout

```
┌──────────────────────────────────────────────────────────────┐
│  Settings                                               [×]  │
├──────────────────────────────────────────────────────────────┤
│  [MCP Servers]  [LLM Config]  [Tools]                        │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Gateway Mode                                                │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  ○ Non-Enterprise Gateway    ● Enterprise Gateway      │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ╔═══════════════════════════════════════════════════════╗   │
│  ║  ENTERPRISE GATEWAY PANEL  (shown when ● Enterprise)  ║   │
│  ║                                                       ║   │
│  ║  Provider:  [ Comcast-LLM ]  (read-only badge)        ║   │
│  ║                                                       ║   │
│  ║  Model:     [gpt-4o (Azure)               ▼]         ║   │
│  ║             [+ Add Model]                            ║   │
│  ║                                                       ║   │
│  ║  LLM Gateway URL:                                     ║   │
│  ║  [https://<LLM-GATEWAY>/modelgw/models/openai/v1  ]  ║   │
│  ║                                                       ║   │
│  ║  Authentication:  [Bearer Token (OAuth)  ▼]          ║   │
│  ║                                                       ║   │
│  ║  X-Client-Id:       [________________________]       ║   │
│  ║  X-Client-Secret:   [••••••••••••••••••••••••]  👁   ║   │
│  ║  Token Endpoint URL:[________________________]       ║   │
│  ║                                                       ║   │
│  ║  [      Save Enterprise Config      ]                 ║   │
│  ║                                                       ║   │
│  ║  Token Status: ● Token Active ✓  (since 12:00 PM)    ║   │
│  ║  [      Fetch Token      ]                            ║   │
│  ╚═══════════════════════════════════════════════════════╝   │
│                                                              │
│  ╔═══════════════════════════════════════════════════════╗   │
│  ║  STANDARD PANEL  (shown when ○ Non-Enterprise)        ║   │
│  ║  Provider: [OpenAI ▼]   Model: [gpt-4o]              ║   │
│  ║  Base URL: [https://api.openai.com]                   ║   │
│  ║  API Key:  [••••••••••••••••]                         ║   │
│  ║  [  Save LLM Configuration  ]  [Test Connection]     ║   │
│  ╚═══════════════════════════════════════════════════════╝   │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Model Dropdown Design

```
┌─────────────────────────────────────────────┐
│ Model                                       │
│ ┌─────────────────────────────────────────┐ │
│ │ gpt-4o (Azure)                        ▼ │ │
│ └─────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────┐  │
│  │ ── AWS Models ──────────────────────  │  │
│  │  claude-3-7-sonnet (AWS)              │  │
│  │  claude-4-5-haiku (AWS)               │  │
│  │  claude-4-5-sonnet (AWS)              │  │
│  │  claude-4-6-sonnet (AWS)              │  │
│  │  claude-4-sonnet (AWS)                │  │
│  │  nova-lite (AWS)                      │  │
│  │  nova-micro (AWS)                     │  │
│  │  nova-pro (AWS)                       │  │
│  │ ── Azure Models ────────────────────  │  │
│  │  gpt-41 (Azure)                       │  │
│  │▶ gpt-4o (Azure)          ← default   │  │
│  │  gpt-5-1 (Azure)                      │  │
│  │  gpt-5-2 (Azure)                      │  │
│  │  gpt-5-mini (Azure)                   │  │
│  │  gpt-5-nano (Azure)                   │  │
│  │  o4-mini (Azure)                      │  │
│  │ ── Embedding ───────────────────────  │  │
│  │  text-embedding-3-large (Azure) [emb] │  │
│  │ ── Custom ──────────────────────────  │  │
│  │  gemini-2-pro (Google) [custom]  [×]  │  │
│  └───────────────────────────────────────┘  │
│  [+ Add Model]                              │
└─────────────────────────────────────────────┘
```

### 3.3 Fetch Token Button State Machine

```
          ┌─────────────────────────────────┐
          │  IDLE (no token cached)         │
          │  [ Fetch Token ]  (primary btn) │
          └──────────────┬──────────────────┘
                         │ onClick
                         ▼
          ┌─────────────────────────────────┐
          │  LOADING                        │
          │  [ Fetching… ⟳ ]  (disabled)   │
          │  POST /api/enterprise/token     │
          └────────────┬────────────────────┘
               ┌───────┴────────┐
         200 OK│                │4xx / 5xx
               ▼                ▼
  ┌─────────────────────┐  ┌───────────────────────┐
  │  SUCCESS            │  │  ERROR                │
  │  [Token Active ✓]   │  │  [Fetch Failed ✗]     │
  │  (green, disabled)  │  │  (red, re-clickable)  │
  │  "since 12:00 PM"   │  │  Error msg below btn  │
  └─────────────────────┘  └───────────────────────┘
          │ onClick                  │ onClick
          └──────────┬───────────────┘
                     ▼
               Returns to LOADING
```

### 3.4 localStorage Schema Extension

```javascript
// Existing keys — UNCHANGED
{
  "mcpServers": [ ... ],
  "llmConfig": { "provider": "openai", "model": "gpt-4o", ... }
}

// New enterprise keys
{
  "llmGatewayMode": "enterprise",           // "standard" | "enterprise"
  "enterpriseGatewayUrl": "https://llm-gw.internal.net/modelgw/models/openai/v1",
  "enterpriseTokenEndpoint": "https://auth.internal.net/v2/oauth/token",
  "enterpriseClientId": "my-client-id",
  "enterpriseClientSecret": "my-secret",    // plaintext — security notice shown
  "enterpriseSelectedModel": "gpt-4o",      // model ID from dropdown
  "enterpriseAuthMethod": "bearer",
  "enterpriseCustomModels": [
    {
      "model_id": "gemini-2-pro",
      "provider": "Google",
      "type": "LLM",
      "is_default": false
    }
  ]
}
```

---

## 4. Backend Design

### 4.1 Updated LLMConfig Pydantic Model

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional

class LLMConfig(BaseModel):
    """LLM provider configuration — extended for enterprise gateway"""
    
    # ── Existing fields (unchanged) ──────────────────────────────────
    provider: Literal["openai", "ollama", "mock", "enterprise"] = Field(
        ..., description="LLM provider type"
    )
    model: str = Field(..., description="Model name — for enterprise: UI dropdown selection")
    base_url: Optional[str] = Field(None, description="Provider API base URL (standard mode)")
    api_key: Optional[str] = Field(None, description="API key (standard OpenAI mode)")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=4096, ge=1)

    # ── New enterprise fields ─────────────────────────────────────────
    gateway_mode: Literal["standard", "enterprise"] = Field(
        default="standard", description="Gateway routing mode"
    )
    enterprise_gateway_url: Optional[str] = Field(
        None, pattern=r"^https://",
        description="Comcast LLM Gateway base URL"
    )
    enterprise_token_endpoint: Optional[str] = Field(
        None, pattern=r"^https://",
        description="OAuth token endpoint URL"
    )
    enterprise_client_id: Optional[str] = Field(
        None, description="X-Client-Id credential"
    )
    enterprise_client_secret: Optional[str] = Field(
        None, description="X-Client-Secret credential (never logged)"
    )
    enterprise_auth_method: Literal["bearer"] = Field(
        default="bearer", description="Enterprise auth method"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "provider": "enterprise",
                "model": "gpt-4o",
                "gateway_mode": "enterprise",
                "enterprise_gateway_url": "https://llm-gw.internal.net/modelgw/models/openai/v1",
                "enterprise_token_endpoint": "https://auth.internal.net/v2/oauth/token",
                "enterprise_client_id": "my-client-id",
                "enterprise_client_secret": "***",
                "enterprise_auth_method": "bearer"
            }
        }
```

### 4.2 New Pydantic Models

```python
class EnterpriseTokenRequest(BaseModel):
    """Request body for token acquisition endpoint"""
    token_endpoint_url: str = Field(
        ..., pattern=r"^https://", description="OAuth token endpoint URL"
    )
    client_id: str = Field(..., min_length=1, description="X-Client-Id value")
    client_secret: str = Field(..., min_length=1, description="X-Client-Secret value")

    class Config:
        json_schema_extra = {
            "example": {
                "token_endpoint_url": "https://test.tv.test.net/v2/oauth/token",
                "client_id": "my-client-id",
                "client_secret": "***"
            }
        }


class EnterpriseTokenResponse(BaseModel):
    """Response from token acquisition — never includes raw token"""
    token_acquired: bool
    expires_in: Optional[int] = None     # seconds
    cached_at: Optional[str] = None      # ISO 8601
    error: Optional[str] = None          # populated on failure


class EnterpriseTokenStatus(BaseModel):
    """Token cache status — opaque, never exposes token value"""
    token_cached: bool
    cached_at: Optional[str] = None
    expires_in: Optional[int] = None


class EnterpriseModelEntry(BaseModel):
    """A single model entry in the enterprise model catalog"""
    model_id: str = Field(..., description="Model identifier")
    provider: str = Field(..., description="Backend provider (AWS, Azure, Other)")
    type: Literal["LLM", "Embedding"] = "LLM"
    is_default: bool = False
```

### 4.3 In-Memory Token Cache

```python
# main.py — module-level singleton cache
from datetime import datetime
from typing import Optional, Dict, Any

enterprise_token_cache: Dict[str, Any] = {
    "access_token": None,       # raw token — never exposed via API
    "cached_at": None,          # datetime
    "expires_in": None          # int seconds
}

def _cache_has_token() -> bool:
    return enterprise_token_cache.get("access_token") is not None

def _get_cached_token() -> Optional[str]:
    return enterprise_token_cache.get("access_token")

def _store_token(access_token: str, expires_in: int):
    enterprise_token_cache["access_token"] = access_token
    enterprise_token_cache["cached_at"] = datetime.utcnow()
    enterprise_token_cache["expires_in"] = expires_in

def _clear_token():
    enterprise_token_cache["access_token"] = None
    enterprise_token_cache["cached_at"] = None
    enterprise_token_cache["expires_in"] = None
```

### 4.4 New API Endpoints

```python
@app.post(
    "/api/enterprise/token",
    response_model=EnterpriseTokenResponse,
    tags=["Enterprise Gateway"],
    summary="Acquire OAuth bearer token",
    description="Fetches bearer token from enterprise OAuth endpoint and caches it in memory. "
                "Raw token is never returned in the response."
)
async def acquire_enterprise_token(
    request: EnterpriseTokenRequest
) -> EnterpriseTokenResponse:
    """Acquire and cache enterprise OAuth bearer token."""
    ...


@app.get(
    "/api/enterprise/token/status",
    response_model=EnterpriseTokenStatus,
    tags=["Enterprise Gateway"],
    summary="Check token cache status"
)
async def get_token_status() -> EnterpriseTokenStatus:
    """Return token cache metadata — never returns the raw token value."""
    ...


@app.delete(
    "/api/enterprise/token",
    tags=["Enterprise Gateway"],
    summary="Clear cached token"
)
async def clear_enterprise_token():
    """Invalidate the cached bearer token."""
    ...


@app.get(
    "/api/enterprise/models",
    response_model=List[EnterpriseModelEntry],
    tags=["Enterprise Gateway"],
    summary="List enterprise model catalog"
)
async def list_enterprise_models() -> List[EnterpriseModelEntry]:
    """Return merged list of default models + any user-added custom models."""
    ...
```

### 4.5 EnterpriseLLMClient Class Design

```python
class EnterpriseLLMClient(BaseLLMClient):
    """
    LLM adapter for Comcast Model Gateway.
    Uses cached OAuth bearer token for authentication.
    Gateway exposes OpenAI-compatible /chat/completions endpoint.
    """

    def __init__(self, config: LLMConfig, token_cache_fn: Callable[[], Optional[str]]):
        self.gateway_url = config.enterprise_gateway_url
        self.model = config.model           # always from UI selection — never hardcoded
        self.get_token = token_cache_fn     # injected: returns cached token or None
        self.timeout = httpx.Timeout(
            connect=5.0,
            read=60.0,     # longer for enterprise network latency
            write=5.0,
            pool=5.0
        )

    async def chat_completion(
        self,
        messages: List[dict],
        tools: List[dict]
    ) -> dict:
        token = self.get_token()
        if not token:
            raise EnterpriseTokenMissingError(
                "No enterprise token cached. Please fetch a token first."
            )

        payload = {
            "model": self.model,           # from UI dropdown selection
            "messages": messages,
            "tools": tools,
            "max_tokens": 4096,
            "stream": False
        }

        # Pre-flight redacted curl log (DEBUG level)
        self._log_redacted_curl(payload)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger_external.info(f"→ POST {self.gateway_url}/chat/completions")
            response = await client.post(
                f"{self.gateway_url}/chat/completions",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}"   # token injected; never logged
                }
            )
            logger_external.info(f"← {response.status_code}")

        return self._parse_response(response)

    def _log_redacted_curl(self, payload: dict):
        """Log a curl-equivalent of the request with token [REDACTED]."""
        import json
        redacted_messages = [
            {**m, "content": (m.get("content", "")[:200] + "...") 
             if len(m.get("content", "")) > 200 else m.get("content", "")}
            for m in payload["messages"]
        ]
        summary_payload = {
            "model": payload["model"],
            "messages": redacted_messages,
            "tools": f"[{len(payload.get('tools', []))} tools]",
            "max_tokens": payload["max_tokens"],
            "stream": False
        }
        logger_external.debug(
            f"[enterprise] → LLM request (redacted):\n"
            f"curl '{self.gateway_url}/chat/completions' -X POST \\\n"
            f"  -H 'Content-Type: application/json' \\\n"
            f"  -H 'Authorization: Bearer [REDACTED]' \\\n"
            f"  -d '{json.dumps(summary_payload)}'"
        )

    def _parse_response(self, response: httpx.Response) -> dict:
        """Parse OpenAI-compatible response — same logic as OpenAIClient."""
        if response.status_code == 401:
            raise EnterpriseAuthError(
                "Token expired or invalid. Re-acquire token."
            )
        if response.status_code == 429:
            raise EnterpriseLLMError("Rate limit exceeded.")
        if response.status_code >= 500:
            raise EnterpriseLLMError(
                f"Enterprise gateway error: {response.status_code}"
            )
        response.raise_for_status()
        return response.json()
```

### 4.6 LLM Client Factory Update

```python
def get_llm_client(config: LLMConfig) -> BaseLLMClient:
    """
    Factory: returns appropriate LLM client based on gateway_mode / provider.
    Standard providers are fully unaffected.
    """
    if config.gateway_mode == "enterprise" or config.provider == "enterprise":
        return EnterpriseLLMClient(
            config=config,
            token_cache_fn=_get_cached_token   # injected from main.py cache
        )
    elif config.provider == "openai":
        return OpenAIClient(config)
    elif config.provider == "ollama":
        return OllamaClient(config)
    elif config.provider == "mock":
        return MockLLMClient(config)
    else:
        raise ValueError(f"Unknown provider: {config.provider}")
```

### 4.7 Token Acquisition Flow (Backend)

```python
async def _acquire_token(request: EnterpriseTokenRequest) -> EnterpriseTokenResponse:
    """
    Issues POST to enterprise OAuth endpoint using X-Client-Id/Secret headers.
    Stores token in module-level cache. Never returns raw token.
    """
    # Pre-flight redacted curl log
    logger_external.debug(
        f"[enterprise] → token request (redacted):\n"
        f"curl --location --request POST '{request.token_endpoint_url}' \\\n"
        f"  --header 'Content-Type: application/json' \\\n"
        f"  --header 'X-Client-Id: [REDACTED]' \\\n"      # name logged, value redacted
        f"  --header 'X-Client-Secret: [REDACTED]' \\\n"  # name logged, value redacted
        f"  --data ''"
    )

    token_host = urlparse(request.token_endpoint_url).netloc
    logger_external.info(f"→ POST {token_host} (token endpoint)")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
    ) as client:
        response = await client.post(
            request.token_endpoint_url,
            headers={
                "Content-Type": "application/json",
                "X-Client-Id": request.client_id,       # sent in header
                "X-Client-Secret": request.client_secret # sent in header
            },
            content=""   # empty body per spec
        )

    logger_external.info(f"← {response.status_code} (token endpoint)")

    if response.status_code != 200:
        return EnterpriseTokenResponse(
            token_acquired=False,
            error=f"Token endpoint returned {response.status_code}"
        )

    data = response.json()
    access_token = data.get("access_token")  # standard OAuth field name (see OQ-1)
    expires_in = data.get("expires_in", 3600)

    _store_token(access_token, expires_in)

    return EnterpriseTokenResponse(
        token_acquired=True,
        expires_in=expires_in,
        cached_at=datetime.utcnow().isoformat() + "Z"
        # Note: access_token deliberately NOT included in response
    )
```

---

## 5. Data Flow

### 5.1 Enterprise Token Acquisition Flow

```
User                 Frontend             Backend              OAuth Endpoint
 │                      │                    │                       │
 │ Enter credentials     │                    │                       │
 │ Click "Fetch Token"   │                    │                       │
 ├──────────────────────►│                    │                       │
 │                       │ POST               │                       │
 │                       │ /api/enterprise/   │                       │
 │                       │ token              │                       │
 │                       │ {token_endpoint,   │                       │
 │                       │  client_id,        │                       │
 │                       │  client_secret}    │                       │
 │                       ├───────────────────►│                       │
 │                       │                    │ Log redacted curl     │
 │                       │                    │ (DEBUG)               │
 │                       │                    │ POST (with headers)   │
 │                       │                    ├──────────────────────►│
 │                       │                    │       200 OK          │
 │                       │                    │  {access_token, ...}  │
 │                       │                    │◄──────────────────────┤
 │                       │                    │                       │
 │                       │                    │ Store token in        │
 │                       │                    │ memory cache          │
 │                       │                    │ (token NOT in resp)   │
 │                       │  {token_acquired:  │                       │
 │                       │   true,            │                       │
 │                       │   cached_at,       │                       │
 │                       │   expires_in}      │                       │
 │                       │◄───────────────────┤                       │
 │ "Token Active ✓"      │                    │                       │
 │◄──────────────────────┤                    │                       │
```

### 5.2 Enterprise LLM Chat Flow

```
User     Frontend    Backend    MCP Server    EnterpriseLLMClient    Comcast Gateway
 │          │           │            │                │                     │
 │ Message  │           │            │                │                     │
 ├─────────►│           │            │                │                     │
 │          │ POST      │            │                │                     │
 │          │ /sessions │            │                │                     │
 │          │ /{id}/    │            │                │                     │
 │          │ messages  │            │                │                     │
 │          ├──────────►│            │                │                     │
 │          │           │ Get tools  │                │                     │
 │          │           ├───────────►│                │                     │
 │          │           │◄───────────┤                │                     │
 │          │           │            │                │                     │
 │          │           │ Check token cache           │                     │
 │          │           │ (in-memory)                 │                     │
 │          │           │            │                │                     │
 │          │           │ chat_completion(            │                     │
 │          │           │   messages, tools)          │                     │
 │          │           ├───────────────────────────►│                     │
 │          │           │            │                │ Log redacted curl    │
 │          │           │            │                │ (DEBUG)             │
 │          │           │            │                │ POST /chat/         │
 │          │           │            │                │ completions         │
 │          │           │            │                │ Authorization:      │
 │          │           │            │                │ Bearer <token>      │
 │          │           │            │                ├────────────────────►│
 │          │           │            │                │ {tool_calls} or     │
 │          │           │            │                │ {text response}     │
 │          │           │            │                │◄────────────────────┤
 │          │           │◄───────────────────────────┤                     │
 │          │           │            │                │                     │
 │          │           │ [if tool_calls]             │                     │
 │          │           │ Execute on MCP server       │                     │
 │          │           ├───────────►│                │                     │
 │          │           │◄───────────┤                │                     │
 │          │           │ Loop (max 8 tool calls)     │                     │
 │          │           │            │                │                     │
 │          │  Response │            │                │                     │
 │          │◄──────────┤            │                │                     │
 │ Display  │           │            │                │                     │
 │◄─────────┤           │            │                │                     │
```

### 5.3 Model Selection Flow (UI → Request)

```
1. User opens Settings → LLM Config → Enterprise mode
   │
2. User selects "claude-4-6-sonnet (AWS)" from dropdown
   │
3. Frontend: localStorage.setItem("enterpriseSelectedModel", "claude-4-6-sonnet")
   │
4. User clicks "Save Enterprise Config"
   │
5. Frontend: PUT /api/llm-config
   { "provider": "enterprise",
     "model": "claude-4-6-sonnet",    ← from dropdown
     "gateway_mode": "enterprise",
     ... }
   │
6. Backend: Updates session LLMConfig.model = "claude-4-6-sonnet"
   │
7. Next chat message:
   EnterpriseLLMClient sends:
   { "model": "claude-4-6-sonnet",   ← from LLMConfig.model
     "messages": [...],
     "stream": false }
   to Comcast Gateway
```

---

## 6. Security Design

### 6.1 Credential Isolation Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Credential Lifecycle                         │
│                                                                 │
│  User Input          Frontend              Backend              │
│  ─────────────────────────────────────────────────────────      │
│  X-Client-Id    →  localStorage        →  Request body only    │
│  X-Client-Secret→  localStorage        →  Header to OAuth EP   │
│  (masked field)    (plaintext ⚠️)         (never logged)        │
│                                                                 │
│  OAuth Response    NOT returned            In-memory cache      │
│  access_token   ←  to frontend  ←─────── only                  │
│                    (opaque)                (never on disk)      │
│                                                                 │
│  LLM Request       NOT visible             Injected from        │
│  Authorization  ←  to frontend  ←─────── cache                 │
│  Bearer <token>    (backend only)          never logged         │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Logging Redaction Design

Every outbound enterprise HTTP call produces two log entries:

**Entry 1 — Pre-flight DEBUG (redacted curl)**
```
[enterprise] → token request (redacted):
curl --location --request POST 'https://test.tv.test.net/v2/oauth/token' \
  --header 'Content-Type: application/json' \
  --header 'X-Client-Id: [REDACTED]' \
  --header 'X-Client-Secret: [REDACTED]' \
  --data ''

[enterprise] → LLM request (redacted):
curl 'https://llm-gw.net/modelgw/models/openai/v1/chat/completions' -X POST \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer [REDACTED]' \
  -d '{ "model": "gpt-4o", "messages": [{"role":"user","content":"What is the weat..."}],
       "tools": [3 tools], "max_tokens": 4096, "stream": false }'
```

**Entry 2 — INFO directional arrow**
```
→ POST test.tv.test.net (token endpoint)
← 200 (token endpoint)

→ POST llm-gw.net/modelgw/models/openai/v1/chat/completions
← 200
```

**Redaction Rules**:
| Field | Rule |
|-------|------|
| `X-Client-Id` value | Always `[REDACTED]` |
| `X-Client-Secret` value | Always `[REDACTED]` |
| `Authorization: Bearer <value>` | Value always `[REDACTED]` |
| `model` field | **Not redacted** (not sensitive) |
| Message `content` | Truncated to 200 chars |
| `tools` array | Summarised as `[N tools]` |

### 6.3 HTTPS Enforcement

```python
def _validate_enterprise_url(url: str, field_name: str):
    if not url.startswith("https://"):
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must use HTTPS. HTTP is not permitted for enterprise endpoints."
        )
```

Applied to:
- `enterprise_gateway_url` on `LLMConfig` save
- `token_endpoint_url` on `EnterpriseTokenRequest`

---

## 7. Updated API Endpoint Table

| Method | Path | Description | New? |
|--------|------|-------------|------|
| GET | `/` | Serve main HTML | — |
| POST | `/api/sessions` | Create session | — |
| POST | `/api/sessions/{id}/messages` | Send chat message | — |
| GET | `/api/servers` | List MCP servers | — |
| POST | `/api/servers` | Register server | — |
| PUT | `/api/servers/{id}` | Update server | — |
| DELETE | `/api/servers/{id}` | Delete server | — |
| POST | `/api/servers/refresh-tools` | Refresh tools | — |
| GET | `/api/tools` | List tools | — |
| POST | `/api/llm/config` | Save LLM config | Extended |
| GET | `/api/llm/config` | Get LLM config | Extended |
| **POST** | **`/api/enterprise/token`** | **Acquire bearer token** | **✓ New** |
| **GET** | **`/api/enterprise/token/status`** | **Token cache status** | **✓ New** |
| **DELETE** | **`/api/enterprise/token`** | **Clear cached token** | **✓ New** |
| **GET** | **`/api/enterprise/models`** | **List model catalog** | **✓ New** |

---

## 8. Deployment Architecture

### 8.1 Enterprise Multi-Machine Topology

```
┌─────────────────────────────────────────────┐
│  User's Browser (Machine A)                 │
│  - Settings: enterprise mode                │
│  - localStorage: credentials, model         │
│  - No direct network access to LLM/OAuth    │
└──────────────────┬──────────────────────────┘
                   │ HTTP to backend
                   ▼
┌─────────────────────────────────────────────┐
│  FastAPI Backend (Machine B)                │
│  - In-memory token cache                   │
│  - EnterpriseLLMClient                      │
│  Env vars:                                  │
│    ENTERPRISE_LLM_GATEWAY_URL=              │
│      https://llm-gw.corporate.net/...       │
│    ENTERPRISE_TOKEN_ENDPOINT_URL=           │
│      https://auth.corporate.net/v2/oauth    │
└────────────────┬──────────────┬─────────────┘
                 │              │
        JSON-RPC │              │ HTTPS REST
                 ▼              ▼
┌─────────────────────┐  ┌──────────────────────────────┐
│  MCP Servers        │  │  Corporate Network            │
│  (unchanged)        │  │  ┌──────────────────────────┐ │
│                     │  │  │  OAuth Token Endpoint    │ │
│                     │  │  │  POST /v2/oauth/token    │ │
│                     │  │  └────────────┬─────────────┘ │
│                     │  │               │               │
│                     │  │  ┌────────────▼─────────────┐ │
│                     │  │  │  Comcast Model Gateway   │ │
│                     │  │  │  POST /modelgw/.../       │ │
│                     │  │  │  chat/completions         │ │
│                     │  │  └──────────────────────────┘ │
└─────────────────────┘  └──────────────────────────────┘
```

### 8.2 New Environment Variables

```bash
# Enterprise gateway (all optional — can be set via UI instead)
ENTERPRISE_LLM_GATEWAY_URL=https://llm-gw.corporate.net/modelgw/models/openai/v1
ENTERPRISE_TOKEN_ENDPOINT_URL=https://auth.corporate.net/v2/oauth/token
ENTERPRISE_CLIENT_ID=my-client-id          # dev override only
ENTERPRISE_CLIENT_SECRET=my-secret         # dev override only — never commit
ENTERPRISE_DEFAULT_MODEL=gpt-4o
```

---

## 9. Non-Functional Design

### 9.1 Timeout Configuration

| Call Type | connect | read | write | pool |
|-----------|---------|------|-------|------|
| Token acquisition | 5.0s | 20.0s | 5.0s | 5.0s |
| Enterprise LLM request | 5.0s | **60.0s** | 5.0s | 5.0s |
| Standard LLM request (unchanged) | 5.0s | 20.0s | 5.0s | 5.0s |
| MCP tool execution (unchanged) | 5.0s | 20.0s | 5.0s | 5.0s |

### 9.2 Backward Compatibility

```
gateway_mode = "standard"  →  OpenAIClient / OllamaClient (unchanged code path)
gateway_mode = "enterprise" → EnterpriseLLMClient (new code path)

Default: gateway_mode = "standard"
```

No existing API endpoints, models, or frontend behaviours are changed when `gateway_mode == "standard"`.

---

## 10. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Token expiry during session | Chat fails mid-conversation | Show clear re-auth error; one-click re-fetch button |
| OAuth endpoint unavailable | Cannot acquire token | Descriptive error in UI; token fetch is manual |
| LLM gateway model not found | HTTP 404 from gateway | Surfaced as error; user prompted to check model selection |
| `access_token` field name differs from `access_token` | Token never cached | Covered in Open Question OQ-1; parse defensively |
| credentials in localStorage | Security risk on shared devices | One-time security notice; design doc acknowledges |
| HTTP URL mistakenly entered | Insecure transmission | HTTPS validation on all enterprise URL fields |
| Enterprise network latency | Slow responses | 60s read timeout; loading indicator in UI |

---

## 11. Open Questions (from Requirements)

| # | Question | Design Impact |
|---|----------|---------------|
| OQ-1 | OAuth response field name for token (`access_token`?) | Affects `_acquire_token` response parsing |
| OQ-2 | Token endpoint body: `{}` vs empty string | Affects `content=` in httpx request |
| OQ-3 | Token TTL / `expires_in` in response | Affects cache metadata; auto-refresh design |
| OQ-4 | Embedding models callable via `/chat/completions`? | Affects model type filtering in dropdown |
| OQ-5 | Exact gateway path for all models? | Affects `enterprise_gateway_url` validation |
| OQ-6 | `max_tokens` default (4096) or user-configurable? | Affects `LLMConfig` model field |

---

## 12. Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-10 | AI Assistant | Initial HLD for enterprise gateway feature |

**Parent Documents**

| Document | Version | Relationship |
|----------|---------|-------------|
| HLD.md | 0.2.0 | Base system HLD (unchanged standard mode) |
| ENTERPRISE_GATEWAY_REQUIREMENTS.md | 0.3.0 | Feature requirements this HLD implements |
| REQUIREMENTS.md | 0.2.0 | Full system requirements |

**Approval**

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Architect | _______________ | _______________ | _______ |
| Security Review | _______________ | _______________ | _______ |
| Tech Lead | _______________ | _______________ | _______ |
