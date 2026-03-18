"""Abstract OIDC provider base class and shared data classes."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class OIDCUserInfo:
    """Normalised user information extracted from an id_token or userinfo response."""
    sub: str
    email: str
    display_name: str
    avatar_url: Optional[str]


class OIDCProvider(ABC):
    """Abstract base for all OIDC identity providers."""

    @property
    @abstractmethod
    def provider_key(self) -> str:
        """Stable snake_case key, e.g. 'azure_ad' or 'google'."""
        ...

    @property
    @abstractmethod
    def display_label(self) -> str:
        """Human-readable name shown on the login button."""
        ...

    @abstractmethod
    def build_authorisation_url(
        self,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        """Return the full IdP authorisation URL including all PKCE/OIDC params."""
        ...

    @abstractmethod
    async def exchange_code(
        self,
        code: str,
        code_verifier: str,
    ) -> dict:
        """Exchange an authorisation code for tokens; returns raw token response dict."""
        ...

    @abstractmethod
    async def validate_id_token(
        self,
        id_token: str,
        nonce: str,
    ) -> OIDCUserInfo:
        """Validate the id_token and return normalised user info.

        Raises jwt.InvalidTokenError (or subclass) on any validation failure.
        """
        ...
