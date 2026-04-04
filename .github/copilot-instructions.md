# MCP Client Web - AI Coding Agent Instructions

## Project Overview
Browser-based MCP (Model Context Protocol) client with FastAPI backend and vanilla JavaScript frontend. Enables chat-based interaction with MCP servers through OpenAI/Ollama using JSON-RPC 2.0 protocol.

**Architecture**: FastAPI backend + SPA frontend | Dual storage (in-memory backend + localStorage) | No build step required

## Critical Workflows

### Development Setup
```bash
# Backend
python -m venv venv && source venv/bin/activate
pip install fastapi==0.115.0 uvicorn[standard]==0.30.6 httpx==0.27.0 pydantic==2.8.2
uvicorn backend.main:app --reload --port 8000

# Environment variables (defaults in code)
export MCP_ALLOW_HTTP_INSECURE=true  # Dev only
export OPENAI_API_KEY=sk-...
export OLLAMA_BASE_URL=http://127.0.0.1:11434

# Multi-machine deployment example
export OPENAI_BASE_URL=https://api.openai.com
export OLLAMA_BASE_URL=http://192.168.1.50:11434  # Remote Ollama server
# MCP servers configured via UI with URLs like:
# - https://mcp-server-1.internal:8080 (production)
# - http://192.168.1.100:3000 (dev with insecure flag)
```

### Testing
Debug pages at `backend/static/`:
- `debug-servers.html` - Server CRUD operations
- `mcp-server-test.html` - MCP protocol integration
- `llm-config-test.html` - LLM provider testing

## Key Architecture Decisions

### Dual-Storage Pattern
**Why**: Offline resilience + stateful sessions without database complexity
- **Backend** (in-memory): Session state, message history, tool execution traces
- **Frontend** (localStorage): Server configs, LLM settings (survives reload)
- **Sync point**: On save/load operations via `/api/servers` endpoints

### JSON-RPC 2.0 Protocol
MCP servers communicate exclusively via JSON-RPC 2.0:
- **Initialization**: Required `initialize()` handshake with protocol version "2024-11-05"
- **Tool operations**: `tools/list` (discover) and `tools/call` (execute)
- **Tool IDs**: Namespaced as `{server_alias}__{tool_name}` to prevent conflicts
- **Client info**: `{"name": "mcp-client-web", "version": "1.0"}` sent in initialize

### Tool Execution Flow
```
User message → LLM + tools → Tool calls → Execute on MCP servers → 
Results to LLM → Next turn (max 8 tool calls/turn)
```
- **OpenAI format**: Uses `tool_call_id` in responses
- **Ollama format**: Uses `tool_name` instead (adapt messaging)
- **Truncation**: Results >12K chars truncated before sending to LLM

### Adaptive Query Learning (AQL)
**Canonical docs**:
- `docs/AQL-ADAPTIVE-QUERY-LEARNING-REQUIREMENTS.md`
- `docs/AQL-ADAPTIVE-QUERY-LEARNING-HLD.md`
- `docs/AQL-ADAPTIVE-QUERY-LEARNING-IMPLEMENTATION-SPEC.md`
- `docs/AQL-P1-SCHEMA-CONFIG-STORE-REQUIREMENTS.md`
- `docs/AQL-P1-SCHEMA-CONFIG-STORE-HLD.md`
- `docs/AQL-P1-SCHEMA-CONFIG-STORE-IMPLEMENTATION-SPEC.md`
- `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-REQUIREMENTS.md`
- `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-HLD.md`
- `docs/AQL-P2-PASSIVE-QUALITY-RECORDING-IMPLEMENTATION-SPEC.md`
- `docs/AQL-P3-CORRECTION-PATCHING-REQUIREMENTS.md`
- `docs/AQL-P3-CORRECTION-PATCHING-HLD.md`
- `docs/AQL-P3-CORRECTION-PATCHING-IMPLEMENTATION-SPEC.md`

**AQL requirement summary**:
- Additive only: never break current chat, routing, cache, or admin behavior.
- Disabled by default behind `enable_adaptive_learning` / `AQL_ENABLE`.
- Reuse existing Milvus infrastructure only; no new DB, queue, or service.
- Write quality history asynchronously after response return; never add visible latency.
- Treat learned tool affinity as a soft prior that narrows the tool list; do not bypass the LLM.
- Surface freshness recommendations for operators; never auto-edit `tool_cache_freshness_keywords`.

