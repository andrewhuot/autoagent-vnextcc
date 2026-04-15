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
    provider: str | None = None
    """Active provider name (``openai`` / ``anthropic`` / ``google``). When
    set, the renderer folds it into the model segment as ``model · provider``
    so the operator can see at a glance which API will be called."""
    provider_key_present: bool = True
    """``False`` when the active provider's API key env var is unset. The
    renderer switches the model segment to warn-color and appends ``[no key]``
    so silent-fallback bugs are obvious before a command is even issued."""
    pending_reviews: int = 0
    best_score: str | None = None
    agentlab_version: str = ""
    session_title: str | None = None
    tokens_used: int | None = None
    """Running total of context tokens consumed this session. ``None`` when
    the caller hasn't wired token accounting yet — the renderer hides the
    field rather than guessing a misleading ``0``."""
    context_limit: int | None = None
    """Optional explicit window. When omitted but ``model`` is set, the
    renderer looks the limit up via :mod:`cli.llm.capabilities`."""
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


def _describe_provider_safely(workspace: Any | None) -> Any | None:
    """Look up the active provider without ever crashing the status bar.

    Status-line failures must be invisible — an unreadable runtime config or a
    missing optional dependency can't take down the REPL prompt. We return
    ``None`` on any error; the renderer treats that as "no provider info".
    """
    try:
        from optimizer.providers import describe_default_provider
    except Exception:
        return None
    runtime_config_path = getattr(workspace, "runtime_config_path", None) if workspace else None
    try:
        return describe_default_provider(runtime_config_path=runtime_config_path)
    except Exception:
        return None


def snapshot_from_workspace(
    workspace: Any | None,
    *,
    session: Session | None = None,
    model_override: str | None = None,
    provider_info: Any | None = None,
) -> StatusSnapshot:
    """Build a :class:`StatusSnapshot` from current workspace/session state.

    ``model_override`` wins over whatever the active config reports — used by
    ``/model`` (T14) to reflect a session-local model switch that hasn't been
    written back to the config yet.

    ``provider_info`` lets tests inject a pre-built :class:`ProviderInfo` so
    they don't touch environment variables or the runtime config.  When omitted
    the status bar calls :func:`optimizer.providers.describe_default_provider`
    via :func:`_describe_provider_safely`.
    """
    version = get_agentlab_version()
    info = provider_info if provider_info is not None else _describe_provider_safely(workspace)

    provider_name = getattr(info, "name", None) if info is not None else None
    provider_key_present = bool(getattr(info, "key_present", True)) if info is not None else True

    if workspace is None:
        return StatusSnapshot(
            agentlab_version=version,
            session_title=(session.title if session else None),
            model=model_override,
            provider=provider_name,
            provider_key_present=provider_key_present,
        )

    active = _resolve_active_config(workspace)
    config_version = getattr(active, "version", None) if active else None
    model = model_override or _model_from_config(active)

    return StatusSnapshot(
        workspace_label=getattr(workspace, "workspace_label", None),
        config_version=config_version,
        model=model,
        provider=provider_name,
        provider_key_present=provider_key_present,
        pending_reviews=_read_pending_reviews(workspace),
        best_score=_read_best_score(workspace),
        agentlab_version=version,
        session_title=(session.title if session else None),
    )


def _resolve_limit_for_snapshot(snapshot: "StatusSnapshot") -> int | None:
    """Prefer an explicit ``context_limit`` on the snapshot; otherwise fall
    back to the capabilities registry keyed by ``model``. Lazy import keeps
    this renderer usable in environments that never look the limit up."""
    if snapshot.context_limit:
        return snapshot.context_limit
    if not snapshot.model:
        return None
    from cli.llm.capabilities import get_capability

    cap = get_capability(snapshot.model)
    return cap.context_window if cap is not None else None


def render_snapshot(snapshot: StatusSnapshot, *, color: bool = True) -> str:
    """Render a snapshot to a single status line.

    ``color=False`` emits a plain string (no ANSI escapes) — used by tests
    and by contexts that want to log the bar without terminal markup.
    """

    from cli.workbench_app import theme  # local import — avoids cycle w/ app.py

    parts: list[str] = []
    if snapshot.workspace_label:
        parts.append(theme.workspace(snapshot.workspace_label, color=color))
    else:
        parts.append(theme.warning("no workspace", color=color))

    if snapshot.config_version is not None:
        parts.append(f"v{snapshot.config_version:03d}")

    if snapshot.model or snapshot.provider:
        segment_parts: list[str] = []
        if snapshot.model:
            segment_parts.append(snapshot.model)
        if snapshot.provider:
            segment_parts.append(snapshot.provider)
        if not snapshot.provider_key_present:
            segment_parts.append("[no key]")
        segment = " · ".join(segment_parts)
        if not snapshot.provider_key_present:
            parts.append(theme.warning(segment, color=color))
        else:
            parts.append(segment)

    if snapshot.tokens_used is not None:
        limit = _resolve_limit_for_snapshot(snapshot)
        if limit:
            parts.append(f"{snapshot.tokens_used:,}/{limit:,} tok")
        else:
            parts.append(f"{snapshot.tokens_used:,} tok")

    if snapshot.pending_reviews > 0:
        label = "review" if snapshot.pending_reviews == 1 else "reviews"
        parts.append(
            theme.warning(f"{snapshot.pending_reviews} {label}", color=color)
        )

    if snapshot.best_score:
        parts.append(f"score:{snapshot.best_score}")

    for label, value in snapshot.extras:
        parts.append(f"{label}:{value}")

    if snapshot.agentlab_version:
        parts.append(theme.meta(f"agentlab {snapshot.agentlab_version}", color=color))

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
        provider_info: Any | None = None,
    ) -> StatusSnapshot:
        """Rebuild the snapshot from disk/DB state and return the new value."""
        self._snapshot = snapshot_from_workspace(
            workspace,
            session=session,
            model_override=model_override,
            provider_info=provider_info,
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
