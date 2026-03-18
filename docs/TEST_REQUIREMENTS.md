# Test Requirements Document
## MCP Client Web Interface

**Project**: MCP Client Web  
**Version**: 0.2.0-jsonrpc  
**Date**: March 10, 2026  
**Status**: Active  
**Scope**: All existing features in v0.2.0-jsonrpc (Standard Mode only)  
**Excludes**: Enterprise Gateway features (covered in ENTERPRISE_GATEWAY_REQUIREMENTS.md §8)

---

## 1. Test Strategy

### 1.1 Test Layers

| Layer | Type | Tool | Purpose |
|-------|------|------|---------|
| Unit | Component isolation | `pytest` | Models, LLM clients, session manager, MCP manager |
| Integration | API endpoint | `pytest` + `httpx.AsyncClient` via FastAPI `TestClient` | All REST endpoints |
| Contract | JSON-RPC protocol | `pytest` + mock HTTP | MCP server communication |
| End-to-End | Full chat flow | `pytest` + mock LLM + mock MCP | Complete user workflows |
| Security | Credential / HTTPS | `pytest` | HTTPS enforcement, no credential leakage |

### 1.2 Test Naming Convention

```
test_<component>_<scenario>_<expected_outcome>
e.g.  test_server_create_duplicate_alias_returns_409
```

### 1.3 Fixtures Required

- `test_client` — FastAPI `TestClient` with clean in-memory state
- `mock_mcp_server` — `httpx` mock for JSON-RPC responses
- `mock_openai` — mock for OpenAI `/v1/chat/completions`
- `mock_ollama` — mock for Ollama `/api/chat`
- `sample_server_config` — valid `ServerConfig` fixture
- `sample_llm_config_openai` — valid OpenAI `LLMConfig`
- `sample_llm_config_ollama` — valid Ollama `LLMConfig`

---

## 2. Health Check Tests

### TR-HC-1: API Health Endpoint

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-HC-01 | Basic health check | `GET /health` | HTTP 200, `status="healthy"`, `version="0.2.0-jsonrpc"`, `timestamp` present |
| TC-HC-02 | Response schema | `GET /health` | Response matches `HealthResponse` Pydantic model |
| TC-HC-03 | Timestamp is UTC | `GET /health` | `timestamp` field is a valid ISO 8601 datetime |

---

## 3. MCP Server Management Tests

### TR-SRV-1: List Servers

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-SRV-01 | Empty list | `GET /api/servers` on fresh state | HTTP 200, empty array `[]` |
| TC-SRV-02 | List after add | Add 2 servers, then `GET /api/servers` | HTTP 200, array with 2 servers |
| TC-SRV-03 | Response schema | `GET /api/servers` | Each item matches `ServerConfig` model |

### TR-SRV-2: Create Server

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-SRV-04 | Create valid server (HTTP, insecure flag) | `POST /api/servers` with valid alias + HTTP URL, `MCP_ALLOW_HTTP_INSECURE=true` | HTTP 201, server object returned with `server_id` |
| TC-SRV-05 | Create valid server (HTTPS) | `POST /api/servers` with HTTPS URL | HTTP 201, server stored |
| TC-SRV-06 | Auto-generated server_id | `POST /api/servers` without `server_id` | HTTP 201, `server_id` is a valid UUID |
| TC-SRV-07 | Duplicate alias rejected | Create server, then create another with same alias | HTTP 409, error detail mentions alias |
| TC-SRV-08 | Duplicate server_id rejected | `POST` with an existing `server_id` | HTTP 409 |
| TC-SRV-09 | HTTP URL blocked in production | `POST` with `http://` URL, `MCP_ALLOW_HTTP_INSECURE=false` | HTTP 400, error mentions HTTPS |
| TC-SRV-10 | HTTP URL allowed in dev | `POST` with `http://` URL, `MCP_ALLOW_HTTP_INSECURE=true` | HTTP 201 |
| TC-SRV-11 | Missing alias field | `POST` without `alias` | HTTP 422 (validation error) |
| TC-SRV-12 | Missing base_url field | `POST` without `base_url` | HTTP 422 |
| TC-SRV-13 | Invalid URL format | `POST` with `base_url="not-a-url"` | HTTP 422 |
| TC-SRV-14 | Alias too long (>64 chars) | `POST` with 65-char alias | HTTP 422 |
| TC-SRV-15 | Empty alias | `POST` with `alias=""` | HTTP 422 |
| TC-SRV-16 | All auth types accepted | `POST` with `auth_type` = `none`, `bearer`, `api_key` | HTTP 201 for each |
| TC-SRV-17 | Default timeout_ms | `POST` without `timeout_ms` | Returned object has `timeout_ms=20000` |
| TC-SRV-18 | Bearer token stored | `POST` with `bearer_token="secret"` | Stored server has `bearer_token="secret"` |

### TR-SRV-3: Update Server

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-SRV-19 | Update existing server | `PUT /api/servers/{id}` with changed alias | HTTP 200, updated object returned |
| TC-SRV-20 | server_id from path wins | `PUT` with different `server_id` in body | `server_id` in response matches path param |
| TC-SRV-21 | Update non-existent server | `PUT /api/servers/nonexistent` | HTTP 404 |
| TC-SRV-22 | Update is idempotent | `PUT` twice with same data | HTTP 200 both times, state unchanged |

### TR-SRV-4: Delete Server

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-SRV-23 | Delete existing server | `DELETE /api/servers/{id}` | HTTP 200, `success=true` |
| TC-SRV-24 | Server removed from list | Delete, then `GET /api/servers` | Deleted server absent from list |
| TC-SRV-25 | Delete non-existent server | `DELETE /api/servers/nonexistent` | HTTP 404 |
| TC-SRV-26 | Associated tools removed | Add server, discover tools, delete server | Tools for that server removed from `mcp_manager.tools` |
| TC-SRV-27 | Delete is idempotent | Delete same ID twice | First: 200; Second: 404 |

---

## 4. Tool Discovery Tests

