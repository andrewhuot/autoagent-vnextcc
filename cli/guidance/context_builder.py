"""Adapters that populate a :class:`GuidanceContext` from real runtime state.

These helpers live outside :mod:`cli.guidance.engine` on purpose — the engine
stays pure (duck-typed, no I/O) while this module does the actual workspace
reads, SQLite queries, and provider lookups. Import shapes:

    from cli.guidance.context_builder import build_context_from_workspace

That import should never bring optimizer/evaluator code in if the caller
isn't using it. All the optional integrations are guarded behind local
imports and except-pass so a missing dependency can't break status-bar
rendering.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from cli.guidance.types import GuidanceContext


def _read_best_score(workspace: Any) -> str | None:
    path = getattr(workspace, "best_score_file", None)
    if path is None or not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _read_pending_reviews(workspace: Any) -> int:
    db = getattr(workspace, "change_cards_db", None)
    if db is None or not db.exists():
        return 0
    try:
        conn = sqlite3.connect(str(db))
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
    try:
        return int(row[0]) if row else 0
    except (TypeError, ValueError):
        return 0


def _describe_provider(workspace: Any) -> tuple[str | None, bool, bool, str | None]:
    """Return ``(name, key_present, mock_mode, mock_reason)`` defensively.

    Anything goes wrong — missing module, unreadable runtime config, raising
    describe fn — we return ``(None, True, False, None)`` so the guidance
    engine simply skips provider-related rules instead of crashing.
    """
    try:
        from optimizer.providers import describe_default_provider  # type: ignore
    except Exception:
        return None, True, False, None
    runtime_config_path = getattr(workspace, "runtime_config_path", None) if workspace else None
    try:
        info = describe_default_provider(runtime_config_path=runtime_config_path)
    except Exception:
        return None, True, False, None
    name = getattr(info, "name", None)
    key_present = bool(getattr(info, "key_present", True))
    # ``ProviderInfo`` today doesn't carry a mock flag — mock detection lives
    # on the router. We treat ``provider.name == 'mock'`` as mock_mode so the
    # guidance module doesn't need to import the router.
    mock_mode = (name or "").strip().lower() == "mock"
    return name, key_present, mock_mode, None


def _most_recent_mtime(path: Path) -> float | None:
    """Return ``path.stat().st_mtime`` or ``None`` on any error / missing file."""
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _last_eval_at(workspace: Any) -> float | None:
    """Best-effort timestamp of the most recent eval.

    Prefers the ``eval_history.db`` mtime; falls back to the best-score file
    which is touched on every eval completion. Either is a good proxy; we
    don't need exact event timestamps for a cooldown-sized nudge.
    """
    for attr in ("eval_history_db", "best_score_file"):
        p = getattr(workspace, attr, None)
        if isinstance(p, Path):
            mtime = _most_recent_mtime(p)
            if mtime is not None:
                return mtime
    return None


def _last_optimize_at(workspace: Any) -> float | None:
    """Best-effort timestamp of the most recent optimize run."""
    for attr in ("memory_db", "change_cards_db"):
        p = getattr(workspace, attr, None)
        if isinstance(p, Path):
            mtime = _most_recent_mtime(p)
            if mtime is not None:
                return mtime
    return None


def _latest_session(session_store: Any) -> tuple[str | None, int]:
    """Return ``(latest_session_id, session_count)`` for the store or defaults."""
    if session_store is None:
        return None, 0
    try:
        sessions = session_store.list_sessions(limit=1)
    except Exception:
        return None, 0
    count = 0
    try:
        count = int(getattr(session_store, "count", lambda: len(sessions))())
    except Exception:
        count = len(sessions) if sessions else 0
    if not sessions:
        return None, count
    first = sessions[0]
    return getattr(first, "session_id", None), count


def build_context_from_workspace(
    workspace: Any | None,
    *,
    active_session_id: str | None = None,
    session_store: Any | None = None,
    deployment_blocked_reason: str | None = None,
    doctor_failing: bool = False,
    doctor_summary: str | None = None,
    extras: dict[str, Any] | None = None,
    now: float | None = None,
) -> GuidanceContext:
    """Gather every field a built-in rule might read.

    This is the canonical "I have a workspace, give me a context" helper.
    Web API and CLI status both call it; per-UI overrides are expressed as
    keyword args rather than post-hoc mutation so the shape is visible at
    the call site.
    """
    ctx_now = now if now is not None else time.time()

    if workspace is None:
        return GuidanceContext(
            workspace=None,
            workspace_valid=False,
            doctor_failing=doctor_failing,
            doctor_summary=doctor_summary,
            now=ctx_now,
            extras=dict(extras or {}),
        )

    provider_name, key_present, mock_mode, mock_reason = _describe_provider(workspace)
    latest_session_id, session_count = _latest_session(session_store)

    return GuidanceContext(
        workspace=workspace,
        workspace_path=str(getattr(workspace, "root", "") or "") or None,
        workspace_valid=True,
        provider_name=provider_name,
        provider_key_present=key_present,
        mock_mode=mock_mode,
        mock_reason=mock_reason,
        best_score=_read_best_score(workspace),
        last_eval_at=_last_eval_at(workspace),
        last_optimize_at=_last_optimize_at(workspace),
        pending_review_cards=_read_pending_reviews(workspace),
        deployment_blocked_reason=deployment_blocked_reason,
        active_session_id=active_session_id,
        latest_session_id=latest_session_id,
        session_count=session_count,
        doctor_failing=doctor_failing,
        doctor_summary=doctor_summary,
        now=ctx_now,
        extras=dict(extras or {}),
    )


def history_path_for_workspace(workspace: Any | None) -> Path | None:
    """Resolve the guidance history JSON path for a workspace.

    Lives under ``.agentlab/guidance_history.json`` so it rolls with the
    workspace (backed up, shared via ``agentlab init``). Returns ``None``
    when no workspace is bound — callers fall back to an in-memory history.
    """
    if workspace is None:
        return None
    agentlab_dir = getattr(workspace, "agentlab_dir", None)
    if not isinstance(agentlab_dir, Path):
        return None
    return agentlab_dir / "guidance_history.json"


__all__ = ["build_context_from_workspace", "history_path_for_workspace"]
