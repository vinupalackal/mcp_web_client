"""
Unit tests for per-user store classes (backend.user_store)
Test IDs: TC-CRED-*  TC-LLM-STORE-*  TC-SRV-STORE-*  TC-SETTINGS-STORE-*

All tests require the `sso_db` fixture (in-memory SQLite) and, where credential
encryption is exercised, the `secret_key` fixture.
"""

import json

import pytest

from backend.models import LLMConfig, ServerConfig, UserSettings, UserSettingsPatch
from backend.user_store import (
    UserScopedLLMConfigStore,
    UserScopedServerStore,
    UserSettingsStore,
    _decrypt_field,
    _encrypt_field,
    _mask_credential,
)


# ============================================================================
# Credential helpers
# ============================================================================

class TestCredentialHelpers:

    def test_mask_long_credential_hides_middle(self, secret_key):
        """TC-CRED-01: _mask_credential returns prefix...last4 — full value never exposed."""
        result = _mask_credential("sk-abcdefghij1234")
        assert "1234" in result                      # last-4 chars visible
        assert "sk-abcdefghij1234" not in result     # full plaintext never returned
        assert "..." in result                       # ellipsis separates prefix and suffix

    def test_mask_short_credential_returns_stars(self, secret_key):
        """TC-CRED-02: _mask_credential returns '****' for values <= 7 chars."""
        assert _mask_credential("abc") == "****"

    def test_mask_empty_string(self, secret_key):
        """TC-CRED-03: _mask_credential returns '****' for an empty string."""
        assert _mask_credential("") == "****"

    def test_encrypt_decrypt_roundtrip(self, secret_key):
        """TC-CRED-04: _decrypt_field(_encrypt_field(value)) == original value."""
        original = "sk-test-secret-api-key-abcde12345"
        encrypted = _encrypt_field(original)
        assert encrypted != original
        decrypted = _decrypt_field(encrypted)
        assert decrypted == original

    def test_encrypted_value_starts_with_enc_prefix(self, secret_key):
        """TC-CRED-05: Encrypted values always start with 'enc:'."""
        result = _encrypt_field("my-api-key-value")
        assert result.startswith("enc:")

    def test_encrypted_values_differ_each_call(self, secret_key):
        """TC-CRED-06: Same plaintext produces different ciphertext each call (random IV)."""
        a = _encrypt_field("same-key")
        b = _encrypt_field("same-key")
        assert a != b, "Encrypted values should differ due to random IV"

    def test_decrypt_plain_value_passthrough(self, secret_key):
        """TC-CRED-07: _decrypt_field returns non-encrypted strings unchanged."""
        plain = "plaintext-not-encrypted"
        assert _decrypt_field(plain) == plain


# ============================================================================
# UserScopedLLMConfigStore
# ============================================================================