### TR-TOOL-1: Refresh Tools

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-TOOL-01 | No servers configured | `POST /api/servers/refresh-tools` with empty server list | HTTP 200, `total_tools=0`, `servers_refreshed=0`, error message in `errors` |
| TC-TOOL-02 | Successful discovery | Mock MCP server returns 3 tools | HTTP 200, `total_tools=3`, `servers_refreshed=1`, `errors=[]` |
| TC-TOOL-03 | Multiple servers | 2 servers, each with 2 tools | `total_tools=4`, `servers_refreshed=2` |
| TC-TOOL-04 | Partial failure | Server 1 succeeds (3 tools), Server 2 times out | `total_tools=3`, `servers_refreshed=1`, `errors` contains server 2 error |
| TC-TOOL-05 | Tool namespacing | Server alias `weather_api`, tool name `get_weather` | Tool stored as `weather_api__get_weather` |
| TC-TOOL-06 | Refresh replaces stale tools | Refresh twice (second time server has 1 fewer tool) | Tool registry reflects latest count |

### TR-TOOL-2: List Tools

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-TOOL-07 | Empty list | `GET /api/tools` before any discovery | HTTP 200, `[]` |
| TC-TOOL-08 | Tools after discovery | Discover 3 tools, `GET /api/tools` | HTTP 200, 3 tools in array |
| TC-TOOL-09 | Tool schema shape | `GET /api/tools` | Each item has `namespaced_id`, `server_alias`, `name`, `description`, `parameters` |
| TC-TOOL-10 | Namespaced ID format | Tools from server `svc` with tool `ping` | `namespaced_id = "svc__ping"` |

---

## 5. LLM Configuration Tests

### TR-LLM-1: Get LLM Config

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-LLM-01 | No config set | `GET /api/llm/config` on fresh state | HTTP 404 |
| TC-LLM-02 | Config after save | Save config, then `GET /api/llm/config` | HTTP 200, matches saved config |
| TC-LLM-03 | Response schema | `GET /api/llm/config` | Response matches `LLMConfig` model |

### TR-LLM-2: Save LLM Config

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-LLM-04 | Save OpenAI config | `POST /api/llm/config` with `provider="openai"` | HTTP 200, config returned |
| TC-LLM-05 | Save Ollama config | `POST /api/llm/config` with `provider="ollama"` | HTTP 200 |
| TC-LLM-06 | Save Mock config | `POST /api/llm/config` with `provider="mock"` | HTTP 200 |
| TC-LLM-07 | Invalid provider | `POST /api/llm/config` with `provider="unknown"` | HTTP 422 |
| TC-LLM-08 | Missing provider | `POST /api/llm/config` without `provider` | HTTP 422 |
| TC-LLM-09 | Missing model | `POST /api/llm/config` without `model` | HTTP 422 |
| TC-LLM-10 | Temperature range | `POST` with `temperature=2.1` | HTTP 422 |
| TC-LLM-11 | Temperature valid boundary | `POST` with `temperature=0.0` and `temperature=2.0` | HTTP 200 for both |
| TC-LLM-12 | Config overwrite | Save twice with different models | Second model stored |
| TC-LLM-13 | max_tokens optional | `POST` without `max_tokens` | HTTP 200, `max_tokens=None` |
| TC-LLM-14 | api_key optional | `POST` without `api_key` | HTTP 200 |

---

## 6. Session Management Tests

### TR-SESS-1: Create Session

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-SESS-01 | Create session (no body) | `POST /api/sessions` | HTTP 201, `session_id` is UUID, `created_at` present |
| TC-SESS-02 | Unique session IDs | Create 5 sessions | All 5 `session_id` values are distinct |
| TC-SESS-03 | Session stored in manager | Create session | `session_manager.get_session(id)` returns the session |
| TC-SESS-04 | Messages initialized empty | Create session | `session_manager.get_messages(id)` returns `[]` |
| TC-SESS-05 | Tool traces initialized empty | Create session | `session_manager.get_tool_traces(id)` returns `[]` |

### TR-SESS-2: Session Manager Unit Tests

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-SESS-06 | `create_session()` default ID | Call without `session_id` | Returns `SimpleSession` with UUID `session_id` |
| TC-SESS-07 | `create_session()` with ID | Call with explicit `session_id="abc"` | Session ID is `"abc"` |
| TC-SESS-08 | `get_session()` found | Create then get | Returns `SimpleSession` |
| TC-SESS-09 | `get_session()` not found | Get non-existent ID | Returns `None` |
| TC-SESS-10 | `delete_session()` success | Create then delete | Returns `True`, session gone |
| TC-SESS-11 | `delete_session()` not found | Delete non-existent ID | Returns `False` |
| TC-SESS-12 | `add_message()` auto-creates session | Add to non-existent session | Session created automatically, message stored |
| TC-SESS-13 | `get_messages()` order | Add 3 messages | Returned in insertion order |
| TC-SESS-14 | `add_tool_trace()` stored | Add trace event | Returned by `get_tool_traces()` |
| TC-SESS-15 | `update_session_title()` | Update existing session title | Returns `True`, title updated |
| TC-SESS-16 | `update_session_title()` not found | Update non-existent session | Returns `False` |

---

## 7. Chat / Message Flow Tests

### TR-CHAT-1: Send Message Endpoint

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-CHAT-01 | No LLM config | Send message without LLM config set | HTTP 200, response content: "Please configure an LLM provider in Settings." |
| TC-CHAT-02 | Mock LLM, no tools | Send message with Mock provider | HTTP 200, response has `role="assistant"`, non-empty content |
| TC-CHAT-03 | Response structure | Any successful send | Response has `session_id`, `message`, `tool_executions` |
| TC-CHAT-04 | Message added to session | Send message | `session_manager.get_messages(id)` has user message + assistant message |
| TC-CHAT-05 | Invalid session ID | `POST /api/sessions/nonexistent/messages` | HTTP 200 (session auto-created per current behavior) |
| TC-CHAT-06 | Empty content rejected | `POST` with `content=""` | HTTP 422 |
| TC-CHAT-07 | System prompt injected | Send any message | Messages sent to LLM start with `role="system"` |

