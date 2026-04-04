"""
Unit tests for SessionManager (TR-SESS-*, TR-FMT-*, TR-PERSIST-*)
"""

import json
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from backend.database import Base, ChatSessionRow, ChatMessageRow
from backend.session_manager import SessionManager, SimpleSession
from backend.models import ChatMessage, ToolCall, FunctionCall


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_factory(tmp_path):
    """Return a (engine, factory) pair backed by an isolated per-test SQLite file."""
    engine = create_engine(
        f"sqlite:///{tmp_path}/sm_unit.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return engine, factory


@pytest.fixture
def mgr(db_factory):
    """SessionManager backed by a per-test isolated SQLite database."""
    _engine, factory = db_factory
    return SessionManager(session_factory=factory)


# ---------------------------------------------------------------------------
# DB-level helpers used by persistence tests
# ---------------------------------------------------------------------------

def _db_session_count(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(ChatSessionRow)).scalar()


def _db_message_count(engine, session_id: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(ChatMessageRow).where(
                ChatMessageRow.session_id == session_id
            )
        ).scalar()


def _rebuild(factory) -> SessionManager:
    """Simulate a backend restart: fresh SessionManager with the same DB."""
    return SessionManager(session_factory=factory)


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

    def test_session_written_to_db(self, mgr, db_factory):
        """TC-SESS-DB-01: create_session writes a row to chat_sessions."""
        engine, _ = db_factory
        mgr.create_session("db-check")
        assert _db_session_count(engine) == 1

    def test_session_config_stored_in_db(self, mgr, db_factory):
        """TC-SESS-DB-02: create_session persists config JSON to DB."""
        engine, factory = db_factory
        mgr.create_session("cfg-sess", config={"theme": "dark"})
        with engine.connect() as conn:
            row = conn.execute(
                select(ChatSessionRow).where(ChatSessionRow.session_id == "cfg-sess")
            ).fetchone()
        assert json.loads(row.config_json) == {"theme": "dark"}

    def test_session_user_id_stored_in_db(self, mgr, db_factory):
        """TC-SESS-DB-03: create_session persists user_id to DB."""
        engine, _ = db_factory
        mgr.create_session("uid-sess", user_id="user-42")
        with engine.connect() as conn:
            row = conn.execute(
                select(ChatSessionRow).where(ChatSessionRow.session_id == "uid-sess")
            ).fetchone()
        assert row.user_id == "user-42"


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

    def test_delete_removes_session_row_from_db(self, mgr, db_factory):
        """TC-SESS-DB-10: delete_session removes the chat_sessions row."""
        engine, _ = db_factory
        s = mgr.create_session()
        assert _db_session_count(engine) == 1
        mgr.delete_session(s.session_id)
        assert _db_session_count(engine) == 0

    def test_delete_removes_message_rows_from_db(self, mgr, db_factory):
        """TC-SESS-DB-11: delete_session removes all chat_messages rows for the session."""
        engine, _ = db_factory
        s = mgr.create_session()
        for i in range(3):
            mgr.add_message(s.session_id, ChatMessage(role="user", content=str(i)))
        assert _db_message_count(engine, s.session_id) == 3
        mgr.delete_session(s.session_id)
        assert _db_message_count(engine, s.session_id) == 0


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

    def test_message_written_to_db(self, mgr, db_factory):
        """TC-SESS-DB-12: add_message writes a row to chat_messages."""
        engine, _ = db_factory
        s = mgr.create_session()
        mgr.add_message(s.session_id, ChatMessage(role="user", content="persisted"))
        assert _db_message_count(engine, s.session_id) == 1

    def test_multiple_messages_have_increasing_sequence_nums(self, mgr, db_factory):
        """TC-SESS-DB-13: sequence_num increases monotonically."""
        engine, _ = db_factory
        s = mgr.create_session()
        for i in range(4):
            mgr.add_message(s.session_id, ChatMessage(role="user", content=str(i)))
        with engine.connect() as conn:
            rows = conn.execute(
                select(ChatMessageRow.sequence_num).where(
                    ChatMessageRow.session_id == s.session_id
                ).order_by(ChatMessageRow.sequence_num)
            ).fetchall()
        assert [r[0] for r in rows] == [0, 1, 2, 3]

    def test_tool_call_id_persisted_to_db(self, mgr, db_factory):
        """TC-SESS-DB-14: tool_call_id is stored in the message row."""
        engine, _ = db_factory
        s = mgr.create_session()
        mgr.add_message(s.session_id, ChatMessage(role="tool", content="result", tool_call_id="call_xyz"))
        with engine.connect() as conn:
            row = conn.execute(
                select(ChatMessageRow).where(ChatMessageRow.session_id == s.session_id)
            ).fetchone()
        assert row.tool_call_id == "call_xyz"

    def test_tool_calls_serialised_as_json(self, mgr, db_factory):
        """TC-SESS-DB-15: tool_calls list is stored as JSON in tool_calls_json."""
        engine, _ = db_factory
        tc = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="svc__ping", arguments='{"host":"x"}'),
        )
        s = mgr.create_session()
        mgr.add_message(s.session_id, ChatMessage(role="assistant", content="", tool_calls=[tc]))
        with engine.connect() as conn:
            row = conn.execute(
                select(ChatMessageRow).where(ChatMessageRow.session_id == s.session_id)
            ).fetchone()
        tc_data = json.loads(row.tool_calls_json)
        assert len(tc_data) == 1
        assert tc_data[0]["id"] == "call_1"
        assert tc_data[0]["function"]["name"] == "svc__ping"


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