class TestUserScopedLLMConfigStore:

    @pytest.fixture(autouse=True)
    def setup(self, sso_db, secret_key):
        self.store = UserScopedLLMConfigStore()
        self.uid = "llm-store-user-001"

    # --- get when empty ---

    def test_get_masked_returns_none_when_no_config(self):
        """TC-LLM-STORE-01: get_masked returns None for user with no saved config."""
        assert self.store.get_masked(self.uid) is None

    def test_get_full_returns_none_when_no_config(self):
        """TC-LLM-STORE-02: get_full returns None for user with no saved config."""
        assert self.store.get_full(self.uid) is None

    # --- set / get round-trip ---

    def test_set_then_get_masked_returns_llmconfig(self):
        """TC-LLM-STORE-03: set() then get_masked() returns an LLMConfig instance."""
        cfg = LLMConfig(provider="mock", model="mock-model", base_url="http://localhost")
        self.store.set(self.uid, cfg)
        result = self.store.get_masked(self.uid)
        assert result is not None
        assert result.model == "mock-model"

    def test_api_key_is_masked_in_get_masked(self):
        """TC-LLM-STORE-04: get_masked returns masked api_key — full value never exposed."""
        cfg = LLMConfig(
            provider="openai", model="gpt-4o",
            base_url="https://api.openai.com",
            api_key="sk-test-secret-key-1234"
        )
        self.store.set(self.uid, cfg)
        result = self.store.get_masked(self.uid)
        assert result.api_key is not None
        # Full plaintext must not be exposed
        assert result.api_key != "sk-test-secret-key-1234"
        assert "sk-test-secret-key-1234" not in (result.api_key or "")

    def test_api_key_is_fully_decrypted_in_get_full(self):
        """TC-LLM-STORE-05: get_full returns the original (decrypted) api_key."""
        cfg = LLMConfig(
            provider="openai", model="gpt-4o",
            base_url="https://api.openai.com",
            api_key="sk-test-secret-key-1234"
        )
        self.store.set(self.uid, cfg)
        result = self.store.get_full(self.uid)
        assert result.api_key == "sk-test-secret-key-1234"

    # --- masked value preservation ---

    def test_set_with_masked_value_preserves_existing_key(self):
        """TC-LLM-STORE-06: Saving with a masked api_key keeps the existing encrypted key."""
        original_cfg = LLMConfig(
            provider="openai", model="gpt-4o",
            base_url="https://api.openai.com",
            api_key="sk-original-secret-key-abc"
        )
        self.store.set(self.uid, original_cfg)

        # Simulate user re-saving without re-entering the key (masked placeholder)
        masked_cfg = LLMConfig(
            provider="openai", model="gpt-4o-mini",
            base_url="https://api.openai.com",
            api_key="sk-...****"
        )
        self.store.set(self.uid, masked_cfg)

        result = self.store.get_full(self.uid)
        assert result.api_key == "sk-original-secret-key-abc"
        assert result.model == "gpt-4o-mini"  # model updated

    # --- at-rest encryption ---

    def test_credential_encrypted_in_db(self, sso_db):
        """TC-LLM-STORE-07: Raw config_json in the DB does not contain the plaintext key."""
        from backend.database import UserLLMConfigRow

        cfg = LLMConfig(
            provider="openai", model="gpt-4o",
            base_url="https://api.openai.com",
            api_key="sk-super-secret-plain-text"
        )
        self.store.set(self.uid, cfg)

        with sso_db() as db:
            row = db.get(UserLLMConfigRow, self.uid)
            assert row is not None
            assert "sk-super-secret-plain-text" not in row.config_json
            stored = json.loads(row.config_json)
            assert stored.get("api_key", "").startswith("enc:")

    # --- delete ---

    def test_delete_removes_config(self):
        """TC-LLM-STORE-08: delete() removes the user's config; get_masked returns None."""
        cfg = LLMConfig(provider="mock", model="mock", base_url="http://localhost")
        self.store.set(self.uid, cfg)
        self.store.delete(self.uid)
        assert self.store.get_masked(self.uid) is None

    def test_delete_nonexistent_is_noop(self):
        """TC-LLM-STORE-09: delete() on a user with no config raises no error."""
        self.store.delete("user-no-config")  # Should not raise

    # --- isolation ---

    def test_different_users_have_isolated_configs(self):
        """TC-LLM-STORE-10: User A's LLM config is invisible to user B."""
        cfg_a = LLMConfig(provider="mock", model="model-a", base_url="http://localhost")
        cfg_b = LLMConfig(provider="mock", model="model-b", base_url="http://localhost")
        self.store.set("user-a", cfg_a)
        self.store.set("user-b", cfg_b)
        assert self.store.get_masked("user-a").model == "model-a"
        assert self.store.get_masked("user-b").model == "model-b"


# ============================================================================
# UserScopedServerStore
# ============================================================================