### TR-CHAT-2: Tool Calling Flow

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-CHAT-08 | LLM requests tool call | Mock LLM returns `finish_reason="tool_calls"` | Tool executed via MCP manager |
| TC-CHAT-09 | Tool result returned to LLM | Tool executed successfully | Tool result message added to conversation, second LLM call made |
| TC-CHAT-10 | Tool execution logged | Successful tool call | `session_manager.get_tool_traces(id)` contains trace with `success=True` |
| TC-CHAT-11 | Failed tool execution traced | Tool raises exception | Trace contains `success=False`, error message surfaced to LLM |
| TC-CHAT-12 | Max tool call limit | Mock LLM always returns `tool_calls` | Loop stops at `MCP_MAX_TOOL_CALLS_PER_TURN` (default 8), fallback message returned |
| TC-CHAT-13 | Result truncation | Tool returns >12000 chars | Content sent to LLM is truncated to `MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM` |
| TC-CHAT-14 | Invalid tool name format | LLM returns tool without `__` | Error logged, tool skipped gracefully |
| TC-CHAT-15 | Unknown server alias | LLM calls tool for non-existent server | Error message returned as tool result |
| TC-CHAT-16 | Multiple tool calls in one turn | LLM returns 2 tool calls | Both tools executed, results returned to LLM |

### TR-CHAT-3: Get Message History

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-CHAT-17 | Get messages | `GET /api/sessions/{id}/messages` | HTTP 200, `MessageListResponse` |
| TC-CHAT-18 | Response schema | `GET /api/sessions/{id}/messages` | Has `session_id` and `messages` array |

---

## 8. LLM Client Unit Tests

### TR-LLMC-1: OpenAI Client

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-LLMC-01 | Successful completion | Mock returns 200 with choices | Returns parsed response dict |
| TC-LLMC-02 | Tools included in payload | `tools` list non-empty | Request body contains `tools` and `tool_choice="auto"` |
| TC-LLMC-03 | No tools when empty | `tools=[]` | Request body has no `tools` key |
| TC-LLMC-04 | max_tokens included | `LLMConfig.max_tokens=500` | Request body contains `max_tokens=500` |
| TC-LLMC-05 | max_tokens omitted | `LLMConfig.max_tokens=None` | Request body has no `max_tokens` key |
| TC-LLMC-06 | Timeout exception | Mock raises `httpx.TimeoutException` | Raises `Exception("LLM request timeout")` |
| TC-LLMC-07 | HTTP error | Mock returns HTTP 500 | Raises `Exception` with HTTP error detail |
| TC-LLMC-08 | URL construction | `base_url="https://api.openai.com"` | Request sent to `https://api.openai.com/v1/chat/completions` |
| TC-LLMC-09 | Auth header | `api_key="sk-test"` | Request header `Authorization: Bearer sk-test` |
| TC-LLMC-10 | `format_tool_result` OpenAI | `tool_call_id="call_1"`, `content="ok"` | Returns `{"role":"tool","tool_call_id":"call_1","content":"ok"}` |

### TR-LLMC-2: Ollama Client

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-LLMC-11 | Response normalized | Ollama format response | Returns OpenAI-compatible `choices` structure |
| TC-LLMC-12 | `done=true` → `finish_reason="stop"` | Ollama `done: true` | Normalized `finish_reason="stop"` |
| TC-LLMC-13 | Tool calls detected | Ollama message has `tool_calls` | `finish_reason="tool_calls"` in normalized response |
| TC-LLMC-14 | URL construction | `base_url="http://localhost:11434"` | Request sent to `http://localhost:11434/api/chat` |
| TC-LLMC-15 | No Authorization header | Ollama config | Request has no `Authorization` header |
| TC-LLMC-16 | `format_tool_result` Ollama | `tool_call_id="call_1"`, `content="ok"` | Returns `{"role":"tool","content":"ok"}` (no `tool_call_id`) |
| TC-LLMC-17 | `stream: false` | Any call | Payload contains `"stream": false` |
| TC-LLMC-18 | Timeout exception | Mock raises timeout | Raises `Exception("LLM request timeout")` |
| TC-LLMC-19 | HTTP status error | Mock returns 400 | Raises `Exception` with HTTP error detail |

### TR-LLMC-3: Mock LLM Client

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-LLMC-20 | Returns mock response | Any messages/tools | Returns `choices[0].message.role == "assistant"` |
| TC-LLMC-21 | `finish_reason="stop"` | Any call | `finish_reason="stop"` in response |
| TC-LLMC-22 | No external HTTP call | Any call | No outbound HTTP requests made |

### TR-LLMC-4: LLM Client Factory

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-LLMC-23 | OpenAI factory | `provider="openai"` | Returns `OpenAIClient` instance |
| TC-LLMC-24 | Ollama factory | `provider="ollama"` | Returns `OllamaClient` instance |
| TC-LLMC-25 | Mock factory | `provider="mock"` | Returns `MockLLMClient` instance |
| TC-LLMC-26 | Unknown provider | `provider="unknown"` | Raises `ValueError` |

---

## 9. Session Manager — Message Format Tests

### TR-FMT-1: `get_messages_for_llm()`

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-FMT-01 | OpenAI format — user message | `role="user"`, `content="hello"` | `{"role":"user","content":"hello"}` |
| TC-FMT-02 | OpenAI format — tool result | `role="tool"`, `tool_call_id="call_1"` | Includes `"tool_call_id":"call_1"` |
| TC-FMT-03 | OpenAI format — tool_calls | Assistant message with tool_calls | `tool_calls` array included in dict |
| TC-FMT-04 | Ollama format — tool message | `role="tool"`, provider=`"ollama"` | Converted to `{"role":"user","content":"Tool result: ..."}` |
| TC-FMT-05 | Ollama format — assistant with tool_calls | Provider=`"ollama"`, message has `tool_calls` and no `content` | Message skipped entirely |
| TC-FMT-06 | Ollama format — no tool_call_id | Provider=`"ollama"` | No `tool_call_id` key in any message |
| TC-FMT-07 | None content → empty string | `content=None` | `content=""` in output |
| TC-FMT-08 | Order preserved | Add 5 messages | Output in insertion order |
| TC-FMT-09 | Empty session | No messages | Returns `[]` |

