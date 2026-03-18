"""Azure AD / Entra ID OIDC provider implementation.

Required environment variables:
    AZURE_AD_CLIENT_ID     — App registration client ID
    AZURE_AD_CLIENT_SECRET — App registration client secret  (never logged)
    AZURE_AD_TENANT_ID     — Tenant ID (used to form the discovery / token URLs)
    AZURE_AD_REDIRECT_URI  — Must match the URI registered in Azure

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


class AzureADProvider(OIDCProvider):
    """OIDC provider for Microsoft Azure AD / Entra ID."""

    def __init__(self) -> None:
        self._client_id = os.environ["AZURE_AD_CLIENT_ID"]
        self._client_secret = os.environ["AZURE_AD_CLIENT_SECRET"]
        self._tenant_id = os.environ["AZURE_AD_TENANT_ID"]
        self._redirect_uri = os.environ["AZURE_AD_REDIRECT_URI"]
        base = f"https://login.microsoftonline.com/{self._tenant_id}/v2.0"
        self._auth_endpoint = f"{base}/authorize"
        self._token_endpoint = f"{base}/token"
        jwks_uri = f"{base}/keys"
        self._jwks = JWKSCache(jwks_uri)

    # --- OIDCProvider interface ---

    @property
    def provider_key(self) -> str:
        return "azure_ad"

    @property
    def display_label(self) -> str:
        return "Sign in with Microsoft"

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
        }
        return f"{self._auth_endpoint}?{urlencode(params)}"

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
                self._token_endpoint,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
        return resp.json()

    async def validate_id_token(self, id_token: str, nonce: str) -> OIDCUserInfo:
        header = jwt.get_unverified_header(id_token)
        kid: Optional[str] = header.get("kid")
        keys = await self._jwks.get_keys()
        jwk = self._jwks.find_key(kid)

        if jwk is None:
            # Force refresh once and retry
            keys = await self._jwks.get_keys(force_refresh=True)
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
        )

        if payload.get("nonce") != nonce:
            raise jwt.InvalidTokenError("nonce mismatch")

        return OIDCUserInfo(
            sub=payload["sub"],
            email=payload.get("email") or payload.get("preferred_username", ""),
            display_name=payload.get("name", ""),
            avatar_url=payload.get("picture"),
        )

    @classmethod
    def is_configured(cls) -> bool:
        """Return True if all required env vars are set."""
        return all(
            os.getenv(k)
            for k in (
                "AZURE_AD_CLIENT_ID",
                "AZURE_AD_CLIENT_SECRET",
                "AZURE_AD_TENANT_ID",
                "AZURE_AD_REDIRECT_URI",
            )
        )
