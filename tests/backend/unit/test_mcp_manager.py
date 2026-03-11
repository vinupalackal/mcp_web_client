"""
Unit tests for MCPManager (TR-MCP-*)
Uses respx to mock outbound httpx requests.
"""

import json
import pytest
import respx
import httpx
from backend.mcp_manager import MCPManager
from backend.models import ServerConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mgr():
    return MCPManager()


@pytest.fixture
def server_https():
    return ServerConfig(alias="svc", base_url="https://mcp.example.com", auth_type="none")


@pytest.fixture
def server_bearer():
    return ServerConfig(
        alias="svc",
        base_url="https://mcp.example.com",
        auth_type="bearer",
        bearer_token="tok",
    )


@pytest.fixture
def server_no_auth():
    return ServerConfig(alias="svc", base_url="https://mcp.example.com", auth_type="none")


def _init_ok():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"protocolVersion": "2024-11-05", "capabilities": {}},
    }


def _tools_ok(tools):
    return {"jsonrpc": "2.0", "id": 2, "result": {"tools": tools}}


def _exec_ok(result):
    return {"jsonrpc": "2.0", "id": 3, "result": result}


def _rpc_error(message="error"):
    return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": message}}


_SAMPLE_TOOL = {
    "name": "ping",
    "description": "Ping a host",
    "inputSchema": {
        "type": "object",
        "properties": {"host": {"type": "string"}},
    },
}


# ============================================================================
# TR-MCP-1: Server Initialization
# ============================================================================

class TestInitializeServer:

    @respx.mock
    @pytest.mark.asyncio
    async def test_successful_init_marks_server(self, mgr, server_https):
        """TC-MCP-01: Successful init sets initialized_servers[id]=True."""
        respx.post("https://mcp.example.com/mcp").mock(
            return_value=httpx.Response(200, json=_init_ok())
        )
        await mgr.initialize_server(server_https)
        assert mgr.initialized_servers.get(server_https.server_id) is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_jsonrpc_error_raises(self, mgr, server_https):
        """TC-MCP-02: JSON-RPC error in response raises Exception."""
        respx.post("https://mcp.example.com/mcp").mock(
            return_value=httpx.Response(200, json=_rpc_error("bad version"))
        )
        with pytest.raises(Exception, match="JSON-RPC error"):
            await mgr.initialize_server(server_https)

    @respx.mock
    @pytest.mark.asyncio
    async def test_http_error_raises(self, mgr, server_https):
        """TC-MCP-03: HTTP 500 raises Exception."""
        respx.post("https://mcp.example.com/mcp").mock(
            return_value=httpx.Response(500, text="Server Error")
        )
        with pytest.raises(Exception):
            await mgr.initialize_server(server_https)

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_raises(self, mgr, server_https):
        """TC-MCP-04: Timeout raises Exception mentioning server alias."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        with pytest.raises(Exception, match="Timeout"):
            await mgr.initialize_server(server_https)

    @respx.mock
    @pytest.mark.asyncio
    async def test_payload_format(self, mgr, server_https):
        """TC-MCP-05: Payload contains required JSON-RPC initialize fields."""
        route = respx.post("https://mcp.example.com/mcp").mock(
            return_value=httpx.Response(200, json=_init_ok())
        )
        await mgr.initialize_server(server_https)
        payload = json.loads(route.calls.last.request.read())
        assert payload["jsonrpc"] == "2.0"
        assert payload["method"] == "initialize"
        assert payload["params"]["protocolVersion"] == "2024-11-05"
        assert payload["params"]["clientInfo"]["name"] == "mcp-client-web"

    @respx.mock
    @pytest.mark.asyncio
    async def test_rpc_url_construction(self, mgr, server_https):
        """TC-MCP-06: Request sent to {base_url}/mcp."""
        route = respx.post("https://mcp.example.com/mcp").mock(
            return_value=httpx.Response(200, json=_init_ok())
        )
        await mgr.initialize_server(server_https)
        assert route.called

    @respx.mock
    @pytest.mark.asyncio
    async def test_bearer_auth_header(self, mgr, server_bearer):
        """TC-MCP-07: Bearer auth_type sets Authorization header."""
        route = respx.post("https://mcp.example.com/mcp").mock(
            return_value=httpx.Response(200, json=_init_ok())
        )
        await mgr.initialize_server(server_bearer)
        auth = route.calls.last.request.headers["authorization"]
        assert auth == "Bearer tok"

    @respx.mock
    @pytest.mark.asyncio
    async def test_no_auth_header_for_none(self, mgr, server_no_auth):
        """TC-MCP-08: auth_type='none' sends no Authorization header."""
        route = respx.post("https://mcp.example.com/mcp").mock(
            return_value=httpx.Response(200, json=_init_ok())
        )
        await mgr.initialize_server(server_no_auth)
        assert "authorization" not in route.calls.last.request.headers


# ============================================================================
# TR-MCP-2: Tool Discovery
# ============================================================================

class TestDiscoverTools:

    @respx.mock
    @pytest.mark.asyncio
    async def test_discovers_tools(self, mgr, server_https):
        """TC-MCP-09: Returns correct number of ToolSchema objects."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok([_SAMPLE_TOOL])),
            ]
        )
        tools = await mgr.discover_tools(server_https)
        assert len(tools) == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_tools_stored_in_registry(self, mgr, server_https):
        """TC-MCP-10: Discovered tools stored in mcp_manager.tools."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok([_SAMPLE_TOOL])),
            ]
        )
        await mgr.discover_tools(server_https)
        assert "svc__ping" in mgr.tools

    @respx.mock
    @pytest.mark.asyncio
    async def test_namespaced_id_format(self, mgr, server_https):
        """TC-MCP-11: namespaced_id = server_alias__tool_name."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok([_SAMPLE_TOOL])),
            ]
        )
        tools = await mgr.discover_tools(server_https)
        assert tools[0].namespaced_id == "svc__ping"

    @respx.mock
    @pytest.mark.asyncio
    async def test_auto_initializes_server(self, mgr, server_https):
        """TC-MCP-12: discover_tools auto-calls initialize if not done."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),   # init
                httpx.Response(200, json=_tools_ok([_SAMPLE_TOOL])),  # tools/list
            ]
        )
        assert server_https.server_id not in mgr.initialized_servers
        await mgr.discover_tools(server_https)
        assert server_https.server_id in mgr.initialized_servers

    @respx.mock
    @pytest.mark.asyncio
    async def test_jsonrpc_error_raises(self, mgr, server_https):
        """TC-MCP-13: JSON-RPC error in tools/list raises Exception."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_rpc_error("method not found")),
            ]
        )
        with pytest.raises(Exception, match="JSON-RPC error"):
            await mgr.discover_tools(server_https)

    @respx.mock
    @pytest.mark.asyncio
    async def test_empty_tools_list(self, mgr, server_https):
        """TC-MCP-14: Empty tools list returns [] without error."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok([])),
            ]
        )
        tools = await mgr.discover_tools(server_https)
        assert tools == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_tools_list_payload_format(self, mgr, server_https):
        """TC-MCP-15: tools/list payload contains method='tools/list'."""
        route = respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok([_SAMPLE_TOOL])),
            ]
        )
        await mgr.discover_tools(server_https)
        # Second call is the tools/list
        payload = json.loads(route.calls[1].request.read())
        assert payload["method"] == "tools/list"

    @respx.mock
    @pytest.mark.asyncio
    async def test_description_stored(self, mgr, server_https):
        """TC-MCP-16: Tool description stored in ToolSchema."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok([_SAMPLE_TOOL])),
            ]
        )
        tools = await mgr.discover_tools(server_https)
        assert tools[0].description == "Ping a host"

    @respx.mock
    @pytest.mark.asyncio
    async def test_parameters_stored(self, mgr, server_https):
        """TC-MCP-17: Tool inputSchema stored in ToolSchema.parameters."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok([_SAMPLE_TOOL])),
            ]
        )
        tools = await mgr.discover_tools(server_https)
        assert "properties" in tools[0].parameters


# ============================================================================
# TR-MCP-3: Tool Execution
# ============================================================================

class TestExecuteTool:

    @respx.mock
    @pytest.mark.asyncio
    async def test_successful_execution(self, mgr, server_https):
        """TC-MCP-18: Successful execution returns result dict."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_exec_ok({"output": "pong"})),
            ]
        )
        result = await mgr.execute_tool(server_https, "ping", {"host": "1.2.3.4"})
        assert result == {"output": "pong"}

    @respx.mock
    @pytest.mark.asyncio
    async def test_tools_call_payload_format(self, mgr, server_https):
        """TC-MCP-19: tools/call payload has correct method and params."""
        route = respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_exec_ok({})),
            ]
        )
        await mgr.execute_tool(server_https, "ping", {"host": "1.2.3.4"})
        payload = json.loads(route.calls[1].request.read())
        assert payload["method"] == "tools/call"
        assert payload["params"]["name"] == "ping"
        assert payload["params"]["arguments"] == {"host": "1.2.3.4"}

    @respx.mock
    @pytest.mark.asyncio
    async def test_jsonrpc_error_raises(self, mgr, server_https):
        """TC-MCP-20: JSON-RPC error in tools/call raises Exception."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_rpc_error("tool not found")),
            ]
        )
        with pytest.raises(Exception):
            await mgr.execute_tool(server_https, "missing_tool", {})

    @respx.mock
    @pytest.mark.asyncio
    async def test_http_error_raises(self, mgr, server_https):
        """TC-MCP-21: HTTP 404 raises Exception."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(404, text="Not Found"),
            ]
        )
        with pytest.raises(Exception):
            await mgr.execute_tool(server_https, "ping", {})

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_raises(self, mgr, server_https):
        """TC-MCP-22: Timeout raises Exception."""
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.TimeoutException("timed out"),
            ]
        )
        with pytest.raises(Exception):
            await mgr.execute_tool(server_https, "ping", {})


