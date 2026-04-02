# MCP Client Web

Browser-based chat interface for Model Context Protocol (MCP) servers. Inspired by LibreChat, this application enables seamless interaction with AI tools through JSON-RPC 2.0 protocol.

## Features

- 🎨 **LibreChat-inspired UI** - Clean, modern chat interface
- 🔧 **MCP Server Management** - Connect to multiple MCP servers (local or remote)
- 🤖 **Multi-LLM Support** - OpenAI, Ollama, and Mock providers
- 🌐 **Distributed Architecture** - MCP servers, LLM, and client on different machines
- 📡 **JSON-RPC 2.0** - Standard protocol communication
- 💾 **Dual Storage** - In-memory sessions + localStorage persistence
- 📚 **OpenAPI 3.0** - Auto-generated interactive documentation

## Quick Start

### Prerequisites

- Python 3.8+
- Modern web browser (Chrome, Firefox, Safari, Edge)
- MCP server (local or remote)
- LLM provider (OpenAI API key or Ollama instance)

### Installation

```bash
# Clone repository
git clone <repository-url>
cd mcp_client

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your configuration
```

### Configuration

Edit `.env` file:

```bash
# SECURITY: Only enable for development with HTTP MCP servers
MCP_ALLOW_HTTP_INSECURE=false  # Set to true for local dev only

# Configure LLM provider
OPENAI_API_KEY=sk-your-key-here
# OR
OLLAMA_BASE_URL=http://192.168.1.50:11434
```

### Run the Application

```bash
python -m backend
```

Or with uvicorn:

```bash
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Run both commands from the repository root (`mcp_client`).

Using `python -m uvicorn` ensures the server starts with the same interpreter as the active virtual environment.

### Access the Application

- **Frontend**: http://localhost:8000
- **API Docs (Swagger)**: http://localhost:8000/docs
- **API Docs (ReDoc)**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## Usage

### 1. Configure MCP Servers

1. Click **Settings** button in header
2. Navigate to **MCP Servers** tab
3. Add server:
   - **Alias**: `weather_api`
   - **Base URL**: `http://192.168.1.100:3000`
   - **Auth**: Bearer token (if required)
4. Click **Add Server**
5. Click **Refresh Tools** to discover available tools

### 2. Configure LLM Provider

1. Navigate to **LLM** tab
2. Select provider (OpenAI/Ollama)
3. Enter model name (e.g., `llama3.1` or `gpt-4`)
4. Add credentials if required
5. Click **Save Configuration**

### 3. Start Chatting

1. Click **New Chat** to start session
2. Type message: "What's the weather in NYC?"
3. Press **Enter** or click **Send**
4. Watch tool execution and results

## Multi-Machine Deployment

Example setup with distributed components:

```
┌─────────────────┐     ┌─────────────────┐
│  MCP Server A   │     │  MCP Server B   │
│  192.168.1.100  │     │  192.168.1.101  │
│  Port: 3000     │     │  Port: 3001     │
└─────────────────┘     └─────────────────┘
        ↑                       ↑
        │    JSON-RPC 2.0       │
        └───────────┬───────────┘
                    │
        ┌───────────────────────┐
        │  Backend Server       │
        │  192.168.1.50:8000    │
        └───────────────────────┘
                    │
                    ↓
        ┌───────────────────────┐
        │  Ollama/OpenAI        │
        │  192.168.1.60:11434   │
        └───────────────────────┘
```

### Network Configuration

1. **Firewall**: Allow TCP traffic between machines
2. **MCP Servers**: Configure via UI with `http://IP:PORT`
3. **LLM**: Set `OLLAMA_BASE_URL` or `OPENAI_BASE_URL` in `.env`
4. **Testing**: Use `/health` endpoint to verify connectivity

## Development

### Project Structure

```
mcp_client/
├── backend/
│   ├── main.py              # FastAPI app
│   ├── models.py            # Pydantic models (OpenAPI source)
│   ├── mcp_manager.py       # MCP JSON-RPC client
│   ├── llm_client.py        # LLM adapters
│   ├── session_manager.py   # Session state
│   └── static/
│       ├── index.html       # Main UI
│       ├── app.js           # Chat logic
│       └── settings.js      # Settings modal
├── requirements.txt
├── .env.example
├── REQUIREMENTS.md          # Functional requirements
├── HLD.md                   # High-level design
└── .github/
    └── copilot-instructions.md  # AI coding guidelines
```

