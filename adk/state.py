"""ADK session state management with scoped prefixes.

Each state entry belongs to one of four scopes:
- USER   (prefix ``user:``)  — persisted per user across sessions
- APP    (prefix ``app:``)   — persisted per application
- TEMP   (prefix ``temp:``)  — ephemeral, discarded when session closes
- SESSION (no prefix)        — default scope, session-lived

The underlying storage is a flat dict.  Scoped helpers layer the prefix
convention on top so callers can work with bare keys while the ADK-format
state dict always sees the fully-qualified ``scope:key`` form.
"""
from __future__ import annotations

from enum import Enum
from typing import Any


class StateScope(str, Enum):
    """Scopes for ADK session state entries."""

    USER = "user"
    APP = "app"
    TEMP = "temp"
    SESSION = "session"


# Mapping from scope → ADK prefix string (SESSION has no prefix).
_SCOPE_PREFIX: dict[StateScope, str] = {
    StateScope.USER: "user:",
    StateScope.APP: "app:",
    StateScope.TEMP: "temp:",
    StateScope.SESSION: "",
}

# Reverse mapping: prefix → scope (used when importing ADK-format state).
_PREFIX_SCOPE: dict[str, StateScope] = {
    "user:": StateScope.USER,
    "app:": StateScope.APP,
    "temp:": StateScope.TEMP,
}


def _prefix_for(scope: StateScope) -> str:
    return _SCOPE_PREFIX[scope]


def _scope_for_key(adk_key: str) -> tuple[StateScope, str]:
    """Return (scope, bare_key) for an ADK-format ``prefix:key`` string."""
    for prefix, scope in _PREFIX_SCOPE.items():
        if adk_key.startswith(prefix):
            return scope, adk_key[len(prefix):]
    return StateScope.SESSION, adk_key


class AdkStateManager:
    """Manages ADK session state with scope-based organisation.

    All state is stored in a single flat dict keyed by ``scope:bare_key``.
    The ``SESSION`` scope uses an empty prefix so its keys are stored verbatim.

    Example::

        sm = AdkStateManager()
        sm.set("name", "Alice", StateScope.USER)
        sm.set("debug", True, StateScope.TEMP)
        adk_state = sm.to_adk_state()
        # {"user:name": "Alice", "temp:debug": True}
    """

    def __init__(self) -> None:
        # Flat storage: internal key = "<prefix><bare_key>"
        self._store: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Core get / set
    # ------------------------------------------------------------------

    def get(self, key: str, scope: StateScope = StateScope.SESSION) -> Any:
        """Return the value stored under *key* in *scope*, or ``None``.

        Args:
            key: Bare key (without scope prefix).
            scope: State scope.

        Returns:
            Stored value, or ``None`` if the key is absent.
        """
        internal_key = _prefix_for(scope) + key
        return self._store.get(internal_key)

    def set(
        self,
        key: str,
        value: Any,
        scope: StateScope = StateScope.SESSION,
    ) -> None:
        """Store *value* under *key* in *scope*.

        Args:
            key: Bare key (without scope prefix).
            value: Any JSON-serialisable value.
            scope: State scope (defaults to SESSION).
        """
        internal_key = _prefix_for(scope) + key
        self._store[internal_key] = value

    # ------------------------------------------------------------------
    # Bulk accessors
    # ------------------------------------------------------------------

    def get_scoped_state(self, scope: StateScope) -> dict:
        """Return all state entries belonging to *scope* as bare-key dict.

        Args:
            scope: The scope to filter by.

        Returns:
            Dict mapping bare keys to values for the given scope.
        """
        prefix = _prefix_for(scope)
        if prefix:
            result: dict[str, Any] = {}
            for k, v in self._store.items():
                if k.startswith(prefix):
                    result[k[len(prefix):]] = v
            return result
        # SESSION scope has no prefix — return all keys that don't match
        # any known prefix.
        known_prefixes = tuple(_PREFIX_SCOPE.keys())
        return {k: v for k, v in self._store.items() if not k.startswith(known_prefixes)}

    # ------------------------------------------------------------------
    # ADK-format import / export
    # ------------------------------------------------------------------

    def to_adk_state(self) -> dict:
        """Export state as an ADK-format flat dict (prefixed keys).

        Returns:
            A flat dict suitable for passing to the ADK SDK session state.
        """
        return dict(self._store)

    def from_adk_state(self, adk_state: dict) -> None:
        """Import state from an ADK-format flat dict.

        Existing entries in this manager are *replaced* by the imported
        values.  Entries not present in *adk_state* are preserved.

        Args:
            adk_state: Flat dict with prefixed keys as produced by
                ``to_adk_state`` or returned by the ADK SDK.
        """
        for k, v in adk_state.items():
            self._store[k] = v

    # ------------------------------------------------------------------
    # AutoAgent integration
    # ------------------------------------------------------------------

    def to_environment_snapshot(self) -> dict:
        """Convert state to an AutoAgent ``EnvironmentSnapshot``-compatible dict.

        The snapshot groups state by scope so AutoAgent can display / diff it
        clearly in the evaluation UI.

        Returns:
            Dict with keys ``user``, ``app``, ``temp``, ``session`` each
            containing a bare-key dict.
        """
        return {
            "user": self.get_scoped_state(StateScope.USER),
            "app": self.get_scoped_state(StateScope.APP),
            "temp": self.get_scoped_state(StateScope.TEMP),
            "session": self.get_scoped_state(StateScope.SESSION),
        }

    # ------------------------------------------------------------------
    # Diff
    # ------------------------------------------------------------------

    def diff(self, other: "AdkStateManager") -> dict:
        """Compute the delta between this manager and *other*.

        Returns a dict describing additions, removals, and changed values
        relative to *self* (i.e. what would need to be applied to *self* to
        produce *other*).

        Args:
            other: The state manager to compare against.

        Returns:
            Dict with keys:
            - ``added``: keys present in *other* but not in *self*
            - ``removed``: keys present in *self* but not in *other*
            - ``changed``: keys present in both but with different values
        """
        self_keys = set(self._store.keys())
        other_keys = set(other._store.keys())

        added = {k: other._store[k] for k in other_keys - self_keys}
        removed = {k: self._store[k] for k in self_keys - other_keys}
        changed = {
            k: {"from": self._store[k], "to": other._store[k]}
            for k in self_keys & other_keys
            if self._store[k] != other._store[k]
        }

        return {"added": added, "removed": removed, "changed": changed}
