"""
Unit tests for SessionManager (TR-SESS-*, TR-FMT-*)
"""

import pytest
from backend.session_manager import SessionManager, SimpleSession
from backend.models import ChatMessage, ToolCall, FunctionCall


@pytest.fixture
def mgr():
    return SessionManager()


# ============================================================================
# TR-SESS-2: SessionManager core operations
# ============================================================================

class TestCreateSession:

    def test_auto_generates_uuid(self, mgr):
        """TC-SESS-06: create_session() without ID generates UUID session_id."""
        s = mgr.create_session()
        assert isinstance(s, SimpleSession)
        assert len(s.session_id) == 36  # UUID format

    def test_explicit_session_id(self, mgr):
        """TC-SESS-07: create_session() with explicit ID uses that value."""
        s = mgr.create_session("my-session")
        assert s.session_id == "my-session"

    def test_messages_initialized_empty(self, mgr):
        """TC-SESS-04: Newly created session has no messages."""
        s = mgr.create_session()
        assert mgr.get_messages(s.session_id) == []

    def test_tool_traces_initialized_empty(self, mgr):
        """TC-SESS-05: Newly created session has no traces."""
        s = mgr.create_session()
        assert mgr.get_tool_traces(s.session_id) == []

    def test_session_stored_in_manager(self, mgr):
        """TC-SESS-03: Created session retrievable via get_session."""
        s = mgr.create_session()
        assert mgr.get_session(s.session_id) is s

    def test_unique_session_ids(self, mgr):
        """TC-SESS-02: Multiple sessions get distinct IDs."""
        ids = {mgr.create_session().session_id for _ in range(5)}
        assert len(ids) == 5


class TestGetSession:

    def test_found(self, mgr):
        """TC-SESS-08: get_session returns existing session."""
        s = mgr.create_session()
        assert mgr.get_session(s.session_id) is s

    def test_not_found_returns_none(self, mgr):
        """TC-SESS-09: get_session returns None for unknown ID."""
        assert mgr.get_session("does-not-exist") is None


class TestDeleteSession:

    def test_delete_success(self, mgr):
        """TC-SESS-10: delete_session returns True and session is gone."""
        s = mgr.create_session()
        assert mgr.delete_session(s.session_id) is True
        assert mgr.get_session(s.session_id) is None

    def test_delete_not_found(self, mgr):
        """TC-SESS-11: delete_session returns False for unknown ID."""
        assert mgr.delete_session("ghost") is False

    def test_delete_cleans_messages_and_traces(self, mgr):
        """TC-SESS-10b: delete_session removes messages and traces."""
        s = mgr.create_session()
        mgr.add_message(s.session_id, ChatMessage(role="user", content="hi"))
        mgr.add_tool_trace(s.session_id, "tool", {}, "result", True)
        mgr.delete_session(s.session_id)
        assert mgr.get_messages(s.session_id) == []
        assert mgr.get_tool_traces(s.session_id) == []


class TestAddMessage:

    def test_message_stored(self, mgr):
        """TC-SESS-12: add_message stores message in session."""
        s = mgr.create_session()
        msg = ChatMessage(role="user", content="hello")
        mgr.add_message(s.session_id, msg)
        assert mgr.get_messages(s.session_id) == [msg]

    def test_auto_creates_session_if_missing(self, mgr):
        """TC-SESS-12b: add_message auto-creates session when not found."""
        mgr.add_message("new-id", ChatMessage(role="user", content="hi"))
        assert len(mgr.get_messages("new-id")) == 1

    def test_insertion_order_preserved(self, mgr):
        """TC-SESS-13: Messages returned in insertion order."""
        s = mgr.create_session()
        for i in range(3):
            mgr.add_message(s.session_id, ChatMessage(role="user", content=str(i)))
        contents = [m.content for m in mgr.get_messages(s.session_id)]
        assert contents == ["0", "1", "2"]


class TestToolTrace:

    def test_trace_stored_and_retrieved(self, mgr):
        """TC-SESS-14: add_tool_trace stores trace retrievable via get_tool_traces."""
        s = mgr.create_session()
        mgr.add_tool_trace(s.session_id, "ping", {"host": "1.2.3.4"}, "ok", True)
        traces = mgr.get_tool_traces(s.session_id)
        assert len(traces) == 1
        t = traces[0]
        assert t["tool_name"] == "ping"
        assert t["arguments"] == {"host": "1.2.3.4"}
        assert t["result"] == "ok"
        assert t["success"] is True

    def test_trace_has_timestamp(self, mgr):
        """TC-SESS-14b: Trace entry contains timestamp."""
        s = mgr.create_session()
        mgr.add_tool_trace(s.session_id, "ping", {}, "ok", True)
        assert "timestamp" in mgr.get_tool_traces(s.session_id)[0]


class TestUpdateSessionTitle:

    def test_title_updated(self, mgr):
        """TC-SESS-15: update_session_title returns True and updates title."""
        s = mgr.create_session()
        assert mgr.update_session_title(s.session_id, "My Chat") is True
        assert mgr.get_session(s.session_id).title == "My Chat"

    def test_title_not_found(self, mgr):
        """TC-SESS-16: update_session_title returns False for unknown ID."""
        assert mgr.update_session_title("ghost", "title") is False


# ============================================================================
# TR-FMT-1: get_messages_for_llm — message formatting
# ============================================================================

