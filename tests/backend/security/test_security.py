"""
Security tests — HTTPS enforcement + credential handling (TR-SEC-*)
"""

import pytest
import logging
import backend.main as main_module


class TestHTTPSEnforcement:

    def test_http_url_blocked_by_default(self, client, server_payload_http):
        """TC-SEC-01: HTTP URL rejected when MCP_ALLOW_HTTP_INSECURE is false."""
        import os
        os.environ.pop("MCP_ALLOW_HTTP_INSECURE", None)
        r = client.post("/api/servers", json=server_payload_http)
        assert r.status_code == 400
        assert "https" in r.json()["detail"].lower() or "http" in r.json()["detail"].lower()

    def test_http_url_allowed_with_insecure_flag(self, client, server_payload_http, monkeypatch):
        """TC-SEC-02: HTTP URL accepted when MCP_ALLOW_HTTP_INSECURE=true."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        r = client.post("/api/servers", json=server_payload_http)
        assert r.status_code == 201

    def test_https_always_allowed(self, client, server_payload, monkeypatch):
        """TC-SEC-03: HTTPS URL accepted regardless of env flag."""
        for flag in ("true", "false"):
            monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", flag)
            r = client.post("/api/servers", json={
                **server_payload, "alias": f"svc_{flag}"
            })
            assert r.status_code == 201

    def test_localhost_http_allowed_in_dev(self, client, monkeypatch):
        """TC-SEC-04: http://localhost allowed in dev mode."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        r = client.post("/api/servers", json={
            "alias": "local_dev",
            "base_url": "http://localhost:3000",
            "auth_type": "none",
        })
        assert r.status_code == 201


