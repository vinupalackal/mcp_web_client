"""
Integration tests — Enterprise Gateway endpoints and chat flow.
"""

import httpx
import pytest
import respx


_OPENAI_RESPONSE = {
    "choices": [
        {
            "message": {"role": "assistant", "content": "Enterprise hello!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9},
}


class TestEnterpriseTokenEndpoints:

    @respx.mock
    def test_acquire_token_success(self, client):
        respx.post("https://auth.internal/v2/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
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
        assert body["token_acquired"] is True
        assert body["expires_in"] == 3600
        assert "access_token" not in body

    def test_token_status_false_when_not_cached(self, client):
        response = client.get("/api/enterprise/token/status")
        assert response.status_code == 200
        assert response.json()["token_cached"] is False

    @respx.mock
    def test_delete_token_clears_cache(self, client):
        respx.post("https://auth.internal/v2/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        )
        client.post(
            "/api/enterprise/token",
            json={
                "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                "client_id": "enterprise-client",
                "client_secret": "enterprise-secret",
            },
        )

        delete_response = client.delete("/api/enterprise/token")
        status_response = client.get("/api/enterprise/token/status")

        assert delete_response.status_code == 200
        assert status_response.json()["token_cached"] is False

    @respx.mock
    def test_upstream_failure_returns_502(self, client):
        respx.post("https://auth.internal/v2/oauth/token").mock(
            return_value=httpx.Response(401, json={"detail": "unauthorized"})
        )

        response = client.post(
            "/api/enterprise/token",
            json={
                "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                "client_id": "enterprise-client",
                "client_secret": "enterprise-secret",
            },
        )

        assert response.status_code == 502

    @respx.mock
    def test_token_status_true_when_cached(self, client):
        """Token status returns token_cached=True with metadata after successful acquisition."""
        respx.post("https://auth.internal/v2/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        )
        client.post(
            "/api/enterprise/token",
            json={
                "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                "client_id": "enterprise-client",
                "client_secret": "enterprise-secret",
            },
        )

        response = client.get("/api/enterprise/token/status")
        assert response.status_code == 200
        body = response.json()
        assert body["token_cached"] is True
        assert body["cached_at"] is not None
        assert body["expires_in"] == 3600

    @respx.mock
    def test_token_endpoint_missing_access_token_returns_502(self, client):
        """Upstream returns 200 but omits access_token field → 502."""
        respx.post("https://auth.internal/v2/oauth/token").mock(
            return_value=httpx.Response(200, json={"token_type": "Bearer"})
        )

        response = client.post(
            "/api/enterprise/token",
            json={
                "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                "client_id": "enterprise-client",
                "client_secret": "enterprise-secret",
            },
        )

        assert response.status_code == 502
        assert "access_token" in response.json()["detail"].lower()

    @respx.mock
    def test_token_endpoint_timeout_returns_502(self, client):
        """Token endpoint request timeout returns 502 with appropriate detail."""
        respx.post("https://auth.internal/v2/oauth/token").mock(
            side_effect=httpx.TimeoutException("timed out")
        )

        response = client.post(
            "/api/enterprise/token",
            json={
                "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                "client_id": "enterprise-client",
                "client_secret": "enterprise-secret",
            },
        )

        assert response.status_code == 502
        assert "timed out" in response.json()["detail"].lower()

    def test_token_endpoint_http_url_rejected(self, client):
        """HTTP token_endpoint_url rejected with 422 (Pydantic pattern validation)."""
        response = client.post(
            "/api/enterprise/token",
            json={
                "token_endpoint_url": "http://auth.internal/v2/oauth/token",
                "client_id": "enterprise-client",
                "client_secret": "enterprise-secret",
            },
        )

        assert response.status_code == 422

    def test_delete_idempotent_when_cache_empty(self, client):
        """DELETE /api/enterprise/token succeeds even when cache is already empty."""
        response = client.delete("/api/enterprise/token")
        assert response.status_code == 200
        assert response.json()["success"] is True


class TestEnterpriseChatFlow:

    @respx.mock
    def test_enterprise_message_requires_cached_token(self, client, llm_enterprise):
        client.post("/api/llm/config", json=llm_enterprise)
        session = client.post("/api/sessions")

        response = client.post(
            f"/api/sessions/{session.json()['session_id']}/messages",
            json={"role": "user", "content": "Hello enterprise"},
        )

        assert response.status_code == 200
        assert "Fetch an Enterprise Gateway token".lower() in response.json()["message"]["content"].lower()

    @respx.mock
    def test_enterprise_message_uses_gateway(self, client, llm_enterprise):
        client.post("/api/llm/config", json=llm_enterprise)

        respx.post("https://auth.internal/v2/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        )
        client.post(
            "/api/enterprise/token",
            json={
                "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                "client_id": "enterprise-client",
                "client_secret": "enterprise-secret",
            },
        )

        gateway_route = respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions"
        ).mock(return_value=httpx.Response(200, json=_OPENAI_RESPONSE))

        session = client.post("/api/sessions")
        response = client.post(
            f"/api/sessions/{session.json()['session_id']}/messages",
            json={"role": "user", "content": "Hello enterprise"},
        )

        assert response.status_code == 200
        assert response.json()["message"]["content"] == "Enterprise hello!"
        assert gateway_route.called
        assert gateway_route.calls.last.request.headers["authorization"] == "Bearer token-123"

    @respx.mock
    def test_enterprise_gateway_timeout_returns_error_message(self, client, llm_enterprise):
        """Gateway timeout during chat surfaces as an error message (HTTP 200)."""
        client.post("/api/llm/config", json=llm_enterprise)

        respx.post("https://auth.internal/v2/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "token-123", "expires_in": 3600})
        )
        client.post(
            "/api/enterprise/token",
            json={
                "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                "client_id": "enterprise-client",
                "client_secret": "enterprise-secret",
            },
        )

        respx.post(
            "https://llm-gateway.internal/modelgw/models/openai/v1/chat/completions"
        ).mock(side_effect=httpx.TimeoutException("gateway timeout"))

        session = client.post("/api/sessions")
        response = client.post(
            f"/api/sessions/{session.json()['session_id']}/messages",
            json={"role": "user", "content": "Hello"},
        )

        assert response.status_code == 200
        content = response.json()["message"]["content"].lower()
        assert "timeout" in content or "error" in content


class TestEnterpriseConfigChange:
    """Tests that verify credential-change triggers cache invalidation."""

    @respx.mock
    def test_client_id_change_clears_token_cache(self, client, llm_enterprise):
        """Saving enterprise config with a new client_id clears the cached token."""
        respx.post("https://auth.internal/v2/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "token-abc", "expires_in": 3600})
        )
        client.post("/api/llm/config", json=llm_enterprise)
        client.post(
            "/api/enterprise/token",
            json={
                "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                "client_id": "enterprise-client",
                "client_secret": "enterprise-secret",
            },
        )
        assert client.get("/api/enterprise/token/status").json()["token_cached"] is True

        updated = {**llm_enterprise, "client_id": "new-enterprise-client"}
        client.post("/api/llm/config", json=updated)

        assert client.get("/api/enterprise/token/status").json()["token_cached"] is False

    @respx.mock
    def test_base_url_change_clears_token_cache(self, client, llm_enterprise):
        """Saving enterprise config with a new base_url clears the cached token."""
        respx.post("https://auth.internal/v2/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "token-abc", "expires_in": 3600})
        )
        client.post("/api/llm/config", json=llm_enterprise)
        client.post(
            "/api/enterprise/token",
            json={
                "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                "client_id": "enterprise-client",
                "client_secret": "enterprise-secret",
            },
        )
        assert client.get("/api/enterprise/token/status").json()["token_cached"] is True

        updated = {**llm_enterprise, "base_url": "https://new-gateway.internal/v1"}
        client.post("/api/llm/config", json=updated)

        assert client.get("/api/enterprise/token/status").json()["token_cached"] is False

    @respx.mock
    def test_temperature_only_change_preserves_token_cache(self, client, llm_enterprise):
        """Saving enterprise config with only temperature changed keeps the cached token."""
        respx.post("https://auth.internal/v2/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "token-abc", "expires_in": 3600})
        )
        client.post("/api/llm/config", json=llm_enterprise)
        client.post(
            "/api/enterprise/token",
            json={
                "token_endpoint_url": "https://auth.internal/v2/oauth/token",
                "client_id": "enterprise-client",
                "client_secret": "enterprise-secret",
            },
        )
        assert client.get("/api/enterprise/token/status").json()["token_cached"] is True

        updated = {**llm_enterprise, "temperature": 0.9}
        client.post("/api/llm/config", json=updated)

        assert client.get("/api/enterprise/token/status").json()["token_cached"] is True