# ============================================================================
# TR-MCP-3b: discover_all_tools
# ============================================================================

class TestDiscoverAllTools:

    @respx.mock
    @pytest.mark.asyncio
    async def test_all_servers_success(self, mgr):
        """TC-MCP-23: Both servers succeed → correct counts."""
        s1 = ServerConfig(alias="s1", base_url="https://s1.example.com", auth_type="none")
        s2 = ServerConfig(alias="s2", base_url="https://s2.example.com", auth_type="none")

        respx.post("https://s1.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok([_SAMPLE_TOOL, _SAMPLE_TOOL])),
            ]
        )
        respx.post("https://s2.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok([_SAMPLE_TOOL])),
            ]
        )

        total, refreshed, errors = await mgr.discover_all_tools([s1, s2])
        assert total == 3
        assert refreshed == 2
        assert errors == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_partial_failure(self, mgr):
        """TC-MCP-24: One server fails → partial success."""
        s1 = ServerConfig(alias="s1", base_url="https://s1.example.com", auth_type="none")
        s2 = ServerConfig(alias="s2", base_url="https://s2.example.com", auth_type="none")

        respx.post("https://s1.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok([_SAMPLE_TOOL])),
            ]
        )
        respx.post("https://s2.example.com/mcp").mock(
            return_value=httpx.Response(500, text="Error")
        )

        total, refreshed, errors = await mgr.discover_all_tools([s1, s2])
        assert total == 1
        assert refreshed == 1
        assert len(errors) == 1