class TestCredentialHandling:

    def test_bearer_token_not_in_internal_logs(self, client, server_payload_bearer, caplog):
        """TC-SEC-05: Bearer token value never appears in internal log output."""
        with caplog.at_level(logging.INFO, logger="mcp_client.internal"):
            client.post("/api/servers", json=server_payload_bearer)
        for record in caplog.records:
            if record.name == "mcp_client.internal":
                assert "my-secret-token" not in record.message

    def test_api_key_not_in_internal_logs(self, client, llm_openai, caplog):
        """TC-SEC-06: LLM api_key value never appears in internal log output."""
        with caplog.at_level(logging.INFO, logger="mcp_client.internal"):
            client.post("/api/llm/config", json=llm_openai)
        for record in caplog.records:
            if record.name == "mcp_client.internal":
                assert "sk-test-key" not in record.message

    def test_mcp_bearer_sent_as_auth_header(self, client, server_payload_bearer, monkeypatch):
        """TC-SEC-07: Bearer token sent as Authorization header to MCP server."""
        import respx
        import httpx
        from backend.mcp_manager import MCPManager

        mgr = MCPManager()
        server = __import__("backend.models", fromlist=["ServerConfig"]).ServerConfig(
            alias="svc",
            base_url="https://mcp.example.com",
            auth_type="bearer",
            bearer_token="my-secret-token",
        )
        headers = mgr._build_headers(server)
        assert headers.get("Authorization") == "Bearer my-secret-token"

    def test_enterprise_client_secret_not_in_external_logs(self, client, caplog):
        """TC-SEC-08: Enterprise client_secret never appears in external log output."""
        import respx
        import httpx

        with respx.mock:
            respx.post("https://auth.internal/v2/oauth/token").mock(
                return_value=httpx.Response(200, json={"access_token": "tok-xyz", "expires_in": 3600})
            )
            with caplog.at_level(logging.DEBUG, logger="mcp_client.external"):
                client.post(
                    "/api/enterprise/token",
                    json={
                        "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                        "client_id": "enterprise-client",
                        "client_secret": "ultra-secret-value",
                    },
                )

        for record in caplog.records:
            if record.name == "mcp_client.external":
                assert "ultra-secret-value" not in record.message

    def test_enterprise_access_token_not_in_api_response(self, client):
        """TC-SEC-09: Token acquisition response body never contains the raw access_token."""
        import respx
        import httpx

        with respx.mock:
            respx.post("https://auth.internal/v2/oauth/token").mock(
                return_value=httpx.Response(200, json={"access_token": "raw-secret-token", "expires_in": 3600})
            )
            response = client.post(
                "/api/enterprise/token",
                json={
                    "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                    "client_id": "enterprise-client",
                    "client_secret": "enterprise-secret",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert "access_token" not in body
        assert "raw-secret-token" not in str(body)


class TestDualLoggerPattern:

    def test_external_logger_on_server_create(self, client, server_payload, caplog):
        """TC-LOG-01: external logger emits request and response arrows."""
        with caplog.at_level(logging.INFO, logger="mcp_client.external"):
            client.post("/api/servers", json=server_payload)
        messages = [r.message for r in caplog.records if r.name == "mcp_client.external"]
        assert any("→" in m for m in messages)
        assert any("←" in m for m in messages)

    def test_external_logger_on_server_list(self, client, caplog):
        """TC-LOG-02: GET /api/servers triggers external logger."""
        with caplog.at_level(logging.INFO, logger="mcp_client.external"):
            client.get("/api/servers")
        messages = [r.message for r in caplog.records if r.name == "mcp_client.external"]
        assert any("→" in m and "GET" in m for m in messages)

    def test_internal_logger_on_session_create(self, client, caplog):
        """TC-LOG-05: Creating a session logs via internal logger."""
        with caplog.at_level(logging.INFO, logger="mcp_client.internal"):
            client.post("/api/sessions")
        messages = [r.message for r in caplog.records if r.name == "mcp_client.internal"]
        assert any("session" in m.lower() for m in messages)


# ============================================================================
# SSO / Auth Security tests  (v0.4.0-sso-user-settings)
# TC-SSO-SEC-*
# ============================================================================

class TestSSOTokenSecurity:

    def test_missing_token_returns_json_401_not_redirect(self, sso_client):
        """TC-SSO-SEC-01: /api/* path with no cookie returns JSON 401, not HTML redirect."""
        r = sso_client.get("/api/users/me", follow_redirects=False)
        assert r.status_code == 401
        assert r.headers.get("content-type", "").startswith("application/json")

    def test_tampered_token_rejected(self, sso_client, secret_key):
        """TC-SSO-SEC-02: Token with modified payload is rejected with 401."""
        import base64
        import json as _json
        from backend.auth.jwt_utils import issue_app_token

        token = issue_app_token("uid-sec-001", "a@b.com", ["user"])
        header, payload_b64, sig = token.split(".")
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_data = _json.loads(base64.urlsafe_b64decode(padded))
        payload_data["roles"] = ["user", "admin"]
        new_payload = base64.urlsafe_b64encode(
            _json.dumps(payload_data).encode()
        ).rstrip(b"=").decode()
        tampered = f"{header}.{new_payload}.{sig}"
        r = sso_client.get("/api/users/me", cookies={"app_token": tampered})
        assert r.status_code == 401

    def test_expired_token_returns_session_expired_detail(
        self, sso_client, make_db_user, auth_cookie
    ):
        """TC-SSO-SEC-03: Expired token returns 401 with 'Session expired' in detail."""
        import time
        user = make_db_user(email="sec-expire@example.com")
        token = auth_cookie(user.user_id, user.email, ttl_hours=0)
        time.sleep(1)
        r = sso_client.get("/api/users/me", cookies={"app_token": token})
        assert r.status_code == 401
        assert "expired" in r.json().get("detail", "").lower()

    def test_logout_clears_cookie(self, sso_client):
        """TC-SSO-SEC-04: POST /auth/logout response header expires the session cookie."""
        r = sso_client.post("/auth/logout", follow_redirects=False)
        set_cookie = r.headers.get("set-cookie", "")
        assert "app_token" in set_cookie
        assert "max-age=0" in set_cookie.lower() or "expires=" in set_cookie.lower()

    def test_secret_key_value_not_in_log_output(self, sso_client, caplog):
        """TC-SSO-SEC-05: The SECRET_KEY value never appears in any log message."""
        import os
        secret = os.getenv("SECRET_KEY", "")
        with caplog.at_level(logging.DEBUG, logger="mcp_client.internal"):
            sso_client.get("/auth/providers")
        for record in caplog.records:
            assert secret not in record.message


class TestSSODataIsolation:

    def test_user_a_cannot_read_user_b_servers(
        self, sso_client, make_db_user, auth_cookie
    ):
        """TC-SSO-SEC-06: User A's GET /api/servers does not return User B's servers."""
        user_a = make_db_user(email="sec-isol-a@example.com", sub="sec-sub-a")
        user_b = make_db_user(email="sec-isol-b@example.com", sub="sec-sub-b")
        token_a = auth_cookie(user_a.user_id, user_a.email)
        token_b = auth_cookie(user_b.user_id, user_b.email)

        # User B registers a server
        sso_client.post(
            "/api/servers",
            json={"alias": "b_private_server", "base_url": "https://secret.b.example.com"},
            cookies={"app_token": token_b},
        )

        # User A's server list must not contain user B's server
        r = sso_client.get("/api/servers", cookies={"app_token": token_a})
        assert r.status_code == 200
        aliases = [s["alias"] for s in r.json()]
        assert "b_private_server" not in aliases

    def test_non_admin_cannot_access_admin_endpoints(
        self, sso_client, make_db_user, auth_cookie
    ):
        """TC-SSO-SEC-07: Non-admin gets 403 on all /api/admin/* endpoints."""
        user = make_db_user(email="sec-nonadmin@example.com", sub="sec-sub-nonadmin")
        token = auth_cookie(user.user_id, user.email, roles=["user"])
        for path in [
            "/api/admin/users",
            f"/api/admin/users/{user.user_id}",
        ]:
            r = sso_client.get(path, cookies={"app_token": token})
            assert r.status_code == 403, f"Expected 403 on {path}, got {r.status_code}"

    def test_user_profile_never_contains_credentials(
        self, sso_client, make_db_user, auth_cookie
    ):
        """TC-SSO-SEC-08: GET /api/users/me response body never includes sensitive fields."""
        user = make_db_user(email="sec-profile@example.com")
        token = auth_cookie(user.user_id, user.email)
        r = sso_client.get("/api/users/me", cookies={"app_token": token})
        body_text = r.text
        for sensitive_field in ("api_key", "client_secret", "bearer_token", "password"):
            assert sensitive_field not in body_text, (
                f"Sensitive field '{sensitive_field}' found in /api/users/me response"
            )