**AQL HLD summary**:
- Persist execution feedback in Milvus collection `mcp_client_tool_execution_quality_v1` (logical key `tool_execution_quality`).
- Feed quality history into four later decision points: affinity routing, freshness-candidate reporting, split-phase chunk reorder, and admin quality reporting.
- Exclude corrected turns from future affinity routing.
- Degrade silently to existing routing when Milvus is unavailable, AQL is disabled, or confidence/record thresholds are not met.

**AQL development approach**:
1. Land passive plumbing before behavior changes.
2. Implement phases in order: Phase 1 schema/config/store → Phase 2 passive quality recording → Phase 3 correction patching → Phase 4 admin reporting → Phase 5 affinity lookup → Phase 6 routing integration → Phase 7 chunk reordering.
3. Before implementing any phase, create or update that phase's own requirements doc, HLD doc, and implementation spec doc. Do not start Phase 2+ code from only the parent AQL docs when the repo is following a per-phase documentation workflow.
4. Follow the established naming pattern for per-phase docs, e.g. `docs/AQL-P1-SCHEMA-CONFIG-STORE-*.md`, and create the matching Phase 2/3/etc. triplet before code changes.
5. After the phase docs are in place, implement the phase code in the repo before moving on to later phases.
6. After implementation, develop or update the phase's focused test coverage so the new behavior is explicitly validated at the unit/integration level where appropriate.
7. Execute the full phase validation sequence in order: focused tests first, then broader integration coverage if applicable, then the entire backend regression suite before marking the phase complete.
8. Keep Phase 1 non-behavioral: config, models, collection schema, row counts, snapshot visibility, and cleanup readiness only.
9. Extend existing files instead of adding parallel AQL subsystems: `backend/models.py`, `backend/milvus_store.py`, `backend/memory_service.py`, `backend/main.py`.
10. Preserve degraded-mode behavior: log warnings on AQL failures and suppress them from end users.

## Project-Specific Conventions

### OpenAPI Spec-Driven Development
**Source of truth**: Pydantic models → FastAPI generates OpenAPI spec → Implementation follows spec

**Always include in models**:
```python
from pydantic import BaseModel, Field

class ServerConfig(BaseModel):
    """MCP server configuration"""
    server_id: str = Field(..., description="Unique server identifier (UUID)")
    alias: str = Field(..., min_length=1, max_length=64, 
                       description="Human-readable server name")
    base_url: str = Field(..., description="MCP server base URL",
                         pattern=r"^https?://")
    
    class Config:
        json_schema_extra = {
            "example": {
                "server_id": "550e8400-e29b-41d4-a716-446655440000",
                "alias": "weather_api",
                "base_url": "http://192.168.1.100:3000"
            }
        }
```

**Always document endpoints**:
```python
@app.get(
    "/api/servers",
    response_model=List[ServerConfig],
    tags=["MCP Servers"],
    summary="List all MCP servers",
    responses={
        200: {"description": "List of configured servers"},
        500: {"description": "Internal server error"}
    }
)
async def list_servers() -> List[ServerConfig]:
    """Retrieve all configured MCP servers from backend storage"""
```

**Verify spec**: Check `/docs` after every endpoint addition to ensure OpenAPI compliance

### Dual-Logger Pattern
```python
logger_internal = logging.getLogger("mcp_client.internal")  # App flow
logger_external = logging.getLogger("mcp_client.external")  # API calls
```
- External logs use directional arrows: `→ POST /api/servers` (request), `← 201 Created` (response)
- Internal logs track state changes and business logic

### Error Handling Granularity
Timeout configuration uses 4-level granularity:
```python
timeout = httpx.Timeout(
    connect=5.0,   # Connection establishment
    read=20.0,     # Waiting for response
    write=5.0,     # Sending request
    pool=5.0       # Pool acquisition
)
```
**Never use simple integer timeouts** - always use httpx.Timeout object

### AQL Schema and Config Conventions
- Add AQL config fields to `MilvusConfig` first, then pass them through `_initialize_memory_service()` into `MemoryServiceConfig`.
- Keep AQL defaults normalized in model helpers so runtime code does not branch on missing weights or blank correction patterns.
- Extend existing row-count, snapshot, and expiry-cleanup helpers when adding new Milvus collections.
- For Phase 1-style plumbing work, do not add route-selection logic, post-response writers, or new endpoint behavior in the same patch unless the phase explicitly requires it.
- New AQL admin response shapes must remain OpenAPI-friendly and additive.

### AQL Phase Documentation Discipline
- Treat each AQL phase as a doc-backed mini-project: requirements → HLD → implementation spec → implementation → test development → focused validation → full test execution.
- For Phase 2 and later, do not skip the phase-specific docs even if the parent AQL docs already describe the behavior at a high level.
- When a phase is already partially implemented without its own docs, reconcile by backfilling the missing phase docs before continuing to the next phase.
- Do not treat a phase as complete after docs alone; the expected execution order is phase docs, code implementation, test updates/additions, focused test runs, and then full regression execution.
- Keep the phase docs aligned with the actual file-level plan so implementation and GitHub issue updates reference the same scope boundaries.

