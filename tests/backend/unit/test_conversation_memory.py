"""Retention and scope tests for conversation memory persistence (TC-CMEM-*).

These tests validate:
  - Same-user recall returns only that user's turns
  - Cross-user recall is blocked (different user returns nothing)
  - Retention/expiry: expired turns are excluded from get_conversation_turns()
  - expire_conversation_turns() deletes old rows and returns correct count
  - Workspace scoping isolates turns to the right workspace
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.database import init_db
from backend.memory_persistence import MemoryPersistence


@pytest.fixture()
def persistence(tmp_path):
    """Return a MemoryPersistence backed by a fresh in-memory SQLite database."""
    import os
    db_file = tmp_path / "test_conv.db"
    os.environ["DB_URL"] = f"sqlite:///{db_file}"
    # Re-import to pick up the new DB_URL
    import importlib
    import backend.database as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=db_mod._engine, expire_on_commit=False)
    return MemoryPersistence(session_factory=factory)


def _now():
    return datetime.now(timezone.utc)


def _future(days: int = 7):
    return _now() + timedelta(days=days)


def _past(days: int = 1):
    return _now() - timedelta(days=days)


class TestConversationTurnRetention:

    def test_record_and_retrieve_basic_turn(self, persistence):
        """TC-CMEM-01: Basic insert + retrieval round-trip."""
        row = persistence.record_conversation_turn(
            session_id="sess-1",
            user_message="hello",
            assistant_summary="hi there",
            user_id="user-a",
            turn_number=0,
        )
        assert row.session_id == "sess-1"
        assert row.user_message == "hello"
        assert row.assistant_summary == "hi there"
        assert row.user_id == "user-a"

    def test_same_user_recall_returns_own_turns(self, persistence):
        """TC-CMEM-02: get_conversation_turns with user_id returns only that user's turns."""
        persistence.record_conversation_turn(
            session_id="sess-a",
            user_message="a message",
            assistant_summary="a reply",
            user_id="user-a",
        )
        persistence.record_conversation_turn(
            session_id="sess-b",
            user_message="b message",
            assistant_summary="b reply",
            user_id="user-b",
        )

        rows = persistence.get_conversation_turns(user_id="user-a")
        assert len(rows) == 1
        assert rows[0].user_id == "user-a"
        assert rows[0].user_message == "a message"

    def test_cross_user_recall_blocked(self, persistence):
        """TC-CMEM-03: user-b's turns are not visible when querying for user-a."""
        persistence.record_conversation_turn(
            session_id="sess-b",
            user_message="secret message",
            assistant_summary="secret reply",
            user_id="user-b",
        )

        rows = persistence.get_conversation_turns(user_id="user-a")
        assert rows == []

    def test_expired_turns_excluded_from_results(self, persistence):
        """TC-CMEM-04: Turns with expires_at in the past are excluded when not_expired_as_of is set."""
        persistence.record_conversation_turn(
            session_id="sess-1",
            user_message="old message",
            assistant_summary="old reply",
            user_id="user-a",
            expires_at=_past(days=1),  # already expired
        )
        persistence.record_conversation_turn(
            session_id="sess-1",
            user_message="new message",
            assistant_summary="new reply",
            user_id="user-a",
            expires_at=_future(days=7),  # still valid
        )

        rows = persistence.get_conversation_turns(
            user_id="user-a",
            not_expired_as_of=_now(),
        )
        assert len(rows) == 1
        assert rows[0].user_message == "new message"

    def test_no_expires_at_is_never_excluded(self, persistence):
        """TC-CMEM-05: Turns with expires_at=None are always returned (no expiry)."""
        persistence.record_conversation_turn(
            session_id="sess-1",
            user_message="eternal message",
            assistant_summary="eternal reply",
            user_id="user-a",
            expires_at=None,
        )

        rows = persistence.get_conversation_turns(
            user_id="user-a",
            not_expired_as_of=_now(),
        )
        assert len(rows) == 1
        assert rows[0].user_message == "eternal message"

    def test_expire_conversation_turns_by_user(self, persistence):
        """TC-CMEM-06: expire_conversation_turns deletes all turns for a given user."""
        for i in range(3):
            persistence.record_conversation_turn(
                session_id=f"sess-{i}",
                user_message=f"msg {i}",
                assistant_summary=f"reply {i}",
                user_id="user-delete",
            )
        persistence.record_conversation_turn(
            session_id="sess-other",
            user_message="other msg",
            assistant_summary="other reply",
            user_id="user-keep",
        )

        deleted = persistence.expire_conversation_turns(user_id="user-delete")
        assert deleted == 3

        remaining = persistence.get_conversation_turns(user_id="user-delete")
        assert remaining == []

        kept = persistence.get_conversation_turns(user_id="user-keep")
        assert len(kept) == 1

    def test_expire_conversation_turns_by_older_than(self, persistence):
        """TC-CMEM-07: expire_conversation_turns deletes turns older than given datetime."""
        persistence.record_conversation_turn(
            session_id="sess-1",
            user_message="old turn",
            assistant_summary="old reply",
            user_id="user-a",
            created_at=_past(days=10),
        )
        persistence.record_conversation_turn(
            session_id="sess-1",
            user_message="recent turn",
            assistant_summary="recent reply",
            user_id="user-a",
        )

        # Delete turns older than 5 days
        deleted = persistence.expire_conversation_turns(
            older_than=_now() - timedelta(days=5)
        )
        assert deleted == 1

        remaining = persistence.get_conversation_turns(user_id="user-a")
        assert len(remaining) == 1
        assert remaining[0].user_message == "recent turn"

    def test_expire_conversation_turns_requires_at_least_one_filter(self, persistence):
        """TC-CMEM-08: expire_conversation_turns raises if no filter provided."""
        with pytest.raises(ValueError, match="At least one of"):
            persistence.expire_conversation_turns()

    def test_workspace_scope_isolates_turns(self, persistence):
        """TC-CMEM-09: get_conversation_turns filters by workspace_scope."""
        persistence.record_conversation_turn(
            session_id="sess-1",
            user_message="ws-a message",
            assistant_summary="ws-a reply",
            user_id="user-a",
            workspace_scope="workspace-alpha",
        )
        persistence.record_conversation_turn(
            session_id="sess-2",
            user_message="ws-b message",
            assistant_summary="ws-b reply",
            user_id="user-a",
            workspace_scope="workspace-beta",
        )

        rows = persistence.get_conversation_turns(
            user_id="user-a",
            workspace_scope="workspace-alpha",
        )
        assert len(rows) == 1
        assert rows[0].workspace_scope == "workspace-alpha"
        assert rows[0].user_message == "ws-a message"

    def test_limit_caps_result_count(self, persistence):
        """TC-CMEM-10: limit parameter restricts the number of returned turns."""
        for i in range(5):
            persistence.record_conversation_turn(
                session_id="sess-1",
                user_message=f"msg {i}",
                assistant_summary=f"reply {i}",
                user_id="user-a",
            )

        rows = persistence.get_conversation_turns(user_id="user-a", limit=3)
        assert len(rows) == 3

    def test_record_turn_missing_session_id_raises(self, persistence):
        """TC-CMEM-11: Omitting session_id raises ValueError."""
        with pytest.raises(ValueError, match="session_id is required"):
            persistence.record_conversation_turn(
                session_id="",
                user_message="msg",
                assistant_summary="reply",
            )

    def test_record_turn_unknown_field_raises(self, persistence):
        """TC-CMEM-12: Passing an unknown field raises ValueError."""
        with pytest.raises(ValueError, match="Unknown conversation turn field"):
            persistence.record_conversation_turn(
                session_id="sess-1",
                user_message="msg",
                assistant_summary="reply",
                unknown_field_xyz="value",
            )

    def test_expire_conversation_turns_by_expired_as_of(self, persistence):
        """TC-CMEM-13: expire_conversation_turns(expired_as_of=...) deletes only expired rows."""
        persistence.record_conversation_turn(
            session_id="sess-old",
            user_message="expired msg",
            assistant_summary="expired reply",
            user_id="user-a",
            expires_at=_past(days=1),
        )
        persistence.record_conversation_turn(
            session_id="sess-new",
            user_message="live msg",
            assistant_summary="live reply",
            user_id="user-a",
            expires_at=_future(days=7),
        )

        deleted = persistence.expire_conversation_turns(expired_as_of=_now())

        assert deleted == 1
        rows = persistence.get_conversation_turns(user_id="user-a")
        assert len(rows) == 1
        assert rows[0].user_message == "live msg"

    def test_expire_conversation_turns_requires_any_filter_including_expired_as_of(self, persistence):
        """TC-CMEM-14: no filters still raises, but expired_as_of alone is accepted."""
        persistence.record_conversation_turn(
            session_id="sess-1",
            user_message="expired msg",
            assistant_summary="expired reply",
            user_id="user-a",
            expires_at=_past(days=1),
        )

        deleted = persistence.expire_conversation_turns(expired_as_of=_now())

        assert deleted == 1
