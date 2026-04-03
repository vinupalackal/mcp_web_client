"""Integration tests for memory retrieval wiring in the chat flow."""

import respx
import httpx
import backend.main as main_module
from backend.memory_service import RetrievalBlock, RetrievalResult, ToolCacheResult


class _CapturingLLMClient:
    def __init__(self, response_text="Memory-aware answer"):
        self.response_text = response_text
        self.calls = []

    async def chat_completion(self, messages, tools):
        self.calls.append({"messages": list(messages), "tools": list(tools)})
        return {
            "choices": [{
                "message": {"role": "assistant", "content": self.response_text},
                "finish_reason": "stop",
            }],
            "usage": {},
        }

    def format_tool_result(self, tool_call_id, content):
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


class _FakeMemoryService:
    def __init__(self, result: RetrievalResult):
        self.result = result
        self.calls = []
        self.record_turn_calls = []

    async def enrich_for_turn(self, *, user_message, session_id, repo_id=None, request_id=None, user_id="", workspace_scope="", include_code_memory=True):
        self.calls.append(
            {
                "user_message": user_message,
                "session_id": session_id,
                "repo_id": repo_id,
                "request_id": request_id,
                "include_code_memory": include_code_memory,
            }
        )
        return self.result

    async def record_turn(self, **kwargs):
        self.record_turn_calls.append(kwargs)

    async def resolve_tools_from_memory(self, *, user_message, user_id="", available_tool_names, request_id="", similarity_threshold=0.30):
        return []  # No memory-based tool routing in these tests; fall through to LLM.

    def lookup_tool_cache(self, *, tool_name, arguments, user_id="", workspace_scope=""):
        return ToolCacheResult()  # always miss — never block tool execution in tests

    def record_tool_cache(self, *, tool_name, arguments, result_text, user_id="", workspace_scope=""):
        pass  # no-op

    async def health_status(self):
        return {"enabled": True, "healthy": True, "degraded": False, "active_collections": []}


class TestMemoryRetrievalFlow:

    def test_chat_memory_disabled_is_no_op(self, client, llm_mock):
        """TC-FLOW-01: Chat succeeds with memory disabled and stores no retrieval traces."""
        client.post("/api/llm/config", json=llm_mock)
        session_id = client.post("/api/sessions").json()["session_id"]

        response = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"role": "user", "content": "explain the code"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"]["role"] == "assistant"
        assert main_module.session_manager.get_retrieval_traces(session_id) == []

    def test_chat_memory_success_records_trace_and_injects_context(self, client, llm_mock, monkeypatch):
        """TC-FLOW-02: Successful retrieval records a trace and injects retrieved context into LLM messages."""
        client.post("/api/llm/config", json=llm_mock)
        session_id = client.post("/api/sessions").json()["session_id"]

        fake_llm = _CapturingLLMClient(response_text="Retrieved context was used.")
        monkeypatch.setattr(main_module.LLMClientFactory, "create", lambda *args, **kwargs: fake_llm)
        main_module._memory_service = _FakeMemoryService(
            RetrievalResult(
                blocks=[
                    RetrievalBlock(
                        payload_ref="payload://code/repo/src/main.c#main",
                        collection="code_memory",
                        score=0.01,
                        snippet="main entry point",
                        source_path="src/main.c",
                    ),
                    RetrievalBlock(
                        payload_ref="payload://doc/repo/README.md#usage",
                        collection="doc_memory",
                        score=0.02,
                        snippet="usage documentation",
                        source_path="README.md",
                    ),
                ],
                degraded=False,
                degraded_reason="",
                latency_ms=12.5,
                query_hash="hash1234",
                collection_keys=("code_memory", "doc_memory"),
            )
        )

        response = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"role": "user", "content": "explain the code"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["message"]["content"] == "Retrieved context was used."
        assert payload["transaction_id"].startswith("chat-")
        assert payload["retrieval_trace"]["request_id"] == payload["transaction_id"]
        assert payload["retrieval_trace"]["result_count"] == 2
        traces = main_module.session_manager.get_retrieval_traces(session_id)
        assert len(traces) == 1
        assert traces[0]["request_id"] == payload["transaction_id"]
        assert traces[0]["result_count"] == 2
        assert traces[0]["degraded"] is False
        assert traces[0]["query_hash"] == "hash1234"

        sent_messages = fake_llm.calls[0]["messages"]
        assert sent_messages[0]["role"] == "system"
        assert "## Retrieved context" in sent_messages[0]["content"]
        assert "src/main.c (code_memory)" in sent_messages[0]["content"]
        assert "usage documentation" in sent_messages[0]["content"]

    def test_chat_memory_empty_results_records_zero_count(self, client, llm_mock, monkeypatch):
        """TC-FLOW-03: Non-degraded empty retrieval still records a zero-result trace."""
        client.post("/api/llm/config", json=llm_mock)
        session_id = client.post("/api/sessions").json()["session_id"]

        fake_llm = _CapturingLLMClient(response_text="No retrieved context needed.")
        monkeypatch.setattr(main_module.LLMClientFactory, "create", lambda *args, **kwargs: fake_llm)
        main_module._memory_service = _FakeMemoryService(
            RetrievalResult(
                blocks=[],
                degraded=False,
                degraded_reason="",
                latency_ms=8.1,
                query_hash="hash-empty",
                collection_keys=("code_memory", "doc_memory"),
            )
        )

        response = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"role": "user", "content": "explain the code"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["transaction_id"].startswith("chat-")
        assert payload["retrieval_trace"]["request_id"] == payload["transaction_id"]
        assert payload["retrieval_trace"]["result_count"] == 0
        traces = main_module.session_manager.get_retrieval_traces(session_id)
        assert len(traces) == 1
        assert traces[0]["request_id"] == payload["transaction_id"]
        assert traces[0]["result_count"] == 0
        assert traces[0]["degraded"] is False


