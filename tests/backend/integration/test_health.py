"""
Integration tests — Health check (TR-HC-*)
"""

import pytest


class TestHealth:

    def test_health_returns_200(self, client):
        """TC-HC-01: GET /health returns HTTP 200."""
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_body(self, client):
        """TC-HC-01b: Response contains status=healthy and version."""
        r = client.get("/health")
        data = r.json()
        assert data["status"] == "healthy"
        assert data["version"] == "0.2.0-jsonrpc"

    def test_health_timestamp_present(self, client):
        """TC-HC-03: Response contains a timestamp field."""
        r = client.get("/health")
        assert "timestamp" in r.json()

    def test_health_schema_valid(self, client):
        """TC-HC-02: Response matches HealthResponse shape."""
        from backend.models import HealthResponse
        r = client.get("/health")
        HealthResponse(**r.json())  # raises if schema mismatch