class TestRetrievalTrace:

    def test_retrieval_trace_stored_and_retrieved(self, mgr):
        """TC-TRACE-01: add_retrieval_trace stores a trace retrievable by session."""
        s = mgr.create_session()
        mgr.add_retrieval_trace(
            s.session_id,
            request_id="chat-1",
            query_hash="abc123",
            collection_keys=["code_memory", "doc_memory"],
            result_count=2,
            degraded=False,
            latency_ms=42.5,
            message_preview="explain the code",
        )

        traces = mgr.get_retrieval_traces(s.session_id)
        assert len(traces) == 1
        assert traces[0]["request_id"] == "chat-1"
        assert traces[0]["query_hash"] == "abc123"
        assert traces[0]["collection_keys"] == ["code_memory", "doc_memory"]
        assert traces[0]["result_count"] == 2
        assert traces[0]["degraded"] is False
        assert traces[0]["message_preview"] == "explain the code"
        assert "recorded_at" in traces[0]

    def test_get_retrieval_traces_empty_for_unknown_session(self, mgr):
        """TC-TRACE-02: Unknown sessions return an empty retrieval trace list."""
        assert mgr.get_retrieval_traces("ghost") == []

    def test_delete_session_cleans_retrieval_traces(self, mgr):
        """TC-TRACE-03: delete_session removes retrieval traces alongside other session state."""
        s = mgr.create_session()
        mgr.add_retrieval_trace(
            s.session_id,
            query_hash="abc123",
            collection_keys=["code_memory"],
            result_count=1,
            degraded=False,
        )

        mgr.delete_session(s.session_id)
        assert mgr.get_retrieval_traces(s.session_id) == []

    def test_multiple_retrieval_traces_preserve_order(self, mgr):
        """TC-TRACE-04: Retrieval traces accumulate in insertion order."""
        s = mgr.create_session()
        mgr.add_retrieval_trace(
            s.session_id,
            query_hash="first",
            collection_keys=["code_memory"],
            result_count=1,
            degraded=False,
        )
        mgr.add_retrieval_trace(
            s.session_id,
            query_hash="second",
            collection_keys=["doc_memory"],
            result_count=0,
            degraded=True,
            degraded_reason="timeout",
        )

        traces = mgr.get_retrieval_traces(s.session_id)
        assert [trace["query_hash"] for trace in traces] == ["first", "second"]