# ---------------------------------------------------------------------------
# Helpers for synthesis-timing tests
# ---------------------------------------------------------------------------

class _ToolAwareCapturingLLMClient:
    """Two-turn LLM stub.

    Behaviour:
    - First ``chat_completion`` call that receives a **non-empty** ``tools``
      list returns a tool-call response (``finish_reason='tool_calls'``).
    - Every other call (classification preamble, synthesis turn) returns a
      plain stop response.

    This mirrors the real multi-turn flow:
      [optional classification with tools=[]] →
      [tool-catalog call with tools=[...]] →
      [synthesis call with tools=[]]
    without needing HTTP mocks for the LLM layer.
    """

    def __init__(self, synthesis_content: str = "Synthesis answer with code context."):
        self.calls: list = []
        self._tool_call_fired = False
        self.synthesis_content = synthesis_content

    async def chat_completion(self, messages, tools):
        self.calls.append({"messages": list(messages), "tools": list(tools)})
        if tools and not self._tool_call_fired:
            self._tool_call_fired = True
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": "call_synth_test_001",
                            "type": "function",
                            "function": {
                                "name": "svc__ping",
                                "arguments": '{"host": "1.2.3.4"}',
                            },
                        }],
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {},
            }
        # classification preamble OR synthesis turn — both return stop
        return {
            "choices": [{
                "message": {"role": "assistant", "content": self.synthesis_content},
                "finish_reason": "stop",
            }],
            "usage": {},
        }

    def format_tool_result(self, tool_call_id, content):
        return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


class _SynthesisAwareFakeMemoryService(_FakeMemoryService):
    """Fake memory service that differentiates planning vs synthesis retrievals.

    - ``include_code_memory=False``  (planning phase) → returns ``self.result``
      (empty blocks by default so no context is injected before the tool call).
    - ``include_code_memory=True``   (synthesis phase) → returns
      ``self.synthesis_result`` (rich blocks so the test can assert they appear
      in the synthesis LLM call's messages).
    """

    def __init__(self, synthesis_result: RetrievalResult):
        empty = RetrievalResult(
            blocks=[],
            degraded=False,
            degraded_reason="",
            latency_ms=0.0,
            query_hash="",
            collection_keys=(),
        )
        super().__init__(empty)
        self.synthesis_result = synthesis_result

    async def enrich_for_turn(
        self,
        *,
        user_message,
        session_id,
        repo_id=None,
        request_id=None,
        user_id="",
        workspace_scope="",
        include_code_memory=True,
    ):
        self.calls.append(
            {
                "user_message": user_message,
                "session_id": session_id,
                "repo_id": repo_id,
                "request_id": request_id,
                "include_code_memory": include_code_memory,
            }
        )
        if include_code_memory:
            return self.synthesis_result
        return self.result  # empty — planning phase


# ---------------------------------------------------------------------------
# Tests: synthesis retrieval timing
# ---------------------------------------------------------------------------

