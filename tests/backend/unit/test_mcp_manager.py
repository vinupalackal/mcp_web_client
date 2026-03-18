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


# ============================================================================
# TR-MCP-4: Virtual Tool (mcp_repeated_exec)
# ============================================================================

class TestVirtualRepeatedExecTool:

    def test_virtual_tool_always_present_in_catalog(self, mgr):
        """TC-MCP-25: get_tools_for_llm() always includes mcp_repeated_exec."""
        tools = mgr.get_tools_for_llm()
        names = [t["function"]["name"] for t in tools]
        assert "mcp_repeated_exec" in names

    def test_virtual_tool_present_with_no_real_tools(self, mgr):
        """TC-MCP-26: Even with empty real tool registry, virtual tool is injected."""
        assert len(mgr.tools) == 0
        tools = mgr.get_tools_for_llm()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "mcp_repeated_exec"

    def test_virtual_tool_appended_after_real_tools(self, mgr, server_https):
        """TC-MCP-27: Virtual tool is the last entry when real tools exist."""
        mgr.tools["svc__ping"] = __import__(
            "backend.models", fromlist=["ToolSchema"]
        ).ToolSchema(
            namespaced_id="svc__ping", server_alias="svc",
            name="ping", description="Ping",
        )
        tools = mgr.get_tools_for_llm()
        assert tools[-1]["function"]["name"] == "mcp_repeated_exec"
        assert tools[0]["function"]["name"] == "svc__ping"

    def test_virtual_tool_required_params(self, mgr):
        """TC-MCP-28: Schema declares target_tool, repeat_count, interval_ms as required."""
        tools = mgr.get_tools_for_llm()
        vt = next(t for t in tools if t["function"]["name"] == "mcp_repeated_exec")
        required = vt["function"]["parameters"]["required"]
        assert "target_tool" in required
        assert "repeat_count" in required
        assert "interval_ms" in required

    def test_virtual_tool_repeat_count_bounds(self, mgr):
        """TC-MCP-29: repeat_count has minimum=1 and maximum=10 in schema."""
        tools = mgr.get_tools_for_llm()
        vt = next(t for t in tools if t["function"]["name"] == "mcp_repeated_exec")
        rc = vt["function"]["parameters"]["properties"]["repeat_count"]
        assert rc["minimum"] == 1
        assert rc["maximum"] == 10

    def test_virtual_tool_interval_ms_minimum_zero(self, mgr):
        """TC-MCP-30: interval_ms has minimum=0 (back-to-back runs allowed)."""
        tools = mgr.get_tools_for_llm()
        vt = next(t for t in tools if t["function"]["name"] == "mcp_repeated_exec")
        im = vt["function"]["parameters"]["properties"]["interval_ms"]
        assert im["minimum"] == 0


# ============================================================================
# TR-MCP-5: _safe_name path-traversal sanitisation
# ============================================================================

class TestSafeName:

    def test_plain_hostname_unchanged(self, mgr):
        """TC-MCP-31: Normal hostname passes through unchanged."""
        assert mgr._safe_name("myhost") == "myhost"

    def test_spaces_replaced_with_underscore(self, mgr):
        """TC-MCP-32: Spaces become underscores."""
        assert mgr._safe_name("proc cpu spin") == "proc_cpu_spin"

    def test_path_traversal_stripped(self, mgr):
        """TC-MCP-33: Path traversal sequences are stripped (NFR-REP-006)."""
        assert mgr._safe_name("../etc/passwd") == "etc_passwd"

    def test_double_slash_collapsed(self, mgr):
        """TC-MCP-34: Double slashes become a single underscore."""
        assert mgr._safe_name("foo//bar") == "foo_bar"

    def test_dotdot_stripped(self, mgr):
        """TC-MCP-35: Double-dot sequences are removed."""
        assert mgr._safe_name("a..b") == "a_b"

    def test_empty_string_returns_unknown(self, mgr):
        """TC-MCP-36: Empty input returns 'unknown' sentinel."""
        assert mgr._safe_name("") == "unknown"

    def test_only_special_chars_returns_unknown(self, mgr):
        """TC-MCP-37: Input of only unsafe chars returns 'unknown'."""
        assert mgr._safe_name("///") == "unknown"

    def test_mixed_special_chars(self, mgr):
        """TC-MCP-38: Mixed alphanumeric and special chars preserves alnum."""
        result = mgr._safe_name("proc-fd_leak.detect")
        # hyphens and underscores allowed; dots become underscores
        assert "proc" in result
        assert "fd" in result
        assert "leak" in result
        assert "detect" in result
        assert "/" not in result
        assert ".." not in result


