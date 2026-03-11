"""
Root conftest.py — shared fixtures for all backend tests.
Resets module-level in-memory state between every test so tests are isolated.
"""

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import app
from backend.session_manager import SessionManager
from backend.mcp_manager import MCPManager


# ---------------------------------------------------------------------------
# State reset
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_backend_state(tmp_path, monkeypatch):
    """Clear all module-level in-memory storage before each test."""
    data_dir = tmp_path / "mcp-test-data"
    monkeypatch.setattr(main_module, "MCP_DATA_DIR", data_dir)
    main_module.servers_storage.clear()
    main_module.llm_config_storage = None
    main_module.enterprise_token_cache.clear()
    main_module.session_manager = SessionManager()
    main_module.mcp_manager = MCPManager()
    yield
    main_module.servers_storage.clear()
    main_module.llm_config_storage = None
    main_module.enterprise_token_cache.clear()


# ---------------------------------------------------------------------------
# HTTP test client
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------

@pytest.fixture
def server_payload():
    return {
        "alias": "test_server",
        "base_url": "https://mcp.example.com",
        "auth_type": "none",
    }


@pytest.fixture
def server_payload_http():
    return {
        "alias": "http_server",
        "base_url": "http://mcp.example.com",
        "auth_type": "none",
    }


@pytest.fixture
def server_payload_bearer():
    return {
        "alias": "bearer_server",
        "base_url": "https://mcp.example.com",
        "auth_type": "bearer",
        "bearer_token": "my-secret-token",
    }


@pytest.fixture
def llm_openai():
    return {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com",
        "api_key": "sk-test-key",
        "temperature": 0.7,
    }


@pytest.fixture
def llm_ollama():
    return {
        "provider": "ollama",
        "model": "llama3.2",
        "base_url": "http://127.0.0.1:11434",
        "temperature": 0.5,
    }


@pytest.fixture
def llm_mock():
    return {
        "provider": "mock",
        "model": "mock-model",
        "base_url": "http://localhost",
        "temperature": 0.7,
    }


@pytest.fixture
def llm_enterprise():
    return {
        "gateway_mode": "enterprise",
        "provider": "enterprise",
        "model": "gpt-4o",
        "base_url": "https://llm-gateway.internal/modelgw/models/openai/v1",
        "auth_method": "bearer",
        "client_id": "enterprise-client",
        "client_secret": "enterprise-secret",
        "token_endpoint_url": "https://auth.internal/v2/oauth/token",
        "temperature": 0.3,
    }


# ---------------------------------------------------------------------------
# Mock JSON-RPC helpers
# ---------------------------------------------------------------------------

def make_jsonrpc_tool(name: str, description: str = "", params: dict = None):
    """Return a JSON-RPC tool entry as an MCP server would."""
    return {
        "name": name,
        "description": description,
        "inputSchema": params or {"type": "object", "properties": {}},
    }


def make_jsonrpc_success(result: dict, rpc_id: int = 1):
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def make_jsonrpc_error(code: int, message: str, rpc_id: int = 1):
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}