### OpenAPI Spec-Driven Development

1. Define Pydantic models in `models.py`
2. Add endpoints with full type hints
3. Verify at `/docs` (auto-generated)
4. Implement logic following models
5. Test against OpenAPI schema

For a quick repo-specific explanation of when to use Pydantic vs SQLAlchemy, see `docs/PYDANTIC-VS-SQLALCHEMY-IN-THIS-REPO.md`.

### Running Tests

```bash
# Run everything from the repo root
make test

# Run backend tests only
make test-backend

# Run frontend tests only
make test-frontend
```

Frontend tests use Jest from [tests/frontend](tests/frontend), so install its dependencies once if needed:

```bash
cd tests/frontend && npm install
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_ALLOW_HTTP_INSECURE` | `false` | Allow HTTP MCP servers (dev only) |
| `MCP_REQUEST_TIMEOUT_MS` | `20000` | Request timeout (milliseconds) |
| `MCP_MAX_TOOL_CALLS_PER_TURN` | `8` | Max tool executions per turn |
| `MCP_MAX_TOOLS_PER_REQUEST` | `128` | Max tools sent to the LLM per request (Azure OpenAI hard limit is 128) |
| `MCP_ENABLE_LLM_MODE_CLASSIFIER` | `false` | Enable a tiny no-tools LLM pass to resolve ambiguous request-mode routing (can also be overridden per saved LLM config in Settings) |
| `MCP_LLM_MODE_CLASSIFIER_MIN_CONFIDENCE` | `0.60` | Heuristic-confidence threshold below which the tiny LLM classifier is consulted |
| `MCP_LLM_MODE_CLASSIFIER_MIN_SCORE_GAP` | `3` | Heuristic score-gap threshold below which the tiny LLM classifier is consulted |
| `MCP_LLM_MODE_CLASSIFIER_ACCEPT_CONFIDENCE` | `0.55` | Minimum tiny-classifier confidence required before overriding heuristic routing |
| `MCP_LLM_MODE_CLASSIFIER_MAX_TOKENS` | `96` | Max tokens reserved for the tiny classifier response |
| `OPENAI_API_KEY` | - | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com` | OpenAI endpoint |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |

## Memory-Augmented Retrieval (Optional)

The application can optionally index your codebase and documentation into a Milvus vector store and use retrieved context to improve LLM responses.  All memory features are **disabled by default** — the chat flow is unchanged when they are off.

You can configure these runtime Milvus settings directly in Settings → Milvus Config, alongside the existing MCP Servers and LLM Config tabs.

For day-to-day usage guidance, prompting tips, and Milvus-specific examples, see [docs/MILVUS-USER-GUIDE.md](docs/MILVUS-USER-GUIDE.md).

### How Vector Retrieval Works

In plain English, the memory flow looks like this:

1. **User message** — you ask something like "show memory usage".
2. **Embed message** — the embedding model converts that text into a numeric vector.
3. **Vector search** — Milvus compares that vector with stored vectors from code/doc memory, conversation memory, or tool cache.
4. **Retrieve nearest matches** — lower distance means a closer semantic match.
5. **Inject context** — the best matching snippets are added to the LLM input.
6. **Answer or tool decision** — the app then uses that context to improve tool selection and the final response.

Important terms:

- **Embedding**: turning text into coordinates that capture meaning.
- **Vector search**: finding stored items with nearby coordinates.
- **Distance**: the similarity score Milvus returns; lower is better in this app.
- **Degraded mode**: retrieval timed out or failed, so chat continues without memory context.

Tool selection follows this order:

1. direct route match,
2. memory-based tool route from `conversation_memory` and `tool_cache`,
3. LLM fallback if the first two do not produce a confident result.

For tool routing, `code_memory` is intentionally skipped because code/document matches are useful for answer synthesis but not reliable evidence for which tool should run.

### Prerequisites

- A running [Milvus](https://milvus.io/) instance (v2.4+).  Standalone mode on a local or remote machine is sufficient for development.
- The `pymilvus` package (already included when you install `requirements.txt`).

### Quick Setup

```bash
# 1. Start a standalone Milvus instance (Docker example)
docker run -d --name milvus-standalone \
  -p 19530:19530 -p 9091:9091 \
  milvusdb/milvus:v2.4.0-rc.1 \
  milvus run standalone

# 2. Add memory env vars to .env
MEMORY_ENABLED=true
MEMORY_MILVUS_URI=http://localhost:19530
MEMORY_REPO_ID=my-project          # logical scope for retrieval