---

## 10. MCP Manager Unit Tests

### TR-MCP-1: Server Initialization

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-MCP-01 | Successful initialize | Mock returns JSON-RPC success | `initialized_servers[server_id] = True` |
| TC-MCP-02 | JSON-RPC error in response | Mock returns `{"error": {...}}` | Raises `Exception` with error detail |
| TC-MCP-03 | HTTP error | Mock returns 500 | Raises `Exception` |
| TC-MCP-04 | Timeout | Mock hangs > timeout | Raises `Exception("Timeout connecting to ...")` |
| TC-MCP-05 | Init payload format | Inspect request body | Has `jsonrpc="2.0"`, `method="initialize"`, `protocolVersion="2024-11-05"`, `clientInfo.name="mcp-client-web"` |
| TC-MCP-06 | RPC URL construction | `base_url="http://host:3000"` | Sends to `http://host:3000/mcp` |
| TC-MCP-07 | Bearer auth header | `auth_type="bearer"`, `bearer_token="tok"` | Request header `Authorization: Bearer tok` |
| TC-MCP-08 | No auth header | `auth_type="none"` | No `Authorization` header |

### TR-MCP-2: Tool Discovery

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-MCP-09 | Discovers tools | Mock returns 2 tools | Returns list of 2 `ToolSchema` |
| TC-MCP-10 | Tools stored in registry | Discover from server | `mcp_manager.tools` contains discovered tools |
| TC-MCP-11 | Namespaced IDs | Server alias `"svc"`, tool `"ping"` | `namespaced_id = "svc__ping"` |
| TC-MCP-12 | Auto-initializes server | Call `discover_tools` without prior `initialize_server` | Initialization called automatically |
| TC-MCP-13 | JSON-RPC error | Mock returns tools/list error | Raises `Exception` |
| TC-MCP-14 | Empty tools list | Mock returns `{"tools": []}` | Returns `[]`, no error |
| TC-MCP-15 | `tools/list` payload format | Inspect request body | Has `method="tools/list"` |
| TC-MCP-16 | Description field | Tool has `description` | Stored in `ToolSchema.description` |
| TC-MCP-17 | Parameters field | Tool has `inputSchema` | Stored in `ToolSchema.parameters` |

### TR-MCP-3: Tool Execution

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-MCP-18 | Successful execution | Mock returns result | Returns result dict |
| TC-MCP-19 | `tools/call` payload | Execute `ping` with `{"host":"1.2.3.4"}` | Body has `method="tools/call"`, `params.name="ping"`, `params.arguments={"host":"1.2.3.4"}` |
| TC-MCP-20 | JSON-RPC error in result | Mock returns error | Raises `Exception` |
| TC-MCP-21 | HTTP error | Mock returns 404 | Raises `Exception` |
| TC-MCP-22 | Timeout | Mock hangs | Raises timeout `Exception` |
| TC-MCP-23 | Discover all tools | 2 servers, both succeed | Returns `(total_tools, 2, [])` |
| TC-MCP-24 | Discover all — partial fail | Server 2 raises error | Returns `(tools_from_1, 1, [error_msg])` |

---

## 11. Pydantic Model Validation Tests

### TR-MODEL-1: ServerConfig

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-MODEL-01 | Valid minimal config | No error, `server_id` auto-generated UUID |
| TC-MODEL-02 | `alias` max length 64 | 64 chars: ok; 65 chars: `ValidationError` |
| TC-MODEL-03 | `alias` min length 1 | Empty string: `ValidationError` |
| TC-MODEL-04 | `base_url` pattern | `"not-a-url"`: `ValidationError`; `"http://x"`: ok |
| TC-MODEL-05 | `auth_type` enum | `"api_key"`: ok; `"jwt"`: `ValidationError` |
| TC-MODEL-06 | `timeout_ms` range | 999: error; 1000: ok; 60000: ok; 60001: error |

### TR-MODEL-2: LLMConfig

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-MODEL-07 | Valid OpenAI config | No validation error |
| TC-MODEL-08 | `provider` enum | `"openai"`,`"ollama"`,`"mock"`: ok; anything else: error |
| TC-MODEL-09 | `temperature` range | -0.1: error; 0.0: ok; 2.0: ok; 2.1: error |
| TC-MODEL-10 | `max_tokens` min | 0: error; 1: ok; `None`: ok |
| TC-MODEL-11 | `model` required | Omitted: `ValidationError` |

### TR-MODEL-3: ChatMessage

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-MODEL-12 | `role` enum | `"user"`,`"assistant"`,`"tool"`,`"system"`: ok; `"bot"`: error |
| TC-MODEL-13 | `content` required | Omitted: `ValidationError` |
| TC-MODEL-14 | `tool_call_id` optional | Omitted: `None`; provided: stored |
| TC-MODEL-15 | `tool_calls` optional | Omitted: `None` |

### TR-MODEL-4: ToolSchema

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-MODEL-16 | All required fields | `namespaced_id`, `server_alias`, `name`, `description` required |
| TC-MODEL-17 | `parameters` default | Omitted `parameters`: defaults to `{}` |

---

## 12. Security Tests

### TR-SEC-1: HTTPS Enforcement

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-SEC-01 | HTTP blocked in prod | `POST /api/servers` with `http://` URL, env flag `false` | HTTP 400, error message mentions HTTPS |
| TC-SEC-02 | HTTP allowed in dev | `POST /api/servers` with `http://` URL, `MCP_ALLOW_HTTP_INSECURE=true` | HTTP 201 |
| TC-SEC-03 | HTTPS always allowed | `POST /api/servers` with `https://` URL, any env setting | HTTP 201 |
| TC-SEC-04 | Localhost HTTP in dev | `POST` with `http://localhost:3000`, insecure flag `true` | HTTP 201 |