### Frontend Emoji Logging
Browser console uses emoji prefixes for categorization:
- `⚙️` Settings operations
- `🔧` Tool discovery/execution  
- `💬` Chat/messaging
- `🔌` API requests

## Critical Integration Points

### MCP Server Communication
**JSON-RPC initialization** (required before tool operations):
```json
POST /rpc
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "clientInfo": {"name": "mcp-client-web", "version": "1.0"}
  }
}
```

**Tool schema canonicalization**: Parse JSON-RPC tool schemas into internal format with `namespaced_id`, `server_alias`, `name`, `description`, `parameters`

### LLM Provider Adapters
OpenAI and Ollama have different message formats for tool results:
```python
# OpenAI
{"role": "tool", "tool_call_id": "call_123", "content": "result"}

# Ollama  
{"role": "tool", "content": "result"}  # No tool_call_id
```
**Always check provider type** when formatting tool result messages

### AQL Routing Order
When later AQL phases are implemented, keep this decision order intact:
1. Direct single-tool route (existing bypass path)
2. Existing memory/tool-cache-assisted route
3. AQL affinity route when enabled and sufficiently confident
4. Existing LLM fallback / split-phase selection

Affinity routing may reduce the offered tool set, but it must not replace direct-route behavior or bypass the LLM selection call.

### Security Constraints
- **HTTPS enforcement**: Reject `http://` MCP server URLs unless `MCP_ALLOW_HTTP_INSECURE=true`
- **Credential masking**: Never log API keys/tokens (use `type="password"` in forms)
- **localStorage caveat**: Acknowledge security trade-offs (plaintext storage) in docs
- **Network accessibility**: Client must have network routes to both MCP and LLM servers (handle cross-machine deployments)

## File Structure Patterns

### Backend Layout
```
backend/
├── main.py              # FastAPI app, CORS, static files
├── models.py            # Pydantic schemas (ServerConfig, LLMConfig, etc.)
├── mcp_manager.py       # MCP protocol adapters, tool execution
├── llm_client.py        # OpenAI/Ollama/Mock provider implementations
├── session_manager.py   # Session CRUD, message history
└── static/
    ├── index.html       # Main SPA
    ├── app.js           # Chat UI logic
    ├── settings.js      # Settings modal (tabbed: Servers, LLM, Tools)
    └── debug-*.html     # Test utilities
```

