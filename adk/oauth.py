"""Agent OAuth Manager — configure OAuth flows and manage agent tokens."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future_iso(seconds: int = 3600) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class OAuthConfig:
    """OAuth 2.0 client configuration for an agent."""

    client_id: str
    client_secret: str
    token_url: str
    scopes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "client_secret": "***",  # Never serialise secrets
            "token_url": self.token_url,
            "scopes": self.scopes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OAuthConfig":
        return cls(
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            token_url=data["token_url"],
            scopes=data.get("scopes", []),
        )


# ---------------------------------------------------------------------------
# Token store entry
# ---------------------------------------------------------------------------

@dataclass
class _TokenEntry:
    access_token: str
    expires_at: str
    refresh_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class AgentOAuthManager:
    """Issue and refresh OAuth access tokens for agents (in-memory token store)."""

    def __init__(self) -> None:
        self._configs: dict[str, OAuthConfig] = {}
        self._tokens: dict[str, _TokenEntry] = {}  # keyed by agent_id

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(self, config: OAuthConfig) -> None:
        """Register an OAuth config (keyed by client_id)."""
        self._configs[config.client_id] = config

    # ------------------------------------------------------------------
    # Token operations
    # ------------------------------------------------------------------

    def get_token(self, agent_id: str) -> Optional[str]:
        """Return a valid access token for *agent_id*, or None if absent/expired.

        In production this would perform an actual OAuth client-credentials
        grant against ``config.token_url``.  Here we issue a signed stub token
        so that callers can exercise the interface without network access.
        """
        entry = self._tokens.get(agent_id)
        if entry is None:
            # Auto-issue a stub token using the first registered config
            if not self._configs:
                return None
            config = next(iter(self._configs.values()))
            token = self._issue_stub_token(agent_id, config)
            return token

        # Check expiry
        now = datetime.now(timezone.utc).isoformat()
        if entry.expires_at < now:
            return None
        return entry.access_token

    def refresh_token(self, agent_id: str) -> Optional[str]:
        """Force-refresh the token for *agent_id* and return the new token."""
        if not self._configs:
            return None
        config = next(iter(self._configs.values()))
        return self._issue_stub_token(agent_id, config)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _issue_stub_token(self, agent_id: str, config: OAuthConfig) -> str:
        """Mint a stub access token and store it."""
        token_value = secrets.token_urlsafe(32)
        entry = _TokenEntry(
            access_token=token_value,
            expires_at=_future_iso(seconds=3600),
            refresh_token=secrets.token_urlsafe(24),
        )
        self._tokens[agent_id] = entry
        return token_value
