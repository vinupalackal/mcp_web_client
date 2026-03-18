"""
Unit tests for database helper functions (backend.database)
Test IDs: TC-DB-*

All tests require the `sso_db` fixture which patches the module-level engine and
SessionLocal with an isolated in-memory SQLite database.
"""

import json
import time

import pytest
from sqlalchemy import select

from backend.database import (
    UserRow,
    UserSettingsRow,
    get_user_by_email,
    get_user_by_id,
    get_user_by_provider,
    init_db,
    upsert_user,
)


# ============================================================================
# init_db
# ============================================================================

class TestInitDb:

    def test_no_exception_on_existing_schema(self, sso_db):
        """TC-DB-01: Calling init_db() when tables already exist raises no error."""
        # Tables were created by the sso_db fixture; calling again must be a no-op
        init_db()

    def test_tables_are_queryable(self, sso_db):
        """TC-DB-02: All ORM tables are present and queryable after init_db()."""
        with sso_db() as db:
            db.execute(select(UserRow))
            db.execute(select(UserSettingsRow))


# ============================================================================
# upsert_user — first login (insert)
# ============================================================================

class TestUpsertUserInsert:
    # NOTE: upsert_user's returned UserRow may have expired attrs after the second
    # commit() in the first-login path.  Re-query via get_user_by_* for safety.

    def test_creates_user_on_first_login(self, sso_db):
        """TC-DB-03: upsert_user creates a new UserRow when (provider, sub) is new."""
        upsert_user("google", "sub-001", "alice@example.com", "Alice", None, [])
        user = get_user_by_email("alice@example.com")
        assert user is not None
        assert user.email == "alice@example.com"
        assert user.provider == "google"
        assert user.provider_sub == "sub-001"
        assert user.user_id

    def test_new_user_is_active(self, sso_db):
        """TC-DB-04: New user is created with is_active=True."""
        upsert_user("google", "sub-002", "bob@example.com", "Bob", None, [])
        user = get_user_by_email("bob@example.com")
        assert user is not None and user.is_active is True

    def test_new_user_default_role_is_user(self, sso_db):
        """TC-DB-05: New user gets ['user'] role when email not in admin list."""
        upsert_user("google", "sub-003", "carol@example.com", "Carol", None, [])
        user = get_user_by_email("carol@example.com")
        assert json.loads(user.roles) == ["user"]

    def test_admin_email_grants_admin_role(self, sso_db):
        """TC-DB-06: Email present in admin_emails list gets ['user', 'admin'] roles."""
        upsert_user("google", "sub-004", "admin@corp.com", "Admin", None, ["admin@corp.com"])
        user = get_user_by_email("admin@corp.com")
        roles = json.loads(user.roles)
        assert "admin" in roles
        assert "user" in roles

    def test_admin_match_is_case_insensitive(self, sso_db):
        """TC-DB-07: Admin email comparison is case-insensitive."""
        upsert_user("google", "sub-005", "ADMIN@CORP.COM", "Admin", None, ["admin@corp.com"])
        user = get_user_by_email("ADMIN@CORP.COM")
        assert user is not None and "admin" in json.loads(user.roles)

    def test_creates_default_settings_row(self, sso_db):
        """TC-DB-08: First login also creates a UserSettingsRow with default values."""
        upsert_user("google", "sub-006", "settings@example.com", "S", None, [])
        user = get_user_by_email("settings@example.com")
        with sso_db() as db:
            row = db.get(UserSettingsRow, user.user_id)
        assert row is not None
        assert row.theme == "system"
        assert row.message_density == "comfortable"
        assert row.tool_panel_visible is True
        assert row.sidebar_collapsed is False

    def test_avatar_url_stored(self, sso_db):
        """TC-DB-09: avatar_url is saved when provided on first login."""
        upsert_user(
            "google", "sub-007", "avatar@example.com", "Av",
            "https://example.com/pic.jpg", []
        )
        user = get_user_by_email("avatar@example.com")
        assert user is not None and user.avatar_url == "https://example.com/pic.jpg"


# ============================================================================
# upsert_user — repeat login (update)
# ============================================================================

