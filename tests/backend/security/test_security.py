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