class TestTurnMetadata:

    def test_set_and_get_last_turn_metadata(self, mgr):
        """TC-TRACE-05: Last-turn metadata is stored and returned as a copy."""
        s = mgr.create_session()
        mgr.set_last_turn_metadata(s.session_id, {"query_hash": "abc123", "request_id": "chat-1"})

        metadata = mgr.get_last_turn_metadata(s.session_id)
        assert metadata == {"query_hash": "abc123", "request_id": "chat-1"}
        metadata["query_hash"] = "mutated"
        assert mgr.get_last_turn_metadata(s.session_id) == {"query_hash": "abc123", "request_id": "chat-1"}

    def test_delete_session_cleans_last_turn_metadata(self, mgr):
        """TC-TRACE-06: delete_session removes internal turn metadata."""
        s = mgr.create_session()
        mgr.set_last_turn_metadata(s.session_id, {"query_hash": "abc123"})

        mgr.delete_session(s.session_id)
        assert mgr.get_last_turn_metadata(s.session_id) is None


class TestUpdateSessionTitle:

    def test_title_updated(self, mgr):
        """TC-SESS-15: update_session_title returns True and updates title."""
        s = mgr.create_session()
        assert mgr.update_session_title(s.session_id, "My Chat") is True
        assert mgr.get_session(s.session_id).title == "My Chat"

    def test_title_not_found(self, mgr):
        """TC-SESS-16: update_session_title returns False for unknown ID."""
        assert mgr.update_session_title("ghost", "title") is False

    def test_title_written_to_db(self, mgr, db_factory):
        """TC-SESS-DB-15: update_session_title writes the new title to the DB row."""
        engine, _ = db_factory
        s = mgr.create_session()
        mgr.update_session_title(s.session_id, "Updated")
        with engine.connect() as conn:
            row = conn.execute(
                select(ChatSessionRow).where(ChatSessionRow.session_id == s.session_id)
            ).fetchone()
        assert row.title == "Updated"


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


class TestHistorySummary:

    def test_build_history_summary_includes_recent_messages_and_tools(self, mgr):
        """Summary mode captures recent requests, answers, and tool outcomes."""
        s = mgr.create_session()
        mgr.add_message(s.session_id, ChatMessage(role="user", content="check memory"))
        mgr.add_message(s.session_id, ChatMessage(role="assistant", content="Memory is low."))
        mgr.add_tool_trace(s.session_id, "svc__system_memory_free", {}, {"value": 60}, True)

        summary = mgr.build_history_summary(s.session_id)

        assert summary is not None
        assert "check memory" in summary
        assert "Memory is low." in summary
        assert "svc__system_memory_free" in summary

    def test_build_history_summary_respects_upto_index(self, mgr):
        """Summary mode excludes messages beyond the requested cutoff."""
        s = mgr.create_session()
        mgr.add_message(s.session_id, ChatMessage(role="user", content="first"))
        mgr.add_message(s.session_id, ChatMessage(role="assistant", content="reply one"))
        mgr.add_message(s.session_id, ChatMessage(role="user", content="second"))

        summary = mgr.build_history_summary(s.session_id, upto_index=2)

        assert summary is not None
        assert "first" in summary
        assert "reply one" in summary
        assert "second" not in summary


# ============================================================================
# TR-PERSIST-1: Survive backend restart (same DB factory)
# ============================================================================