class TestGetMessagesForLLM:

    def _session_with(self, mgr, *messages):
        s = mgr.create_session()
        for m in messages:
            mgr.add_message(s.session_id, m)
        return s.session_id

    # --- OpenAI format ---

    def test_openai_user_message(self, mgr):
        """TC-FMT-01: OpenAI user message formatted correctly."""
        sid = self._session_with(mgr, ChatMessage(role="user", content="hello"))
        msgs = mgr.get_messages_for_llm(sid, "openai")
        assert msgs == [{"role": "user", "content": "hello"}]

    def test_openai_tool_result_includes_tool_call_id(self, mgr):
        """TC-FMT-02: OpenAI tool message keeps tool_call_id."""
        sid = self._session_with(
            mgr, ChatMessage(role="tool", content="pong", tool_call_id="call_1")
        )
        msgs = mgr.get_messages_for_llm(sid, "openai")
        assert msgs[0]["tool_call_id"] == "call_1"

    def test_openai_tool_calls_included(self, mgr):
        """TC-FMT-03: OpenAI assistant message with tool_calls serialized."""
        tc = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="svc__ping", arguments='{"host":"x"}'),
        )
        sid = self._session_with(
            mgr, ChatMessage(role="assistant", content="", tool_calls=[tc])
        )
        msgs = mgr.get_messages_for_llm(sid, "openai")
        assert "tool_calls" in msgs[0]
        assert msgs[0]["tool_calls"][0]["id"] == "call_1"

    # --- Ollama format ---

    def test_enterprise_tool_result_includes_tool_call_id(self, mgr):
        """TC-FMT-07: Enterprise tool message keeps tool_call_id (gateway requires it)."""
        sid = self._session_with(
            mgr, ChatMessage(role="tool", content="5611.23 8841.99", tool_call_id="call_HKIrE8Ck")
        )
        msgs = mgr.get_messages_for_llm(sid, "enterprise")
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["tool_call_id"] == "call_HKIrE8Ck"

    def test_enterprise_tool_calls_included_in_assistant(self, mgr):
        """TC-FMT-08: Enterprise assistant message with tool_calls serialized (OpenAI-compatible)."""
        tc = ToolCall(
            id="call_HKIrE8Ck",
            type="function",
            function=FunctionCall(name="map_api__get_system_uptime", arguments="{}"),
        )
        sid = self._session_with(
            mgr, ChatMessage(role="assistant", content="", tool_calls=[tc])
        )
        msgs = mgr.get_messages_for_llm(sid, "enterprise")
        assert "tool_calls" in msgs[0]
        assert msgs[0]["tool_calls"][0]["id"] == "call_HKIrE8Ck"

    def test_ollama_tool_converted_to_user(self, mgr):
        """TC-FMT-04: Ollama converts tool role to user with prefix."""
        sid = self._session_with(
            mgr, ChatMessage(role="tool", content="pong", tool_call_id="call_1")
        )
        msgs = mgr.get_messages_for_llm(sid, "ollama")
        assert msgs[0]["role"] == "user"
        assert "pong" in msgs[0]["content"]

    def test_ollama_no_tool_call_id(self, mgr):
        """TC-FMT-06: Ollama output never contains tool_call_id."""
        sid = self._session_with(
            mgr, ChatMessage(role="user", content="hi"),
            ChatMessage(role="tool", content="result", tool_call_id="call_1"),
        )
        msgs = mgr.get_messages_for_llm(sid, "ollama")
        for m in msgs:
            assert "tool_call_id" not in m

    def test_ollama_skips_assistant_with_only_tool_calls(self, mgr):
        """TC-FMT-05: Ollama replaces a tool-calls-only assistant message with a synthetic
        placeholder to prevent consecutive user messages in the history."""
        tc = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="svc__ping", arguments="{}"),
        )
        sid = self._session_with(
            mgr, ChatMessage(role="assistant", content="", tool_calls=[tc])
        )
        msgs = mgr.get_messages_for_llm(sid, "ollama")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert "tools" in msgs[0]["content"].lower() or "check" in msgs[0]["content"].lower()

    def test_none_content_becomes_empty_string(self, mgr):
        """TC-FMT-07: None content is converted to empty string."""
        s = mgr.create_session()
        msg = ChatMessage(role="assistant", content="placeholder")
        msg.content = None  # Force None after construction
        mgr.add_message(s.session_id, msg)
        msgs = mgr.get_messages_for_llm(s.session_id, "openai")
        assert msgs[0]["content"] == ""

    def test_empty_session_returns_empty_list(self, mgr):
        """TC-FMT-09: Session with no messages returns []."""
        s = mgr.create_session()
        assert mgr.get_messages_for_llm(s.session_id, "openai") == []

    def test_order_preserved(self, mgr):
        """TC-FMT-08: Message order matches insertion order."""
        s = mgr.create_session()
        roles = ["user", "assistant", "user"]
        for role in roles:
            mgr.add_message(s.session_id, ChatMessage(role=role, content=role))
        msgs = mgr.get_messages_for_llm(s.session_id, "openai")
        assert [m["role"] for m in msgs] == roles

    def test_start_index_limits_history_scope(self, mgr):
        """Only messages from start_index onward are formatted for the LLM."""
        s = mgr.create_session()
        mgr.add_message(s.session_id, ChatMessage(role="user", content="old"))
        mgr.add_message(s.session_id, ChatMessage(role="assistant", content="old reply"))
        mgr.add_message(s.session_id, ChatMessage(role="user", content="new"))
        msgs = mgr.get_messages_for_llm(s.session_id, "openai", start_index=2)
        assert msgs == [{"role": "user", "content": "new"}]