# ============================================================================
# TR-MCP-6: execute_repeated
# ============================================================================

_EXEC_TOOL = {
    "name": "monitor",
    "description": "Monitor a target",
    "inputSchema": {"type": "object", "properties": {}},
}


class TestExecuteRepeated:

    @respx.mock
    @pytest.mark.asyncio
    async def test_all_runs_succeed(self, mgr, server_https, tmp_path, monkeypatch):
        """TC-MCP-39: 3 successful runs → summary has success_count=3, failure_count=0."""
        monkeypatch.setenv("MCP_REPEATED_EXEC_OUTPUT_DIR", str(tmp_path))

        # init + 3 tool executions
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_exec_ok({"val": 1})),
                httpx.Response(200, json=_exec_ok({"val": 2})),
                httpx.Response(200, json=_exec_ok({"val": 3})),
            ]
        )

        summary, files = await mgr.execute_repeated(
            server=server_https,
            tool_name="monitor",
            tool_arguments={},
            repeat_count=3,
            interval_ms=0,
        )

        assert summary.repeat_count == 3
        assert summary.success_count == 3
        assert summary.failure_count == 0
        assert len(summary.runs) == 3
        assert all(r.success for r in summary.runs)

    @respx.mock
    @pytest.mark.asyncio
    async def test_files_written_per_run(self, mgr, server_https, tmp_path, monkeypatch):
        """TC-MCP-40: One file written per run in the configured output dir."""
        monkeypatch.setenv("MCP_REPEATED_EXEC_OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("MCP_DEVICE_ID", "testhost")

        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_exec_ok({"v": 1})),
                httpx.Response(200, json=_exec_ok({"v": 2})),
            ]
        )

        summary, files = await mgr.execute_repeated(
            server=server_https,
            tool_name="monitor",
            tool_arguments={},
            repeat_count=2,
            interval_ms=0,
        )

        # Files should exist on disk immediately after execute_repeated returns
        # (caller deletes them — here we check they were created)
        assert len(files) == 2
        for f in files:
            assert f.exists()
            content = json.loads(f.read_text())
            assert content["tool_name"] == "monitor"
            assert content["device_id"] == "testhost"

    @respx.mock
    @pytest.mark.asyncio
    async def test_file_names_contain_device_tool_index_timestamp(
        self, mgr, server_https, tmp_path, monkeypatch
    ):
        """TC-MCP-41: File names follow <device>_<tool>_<idx>_<ts>.txt pattern."""
        monkeypatch.setenv("MCP_REPEATED_EXEC_OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("MCP_DEVICE_ID", "devA")

        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_exec_ok({})),
            ]
        )

        summary, files = await mgr.execute_repeated(
            server=server_https,
            tool_name="monitor",
            tool_arguments={},
            repeat_count=1,
            interval_ms=0,
        )

        assert len(files) == 1
        fname = files[0].name
        assert fname.startswith("devA_monitor_")
        assert fname.endswith(".txt")
        # run index zero-padded to width of repeat_count (1 digit for count=1)
        assert "_1_" in fname

    @respx.mock
    @pytest.mark.asyncio
    async def test_partial_failure_continues_sequence(
        self, mgr, server_https, tmp_path, monkeypatch
    ):
        """TC-MCP-42: One failing run does NOT abort the sequence (FR-REP-009)."""
        monkeypatch.setenv("MCP_REPEATED_EXEC_OUTPUT_DIR", str(tmp_path))

        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_exec_ok({"v": 1})),
                httpx.Response(500, text="Server Error"),   # run 2 fails
                httpx.Response(200, json=_exec_ok({"v": 3})),
            ]
        )

        summary, files = await mgr.execute_repeated(
            server=server_https,
            tool_name="monitor",
            tool_arguments={},
            repeat_count=3,
            interval_ms=0,
        )

        assert summary.success_count == 2
        assert summary.failure_count == 1
        assert len(summary.runs) == 3
        assert summary.runs[1].success is False
        assert summary.runs[0].success is True
        assert summary.runs[2].success is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_all_runs_fail(self, mgr, server_https, tmp_path, monkeypatch):
        """TC-MCP-43: All runs failing → failure_count=N, success_count=0."""
        monkeypatch.setenv("MCP_REPEATED_EXEC_OUTPUT_DIR", str(tmp_path))

        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(500, text="err"),
                httpx.Response(500, text="err"),
            ]
        )

        summary, _ = await mgr.execute_repeated(
            server=server_https,
            tool_name="monitor",
            tool_arguments={},
            repeat_count=2,
            interval_ms=0,
        )

        assert summary.success_count == 0
        assert summary.failure_count == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_run_index_zero_padded(self, mgr, server_https, tmp_path, monkeypatch):
        """TC-MCP-44: Run index is zero-padded to match width of repeat_count."""
        monkeypatch.setenv("MCP_REPEATED_EXEC_OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("MCP_DEVICE_ID", "host")

        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                *[httpx.Response(200, json=_exec_ok({})) for _ in range(10)],
            ]
        )

        summary, files = await mgr.execute_repeated(
            server=server_https,
            tool_name="monitor",
            tool_arguments={},
            repeat_count=10,
            interval_ms=0,
        )

        names = [f.name for f in files]
        # run 1 → "01", run 10 → "10" (2-digit padding for count=10)
        assert any("_01_" in n for n in names)
        assert any("_10_" in n for n in names)

    @respx.mock
    @pytest.mark.asyncio
    async def test_summary_device_and_tool_name(self, mgr, server_https, tmp_path, monkeypatch):
        """TC-MCP-45: Summary records correct device_id and bare tool_name."""
        monkeypatch.setenv("MCP_REPEATED_EXEC_OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("MCP_DEVICE_ID", "mydevice")

        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_exec_ok({"ok": True})),
            ]
        )

        summary, _ = await mgr.execute_repeated(
            server=server_https,
            tool_name="monitor",
            tool_arguments={"pid": 123},
            repeat_count=1,
            interval_ms=0,
        )

        assert summary.device_id == "mydevice"
        assert summary.tool_name == "monitor"
        assert summary.target_tool == "svc__monitor"
        assert summary.tool_arguments == {"pid": 123}

    @respx.mock
    @pytest.mark.asyncio
    async def test_interval_not_applied_after_last_run(
        self, mgr, server_https, tmp_path, monkeypatch
    ):
        """TC-MCP-46: asyncio.sleep is called N-1 times (not after last run, FR-REP-010)."""
        import asyncio
        monkeypatch.setenv("MCP_REPEATED_EXEC_OUTPUT_DIR", str(tmp_path))

        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_exec_ok({})),
                httpx.Response(200, json=_exec_ok({})),
                httpx.Response(200, json=_exec_ok({})),
            ]
        )

        sleep_calls = []
        original_sleep = asyncio.sleep

        async def mock_sleep(secs):
            sleep_calls.append(secs)

        monkeypatch.setattr(asyncio, "sleep", mock_sleep)

        await mgr.execute_repeated(
            server=server_https,
            tool_name="monitor",
            tool_arguments={},
            repeat_count=3,
            interval_ms=500,
        )

        # Should be called exactly repeat_count - 1 = 2 times
        assert len(sleep_calls) == 2
        assert all(s == 0.5 for s in sleep_calls)

    @respx.mock
    @pytest.mark.asyncio
    async def test_file_json_schema_complete(self, mgr, server_https, tmp_path, monkeypatch):
        """TC-MCP-47: Each run file contains all required JSON fields (FR-REP-015)."""
        monkeypatch.setenv("MCP_REPEATED_EXEC_OUTPUT_DIR", str(tmp_path))
        monkeypatch.setenv("MCP_DEVICE_ID", "host")

        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_exec_ok({"data": "x"})),
            ]
        )

        _, files = await mgr.execute_repeated(
            server=server_https,
            tool_name="monitor",
            tool_arguments={"pid": 1},
            repeat_count=1,
            interval_ms=0,
        )

        content = json.loads(files[0].read_text())
        required_keys = {
            "device_id", "target_tool", "tool_name", "tool_arguments",
            "run_index", "repeat_count", "interval_ms", "timestamp_utc",
            "duration_ms", "success", "result", "error",
        }
        assert required_keys.issubset(content.keys())
        assert content["device_id"] == "host"
        assert content["tool_name"] == "monitor"
        assert content["run_index"] == 1
        assert content["repeat_count"] == 1
        assert content["success"] is True
        assert content["result"] == {"data": "x"}
        assert content["error"] is None