### TR-SEC-2: Credential Handling

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-SEC-05 | Bearer token not in internal logs | Create server with `bearer_token`, check `logger_internal` output | No token value in log output |
| TC-SEC-06 | API key not in internal logs | Save LLM config with `api_key="sk-test"`, check logs | No `sk-test` in log output |
| TC-SEC-07 | MCP bearer token sent as header | Execute tool on server with `bearer_token="tok"` | `Authorization: Bearer tok` header sent to MCP server |

---

## 13. Logging Tests

### TR-LOG-1: Dual-Logger Pattern

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-LOG-01 | External logger on server create | `POST /api/servers` | `logger_external` emits `→ POST /api/servers` and `← 201 Created` |
| TC-LOG-02 | External logger on server list | `GET /api/servers` | `logger_external` emits `→ GET /api/servers` and `← 200 OK` |
| TC-LOG-03 | External logger on LLM call | OpenAI `chat_completion()` | `→ POST <url> (OpenAI chat)` and `← <status>` |
| TC-LOG-04 | External logger on MCP init | `initialize_server()` | `→ POST <url> (initialize)` and `← <status>` |
| TC-LOG-05 | Internal logger on session create | `create_session()` | `logger_internal` logs session ID |
| TC-LOG-06 | Internal logger on tool trace | `add_tool_trace()` | `logger_internal` logs tool name and success status |

---

## 14. End-to-End Flow Tests

### TR-E2E-1: Complete Chat Workflow (No Tools)

| Step | Action | Expected |
|------|--------|----------|
| 1 | `POST /api/llm/config` (Mock provider) | HTTP 200 |
| 2 | `POST /api/sessions` | HTTP 201, `session_id` returned |
| 3 | `POST /api/sessions/{id}/messages` with `{"role":"user","content":"Hello"}` | HTTP 200, `message.role=="assistant"`, content not empty |
| 4 | `GET /api/sessions/{id}/messages` | 2 messages: user + assistant |

### TR-E2E-2: Complete Chat Workflow (With Tool Execution)

| Step | Action | Expected |
|------|--------|----------|
| 1 | `POST /api/llm/config` (OpenAI mock) | HTTP 200 |
| 2 | `POST /api/servers` (mock MCP server URL) | HTTP 201 |
| 3 | `POST /api/servers/refresh-tools` (mock returns 1 tool) | `total_tools=1` |
| 4 | `POST /api/sessions` | HTTP 201 |
| 5 | `POST /api/sessions/{id}/messages` (mock LLM returns tool call, then text) | HTTP 200, `tool_executions` has 1 entry with `success=True` |
| 6 | `session_manager.get_tool_traces(id)` | 1 trace with `success=True` |

### TR-E2E-3: Server Lifecycle

| Step | Action | Expected |
|------|--------|----------|
| 1 | `GET /api/servers` | `[]` |
| 2 | `POST /api/servers` (server A) | HTTP 201 |
| 3 | `POST /api/servers` (server B) | HTTP 201 |
| 4 | `GET /api/servers` | 2 servers |
| 5 | `DELETE /api/servers/{A.id}` | HTTP 200 |
| 6 | `GET /api/servers` | 1 server (B) |
| 7 | `DELETE /api/servers/{A.id}` | HTTP 404 |

### TR-E2E-4: Tool Namespace Conflict Prevention

| Step | Action | Expected |
|------|--------|----------|
| 1 | Register `server_a` and `server_b`, both have tool named `ping` | Both accepted |
| 2 | Refresh tools | `server_a__ping` and `server_b__ping` both in registry |
| 3 | `GET /api/tools` | Both tools present with different `namespaced_id` |

---

## 15. Environment Variable Tests

### TR-ENV-1: Configuration Overrides

| Test ID | Variable | Value | Expected Behavior |
|---------|----------|-------|-------------------|
| TC-ENV-01 | `MCP_ALLOW_HTTP_INSECURE` | `"true"` | HTTP server URLs accepted |
| TC-ENV-02 | `MCP_ALLOW_HTTP_INSECURE` | `"false"` (default) | HTTP server URLs rejected |
| TC-ENV-03 | `MCP_MAX_TOOL_CALLS_PER_TURN` | `"2"` | Chat loop exits after 2 tool calls |
| TC-ENV-04 | `MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM` | `"100"` | Tool output >100 chars is truncated |
| TC-ENV-05 | `MCP_REQUEST_TIMEOUT_MS` | `"5000"` | MCP manager uses 5.0s read timeout |

---

## 16. Frontend — Chat UI Tests (`app.js`)

### TR-FE-CHAT-1: Initialization

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-CHAT-01 | Textarea auto-resize | Type multi-line input → `textarea.style.height` grows to `scrollHeight` |
| TC-FE-CHAT-02 | Send button disabled on empty | `messageInput.value = ""` → `sendBtn.disabled === true` |
| TC-FE-CHAT-03 | Send button enabled on input | Type text → `sendBtn.disabled === false` |
| TC-FE-CHAT-04 | Send button disabled while processing | `isProcessing = true` → `sendBtn.disabled === true` regardless of input |
| TC-FE-CHAT-05 | Enter key sends message | Press Enter (no Shift) → `sendMessage()` called |
| TC-FE-CHAT-06 | Shift+Enter inserts newline | Press Shift+Enter → `sendMessage()` NOT called, newline inserted |
| TC-FE-CHAT-07 | Click send button | Click `sendBtn` → `sendMessage()` called |
| TC-FE-CHAT-08 | New chat button | Click `newChatBtn` → `createNewSession()` called |

