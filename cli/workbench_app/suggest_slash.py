"""``/suggest`` — show, dismiss, or reset proactive guidance suggestions.

Thin handler over :mod:`cli.guidance`. Registered from
:func:`cli.workbench_app.slash.build_builtin_registry` so the existing
slash dispatch picks it up without further wiring.
"""

from __future__ import annotations

import time
from typing import Any

from cli.guidance import (
    build_context_from_workspace,
    history_path_for_workspace,
    select_suggestions,
)
from cli.guidance.engine import SuggestionHistory, evaluate_rules
from cli.guidance.render import render_suggestions_detail
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done


def _load_history(workspace: Any) -> SuggestionHistory:
    return SuggestionHistory.load(history_path_for_workspace(workspace))


def _handle_suggest(ctx, *args: str) -> OnDoneResult:
    """Dispatch: no args → show list, ``dismiss <id>`` → suppress, ``reset`` → clear."""
    workspace = getattr(ctx, "workspace", None)
    session = getattr(ctx, "session", None)
    session_store = getattr(ctx, "session_store", None)
    active_id = session.session_id if session else None

    history = _load_history(workspace)

    if args and args[0] == "reset":
        history.shown_at.clear()
        history.dismissed_at.clear()
        history.accepted_at.clear()
        history.save()
        return on_done("  Guidance history cleared.", display="system")

    if args and args[0] == "dismiss":
        if len(args) < 2:
            return on_done(
                "  Usage: /suggest dismiss <suggestion-id>", display="system"
            )
        suggestion_id = args[1]
        history.mark_dismissed(suggestion_id, time.time())
        history.save()
        return on_done(
            f"  Dismissed suggestion {suggestion_id!r}. It won't show again "
            "until its cooldown lapses.",
            display="system",
        )

    guidance_ctx = build_context_from_workspace(
        workspace,
        active_session_id=active_id,
        session_store=session_store,
    )
    # Use ``evaluate_rules`` (not ``select_suggestions``) so the detail view
    # shows every currently-applicable suggestion regardless of cooldown — the
    # operator explicitly typed ``/suggest`` to see the full list.
    suggestions = evaluate_rules(guidance_ctx)
    return on_done(render_suggestions_detail(suggestions), display="user")


def build_suggest_command() -> LocalCommand:
    return LocalCommand(
        name="suggest",
        description="Show proactive guidance suggestions",
        handler=_handle_suggest,
        source="builtin",
        argument_hint="[dismiss <id> | reset]",
        when_to_use=(
            "Use to see current next-step recommendations, or to quiet one "
            "you don't want to see again."
        ),
    )


def select_active_suggestions(
    workspace: Any | None,
    *,
    session: Any | None = None,
    session_store: Any | None = None,
    limit: int = 2,
) -> list:
    """Public helper — used by the status command and the web API.

    Wraps the boilerplate around ``build_context_from_workspace`` +
    ``select_suggestions`` + history load/save so callers don't need to
    know about the history path plumbing.
    """
    history = _load_history(workspace)
    ctx = build_context_from_workspace(
        workspace,
        active_session_id=(session.session_id if session else None),
        session_store=session_store,
    )
    return select_suggestions(ctx, history=history, limit=limit)


__all__ = ["build_suggest_command", "select_active_suggestions"]
