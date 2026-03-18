"""Per-user store layer — DB-backed replacements for the shared in-memory dicts.

UserScopedLLMConfigStore  — replaces global llm_config_storage
UserScopedServerStore     — replaces global servers_storage
UserSettingsStore         — new; persists UI preferences per user

Credentials stored in user_llm_configs.config_json are AES-256-GCM encrypted
at rest. The encryption key is derived from the SECRET_KEY env var.
"""
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Any, Dict

from sqlalchemy import select

from backend.database import (
    SessionLocal,
    UserLLMConfigRow,
    UserServerRow,
    UserSettingsRow,
)
from backend.models import LLMConfig, ServerConfig, UserSettings, UserSettingsPatch

logger = logging.getLogger("mcp_client.internal")

# ---------------------------------------------------------------------------
# Credential encryption helpers (AES-256-GCM)
# ---------------------------------------------------------------------------

_CREDENTIAL_FIELDS = ("api_key", "client_secret")


def _derive_key() -> bytes:
    """Derive a 32-byte key from SECRET_KEY env var."""
    raw = os.getenv("SECRET_KEY", "")
    if not raw:
        raise RuntimeError("SECRET_KEY is not set — cannot encrypt credentials.")
    # Pad/trim to 32 bytes
    key_bytes = raw.encode()[:32].ljust(32, b"\x00")
    return key_bytes


def _encrypt_field(plaintext: str) -> str:
    """Encrypt a credential field with AES-256-GCM. Returns 'enc:<b64iv>:<b64tag>:<b64ct>'."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import os as _os
    key = _derive_key()
    iv = _os.urandom(12)
    aesgcm = AESGCM(key)
    ct_with_tag = aesgcm.encrypt(iv, plaintext.encode(), None)
    # cryptography appends the 16-byte tag at the end of ciphertext
    ct = ct_with_tag[:-16]
    tag = ct_with_tag[-16:]
    return (
        "enc:"
        + base64.b64encode(iv).decode()
        + ":"
        + base64.b64encode(tag).decode()
        + ":"
        + base64.b64encode(ct).decode()
    )


def _decrypt_field(encoded: str) -> str:
    """Decrypt a credential field produced by _encrypt_field."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    parts = encoded.split(":", 3)
    if len(parts) != 4 or parts[0] != "enc":
        return encoded  # Not encrypted — return as-is (migration path)
    _, iv_b64, tag_b64, ct_b64 = parts
    iv = base64.b64decode(iv_b64)
    tag = base64.b64decode(tag_b64)
    ct = base64.b64decode(ct_b64)
    key = _derive_key()
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ct + tag, None)
    return plaintext.decode()


def _mask_credential(value: str) -> str:
    """Return 'sk-...****' style masked version of a credential."""
    if not value or value.startswith("enc:"):
        return "****"
    prefix = value[:3] if len(value) > 7 else ""
    return f"{prefix}...{value[-4:]}" if len(value) > 7 else "****"


def _encrypt_config_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of the config dict with credential fields encrypted."""
    result = dict(data)
    for field in _CREDENTIAL_FIELDS:
        if result.get(field):
            result[field] = _encrypt_field(result[field])
    return result


def _decrypt_and_mask_config_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy with credentials decrypted-then-masked (safe for API responses)."""
    result = dict(data)
    for field in _CREDENTIAL_FIELDS:
        raw = result.get(field)
        if raw and isinstance(raw, str) and raw.startswith("enc:"):
            try:
                plaintext = _decrypt_field(raw)
                result[field] = _mask_credential(plaintext)
            except Exception:
                result[field] = "****"
    return result


def _decrypt_config_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy with credentials fully decrypted (for LLM client use only)."""
    result = dict(data)
    for field in _CREDENTIAL_FIELDS:
        raw = result.get(field)
        if raw and isinstance(raw, str) and raw.startswith("enc:"):
            try:
                result[field] = _decrypt_field(raw)
            except Exception:
                logger.warning(f"Failed to decrypt credential field '{field}'")
                result[field] = None
    return result


# ---------------------------------------------------------------------------
# UserScopedLLMConfigStore
# ---------------------------------------------------------------------------

class UserScopedLLMConfigStore:
    """Replaces the global llm_config_storage dict."""

    def get_masked(self, user_id: str) -> Optional[LLMConfig]:
        """Return user's LLM config with credentials masked (for API responses)."""
        with SessionLocal() as db:
            row = db.get(UserLLMConfigRow, user_id)
            if row is None:
                return None
            data = _decrypt_and_mask_config_dict(json.loads(row.config_json))
            return LLMConfig.model_validate(data)

    def get_full(self, user_id: str) -> Optional[LLMConfig]:
        """Return user's LLM config with credentials fully decrypted (for LLM client)."""
        with SessionLocal() as db:
            row = db.get(UserLLMConfigRow, user_id)
            if row is None:
                return None
            data = _decrypt_config_dict(json.loads(row.config_json))
            return LLMConfig.model_validate(data)

    def set(self, user_id: str, config: LLMConfig) -> None:
        """Save (upsert) user's LLM config, encrypting credentials."""
        now = datetime.now(timezone.utc)
        raw_dict = json.loads(config.model_dump_json())

        # If the incoming value is masked (sk-...****), preserve existing encrypted value
        with SessionLocal() as db:
            existing = db.get(UserLLMConfigRow, user_id)
            if existing:
                existing_data = _decrypt_config_dict(json.loads(existing.config_json))
                for field in _CREDENTIAL_FIELDS:
                    new_val = raw_dict.get(field, "")
                    if not new_val or (isinstance(new_val, str) and "****" in new_val):
                        raw_dict[field] = existing_data.get(field)

        encrypted = _encrypt_config_dict(raw_dict)
        with SessionLocal() as db:
            row = db.get(UserLLMConfigRow, user_id)
            if row:
                row.config_json = json.dumps(encrypted)
                row.updated_at = now
            else:
                row = UserLLMConfigRow(
                    user_id=user_id,
                    config_json=json.dumps(encrypted),
                    updated_at=now,
                )
                db.add(row)
            db.commit()

    def delete(self, user_id: str) -> None:
        with SessionLocal() as db:
            row = db.get(UserLLMConfigRow, user_id)
            if row:
                db.delete(row)
                db.commit()


