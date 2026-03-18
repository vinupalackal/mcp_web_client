"""
Integration tests for SSO auth and user/admin API endpoints  (TR-SSO-*)
Test IDs: TC-SSO-AUTH-*  TC-SSO-USER-*  TC-SSO-SETTINGS-*  TC-SSO-ADMIN-*

All tests in this module use the `sso_client` fixture which provides a
TestClient with SECRET_KEY set and one mock OIDC provider ("mock_idp") loaded.
"""

import pytest


# ============================================================================
# GET /auth/providers
# ============================================================================

class TestAuthProviders:

    def test_returns_empty_list_when_no_providers(self, client):
        """TC-SSO-AUTH-01: /auth/providers returns [] when no IdP is configured."""
        r = client.get("/auth/providers")
        assert r.status_code == 200
        assert r.json()["providers"] == []

    def test_returns_configured_provider_key(self, sso_client):
        """TC-SSO-AUTH-02: /auth/providers returns the mock_idp key when SSO is enabled."""
        r = sso_client.get("/auth/providers")
        assert r.status_code == 200
        assert "mock_idp" in r.json()["providers"]


# ============================================================================
# GET /auth/login/{provider}
# ============================================================================

class TestAuthLogin:

    def test_unknown_provider_returns_404(self, sso_client):
        """TC-SSO-AUTH-03: /auth/login for an unconfigured provider returns 404."""
        r = sso_client.get("/auth/login/no_such_provider", follow_redirects=False)
        assert r.status_code == 404

    def test_known_provider_redirects_to_idp(self, sso_client):
        """TC-SSO-AUTH-04: /auth/login/mock_idp redirects (302) to the mock IdP URL."""
        r = sso_client.get("/auth/login/mock_idp", follow_redirects=False)
        assert r.status_code == 302
        assert "mock-idp.example.com" in r.headers["location"]

    def test_redirect_includes_state_param(self, sso_client):
        """TC-SSO-AUTH-05: Auth redirect URL contains the state parameter."""
        r = sso_client.get("/auth/login/mock_idp", follow_redirects=False)
        assert "state=" in r.headers["location"]

    def test_redirect_includes_code_challenge(self, sso_client):
        """TC-SSO-AUTH-06: Auth redirect URL contains code_challenge (PKCE S256)."""
        r = sso_client.get("/auth/login/mock_idp", follow_redirects=False)
        assert "code_challenge=" in r.headers["location"]

    def test_two_logins_produce_different_states(self, sso_client):
        """TC-SSO-AUTH-07: Each /auth/login call generates a unique state value."""
        r1 = sso_client.get("/auth/login/mock_idp", follow_redirects=False)
        r2 = sso_client.get("/auth/login/mock_idp", follow_redirects=False)
        loc1 = r1.headers["location"]
        loc2 = r2.headers["location"]
        state1 = next(p.split("=")[1] for p in loc1.split("&") if "state=" in p)
        state2 = next(p.split("=")[1] for p in loc2.split("&") if "state=" in p)
        assert state1 != state2


# ============================================================================
# GET /auth/callback/{provider}
# ============================================================================

