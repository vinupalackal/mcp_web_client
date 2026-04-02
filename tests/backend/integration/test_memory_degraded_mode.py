"""Integration tests for degraded memory behavior."""

import backend.main as main_module
from backend.memory_service import RetrievalResult


class _CapturingLLMClient:
    def __init__(self, response_text="Fallback answer"):
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
        self.record_turn_calls = []

    async def enrich_for_turn(self, *, user_message, session_id, repo_id=None, request_id=None, user_id="", workspace_scope=""):
        return self.result

    async def record_turn(self, **kwargs):
        self.record_turn_calls.append(kwargs)

    async def health_status(self):
        return {
            "enabled": True,
            "healthy": False,
            "degraded": True,
            "status": "degraded",
            "reason": self.result.degraded_reason or "fake degraded",
            "warnings": ["Memory degraded mode is active"],
            "milvus_reachable": False,
            "embedding_available": True,
            "active_collections": [],
        }


class TestMemoryDegradedMode:

    def test_degraded_retrieval_does_not_fail_chat(self, client, llm_mock, monkeypatch):
        """TC-DEGRADE-01: Degraded retrieval still returns a valid chat response and trace."""
        client.post("/api/llm/config", json=llm_mock)
        session_id = client.post("/api/sessions").json()["session_id"]

        fake_llm = _CapturingLLMClient(response_text="Answer without retrieval context.")
        monkeypatch.setattr(main_module.LLMClientFactory, "create", lambda *args, **kwargs: fake_llm)
        main_module._memory_service = _FakeMemoryService(
            RetrievalResult(
                blocks=[],
                degraded=True,
                degraded_reason="fake degraded",
                latency_ms=50.0,
                query_hash="hash-degraded",
                collection_keys=("code_memory", "doc_memory"),
            )
        )

        response = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"role": "user", "content": "diagnose startup issue"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"]["role"] == "assistant"
        assert data["message"]["content"] == "Answer without retrieval context."

        traces = main_module.session_manager.get_retrieval_traces(session_id)
        assert len(traces) == 1
        assert traces[0]["degraded"] is True
        assert traces[0]["degraded_reason"] == "fake degraded"

        sent_messages = fake_llm.calls[0]["messages"]
        assert "## Retrieved context" not in sent_messages[0]["content"]

    def test_memory_none_is_safe_for_health_and_chat(self, client, llm_mock):
        """TC-DEGRADE-02: Memory unavailable at startup leaves health and chat on the safe no-op path."""
        client.post("/api/llm/config", json=llm_mock)
        session_id = client.post("/api/sessions").json()["session_id"]

        health = client.get("/health")
        chat = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"role": "user", "content": "hello"},
        )

        assert health.status_code == 200
        assert health.json()["memory"] == {"enabled": False}
        assert chat.status_code == 200
        assert chat.json()["message"]["role"] == "assistant"
