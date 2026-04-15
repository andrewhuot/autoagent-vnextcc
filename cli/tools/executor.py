"""Tool-call executor — the seam between the LLM loop and tool implementations.

A model response with a ``tool_use`` block hands the tool name and input to
:func:`execute_tool_call`, which:

1. Resolves the tool in the registry.
2. Computes the permission decision via :class:`PermissionManager`.
3. If the decision is ``ask``, runs the permission dialog and honours the
   user's choice (including session/persistent rule updates).
4. On allow, invokes ``tool.run(input, context)`` and returns a
   :class:`ToolExecution` wrapping the :class:`ToolResult`.
5. On deny, returns a :class:`ToolExecution` with a structured denial
   message that is safe to forward to the LLM as a ``tool_result``.

Separating this logic from the REPL loop means the workbench, the non-
interactive ``agentlab -p`` runner, and the API server can share the same
gating behaviour without each re-implementing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from cli.permissions import PermissionManager
from cli.tools.base import PermissionDecision, ToolContext, ToolResult
from cli.tools.registry import ToolRegistry


DialogRunner = Callable[..., Any]
"""Function with the same signature as :func:`request_permission`. Injected
so tests can bypass the interactive dialog."""


@dataclass
class ToolExecution:
    """Outcome of a full tool-call attempt, ready to serialise as a tool_result."""

    tool_name: str
    decision: PermissionDecision
    result: ToolResult | None
    """``None`` when the tool was denied before running."""

    denial_reason: str | None = None


def execute_tool_call(
    tool_name: str,
    tool_input: Mapping[str, Any],
    *,
    registry: ToolRegistry,
    permissions: PermissionManager,
    context: ToolContext,
    dialog_runner: DialogRunner | None = None,
    include_persist_option: bool = True,
    hook_registry: Any | None = None,
) -> ToolExecution:
    """Execute a single tool call end-to-end.

    Failure modes are never raised — callers forward ``ToolExecution`` to
    the LLM as a ``tool_result`` block, so a denial or a tool-level failure
    must surface as structured data rather than an exception.

    When ``hook_registry`` is a :class:`~cli.hooks.HookRegistry` the
    executor fires:

    * ``OnPermissionRequest`` — before the interactive dialog. A deny from
      this hook skips the dialog entirely so the user isn't prompted for
      something CI has already vetoed.
    * ``PreToolUse``          — after permission is resolved, before the
      tool actually runs. A deny here is a hard block even if the user
      approved the permission dialog.
    * ``PostToolUse``          — after :meth:`Tool.run` returns. Its
      output is attached to the execution metadata so the UI can surface
      lint warnings etc., but the tool result is not altered.
    """

    if not registry.has(tool_name):
        return ToolExecution(
            tool_name=tool_name,
            decision=PermissionDecision.DENY,
            result=ToolResult.failure(f"Unknown tool: {tool_name}"),
            denial_reason="unknown_tool",
        )

    tool = registry.get(tool_name)
    raw_decision = permissions.decision_for_tool(tool, tool_input)

    if raw_decision == "deny":
        return ToolExecution(
            tool_name=tool_name,
            decision=PermissionDecision.DENY,
            result=ToolResult.failure(
                f"Permission denied for {tool_name} in mode '{permissions.mode}'."
            ),
            denial_reason="policy_deny",
        )

    hook_messages: list[str] = []

    if raw_decision == "ask":
        if hook_registry is not None:
            pre_perm = _fire_hook(
                hook_registry,
                "OnPermissionRequest",
                tool_name=tool_name,
                payload={"tool": tool_name, "input": dict(tool_input)},
            )
            if pre_perm and pre_perm.verdict.value == "deny":
                hook_messages.extend(pre_perm.messages)
                return ToolExecution(
                    tool_name=tool_name,
                    decision=PermissionDecision.DENY,
                    result=ToolResult.failure(
                        "Hook denied permission request: "
                        + ("; ".join(pre_perm.messages) or "no message")
                    ),
                    denial_reason="hook_deny",
                )
            if pre_perm is not None and getattr(pre_perm, "fired", 0) > 0:
                # A hook actually ran and did not deny — treat as auto-
                # approval so the interactive dialog is skipped. Outcomes
                # where ``fired == 0`` mean no hook was subscribed, so
                # the ALLOW default is meaningless and we must still
                # prompt the user.
                hook_messages.extend(pre_perm.messages)
                raw_decision = "allow"

    if raw_decision == "ask":
        runner = dialog_runner or _lazy_default_dialog_runner()
        outcome = runner(
            tool,
            tool_input,
            include_persist_option=include_persist_option,
        )
        if not outcome.allow:
            return ToolExecution(
                tool_name=tool_name,
                decision=PermissionDecision.DENY,
                result=ToolResult.failure(f"User denied {tool_name}."),
                denial_reason="user_deny",
            )
        if outcome.persist_rule and outcome.persist_scope == "session":
            permissions.allow_for_session(outcome.persist_rule)
        elif outcome.persist_rule and outcome.persist_scope == "settings":
            permissions.persist_allow_rule(outcome.persist_rule)

    if hook_registry is not None:
        pre_use = _fire_hook(
            hook_registry,
            "PreToolUse",
            tool_name=tool_name,
            payload={"tool": tool_name, "input": dict(tool_input)},
        )
        if pre_use and pre_use.verdict.value == "deny":
            hook_messages.extend(pre_use.messages)
            return ToolExecution(
                tool_name=tool_name,
                decision=PermissionDecision.DENY,
                result=ToolResult.failure(
                    "PreToolUse hook blocked invocation: "
                    + ("; ".join(pre_use.messages) or "no message")
                ),
                denial_reason="hook_deny",
            )
        if pre_use:
            hook_messages.extend(pre_use.messages)

    try:
        result = tool.run(tool_input, context)
    except Exception as exc:  # pragma: no cover - defensive; tools must not raise
        result = ToolResult.failure(f"{tool_name} crashed: {exc}")

    if hook_registry is not None:
        post_use = _fire_hook(
            hook_registry,
            "PostToolUse",
            tool_name=tool_name,
            payload={
                "tool": tool_name,
                "input": dict(tool_input),
                "ok": result.ok,
                "content": result.content,
            },
        )
        if post_use:
            hook_messages.extend(post_use.messages)

    if hook_messages and result.metadata is not None:
        # Non-destructive: mirror hook diagnostics onto the result metadata
        # so the UI can render "N hook messages" without re-running hooks.
        result.metadata.setdefault("hook_messages", []).extend(hook_messages)

    return ToolExecution(
        tool_name=tool_name,
        decision=PermissionDecision.ALLOW,
        result=result,
    )


def _fire_hook(hook_registry: Any, event_name: str, *, tool_name: str, payload: dict[str, Any]):
    """Thin adapter around :class:`HookRegistry.fire`.

    The signature is resolved lazily so modules that don't use hooks
    never pay for the import, and tests can pass a fake registry
    implementing only ``fire``."""
    from cli.hooks import HookEvent

    try:
        event = HookEvent(event_name)
    except ValueError:
        return None
    try:
        return hook_registry.fire(event, tool_name=tool_name, payload=payload)
    except Exception:  # pragma: no cover - hooks must never crash the loop
        return None


def _lazy_default_dialog_runner() -> DialogRunner:
    """Import the interactive dialog lazily so non-interactive callers
    (tests, ``agentlab -p``) never pull in :mod:`click` prompting
    machinery they don't need."""
    from cli.workbench_app.permission_dialog import request_permission

    def _runner(tool, tool_input, *, include_persist_option=True):
        return request_permission(
            tool,
            tool_input,
            include_persist_option=include_persist_option,
        )

    return _runner
