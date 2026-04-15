"""Slash command that renders the context-usage grid.

The existing ``/context`` command shows coordinator turn history, so we
expose the token-usage visualisation as ``/usage`` to avoid disrupting
existing muscle memory. Users can run either; Claude Code's single
``/context`` command fuses both views, which we could revisit once the
UX settles.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cli.workbench_app import theme
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.context_viz import (
    DEFAULT_CONTEXT_LIMIT,
    render_context_grid,
    snapshot_from_transcript,
)

if TYPE_CHECKING:
    from cli.workbench_app.slash import SlashContext


def build_usage_command() -> LocalCommand:
    """Return the ``/usage`` command definition."""
    return LocalCommand(
        name="usage",
        description="Show a context-window token-usage grid for the current session",
        handler=_handle_usage,
        source="builtin",
        when_to_use=(
            "Use to see which message roles dominate the context window — "
            "pair with /compact when the grid shows the red-zone warning."
        ),
        sensitive=False,
    )


def _handle_usage(ctx: "SlashContext", *_: str) -> OnDoneResult:
    """Build the snapshot and render the grid inline in the transcript."""
    session = ctx.session
    if session is None or not session.transcript:
        return on_done(
            theme.meta(
                "  No transcript recorded yet — run a turn, then /usage will "
                "show the context footprint."
            ),
            display="system",
        )

    context_limit = _context_limit_from_ctx(ctx)
    system_prompt = _system_prompt_from_ctx(ctx)
    tool_overhead = _tool_overhead_from_ctx(ctx)
    active_model = _active_model_from_ctx(ctx)

    snapshot = snapshot_from_transcript(
        ({"role": entry.role, "content": entry.content} for entry in session.transcript),
        system_prompt=system_prompt,
        tool_overhead=tool_overhead,
        context_limit=context_limit,
        model=active_model,
    )

    lines = [theme.workspace("Context window usage"), ""]
    lines.extend(render_context_grid(snapshot))
    return on_done("\n".join(lines), display="user")


# ---------------------------------------------------------------------------
# Meta helpers
# ---------------------------------------------------------------------------


def _context_limit_from_ctx(ctx: "SlashContext") -> int:
    """Pull the workspace's configured context limit off ``meta`` when the
    REPL has published it. Falls back to the Claude-family default."""
    value = ctx.meta.get("context_limit") if ctx.meta else None
    try:
        parsed = int(value) if value is not None else DEFAULT_CONTEXT_LIMIT
    except (TypeError, ValueError):
        parsed = DEFAULT_CONTEXT_LIMIT
    return parsed if parsed > 0 else DEFAULT_CONTEXT_LIMIT


def _system_prompt_from_ctx(ctx: "SlashContext") -> str:
    """Optional system prompt text, attributed to the ``system`` role."""
    value = ctx.meta.get("system_prompt") if ctx.meta else None
    return str(value) if isinstance(value, str) else ""


def _tool_overhead_from_ctx(ctx: "SlashContext") -> int:
    """Optional int representing the tokens consumed by tool schemas
    shown to the model each turn. Accounted against the ``tool`` role."""
    value = ctx.meta.get("tool_schema_tokens") if ctx.meta else None
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _active_model_from_ctx(ctx: "SlashContext") -> str | None:
    """Currently-selected model id, if the REPL has published one on ``meta``.

    Used downstream to resolve per-model context windows via
    :mod:`cli.llm.capabilities` instead of the Claude-family default."""
    value = ctx.meta.get("active_model") if ctx.meta else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = ["build_usage_command"]