### TR-FE-CHAT-2: Session Creation (`createNewSession`)

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-CHAT-09 | No LLM config in localStorage | `localStorage.llmConfig` absent → `showError()` called with settings prompt; no `POST /api/sessions` |
| TC-FE-CHAT-10 | Successful session creation | `POST /api/sessions` returns 201 → `currentSessionId` set to returned `session_id` |
| TC-FE-CHAT-11 | Chat cleared on new session | Create session → `chatMessages.innerHTML === ''` |
| TC-FE-CHAT-12 | System message on new session | Create session → "New chat session started" message rendered |
| TC-FE-CHAT-13 | Enabled servers from localStorage | `mcpServers` in localStorage has 2 entries → both aliases sent in `enabled_servers` |
| TC-FE-CHAT-14 | API failure | `POST /api/sessions` returns 500 → `showError()` called; `currentSessionId` unchanged |

### TR-FE-CHAT-3: Send Message (`sendMessage`)

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-CHAT-15 | Empty content guard | `messageInput.value = ""` → returns immediately; no API call |
| TC-FE-CHAT-16 | isProcessing guard | `isProcessing = true` → returns immediately; no API call |
| TC-FE-CHAT-17 | syncServersToBackend called | Send message → `window.syncServersToBackend()` awaited before fetch |
| TC-FE-CHAT-18 | syncLLMConfigToBackend called | Send message → `window.syncLLMConfigToBackend()` awaited before fetch |
| TC-FE-CHAT-19 | Auto-creates session if none | `currentSessionId = null` → `createNewSession()` called; message sent in new session |
| TC-FE-CHAT-20 | User message added to UI | Send message → `addMessage('user', content)` before fetch |
| TC-FE-CHAT-21 | Input cleared after send | Send message → `messageInput.value === ''` |
| TC-FE-CHAT-22 | Loading indicator shown | Awaiting response → loading element present in DOM |
| TC-FE-CHAT-23 | Loading removed on success | API returns 200 → loading element removed |
| TC-FE-CHAT-24 | Loading removed on error | API returns 500 → loading element removed |
| TC-FE-CHAT-25 | isProcessing set during request | While awaiting → `isProcessing === true` |
| TC-FE-CHAT-26 | isProcessing cleared after response | After response settles → `isProcessing === false` (finally block) |
| TC-FE-CHAT-27 | Assistant message rendered | API returns `{message:{content:"Hi"}}` → "Hi" rendered in chat |
| TC-FE-CHAT-28 | Tool executions badge rendered | Response has 1 successful tool → `✓ tool_name` badge shown |
| TC-FE-CHAT-29 | Failed tool badge | Response has 1 failed tool → `✗ tool_name` badge with error styling |
| TC-FE-CHAT-30 | Fetch error shows message | `fetch` throws → `showError()` called |

### TR-FE-CHAT-4: Message Formatting (`formatMessageContent`)

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| TC-FE-CHAT-31 | XSS prevention | `"<script>alert(1)</script>"` | Rendered as escaped text; no script execution |
| TC-FE-CHAT-32 | Newlines → `<br>` | `"line1\nline2"` | Output contains `line1<br>line2` |
| TC-FE-CHAT-33 | Fenced code block | ` ```python\ncode\n``` ` | `<pre><code class="language-python">code</code></pre>` |
| TC-FE-CHAT-34 | Inline code | `` `var x` `` | `<code>var x</code>` |
| TC-FE-CHAT-35 | Bold `**text**` | `"**bold**"` | `<strong>bold</strong>` |
| TC-FE-CHAT-36 | Bold `__text__` | `"__bold__"` | `<strong>bold</strong>` |
| TC-FE-CHAT-37 | Italic `*text*` | `"*italic*"` | `<em>italic</em>` |
| TC-FE-CHAT-38 | Null/empty content | `null` or `""` | Returns `""` with no error |

### TR-FE-CHAT-5: Tools Sidebar (`window.loadToolsSidebar`)

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-CHAT-39 | Empty tools | `GET /api/tools` returns `[]` → empty-state message rendered |
| TC-FE-CHAT-40 | Tools grouped by server | Tools from 2 servers → each group rendered separately |
| TC-FE-CHAT-41 | Parameter count shown | Tool with 2 properties in schema → "2 parameters" label visible |
| TC-FE-CHAT-42 | No param label for 0 params | Tool has no `properties` → no parameter label |
| TC-FE-CHAT-43 | Description shown | Tool has `description` → description text in tool item |
| TC-FE-CHAT-44 | API error | `GET /api/tools` returns 500 → error message rendered in sidebar |
| TC-FE-CHAT-45 | Refresh button triggers reload | Click `refreshToolsSidebarBtn` → `loadToolsSidebar()` called |
| TC-FE-CHAT-46 | Sidebar loaded on page init | `DOMContentLoaded` fires → `loadToolsSidebar()` called automatically |

---

## 17. Frontend — Settings Modal Tests (`settings.js`)

### TR-FE-SET-1: Modal Lifecycle

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-SET-01 | Open modal | Click `settingsBtn` → `settingsModal` has `"active"` class |
| TC-FE-SET-02 | Close via button | Click `closeSettings` → `"active"` removed from modal |
| TC-FE-SET-03 | Close via backdrop | Click modal backdrop → `"active"` removed |
| TC-FE-SET-04 | loadToolsSidebar on button close | Close via button → `window.loadToolsSidebar()` called |
| TC-FE-SET-05 | loadToolsSidebar on backdrop close | Click backdrop → `window.loadToolsSidebar()` called |

### TR-FE-SET-2: Tab Switching (`switchTab`)

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-SET-06 | Switch to Servers tab | Click Servers tab button → button has `"active"` class; Servers content has `"active"` |
| TC-FE-SET-07 | Switch to LLM tab | Click LLM tab → only LLM content has `"active"` |
| TC-FE-SET-08 | Switch to Tools tab | Click Tools tab → only Tools content has `"active"` |
| TC-FE-SET-09 | Previous tab deactivated | Servers → LLM → Servers button loses `"active"` class |

### TR-FE-SET-3: Auth Type Toggle

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-SET-10 | `none` selected | Both `bearerTokenGroup` and `apiKeyGroup` hidden |
| TC-FE-SET-11 | `bearer` selected | `bearerTokenGroup` `display:block`; `apiKeyGroup` hidden |
| TC-FE-SET-12 | `api_key` selected | `apiKeyGroup` `display:block`; `bearerTokenGroup` hidden |

