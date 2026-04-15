"""Slash commands for transcript rewind.

Named ``/transcript-checkpoint``, ``/transcript-rewind`` and
``/transcript-checkpoints`` so they never collide with the existing
config-versioning commands (``/checkpoint``, ``/rewind``, ``/checkpoints``).

Handlers pull :class:`TranscriptRewindManager` off
``SlashContext.meta['transcript_rewind_manager']`` so tests and the REPL
share a single manager instance."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from cli.workbench_app import theme
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.transcript_checkpoint import (
    TranscriptCheckpoint,
    TranscriptRewindManager,
)

if TYPE_CHECKING:
    from cli.workbench_app.slash import SlashContext


TRANSCRIPT_REWIND_MANAGER_META_KEY = "transcript_rewind_manager"


def build_transcript_checkpoint_command() -> LocalCommand:
    return LocalCommand(
        name="transcript-checkpoint",
        description="Snapshot the current transcript length for later rewind",
        handler=_handle_snapshot,
        source="builtin",
        argument_hint="[label]",
        when_to_use=(
            "Use before an exploratory turn you might want to undo so "
            "/transcript-rewind can restore the prior state."
        ),
    )


def build_transcript_rewind_command() -> LocalCommand:
    return LocalCommand(
        name="transcript-rewind",
        description="Rewind the transcript to a saved checkpoint",
        handler=_handle_rewind,
        source="builtin",
        argument_hint="<checkpoint-id>",
        sensitive=True,
    )


def build_transcript_checkpoints_command() -> LocalCommand:
    return LocalCommand(
        name="transcript-checkpoints",
        description="List transcript checkpoints for the active session",
        handler=_handle_list,
        source="builtin",
        argument_hint="[--all]",
    )


def all_transcript_rewind_commands() -> tuple[LocalCommand, ...]:
    return (
        build_transcript_checkpoint_command(),
        build_transcript_rewind_command(),
        build_transcript_checkpoints_command(),
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _handle_snapshot(ctx: "SlashContext", *args: str) -> OnDoneResult:
    manager = _manager_or_error(ctx)
    if isinstance(manager, OnDoneResult):
        return manager
    session = ctx.session
    if session is None:
        return _no_session()

    label = " ".join(args).strip()
    checkpoint = manager.snapshot(session, label=label)
    return on_done(
        theme.success(
            f"  Transcript checkpoint saved: {checkpoint.checkpoint_id} "
            f"(at message {checkpoint.message_index})"
        ),
        display="user",
    )


def _handle_rewind(ctx: "SlashContext", *args: str) -> OnDoneResult:
    manager = _manager_or_error(ctx)
    if isinstance(manager, OnDoneResult):
        return manager
    session = ctx.session
    if session is None:
        return _no_session()

    if not args:
        return on_done(
            theme.meta(
                "  Usage: /transcript-rewind <checkpoint-id>. "
                "Use /transcript-checkpoints to list available ids."
            ),
            display="system",
        )

    checkpoint_id = args[0].strip()
    try:
        checkpoint, removed = manager.rewind(session, checkpoint_id)
    except ValueError as exc:
        return on_done(theme.warning(f"  {exc}"), display="system")

    lines = [
        theme.success(
            f"  Rewound to checkpoint {checkpoint.checkpoint_id} "
            f"(message {checkpoint.message_index})."
        ),
        theme.meta(f"  Dropped {removed} message(s) from the transcript."),
    ]
    if checkpoint.label:
        lines.append(theme.meta(f"  Label: {checkpoint.label}"))
    return on_done("\n".join(lines), display="user")


def _handle_list(ctx: "SlashContext", *args: str) -> OnDoneResult:
    manager = _manager_or_error(ctx)
    if isinstance(manager, OnDoneResult):
        return manager
    session = ctx.session
    if session is None:
        return _no_session()

    show_auto = "--all" in [shlex.split(arg)[0] if arg else arg for arg in args]
    entries = manager.list(session.session_id, include_auto=show_auto)
    if not entries:
        return on_done(
            theme.meta(
                "  No transcript checkpoints yet. Use /transcript-checkpoint [label] "
                "to create one, or pass --all to include auto-saved entries."
            ),
            display="system",
        )

    lines = [theme.workspace("Transcript checkpoints (newest first)")]
    for checkpoint in entries:
        lines.append(_format_checkpoint_line(checkpoint))
    return on_done("\n".join(lines), display="user")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _manager_or_error(ctx: "SlashContext") -> TranscriptRewindManager | OnDoneResult:
    manager = ctx.meta.get(TRANSCRIPT_REWIND_MANAGER_META_KEY) if ctx.meta else None
    if isinstance(manager, TranscriptRewindManager):
        return manager
    return on_done(
        theme.warning(
            "  Transcript rewind is not configured for this session. "
            "Re-launch the workbench or file a bug if this is unexpected."
        ),
        display="system",
    )


def _no_session() -> OnDoneResult:
    return on_done(
        theme.warning("  No active session — transcript rewind requires one."),
        display="system",
    )


def _format_checkpoint_line(checkpoint: TranscriptCheckpoint) -> str:
    tag = "auto" if checkpoint.auto else "manual"
    body = (
        f"    {checkpoint.checkpoint_id}  msg {checkpoint.message_index}  "
        f"[{tag}]"
    )
    if checkpoint.label:
        body += f"  — {checkpoint.label}"
    return body


__all__ = [
    "TRANSCRIPT_REWIND_MANAGER_META_KEY",
    "all_transcript_rewind_commands",
    "build_transcript_checkpoint_command",
    "build_transcript_checkpoints_command",
    "build_transcript_rewind_command",
]
