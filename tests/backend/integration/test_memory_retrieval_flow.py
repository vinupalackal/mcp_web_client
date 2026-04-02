"""Integration tests for memory retrieval wiring in the chat flow."""

import backend.main as main_module
from backend.memory_service import RetrievalBlock, RetrievalResult


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

    async def enrich_for_turn(self, *, user_message, session_id, repo_id=None, request_id=None, user_id="", workspace_scope=""):
        self.calls.append(
            {
                "user_message": user_message,
                "session_id": session_id,
                "repo_id": repo_id,
                "request_id": request_id,
            }
        )
        return self.result

    async def record_turn(self, **kwargs):
        self.record_turn_calls.append(kwargs)

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
        assert response.json()["message"]["content"] == "Retrieved context was used."
        traces = main_module.session_manager.get_retrieval_traces(session_id)
        assert len(traces) == 1
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
        traces = main_module.session_manager.get_retrieval_traces(session_id)
        assert len(traces) == 1
        assert traces[0]["result_count"] == 0
        assert traces[0]["degraded"] is False
