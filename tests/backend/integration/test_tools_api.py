"""
Integration tests — Tool Discovery endpoints (TR-TOOL-*)
"""

import pytest
import respx
import httpx
import backend.main as main_module
from backend.models import ServerConfig


def _init_ok():
    return {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "capabilities": {}}}


def _tools_ok(tools):
    return {"jsonrpc": "2.0", "id": 2, "result": {"tools": tools}}


_SAMPLE_TOOLS = [
    {"name": "ping", "description": "Ping a host", "inputSchema": {}},
    {"name": "traceroute", "description": "Trace route", "inputSchema": {}},
]


class TestGetTools:

    def test_empty_tools_before_discovery(self, client):
        """TC-TOOL-07: GET /api/tools returns [] before any discovery."""
        r = client.get("/api/tools")
        assert r.status_code == 200
        assert r.json() == []

    def test_tools_after_discovery(self, client, server_payload, monkeypatch):
        """TC-TOOL-08: Tools present after successful refresh."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        # Pre-populate tools in mcp_manager directly
        from backend.models import ToolSchema
        main_module.mcp_manager.tools["svc__ping"] = ToolSchema(
            namespaced_id="svc__ping",
            server_alias="svc",
            name="ping",
            description="Ping",
        )
        r = client.get("/api/tools")
        assert len(r.json()) == 1

    def test_tool_schema_shape(self, client):
        """TC-TOOL-09: Each tool has required fields."""
        from backend.models import ToolSchema
        main_module.mcp_manager.tools["svc__ping"] = ToolSchema(
            namespaced_id="svc__ping",
            server_alias="svc",
            name="ping",
            description="Ping",
        )
        tools = client.get("/api/tools").json()
        for t in tools:
            assert "namespaced_id" in t
            assert "server_alias" in t
            assert "name" in t
            assert "description" in t

    def test_namespaced_id_format(self, client):
        """TC-TOOL-10: namespaced_id follows server_alias__tool_name pattern."""
        from backend.models import ToolSchema
        main_module.mcp_manager.tools["mysvc__do_thing"] = ToolSchema(
            namespaced_id="mysvc__do_thing",
            server_alias="mysvc",
            name="do_thing",
            description="",
        )
        tools = client.get("/api/tools").json()
        assert tools[0]["namespaced_id"] == "mysvc__do_thing"


class TestRefreshTools:

    @respx.mock
    def test_no_servers_returns_zero(self, client):
        """TC-TOOL-01: refresh-tools with no servers → total_tools=0."""
        r = client.post("/api/servers/refresh-tools")
        assert r.status_code == 200
        data = r.json()
        assert data["total_tools"] == 0
        assert data["servers_refreshed"] == 0

    @respx.mock
    def test_successful_discovery(self, client, monkeypatch):
        """TC-TOOL-02: Successful refresh populates tools."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        payload = {"alias": "svc", "base_url": "https://mcp.example.com", "auth_type": "none"}
        client.post("/api/servers", json=payload)

        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok(_SAMPLE_TOOLS)),
            ]
        )
        r = client.post("/api/servers/refresh-tools")
        assert r.status_code == 200
        data = r.json()
        assert data["total_tools"] == 2
        assert data["servers_refreshed"] == 1
        assert data["errors"] == []

    @respx.mock
    def test_tool_namespacing_after_refresh(self, client, monkeypatch):
        """TC-TOOL-05: Tools namespaced as server_alias__tool_name after refresh."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        payload = {"alias": "weather_api", "base_url": "https://mcp.example.com", "auth_type": "none"}
        client.post("/api/servers", json=payload)

        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok([
                    {"name": "get_weather", "description": "", "inputSchema": {}}
                ])),
            ]
        )
        client.post("/api/servers/refresh-tools")
        tools = client.get("/api/tools").json()
        assert any(t["namespaced_id"] == "weather_api__get_weather" for t in tools)

    @respx.mock
    def test_partial_failure(self, client, monkeypatch):
        """TC-TOOL-04: Partial failure reported in errors field."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        client.post("/api/servers", json={
            "alias": "s1", "base_url": "https://s1.example.com", "auth_type": "none"
        })
        client.post("/api/servers", json={
            "alias": "s2", "base_url": "https://s2.example.com", "auth_type": "none"
        })

        respx.post("https://s1.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json=_init_ok()),
                httpx.Response(200, json=_tools_ok(_SAMPLE_TOOLS[:1])),
            ]
        )
        respx.post("https://s2.example.com/mcp").mock(
            return_value=httpx.Response(500, text="Unavailable")
        )

        r = client.post("/api/servers/refresh-tools")
        data = r.json()
        assert data["servers_refreshed"] == 1
        assert len(data["errors"]) == 1


class TestRefreshServerHealth:

    @respx.mock
    def test_no_servers_returns_zero(self, client):
        """TC-TOOL-11: refresh-health with no servers returns zero counts."""
        r = client.post("/api/servers/refresh-health")
        assert r.status_code == 200
        data = r.json()
        assert data["servers_checked"] == 0
        assert data["healthy_servers"] == 0
        assert data["unhealthy_servers"] == 0

    @respx.mock
    def test_successful_health_refresh_marks_server_healthy(self, client, monkeypatch):
        """TC-TOOL-12: refresh-health marks server healthy after initialize succeeds."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        client.post("/api/servers", json={
            "alias": "svc", "base_url": "https://mcp.example.com", "auth_type": "none"
        })

        respx.post("https://mcp.example.com/mcp").mock(
            return_value=httpx.Response(200, json=_init_ok())
        )

        r = client.post("/api/servers/refresh-health")
        assert r.status_code == 200
        data = r.json()
        assert data["servers_checked"] == 1
        assert data["healthy_servers"] == 1
        assert data["unhealthy_servers"] == 0
        assert data["servers"][0]["health_status"] == "healthy"
        assert data["servers"][0]["last_health_check"] is not None

    @respx.mock
    def test_failed_health_refresh_marks_server_unhealthy(self, client, monkeypatch):
        """TC-TOOL-13: refresh-health marks server unhealthy on initialize failure."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        client.post("/api/servers", json={
            "alias": "svc", "base_url": "https://mcp.example.com", "auth_type": "none"
        })

        respx.post("https://mcp.example.com/mcp").mock(
            return_value=httpx.Response(500, text="Unavailable")
        )

        r = client.post("/api/servers/refresh-health")
        assert r.status_code == 200
        data = r.json()
        assert data["servers_checked"] == 1
        assert data["healthy_servers"] == 0
        assert data["unhealthy_servers"] == 1
        assert len(data["errors"]) == 1
        assert data["servers"][0]["health_status"] == "unhealthy"