### State Management
- **No framework**: Use plain objects + localStorage helpers
- **Settings modal state**: Keep modal open during multi-step ops (don't close on save)
- **Tab persistence**: Remember active tab in settings modal across opens

## Common Pitfalls

1. **Session ID confusion**: Sessions are backend-only (lost on reload). Don't store in localStorage.
2. **Tool ID format**: Always use `server_alias__tool_name`, never just `tool_name`
3. **Tool call limits**: Respect `MCP_MAX_TOOL_CALLS_PER_TURN=8` to prevent infinite loops
4. **Async/await**: All MCP/LLM calls are async - use `httpx.AsyncClient`, not sync client
5. **CORS in production**: Disable permissive CORS, add proper origin whitelist
6. **Network timeouts**: In multi-machine setups, configure timeouts generously for network latency
7. **URL validation**: Support both `localhost`, LAN IPs (`192.168.x.x`), and domain names in server configs

## Environment Variables Reference
| Variable | Default | Purpose |
|----------|---------|---------|
| `MCP_ALLOW_HTTP_INSECURE` | `false` | Allow HTTP MCP servers (dev only) |
| `MCP_REQUEST_TIMEOUT_MS` | `20000` | Default request timeout |
| `MCP_MAX_TOOL_CALLS_PER_TURN` | `8` | Max tool executions per LLM turn |
| `MCP_MAX_RESULT_PREVIEW_CHARS` | `4000` | Result preview truncation |
| `MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM` | `12000` | Max tool output sent to LLM |
| `AQL_ENABLE` | `false` | Enable Adaptive Query Learning plumbing and later routing features |
| `AQL_QUALITY_RETENTION_DAYS` | `30` | Retention window for AQL quality-history records |
| `AQL_MIN_RECORDS` | `20` | Minimum quality-history records before affinity routing can activate |
| `AQL_AFFINITY_THRESHOLD` | `0.65` | Minimum confidence required to apply affinity routing |
| `OPENAI_API_KEY` | - | OpenAI authentication |
| `OPENAI_BASE_URL` | `https://api.openai.com` | OpenAI endpoint |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |

## OpenAPI Development Workflow

1. **Define Model First**: Create Pydantic model with Field descriptions and examples
2. **Add Endpoint**: Use full type hints, response_model, tags, and summary
3. **Document**: Add docstring and response codes
4. **Verify Spec**: Check `/docs` UI shows complete documentation
5. **Implement Logic**: Write endpoint code following model contracts
6. **Test**: Validate against OpenAPI schema

**Access API Docs**:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## When Implementing Features

### Adding MCP Server Support
1. Update `mcp_manager.py` JSON-RPC handlers
2. Ensure proper `initialize()` handshake sequence
3. Test with `mcp-server-test.html` debug page
4. Verify tool schema parsing for new server types

### Adding LLM Provider
1. Create provider class in `llm_client.py` implementing base interface
2. Add provider-specific message formatting (especially tool results)
3. Update `settings.js` provider selection dropdown
4. Add provider config to `LLMConfig` Pydantic model
5. Test tool execution workflow end-to-end

### Modifying Tool Execution
- Maintain JSON-RPC 2.0 message format compliance
- Preserve trace events for debugging (logged to session)
- Update result truncation logic if changing size limits
- Test with slow/failing tools (timeout handling)
- Handle JSON-RPC error responses with proper error codes

### Implementing Adaptive Query Learning
1. Start from the AQL requirements/HLD/spec docs and honor phase boundaries.
2. Use `tool_execution_quality` as the sole Milvus collection for learned execution feedback.
3. Record correction signals with regex heuristics only; do not add an LLM call for correction detection.
4. Keep affinity routing confidence-gated and domain-aware.
5. Surface freshness candidates through admin APIs for human review instead of auto-mutating config.
6. Test additive behavior carefully so existing direct-route, split-phase, and memory-route flows stay green.

## Deployment Patterns

### Multi-Machine Configuration
**Scenario**: MCP server on machine A, LLM on machine B, client on machine C
- **Backend**: Set `OLLAMA_BASE_URL` or `OPENAI_BASE_URL` to point to machine B
- **MCP servers**: Add via UI with machine A's IP/hostname + port
- **Network**: Ensure firewall rules allow traffic between machines
- **Testing**: Use debug pages with explicit URLs before configuring in UI

### Network Troubleshooting
```bash
# Test MCP server connectivity
curl -v http://192.168.1.100:3000/health

# Test LLM server connectivity  
curl -v http://192.168.1.50:11434/api/tags

# Check from backend server
httpx.get("http://mcp-server-ip:port/health", timeout=5.0)
```

## GitHub CLI Execution Reminders

When updating GitHub issues, milestones, or labels from the terminal, prefer **single-command `gh` invocations** or **file-based request bodies**.

### Safe Patterns
- Use `gh issue view <n> --json ...` to inspect state before editing.
- Use `gh issue edit <n> --body-file /tmp/file.md` for large body updates.
- Use `gh api repos/<owner>/<repo>/issues/<n> --method PATCH --input /tmp/payload.json` for structured API updates.
- Generate temp files first, then call `gh` separately.
- Re-read the issue after editing to confirm the intended body/checklist state.

### Avoid
- Avoid shell heredocs for long inline Python or long Markdown bodies during `gh` operations.
- Avoid nested quoting chains that combine Python, Markdown, and shell interpolation in one command.
- Avoid editing issue bodies blind; always fetch the current body first so earlier spec content is preserved.

### Known Failure Mode
- In this repo/session, multiline heredoc-based `python - <<'PY'` commands caused the zsh terminal to enter a malformed heredoc state and garble the command stream instead of executing cleanly.
- If a terminal enters a heredoc prompt unexpectedly, cancel it immediately and switch to a safer pattern (`create temp file` → `gh issue edit --body-file` or `gh api --input`).

### Recommended Workflow For Issue Updates
1. Read the current issue body with `gh issue view`.
2. Build the replacement body in a temp Markdown file.
3. Apply the update with `gh issue edit --body-file` or `gh api --input`.
4. Re-fetch the issue and verify exact checklist/body changes.
5. If terminal behavior looks unstable, use a subagent or direct GitHub API call instead of retrying the same heredoc approach.

## Quick Reference
- **Version**: 0.2.0-jsonrpc
- **Python**: 3.8+ required
- **No database**: All storage is in-memory (backend) + localStorage (frontend)
- **No auth**: Single-user application
- **Deployment**: Supports distributed multi-machine setups
- **Docs**: See REQUIREMENTS.md for full functional/non-functional requirements
