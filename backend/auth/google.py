"""Google Workspace OIDC provider implementation.

Required environment variables:
    GOOGLE_CLIENT_ID      — OAuth 2.0 client ID
    GOOGLE_CLIENT_SECRET  — OAuth 2.0 client secret  (never logged)
    GOOGLE_REDIRECT_URI   — Must match the URI in Google Cloud Console

Optional:
    JWKS_CACHE_TTL_SECONDS — Override JWKS key cache TTL (default 3600 s)
"""
import os
import logging
from typing import Optional
from urllib.parse import urlencode

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from backend.auth.provider import OIDCProvider, OIDCUserInfo
from backend.auth.jwks_cache import JWKSCache

logger = logging.getLogger("mcp_client.internal")

_GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUER = "https://accounts.google.com"


class GoogleProvider(OIDCProvider):
    """OIDC provider for Google Workspace."""

    def __init__(self) -> None:
        self._client_id = os.environ["GOOGLE_CLIENT_ID"]
        self._client_secret = os.environ["GOOGLE_CLIENT_SECRET"]
        self._redirect_uri = os.environ["GOOGLE_REDIRECT_URI"]
        self._jwks = JWKSCache(_GOOGLE_JWKS_URI)

    # --- OIDCProvider interface ---

    @property
    def provider_key(self) -> str:
        return "google"

    @property
    def display_label(self) -> str:
        return "Sign in with Google"

    def build_authorisation_url(
        self, state: str, nonce: str, code_challenge: str
    ) -> str:
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
        }
        return f"{_GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"

    async def exchange_code(self, code: str, code_verifier: str) -> dict:
        data = {
            "grant_type": "authorization_code",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "redirect_uri": self._redirect_uri,
            "code_verifier": code_verifier,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _GOOGLE_TOKEN_ENDPOINT,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
        return resp.json()

    async def validate_id_token(self, id_token: str, nonce: str) -> OIDCUserInfo:
        header = jwt.get_unverified_header(id_token)
        kid: Optional[str] = header.get("kid")
        await self._jwks.get_keys()
        jwk = self._jwks.find_key(kid)

        if jwk is None:
            await self._jwks.get_keys(force_refresh=True)
            jwk = self._jwks.find_key(kid)
            if jwk is None:
                raise jwt.InvalidTokenError(f"No matching key for kid={kid}")

        import json as _json
        public_key = RSAAlgorithm.from_jwk(_json.dumps(jwk))
        payload = jwt.decode(
            id_token,
            public_key,
            algorithms=["RS256"],
            audience=self._client_id,
            options={"verify_iss": True},
            issuer=_GOOGLE_ISSUER,
        )

        if payload.get("nonce") != nonce:
            raise jwt.InvalidTokenError("nonce mismatch")

        return OIDCUserInfo(
            sub=payload["sub"],
            email=payload.get("email", ""),
            display_name=payload.get("name", ""),
            avatar_url=payload.get("picture"),
        )

    @classmethod
    def is_configured(cls) -> bool:
        return all(
            os.getenv(k)
            for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")
        )