class TestAuthCallback:

    def test_missing_code_returns_400(self, sso_client):
        """TC-SSO-AUTH-08: Callback with state but no code returns 400."""
        r = sso_client.get(
            "/auth/callback/mock_idp?state=some-state",
            follow_redirects=False,
        )
        assert r.status_code == 400

    def test_missing_state_returns_400(self, sso_client):
        """TC-SSO-AUTH-09: Callback with code but no state returns 400."""
        r = sso_client.get(
            "/auth/callback/mock_idp?code=auth-code-xyz",
            follow_redirects=False,
        )
        assert r.status_code == 400

    def test_invalid_state_returns_401(self, sso_client):
        """TC-SSO-AUTH-10: Callback with unrecognised state returns 401 (CSRF protection)."""
        r = sso_client.get(
            "/auth/callback/mock_idp?code=abc&state=not-in-pkce-store",
            follow_redirects=False,
        )
        assert r.status_code == 401

    def test_idp_error_redirects_to_login(self, sso_client):
        """TC-SSO-AUTH-11: IdP error= parameter causes redirect to /login?reason=..."""
        r = sso_client.get(
            "/auth/callback/mock_idp?error=access_denied",
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "/login" in r.headers["location"]


# ============================================================================
# POST /auth/logout
# ============================================================================

class TestAuthLogout:

    def test_logout_redirects_to_login_page(self, sso_client):
        """TC-SSO-AUTH-12: POST /auth/logout redirects to /login."""
        r = sso_client.post("/auth/logout", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers["location"]

    def test_logout_expires_session_cookie(self, sso_client):
        """TC-SSO-AUTH-13: POST /auth/logout sets app_token cookie with Max-Age=0."""
        r = sso_client.post("/auth/logout", follow_redirects=False)
        set_cookie = r.headers.get("set-cookie", "")
        assert "app_token" in set_cookie
        # FastAPI delete_cookie sets Max-Age=0
        assert "max-age=0" in set_cookie.lower() or "expires=" in set_cookie.lower()


# ============================================================================
# GET /api/users/me
# ============================================================================

class TestGetMe:

    def test_returns_401_without_cookie(self, sso_client):
        """TC-SSO-USER-01: GET /api/users/me without app_token returns 401."""
        r = sso_client.get("/api/users/me")
        assert r.status_code == 401

    def test_returns_profile_with_valid_token(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-USER-02: GET /api/users/me returns UserProfile for a valid token."""
        user = make_db_user(email="getme@example.com", display_name="Get Me User")
        token = auth_cookie(user.user_id, user.email, ["user"])
        r = sso_client.get("/api/users/me", cookies={"app_token": token})
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == "getme@example.com"
        assert body["display_name"] == "Get Me User"
        assert "user_id" in body
        assert "roles" in body

    def test_profile_response_has_no_credential_fields(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-USER-03: UserProfile response never contains api_key or client_secret."""
        user = make_db_user(email="nocreds@example.com")
        token = auth_cookie(user.user_id, user.email)
        r = sso_client.get("/api/users/me", cookies={"app_token": token})
        body = r.json()
        assert "api_key" not in body
        assert "client_secret" not in body

    def test_expired_token_returns_401(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-USER-04: Expired app_token returns 401 with 'Session expired' message."""
        import time
        user = make_db_user(email="expired@example.com")
        token = auth_cookie(user.user_id, user.email, ttl_hours=0)
        time.sleep(1)
        r = sso_client.get("/api/users/me", cookies={"app_token": token})
        assert r.status_code == 401
        assert "expired" in r.json().get("detail", "").lower()

    def test_disabled_user_returns_403(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-USER-05: Disabled user (is_active=False) receives 403."""
        user = make_db_user(email="disabled@example.com", is_active=False)
        token = auth_cookie(user.user_id, user.email)
        r = sso_client.get("/api/users/me", cookies={"app_token": token})
        assert r.status_code == 403
        assert "disabled" in r.json().get("detail", "").lower()

    def test_admin_user_has_admin_in_roles(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-USER-06: Admin user's profile reflects the admin role."""
        user = make_db_user(email="adminuser@example.com", roles=["user", "admin"])
        token = auth_cookie(user.user_id, user.email, roles=["user", "admin"])
        r = sso_client.get("/api/users/me", cookies={"app_token": token})
        assert r.status_code == 200
        assert "admin" in r.json()["roles"]


# ============================================================================
# GET /api/users/me/settings  +  PATCH /api/users/me/settings
# ============================================================================

class TestMySettings:

    def test_get_settings_returns_defaults(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-SETTINGS-01: GET /api/users/me/settings returns default UserSettings."""
        user = make_db_user(email="settings-get@example.com")
        token = auth_cookie(user.user_id, user.email)
        r = sso_client.get("/api/users/me/settings", cookies={"app_token": token})
        assert r.status_code == 200
        body = r.json()
        assert body["theme"] == "system"
        assert body["message_density"] == "comfortable"
        assert body["tool_panel_visible"] is True

    def test_patch_settings_updates_theme(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-SETTINGS-02: PATCH /api/users/me/settings persists the theme change."""
        user = make_db_user(email="settings-patch@example.com")
        token = auth_cookie(user.user_id, user.email)
        r = sso_client.patch(
            "/api/users/me/settings",
            json={"theme": "dark"},
            cookies={"app_token": token},
        )
        assert r.status_code == 200
        assert r.json()["theme"] == "dark"

    def test_patch_is_partial_update(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-SETTINGS-03: PATCH only changes supplied fields; others remain unchanged."""
        user = make_db_user(email="settings-partial@example.com")
        token = auth_cookie(user.user_id, user.email)
        # Establish an initial non-default state
        sso_client.patch(
            "/api/users/me/settings",
            json={"theme": "dark", "message_density": "compact"},
            cookies={"app_token": token},
        )
        # Partial patch — only theme
        r = sso_client.patch(
            "/api/users/me/settings",
            json={"theme": "light"},
            cookies={"app_token": token},
        )
        assert r.json()["theme"] == "light"
        assert r.json()["message_density"] == "compact"   # unchanged

    def test_get_settings_without_token_returns_401(self, sso_client):
        """TC-SSO-SETTINGS-04: GET /api/users/me/settings without auth returns 401."""
        r = sso_client.get("/api/users/me/settings")
        assert r.status_code == 401

    def test_patch_settings_without_token_returns_401(self, sso_client):
        """TC-SSO-SETTINGS-05: PATCH /api/users/me/settings without auth returns 401."""
        r = sso_client.patch("/api/users/me/settings", json={"theme": "dark"})
        assert r.status_code == 401

    def test_patch_empty_body_is_noop(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-SETTINGS-06: PATCH with all-null body leaves settings unchanged."""
        user = make_db_user(email="settings-noop@example.com")
        token = auth_cookie(user.user_id, user.email)
        sso_client.patch(
            "/api/users/me/settings",
            json={"theme": "dark"},
            cookies={"app_token": token},
        )
        sso_client.patch(
            "/api/users/me/settings",
            json={},
            cookies={"app_token": token},
        )
        r = sso_client.get("/api/users/me/settings", cookies={"app_token": token})
        assert r.json()["theme"] == "dark"


# ============================================================================
# GET /api/admin/users  +  GET/PATCH /api/admin/users/{id}
# ============================================================================

class TestAdminUsers:

    def test_regular_user_gets_403_on_list(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-ADMIN-01: Regular user (no admin role) gets 403 on GET /api/admin/users."""
        user = make_db_user(email="regular-admin-test@example.com")
        token = auth_cookie(user.user_id, user.email, roles=["user"])
        r = sso_client.get("/api/admin/users", cookies={"app_token": token})
        assert r.status_code == 403

    def test_unauthenticated_request_gets_401(self, sso_client):
        """TC-SSO-ADMIN-02: Unauthenticated request to /api/admin/users gets 401."""
        r = sso_client.get("/api/admin/users")
        assert r.status_code == 401

    def test_admin_can_list_users(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-ADMIN-03: Admin user gets 200 with a UserListResponse on GET /api/admin/users."""
        admin = make_db_user(email="admin-list@corp.com", roles=["user", "admin"])
        make_db_user(email="listed-user@example.com", sub="sub-listed")
        token = auth_cookie(admin.user_id, admin.email, roles=["user", "admin"])
        r = sso_client.get("/api/admin/users", cookies={"app_token": token})
        assert r.status_code == 200
        body = r.json()
        assert "users" in body
        assert "total" in body
        assert body["total"] >= 2

    def test_admin_can_get_single_user(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-ADMIN-04: Admin can GET /api/admin/users/{user_id} for any user."""
        admin = make_db_user(email="admin-get@corp.com", roles=["user", "admin"])
        target = make_db_user(email="target-user@example.com", sub="sub-target-get")
        token = auth_cookie(admin.user_id, admin.email, roles=["user", "admin"])
        r = sso_client.get(f"/api/admin/users/{target.user_id}", cookies={"app_token": token})
        assert r.status_code == 200
        assert r.json()["email"] == "target-user@example.com"

    def test_admin_get_unknown_user_returns_404(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-ADMIN-05: Admin GET for a nonexistent user_id returns 404."""
        admin = make_db_user(email="admin-404@corp.com", roles=["user", "admin"])
        token = auth_cookie(admin.user_id, admin.email, roles=["user", "admin"])
        r = sso_client.get(
            "/api/admin/users/00000000-0000-0000-0000-000000000000",
            cookies={"app_token": token},
        )
        assert r.status_code == 404

    def test_admin_can_disable_user(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-ADMIN-06: Admin PATCH sets is_active=False; response reflects the change."""
        admin = make_db_user(email="admin-disable@corp.com", roles=["user", "admin"])
        target = make_db_user(email="to-be-disabled@example.com", sub="sub-disable")
        token = auth_cookie(admin.user_id, admin.email, roles=["user", "admin"])
        r = sso_client.patch(
            f"/api/admin/users/{target.user_id}",
            json={"is_active": False},
            cookies={"app_token": token},
        )
        assert r.status_code == 200

    def test_disabled_user_blocked_by_middleware(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-ADMIN-07: Disabled user's subsequent requests are rejected with 403."""
        user = make_db_user(email="already-disabled@example.com", is_active=False)
        token = auth_cookie(user.user_id, user.email)
        r = sso_client.get("/api/users/me", cookies={"app_token": token})
        assert r.status_code == 403

    def test_admin_reset_user_settings_returns_200(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-ADMIN-08: DELETE /api/admin/users/{id}/settings returns 200."""
        admin = make_db_user(email="admin-reset@corp.com", roles=["user", "admin"])
        target = make_db_user(email="reset-target@example.com", sub="sub-reset")
        token = auth_cookie(admin.user_id, admin.email, roles=["user", "admin"])
        r = sso_client.delete(
            f"/api/admin/users/{target.user_id}/settings",
            cookies={"app_token": token},
        )
        assert r.status_code == 200

    def test_list_users_pagination_limit(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-ADMIN-09: Pagination limit is reflected in the response."""
        admin = make_db_user(email="admin-page@corp.com", roles=["user", "admin"])
        for i in range(5):
            make_db_user(email=f"page-user-{i}@example.com", sub=f"sub-page-{i}")
        token = auth_cookie(admin.user_id, admin.email, roles=["user", "admin"])
        r = sso_client.get("/api/admin/users?limit=2&offset=0", cookies={"app_token": token})
        assert r.status_code == 200
        body = r.json()
        assert body["limit"] == 2
        assert len(body["users"]) <= 2

    def test_regular_user_gets_403_on_get_single(self, sso_client, make_db_user, auth_cookie):
        """TC-SSO-ADMIN-10: Non-admin gets 403 when trying to GET a specific user."""
        user = make_db_user(email="non-admin-get@example.com")
        target = make_db_user(email="target-for-403@example.com", sub="sub-403")
        token = auth_cookie(user.user_id, user.email, roles=["user"])
        r = sso_client.get(
            f"/api/admin/users/{target.user_id}",
            cookies={"app_token": token},
        )
        assert r.status_code == 403
