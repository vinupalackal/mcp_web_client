# MCP Client Web (JSON-RPC) - Requirements Document

**Project**: MCP Client Web Interface  
**Version**: 0.2.0-jsonrpc  
**Date**: March 7, 2026  
**Status**: Active Development

## 1. Executive Summary

The MCP Client Web is a browser-based chat interface inspired by LibreChat, designed for seamless interaction with Model Context Protocol (MCP) servers. Users engage with AI tools through an intuitive chat interface that integrates with multiple LLM providers (OpenAI/Ollama). The system uses JSON-RPC 2.0 protocol for MCP server communication and supports distributed multi-machine deployments.

## 2. System Overview

### 2.1 Architecture
- **Backend**: FastAPI-based Python server (uvicorn)
- **Frontend**: Vanilla JavaScript SPA with LibreChat-inspired UI
- **Protocol Support**: JSON-RPC 2.0 for MCP servers
- **Storage**: Dual storage (in-memory backend + browser localStorage)
- **Deployment**: Supports distributed multi-machine setups (MCP servers, LLM, and client on different hosts)

### 2.2 Core Components
1. Chat Interface (LibreChat-inspired layout)
2. MCP Server Management System (JSON-RPC 2.0)
3. LLM Integration Layer (OpenAI, Ollama, Mock)
4. Tool Discovery and Execution Engine
5. Session Management System
6. Settings Modal (Tabbed: MCP Servers, LLM Config, Tools)

## 3. Functional Requirements

### 3.1 MCP Server Management

#### FR-1.1: Server Registration
- **Priority**: P0 (Critical)
- **Description**: Users shall be able to register MCP servers via settings modal with the following attributes:
  - Server alias (unique identifier, 1-64 characters)
  - Base URL (HTTP/HTTPS endpoint, supports remote hosts)
  - Authentication type (none, bearer token, API key)
  - Protocol: JSON-RPC 2.0 (fixed)
  - Timeout configuration (default 20 seconds)
- **Network Support**: Localhost, LAN IPs (192.168.x.x), and domain names
- **Acceptance Criteria**:
  - Form validates required fields (alias, base_url)
  - Duplicate aliases are rejected
  - HTTPS enforcement (unless `MCP_ALLOW_HTTP_INSECURE=true`)
  - Configuration persists to both backend and localStorage
  - Server appears in "Configured Servers" list immediately after save

#### FR-1.2: Server CRUD Operations
- **Priority**: P0 (Critical)
- **Description**: System shall support full Create, Read, Update, Delete operations for servers
- **API Endpoints**:
  - `GET /api/servers` - List all servers
  - `POST /api/servers` - Create new server
  - `PUT /api/servers/{server_id}` - Update server
  - `DELETE /api/servers/{server_id}` - Delete server
- **Acceptance Criteria**:
  - Changes sync between backend API and localStorage
  - Server deletion removes associated tools
  - Settings modal remains open during operations
  - Success/error messages display inline

#### FR-1.3: Server Health Monitoring
- **Priority**: P1 (High)
- **Description**: System shall monitor server health status
- **Capabilities**:
  - Health check endpoint testing
  - Latency measurement
  - Status indicators (healthy, unhealthy, unknown)
  - Timestamp of last check
- **Acceptance Criteria**:
  - Health status updates on server registration
  - Periodic health checks (configurable)
  - Visual status indicators in UI

### 3.2 Tool Discovery and Management

#### FR-2.1: Tool Discovery
- **Priority**: P0 (Critical)
- **Description**: System shall automatically discover tools from connected MCP servers
- **Process**:
  1. Initialize server connection (JSON-RPC only)
  2. Call `tools/list` endpoint
  3. Parse and canonicalize tool schemas
  4. Store with namespaced IDs: `{server_alias}__{tool_name}`
- **Acceptance Criteria**:
  - Tools refresh on demand via "Refresh Tools" button
  - Tools display with description and metadata
  - Tool count updates per server
  - Duplicate tool names across servers don't conflict

#### FR-2.2: Tool Execution
- **Priority**: P0 (Critical)
- **Description**: System shall execute tools via MCP servers and return results to LLM
- **Capabilities**:
  - JSON-RPC: `tools/call` with tool name and arguments
  - REST: `POST /mcp/v1/tools/call` with payload
  - Timeout handling with granular controls
  - Result preview generation (truncated for large outputs)
  - Result storage with handle-based retrieval