# ---------------------------------------------------------------------------
# UserScopedServerStore
# ---------------------------------------------------------------------------

class UserScopedServerStore:
    """Replaces the global servers_storage dict."""

    def list(self, user_id: str) -> List[ServerConfig]:
        with SessionLocal() as db:
            rows = db.execute(
                select(UserServerRow).where(UserServerRow.user_id == user_id)
            ).scalars().all()
            return [ServerConfig.model_validate(json.loads(r.config_json)) for r in rows]

    def get(self, user_id: str, server_id: str) -> Optional[ServerConfig]:
        with SessionLocal() as db:
            row = db.execute(
                select(UserServerRow).where(
                    UserServerRow.user_id == user_id,
                    UserServerRow.server_id == server_id,
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return ServerConfig.model_validate(json.loads(row.config_json))

    def owns(self, user_id: str, server_id: str) -> bool:
        with SessionLocal() as db:
            row = db.execute(
                select(UserServerRow).where(
                    UserServerRow.user_id == user_id,
                    UserServerRow.server_id == server_id,
                )
            ).scalar_one_or_none()
            return row is not None

    def create(self, user_id: str, config: ServerConfig) -> ServerConfig:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            row = UserServerRow(
                server_id=config.server_id,
                user_id=user_id,
                config_json=config.model_dump_json(),
                created_at=now,
            )
            db.add(row)
            db.commit()
        return config

    def update(self, user_id: str, server_id: str, config: ServerConfig) -> ServerConfig:
        with SessionLocal() as db:
            row = db.execute(
                select(UserServerRow).where(
                    UserServerRow.user_id == user_id,
                    UserServerRow.server_id == server_id,
                )
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"Server {server_id} not found for user {user_id}")
            row.config_json = config.model_dump_json()
            db.commit()
        return config

    def delete(self, user_id: str, server_id: str) -> bool:
        with SessionLocal() as db:
            row = db.execute(
                select(UserServerRow).where(
                    UserServerRow.user_id == user_id,
                    UserServerRow.server_id == server_id,
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            db.delete(row)
            db.commit()
        return True

    def delete_all_for_user(self, user_id: str) -> None:
        with SessionLocal() as db:
            rows = db.execute(
                select(UserServerRow).where(UserServerRow.user_id == user_id)
            ).scalars().all()
            for r in rows:
                db.delete(r)
            db.commit()


# ---------------------------------------------------------------------------
# UserSettingsStore
# ---------------------------------------------------------------------------

class UserSettingsStore:
    """Persists per-user UI preferences."""

    def get(self, user_id: str) -> UserSettings:
        with SessionLocal() as db:
            row = db.get(UserSettingsRow, user_id)
            if row is None:
                return UserSettings()
            return UserSettings(
                theme=row.theme,
                message_density=row.message_density,
                tool_panel_visible=row.tool_panel_visible,
                sidebar_collapsed=row.sidebar_collapsed,
                default_llm_model=row.default_llm_model,
            )

    def patch(self, user_id: str, updates: UserSettingsPatch) -> UserSettings:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            row = db.get(UserSettingsRow, user_id)
            if row is None:
                row = UserSettingsRow(user_id=user_id, updated_at=now)
                db.add(row)
            if updates.theme is not None:
                row.theme = updates.theme
            if updates.message_density is not None:
                row.message_density = updates.message_density
            if updates.tool_panel_visible is not None:
                row.tool_panel_visible = updates.tool_panel_visible
            if updates.sidebar_collapsed is not None:
                row.sidebar_collapsed = updates.sidebar_collapsed
            if updates.default_llm_model is not None:
                row.default_llm_model = updates.default_llm_model
            row.updated_at = now
            db.commit()
            db.refresh(row)
            return UserSettings(
                theme=row.theme,
                message_density=row.message_density,
                tool_panel_visible=row.tool_panel_visible,
                sidebar_collapsed=row.sidebar_collapsed,
                default_llm_model=row.default_llm_model,
            )

    def reset(self, user_id: str) -> None:
        with SessionLocal() as db:
            row = db.get(UserSettingsRow, user_id)
            if row:
                db.delete(row)
                db.commit()
