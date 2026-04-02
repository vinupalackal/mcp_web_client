"""Tool cache persistence tests (TC-TCACHE-*).

Validates:
  - record + lookup round-trip with correct key matching
  - Expired entries are excluded
  - Scope isolation (different scope_hash produces miss)
  - expire_tool_cache_entries() deletes by tool_name, scope_hash, older_than
  - Safety guard: expire with no filters raises ValueError
  - Upsert behaviour: second write updates result_text
  - Unknown field raises ValueError
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.database import init_db
from backend.memory_persistence import MemoryPersistence


@pytest.fixture()
def persistence(tmp_path):
    import os
    db_file = tmp_path / "test_toolcache.db"
    os.environ["DB_URL"] = f"sqlite:///{db_file}"
    import importlib
    import backend.database as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=db_mod._engine, expire_on_commit=False)
    return MemoryPersistence(session_factory=factory)


def _now():
    return datetime.now(timezone.utc)


def _future(seconds: int = 3600):
    return _now() + timedelta(seconds=seconds)


def _past(seconds: int = 10):
    return _now() - timedelta(seconds=seconds)


class TestToolCachePersistence:

    def test_record_and_lookup_roundtrip(self, persistence):
        """TC-TCACHE-01: insert then retrieve returns same result_text."""
        persistence.record_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="abc123",
            scope_hash="scope1",
            result_text='{"temp": 20}',
            is_cacheable=True,
            expires_at=_future(),
        )
        row = persistence.get_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="abc123",
            scope_hash="scope1",
        )
        assert row is not None
        assert row.result_text == '{"temp": 20}'
        assert row.is_cacheable is True

    def test_miss_for_different_params_hash(self, persistence):
        """TC-TCACHE-02: different params_hash produces a cache miss."""
        persistence.record_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-london",
            scope_hash="scope1",
            result_text="london result",
            is_cacheable=True,
            expires_at=_future(),
        )
        row = persistence.get_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-paris",  # different
            scope_hash="scope1",
        )
        assert row is None

    def test_miss_for_different_scope_hash(self, persistence):
        """TC-TCACHE-03: different scope_hash produces a miss (scope isolation)."""
        persistence.record_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-abc",
            scope_hash="scope-user-a",
            result_text="result for A",
            is_cacheable=True,
            expires_at=_future(),
        )
        row = persistence.get_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-abc",
            scope_hash="scope-user-b",  # different user scope
        )
        assert row is None

    def test_expired_entry_is_excluded(self, persistence):
        """TC-TCACHE-04: entry with expires_at in the past is excluded by not_expired_as_of."""
        persistence.record_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-abc",
            scope_hash="scope1",
            result_text="stale result",
            is_cacheable=True,
            expires_at=_past(seconds=1),
        )
        row = persistence.get_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-abc",
            scope_hash="scope1",
            not_expired_as_of=_now(),
        )
        assert row is None

    def test_no_expires_at_never_excluded(self, persistence):
        """TC-TCACHE-05: entry with expires_at=None is always returned."""
        persistence.record_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-abc",
            scope_hash="scope1",
            result_text="permanent result",
            is_cacheable=True,
            expires_at=None,
        )
        row = persistence.get_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-abc",
            scope_hash="scope1",
            not_expired_as_of=_now(),
        )
        assert row is not None
        assert row.result_text == "permanent result"

    def test_upsert_updates_result_text(self, persistence):
        """TC-TCACHE-06: second record call with same key overwrites result_text."""
        persistence.record_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-abc",
            scope_hash="scope1",
            result_text="old result",
            is_cacheable=True,
        )
        persistence.record_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-abc",
            scope_hash="scope1",
            result_text="new result",
            is_cacheable=True,
        )
        row = persistence.get_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-abc",
            scope_hash="scope1",
        )
        assert row is not None
        assert row.result_text == "new result"

    def test_expire_by_tool_name(self, persistence):
        """TC-TCACHE-07: expire_tool_cache_entries by tool_name deletes only that tool's entries."""
        for i in range(3):
            persistence.record_tool_cache_entry(
                tool_name="weather_tool",
                normalized_params_hash=f"hash-{i}",
                scope_hash=f"scope-{i}",
                result_text=f"result {i}",
                is_cacheable=True,
            )
        persistence.record_tool_cache_entry(
            tool_name="other_tool",
            normalized_params_hash="hash-x",
            scope_hash="scope-x",
            result_text="keep me",
            is_cacheable=True,
        )

        deleted = persistence.expire_tool_cache_entries(tool_name="weather_tool")
        assert deleted == 3

        kept = persistence.get_tool_cache_entry(
            tool_name="other_tool",
            normalized_params_hash="hash-x",
            scope_hash="scope-x",
        )
        assert kept is not None

    def test_expire_by_older_than(self, persistence):
        """TC-TCACHE-08: expire_tool_cache_entries by older_than deletes only old entries."""
        persistence.record_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-old",
            scope_hash="scope1",
            result_text="old",
            is_cacheable=True,
            created_at=_past(seconds=7200),
        )
        persistence.record_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-new",
            scope_hash="scope1",
            result_text="new",
            is_cacheable=True,
        )

        deleted = persistence.expire_tool_cache_entries(
            older_than=_now() - timedelta(hours=1)
        )
        assert deleted == 1

        row = persistence.get_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-new",
            scope_hash="scope1",
        )
        assert row is not None

    def test_expire_requires_at_least_one_filter(self, persistence):
        """TC-TCACHE-09: expire_tool_cache_entries raises ValueError with no filters."""
        with pytest.raises(ValueError, match="At least one of"):
            persistence.expire_tool_cache_entries()

    def test_record_unknown_field_raises(self, persistence):
        """TC-TCACHE-10: passing an unknown kwarg raises ValueError."""
        with pytest.raises(ValueError, match="Unknown tool cache field"):
            persistence.record_tool_cache_entry(
                tool_name="get_weather",
                normalized_params_hash="h",
                scope_hash="s",
                result_text="r",
                unknown_field="bad",
            )

    def test_record_missing_tool_name_raises(self, persistence):
        """TC-TCACHE-11: empty tool_name raises ValueError."""
        with pytest.raises(ValueError, match="tool_name is required"):
            persistence.record_tool_cache_entry(
                tool_name="",
                normalized_params_hash="h",
                scope_hash="s",
                result_text="r",
            )

    def test_expire_by_scope_hash(self, persistence):
        """TC-TCACHE-12: expire_tool_cache_entries by scope_hash clears that scope only."""
        persistence.record_tool_cache_entry(
            tool_name="t",
            normalized_params_hash="h1",
            scope_hash="scope-a",
            result_text="a",
            is_cacheable=True,
        )
        persistence.record_tool_cache_entry(
            tool_name="t",
            normalized_params_hash="h2",
            scope_hash="scope-b",
            result_text="b",
            is_cacheable=True,
        )
        deleted = persistence.expire_tool_cache_entries(scope_hash="scope-a")
        assert deleted == 1

        row_b = persistence.get_tool_cache_entry(
            tool_name="t", normalized_params_hash="h2", scope_hash="scope-b"
        )
        assert row_b is not None

    def test_expire_by_expired_as_of(self, persistence):
        """TC-TCACHE-13: expire_tool_cache_entries(expired_as_of=...) deletes only expired rows."""
        persistence.record_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-old",
            scope_hash="scope1",
            result_text="stale result",
            is_cacheable=True,
            expires_at=_past(seconds=1),
        )
        persistence.record_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-new",
            scope_hash="scope1",
            result_text="fresh result",
            is_cacheable=True,
            expires_at=_future(seconds=3600),
        )

        deleted = persistence.expire_tool_cache_entries(expired_as_of=_now())

        assert deleted == 1
        row = persistence.get_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-new",
            scope_hash="scope1",
        )
        assert row is not None
        assert row.result_text == "fresh result"

    def test_expire_requires_filter_but_expired_as_of_counts(self, persistence):
        """TC-TCACHE-14: expired_as_of alone is a valid cleanup filter."""
        persistence.record_tool_cache_entry(
            tool_name="get_weather",
            normalized_params_hash="hash-old",
            scope_hash="scope1",
            result_text="stale result",
            is_cacheable=True,
            expires_at=_past(seconds=1),
        )

        deleted = persistence.expire_tool_cache_entries(expired_as_of=_now())

        assert deleted == 1
