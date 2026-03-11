"""
Integration tests — MCP Server CRUD (TR-SRV-*)
"""

import os
import pytest


class TestListServers:

    def test_empty_list_on_fresh_state(self, client):
        """TC-SRV-01: GET /api/servers returns [] when no servers configured."""
        r = client.get("/api/servers")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_after_add(self, client, server_payload):
        """TC-SRV-02: Lists servers that were previously added."""
        client.post("/api/servers", json=server_payload)
        r = client.get("/api/servers")
        assert len(r.json()) == 1

    def test_list_schema(self, client, server_payload):
        """TC-SRV-03: Each item in the list matches ServerConfig schema."""
        from backend.models import ServerConfig
        client.post("/api/servers", json=server_payload)
        r = client.get("/api/servers")
        for item in r.json():
            ServerConfig(**item)  # raises if schema mismatch


class TestCreateServer:

    def test_create_valid_https_server(self, client, server_payload):
        """TC-SRV-05: POST /api/servers with HTTPS URL returns 201."""
        r = client.post("/api/servers", json=server_payload)
        assert r.status_code == 201

    def test_auto_generated_server_id(self, client, server_payload):
        """TC-SRV-06: server_id is a UUID when not provided."""
        r = client.post("/api/servers", json=server_payload)
        data = r.json()
        assert "server_id" in data
        assert len(data["server_id"]) == 36

    def test_http_url_blocked_by_default(self, client, server_payload_http, monkeypatch):
        """TC-SRV-09: HTTP URL rejected when MCP_ALLOW_HTTP_INSECURE not set."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "false")
        r = client.post("/api/servers", json=server_payload_http)
        assert r.status_code == 400

    def test_http_url_allowed_with_insecure_flag(self, client, server_payload_http, monkeypatch):
        """TC-SRV-10: HTTP URL accepted when MCP_ALLOW_HTTP_INSECURE=true."""
        monkeypatch.setenv("MCP_ALLOW_HTTP_INSECURE", "true")
        r = client.post("/api/servers", json=server_payload_http)
        assert r.status_code == 201

    def test_duplicate_alias_returns_409(self, client, server_payload):
        """TC-SRV-07: Duplicate alias returns 409 Conflict."""
        client.post("/api/servers", json=server_payload)
        r = client.post("/api/servers", json=server_payload)
        assert r.status_code == 409

    def test_duplicate_server_id_returns_409(self, client, server_payload):
        """TC-SRV-08: Duplicate server_id returns 409 Conflict."""
        r1 = client.post("/api/servers", json=server_payload)
        sid = r1.json()["server_id"]
        payload2 = {**server_payload, "alias": "other_alias", "server_id": sid}
        r2 = client.post("/api/servers", json=payload2)
        assert r2.status_code == 409

    def test_missing_alias_returns_422(self, client):
        """TC-SRV-11: Missing alias returns 422."""
        r = client.post("/api/servers", json={"base_url": "https://host.com"})
        assert r.status_code == 422

    def test_missing_base_url_returns_422(self, client):
        """TC-SRV-12: Missing base_url returns 422."""
        r = client.post("/api/servers", json={"alias": "svc"})
        assert r.status_code == 422

    def test_all_auth_types_accepted(self, client):
        """TC-SRV-16: none/bearer/api_key all accepted."""
        for i, auth in enumerate(("none", "bearer", "api_key")):
            r = client.post("/api/servers", json={
                "alias": f"svc_{i}",
                "base_url": "https://host.com",
                "auth_type": auth,
            })
            assert r.status_code == 201, f"auth_type={auth} failed"

    def test_default_timeout_ms(self, client, server_payload):
        """TC-SRV-17: timeout_ms defaults to 20000."""
        r = client.post("/api/servers", json=server_payload)
        assert r.json()["timeout_ms"] == 20000

    def test_bearer_token_stored(self, client, server_payload_bearer):
        """TC-SRV-18: bearer_token persisted in response."""
        r = client.post("/api/servers", json=server_payload_bearer)
        assert r.json()["bearer_token"] == "my-secret-token"


class TestUpdateServer:

    def test_update_existing_server(self, client, server_payload):
        """TC-SRV-19: PUT /api/servers/{id} returns 200 with updated data."""
        sid = client.post("/api/servers", json=server_payload).json()["server_id"]
        updated = {**server_payload, "alias": "renamed_server"}
        r = client.put(f"/api/servers/{sid}", json=updated)
        assert r.status_code == 200
        assert r.json()["alias"] == "renamed_server"

    def test_server_id_from_path_wins(self, client, server_payload):
        """TC-SRV-20: server_id in response matches path param, not body."""
        sid = client.post("/api/servers", json=server_payload).json()["server_id"]
        payload_with_wrong_id = {**server_payload, "server_id": "different-id"}
        r = client.put(f"/api/servers/{sid}", json=payload_with_wrong_id)
        assert r.status_code == 200
        assert r.json()["server_id"] == sid

    def test_update_non_existent_returns_404(self, client, server_payload):
        """TC-SRV-21: PUT on unknown server_id returns 404."""
        r = client.put("/api/servers/nonexistent", json=server_payload)
        assert r.status_code == 404

    def test_update_idempotent(self, client, server_payload):
        """TC-SRV-22: Identical PUT twice both return 200."""
        sid = client.post("/api/servers", json=server_payload).json()["server_id"]
        r1 = client.put(f"/api/servers/{sid}", json=server_payload)
        r2 = client.put(f"/api/servers/{sid}", json=server_payload)
        assert r1.status_code == 200
        assert r2.status_code == 200


class TestDeleteServer:

    def test_delete_existing_server(self, client, server_payload):
        """TC-SRV-23: DELETE returns 200 with success=true."""
        sid = client.post("/api/servers", json=server_payload).json()["server_id"]
        r = client.delete(f"/api/servers/{sid}")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_server_absent_after_delete(self, client, server_payload):
        """TC-SRV-24: Server absent from GET /api/servers after delete."""
        sid = client.post("/api/servers", json=server_payload).json()["server_id"]
        client.delete(f"/api/servers/{sid}")
        ids = [s["server_id"] for s in client.get("/api/servers").json()]
        assert sid not in ids

    def test_delete_non_existent_returns_404(self, client):
        """TC-SRV-25: DELETE on unknown id returns 404."""
        r = client.delete("/api/servers/nonexistent")
        assert r.status_code == 404

    def test_delete_idempotent_second_is_404(self, client, server_payload):
        """TC-SRV-27: Second DELETE on same id returns 404."""
        sid = client.post("/api/servers", json=server_payload).json()["server_id"]
        client.delete(f"/api/servers/{sid}")
        r = client.delete(f"/api/servers/{sid}")
        assert r.status_code == 404
