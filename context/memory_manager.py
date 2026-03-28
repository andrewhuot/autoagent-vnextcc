"""Memory manager — scoped, promotion-aware in-memory store with TTL support."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return time.monotonic()


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MemoryEntry:
    key: str
    value: Any
    scope: str
    created_at: str
    last_accessed: str
    access_count: int
    ttl_seconds: Optional[int]

    # Internal monotonic timestamps for TTL checks (not serialised)
    _created_ts: float = field(default_factory=_now_ts, repr=False, compare=False)
    _accessed_ts: float = field(default_factory=_now_ts, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "scope": self.scope,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        return cls(
            key=d["key"],
            value=d["value"],
            scope=d.get("scope", "temp"),
            created_at=d.get("created_at", _now_iso()),
            last_accessed=d.get("last_accessed", _now_iso()),
            access_count=d.get("access_count", 0),
            ttl_seconds=d.get("ttl_seconds"),
        )

    def is_expired(self) -> bool:
        """Return True if the TTL has elapsed since creation."""
        if self.ttl_seconds is None:
            return False
        elapsed = _now_ts() - self._created_ts
        return elapsed > self.ttl_seconds

    def touch(self) -> None:
        """Update last-access bookkeeping."""
        self.last_accessed = _now_iso()
        self._accessed_ts = _now_ts()
        self.access_count += 1


@dataclass
class MemoryPromotionRule:
    from_scope: str
    to_scope: str
    condition: str
    min_access_count: int = 3

    def to_dict(self) -> dict:
        return {
            "from_scope": self.from_scope,
            "to_scope": self.to_scope,
            "condition": self.condition,
            "min_access_count": self.min_access_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryPromotionRule":
        return cls(
            from_scope=d["from_scope"],
            to_scope=d["to_scope"],
            condition=d.get("condition", "access_count"),
            min_access_count=d.get("min_access_count", 3),
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class MemoryManager:
    """Scoped in-memory store with TTL, auto-promotion, and stale-expiry."""

    def __init__(
        self, rules: Optional[list[MemoryPromotionRule]] = None
    ) -> None:
        # (scope, key) -> MemoryEntry
        self._store: dict[tuple[str, str], MemoryEntry] = {}
        self._rules: list[MemoryPromotionRule] = rules or []

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def store(
        self,
        key: str,
        value: Any,
        scope: str = "temp",
        ttl_seconds: Optional[int] = None,
    ) -> MemoryEntry:
        """Store a value under (scope, key) and return the entry."""
        now = _now_iso()
        entry = MemoryEntry(
            key=key,
            value=value,
            scope=scope,
            created_at=now,
            last_accessed=now,
            access_count=0,
            ttl_seconds=ttl_seconds,
        )
        self._store[(scope, key)] = entry
        return entry

    def retrieve(self, key: str, scope: Optional[str] = None) -> Any:
        """Return the value for key.

        If scope is None, searches all scopes in order: session, persistent,
        temp (most-to-least durable).  Returns None when not found or expired.
        """
        search_scopes = (
            [scope] if scope is not None else ["session", "persistent", "temp"]
        )
        for sc in search_scopes:
            entry = self._store.get((sc, key))
            if entry is not None:
                if entry.is_expired():
                    del self._store[(sc, key)]
                    return None
                entry.touch()
                return entry.value
        return None

    def promote(self, key: str, from_scope: str, to_scope: str) -> MemoryEntry:
        """Move an entry from from_scope to to_scope.

        Raises KeyError if the entry does not exist in from_scope.
        """
        entry = self._store.get((from_scope, key))
        if entry is None:
            raise KeyError(f"No entry '{key}' in scope '{from_scope}'")
        if entry.is_expired():
            del self._store[(from_scope, key)]
            raise KeyError(f"Entry '{key}' in scope '{from_scope}' has expired")

        del self._store[(from_scope, key)]
        entry.scope = to_scope
        self._store[(to_scope, key)] = entry
        return entry

    def auto_promote(self) -> list[MemoryEntry]:
        """Apply all promotion rules and return entries that were promoted."""
        promoted: list[MemoryEntry] = []
        for rule in self._rules:
            candidates = [
                e
                for (sc, _), e in list(self._store.items())
                if sc == rule.from_scope and not e.is_expired()
                and e.access_count >= rule.min_access_count
            ]
            for entry in candidates:
                try:
                    updated = self.promote(entry.key, rule.from_scope, rule.to_scope)
                    promoted.append(updated)
                except KeyError:
                    pass
        return promoted

    def list_entries(self, scope: Optional[str] = None) -> list[MemoryEntry]:
        """Return all non-expired entries, optionally filtered by scope."""
        result: list[MemoryEntry] = []
        for (sc, _), entry in list(self._store.items()):
            if entry.is_expired():
                del self._store[(sc, entry.key)]
                continue
            if scope is None or sc == scope:
                result.append(entry)
        return result

    def expire_stale(self, max_age_seconds: int) -> int:
        """Remove entries older than max_age_seconds.  Returns count removed."""
        now_ts = _now_ts()
        to_remove = [
            (sc, key)
            for (sc, key), entry in self._store.items()
            if (now_ts - entry._created_ts) > max_age_seconds
        ]
        for key_tuple in to_remove:
            del self._store[key_tuple]
        return len(to_remove)
