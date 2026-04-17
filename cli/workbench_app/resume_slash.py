"""``/resume`` slash command — restore a prior conversation into the live runtime.

R7.C.6 supersedes the session-based ``/resume`` (kept as a fallback for
test contexts that don't carry a :class:`WorkbenchRuntime`). When the
slash context exposes a runtime via ``ctx.meta["workbench_runtime"]``,
the handler:

- Defaults to the most recently updated conversation if no id is given.
- Loads the conversation history with
  :func:`cli.workbench_app.conversation_resume.load_history` and writes
  it onto ``runtime.orchestrator.messages``.
- Updates ``runtime.workbench_session.current_conversation_id`` so
  cross-cutting state (cost ticker observers, autosave, headless
  conversation tools) sees the swap.

Without a runtime on ``ctx.meta`` the handler delegates to the legacy
session-based implementation so the existing
``test_resume_handler_*`` tests in :mod:`tests/test_workbench_slash.py`
keep passing untouched.
"""

from __future__ import annotations

from typing import Any

from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.conversation_resume import load_history
from cli.workbench_app.slash import SlashContext, _handle_resume as _legacy_session_resume


def _runtime_from_ctx(ctx: SlashContext) -> Any | None:
    """Return the :class:`WorkbenchRuntime` published on ``ctx.meta`` (or None).

    The boot path in :mod:`app` publishes the runtime under
    ``"workbench_runtime"``. When absent — typical for the legacy
    session-resume tests and the headless ``StubAppResult`` paths — the
    handler falls back to the previous session-based behaviour.
    """
    runtime = ctx.meta.get("workbench_runtime") if isinstance(ctx.meta, dict) else None
    if runtime is None:
        return None
    if not hasattr(runtime, "conversation_store"):
        return None
    return runtime


def _handle_resume(ctx: SlashContext, *args: str) -> OnDoneResult:
    """Resume a conversation if a runtime is bound; else delegate to sessions."""
    runtime = _runtime_from_ctx(ctx)
    if runtime is None:
        return _legacy_session_resume(ctx, *args)

    store = runtime.conversation_store
    requested_id: str | None = args[0] if args else None

    if requested_id is None:
        recent = store.list_recent(limit=1)
        if not recent:
            return on_done(
                "  No conversations to resume.", display="system"
            )
        target_id = recent[0].id
    else:
        target_id = requested_id

    try:
        history = load_history(store, target_id)
    except KeyError:
        return on_done(
            f"  No conversation with id {target_id!r}.", display="system"
        )

    runtime.orchestrator.messages = history

    workbench_session = getattr(runtime, "workbench_session", None)
    if workbench_session is not None:
        try:
            workbench_session.update(current_conversation_id=target_id)
        except Exception:  # pragma: no cover — session update is best-effort
            pass

    return on_done(
        f"  Resumed conversation {target_id} ({len(history)} messages).",
        display="user",
    )


def build_resume_command(
    *, description: str = "Resume a prior conversation"
) -> LocalCommand:
    """Construct the ``/resume`` :class:`LocalCommand` used by the registry."""
    return LocalCommand(
        name="resume",
        description=description,
        handler=_handle_resume,
        source="builtin",
        argument_hint="[conversation_id]",
        when_to_use=(
            "Use after restarting Workbench, switching workspaces, or "
            "after an interrupted tool call to continue a prior conversation."
        ),
        aliases=("r",),
    )


__all__ = ["build_resume_command"]
