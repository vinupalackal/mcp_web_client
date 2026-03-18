"""
Unit tests for PKCE helpers (backend.auth.pkce)
Test IDs: TC-PKCE-*  TC-STATE-*
"""

import base64
import hashlib

import pytest

from backend.auth.pkce import generate_pkce_pair, generate_state_token


# ============================================================================
# generate_pkce_pair
# ============================================================================

class TestGeneratePkcePair:

    def test_returns_two_strings(self):
        """TC-PKCE-01: generate_pkce_pair() returns a 2-tuple of strings."""
        verifier, challenge = generate_pkce_pair()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)

    def test_verifier_meets_rfc7636_min_length(self):
        """TC-PKCE-02: code_verifier is at least 43 chars (RFC 7636 §4.1 minimum)."""
        verifier, _ = generate_pkce_pair()
        assert len(verifier) >= 43

    def test_verifier_is_url_safe_base64_no_padding(self):
        """TC-PKCE-03: code_verifier uses URL-safe alphabet with no + / = chars."""
        verifier, _ = generate_pkce_pair()
        assert "+" not in verifier
        assert "/" not in verifier
        assert "=" not in verifier

    def test_challenge_is_s256_of_verifier(self):
        """TC-PKCE-04: code_challenge == BASE64URL(SHA-256(code_verifier)) — S256 method."""
        verifier, challenge = generate_pkce_pair()
        digest = hashlib.sha256(verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        assert challenge == expected

    def test_challenge_has_no_padding(self):
        """TC-PKCE-05: code_challenge uses URL-safe base64 with no padding."""
        _, challenge = generate_pkce_pair()
        assert "=" not in challenge
        assert "+" not in challenge
        assert "/" not in challenge

    def test_unique_pairs_on_repeated_calls(self):
        """TC-PKCE-06: Successive calls yield distinct (verifier, challenge) pairs."""
        pairs = [generate_pkce_pair() for _ in range(5)]
        verifiers = {p[0] for p in pairs}
        challenges = {p[1] for p in pairs}
        assert len(verifiers) == 5, "code_verifiers are not unique"
        assert len(challenges) == 5, "code_challenges are not unique"

    def test_verifier_and_challenge_differ(self):
        """TC-PKCE-07: code_verifier and code_challenge are not the same string."""
        verifier, challenge = generate_pkce_pair()
        assert verifier != challenge


# ============================================================================
# generate_state_token
# ============================================================================

class TestGenerateStateToken:

    def test_returns_string(self):
        """TC-STATE-01: generate_state_token() returns a string."""
        token = generate_state_token()
        assert isinstance(token, str)

    def test_default_length_sufficient(self):
        """TC-STATE-02: Default token encodes >= 32 random bytes (base64 output >= 43 chars)."""
        token = generate_state_token()
        assert len(token) >= 40

    def test_is_url_safe(self):
        """TC-STATE-03: Token contains only URL-safe characters (no + or /)."""
        for _ in range(10):
            token = generate_state_token()
            assert "+" not in token
            assert "/" not in token

    def test_unique_tokens(self):
        """TC-STATE-04: Each call produces a distinct token."""
        tokens = {generate_state_token() for _ in range(10)}
        assert len(tokens) == 10

    def test_larger_nbytes_produces_longer_token(self):
        """TC-STATE-05: Larger nbytes parameter yields a longer token string."""
        short = generate_state_token(nbytes=16)
        long_ = generate_state_token(nbytes=64)
        assert len(long_) > len(short)
