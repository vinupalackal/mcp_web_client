"""
End-to-end workflow tests (TR-E2E-*)
Exercises complete user flows across multiple API calls.
"""

import pytest
import respx
import httpx
import backend.main as main_module
from backend.models import ToolSchema


_MOCK_LLM_STOP = {
    "choices": [{
        "message": {"role": "assistant", "content": "Done!"},
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
}

_MOCK_LLM_CLASSIFICATION = {
    "choices": [{
        "message": {
            "role": "assistant",
            "content": "Issue classified as: Network / Connectivity",
        },
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 8, "completion_tokens": 8, "total_tokens": 16},
}

_MOCK_LLM_TOOL_CALL = {
    "choices": [{
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_e2e",
                "type": "function",
                "function": {
                    "name": "svc__ping",
                    "arguments": '{"host": "1.2.3.4"}',
                },
            }],
        },
        "finish_reason": "tool_calls",
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
}


class TestChatWorkflowNoTools:
    """TR-E2E-1: Full chat flow without tools."""

    def test_complete_no_tool_flow(self, client, llm_mock):
        """Steps: save LLM → create session → send message → get history."""
        # Step 1 — configure LLM
        assert client.post("/api/llm/config", json=llm_mock).status_code == 200

        # Step 2 — create session
        sid = client.post("/api/sessions").json()["session_id"]
        assert sid

        # Step 3 — send message
        r = client.post(f"/api/sessions/{sid}/messages", json={
            "role": "user", "content": "Hello"
        })
        assert r.status_code == 200
        assert r.json()["message"]["role"] == "assistant"
        assert r.json()["message"]["content"]

        # Step 4 — history has 2 messages
        msgs = main_module.session_manager.get_messages(sid)
        roles = [m.role for m in msgs]
        assert "user" in roles
        assert "assistant" in roles


class TestChatWorkflowWithTools:
    """TR-E2E-2: Full chat flow with one tool execution."""

    @respx.mock
    def test_complete_tool_flow(self, client, llm_openai, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")

        # Step 1 — LLM config
        client.post("/api/llm/config", json=llm_openai)

        # Step 2 — Add server
        client.post("/api/servers", json={
            "alias": "svc",
            "base_url": "https://mcp.example.com",
            "auth_type": "none",
        })

        # Step 3 — Pre-populate tool (bypass network for tool discovery)
        main_module.mcp_manager.tools["svc__ping"] = ToolSchema(
            namespaced_id="svc__ping",
            server_alias="svc",
            name="ping",
            description="Ping",
        )

        # Step 4 — Create session
        sid = client.post("/api/sessions").json()["session_id"]

        # Step 5 — Send message; LLM first returns tool call, then stop
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_MOCK_LLM_CLASSIFICATION),
                httpx.Response(200, json=_MOCK_LLM_TOOL_CALL),
                httpx.Response(200, json=_MOCK_LLM_STOP),
            ]
        )
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 1,
                    "result": {"protocolVersion": "2024-11-05", "capabilities": {}}
                }),
                httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 3, "result": {"output": "pong"}
                }),
            ]
        )

        r = client.post(f"/api/sessions/{sid}/messages", json={
            "role": "user", "content": "ping 1.2.3.4"
        })
        assert r.status_code == 200
        data = r.json()

        # Step 6 — tool_executions populated
        assert len(data["tool_executions"]) >= 1
        assert data["tool_executions"][0]["success"] is True

        # Tool trace recorded
        traces = main_module.session_manager.get_tool_traces(sid)
        assert any(t["success"] is True for t in traces)


class TestServerLifecycle:
    """TR-E2E-3: Full server add → list → delete → list flow."""

    def test_server_lifecycle(self, client, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")

        # Empty at start
        assert client.get("/api/servers").json() == []

        # Add two servers
        sid_a = client.post("/api/servers", json={
            "alias": "server_a", "base_url": "https://a.example.com", "auth_type": "none"
        }).json()["server_id"]
        sid_b = client.post("/api/servers", json={
            "alias": "server_b", "base_url": "https://b.example.com", "auth_type": "none"
        }).json()["server_id"]

        # Both present
        ids = {s["server_id"] for s in client.get("/api/servers").json()}
        assert {sid_a, sid_b} == ids

        # Delete server A
        assert client.delete(f"/api/servers/{sid_a}").status_code == 200

        # Only B remains
        remaining = [s["server_id"] for s in client.get("/api/servers").json()]
        assert sid_b in remaining
        assert sid_a not in remaining

        # Second delete is 404
        assert client.delete(f"/api/servers/{sid_a}").status_code == 404


class TestToolNamespaceConflictPrevention:
    """TR-E2E-4: Two servers with same tool name get distinct namespaced_ids."""

    def test_namespace_isolation(self, client, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")

        # Register two servers both with a "ping" tool
        main_module.mcp_manager.tools["server_a__ping"] = ToolSchema(
            namespaced_id="server_a__ping",
            server_alias="server_a",
            name="ping",
            description="",
        )
        main_module.mcp_manager.tools["server_b__ping"] = ToolSchema(
            namespaced_id="server_b__ping",
            server_alias="server_b",
            name="ping",
            description="",
        )

        tools = client.get("/api/tools").json()
        ns_ids = {t["namespaced_id"] for t in tools}
        assert "server_a__ping" in ns_ids
        assert "server_b__ping" in ns_ids
        assert len(ns_ids) == 2