# 3. Restart the backend
python -m backend
```

### Indexing Your Code and Docs

Once memory is enabled, run an ingestion pass through the API or a helper script:

```bash
# Trigger ingestion (example — adjust roots to your workspace)
curl -X POST http://localhost:8000/api/memory/ingest \
  -H "Content-Type: application/json" \
  -d '{"repo_roots": ["./src"], "doc_roots": ["./docs"], "repo_id": "my-project"}'

# Check ingestion job status via health endpoint
curl -s http://localhost:8000/health | python3 -m json.tool | grep -A 6 '"memory"'
```

### Health Check

The `/health` endpoint always includes a `memory` key:

```json
// Memory disabled (default)
{ "status": "healthy", ..., "memory": { "enabled": false } }

// Memory healthy
{ "status": "healthy", ..., "memory": { "enabled": true, "healthy": true, "degraded": false } }

// Memory degraded (Milvus unreachable) — top-level app is still healthy
{ "status": "healthy", ..., "memory": { "enabled": true, "healthy": false, "degraded": true } }

// Memory healthy with expiry cleanup enabled
{
  "status": "healthy",
  ...,
  "memory": {
    "enabled": true,
    "healthy": true,
    "degraded": false,
    "expiry_cleanup": {
      "enabled": true,
      "interval_s": 300.0,
      "last_run_at": "2026-04-02T10:15:00+00:00",
      "last_summary": {
        "ran": true,
        "conversation_deleted": 2,
        "tool_cache_deleted": 4
      }
    }
  }
}
```

### Degraded Mode

When `MEMORY_DEGRADED_MODE=true` or when Milvus is temporarily unreachable:

- Retrieval is skipped silently for that request.
- Chat responses remain fully functional — only the context enrichment is absent.
- A `WARNING` log line is emitted: `Retrieval degraded: <reason>`.
- The `/health` endpoint reports `memory.degraded: true` without affecting the top-level `status`.

### Memory Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_ENABLED` | `false` | Enable the memory/retrieval subsystem |
| `MEMORY_MILVUS_URI` | `""` | Milvus endpoint (e.g. `http://localhost:19530`) |
| `MEMORY_REPO_ID` | `""` | Default workspace/repo scope for retrieval |
| `MEMORY_COLLECTION_GENERATION` | `v1` | Active collection generation to search and ingest into |
| `MEMORY_MAX_RESULTS` | `5` | Maximum context blocks returned per chat turn |
| `MEMORY_RETRIEVAL_TIMEOUT_S` | `15.0` | Per-turn retrieval timeout in seconds |
| `MEMORY_DEGRADED_MODE` | `false` | Force degraded (no retrieval) mode without disabling the subsystem |
| `MEMORY_CONVERSATION_ENABLED` | `false` | Enable same-user conversation memory recall and storage |
| `MEMORY_CONVERSATION_RETENTION_DAYS` | `7` | TTL for persisted conversation-memory turns |
| `MEMORY_TOOL_CACHE_ENABLED` | `false` | Enable safe allowlisted tool-result caching |
| `MEMORY_TOOL_CACHE_TTL_S` | `3600.0` | TTL for cached tool results in seconds |
| `MEMORY_TOOL_CACHE_ALLOWLIST` | `""` | Comma-separated tool names allowed to use the cache |
| `MEMORY_EXPIRY_CLEANUP_ENABLED` | `true` | Run automatic expiry cleanup for expired conversation-memory and tool-cache rows |
| `MEMORY_EXPIRY_CLEANUP_INTERVAL_S` | `300.0` | Minimum interval between automatic cleanup runs |

### Expiry Cleanup and Operations Hardening

Phase 4 adds automatic expiry maintenance for long-lived memory artifacts:

- **Conversation memory**: expired turn rows are removed from the SQL sidecar and expired vector rows are pruned from the `conversation_memory` collection.
- **Tool cache**: expired cache rows are removed from the SQL sidecar and expired vector rows are pruned from the `tool_cache` collection when present.
- **Startup cleanup**: when memory is enabled, one cleanup pass runs during backend startup.
- **Request-time maintenance**: subsequent cleanup passes run opportunistically during chat requests, but only after `MEMORY_EXPIRY_CLEANUP_INTERVAL_S` has elapsed.
- **Fail-open behavior**: cleanup failures are logged and surfaced in `memory.expiry_cleanup.last_summary`, but they do not break chat responses.

