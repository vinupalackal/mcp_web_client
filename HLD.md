# High-Level Design Document
## MCP Client Web Interface

**Project**: MCP Client Web  
**Version**: 0.2.0-jsonrpc  
**Date**: March 7, 2026  
**Status**: Design Phase  

---

## 1. Executive Summary

The MCP Client Web is a browser-based interface for interacting with Model Context Protocol (MCP) servers through a chat interface, similar to LibreChat. The system enables users to leverage AI tools via LLM providers (OpenAI/Ollama) with real-time tool execution capabilities using JSON-RPC 2.0 protocol.

### 1.1 Design Goals
- **Simplicity**: No build step, vanilla JavaScript SPA
- **Flexibility**: Support multiple MCP servers and LLM providers
- **Resilience**: Dual-storage pattern for offline capability
- **Distributed**: Multi-machine deployment support (MCP server, LLM, client on different hosts)

---

## 2. System Architecture

### 2.1 High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         User's Browser                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Frontend (Vanilla JavaScript)                │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │  │
│  │  │   Chat UI   │  │  Settings   │  │  localStorage   │  │  │
│  │  │  (app.js)   │  │(settings.js)│  │   (Configs)     │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP/WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend Server                       │
│  ┌────────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │  API Endpoints │  │  MCP Manager    │  │ LLM Client     │  │
│  │  (main.py)     │  │  (JSON-RPC 2.0) │  │ (Adapters)     │  │
│  └────────────────┘  └─────────────────┘  └────────────────┘  │
│  ┌────────────────┐  ┌─────────────────┐                       │
│  │Session Manager │  │  Pydantic Models│                       │
│  │ (In-memory)    │  │  (Validation)   │                       │
│  └────────────────┘  └─────────────────┘                       │
└───────────┬────────────────────┬─────────────────────────────────┘
            │                    │
            ▼                    ▼