class TestPersistence:
    """All tests create state on one SessionManager, then rebuild from the same
    factory to verify the data reloads correctly — exactly what happens when
    uvicorn restarts while the SQLite file is still on disk."""

    # --- Sessions ---

    def test_session_survives_restart(self, db_factory):
        """TC-PERSIST-01: Session created before restart is visible after restart."""
        _, factory = db_factory
        mgr1 = _rebuild(factory)
        s = mgr1.create_session("sess-a")

        mgr2 = _rebuild(factory)
        assert mgr2.get_session("sess-a") is not None
        assert mgr2.get_session("sess-a").session_id == "sess-a"

    def test_session_title_survives_restart(self, db_factory):
        """TC-PERSIST-02: Title updated before restart is correct after restart."""
        _, factory = db_factory
        mgr1 = _rebuild(factory)
        mgr1.create_session("titled")
        mgr1.update_session_title("titled", "Renamed Chat")

        mgr2 = _rebuild(factory)
        assert mgr2.get_session("titled").title == "Renamed Chat"

    def test_session_config_survives_restart(self, db_factory):
        """TC-PERSIST-03: Config dict persists through restart."""
        _, factory = db_factory
        mgr1 = _rebuild(factory)
        mgr1.create_session("cfg", config={"foo": "bar", "n": 42})

        mgr2 = _rebuild(factory)
        assert mgr2.get_session("cfg").config == {"foo": "bar", "n": 42}

    def test_session_user_id_survives_restart(self, db_factory):
        """TC-PERSIST-04: user_id persists through restart."""
        _, factory = db_factory
        mgr1 = _rebuild(factory)
        mgr1.create_session("usr", user_id="u-99")

        mgr2 = _rebuild(factory)
        assert mgr2.get_session("usr").user_id == "u-99"

    def test_multiple_sessions_all_survive_restart(self, db_factory):
        """TC-PERSIST-05: Multiple sessions all reload after restart."""
        _, factory = db_factory
        mgr1 = _rebuild(factory)
        ids = [mgr1.create_session().session_id for _ in range(4)]

        mgr2 = _rebuild(factory)
        reloaded = {s.session_id for s in mgr2.list_sessions()}
        assert set(ids) == reloaded

    # --- Messages ---

    def test_plain_messages_survive_restart(self, db_factory):
        """TC-PERSIST-10: Simple user/assistant messages reload correctly."""
        _, factory = db_factory
        mgr1 = _rebuild(factory)
        s = mgr1.create_session("msgs")
        mgr1.add_message("msgs", ChatMessage(role="user", content="hello"))
        mgr1.add_message("msgs", ChatMessage(role="assistant", content="world"))

        mgr2 = _rebuild(factory)
        loaded = mgr2.get_messages("msgs")
        assert len(loaded) == 2
        assert loaded[0].role == "user"
        assert loaded[0].content == "hello"
        assert loaded[1].role == "assistant"
        assert loaded[1].content == "world"

    def test_message_order_preserved_after_restart(self, db_factory):
        """TC-PERSIST-11: Message insertion order is restored correctly."""
        _, factory = db_factory
        mgr1 = _rebuild(factory)
        mgr1.create_session("order")
        for i in range(5):
            mgr1.add_message("order", ChatMessage(role="user", content=str(i)))

        mgr2 = _rebuild(factory)
        contents = [m.content for m in mgr2.get_messages("order")]
        assert contents == ["0", "1", "2", "3", "4"]

    def test_tool_call_id_survives_restart(self, db_factory):
        """TC-PERSIST-12: tool_call_id on a tool-role message reloads correctly."""
        _, factory = db_factory
        mgr1 = _rebuild(factory)
        mgr1.create_session("tcid")
        mgr1.add_message("tcid", ChatMessage(role="tool", content="42s", tool_call_id="call_abc"))

        mgr2 = _rebuild(factory)
        msg = mgr2.get_messages("tcid")[0]
        assert msg.tool_call_id == "call_abc"
        assert msg.content == "42s"

    def test_tool_calls_round_trip_after_restart(self, db_factory):
        """TC-PERSIST-13: tool_calls list on an assistant message reloads with correct structure."""
        _, factory = db_factory
        tc = ToolCall(
            id="call_99",
            type="function",
            function=FunctionCall(name="svc__get_uptime", arguments="{}"),
        )
        mgr1 = _rebuild(factory)
        mgr1.create_session("tc-rt")
        mgr1.add_message("tc-rt", ChatMessage(role="assistant", content="", tool_calls=[tc]))

        mgr2 = _rebuild(factory)
        msg = mgr2.get_messages("tc-rt")[0]
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].id == "call_99"
        assert msg.tool_calls[0].function.name == "svc__get_uptime"

    def test_mixed_conversation_round_trip(self, db_factory):
        """TC-PERSIST-14: A realistic multi-turn conversation reloads end-to-end."""
        _, factory = db_factory
        tc = ToolCall(
            id="call_x",
            type="function",
            function=FunctionCall(name="svc__ping", arguments='{"host":"1.2.3.4"}'),
        )
        mgr1 = _rebuild(factory)
        mgr1.create_session("conv")
        mgr1.add_message("conv", ChatMessage(role="user", content="ping 1.2.3.4"))
        mgr1.add_message("conv", ChatMessage(role="assistant", content="", tool_calls=[tc]))
        mgr1.add_message("conv", ChatMessage(role="tool", content="OK 12ms", tool_call_id="call_x"))
        mgr1.add_message("conv", ChatMessage(role="assistant", content="Ping succeeded in 12ms."))

        mgr2 = _rebuild(factory)
        msgs = mgr2.get_messages("conv")
        assert len(msgs) == 4
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"
        assert msgs[1].tool_calls[0].id == "call_x"
        assert msgs[2].role == "tool"
        assert msgs[2].tool_call_id == "call_x"
        assert msgs[3].role == "assistant"
        assert "12ms" in msgs[3].content

    # --- Delete + restart ---

    def test_deleted_session_absent_after_restart(self, db_factory):
        """TC-PERSIST-20: Deleted session does not reappear after restart."""
        _, factory = db_factory
        mgr1 = _rebuild(factory)
        mgr1.create_session("gone")
        mgr1.add_message("gone", ChatMessage(role="user", content="hi"))
        mgr1.delete_session("gone")

        mgr2 = _rebuild(factory)
        assert mgr2.get_session("gone") is None
        assert mgr2.get_messages("gone") == []

    def test_only_non_deleted_sessions_survive(self, db_factory):
        """TC-PERSIST-21: Deleting one session does not affect others after restart."""
        _, factory = db_factory
        mgr1 = _rebuild(factory)
        mgr1.create_session("keep")
        mgr1.create_session("drop")
        mgr1.add_message("keep", ChatMessage(role="user", content="stay"))
        mgr1.add_message("drop", ChatMessage(role="user", content="gone"))
        mgr1.delete_session("drop")

        mgr2 = _rebuild(factory)
        assert mgr2.get_session("keep") is not None
        assert mgr2.get_messages("keep")[0].content == "stay"
        assert mgr2.get_session("drop") is None

    # --- Edge cases ---

    def test_empty_manager_starts_empty_after_restart(self, db_factory):
        """TC-PERSIST-30: A fresh DB yields zero sessions after restart."""
        _, factory = db_factory
        mgr1 = _rebuild(factory)  # creates tables, no data
        mgr2 = _rebuild(factory)
        assert mgr2.list_sessions() == []

    def test_corrupt_tool_calls_json_skipped_gracefully(self, db_factory):
        """TC-PERSIST-31: A message row with invalid tool_calls_json loads without tool_calls."""
        engine, factory = db_factory
        # Write a session and a message row with corrupt JSON directly to the DB.
        with engine.connect() as conn:
            conn.execute(
                ChatSessionRow.__table__.insert().values(
                    session_id="corrupt",
                    title="Corrupt",
                    user_id=None,
                    config_json="{}",
                )
            )
            conn.execute(
                ChatMessageRow.__table__.insert().values(
                    session_id="corrupt",
                    sequence_num=0,
                    role="assistant",
                    content="",
                    tool_call_id=None,
                    tool_calls_json="{not valid json[",
                )
            )
            conn.commit()

        mgr = _rebuild(factory)
        msgs = mgr.get_messages("corrupt")
        assert len(msgs) == 1
        assert msgs[0].tool_calls is None  # corrupt JSON skipped, message still loaded

    def test_auto_created_session_survives_restart(self, db_factory):
        """TC-PERSIST-32: Session auto-created by add_message (unknown ID path) also persists."""
        _, factory = db_factory
        mgr1 = _rebuild(factory)
        mgr1.add_message("auto", ChatMessage(role="user", content="implicit"))

        mgr2 = _rebuild(factory)
        assert mgr2.get_session("auto") is not None
        assert mgr2.get_messages("auto")[0].content == "implicit"