class TestSynthesisRetrievalTiming:
    """Verify that synthesis enrich_for_turn fires BEFORE the synthesis LLM call.

    Regression guard for the bug where synthesis retrieval ran AFTER
    ``finish_reason=stop``, making the 241 ms Milvus search completely wasted.
    """

    def _setup_server_and_tool(self, client, monkeypatch):
        """Register a fake MCP server + svc__ping tool."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        client.post("/api/servers", json={
            "alias": "svc",
            "base_url": "https://mcp.example.com",
            "auth_type": "none",
        })
        from backend.models import ToolSchema
        main_module.mcp_manager.tools["svc__ping"] = ToolSchema(
            namespaced_id="svc__ping",
            server_alias="svc",
            name="ping",
            description="Ping a host and report latency.",
        )

    @respx.mock
    def test_synthesis_context_injected_before_synthesis_llm_call(
        self, client, llm_mock, monkeypatch
    ):
        """TC-FLOW-04: After tool execution the synthesis enrich_for_turn fires BEFORE
        the synthesis LLM call, so the code-memory context is present in the messages
        that the synthesis LLM actually receives.

        Failure mode caught: synthesis retrieval was in the ``else`` branch (post
        ``finish_reason=stop``), so the injected context was never seen by any LLM call.
        """
        self._setup_server_and_tool(client, monkeypatch)
        client.post("/api/llm/config", json=llm_mock)
        session_id = client.post("/api/sessions").json()["session_id"]

        # LLM stub: tool-catalog call → tool_calls; everything else → stop
        fake_llm = _ToolAwareCapturingLLMClient(
            synthesis_content="Pong succeeded. Here is the code context."
        )
        monkeypatch.setattr(
            main_module.LLMClientFactory, "create", lambda *a, **kw: fake_llm
        )

        # Memory stub: empty for planning, rich block for synthesis
        synthesis_block = RetrievalBlock(
            payload_ref="payload://code/repo/src/ping.c#ping_impl",
            collection="code_memory",
            score=0.05,
            snippet="ping implementation detail from source",
            source_path="src/ping.c",
        )
        fake_memory = _SynthesisAwareFakeMemoryService(
            synthesis_result=RetrievalResult(
                blocks=[synthesis_block],
                degraded=False,
                degraded_reason="",
                latency_ms=15.0,
                query_hash="synth-qhash-001",
                collection_keys=("code_memory",),
            )
        )
        main_module._memory_service = fake_memory

        # MCP HTTP mock: initialize handshake + tool execution result
        respx.post("https://mcp.example.com/mcp").mock(
            side_effect=[
                httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 1,
                    "result": {"protocolVersion": "2024-11-05", "capabilities": {}},
                }),
                httpx.Response(200, json={
                    "jsonrpc": "2.0", "id": 3,
                    "result": {"output": "pong from 1.2.3.4"},
                }),
            ]
        )

        response = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"role": "user", "content": "ping 1.2.3.4"},
        )

        assert response.status_code == 200
        data = response.json()

        # At least one tool must have been executed for the fix to be testable
        assert len(data["tool_executions"]) >= 1, (
            "No tools were executed; cannot validate synthesis retrieval timing"
        )

        # --- Verify synthesis enrich_for_turn was called with include_code_memory=True ---
        synthesis_memory_calls = [
            c for c in fake_memory.calls if c["include_code_memory"]
        ]
        assert len(synthesis_memory_calls) >= 1, (
            "enrich_for_turn(include_code_memory=True) was never called — "
            "synthesis retrieval did not fire"
        )

        # --- Verify planning enrich_for_turn was called with include_code_memory=False ---
        planning_memory_calls = [
            c for c in fake_memory.calls if not c["include_code_memory"]
        ]
        assert len(planning_memory_calls) >= 1, (
            "enrich_for_turn(include_code_memory=False) was never called — "
            "planning retrieval did not fire"
        )

        # --- Core assertion: the synthesis LLM call's messages contain the context ---
        # The last call to the LLM is always the synthesis turn.
        synthesis_llm_messages = fake_llm.calls[-1]["messages"]
        context_injected = any(
            "## Retrieved context" in (msg.get("content") or "")
            for msg in synthesis_llm_messages
        )
        assert context_injected, (
            "Synthesis LLM call did NOT receive '## Retrieved context' in its messages. "
            "The synthesis retrieval result was injected too late (after finish_reason=stop). "
            f"Last LLM call message previews: "
            f"{[str(m.get('content', ''))[:120] for m in synthesis_llm_messages]}"
        )

    def test_synthesis_retrieval_skipped_when_no_tools_executed(
        self, client, llm_mock, monkeypatch
    ):
        """TC-FLOW-05: When the LLM responds stop without calling any tools,
        the synthesis enrich_for_turn (include_code_memory=True) is never called
        — only the planning retrieval fires (include_code_memory=False).

        This validates the guard ``if _memory_service is not None and tool_executions:``
        that prevents a wasted Milvus search when there are no tool results to enrich.
        """
        client.post("/api/llm/config", json=llm_mock)
        session_id = client.post("/api/sessions").json()["session_id"]

        # Always-stop client: never requests tools → tool_executions stays empty
        always_stop = _CapturingLLMClient(response_text="Direct answer, no tools needed.")
        monkeypatch.setattr(
            main_module.LLMClientFactory, "create", lambda *a, **kw: always_stop
        )

        fake_memory = _SynthesisAwareFakeMemoryService(
            synthesis_result=RetrievalResult(
                blocks=[],  # irrelevant — should never be queried
                degraded=False,
                degraded_reason="",
                latency_ms=0.0,
                query_hash="",
                collection_keys=(),
            )
        )
        main_module._memory_service = fake_memory

        response = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"role": "user", "content": "what is 2 + 2"},
        )

        assert response.status_code == 200
        assert response.json()["message"]["content"] == "Direct answer, no tools needed."

        # No tools were executed → synthesis guard must prevent the synthesis retrieval
        synthesis_calls = [c for c in fake_memory.calls if c["include_code_memory"]]
        assert len(synthesis_calls) == 0, (
            f"enrich_for_turn(include_code_memory=True) was unexpectedly called "
            f"{len(synthesis_calls)} time(s) despite no tool executions"
        )

        # Planning retrieval should still have fired
        planning_calls = [c for c in fake_memory.calls if not c["include_code_memory"]]
        assert len(planning_calls) >= 1, (
            "enrich_for_turn(include_code_memory=False) never fired — "
            "planning retrieval is broken"
        )