- **Acceptance Criteria**:
  - Tool execution completes within configured timeout
  - Results formatted appropriately for LLM provider (OpenAI vs Ollama)
  - Execution traces captured with duration metrics
  - Error handling with descriptive messages

### 3.3 LLM Integration

#### FR-3.1: Multiple LLM Provider Support
- **Priority**: P0 (Critical)
- **Description**: System shall integrate with multiple LLM providers
- **Supported Providers**:
  - OpenAI (API key + base URL configuration)
  - Ollama (local instance with base URL)
  - Mock (testing mode)
- **Acceptance Criteria**:
  - Provider selection persists to localStorage
  - API credentials secured (not logged)
  - Provider-specific message formatting
  - Connection testing functionality

#### FR-3.2: Tool-Calling Workflow
- **Priority**: P0 (Critical)
- **Description**: System shall orchestrate multi-turn conversations with tool execution
- **Workflow**:
  1. User sends message
  2. LLM receives message + available tools
  3. LLM responds with text or tool call requests
  4. System executes requested tools
  5. Tool results returned to LLM
  6. Loop continues until no more tool calls (max 8 per turn)
- **Acceptance Criteria**:
  - Maximum tool calls per turn configurable (`MCP_MAX_TOOL_CALLS_PER_TURN`)
  - Tool results truncated if exceeding size limits
  - OpenAI uses `tool_call_id`, Ollama uses `tool_name`
  - Conversation history maintained in session

### 3.4 Session Management

#### FR-4.1: Session Creation
- **Priority**: P1 (High)
- **Description**: System shall create isolated conversation sessions
- **Session Attributes**:
  - Unique session ID
  - LLM configuration (provider, model)
  - MCP configuration (enabled servers)
  - Message history
  - Tool call traces
  - Trace events
- **Acceptance Criteria**:
  - Sessions persist until page reload
  - New chat creates new session
  - Session ID displayed in UI

#### FR-4.2: Message History
- **Priority**: P1 (High)
- **Description**: System shall maintain conversation history per session
- **Capabilities**:
  - User messages stored with role
  - Assistant responses stored
  - Tool execution results stored
  - Trace events for debugging
- **Acceptance Criteria**:
  - Messages display in chronological order
  - Role-based styling (user, assistant, system)
  - Tool call traces accessible via API

### 3.5 User Interface

#### FR-5.1: LibreChat-Inspired Chat Interface
- **Priority**: P0 (Critical)
- **Description**: System shall provide a clean, modern chat interface similar to LibreChat
- **Layout Components**:
  - Header with Settings and New Chat buttons
  - Main chat area with message history
  - Message input at bottom with send button
  - Visual distinction between user/assistant messages
  - Tool execution indicators and results display
- **Acceptance Criteria**:
  - Responsive layout (desktop and tablet)
  - Auto-scroll to latest message
  - Enter key sends message
  - Loading indicators during processing
  - Tool calls visually highlighted

#### FR-5.2: Settings Management
- **Priority**: P0 (Critical)
- **Description**: System shall provide tabbed settings modal overlay
- **Tabs**:
  - MCP Servers (add, list, delete, refresh tools)
  - LLM Configuration (provider, model, credentials, test connection)
  - Tools (view discovered tools with server grouping)
- **Acceptance Criteria**:
  - Modal persists during multi-step operations
  - Tab state preserved during navigation
  - Real-time configuration updates
  - Inline validation and error messages
  - Close button (X) in top-right corner

#### FR-5.3: Tool Execution Visualization
- **Priority**: P1 (High)
- **Description**: System shall clearly display tool execution in chat messages
- **Features**:
  - Tool call indicators (e.g., "[Tool: weather_api__get_weather]")
  - Tool execution status (running, success, error)
  - Result preview in chat (truncated if large)
  - Expandable full results (optional)
  - Execution timing information
- **Acceptance Criteria**:
  - Tool calls appear inline with assistant messages
  - Visual differentiation from regular text
  - Error states clearly indicated
  - Results formatted readably

## 4. Non-Functional Requirements

### 4.1 Performance

#### NFR-1.1: Response Times
- **Priority**: P1 (High)
- **Requirements**:
  - Server registration: < 1 second
  - Tool discovery: < 5 seconds per server
  - Tool execution: Within configured timeout (default 20s)
  - UI interactions: < 100ms
- **Acceptance Criteria**:
  - Loading indicators for operations > 200ms
  - Timeout errors clearly communicated

#### NFR-1.2: Concurrency
- **Priority**: P2 (Medium)
- **Requirements**:
  - Support multiple concurrent sessions (browser limitation)
  - Sequential tool execution within a turn
  - Async API operations
