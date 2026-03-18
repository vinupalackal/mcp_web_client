"""Application JWT issue / verify utilities.

Uses HS256 symmetric signing with the SECRET_KEY environment variable.
The app_token is set as an HttpOnly session cookie by the auth callback handler.
"""
import os
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

import jwt

logger = logging.getLogger("mcp_client.internal")

_SECRET_KEY: str = os.getenv("SECRET_KEY", "")  # Must be set in production


def _get_secret() -> str:
    key = os.getenv("SECRET_KEY", _SECRET_KEY)
    if not key:
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return key


def issue_app_token(
    user_id: str,
    email: str,
    roles: list,
    ttl_hours: int = 8,
) -> str:
    """Issue a signed HS256 JWT for the given user.

    Args:
        user_id: Immutable UUID of the user.
        email: User's primary email.
        roles: List of role strings, e.g. ["user"] or ["user", "admin"].
        ttl_hours: Token lifetime in hours (default 8).

    Returns:
        Signed JWT string.
    """
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "roles": roles,
        "iat": now,
        "exp": now + timedelta(hours=ttl_hours),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, _get_secret(), algorithm="HS256")
    return token


def verify_app_token(token: str) -> Dict[str, Any]:
    """Verify and decode an app_token JWT.

    Returns:
        Decoded payload dict with 'sub', 'email', 'roles', 'exp', etc.

    Raises:
        jwt.ExpiredSignatureError: Token has expired.
        jwt.InvalidTokenError: Token is malformed or signature invalid.
    """
    return jwt.decode(token, _get_secret(), algorithms=["HS256"])
