"""Reactive status line for the workbench app.

T06 replaces the stub :func:`cli.workbench_app.app.build_status_line` with a
stateful ``StatusBar`` that the enclosing loop can refresh from the workspace
or update directly from events (model changes, score updates, review counts).

The bar renders a one-line summary of:

- workspace label (cyan, bold)
- active config version (``v007``)
- active model (from the resolved config, or an explicit override)
- pending review count (yellow, only when > 0)
- best score (when recorded on disk)
- agentlab version (dim suffix)

Later tasks (T07/T08) will wire event observers that call
:meth:`StatusBar.update` as ``task.progress`` / ``review.added`` events arrive,
so no long-running work is needed here — just a cheap snapshot + render.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, replace
from typing import Any, Callable

import click

from cli.branding import get_agentlab_version
from cli.sessions import Session


RenderFn = Callable[["StatusSnapshot"], str]
"""Callable that converts a snapshot to a one-line string."""


@dataclass(frozen=True)
class StatusSnapshot:
    """Immutable view of the state displayed in the status bar.

    Kept explicit (not a ``dict[str, Any]``) so the type system catches typos
    and downstream consumers — the banner renderer, the transcript header,
    and future tests — share one shape.
    """

    workspace_label: str | None = None
    config_version: int | None = None
    model: str | None = None
    pending_reviews: int = 0
    best_score: str | None = None
    agentlab_version: str = ""
    session_title: str | None = None
    extras: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    """Ad-hoc ``(label, value)`` pairs appended after the standard fields."""


def _read_pending_reviews(workspace: Any) -> int:
    """Return the pending review count for ``workspace`` or ``0`` on failure.

    This touches the change-cards sqlite DB; the original REPL status bar
    silently swallowed exceptions because the DB can be missing, corrupted,
    or locked by a concurrent writer. We preserve that behaviour — the
    status line must never crash the loop.
    """
    cards_db = getattr(workspace, "change_cards_db", None)
    if cards_db is None or not cards_db.exists():
        return 0
    try:
        conn = sqlite3.connect(str(cards_db))
    except sqlite3.Error:
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM change_cards WHERE status = 'pending'"
        ).fetchone()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    if not row:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def _read_best_score(workspace: Any) -> str | None:
    score_file = getattr(workspace, "best_score_file", None)
    if score_file is None or not score_file.exists():
        return None
    try:
        text = score_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _resolve_active_config(workspace: Any) -> Any | None:
    """Call ``workspace.resolve_active_config()`` tolerating missing attrs or raises."""
    resolver = getattr(workspace, "resolve_active_config", None)
    if resolver is None:
        return None
    try:
        return resolver()
    except Exception:
        return None


def _model_from_config(active: Any | None) -> str | None:
    if active is None:
        return None
    config = getattr(active, "config", None)
    if not isinstance(config, dict):
        return None
    model = config.get("model")
    return str(model) if model else None


def snapshot_from_workspace(
    workspace: Any | None,
    *,
    session: Session | None = None,
    model_override: str | None = None,
) -> StatusSnapshot:
    """Build a :class:`StatusSnapshot` from current workspace/session state.

    ``model_override`` wins over whatever the active config reports — used by
    ``/model`` (T14) to reflect a session-local model switch that hasn't been
    written back to the config yet.
    """
    version = get_agentlab_version()
    if workspace is None:
        return StatusSnapshot(
            agentlab_version=version,
            session_title=(session.title if session else None),
            model=model_override,
        )

    active = _resolve_active_config(workspace)
    config_version = getattr(active, "version", None) if active else None
    model = model_override or _model_from_config(active)

    return StatusSnapshot(
        workspace_label=getattr(workspace, "workspace_label", None),
        config_version=config_version,
        model=model,
        pending_reviews=_read_pending_reviews(workspace),
        best_score=_read_best_score(workspace),
        agentlab_version=version,
        session_title=(session.title if session else None),
    )


def render_snapshot(snapshot: StatusSnapshot, *, color: bool = True) -> str:
    """Render a snapshot to a single status line.

    ``color=False`` emits a plain string (no ANSI escapes) — used by tests
    and by contexts that want to log the bar without terminal markup.
    """

    def style(text: str, **kwargs: Any) -> str:
        return click.style(text, **kwargs) if color else text

    parts: list[str] = []
    if snapshot.workspace_label:
        parts.append(style(snapshot.workspace_label, fg="cyan", bold=True))
    else:
        parts.append(style("no workspace", fg="yellow"))

    if snapshot.config_version is not None:
        parts.append(f"v{snapshot.config_version:03d}")

    if snapshot.model:
        parts.append(snapshot.model)

    if snapshot.pending_reviews > 0:
        label = "review" if snapshot.pending_reviews == 1 else "reviews"
        parts.append(
            style(f"{snapshot.pending_reviews} {label}", fg="yellow")
        )

    if snapshot.best_score:
        parts.append(f"score:{snapshot.best_score}")

    for label, value in snapshot.extras:
        parts.append(f"{label}:{value}")

    if snapshot.agentlab_version:
        parts.append(style(f"agentlab {snapshot.agentlab_version}", dim=True))

    return " | ".join(parts)


class StatusBar:
    """Stateful holder for the reactive status line.

    The workbench loop owns a single instance and either:

    - calls :meth:`refresh_from_workspace` after any workspace-mutating
      command (config switch, new review card, score update), or
    - calls :meth:`update` with explicit fields when an event stream has
      already told us what changed (avoids re-querying the DB).
    """

    def __init__(
        self,
        snapshot: StatusSnapshot | None = None,
        *,
        render_fn: RenderFn | None = None,
    ) -> None:
        self._snapshot = snapshot or StatusSnapshot(
            agentlab_version=get_agentlab_version()
        )
        self._render_fn = render_fn or (lambda s: render_snapshot(s, color=True))

    @property
    def snapshot(self) -> StatusSnapshot:
        return self._snapshot

    def refresh_from_workspace(
        self,
        workspace: Any | None,
        *,
        session: Session | None = None,
        model_override: str | None = None,
    ) -> StatusSnapshot:
        """Rebuild the snapshot from disk/DB state and return the new value."""
        self._snapshot = snapshot_from_workspace(
            workspace, session=session, model_override=model_override
        )
        return self._snapshot

    def update(self, **changes: Any) -> StatusSnapshot:
        """Patch specific snapshot fields without touching the rest.

        Raises :class:`TypeError` for unknown fields so typos surface at the
        call site instead of silently dropping updates. ``extras`` entries
        replace (not merge) the existing tuple — callers compose the full
        list themselves.
        """
        allowed = {f.name for f in StatusSnapshot.__dataclass_fields__.values()}
        unknown = set(changes) - allowed
        if unknown:
            raise TypeError(
                f"StatusBar.update got unknown fields: {sorted(unknown)}"
            )
        self._snapshot = replace(self._snapshot, **changes)
        return self._snapshot

    def render(self, *, color: bool = True) -> str:
        """Render the current snapshot. ``color=False`` strips ANSI escapes."""
        if color:
            return self._render_fn(self._snapshot)
        return render_snapshot(self._snapshot, color=False)


__all__ = [
    "RenderFn",
    "StatusBar",
    "StatusSnapshot",
    "render_snapshot",
    "snapshot_from_workspace",
]