┌──────────────────────┐  ┌──────────────────────┐
│   MCP Servers        │  │   LLM Providers      │
│  (Machine A, B...)   │  │  (OpenAI/Ollama)     │
│                      │  │  (Machine C)         │
│  ┌────────────────┐  │  │  ┌────────────────┐  │
│  │ Tool Registry  │  │  │  │ Chat Completion│  │
│  │ Tool Executor  │  │  │  │ Function Call  │  │
│  └────────────────┘  │  │  └────────────────┘  │
│  JSON-RPC 2.0 API    │  │  REST API            │
└──────────────────────┘  └──────────────────────┘
```

### 2.2 Component Overview

| Component | Technology | Responsibility |
|-----------|------------|----------------|
| Frontend UI | Vanilla JavaScript | Chat interface, settings modal, user interactions |
| Backend API | FastAPI (Python 3.8+) | Request routing, business logic, orchestration |
| MCP Manager | httpx + JSON-RPC | MCP server communication, tool discovery/execution |
| LLM Client | httpx | OpenAI/Ollama API integration, message formatting |
| Session Manager | In-memory dict | Session state, message history, trace events |
| Storage | localStorage + memory | Config persistence, session state |

---

## 3. Component Design

### 3.1 Frontend Architecture

#### 3.1.1 UI Layout (LibreChat-inspired)
```
┌─────────────────────────────────────────────────────────┐
│  Header                                [Settings] [New] │
├─────────────────────────────────────────────────────────┤
│                                                         │
│                   Chat Messages                         │
│  ┌────────────────────────────────────────────────┐    │
│  │ User: Can you check the weather in NYC?        │    │
│  └────────────────────────────────────────────────┘    │
│                                                         │
│  ┌────────────────────────────────────────────────┐    │
│  │ Assistant: Let me check that for you...        │    │
│  │ [Tool: weather_api__get_weather]               │    │
│  │ Result: 72°F, Partly Cloudy                    │    │
│  └────────────────────────────────────────────────┘    │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  [Type your message...]                    [Send ↑]   │
└─────────────────────────────────────────────────────────┘
```

#### 3.1.2 Settings Modal (Tabbed Interface)
```
┌─────────────────────────────────────────────┐
│  Settings                              [×]  │
├─────────────────────────────────────────────┤
│  [MCP Servers] [LLM Config] [Tools]         │
├─────────────────────────────────────────────┤
│                                             │
│  MCP Servers Tab:                           │
│  ┌───────────────────────────────────────┐ │
│  │ Server Alias: weather_api             │ │
│  │ Base URL: http://192.168.1.100:3000   │ │
│  │ Auth: [Bearer Token]                  │ │
│  │ Token: [••••••••••]                   │ │
│  │              [Add Server] [Refresh]   │ │
│  └───────────────────────────────────────┘ │
│                                             │
│  Configured Servers:                        │
│  • weather_api (3 tools) [Delete]           │
│  • database_api (5 tools) [Delete]          │
│                                             │
└─────────────────────────────────────────────┘
```

#### 3.1.3 Frontend Modules

**app.js** - Chat Interface Logic
- Message rendering with role-based styling
- Input handling (Enter to send)
- Auto-scroll to latest message
- Loading indicators during LLM/tool execution
- Tool call result visualization

**settings.js** - Settings Modal Management
- Tab switching (MCP Servers, LLM Config, Tools)
- Server CRUD operations via API
- LLM provider configuration
- Tool discovery trigger
- localStorage sync for configs

**localStorage Schema**
```javascript
{
  "mcpServers": [
    {
      "server_id": "uuid-1",
      "alias": "weather_api",
      "base_url": "http://192.168.1.100:3000",
      "auth_type": "bearer",
      "bearer_token": "token123",
      "timeout_ms": 20000
    }
  ],
  "llmConfig": {
    "provider": "ollama",
    "model": "llama3.1",
    "base_url": "http://192.168.1.50:11434",
    "api_key": null
  }
}
```

### 3.2 Backend Architecture

#### 3.2.1 OpenAPI-Driven API Design

**Development Approach**: Spec-first development using FastAPI + Pydantic
- All endpoints auto-documented via OpenAPI 3.0+
- Interactive documentation at `/docs` (Swagger UI)
- Schema validation enforced by Pydantic models

**API Endpoints**

| Method | Endpoint | Purpose | Response Model | Status Codes |
|--------|----------|---------|----------------|--------------|
| GET | `/` | Serve main HTML | HTML | 200 |
| GET | `/docs` | Swagger UI | HTML | 200 |
| GET | `/redoc` | ReDoc UI | HTML | 200 |
| GET | `/openapi.json` | OpenAPI spec | JSON | 200 |
| GET | `/static/*` | Serve static assets | File | 200, 404 |
| POST | `/api/sessions` | Create new session | SessionResponse | 201, 400, 500 |
| POST | `/api/sessions/{session_id}/messages` | Send chat message | ChatResponse | 200, 404, 422, 500 |
| GET | `/api/sessions/{session_id}/messages` | Get message history | MessageList | 200, 404 |
| GET | `/api/servers` | List MCP servers | List[ServerConfig] | 200 |
| POST | `/api/servers` | Register MCP server | ServerConfig | 201, 400, 422 |
| PUT | `/api/servers/{server_id}` | Update server config | ServerConfig | 200, 404, 422 |
| DELETE | `/api/servers/{server_id}` | Delete server | DeleteResponse | 204, 404 |
| POST | `/api/servers/refresh-tools` | Refresh tool discovery | ToolRefreshResponse | 200, 500 |
| GET | `/api/tools` | List all discovered tools | List[ToolSchema] | 200 |
| POST | `/api/llm/config` | Save LLM configuration | LLMConfig | 200, 422 |
| GET | `/api/llm/config` | Get LLM configuration | LLMConfig | 200, 404 |

#### 3.2.2 OpenAPI Schema Examples

**Accessing the Spec**:
- **Swagger UI**: http://localhost:8000/docs (interactive testing)
- **ReDoc**: http://localhost:8000/redoc (clean documentation)
- **Raw JSON**: http://localhost:8000/openapi.json (for tooling/CI)

**Key OpenAPI Features**:
- Request/response validation via Pydantic
- Automatic example generation
- Error response schemas (400, 404, 422, 500)
- Tag-based grouping (Chat, MCP Servers, LLM, Tools)

#### 3.2.3 Data Models (Pydantic)

**models.py** (OpenAPI-compliant with full documentation)
```python
from pydantic import BaseModel, Field
from typing import Literal, Optional, List

class ServerConfig(BaseModel):
    """MCP server configuration"""
    server_id: str = Field(..., description="Unique server identifier (UUID)")
    alias: str = Field(..., min_length=1, max_length=64, 
                       description="Human-readable server name")
    base_url: str = Field(..., description="MCP server base URL", 
                         pattern=r"^https?://")
    auth_type: Literal["none", "bearer", "api_key"] = Field(
        default="none", description="Authentication method"
    )
    bearer_token: Optional[str] = Field(None, description="Bearer token for auth")
    api_key: Optional[str] = Field(None, description="API key for auth")
    timeout_ms: int = Field(default=20000, ge=1000, le=60000,
                           description="Request timeout in milliseconds")
    health_status: Optional[str] = Field(None, description="Last health check status")
    
    class Config:
        json_schema_extra = {
            "example": {
                "server_id": "550e8400-e29b-41d4-a716-446655440000",
                "alias": "weather_api",
                "base_url": "http://192.168.1.100:3000",
                "auth_type": "bearer",
                "bearer_token": "secret-token-123",
                "timeout_ms": 20000
            }
        }

class LLMConfig(BaseModel):
    """LLM provider configuration"""
    provider: Literal["openai", "ollama", "mock"] = Field(
        ..., description="LLM provider type"
    )
    model: str = Field(..., description="Model name/identifier")
    base_url: str = Field(..., description="Provider API base URL")
    api_key: Optional[str] = Field(None, description="API key (if required)")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0,
                               description="Sampling temperature")
    max_tokens: Optional[int] = Field(None, ge=1, description="Max response tokens")
    
    class Config:
        json_schema_extra = {
            "example": {
                "provider": "ollama",
                "model": "llama3.1",
                "base_url": "http://192.168.1.50:11434",
                "temperature": 0.7
            }
        }

class ChatMessage(BaseModel):
    """Chat message in conversation"""
    role: Literal["user", "assistant", "tool", "system"] = Field(
        ..., description="Message role"
    )
    content: str = Field(..., min_length=1, description="Message content")
    tool_call_id: Optional[str] = Field(None, description="Tool call ID (OpenAI)")
    tool_calls: Optional[List['ToolCall']] = Field(None, description="Tool calls requested")
    
    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "What's the weather in NYC?"
            }
        }

class ToolCall(BaseModel):
    """Tool execution request"""
    id: str = Field(..., description="Unique call ID")
    type: str = Field(default="function", description="Call type")
    function: 'FunctionCall' = Field(..., description="Function details")

class FunctionCall(BaseModel):
    """Function call details"""
    name: str = Field(..., description="Namespaced tool name (server__tool)")
    arguments: str = Field(..., description="JSON-encoded arguments")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "weather_api__get_weather",
                "arguments": "{\"city\": \"NYC\"}"
            }
        }

class ErrorResponse(BaseModel):
    """Standard error response"""
    detail: str = Field(..., description="Error message")
    error_code: Optional[str] = Field(None, description="Machine-readable error code")
    
    class Config:
        json_schema_extra = {
            "example": {
                "detail": "MCP server unreachable",
                "error_code": "MCP_CONNECTION_FAILED"
            }
        }
```

#### 3.2.4 Endpoint Implementation Example

**spec-driven implementation pattern**:
```python
from fastapi import FastAPI, Path, Body, HTTPException, status
from typing import List

app = FastAPI(
    title="MCP Client Web API",
    version="0.2.0",
    description="LibreChat-inspired MCP client with JSON-RPC 2.0 support"
)

@app.post(
    "/api/servers",
    response_model=ServerConfig,
    status_code=status.HTTP_201_CREATED,
    tags=["MCP Servers"],
    summary="Register new MCP server",
    description="Add a new MCP server configuration for tool discovery",
    responses={
        201: {"description": "Server created successfully"},
        400: {"model": ErrorResponse, "description": "Invalid configuration"},
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
    \"\"\"
    Register a new MCP server for tool discovery and execution.
    
    The server will be initialized via JSON-RPC handshake and tools
    will be discovered automatically.
    \"\"\"
    # Implementation follows OpenAPI contract
    pass
```

#### 3.2.5 MCP Manager

**mcp_manager.py**
- **Initialization**: JSON-RPC handshake with protocol version
- **Tool Discovery**: Call `tools/list` method, parse schemas
- **Tool Execution**: Call `tools/call` with arguments
- **Timeout Handling**: Granular timeouts (connect, read, write, pool)
- **Error Handling**: JSON-RPC error responses with codes

```python
class MCPManager:
    async def initialize_server(self, server_config: ServerConfig) -> dict:
        """JSON-RPC initialize handshake"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "mcp-client-web", "version": "1.0"}
            }
        }
        # POST to server_config.base_url/rpc
        
    async def discover_tools(self, server_config: ServerConfig) -> List[Tool]:
        """Call tools/list and parse schemas"""
        
    async def execute_tool(self, server_alias: str, tool_name: str, 
                          arguments: dict) -> dict:
        """Call tools/call on specific server"""
```

#### 3.2.4 LLM Client

**llm_client.py**
```python
class BaseLLMClient(ABC):
    async def chat_completion(self, messages: List[dict], 
                             tools: List[dict]) -> dict:
        pass

class OpenAIClient(BaseLLMClient):
    # Uses tool_call_id in responses
    
class OllamaClient(BaseLLMClient):
    # Uses tool_name instead of tool_call_id
    
class MockLLMClient(BaseLLMClient):
    # For testing
```

**Message Formatting Differences**:
```python
# OpenAI tool result format
{"role": "tool", "tool_call_id": "call_abc123", "content": "result"}

# Ollama tool result format  
{"role": "tool", "content": "result"}  # No tool_call_id
```

#### 3.2.5 Session Manager

**session_manager.py**
```python
class SessionManager:
    sessions: Dict[str, Session] = {}
    
    def create_session(self, llm_config: LLMConfig, 
                      mcp_servers: List[str]) -> str:
        """Create new session with config"""
        
    def add_message(self, session_id: str, message: ChatMessage):
        """Append to message history"""
        
    def add_trace_event(self, session_id: str, event: dict):
        """Log tool execution trace"""
```

**Session Object**:
```python
{
    "session_id": "uuid",
    "created_at": "timestamp",
    "llm_config": {...},
    "enabled_servers": ["weather_api", "database_api"],
    "messages": [...],
    "trace_events": [
        {
            "timestamp": "...",
            "type": "tool_call",
            "tool": "weather_api__get_weather",
            "duration_ms": 1234,
            "status": "success"
        }
    ]
}
```

---

## 4. Data Flow

### 4.1 User Message Flow

```
1. User types message and clicks Send
   ↓
2. Frontend: POST /api/sessions/{id}/messages
   {
     "role": "user",
     "content": "What's the weather in NYC?"
   }
   ↓
3. Backend: Retrieve session, get available tools
   ↓
4. Backend: Call LLM with message + tool definitions
   ↓
5. LLM responds with tool_calls:
   {
     "tool_calls": [
       {
         "id": "call_1",
         "function": {
           "name": "weather_api__get_weather",
           "arguments": "{\"city\": \"NYC\"}"
         }
       }
     ]
   }
   ↓
6. Backend: Parse tool calls, execute on MCP server
   - POST to weather_api server: /rpc
   - JSON-RPC: tools/call method
   ↓
7. MCP Server returns result
   ↓
8. Backend: Format result for LLM provider
   - OpenAI: Include tool_call_id
   - Ollama: Omit tool_call_id
   ↓
9. Backend: Send result back to LLM for final response
   ↓
10. LLM generates final text response
    ↓
11. Backend: Return to frontend
    ↓
12. Frontend: Render in chat UI
```

### 4.2 Tool Discovery Flow

```
1. User clicks "Refresh Tools" in settings
   ↓
2. Frontend: POST /api/servers/refresh-tools
   ↓
3. Backend: For each configured server:
   - Initialize connection (if not done)
   - POST /rpc: {"method": "tools/list"}
   - Parse tool schemas
   - Create namespaced tool IDs
   ↓
4. Backend: Store tools in memory
   ↓
5. Frontend: GET /api/tools to display
   ↓
6. Frontend: Render in "Tools" tab
```

### 4.3 Configuration Sync Flow

```
┌──────────────┐        ┌──────────────┐        ┌──────────────┐
│  localStorage│◄──────►│   Frontend   │◄──────►│   Backend    │
│  (Browser)   │  sync  │   (UI State) │   API  │  (Sessions)  │
└──────────────┘        └──────────────┘        └──────────────┘
     │                                                   │
     │ Survives page reload                             │ Lost on reload
     │ - Server configs                                 │ - Message history
     │ - LLM settings                                   │ - Tool traces
     │ - UI preferences                                 │ - Session state
     └─────────────────────────────────────────────────┘
```

---

## 5. Sequence Diagrams

### 5.1 Tool Execution Sequence

```
User     Frontend    Backend    MCP Server    LLM Provider
 │          │           │            │              │
 │ Message  │           │            │              │
 ├─────────►│           │            │              │
 │          │  POST     │            │              │
 │          ├──────────►│            │              │
 │          │           │ Chat +Tools│              │
 │          │           ├───────────────────────────►│
 │          │           │            │  Tool Calls  │
 │          │           │◄───────────────────────────┤
 │          │           │            │              │
 │          │           │ JSON-RPC   │              │
 │          │           ├───────────►│              │
 │          │           │   Result   │              │
 │          │           │◄───────────┤              │
 │          │           │            │              │
 │          │           │ Result+Msg │              │
 │          │           ├───────────────────────────►│
 │          │           │            │   Response   │
 │          │           │◄───────────────────────────┤
 │          │  Response │            │              │
 │          │◄──────────┤            │              │
 │ Display  │           │            │              │
 │◄─────────┤           │            │              │
```

### 5.2 Multi-Server Tool Discovery

```
Backend        MCP Server 1      MCP Server 2
   │                 │                 │
   │  Initialize     │                 │
   ├────────────────►│                 │
   │  Success        │                 │
   │◄────────────────┤                 │
   │                 │                 │
   │  tools/list     │                 │
   ├────────────────►│                 │
   │  [tool1, tool2] │                 │
   │◄────────────────┤                 │
   │                 │                 │
   │  Namespace: server1__tool1        │
   │             server1__tool2        │
   │                 │                 │
   │  Initialize     │                 │
   ├─────────────────────────────────► │
   │                 │      Success    │
   │◄────────────────────────────────── │
   │                 │                 │
   │  tools/list     │                 │
   ├─────────────────────────────────► │
   │                 │  [tool3, tool4] │
   │◄────────────────────────────────── │
   │                 │                 │
   │  Namespace: server2__tool3        │
   │             server2__tool4        │
   │                 │                 │
   │  Combined Tool Registry:          │
   │  - server1__tool1                 │
   │  - server1__tool2                 │
   │  - server2__tool3                 │
   │  - server2__tool4                 │
```

---

## 6. Non-Functional Design

### 6.1 Performance Design

**Timeout Configuration**:
```python
timeout = httpx.Timeout(
    connect=5.0,    # TCP connection establishment
    read=20.0,      # Reading response data
    write=5.0,      # Writing request data
    pool=5.0        # Acquiring connection from pool
)
```

**Result Truncation**:
- Tool result preview: 4,000 chars
- Tool output to LLM: 12,000 chars
- Prevents LLM context overflow

**Tool Call Limits**:
- Max 8 tool calls per conversation turn
- Prevents infinite loops
- Configurable via `MCP_MAX_TOOL_CALLS_PER_TURN`

### 6.2 Security Design

**HTTPS Enforcement**:
```python
if not server_url.startswith("https://"):
    if not os.getenv("MCP_ALLOW_HTTP_INSECURE"):
        raise SecurityError("HTTP not allowed in production")
```

**Credential Handling**:
- Never log API keys/tokens
- Use password input fields in UI
- localStorage encryption (future enhancement)

**Network Security**:
- Validate server URLs (prevent SSRF)
- Firewall rules between machines
- Token-based auth for MCP servers

### 6.3 Logging Design

**Dual-Logger Architecture**:
```python
logger_internal = logging.getLogger("mcp_client.internal")
logger_external = logging.getLogger("mcp_client.external")

# External API call
logger_external.info("→ POST /api/servers")
logger_external.info("← 201 Created")

# Internal state change
logger_internal.info("Session abc123 created")
logger_internal.debug("Tool discovery started for weather_api")
```

**Frontend Logging**:
```javascript
console.log("⚙️ Settings: Saving server config")
console.log("🔧 Tools: Discovered 5 tools from weather_api")
console.log("💬 Chat: User message sent")
console.log("🔌 API: POST /api/sessions/123/messages")
```

### 6.4 Error Handling

**JSON-RPC Error Codes**:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32601,
    "message": "Method not found",
    "data": "tools/unknown_method"
  }
}
```

**HTTP Error Responses**:
```json
{
  "detail": "MCP server unreachable",
  "error_code": "MCP_CONNECTION_FAILED",
  "server_alias": "weather_api"
}
```

---

## 7. Deployment Architecture

### 7.1 Multi-Machine Deployment

```
┌─────────────────────┐
│  Machine A          │
│  MCP Server 1       │
│  Port: 3000         │
│  IP: 192.168.1.100  │
└─────────────────────┘
          ▲
          │ JSON-RPC 2.0
          │
┌─────────────────────┐
│  Machine B          │
│  MCP Server 2       │
│  Port: 3001         │
│  IP: 192.168.1.101  │
└─────────────────────┘
          ▲
          │
          │
┌─────────────────────────────────┐
│  Machine C (Backend Server)     │
│  FastAPI Application            │
│  Port: 8000                     │
│  IP: 192.168.1.50               │
│                                 │
│  Env vars:                      │
│  OLLAMA_BASE_URL=               │
│    http://192.168.1.60:11434    │
└─────────────────────────────────┘
          ▲
          │ HTTP API
          │
┌─────────────────────┐
│  Machine D          │
│  Ollama/OpenAI      │
│  Port: 11434/443    │
│  IP: 192.168.1.60   │
└─────────────────────┘
```

### 7.2 Environment Configuration

**Production**:
```bash
MCP_ALLOW_HTTP_INSECURE=false
MCP_REQUEST_TIMEOUT_MS=30000
OPENAI_API_KEY=sk-prod-...
OPENAI_BASE_URL=https://api.openai.com
```

**Development**:
```bash
MCP_ALLOW_HTTP_INSECURE=true
MCP_REQUEST_TIMEOUT_MS=20000
OLLAMA_BASE_URL=http://192.168.1.60:11434
```

### 7.3 Network Requirements

- **Firewall**: Allow TCP traffic between machines
- **DNS**: Optional for hostname resolution
- **Latency**: Configure generous timeouts for WAN deployments
- **Bandwidth**: Minimal (text-based communication)

---

## 8. Technology Stack

### 8.1 Backend
| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| Framework | FastAPI | 0.115.0 | Web framework |
| ASGI Server | Uvicorn | 0.30.6 | Production server |
| HTTP Client | httpx | 0.27.0 | Async HTTP requests |
| Validation | Pydantic | 2.8.2 | Data validation |
| Runtime | Python | 3.8+ | Programming language |

### 8.2 Frontend
| Component | Technology | Purpose |
|-----------|------------|---------|
| Language | JavaScript (ES6+) | UI logic |
| Storage | localStorage API | Config persistence |
| HTTP | Fetch API | Backend communication |
| UI Framework | None (Vanilla) | No dependencies |

### 8.3 Protocols
- **MCP Communication**: JSON-RPC 2.0 over HTTP/HTTPS
- **LLM Communication**: REST API (provider-specific)
- **Frontend-Backend**: REST API (JSON)

---

## 9. Future Enhancements

### 9.1 Phase 2
- Persistent database (PostgreSQL/SQLite)
- WebSocket streaming for LLM responses
- Multi-user authentication
- Conversation export (JSON/Markdown)

### 9.2 Phase 3
- Tool execution history analytics
- Server discovery/registry
- Custom tool result formatters
- Rate limiting and quotas

---

## 10. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| MCP server downtime | Chat functionality degraded | Health monitoring, graceful degradation |
| LLM provider rate limits | Service interruption | Mock provider fallback, retry logic |
| localStorage quota exceeded | Config loss | Implement compression, warn users |
| Network latency (multi-machine) | Slow responses | Generous timeouts, loading indicators |
| Tool execution loops | Resource exhaustion | Max 8 tool calls per turn limit |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-07 | AI Assistant | Initial HLD document |

**Approval**

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Architect | _______________ | _______________ | _______ |
| Tech Lead | _______________ | _______________ | _______ |
