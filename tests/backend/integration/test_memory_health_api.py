"""Integration tests for memory health reporting."""

import backend.main as main_module


class _FakeMemoryService:
    def __init__(self, status_payload):
        self.status_payload = status_payload

    async def health_status(self):
        return dict(self.status_payload)


class TestMemoryHealthApi:

    def test_health_memory_disabled(self, client):
        """TC-HEALTH-01: Health reports memory disabled when no memory service is wired."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["memory"] == {"enabled": False}

    def test_health_memory_enabled_healthy(self, client):
        """TC-HEALTH-02: Health includes memory healthy payload when memory is wired."""
        main_module._memory_service = _FakeMemoryService(
            {
                "enabled": True,
                "healthy": True,
                "degraded": False,
                "status": "healthy",
                "reason": None,
                "warnings": [],
                "milvus_reachable": True,
                "embedding_available": True,
                "active_collections": ["mcp_client_code_memory_v1"],
            }
        )

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["memory"]["enabled"] is True
        assert data["memory"]["healthy"] is True
        assert data["memory"]["degraded"] is False

    def test_health_memory_enabled_degraded_does_not_change_top_level_status(self, client):
        """TC-HEALTH-03: Memory degraded state does not degrade overall app health."""
        main_module._memory_service = _FakeMemoryService(
            {
                "enabled": True,
                "healthy": False,
                "degraded": True,
                "status": "degraded",
                "reason": "Milvus unreachable",
                "warnings": ["Memory degraded mode is active"],
                "milvus_reachable": False,
                "embedding_available": True,
                "active_collections": [],
            }
        )

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["memory"]["degraded"] is True
        assert data["memory"]["reason"] == "Milvus unreachable"