### TR-FE-SET-4: LLM Provider Toggle

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-SET-13 | OpenAI selected | `llmApiKeyGroup` visible |
| TC-FE-SET-14 | Ollama selected | `llmApiKeyGroup` hidden |
| TC-FE-SET-15 | Mock selected | `llmApiKeyGroup` hidden |
| TC-FE-SET-16 | Default Ollama base URL | Select `"ollama"` with empty URL field → pre-filled with `http://127.0.0.1:11434` |
| TC-FE-SET-17 | Default OpenAI base URL | Select `"openai"` with empty URL field → pre-filled with `https://api.openai.com` |
| TC-FE-SET-18 | No override if URL set | Select provider with existing URL → existing value preserved |

### TR-FE-SET-5: Add Server (`handleAddServer`)

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-SET-19 | Successful add | `POST /api/servers` 201 → server appended to `localStorage.mcpServers`; form reset; success shown |
| TC-FE-SET-20 | API error (409) | `POST /api/servers` 409 → `showFormError()` called; localStorage NOT updated |
| TC-FE-SET-21 | Form data collected correctly | Alias "svc", URL "https://x" → POST body has `alias:"svc"`, `base_url:"https://x"`, `auth_type`, `bearer_token`, `api_key` |
| TC-FE-SET-22 | Empty bearer token → null | Leave bearer token blank → `bearer_token: null` in POST body |
| TC-FE-SET-23 | Empty API key → null | Leave API key blank → `api_key: null` in POST body |

### TR-FE-SET-6: Render Servers List (`renderServersList`)

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-SET-24 | Empty list | `localStorage.mcpServers = []` → empty-state text rendered |
| TC-FE-SET-25 | Server item rendered | 1 server → alias, URL, and Delete button all present |
| TC-FE-SET-26 | Multiple servers | 3 servers → 3 items rendered |

### TR-FE-SET-7: Delete Server (`deleteServer`)

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-SET-27 | Confirm dialog shown | Click Delete → `confirm()` called |
| TC-FE-SET-28 | Cancel aborts delete | User cancels confirm → no API call; localStorage unchanged |
| TC-FE-SET-29 | Successful delete | Confirm + DELETE 200 → server removed from `localStorage.mcpServers`; list re-rendered |
| TC-FE-SET-30 | API error | DELETE 500 → `alert()` called; localStorage unchanged |
| TC-FE-SET-31 | Correct server removed | Delete B from [A, B, C] → localStorage contains [A, C] |

### TR-FE-SET-8: Refresh Tools (`handleRefreshTools`)

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-SET-32 | Button disabled during refresh | Click → `refreshToolsBtn.disabled === true` while awaiting |
| TC-FE-SET-33 | Button text changes | Click → text becomes `"🔄 Refreshing..."` |
| TC-FE-SET-34 | Button restored on success | Refresh completes → `disabled === false`; original text restored |
| TC-FE-SET-35 | Button restored on error | Refresh fails → `disabled === false`; original text restored (finally block) |
| TC-FE-SET-36 | syncServersToBackend first | Click → `syncServersToBackend()` awaited before `POST /api/servers/refresh-tools` |
| TC-FE-SET-37 | Success message with tools | `total_tools=3`, `servers_refreshed=2` → "Discovered 3 tools from 2 servers" |
| TC-FE-SET-38 | Success message no tools | `total_tools=0` → message about no tools |
| TC-FE-SET-39 | Errors alerted | `result.errors` non-empty → `alert()` called with error list |
| TC-FE-SET-40 | Sidebar refreshed after refresh | Success → `window.loadToolsSidebar()` called |

### TR-FE-SET-9: Render Tools List (`renderToolsList`)

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-SET-41 | Empty tools | `tools = []` → empty-state message rendered |
| TC-FE-SET-42 | Grouped by server | Tools from 2 servers → `<h4>server_alias</h4>` per server |
| TC-FE-SET-43 | Count in heading | Server "svc" has 3 tools → heading shows count `3` |
| TC-FE-SET-44 | Tool name and description | Tool `{name:"ping",description:"Check"}` → both rendered |

### TR-FE-SET-10: Save LLM Config (`handleSaveLLMConfig`)

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-SET-45 | Successful save | `POST /api/llm/config` 200 → saved to `localStorage.llmConfig`; success message |
| TC-FE-SET-46 | API error | `POST /api/llm/config` 422 → `showFormError()` called; localStorage NOT updated |
| TC-FE-SET-47 | Form data collected | Fill all fields → POST body contains `provider`, `model`, `base_url`, `api_key`, `temperature` |
| TC-FE-SET-48 | Empty API key → null | Leave API key blank → `api_key: null` |
| TC-FE-SET-49 | Temperature as float | Input `"0.5"` → `temperature: 0.5` (number, not string) |

### TR-FE-SET-11: Load LLM Config (`loadLLMConfig`)

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-SET-50 | No config in localStorage | Absent → form fields unchanged; no error |
| TC-FE-SET-51 | Config restored | Config in localStorage → all form fields populated |
| TC-FE-SET-52 | Provider change event fired | Config loaded → `llmProviderSelect` dispatches `change` event |
| TC-FE-SET-53 | `null` api_key → empty string | `config.api_key = null` → API key field set to `""` not `"null"` |

---

## 18. Frontend — localStorage Persistence Tests

### TR-FE-LS-1: Server Persistence

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-LS-01 | Server saved on add | `handleAddServer` succeeds → `localStorage.mcpServers` contains new server |
| TC-FE-LS-02 | Server removed on delete | `deleteServer` succeeds → server absent from `localStorage.mcpServers` |
| TC-FE-LS-03 | Multiple servers persisted | Add A then B → localStorage has both |
| TC-FE-LS-04 | renderServersList reads localStorage | Call `renderServersList()` → renders current localStorage state |