- **Acceptance Criteria**:
  - No blocking operations in UI thread
  - Background processes don't freeze interface

### 4.2 Security

#### NFR-2.1: HTTPS Enforcement
- **Priority**: P0 (Critical)
- **Requirements**:
  - Production mode requires HTTPS for MCP servers
  - Development mode allows HTTP with explicit flag
  - Environment variable: `MCP_ALLOW_HTTP_INSECURE`
- **Acceptance Criteria**:
  - HTTP URLs rejected unless flag enabled
  - Clear error messages for security violations

#### NFR-2.2: Credential Handling
- **Priority**: P0 (Critical)
- **Requirements**:
  - API keys and tokens not logged
  - Credentials masked in UI (password fields)
  - localStorage used for client-side persistence (acknowledge security implications)
- **Acceptance Criteria**:
  - Sensitive data not in console logs
  - Authentication headers properly formatted

### 4.3 Reliability

#### NFR-3.1: Error Handling
- **Priority**: P0 (Critical)
- **Requirements**:
  - All API calls have timeout protection
  - Granular timeout categorization (connect, read, write, pool)
  - Graceful degradation on server failures
  - Fallback to localStorage if backend unavailable
- **Acceptance Criteria**:
  - Specific error messages for timeout types
  - User-friendly error display
  - System remains functional during partial failures

#### NFR-3.2: Data Persistence
- **Priority**: P1 (High)
- **Requirements**:
  - Dual storage: Backend (in-memory) + Frontend (localStorage)
  - Automatic synchronization on save/load
  - Offline resilience via localStorage
- **Acceptance Criteria**:
  - Server configs survive page reload
  - LLM configs persist across sessions
  - Data consistency between storage layers

### 4.4 Logging and Observability

#### NFR-4.1: Dual-Logger Architecture
- **Priority**: P1 (High)
- **Requirements**:
  - `logger_internal`: Application flow (INFO level)
  - `logger_external`: External API communication (INFO level)
  - Directional arrows for request/response logging
- **Acceptance Criteria**:
  - All API calls logged with method, URL, status
  - Tool execution timing captured
  - Error stack traces in internal logs

#### NFR-4.2: Browser Console Logging
- **Priority**: P2 (Medium)
- **Requirements**:
  - Emoji prefixes for log categorization
  - Function entry/exit logging
  - State change notifications
- **Acceptance Criteria**:
  - Debugging enabled via console inspection
  - Performance impact minimal

## 5. Technical Requirements

### 5.1 Backend Stack

#### TR-1.1: Python Dependencies
- **Priority**: P0 (Critical)
- **Requirements**:
  - Python 3.8+
  - FastAPI 0.115.0
  - Uvicorn 0.30.6 with standard extras
  - httpx 0.27.0 for async HTTP
  - Pydantic 2.8.2 for validation
- **Acceptance Criteria**:
  - Virtual environment setup documented
  - requirements.txt maintained
  - Compatible with production ASGI servers

#### TR-1.2: API Design (OpenAPI Spec-Driven)
- **Priority**: P0 (Critical)
- **Requirements**:
  - OpenAPI 3.0+ specification as source of truth
  - Spec-first development: Define schemas before implementation
  - Pydantic models match OpenAPI schemas exactly
  - FastAPI auto-generates spec from models
  - RESTful API conventions
  - CORS enabled for development
  - Global exception handlers
- **Acceptance Criteria**:
  - OpenAPI spec available at `/openapi.json`
  - Interactive docs at `/docs` (Swagger UI)
  - Alternative docs at `/redoc` (ReDoc)
  - All endpoints documented with descriptions, examples, and response codes
  - Pydantic validation matches OpenAPI constraints
  - Proper HTTP status codes (200, 201, 400, 404, 422, 500)
  - JSON response format with consistent error structure

### 5.2 Frontend Stack

#### TR-2.1: Technology Constraints
- **Priority**: P0 (Critical)
- **Requirements**:
  - Vanilla JavaScript (no frameworks)
  - ES6+ syntax
  - Browser localStorage API
  - Fetch API for HTTP requests
- **Acceptance Criteria**:
  - No build step required
  - Works in modern browsers (Chrome, Firefox, Safari, Edge)
  - Progressive enhancement approach

#### TR-2.2: Static File Serving
- **Priority**: P1 (High)
- **Requirements**:
  - Backend serves static files from `backend/static/`
  - HTML, CSS, JavaScript files
  - FastAPI StaticFiles middleware