class TestUpsertUserUpdate:

    def test_second_login_updates_last_login_at(self, sso_db):
        """TC-DB-10: Second upsert updates last_login_at."""
        upsert_user("google", "sub-010", "u10@example.com", "U10", None, [])
        before_second = get_user_by_email("u10@example.com").last_login_at
        time.sleep(0.05)
        upsert_user("google", "sub-010", "u10@example.com", "U10", None, [])
        after_second = get_user_by_email("u10@example.com").last_login_at
        assert after_second >= before_second

    def test_second_login_preserves_user_id(self, sso_db):
        """TC-DB-11: user_id is immutable across logins."""
        upsert_user("google", "sub-011", "u11@example.com", "U11", None, [])
        uid_first = get_user_by_email("u11@example.com").user_id
        upsert_user("google", "sub-011", "u11@example.com", "U11", None, [])
        uid_second = get_user_by_email("u11@example.com").user_id
        assert uid_first == uid_second

    def test_second_login_updates_display_name(self, sso_db):
        """TC-DB-12: display_name is refreshed on subsequent logins."""
        upsert_user("google", "sub-012", "u12@example.com", "Old Name", None, [])
        upsert_user("google", "sub-012", "u12@example.com", "New Name", None, [])
        user = get_user_by_email("u12@example.com")
        assert user.display_name == "New Name"

    def test_second_login_updates_avatar_url(self, sso_db):
        """TC-DB-13: avatar_url is updated when provided on repeat login."""
        upsert_user("google", "sub-013", "u13@example.com", "U13", None, [])
        upsert_user("google", "sub-013", "u13@example.com", "U13",
                    "https://cdn.example.com/new.jpg", [])
        user = get_user_by_email("u13@example.com")
        assert user.avatar_url == "https://cdn.example.com/new.jpg"

    def test_admin_promotion_on_repeat_login(self, sso_db):
        """TC-DB-14: User gains admin role when email added to admin list at next login."""
        upsert_user("google", "sub-014", "promote@corp.com", "P", None, [])
        upsert_user("google", "sub-014", "promote@corp.com", "P", None, ["promote@corp.com"])
        user = get_user_by_email("promote@corp.com")
        assert "admin" in json.loads(user.roles)


# ============================================================================
# get_user_by_id
# ============================================================================

class TestGetUserById:

    def test_returns_user_for_known_id(self, sso_db, make_db_user):
        """TC-DB-15: Returns UserRow for a known user_id."""
        user = make_db_user(email="findbyid@example.com")
        found = get_user_by_id(user.user_id)
        assert found is not None
        assert found.user_id == user.user_id

    def test_returns_none_for_unknown_id(self, sso_db):
        """TC-DB-16: Returns None for an unknown UUID."""
        assert get_user_by_id("00000000-0000-0000-0000-000000000099") is None


# ============================================================================
# get_user_by_email
# ============================================================================

class TestGetUserByEmail:

    def test_returns_user_for_known_email(self, sso_db, make_db_user):
        """TC-DB-17: Returns UserRow for a known email address."""
        make_db_user(email="findbyemail@example.com")
        found = get_user_by_email("findbyemail@example.com")
        assert found is not None
        assert found.email == "findbyemail@example.com"

    def test_returns_none_for_unknown_email(self, sso_db):
        """TC-DB-18: Returns None for an email that is not in the DB."""
        assert get_user_by_email("ghost@example.com") is None


# ============================================================================
# get_user_by_provider
# ============================================================================

class TestGetUserByProvider:

    def test_returns_user_for_known_provider_sub(self, sso_db, make_db_user):
        """TC-DB-19: Returns UserRow for known (provider, provider_sub) pair."""
        make_db_user(provider="azure_ad", sub="azure-sub-xyz", email="azure@example.com")
        found = get_user_by_provider("azure_ad", "azure-sub-xyz")
        assert found is not None
        assert found.provider_sub == "azure-sub-xyz"

    def test_returns_none_for_wrong_provider(self, sso_db, make_db_user):
        """TC-DB-20: Returns None when provider key doesn't match stored value."""
        make_db_user(provider="google", sub="sub-google-001", email="guser@example.com")
        assert get_user_by_provider("azure_ad", "sub-google-001") is None

    def test_returns_none_for_unknown_sub(self, sso_db):
        """TC-DB-21: Returns None for a sub not present in the DB."""
        assert get_user_by_provider("google", "nonexistent-sub-xyz") is None
