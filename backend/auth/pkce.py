"""PKCE code-verifier / code-challenge helpers and opaque state token generation.

All values are generated using cryptographically secure randomness (secrets module).
Code challenge uses S256 method as required by the security policy (no plain allowed).
"""
import base64
import hashlib
import secrets
from typing import Tuple


def generate_pkce_pair() -> Tuple[str, str]:
    """Generate a PKCE (code_verifier, code_challenge) pair.

    Returns:
        (code_verifier, code_challenge)
        code_verifier — random 64-byte URL-safe base64 string (no padding)
        code_challenge — BASE64URL(SHA-256(code_verifier)) without padding
    """
    verifier_bytes = secrets.token_bytes(64)
    code_verifier = base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode()
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def generate_state_token(nbytes: int = 32) -> str:
    """Generate a cryptographically secure opaque state / nonce token."""
    return secrets.token_urlsafe(nbytes)