- **Acceptance Criteria**:
  - Files accessible at `/static/*` paths
  - Index at root `/` path
  - Proper MIME types

### 5.3 Environment Configuration

#### TR-3.1: Environment Variables
- **Priority**: P1 (High)
- **Required Variables**:
  ```bash
  # Security
  MCP_ALLOW_HTTP_INSECURE=false          # Allow HTTP MCP servers
  
  # Timeouts
  MCP_REQUEST_TIMEOUT_MS=20000           # Default request timeout
  
  # Limits
  MCP_MAX_TOOL_CALLS_PER_TURN=8          # Tool execution limit
  MCP_MAX_RESULT_PREVIEW_CHARS=4000      # Result preview size
  MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM=12000 # Max output to LLM
  
  # LLM Providers
  OPENAI_API_KEY=<key>                   # OpenAI API key
  OPENAI_BASE_URL=https://api.openai.com # OpenAI endpoint
  OLLAMA_BASE_URL=http://127.0.0.1:11434 # Ollama endpoint
  ```
- **Acceptance Criteria**:
  - Defaults work for local development
  - Production values override defaults
  - Documented in README

## 6. Integration Requirements

### 6.1 MCP Server Compatibility

#### IR-1.1: JSON-RPC 2.0 Protocol
- **Priority**: P0 (Critical)
- **Requirements**:
  - JSON-RPC 2.0 specification compliance
  - Protocol version: "2024-11-05"
  - Required initialization handshake: `initialize` method
  - Tool operations: `tools/list` and `tools/call` methods
  - Client info: `{"name": "mcp-client-web", "version": "1.0"}`
  - RPC endpoint: POST to `{base_url}/rpc`
- **Acceptance Criteria**:
  - Successful initialization handshake before tool operations
  - Tool schemas parsed correctly with namespacing
  - JSON-RPC error responses handled with proper error codes
  - Supports remote MCP servers across network

#### IR-1.2: Network Communication
- **Priority**: P0 (Critical)
- **Requirements**:
  - Support HTTP and HTTPS protocols
  - HTTPS enforced in production (unless `MCP_ALLOW_HTTP_INSECURE=true`)
  - Handle network latency in multi-machine deployments
  - Granular timeout configuration (connect, read, write, pool)
- **Acceptance Criteria**:
  - Successfully communicates with MCP servers on different machines
  - Proper error messages for network failures
  - Configurable timeouts for WAN scenarios

### 6.2 LLM Provider Compatibility

#### IR-2.1: OpenAI API
- **Priority**: P0 (Critical)
- **Requirements**:
  - `/v1/chat/completions` endpoint
  - Function calling with `tools` array
  - `tool_call_id` in responses
  - Compatible with OpenAI-compatible APIs
- **Acceptance Criteria**:
  - Tool definitions follow OpenAI schema
  - Streaming disabled (non-streaming mode)
  - Usage metrics captured

#### IR-2.2: Ollama API
- **Priority**: P1 (High)
- **Requirements**:
  - `/api/chat` endpoint
  - Function calling support
  - `tool_name` in responses (not `tool_call_id`)
  - Non-streaming mode
- **Acceptance Criteria**:
  - Local Ollama instance compatibility
  - Model selection from installed models
  - Response format adapted for Ollama

## 7. User Requirements

### 7.1 Target Users
- Developers testing MCP server implementations
- AI engineers integrating MCP tools
- System administrators configuring MCP infrastructure
- QA testers validating MCP workflows

### 7.2 User Workflows

#### UW-1: Configure MCP Server
1. Click Settings button
2. Navigate to "MCP Servers" tab
3. Fill server details (alias, URL, auth)
4. Click "Add Server"
5. Verify server appears in configured list
6. Click "Refresh Tools" to discover tools

#### UW-2: Configure LLM Provider
1. Click Settings button
2. Navigate to "LLM" tab
3. Select provider (OpenAI/Ollama)
4. Enter model name and credentials
5. Click "Save LLM Configuration"
6. Optionally test connection

#### UW-3: Chat with Tools (LibreChat Style)
1. Click "New Chat" button in header
2. Type message in input box (e.g., "What's the weather in NYC?")
3. Press Enter or click Send button
4. Observe assistant response with:
   - Acknowledgment text
   - Tool execution indicator: [Tool: weather_api__get_weather]
   - Tool result preview
   - Final answer synthesized from result
5. Continue multi-turn conversation
6. Tool executions appear inline with messages

## 8. Constraints and Assumptions