### TR-FE-LS-2: LLM Config Persistence

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-LS-05 | Config saved on save | `handleSaveLLMConfig` succeeds → `localStorage.llmConfig` has saved config |
| TC-FE-LS-06 | Config overwritten on re-save | Save twice → only latest config stored |
| TC-FE-LS-07 | Config read in createNewSession | Config in localStorage → included in `POST /api/sessions` body |

### TR-FE-LS-3: Backend Sync on Reload

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-LS-08 | Sync skipped when no servers | `localStorage.mcpServers = []` → no `POST /api/servers` calls |
| TC-FE-LS-09 | Each server POSTed | 2 servers in localStorage → 2 `POST /api/servers` requests made |
| TC-FE-LS-10 | 409 Conflict accepted | Backend returns 409 → no error thrown; sync continues |
| TC-FE-LS-11 | Network error tolerated | One server POST throws → remaining servers still synced |
| TC-FE-LS-12 | LLM sync skipped when absent | `localStorage.llmConfig = null` → no `POST /api/llm/config` |
| TC-FE-LS-13 | LLM config synced before send | `sendMessage()` called → `syncLLMConfigToBackend()` awaited first |
| TC-FE-LS-14 | `loadSettings()` calls both syncs | `DOMContentLoaded` → `syncServersToBackend()` and `syncLLMConfigToBackend()` both called |

---

## 19. Frontend — Cross-Component Integration Tests

| Test ID | Scenario | Expected |
|---------|----------|----------|
| TC-FE-INT-01 | Settings close refreshes sidebar | Add server in settings, close modal → tools sidebar reloaded |
| TC-FE-INT-02 | Refresh Tools updates both views | Click Refresh Tools → tools tab list AND sidebar both updated |
| TC-FE-INT-03 | New session auto-created on first send | Send message with no session → session created transparently; message delivered |
| TC-FE-INT-04 | Missing LLM config blocks new session | Remove `localStorage.llmConfig`, click New Chat → error shown; no session created |
| TC-FE-INT-05 | Page load syncs before chat | Open page, send message immediately → backend has latest server + LLM state before message |

---

## 20. Test File Structure

```
tests/
├── conftest.py                        # Shared fixtures (test_client, mocks)
├── unit/
│   ├── test_models.py                 # TR-MODEL-* (Pydantic validation)
│   ├── test_llm_client.py             # TR-LLMC-* (OpenAI, Ollama, Mock, Factory)
│   ├── test_session_manager.py        # TR-SESS-* + TR-FMT-*
│   └── test_mcp_manager.py            # TR-MCP-* (init, discovery, execution)
├── integration/
│   ├── test_health.py                 # TR-HC-*
│   ├── test_servers_api.py            # TR-SRV-*
│   ├── test_tools_api.py              # TR-TOOL-*
│   ├── test_llm_config_api.py         # TR-LLM-*
│   └── test_chat_api.py               # TR-CHAT-* + TR-SESS-1
├── security/
│   └── test_security.py               # TR-SEC-* + TR-LOG-*
├── e2e/
│   └── test_workflows.py              # TR-E2E-*
└── frontend/
    ├── conftest.js                    # jsdom setup, localStorage mock, fetch mock
    ├── test_chat_ui.test.js           # TR-FE-CHAT-* (app.js)
    ├── test_settings_modal.test.js    # TR-FE-SET-* (settings.js)
    ├── test_localstorage.test.js      # TR-FE-LS-*
    └── test_frontend_integration.test.js  # TR-FE-INT-*
```

---

## 21. Test Tooling

### Backend

| Tool | Purpose |
|------|---------|
| `pytest` | Test runner |
| `pytest-asyncio` | Async test support |
| `httpx` | Test client (`AsyncClient` with ASGI transport) |
| `pytest-mock` / `unittest.mock` | Mock MCP and LLM HTTP calls |
| `respx` | HTTP mock for `httpx` calls in MCP manager and LLM clients |
| `pytest-cov` | Code coverage reporting |

### Frontend

| Tool | Purpose |
|------|----------|
| `jest` | JavaScript test runner |
| `jsdom` | Browser DOM emulation in Node.js |
| `@testing-library/jest-dom` | DOM assertion matchers |
| `jest-fetch-mock` | Mock global `fetch` API |
| `localStorage` mock (jest) | In-memory localStorage for tests |

### Install

```bash
# Backend
pip install pytest pytest-asyncio httpx respx pytest-mock pytest-cov

# Frontend
npm install --save-dev jest jest-environment-jsdom @testing-library/jest-dom jest-fetch-mock
```

### Run

```bash
# Backend — all tests
pytest tests/ -v

# Backend — with coverage
pytest tests/ --cov=backend --cov-report=term-missing

# Backend — specific layer
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/e2e/ -v

# Frontend
npx jest tests/frontend/ --verbose

# Frontend — with coverage
npx jest tests/frontend/ --coverage
```

---

## 22. Coverage Targets

### Backend

| Module | Target Coverage |
|--------|-----------------|
| `backend/models.py` | 95% |
| `backend/llm_client.py` | 90% |
| `backend/session_manager.py` | 95% |
| `backend/mcp_manager.py` | 85% |
| `backend/main.py` (endpoints) | 90% |
| Backend overall | ≥ 85% |

### Frontend

| Module | Target Coverage |
|--------|-----------------|
| `backend/static/app.js` | 85% |
| `backend/static/settings.js` | 85% |
| Frontend overall | ≥ 80% |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-10 | AI Assistant | Initial test requirements for v0.2.0-jsonrpc (backend only) |
| 1.1 | 2026-03-10 | AI Assistant | Added frontend test requirements (Sections 16–19); updated file structure, tooling, coverage targets |

**Related Documents**

| Document | Relationship |
|----------|-------------|
| REQUIREMENTS.md | Functional requirements these tests validate |
| HLD.md | Architecture these tests cover |
| ENTERPRISE_GATEWAY_REQUIREMENTS.md §8 | Enterprise feature test cases (AT-EG-01 to AT-EG-18) |
