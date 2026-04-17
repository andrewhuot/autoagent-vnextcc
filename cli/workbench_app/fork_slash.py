"""``/fork`` slash command — start a fresh conversation under the same runtime.

R7.C.7 part B. After a workspace switch (or whenever the user wants a
clean slate without restarting the REPL), ``/fork`` allocates a brand
new conversation in the SQLite store, swaps the runtime to point at it,
and clears the orchestrator's in-memory message buffer. The previous
conversation row stays intact — operators can hop back to it later via
``/resume <old_id>``.

Mutations:
- ``runtime.conversation_id`` ← new id
- ``runtime.conversation_bridge`` ← fresh :class:`ConversationBridge`
  bound to the new id
- ``runtime.orchestrator.messages`` ← ``[]``
- ``runtime.workbench_session.current_conversation_id`` ← new id (when
  a session is bound). The workspace-change observer is keyed off
  ``current_config_path`` and ignores conversation-id updates, so this
  doesn't trigger a recursive switch warning.
"""

from __future__ import annotations

from typing import Any

from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.conversation_bridge import ConversationBridge
from cli.workbench_app.slash import SlashContext


def _runtime_from_ctx(ctx: SlashContext) -> Any | None:
    """Return the :class:`WorkbenchRuntime` published on ``ctx.meta`` or None."""
    runtime = ctx.meta.get("workbench_runtime") if isinstance(ctx.meta, dict) else None
    if runtime is None:
        return None
    if not hasattr(runtime, "conversation_store"):
        return None
    return runtime


def _resolve_workspace_root(runtime: Any) -> str | None:
    """Best-effort workspace-root extraction for the new conversation row.

    Tries (in order): an explicit ``runtime.workspace_root`` field, then
    the bound :class:`WorkbenchSession`'s on-disk path's grandparent
    (``<workspace>/.agentlab/workbench_session.json`` → ``<workspace>``).
    """
    explicit = getattr(runtime, "workspace_root", None)
    if explicit is not None:
        return str(explicit)
    workbench_session = getattr(runtime, "workbench_session", None)
    path = getattr(workbench_session, "_path", None) if workbench_session else None
    if path is not None:
        try:
            return str(path.parent.parent)
        except Exception:  # pragma: no cover — defensive
            return None
    return None


def _handle_fork(ctx: SlashContext, *_args: str) -> OnDoneResult:
    """Mint a new conversation and rebind the runtime to it."""
    runtime = _runtime_from_ctx(ctx)
    if runtime is None:
        return on_done(
            "  /fork is not available without a Workbench runtime.",
            display="system",
        )

    old_id = getattr(runtime, "conversation_id", None)
    workspace_root = _resolve_workspace_root(runtime)
    model_id = getattr(runtime, "model_id", None)

    store = runtime.conversation_store
    new_conv = store.create_conversation(
        workspace_root=workspace_root,
        model=model_id,
    )

    runtime.conversation_id = new_conv.id
    runtime.conversation_bridge = ConversationBridge(
        store=store, conversation_id=new_conv.id
    )

    orchestrator = getattr(runtime, "orchestrator", None)
    if orchestrator is not None:
        try:
            orchestrator.messages = []
        except Exception:  # pragma: no cover — defensive
            pass

    workbench_session = getattr(runtime, "workbench_session", None)
    if workbench_session is not None:
        try:
            workbench_session.update(current_conversation_id=new_conv.id)
        except Exception:  # pragma: no cover — session update is best-effort
            pass

    if old_id:
        message = (
            f"  Started new conversation {new_conv.id}. "
            f"Old conversation: {old_id}."
        )
    else:
        message = f"  Started new conversation {new_conv.id}."
    return on_done(message, display="user")


def build_fork_command(
    *, description: str = "Start a fresh conversation under the same runtime"
) -> LocalCommand:
    """Construct the ``/fork`` :class:`LocalCommand` used by the registry."""
    return LocalCommand(
        name="fork",
        description=description,
        handler=_handle_fork,
        source="builtin",
        when_to_use=(
            "Use after switching workspaces or when the current conversation "
            "is on a stale topic. The previous conversation stays in the "
            "store and can be re-entered with /resume."
        ),
    )


__all__ = ["build_fork_command"]
