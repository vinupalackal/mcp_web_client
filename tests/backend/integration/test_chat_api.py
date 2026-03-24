"""
Integration tests — Sessions and Chat (TR-SESS-1, TR-CHAT-*)
"""

import pytest
import respx
import httpx
import backend.main as main_module


_MOCK_LLM_STOP = {
    "choices": [{
        "message": {"role": "assistant", "content": "Hello from mock!"},
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
                "id": "call_abc",
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

_MOCK_LLM_TOOL_CALL_WITH_CONTENT = {
    "choices": [{
        "message": {
            "role": "assistant",
            "content": "I'll check the server and summarize what I find.",
            "tool_calls": [{
                "id": "call_with_content",
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

_MOCK_LLM_DUPLICATE_TOOL_CALLS = {
    "choices": [{
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_dup_1",
                    "type": "function",
                    "function": {
                        "name": "svc__ping",
                        "arguments": '{"host": "1.2.3.4"}',
                    },
                },
                {
                    "id": "call_dup_2",
                    "type": "function",
                    "function": {
                        "name": "svc__ping",
                        "arguments": '{"host": "1.2.3.4"}',
                    },
                },
            ],
        },
        "finish_reason": "tool_calls",
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
}

_MOCK_LLM_TEXT_TOOL_CALL = {
    "choices": [{
        "message": {
            "role": "assistant",
            "content": '**{"name": "svc__ping", "parameters": {"host": "1.2.3.4"}}**',
        },
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
}

_MOCK_LLM_EMBEDDED_TEXT_TOOL_CALL = {
    "choices": [{
        "message": {
            "role": "assistant",
            "content": "To answer this question, I will call the `svc__ping` function.\n\nHere is the function call:\n{\"name\": \"svc__ping\", \"parameters\": {\"host\": \"1.2.3.4\"}}",
        },
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
}

_MOCK_LLM_EMBEDDED_BARE_NAME_TOOL_CALL = {
    "choices": [{
        "message": {
            "role": "assistant",
            "content": "To answer this question, I will call the `get_system_uptime` function.\n\n{\"name\": \"get_system_uptime\", \"parameters\": {}}",
        },
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
}

_MOCK_LLM_SUMMARY_AFTER_TOOL = {
    "choices": [{
        "message": {
            "role": "assistant",
            "content": "The host responded successfully with pong.",
        },
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
}

_MOCK_LLM_TOOL_CALL_STOP_REASON = {
    "choices": [{
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_stop_reason",
                "type": "function",
                "function": {
                    "name": "svc__ping",
                    "arguments": '{"host": "1.2.3.4"}',
                },
            }],
        },
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
}

_MOCK_LLM_TWO_TOOL_CALLS = {
    "choices": [{
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_cpu",
                    "type": "function",
                    "function": {
                        "name": "svc__get_cpu",
                        "arguments": '{}'  ,
                    },
                },
                {
                    "id": "call_mem",
                    "type": "function",
                    "function": {
                        "name": "svc__get_memory",
                        "arguments": '{}',
                    },
                },
            ],
        },
        "finish_reason": "tool_calls",
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
}

_MOCK_OLLAMA_TOOL_CALL = {
    "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "function": {
                "name": "svc__ping",
                "arguments": {"host": "1.2.3.4"},
            }
        }],
    },
    "done": True,
    "prompt_eval_count": 5,
    "eval_count": 4,
}

_MOCK_OLLAMA_STOP = {
    "message": {"role": "assistant", "content": "Ping completed."},
    "done": True,
    "prompt_eval_count": 5,
    "eval_count": 4,
}


# ============================================================================
# TR-SESS-1: Create Session
# ============================================================================

class TestCreateSession:

    def test_create_returns_201(self, client):
        """TC-SESS-01: POST /api/sessions returns 201."""
        r = client.post("/api/sessions")
        assert r.status_code == 201

    def test_session_id_is_uuid(self, client):
        """TC-SESS-01b: Returned session_id is a UUID."""
        r = client.post("/api/sessions")
        assert len(r.json()["session_id"]) == 36

    def test_created_at_present(self, client):
        """TC-SESS-01c: created_at field in response."""
        r = client.post("/api/sessions")
        assert "created_at" in r.json()

    def test_unique_session_ids(self, client):
        """TC-SESS-02: Multiple sessions get unique IDs."""
        ids = {client.post("/api/sessions").json()["session_id"] for _ in range(5)}
        assert len(ids) == 5


# ============================================================================
# TR-CHAT-1: Send Message — basic
# ============================================================================

class TestSendMessage:

    def test_no_llm_config_returns_guidance(self, client):
        """TC-CHAT-01: No LLM configured → polite guidance message."""
        sid = client.post("/api/sessions").json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/messages", json={
            "role": "user", "content": "hello"
        })
        assert r.status_code == 200
        assert "configure" in r.json()["message"]["content"].lower()

    def test_mock_llm_returns_assistant_response(self, client, llm_mock):
        """TC-CHAT-02: Mock LLM returns assistant message."""
        client.post("/api/llm/config", json=llm_mock)
        sid = client.post("/api/sessions").json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/messages", json={
            "role": "user", "content": "hello"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["message"]["role"] == "assistant"
        assert data["message"]["content"]

    def test_response_structure(self, client, llm_mock):
        """TC-CHAT-03: Response has session_id, message, tool_executions."""
        client.post("/api/llm/config", json=llm_mock)
        sid = client.post("/api/sessions").json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/messages", json={
            "role": "user", "content": "hi"
        })
        data = r.json()
        assert "session_id" in data
        assert "message" in data
        assert "tool_executions" in data

    def test_messages_stored_in_session(self, client, llm_mock):
        """TC-CHAT-04: User + assistant messages added to session."""
        client.post("/api/llm/config", json=llm_mock)
        sid = client.post("/api/sessions").json()["session_id"]
        client.post(f"/api/sessions/{sid}/messages", json={
            "role": "user", "content": "hi"
        })
        msgs = main_module.session_manager.get_messages(sid)
        roles = [m.role for m in msgs]
        assert "user" in roles
        assert "assistant" in roles

    def test_empty_content_returns_422(self, client, llm_mock):
        """TC-CHAT-06: Empty content field returns 422."""
        client.post("/api/llm/config", json=llm_mock)
        sid = client.post("/api/sessions").json()["session_id"]
        r = client.post(f"/api/sessions/{sid}/messages", json={
            "role": "user", "content": ""
        })
        assert r.status_code == 422

    @respx.mock
    def test_system_prompt_injected(self, client, llm_openai):
        """TC-CHAT-07: System prompt present as first LLM message."""
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        captured_payload = {}

        def capture(request):
            import json
            captured_payload.update(json.loads(request.content))
            return httpx.Response(200, json=_MOCK_LLM_STOP)

        respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=capture)
        client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "hi"})
        assert captured_payload["messages"][0]["role"] == "system"

    @respx.mock
    def test_system_prompt_contains_parallel_tool_call_instruction(self, client, llm_openai):
        """TC-CHAT-07a: System prompt explicitly instructs the model to call multiple tools in parallel."""
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        captured_payload = {}

        def capture(request):
            import json
            captured_payload.update(json.loads(request.content))
            return httpx.Response(200, json=_MOCK_LLM_STOP)

        respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=capture)
        client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "hi"})

        system_content = captured_payload["messages"][0]["content"]
        assert "parallel" in system_content.lower()
        assert "parallel function calls" in system_content or "parallel tool calls" in system_content or "simultaneously" in system_content

    @respx.mock
    def test_system_prompt_contains_diagnostic_strategy_context(self, client, llm_openai, monkeypatch):
        """System prompt includes platform, tool inventory, classification, and dynamic network guidance."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        client.post("/api/servers", json={
            "alias": "svc",
            "base_url": "https://mcp.example.com",
            "auth_type": "none",
        })
        from backend.models import ToolSchema
        main_module.mcp_manager.tools["svc__network_dns_check"] = ToolSchema(
            namespaced_id="svc__network_dns_check",
            server_alias="svc",
            name="network_dns_check",
            description="DNS diagnostics",
        )
        main_module.mcp_manager.tools["svc__wan_status"] = ToolSchema(
            namespaced_id="svc__wan_status",
            server_alias="svc",
            name="wan_status",
            description="WAN status",
        )

        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        captured_payload = {}

        def capture(request):
            import json
            captured_payload.update(json.loads(request.content))
            return httpx.Response(200, json=_MOCK_LLM_STOP)

        respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=capture)
        client.post(
            f"/api/sessions/{sid}/messages",
            json={"role": "user", "content": "The device has no internet and DNS is failing"},
        )

        system_content = captured_payload["messages"][0]["content"]
        assert "Platform profile: Broadband" in system_content
        assert "svc__network_dns_check" in system_content
        assert "svc__wan_status" in system_content
        assert "Issue classified as: Network / Connectivity" in system_content
        assert "Prioritize these available tools in order" in system_content

    @respx.mock
    def test_session_with_include_history_false_sends_only_latest_query(self, client, llm_openai):
        """When include_history is false, prior session messages are not sent with the next user query."""
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions", json={
            "llm_config": llm_openai,
            "enabled_servers": [],
            "include_history": False,
        }).json()["session_id"]

        captured_payloads = []

        def capture(request):
            import json
            captured_payloads.append(json.loads(request.content))
            return httpx.Response(200, json=_MOCK_LLM_STOP)

        respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=capture)

        client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "first"})
        client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "second"})

        assert len(captured_payloads) == 2
        second_messages = captured_payloads[1]["messages"]
        assert [msg["role"] for msg in second_messages] == ["system", "user"]
        assert second_messages[1]["content"] == "second"


# ============================================================================
# TR-CHAT-2: Tool Calling Flow
# ============================================================================

class TestToolCallingFlow:

    def _setup_server_and_tool(self, client, monkeypatch):
        """Helper: add a server and pre-populate a tool in mcp_manager."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        client.post("/api/servers", json={
            "alias": "svc",
            "base_url": "https://mcp.example.com",
            "auth_type": "none",
        })
        from backend.models import ServerConfig, ToolSchema
        server = ServerConfig(
            alias="svc",
            base_url="https://mcp.example.com",
            auth_type="none",
        )
        main_module.mcp_manager.tools["svc__ping"] = ToolSchema(
            namespaced_id="svc__ping",
            server_alias="svc",
            name="ping",
            description="Ping",
        )

    @respx.mock
    def test_tool_executed_on_tool_call_finish_reason(self, client, llm_openai, monkeypatch):
        """TC-CHAT-08/09: LLM tool_calls finish_reason triggers tool execution."""
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        # First call returns tool_calls, second returns stop
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
        assert len(data["tool_executions"]) >= 1

    @respx.mock
    def test_successful_tool_logged(self, client, llm_openai, monkeypatch):
        """TC-CHAT-10: Successful tool call → trace with success=True."""
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

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

        client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "ping"})
        traces = main_module.session_manager.get_tool_traces(sid)
        assert any(t["success"] is True for t in traces)

    @respx.mock
    def test_response_includes_initial_llm_response_when_tool_call_has_content(self, client, llm_openai, monkeypatch):
        """Initial assistant pre-tool text is returned separately from the final answer."""
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_MOCK_LLM_CLASSIFICATION),
                httpx.Response(200, json=_MOCK_LLM_TOOL_CALL_WITH_CONTENT),
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

        r = client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "ping"})
        assert r.status_code == 200
        data = r.json()
        assert data["message"]["content"] == "Hello from mock!"
        assert data["initial_llm_response"] == "I'll check the server and summarize what I find."

    @respx.mock
    def test_duplicate_same_tool_same_args_runs_once_per_turn(self, client, llm_openai, monkeypatch):
        """Duplicate same-tool same-args calls in one turn are executed only once."""
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_MOCK_LLM_CLASSIFICATION),
                httpx.Response(200, json=_MOCK_LLM_DUPLICATE_TOOL_CALLS),
                httpx.Response(200, json=_MOCK_LLM_STOP),
            ]
        )
        mcp_route = respx.post("https://mcp.example.com/mcp").mock(
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

        r = client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "ping twice"})
        assert r.status_code == 200
        data = r.json()
        assert len(data["tool_executions"]) == 1
        assert data["tool_executions"][0]["tool"] == "svc__ping"
        assert len(mcp_route.calls) == 2

    @respx.mock
    def test_json_tool_call_content_is_recovered_and_not_shown_as_final_answer(self, client, llm_openai, monkeypatch):
        """JSON-like tool call content is treated as a tool request instead of the final user-facing answer."""
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_MOCK_LLM_CLASSIFICATION),
                httpx.Response(200, json=_MOCK_LLM_TOOL_CALL),
                httpx.Response(200, json=_MOCK_LLM_TEXT_TOOL_CALL),
                httpx.Response(200, json=_MOCK_LLM_SUMMARY_AFTER_TOOL),
            ]
        )
        mcp_route = respx.post("https://mcp.example.com/mcp").mock(
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

        r = client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "ping then summarize"})
        assert r.status_code == 200
        data = r.json()
        assert data["message"]["content"] == "The host responded successfully with pong."
        assert len(data["tool_executions"]) == 1
        assert len(mcp_route.calls) == 2

    @respx.mock
    def test_embedded_json_tool_call_content_is_recovered(self, client, llm_openai, monkeypatch):
        """Tool call JSON embedded inside prose is recovered and executed."""
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_MOCK_LLM_CLASSIFICATION),
                httpx.Response(200, json=_MOCK_LLM_EMBEDDED_TEXT_TOOL_CALL),
                httpx.Response(200, json=_MOCK_LLM_SUMMARY_AFTER_TOOL),
            ]
        )
        mcp_route = respx.post("https://mcp.example.com/mcp").mock(
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

        r = client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "ping"})
        assert r.status_code == 200
        data = r.json()
        assert data["message"]["content"] == "The host responded successfully with pong."
        assert len(data["tool_executions"]) == 1
        assert data["tool_executions"][0]["tool"] == "svc__ping"
        assert len(mcp_route.calls) == 2

    @respx.mock
    def test_embedded_json_bare_tool_name_is_resolved_to_namespaced_tool(self, client, llm_openai, monkeypatch):
        """A bare tool name embedded in assistant prose is resolved when it maps uniquely to one discovered tool."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        client.post("/api/servers", json={
            "alias": "home_mcp_server",
            "base_url": "https://mcp.example.com",
            "auth_type": "none",
        })
        from backend.models import ToolSchema
        main_module.mcp_manager.tools["home_mcp_server__get_system_uptime"] = ToolSchema(
            namespaced_id="home_mcp_server__get_system_uptime",
            server_alias="home_mcp_server",
            name="get_system_uptime",
            description="Get system uptime",
        )

        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_MOCK_LLM_CLASSIFICATION),
                httpx.Response(200, json=_MOCK_LLM_EMBEDDED_BARE_NAME_TOOL_CALL),
                httpx.Response(200, json={
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "The system has been up for 6 days.",
                        },
                        "finish_reason": "stop",
                    }],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                }),
            ]
        )
        mcp_route = respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 1,
                    "result": {"protocolVersion": "2024-11-05", "capabilities": {}}
                }),
                httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 3, "result": {"uptime": "6d"}
                }),
            ]
        )

        r = client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "uptime?"})
        assert r.status_code == 200
        data = r.json()
        assert data["message"]["content"] == "The system has been up for 6 days."
        assert len(data["tool_executions"]) == 1
        assert data["tool_executions"][0]["tool"] == "home_mcp_server__get_system_uptime"
        assert len(mcp_route.calls) == 2

    @respx.mock
    def test_max_tool_calls_limit(self, client, llm_openai, monkeypatch):
        """TC-CHAT-12: Loop exits after MCP_MAX_TOOL_CALLS_PER_TURN."""
        monkeypatch.setenv("MCP_MAX_TOOL_CALLS_PER_TURN", "2")
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        # LLM always returns tool_calls
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_MOCK_LLM_TOOL_CALL)
        )
        respx.post("https://mcp.example.com/mcp").mock(
            return_value=httpx.Response(200, json={
                "jsonrpc": "2.0", "id": 1,
                "result": {"protocolVersion": "2024-11-05", "capabilities": {}}
            })
        )

        r = client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "loop"})
        assert r.status_code == 200  # did not crash; loop exited gracefully

    @respx.mock
    def test_large_tool_output_truncated(self, client, llm_openai, monkeypatch):
        """TC-CHAT-13: Tool output >12000 chars is truncated before LLM call."""
        monkeypatch.setenv("MCP_MAX_TOOL_OUTPUT_CHARS_TO_LLM", "100")
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        captured = {}

        def capture(request):
            import json
            captured.update(json.loads(request.content))
            return httpx.Response(200, json=_MOCK_LLM_STOP)

        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_MOCK_LLM_CLASSIFICATION),
                httpx.Response(200, json=_MOCK_LLM_TOOL_CALL),
                capture,
            ]
        )
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 1,
                    "result": {"protocolVersion": "2024-11-05", "capabilities": {}}
                }),
                httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 3,
                    "result": {"output": "A" * 20000},  # Large output
                }),
            ]
        )

        client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "big"})
        # Check that the tool result in the second LLM call is truncated
        if captured:
            assert "tools" not in captured
            assert "tool_choice" not in captured
            for msg in captured.get("messages", []):
                if msg.get("role") == "tool":
                    assert len(msg.get("content", "")) <= 200  # truncated

    @respx.mock
    def test_tool_executed_when_tool_calls_present_with_stop_finish_reason(self, client, llm_openai, monkeypatch):
        """Tool execution still runs when provider returns tool_calls with finish_reason='stop'."""
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_MOCK_LLM_CLASSIFICATION),
                httpx.Response(200, json=_MOCK_LLM_TOOL_CALL_STOP_REASON),
                httpx.Response(200, json=_MOCK_LLM_STOP),
            ]
        )
        mcp_route = respx.post("https://mcp.example.com/mcp").mock(
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

        r = client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "ping"})
        assert r.status_code == 200
        assert len(r.json()["tool_executions"]) == 1
        assert len(mcp_route.calls) == 2

    @respx.mock
    def test_ollama_tool_call_without_id_executes_mcp_tool(self, client, llm_ollama, monkeypatch):
        """Ollama tool_calls without id still dispatch to the MCP server."""
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_ollama)
        sid = client.post("/api/sessions").json()["session_id"]

        ollama_payloads = []

        def capture_ollama(request):
            import json
            ollama_payloads.append(json.loads(request.content))
            if len(ollama_payloads) == 1:
                return httpx.Response(200, json=_MOCK_LLM_CLASSIFICATION)
            if len(ollama_payloads) == 2:
                return httpx.Response(200, json=_MOCK_OLLAMA_TOOL_CALL)
            return httpx.Response(200, json=_MOCK_OLLAMA_STOP)

        respx.post("http://127.0.0.1:11434/api/chat").mock(side_effect=capture_ollama)
        mcp_route = respx.post("https://mcp.example.com/mcp").mock(
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

        r = client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "ping"})
        assert r.status_code == 200
        data = r.json()
        assert data["message"]["content"] == "Ping completed."
        assert len(data["tool_executions"]) == 1
        assert data["tool_executions"][0]["success"] is True
        assert len(mcp_route.calls) == 2
        assert len(ollama_payloads) == 3

        follow_up_messages = ollama_payloads[2]["messages"]
        assert all(msg["role"] != "tool" for msg in follow_up_messages)
        assert all("tool_calls" not in msg for msg in follow_up_messages)
        assert any(
            msg["role"] == "user" and "Tool result:" in msg["content"]
            for msg in follow_up_messages
        )

    @respx.mock
    def test_first_llm_request_includes_parallel_tool_calls_flag(self, client, llm_openai, monkeypatch):
        """TC-CHAT-14: First LLM request includes parallel_tool_calls=True when tools are available."""
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        captured_payloads = []

        def capture(request):
            import json
            captured_payloads.append(json.loads(request.content))
            if len(captured_payloads) == 1:
                return httpx.Response(200, json=_MOCK_LLM_CLASSIFICATION)
            return httpx.Response(200, json=_MOCK_LLM_STOP)

        respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=capture)
        client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "show system info"})

        assert len(captured_payloads) == 2
        assert "parallel_tool_calls" not in captured_payloads[0]
        assert captured_payloads[1].get("parallel_tool_calls") is True

    @respx.mock
    def test_second_llm_request_omits_parallel_tool_calls_flag(self, client, llm_openai, monkeypatch):
        """TC-CHAT-15: Follow-up LLM request after tool execution omits parallel_tool_calls (no tools in payload)."""
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        captured_payloads = []

        def capture(request):
            import json
            captured_payloads.append(json.loads(request.content))
            if len(captured_payloads) == 1:
                return httpx.Response(200, json=_MOCK_LLM_CLASSIFICATION)
            if len(captured_payloads) == 2:
                return httpx.Response(200, json=_MOCK_LLM_TOOL_CALL)
            return httpx.Response(200, json=_MOCK_LLM_STOP)

        respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=capture)
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

        client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "ping"})

        assert len(captured_payloads) == 3
        assert "parallel_tool_calls" not in captured_payloads[0]
        assert captured_payloads[1].get("parallel_tool_calls") is True
        follow_up = captured_payloads[2]
        # Tools are omitted on follow-up; parallel_tool_calls must also be absent
        assert "tools" not in follow_up
        assert "parallel_tool_calls" not in follow_up

    @respx.mock
    def test_two_distinct_tools_called_in_single_turn(self, client, llm_openai, monkeypatch):
        """TC-CHAT-16: LLM returning two distinct tool calls in one response executes both."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        client.post("/api/servers", json={
            "alias": "svc",
            "base_url": "https://mcp.example.com",
            "auth_type": "none",
        })
        from backend.models import ToolSchema
        main_module.mcp_manager.tools["svc__get_cpu"] = ToolSchema(
            namespaced_id="svc__get_cpu",
            server_alias="svc",
            name="get_cpu",
            description="Get CPU info",
        )
        main_module.mcp_manager.tools["svc__get_memory"] = ToolSchema(
            namespaced_id="svc__get_memory",
            server_alias="svc",
            name="get_memory",
            description="Get memory info",
        )

        client.post("/api/llm/config", json=llm_openai)
        sid = client.post("/api/sessions").json()["session_id"]

        respx.post("https://api.openai.com/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_MOCK_LLM_CLASSIFICATION),
                httpx.Response(200, json=_MOCK_LLM_TWO_TOOL_CALLS),
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
                    "jsonrpc": "2.0", "id": 2, "result": {"cpu_percent": 42}
                }),
                httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 3, "result": {"mem_used_mb": 1024}
                }),
            ]
        )

        r = client.post(f"/api/sessions/{sid}/messages", json={"role": "user", "content": "show CPU and memory"})
        assert r.status_code == 200
        data = r.json()
        executed_tools = [te["tool"] for te in data["tool_executions"]]
        assert "svc__get_cpu" in executed_tools
        assert "svc__get_memory" in executed_tools
        assert len(data["tool_executions"]) == 2


# ============================================================================
# TR-CHAT-3: Get Message History
# ============================================================================

class TestGetMessageHistory:

    def test_get_messages_returns_200(self, client):
        """TC-CHAT-17: GET /api/sessions/{id}/messages returns 200."""
        sid = client.post("/api/sessions").json()["session_id"]
        r = client.get(f"/api/sessions/{sid}/messages")
        assert r.status_code == 200

    def test_response_schema(self, client):
        """TC-CHAT-18: Response contains session_id and messages."""
        sid = client.post("/api/sessions").json()["session_id"]
        data = client.get(f"/api/sessions/{sid}/messages").json()
        assert "session_id" in data
        assert "messages" in data
