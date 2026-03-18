"""
Unit tests for JWT issue/verify utilities (backend.auth.jwt_utils)
Test IDs: TC-JWT-*
"""

import time

import jwt as pyjwt
import pytest

from backend.auth.jwt_utils import issue_app_token, verify_app_token


# ============================================================================
# issue_app_token
# ============================================================================

class TestIssueAppToken:

    def test_returns_non_empty_string(self, secret_key):
        """TC-JWT-01: issue_app_token returns a non-empty string."""
        token = issue_app_token("uid-001", "alice@example.com", ["user"])
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_has_three_dot_separated_parts(self, secret_key):
        """TC-JWT-02: Token is a three-part dot-separated JWT."""
        token = issue_app_token("uid-001", "alice@example.com", ["user"])
        assert token.count(".") == 2

    def test_raises_runtime_error_without_secret_key(self, monkeypatch):
        """TC-JWT-03: RuntimeError raised when SECRET_KEY env var is unset."""
        monkeypatch.delenv("SECRET_KEY", raising=False)
        import backend.auth.jwt_utils as jwt_mod
        monkeypatch.setattr(jwt_mod, "_SECRET_KEY", "")
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            issue_app_token("uid", "a@b.com", ["user"])

    def test_payload_contains_required_claims(self, secret_key):
        """TC-JWT-04: Decoded payload contains sub, email, roles, iat, exp, jti."""
        token = issue_app_token("uid-001", "alice@example.com", ["user"])
        payload = pyjwt.decode(token, secret_key, algorithms=["HS256"])
        for claim in ("sub", "email", "roles", "iat", "exp", "jti"):
            assert claim in payload, f"Missing JWT claim: {claim}"

    def test_sub_equals_user_id(self, secret_key):
        """TC-JWT-05: 'sub' claim equals the provided user_id."""
        token = issue_app_token("uid-abc-123", "test@example.com", ["user"])
        payload = pyjwt.decode(token, secret_key, algorithms=["HS256"])
        assert payload["sub"] == "uid-abc-123"

    def test_email_preserved_in_payload(self, secret_key):
        """TC-JWT-06: 'email' claim equals the provided email."""
        token = issue_app_token("uid-001", "bob@corp.com", ["user"])
        payload = pyjwt.decode(token, secret_key, algorithms=["HS256"])
        assert payload["email"] == "bob@corp.com"

    def test_roles_preserved_in_payload(self, secret_key):
        """TC-JWT-07: 'roles' claim reflects the provided roles list."""
        token = issue_app_token("uid-001", "admin@corp.com", ["user", "admin"])
        payload = pyjwt.decode(token, secret_key, algorithms=["HS256"])
        assert payload["roles"] == ["user", "admin"]

    def test_consecutive_tokens_have_unique_jti(self, secret_key):
        """TC-JWT-08: Consecutive tokens for the same user have distinct jti values."""
        t1 = issue_app_token("uid-001", "a@b.com", ["user"])
        t2 = issue_app_token("uid-001", "a@b.com", ["user"])
        p1 = pyjwt.decode(t1, secret_key, algorithms=["HS256"])
        p2 = pyjwt.decode(t2, secret_key, algorithms=["HS256"])
        assert p1["jti"] != p2["jti"]

    def test_default_ttl_is_approximately_8_hours(self, secret_key):
        """TC-JWT-09: Default expiry is approximately 8 hours from now."""
        before = int(time.time())
        token = issue_app_token("uid-001", "a@b.com", ["user"])
        payload = pyjwt.decode(token, secret_key, algorithms=["HS256"])
        delta = payload["exp"] - before
        # Allow ±5 s for execution time
        assert 8 * 3600 - 5 <= delta <= 8 * 3600 + 5

    def test_custom_ttl_hours_reflected_in_expiry(self, secret_key):
        """TC-JWT-10: Custom ttl_hours is reflected in the exp claim."""
        before = int(time.time())
        token = issue_app_token("uid-001", "a@b.com", ["user"], ttl_hours=2)
        payload = pyjwt.decode(token, secret_key, algorithms=["HS256"])
        delta = payload["exp"] - before
        assert 2 * 3600 - 5 <= delta <= 2 * 3600 + 5


# ============================================================================
# verify_app_token
# ============================================================================

class TestVerifyAppToken:

    def test_valid_token_returns_correct_payload(self, secret_key):
        """TC-JWT-11: verify_app_token returns correct payload for a valid token."""
        token = issue_app_token("uid-001", "alice@example.com", ["user"])
        payload = verify_app_token(token)
        assert payload["sub"] == "uid-001"
        assert payload["email"] == "alice@example.com"
        assert payload["roles"] == ["user"]

    def test_expired_token_raises_expired_signature_error(self, secret_key):
        """TC-JWT-12: Expired token raises jwt.ExpiredSignatureError."""
        token = issue_app_token("uid-001", "a@b.com", ["user"], ttl_hours=0)
        # ttl_hours=0 → exp == iat; wait 1 s to ensure expiry
        time.sleep(1)
        with pytest.raises(pyjwt.ExpiredSignatureError):
            verify_app_token(token)

    def test_wrong_secret_raises_invalid_token_error(self, secret_key):
        """TC-JWT-13: Token verified against a different key raises InvalidTokenError."""
        token = issue_app_token("uid-001", "a@b.com", ["user"])
        with pytest.raises(pyjwt.InvalidTokenError):
            pyjwt.decode(token, "completely-wrong-secret", algorithms=["HS256"])

    def test_tampered_payload_raises_invalid_token_error(self, secret_key):
        """TC-JWT-14: Altering the payload invalidates the HMAC signature."""
        import base64
        import json

        token = issue_app_token("uid-001", "a@b.com", ["user"])
        header, payload_b64, sig = token.split(".")
        # Decode, mutate, re-encode
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_data = json.loads(base64.urlsafe_b64decode(padded))
        payload_data["roles"] = ["user", "admin"]
        new_payload = base64.urlsafe_b64encode(
            json.dumps(payload_data).encode()
        ).rstrip(b"=").decode()
        tampered = f"{header}.{new_payload}.{sig}"
        with pytest.raises(pyjwt.InvalidTokenError):
            verify_app_token(tampered)

    def test_malformed_string_raises_invalid_token_error(self, secret_key):
        """TC-JWT-15: Non-JWT string raises InvalidTokenError."""
        with pytest.raises(pyjwt.InvalidTokenError):
            verify_app_token("not.a.jwt")

    def test_empty_string_raises_invalid_token_error(self, secret_key):
        """TC-JWT-16: Empty string raises InvalidTokenError."""
        with pytest.raises(pyjwt.InvalidTokenError):
            verify_app_token("")
