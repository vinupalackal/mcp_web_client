"""Integration tests for manual memory maintenance endpoint."""

import backend.main as main_module


def _set_auth_cookie(client, token: str) -> None:
    client.cookies.set("app_token", token)


class _FakeMemoryMaintenanceService:
    def __init__(self):
        self.calls = []

    def run_expiry_cleanup_if_due(
        self,
        *,
        force=False,
        cleanup_expired_conversation_memory=True,
        cleanup_expired_tool_cache=True,
    ):
        self.calls.append(
            {
                "force": force,
                "cleanup_expired_conversation_memory": cleanup_expired_conversation_memory,
                "cleanup_expired_tool_cache": cleanup_expired_tool_cache,
            }
        )
        return {
            "ran": True,
            "conversation_deleted": 2,
            "tool_cache_deleted": 4,
            "cleaned_at": "2026-04-02T10:15:00+00:00",
        }


class TestMemoryMaintenanceApi:

    def test_maintenance_returns_503_when_memory_service_unavailable(self, client):
        """TC-MAINT-01: Endpoint returns 503 when memory subsystem is unavailable."""
        response = client.post(
            "/api/admin/memory/maintenance",
            json={
                "force": True,
                "cleanup_expired_conversation_memory": True,
                "cleanup_expired_tool_cache": True,
            },
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "Memory subsystem is not available"

    def test_maintenance_runs_and_returns_summary(self, client):
        """TC-MAINT-02: Endpoint runs cleanup and returns structured summary."""
        service = _FakeMemoryMaintenanceService()
        main_module._memory_service = service

        response = client.post(
            "/api/admin/memory/maintenance",
            json={
                "force": True,
                "cleanup_expired_conversation_memory": True,
                "cleanup_expired_tool_cache": False,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["message"] == "Memory maintenance completed"
        assert body["summary"]["ran"] is True
        assert body["summary"]["conversation_deleted"] == 2
        assert body["summary"]["tool_cache_deleted"] == 4
        assert service.calls == [
            {
                "force": True,
                "cleanup_expired_conversation_memory": True,
                "cleanup_expired_tool_cache": False,
            }
        ]

    def test_maintenance_requires_auth_when_sso_enabled(self, sso_client):
        """TC-MAINT-03: Unauthenticated request gets 401 when SSO is enabled."""
        main_module._memory_service = _FakeMemoryMaintenanceService()

        response = sso_client.post(
            "/api/admin/memory/maintenance",
            json={"force": True},
        )

        assert response.status_code == 401

    def test_maintenance_requires_admin_role_when_sso_enabled(
        self,
        sso_client,
        make_db_user,
        auth_cookie,
    ):
        """TC-MAINT-04: Regular user gets 403 for admin maintenance endpoint."""
        main_module._memory_service = _FakeMemoryMaintenanceService()
        user = make_db_user(email="regular-maint@example.com", roles=["user"])
        token = auth_cookie(user.user_id, user.email, roles=["user"])
        _set_auth_cookie(sso_client, token)

        response = sso_client.post(
            "/api/admin/memory/maintenance",
            json={"force": True},
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "Admin role required"

    def test_admin_can_run_maintenance_when_sso_enabled(
        self,
        sso_client,
        make_db_user,
        auth_cookie,
    ):
        """TC-MAINT-05: Admin user can run the maintenance endpoint."""
        service = _FakeMemoryMaintenanceService()
        main_module._memory_service = service
        admin = make_db_user(email="admin-maint@example.com", roles=["user", "admin"])
        token = auth_cookie(admin.user_id, admin.email, roles=["user", "admin"])
        _set_auth_cookie(sso_client, token)

        response = sso_client.post(
            "/api/admin/memory/maintenance",
            json={
                "force": False,
                "cleanup_expired_conversation_memory": False,
                "cleanup_expired_tool_cache": True,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["summary"]["ran"] is True
        assert service.calls == [
            {
                "force": False,
                "cleanup_expired_conversation_memory": False,
                "cleanup_expired_tool_cache": True,
            }
        ]
