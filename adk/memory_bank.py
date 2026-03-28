"""Vertex AI Memory Bank adapter for persistent agent memory."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryBankConfig:
    """Configuration for the Memory Bank adapter.

    Attributes:
        enabled: Whether the memory bank is active.
        store_type: Storage backend to use.  Supported values:
            - ``vertex``: Vertex AI Memory Bank (production).
            - ``in_memory``: Ephemeral in-process store (testing / local dev).
        ttl_seconds: Time-to-live for short-term memories in seconds
            (default 86400 = 24 h).  Long-term memories are not subject to TTL.
    """

    enabled: bool = False
    store_type: str = "vertex"
    ttl_seconds: int = 86400

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "enabled": self.enabled,
            "store_type": self.store_type,
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryBankConfig":
        """Deserialise from a plain dictionary."""
        return cls(
            enabled=bool(data.get("enabled", False)),
            store_type=str(data.get("store_type", "vertex")),
            ttl_seconds=int(data.get("ttl_seconds", 86400)),
        )


class MemoryBankAdapter:
    """Adapter for reading and writing agent memory across sessions.

    The adapter provides a unified interface over two storage backends:

    * ``vertex``: Vertex AI Memory Bank REST API (requires the
      ``google-cloud-aiplatform`` package and valid credentials).
    * ``in_memory``: A plain Python dict, suitable for testing and local
      development — all data is lost when the process exits.

    Short-term memories expire after ``config.ttl_seconds``.  Memories can
    be explicitly promoted to long-term storage via
    :meth:`promote_to_long_term`, which removes the TTL expiry.
    """

    def __init__(self, config: MemoryBankConfig | None = None) -> None:
        self.config = config or MemoryBankConfig()
        # In-memory store structure:
        # {session_id: {key: {"value": ..., "expires_at": float|None, "long_term": bool}}}
        self._store: dict[str, dict[str, dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def store(self, session_id: str, key: str, value: Any) -> None:
        """Persist a value in the memory bank.

        Args:
            session_id: Session or conversation identifier.
            key: Memory key (must be unique within the session).
            value: Serialisable value to store.
        """
        expires_at = time.time() + self.config.ttl_seconds if self.config.ttl_seconds > 0 else None

        if self.config.store_type == "vertex" and self.config.enabled:
            self._vertex_store(session_id, key, value, expires_at)
            return

        # In-memory fallback
        self._store.setdefault(session_id, {})[key] = {
            "value": value,
            "expires_at": expires_at,
            "long_term": False,
            "created_at": time.time(),
        }

    def retrieve(self, session_id: str, key: str) -> Any:
        """Retrieve a value from the memory bank.

        Returns ``None`` if the key does not exist or has expired.

        Args:
            session_id: Session or conversation identifier.
            key: Memory key.

        Returns:
            The stored value, or ``None`` if absent / expired.
        """
        if self.config.store_type == "vertex" and self.config.enabled:
            return self._vertex_retrieve(session_id, key)

        session_store = self._store.get(session_id, {})
        entry = session_store.get(key)
        if entry is None:
            return None

        # Check TTL expiry (long-term memories never expire)
        expires_at = entry.get("expires_at")
        if expires_at is not None and not entry.get("long_term", False):
            if time.time() > expires_at:
                del session_store[key]
                return None

        return entry.get("value")

    def list_memories(self, session_id: str) -> list[dict]:
        """List all non-expired memories for a session.

        Args:
            session_id: Session or conversation identifier.

        Returns:
            List of dicts with ``key``, ``long_term``, ``expires_at``, and
            ``created_at`` fields (values are intentionally omitted to keep
            the listing lightweight).
        """
        if self.config.store_type == "vertex" and self.config.enabled:
            return self._vertex_list(session_id)

        session_store = self._store.get(session_id, {})
        now = time.time()
        memories: list[dict] = []

        for key, entry in list(session_store.items()):
            expires_at = entry.get("expires_at")
            long_term = entry.get("long_term", False)

            # Prune expired non-long-term entries
            if expires_at is not None and not long_term and now > expires_at:
                del session_store[key]
                continue

            memories.append({
                "key": key,
                "long_term": long_term,
                "expires_at": expires_at,
                "created_at": entry.get("created_at"),
            })

        return memories

    def promote_to_long_term(self, session_id: str, key: str) -> None:
        """Promote a short-term memory to long-term (no expiry).

        Calling this method removes the TTL from the specified memory entry.
        If the entry does not exist, this is a no-op.

        Args:
            session_id: Session or conversation identifier.
            key: Memory key to promote.
        """
        if self.config.store_type == "vertex" and self.config.enabled:
            self._vertex_promote(session_id, key)
            return

        session_store = self._store.get(session_id, {})
        if key in session_store:
            session_store[key]["long_term"] = True
            session_store[key]["expires_at"] = None

    def delete(self, session_id: str, key: str) -> bool:
        """Delete a specific memory entry.

        Args:
            session_id: Session or conversation identifier.
            key: Memory key to delete.

        Returns:
            True if the entry was deleted, False if it did not exist.
        """
        session_store = self._store.get(session_id, {})
        if key in session_store:
            del session_store[key]
            return True
        return False

    def clear_session(self, session_id: str) -> int:
        """Delete all memories for a session.

        Args:
            session_id: Session or conversation identifier.

        Returns:
            Number of entries deleted.
        """
        session_store = self._store.pop(session_id, {})
        return len(session_store)

    # ------------------------------------------------------------------
    # Vertex AI backend (stubs)
    # ------------------------------------------------------------------

    def _vertex_store(
        self,
        session_id: str,
        key: str,
        value: Any,
        expires_at: float | None,
    ) -> None:
        """Store a value via the Vertex AI Memory Bank API (stub)."""
        try:
            from google.cloud import aiplatform  # type: ignore[import]

            # Vertex AI Memory Bank SDK call would go here.
            # For now fall back to in-memory implementation.
            _ = aiplatform  # suppress unused-import warning
        except ImportError:
            pass

        # In-memory fallback
        self._store.setdefault(session_id, {})[key] = {
            "value": value,
            "expires_at": expires_at,
            "long_term": False,
            "created_at": time.time(),
        }

    def _vertex_retrieve(self, session_id: str, key: str) -> Any:
        """Retrieve a value via the Vertex AI Memory Bank API (stub)."""
        try:
            from google.cloud import aiplatform  # type: ignore[import]
            _ = aiplatform
        except ImportError:
            pass
        # Fall back to in-memory store
        return self.retrieve.__wrapped__(self, session_id, key) if hasattr(self.retrieve, "__wrapped__") else (
            self._store.get(session_id, {}).get(key, {}).get("value")
        )

    def _vertex_list(self, session_id: str) -> list[dict]:
        """List memories via the Vertex AI Memory Bank API (stub)."""
        try:
            from google.cloud import aiplatform  # type: ignore[import]
            _ = aiplatform
        except ImportError:
            pass
        session_store = self._store.get(session_id, {})
        return [
            {
                "key": k,
                "long_term": v.get("long_term", False),
                "expires_at": v.get("expires_at"),
                "created_at": v.get("created_at"),
            }
            for k, v in session_store.items()
        ]

    def _vertex_promote(self, session_id: str, key: str) -> None:
        """Promote memory to long-term via the Vertex AI Memory Bank API (stub)."""
        try:
            from google.cloud import aiplatform  # type: ignore[import]
            _ = aiplatform
        except ImportError:
            pass
        session_store = self._store.get(session_id, {})
        if key in session_store:
            session_store[key]["long_term"] = True
            session_store[key]["expires_at"] = None