class TestUserScopedServerStore:

    @pytest.fixture(autouse=True)
    def setup(self, sso_db):
        self.store = UserScopedServerStore()
        self.uid = "srv-store-user-001"

    def _server(self, alias="test_server", url="https://mcp.example.com"):
        return ServerConfig(alias=alias, base_url=url)

    def test_list_empty_for_new_user(self):
        """TC-SRV-STORE-01: list() returns [] for a user with no registered servers."""
        assert self.store.list(self.uid) == []

    def test_create_then_list_returns_server(self):
        """TC-SRV-STORE-02: create() then list() returns the created server."""
        srv = self._server()
        self.store.create(self.uid, srv)
        servers = self.store.list(self.uid)
        assert len(servers) == 1
        assert servers[0].alias == "test_server"

    def test_get_returns_server_by_id(self):
        """TC-SRV-STORE-03: get() returns the server matching server_id."""
        srv = self._server()
        self.store.create(self.uid, srv)
        found = self.store.get(self.uid, srv.server_id)
        assert found is not None
        assert found.server_id == srv.server_id

    def test_get_returns_none_for_unknown_server_id(self):
        """TC-SRV-STORE-04: get() returns None for an unrecognised server_id."""
        assert self.store.get(self.uid, "00000000-0000-0000-0000-000000000000") is None

    def test_get_returns_none_for_wrong_user(self):
        """TC-SRV-STORE-05: get() returns None when queried by a different user_id."""
        srv = self._server()
        self.store.create(self.uid, srv)
        assert self.store.get("other-user", srv.server_id) is None

    def test_owns_true_for_owner(self):
        """TC-SRV-STORE-06: owns() returns True for the creating user."""
        srv = self._server()
        self.store.create(self.uid, srv)
        assert self.store.owns(self.uid, srv.server_id) is True

    def test_owns_false_for_non_owner(self):
        """TC-SRV-STORE-07: owns() returns False for a user who did not create the server."""
        srv = self._server()
        self.store.create(self.uid, srv)
        assert self.store.owns("another-user", srv.server_id) is False

    def test_update_replaces_config(self):
        """TC-SRV-STORE-08: update() replaces the server's config."""
        srv = self._server(alias="original")
        self.store.create(self.uid, srv)
        updated = ServerConfig(
            server_id=srv.server_id, alias="updated", base_url="https://new.mcp.example.com"
        )
        self.store.update(self.uid, srv.server_id, updated)
        found = self.store.get(self.uid, srv.server_id)
        assert found.alias == "updated"

    def test_update_raises_key_error_for_missing_server(self):
        """TC-SRV-STORE-09: update() raises KeyError for an unknown server_id."""
        with pytest.raises(KeyError):
            self.store.update(self.uid, "ghost-id", self._server())

    def test_delete_removes_server_and_returns_true(self):
        """TC-SRV-STORE-10: delete() removes the server and returns True."""
        srv = self._server()
        self.store.create(self.uid, srv)
        result = self.store.delete(self.uid, srv.server_id)
        assert result is True
        assert self.store.get(self.uid, srv.server_id) is None

    def test_delete_returns_false_for_unknown_server(self):
        """TC-SRV-STORE-11: delete() returns False for a server_id not in the DB."""
        assert self.store.delete(self.uid, "ghost-server-id") is False

    def test_delete_all_for_user_removes_all_servers(self):
        """TC-SRV-STORE-12: delete_all_for_user() removes every server belonging to the user."""
        for i in range(3):
            self.store.create(self.uid, self._server(alias=f"srv_{i}", url=f"https://s{i}.com"))
        self.store.delete_all_for_user(self.uid)
        assert self.store.list(self.uid) == []

    def test_user_isolation(self):
        """TC-SRV-STORE-13: Servers created by user A are invisible to user B."""
        self.store.create("user-a", self._server(alias="a_server", url="https://a.example.com"))
        self.store.create("user-b", self._server(alias="b_server", url="https://b.example.com"))
        a_servers = self.store.list("user-a")
        b_servers = self.store.list("user-b")
        assert len(a_servers) == 1 and a_servers[0].alias == "a_server"
        assert len(b_servers) == 1 and b_servers[0].alias == "b_server"

    def test_multiple_servers_per_user(self):
        """TC-SRV-STORE-14: A single user can register multiple servers."""
        for i in range(5):
            self.store.create(self.uid, self._server(alias=f"srv_{i}", url=f"https://s{i}.com"))
        assert len(self.store.list(self.uid)) == 5


