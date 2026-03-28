"""ADK session lifecycle management.

Sessions are lightweight containers that associate a unique ID with an
``AdkStateManager`` instance and a status flag.  The ``AdkSessionManager``
is an in-process registry; for production use you would replace the backing
store with a database or the ADK SDK session service.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .state import AdkStateManager, StateScope


class SessionStatus(str, Enum):
    """Lifecycle status of an ADK session."""

    CREATED = "created"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AdkSession:
    """An ADK session container.

    Attributes:
        session_id: Unique session identifier (UUID4 by default).
        status: Current lifecycle status.
        state: The ``AdkStateManager`` holding all scoped state for this
            session.
        created_at: ISO-8601 UTC timestamp when the session was created.
        updated_at: ISO-8601 UTC timestamp of the last state change.
        metadata: Arbitrary caller-supplied metadata dict.
    """

    session_id: str
    status: SessionStatus
    state: AdkStateManager
    created_at: str
    updated_at: str
    metadata: dict = field(default_factory=dict)


class AdkSessionManager:
    """In-memory registry for ``AdkSession`` objects.

    All operations are synchronous and thread-unsafe (suitable for single-
    threaded runtimes / tests).  Extend or replace for production deployments
    that require persistence or concurrent access.

    Example::

        mgr = AdkSessionManager()
        session = mgr.create_session(metadata={"user_id": "u1"})
        mgr.update_state(session.session_id, "name", "Alice", StateScope.USER)
        mgr.close_session(session.session_id)
    """

    def __init__(self) -> None:
        self._sessions: dict[str, AdkSession] = {}

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, metadata: dict | None = None) -> AdkSession:
        """Create and register a new session.

        Args:
            metadata: Optional caller-supplied metadata attached to the
                session.

        Returns:
            The newly created ``AdkSession`` with ``CREATED`` status.
        """
        now = _utcnow()
        session = AdkSession(
            session_id=str(uuid.uuid4()),
            status=SessionStatus.CREATED,
            state=AdkStateManager(),
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> AdkSession | None:
        """Return the session with *session_id*, or ``None`` if not found.

        Args:
            session_id: The session identifier to look up.

        Returns:
            The ``AdkSession``, or ``None``.
        """
        return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> None:
        """Mark a session as closed.

        Closed sessions remain in the registry (for audit / replay) but
        their status is set to ``CLOSED`` and no further state updates
        should be made.

        Args:
            session_id: The session to close.

        Raises:
            KeyError: If *session_id* does not exist.
        """
        session = self._sessions[session_id]
        session.status = SessionStatus.CLOSED
        session.updated_at = _utcnow()

    def list_sessions(
        self,
        status: SessionStatus | None = None,
    ) -> list[AdkSession]:
        """Return all sessions, optionally filtered by *status*.

        Args:
            status: When provided, only sessions with this status are
                returned.  When ``None``, all sessions are returned.

        Returns:
            List of ``AdkSession`` objects in creation order.
        """
        sessions = list(self._sessions.values())
        if status is not None:
            sessions = [s for s in sessions if s.status == status]
        return sessions

    # ------------------------------------------------------------------
    # State updates
    # ------------------------------------------------------------------

    def update_state(
        self,
        session_id: str,
        key: str,
        value: Any,
        scope: StateScope = StateScope.SESSION,
    ) -> None:
        """Update a single state entry for the given session.

        Automatically transitions the session status from ``CREATED`` to
        ``ACTIVE`` on first state write.

        Args:
            session_id: Target session identifier.
            key: Bare state key (without scope prefix).
            value: Value to store.
            scope: State scope (defaults to ``SESSION``).

        Raises:
            KeyError: If *session_id* does not exist.
            RuntimeError: If the session is ``CLOSED``.
        """
        session = self._sessions[session_id]
        if session.status == SessionStatus.CLOSED:
            raise RuntimeError(
                f"Cannot update state for closed session {session_id!r}"
            )
        session.state.set(key, value, scope)
        if session.status == SessionStatus.CREATED:
            session.status = SessionStatus.ACTIVE
        session.updated_at = _utcnow()
