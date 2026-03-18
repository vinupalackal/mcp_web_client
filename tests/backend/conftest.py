"""
Root conftest.py — shared fixtures for all backend tests.
Resets module-level in-memory state between every test so tests are isolated.
"""

import uuid as _uuid
import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import app
from backend.session_manager import SessionManager
from backend.mcp_manager import MCPManager


# ---------------------------------------------------------------------------
# State reset
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_backend_state(tmp_path, monkeypatch):
    """Clear all module-level in-memory storage before each test."""
    data_dir = tmp_path / "mcp-test-data"
    monkeypatch.setattr(main_module, "MCP_DATA_DIR", data_dir)
    main_module.servers_storage.clear()
    main_module.llm_config_storage = None
    main_module.enterprise_token_cache.clear()
    main_module.session_manager = SessionManager()
    main_module.mcp_manager = MCPManager()
    yield
    main_module.servers_storage.clear()
    main_module.llm_config_storage = None
    main_module.enterprise_token_cache.clear()


# ---------------------------------------------------------------------------
# HTTP test client
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------

@pytest.fixture
def server_payload():
    return {
        "alias": "test_server",
        "base_url": "https://mcp.example.com",
        "auth_type": "none",
    }


@pytest.fixture
def server_payload_http():
    return {
        "alias": "http_server",
        "base_url": "http://mcp.example.com",
        "auth_type": "none",
    }


@pytest.fixture
def server_payload_bearer():
    return {
        "alias": "bearer_server",
        "base_url": "https://mcp.example.com",
        "auth_type": "bearer",
        "bearer_token": "my-secret-token",
    }


@pytest.fixture
def llm_openai():
    return {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com",
        "api_key": "sk-test-key",
        "temperature": 0.7,
    }


@pytest.fixture
def llm_ollama():
    return {
        "provider": "ollama",
        "model": "llama3.2",
        "base_url": "http://127.0.0.1:11434",
        "temperature": 0.5,
    }


@pytest.fixture
def llm_mock():
    return {
        "provider": "mock",
        "model": "mock-model",
        "base_url": "http://localhost",
        "temperature": 0.7,
    }


@pytest.fixture
def llm_enterprise():
    return {
        "gateway_mode": "enterprise",
        "provider": "enterprise",
        "model": "gpt-4o",
        "base_url": "https://llm-gateway.internal/modelgw/models/openai/v1",
        "auth_method": "bearer",
        "client_id": "enterprise-client",
        "client_secret": "enterprise-secret",
        "token_endpoint_url": "https://auth.internal/v2/oauth/token",
        "temperature": 0.3,
    }


# ---------------------------------------------------------------------------
# Mock JSON-RPC helpers
# ---------------------------------------------------------------------------

def make_jsonrpc_tool(name: str, description: str = "", params: dict = None):
    """Return a JSON-RPC tool entry as an MCP server would."""
    return {
        "name": name,
        "description": description,
        "inputSchema": params or {"type": "object", "properties": {}},
    }


def make_jsonrpc_success(result: dict, rpc_id: int = 1):
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def make_jsonrpc_error(code: int, message: str, rpc_id: int = 1):
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


# ===========================================================================
# SSO / Auth fixtures  (v0.4.0-sso-user-settings)
# ===========================================================================

_TEST_SECRET_KEY = "testkeytestkeytestkeytestkeytestkeytestkeytestkeytestkeytestk"  # 64 chars


@pytest.fixture
def secret_key(monkeypatch):
    """Set SECRET_KEY env var and patch jwt_utils module cache for SSO tests."""
    monkeypatch.setenv("SECRET_KEY", _TEST_SECRET_KEY)
    import backend.auth.jwt_utils as jwt_mod
    monkeypatch.setattr(jwt_mod, "_SECRET_KEY", _TEST_SECRET_KEY)
    yield _TEST_SECRET_KEY


@pytest.fixture
def sso_db(monkeypatch):
    """Isolated in-memory SQLite database for SSO tests.

    Patches SessionLocal in backend.database, backend.user_store, and backend.main
    so all DB operations use the in-memory store.  Also patches _engine so that
    init_db() called from the lifespan creates tables in the same in-memory DB.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import backend.database as db_mod
    import backend.user_store as us_mod

    # StaticPool ensures every session shares the same in-memory connection so
    # data written in make_db_user is visible to the middleware's get_user_by_id.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db_mod.Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_mod, "_engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", factory)
    monkeypatch.setattr(us_mod, "SessionLocal", factory)
    monkeypatch.setattr(main_module, "SessionLocal", factory)

    yield factory


@pytest.fixture
def make_db_user(sso_db):
    """Factory: insert a UserRow + default UserSettingsRow into the test DB.

    Usage::

        user = make_db_user(email="alice@example.com", roles=["user", "admin"])
    """
    import json
    from datetime import datetime, timezone
    from backend.database import UserRow, UserSettingsRow

    def _create(
        email="alice@example.com",
        provider="google",
        sub=None,
        display_name="Alice Smith",
        roles=None,
        is_active=True,
        avatar_url=None,
    ):
        uid = str(_uuid.uuid4())
        sub_val = sub or f"{provider}-sub-{uid[:8]}"
        now = datetime.now(timezone.utc)
        user = UserRow(
            user_id=uid,
            provider=provider,
            provider_sub=sub_val,
            email=email,
            display_name=display_name,
            avatar_url=avatar_url,
            roles=json.dumps(roles or ["user"]),
            is_active=is_active,
            created_at=now,
            last_login_at=now,
        )
        with sso_db() as db:
            db.add(user)
            db.add(UserSettingsRow(user_id=uid, updated_at=now))
            db.commit()
            # Eagerly load all column attributes before detaching
            _ = (
                user.user_id, user.email, user.roles, user.is_active,
                user.display_name, user.avatar_url, user.provider,
                user.provider_sub,
            )
            db.expunge(user)
        return user

    return _create


class _MockOIDCProvider:
    """Minimal OIDC provider stub used for integration tests."""

    provider_key = "mock_idp"
    display_label = "Mock IdP"

    def build_authorisation_url(self, state, nonce, code_challenge):
        return (
            f"https://mock-idp.example.com/auth"
            f"?state={state}&nonce={nonce}&code_challenge={code_challenge}"
        )

    async def exchange_code(self, code, code_verifier):
        return {"id_token": "mock-id-token", "access_token": "mock-access-token"}

    async def validate_id_token(self, id_token, nonce):
        from backend.auth.provider import OIDCUserInfo
        return OIDCUserInfo(
            sub="mock-sub-001",
            email="mockuser@example.com",
            display_name="Mock SSO User",
            avatar_url=None,
        )


@pytest.fixture
def sso_client(secret_key, sso_db, monkeypatch):
    """TestClient with SSO fully enabled via a mock IdP provider."""
    monkeypatch.setattr(main_module, "_sso_providers", {"mock_idp": _MockOIDCProvider()})
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth_cookie(secret_key):
    """Factory: return a signed app_token JWT for the given user."""
    from backend.auth.jwt_utils import issue_app_token

    def _make(user_id, email="test@example.com", roles=None, ttl_hours=8):
        return issue_app_token(user_id, email, roles or ["user"], ttl_hours=ttl_hours)

    return _make