### 8.1 Constraints
- Single-user application (no multi-tenancy)
- Session data lost on page reload
- In-memory backend storage (not persistent)
- Browser localStorage limitations (~5-10MB)
- No authentication/authorization system

### 8.2 Assumptions
- Users have network access to MCP servers (may be on different machines)
- MCP servers implement JSON-RPC 2.0 protocol version 2024-11-05
- Users understand MCP tool concepts
- Modern browser with JavaScript enabled (Chrome, Firefox, Safari, Edge)
- LLM provider accessible via network (localhost, LAN, or internet)
- Firewall rules configured for cross-machine communication
- Network latency acceptable for distributed deployments

## 9. Future Enhancements (Out of Scope)

### 9.1 Planned Features
- Persistent backend storage (database)
- User authentication and authorization
- Multi-user session management
- Streaming LLM responses
- Tool execution history export
- Server configuration import/export
- Advanced tool filtering and search
- Conversation export (JSON, Markdown)
- Real-time server status monitoring
- Tool execution rate limiting
- Custom tool result formatters

### 9.2 Potential Integrations
- Additional LLM providers (Anthropic, Cohere)
- MCP server discovery/registry
- Webhook notifications for tool results
- Integration with CI/CD pipelines
- Monitoring and analytics platform
- API gateway for production deployment

## 10. Acceptance Testing

### 10.1 Critical Path Tests
1. **Chat Interface**: Send messages and receive responses (LibreChat-like UX)
2. **Server Management**: Add, update, delete MCP servers via settings modal
3. **Tool Discovery**: Refresh and display tools from remote JSON-RPC servers
4. **Tool Execution**: Execute tools through LLM conversation with visual feedback
5. **LLM Integration**: Chat with OpenAI and Ollama providers
6. **Session Persistence**: Settings survive page reload (localStorage)
7. **Error Handling**: Graceful failures for unreachable servers
8. **Multi-Machine**: MCP server on remote host communicates successfully
9. **Network Timeout**: Proper handling of slow/unreachable remote servers

### 10.2 Debug Pages
Test utilities in `backend/static/`:
- `debug-servers.html` - Server CRUD testing
- `mcp-server-test.html` - MCP integration testing
- `llm-config-test.html` - LLM configuration testing

## 10.3 OpenAPI Spec-Driven Development

**Workflow**:
1. Define Pydantic models first (source of truth)
2. Add FastAPI endpoints with full type hints
3. Document with docstrings and examples
4. Verify `/docs` shows complete specification
5. Implement endpoint logic following models
6. Test against OpenAPI schema validation

**Model Documentation**:
```python
class ChatMessage(BaseModel):
    """A chat message in the conversation"""
    role: Literal["user", "assistant", "tool", "system"] = Field(
        ..., description="Message role in conversation"
    )
    content: str = Field(..., description="Message content", min_length=1)
    
    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "What's the weather in NYC?"
            }
        }
```

**Endpoint Documentation**:
```python
@app.post(
    "/api/sessions/{session_id}/messages",
    response_model=ChatResponse,
    status_code=200,
    tags=["Chat"],
    summary="Send chat message",
    description="Send a user message and receive assistant response with tool execution"
)
async def send_message(
    session_id: str = Path(..., description="Session UUID"),
    message: ChatMessage = Body(..., description="User message")
) -> ChatResponse:
    """Process user message through LLM with tool execution capability"""
```

## 11. Documentation Requirements

### 11.1 User Documentation
- README with setup instructions ✅
- Environment variable reference ✅
- OpenAPI specification (auto-generated) ✅
- Interactive API documentation at `/docs` ✅
- Troubleshooting guide

### 11.2 Developer Documentation
- AI coding agent instructions ✅ (`.github/copilot-instructions.md`)
- Architecture diagrams
- Code style guide
- Contribution guidelines

## 12. Compliance and Standards

### 12.1 Standards Adherence
- JSON-RPC 2.0 Specification (for MCP communication)
- OpenAPI 3.0+ (for internal REST API)
- HTTP/REST best practices (status codes, headers, methods)
- Semantic versioning (project version)
- Pydantic validation (schema enforcement)

### 12.2 Code Quality
- Python: PEP 8 style guide
- JavaScript: ES6+ best practices
- Type hints with Pydantic models
- Error handling patterns documented

---

**Document Control**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-07 | AI Assistant | Initial requirements document |

**Approval**

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Product Owner | _______________ | _______________ | _______ |
| Technical Lead | _______________ | _______________ | _______ |
| QA Lead | _______________ | _______________ | _______ |

