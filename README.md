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
| `OPENAI_API_KEY` | - | OpenAI API key |
| `OPENAI_BASE_URL` | `https://api.openai.com` | OpenAI endpoint |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |

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