Recommended production settings:

```bash
MEMORY_CONVERSATION_ENABLED=true
MEMORY_CONVERSATION_RETENTION_DAYS=7
MEMORY_TOOL_CACHE_ENABLED=true
MEMORY_TOOL_CACHE_TTL_S=3600
MEMORY_TOOL_CACHE_ALLOWLIST=get_weather,get_build_status
MEMORY_EXPIRY_CLEANUP_ENABLED=true
MEMORY_EXPIRY_CLEANUP_INTERVAL_S=300
```

Operational guidance:

- Keep `MEMORY_TOOL_CACHE_ALLOWLIST` narrow; do not include tools with side effects.
- Use a shorter `MEMORY_TOOL_CACHE_TTL_S` for frequently changing external data.
- Increase `MEMORY_EXPIRY_CLEANUP_INTERVAL_S` if you want fewer maintenance passes on low-traffic systems.
- Check `/health` for `memory.expiry_cleanup.last_summary` when diagnosing stale memory or cache entries.

### Manual Maintenance Endpoint

Operators can also trigger a cleanup run explicitly:

```bash
curl -X POST http://localhost:8000/api/admin/memory/maintenance \
  -H "Content-Type: application/json" \
  -d '{
        "force": true,
        "cleanup_expired_conversation_memory": true,
        "cleanup_expired_tool_cache": true
      }'
```

When SSO is enabled, this endpoint requires an authenticated user with the `admin` role.
When SSO is disabled, it behaves like other local admin endpoints and is callable without auth.

Typical uses:

- run cleanup immediately after changing retention / TTL settings,
- verify that expired rows are pruned during incident response,
- perform maintenance on low-traffic systems before a deployment or demo.

### Frontend Retrieval Indicator

When retrieval returns results, the assistant message shows a collapsible **📚 N sources retrieved** indicator listing the source paths and collection types (`code` / `doc`).  Expand it to see which files were used.  The indicator is absent when memory is disabled or retrieval returns no results.

## Troubleshooting

### MCP Server Connection Failed

```bash
# Test connectivity
curl -v http://192.168.1.100:3000/health

# Check from backend
python -c "import httpx; print(httpx.get('http://192.168.1.100:3000/health'))"
```

### HTTPS Errors in Development

**For local development only**, set `MCP_ALLOW_HTTP_INSECURE=true` in `.env` to allow HTTP MCP server URLs.

⚠️ **Security Warning**: Never enable this in production. Always use HTTPS for MCP servers in production environments.

### Missing `sqlalchemy` or Other Python Modules

If startup fails with `ModuleNotFoundError: No module named 'sqlalchemy'`, the active virtual environment does not have the project dependencies installed.

```bash
# From the repo root
source venv/bin/activate
python -m pip install -r requirements.txt

# Verify the interpreter and package location
which python
python -m pip show sqlalchemy

# Start the app with the same interpreter
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

If you already installed the requirements, double-check that `uvicorn` is not being launched from a different Python environment.

### Tool Discovery Issues

1. Check server logs for JSON-RPC errors
2. Verify `/rpc` endpoint exists on MCP server
3. Check authentication credentials
4. Review timeout settings

### `ModuleNotFoundError: No module named 'backend'`

This usually means the app was started from the wrong working directory.

Use one of these commands from the repository root:

```bash
python -m backend
# or
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Avoid running `uvicorn backend.main:app` from inside the `backend/` folder.

## Documentation

- **Contributing Guide**: See [CONTRIBUTING.md](CONTRIBUTING.md)
- **AI Guidelines**: See [.github/copilot-instructions.md](.github/copilot-instructions.md)
- **API Reference**: http://localhost:8000/docs

## License

- No standalone license file is currently included in this repository.
- Confirm usage, redistribution, or publication terms with the project owner before reusing the code outside its intended environment.

## Contributing

- See [CONTRIBUTING.md](CONTRIBUTING.md) for the contributor workflow, testing expectations, and change guidelines.

## Support

- Start with the documentation links above, especially [README.md](README.md), [HLD.md](HLD.md), [REQUIREMENTS.md](REQUIREMENTS.md), and [LLM-PROMPT-INJECTION-STRATEGY.md](LLM-PROMPT-INJECTION-STRATEGY.md).
- Use the API docs at http://localhost:8000/docs and the troubleshooting section in this README for local setup issues.
- For runtime debugging, review backend logs and the debug/test pages under [backend/static](backend/static).