# ============================================================================
# UserSettingsStore
# ============================================================================

class TestUserSettingsStore:

    @pytest.fixture(autouse=True)
    def setup(self, sso_db, make_db_user):
        self.store = UserSettingsStore()
        self.user = make_db_user(email="settings-store@example.com")
        self.uid = self.user.user_id

    def test_get_returns_defaults_when_no_row(self):
        """TC-SETTINGS-STORE-01: get() returns default UserSettings for unknown user_id."""
        result = self.store.get("user-with-no-settings-row")
        assert result.theme == "system"
        assert result.message_density == "comfortable"
        assert result.tool_panel_visible is True
        assert result.sidebar_collapsed is False
        assert result.default_llm_model is None

    def test_get_returns_stored_settings(self):
        """TC-SETTINGS-STORE-02: get() returns a UserSettings instance for user with DB row."""
        result = self.store.get(self.uid)
        assert isinstance(result, UserSettings)

    def test_patch_updates_single_field(self):
        """TC-SETTINGS-STORE-03: patch() updates only the supplied field."""
        self.store.patch(self.uid, UserSettingsPatch(theme="dark"))
        result = self.store.get(self.uid)
        assert result.theme == "dark"
        # Other fields remain at defaults
        assert result.message_density == "comfortable"
        assert result.tool_panel_visible is True

    def test_patch_multiple_fields_at_once(self):
        """TC-SETTINGS-STORE-04: patch() with multiple fields updates all of them."""
        self.store.patch(self.uid, UserSettingsPatch(
            theme="light",
            message_density="compact",
            tool_panel_visible=False,
            sidebar_collapsed=True,
        ))
        result = self.store.get(self.uid)
        assert result.theme == "light"
        assert result.message_density == "compact"
        assert result.tool_panel_visible is False
        assert result.sidebar_collapsed is True

    def test_patch_all_none_is_noop(self):
        """TC-SETTINGS-STORE-05: patch() with all-None fields leaves existing settings intact."""
        self.store.patch(self.uid, UserSettingsPatch(theme="dark"))
        self.store.patch(self.uid, UserSettingsPatch())          # all None
        assert self.store.get(self.uid).theme == "dark"

    def test_patch_creates_row_if_absent(self):
        """TC-SETTINGS-STORE-06: patch() creates a settings row when none exists."""
        new_uid = "brand-new-user-no-row"
        result = self.store.patch(new_uid, UserSettingsPatch(theme="dark"))
        assert result.theme == "dark"
        assert self.store.get(new_uid).theme == "dark"

    def test_patch_returns_updated_settings_object(self):
        """TC-SETTINGS-STORE-07: patch() returns the updated UserSettings immediately."""
        result = self.store.patch(self.uid, UserSettingsPatch(sidebar_collapsed=True))
        assert isinstance(result, UserSettings)
        assert result.sidebar_collapsed is True

    def test_default_llm_model_can_be_patched(self):
        """TC-SETTINGS-STORE-08: default_llm_model can be set via patch()."""
        self.store.patch(self.uid, UserSettingsPatch(default_llm_model="gpt-4o"))
        assert self.store.get(self.uid).default_llm_model == "gpt-4o"

    def test_reset_restores_defaults(self):
        """TC-SETTINGS-STORE-09: reset() deletes the row; subsequent get() returns defaults."""
        self.store.patch(self.uid, UserSettingsPatch(theme="dark", sidebar_collapsed=True))
        self.store.reset(self.uid)
        result = self.store.get(self.uid)
        assert result.theme == "system"
        assert result.sidebar_collapsed is False

    def test_reset_nonexistent_user_is_noop(self):
        """TC-SETTINGS-STORE-10: reset() on a user with no settings row raises no error."""
        self.store.reset("no-settings-row-user")  # Should not raise
