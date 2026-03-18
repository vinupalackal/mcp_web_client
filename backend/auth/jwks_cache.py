"""JWKS (JSON Web Key Set) public-key cache with configurable TTL.

Fetches the IdP's JWKS endpoint to obtain RSA/EC public keys for id_token validation.
On cache miss or TTL expiry the cache is refreshed from the network.
On validation failure a forced refresh is attempted once before raising.
"""
import logging
import os
import time
from typing import Dict, Any, Optional, List

import httpx

logger = logging.getLogger("mcp_client.internal")

_CACHE_TTL_SECONDS = int(os.getenv("JWKS_CACHE_TTL_SECONDS", "3600"))


class JWKSCache:
    """Thread-safe-enough JWKS key cache for single-process FastAPI deployments."""

    def __init__(self, jwks_uri: str, ttl: int = _CACHE_TTL_SECONDS) -> None:
        self._jwks_uri = jwks_uri
        self._ttl = ttl
        self._keys: List[Dict[str, Any]] = []
        self._fetched_at: float = 0.0

    def _is_stale(self) -> bool:
        return (time.monotonic() - self._fetched_at) > self._ttl

    async def _fetch(self) -> None:
        logger.info(f"Fetching JWKS from {self._jwks_uri}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(self._jwks_uri)
            resp.raise_for_status()
            data = resp.json()
        self._keys = data.get("keys", [])
        self._fetched_at = time.monotonic()
        logger.info(f"JWKS cache refreshed: {len(self._keys)} keys")

    async def get_keys(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Return current list of JWKS keys, refreshing if stale or forced."""
        if force_refresh or self._is_stale():
            await self._fetch()
        return self._keys

    def find_key(self, kid: Optional[str]) -> Optional[Dict[str, Any]]:
        """Find a key by key ID (kid). Returns None if not found."""
        if not kid:
            return self._keys[0] if self._keys else None
        return next((k for k in self._keys if k.get("kid") == kid), None)
