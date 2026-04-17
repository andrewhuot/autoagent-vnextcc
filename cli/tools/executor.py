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
      this hook skips the dialog entirely; an ask keeps the prompt in the
      user's hands.
    * ``PreToolUse``          — after permission is resolved, before the
      tool actually runs. A deny here is a hard block even if the user
      approved the permission dialog.
    * ``PostToolUse``          — after :meth:`Tool.run` returns. Its
      messages are attached to result metadata, and Claude-style updated
      output metadata can replace the content forwarded to the model.
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
    prompted_for_permission = False

    if raw_decision == "ask" and hook_registry is not None:
        pre_perm = _fire_hook(
            hook_registry,
            "OnPermissionRequest",
            tool_name=tool_name,
            payload=_tool_hook_payload(tool_name, tool_input),
        )
        if pre_perm:
            hook_messages.extend(pre_perm.messages)
        if pre_perm and _verdict(pre_perm) == "deny":
            return ToolExecution(
                tool_name=tool_name,
                decision=PermissionDecision.DENY,
                result=ToolResult.failure(
                    "Hook denied permission request: "
                    + _hook_message(pre_perm, default="no message")
                ),
                denial_reason="hook_deny",
            )
        if pre_perm and _verdict(pre_perm) in {"ask", "timeout"}:
            raw_decision = "ask"
        elif pre_perm is not None and getattr(pre_perm, "fired", 0) > 0:
            # A hook actually ran and did not ask/deny — treat it as the
            # existing auto-approval path. Outcomes where ``fired == 0`` mean
            # no hook was subscribed, so the default ALLOW must be ignored.
            raw_decision = "allow"

    if raw_decision == "ask":
        prompted_for_permission = True
        denied = _run_permission_dialog(
            tool_name=tool_name,
            tool=tool,
            tool_input=tool_input,
            permissions=permissions,
            dialog_runner=dialog_runner,
            include_persist_option=include_persist_option,
        )
        if denied is not None:
            return denied

    if hook_registry is not None:
        pre_use = _fire_hook(
            hook_registry,
            "PreToolUse",
            tool_name=tool_name,
            payload=_tool_hook_payload(tool_name, tool_input),
        )
        if pre_use:
            hook_messages.extend(pre_use.messages)
        if pre_use and _verdict(pre_use) == "deny":
            return ToolExecution(
                tool_name=tool_name,
                decision=PermissionDecision.DENY,
                result=ToolResult.failure(
                    "denied by hook: " + _hook_message(pre_use, default=tool_name)
                ),
                denial_reason="hook_deny",
            )
        if pre_use and _verdict(pre_use) == "ask" and not prompted_for_permission:
            denied = _run_permission_dialog(
                tool_name=tool_name,
                tool=tool,
                tool_input=tool_input,
                permissions=permissions,
                dialog_runner=dialog_runner,
                include_persist_option=include_persist_option,
            )
            if denied is not None:
                return denied

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
                "tool_name": tool_name,
                "tool_input": dict(tool_input),
                "tool_response": _tool_response_payload(result),
            },
        )
        if post_use:
            hook_messages.extend(post_use.messages)
            updated_response = _updated_tool_response(post_use)
            if updated_response is not None:
                result.content = updated_response

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


def _tool_hook_payload(tool_name: str, tool_input: Mapping[str, Any]) -> dict[str, Any]:
    return {"tool_name": tool_name, "tool_input": dict(tool_input)}


def _tool_response_payload(result: ToolResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": result.ok,
        "content": result.content,
        "metadata": dict(result.metadata or {}),
    }
    if result.display is not None:
        payload["display"] = result.display
    return payload


def _verdict(outcome: Any) -> str:
    verdict = getattr(outcome, "verdict", "")
    return str(getattr(verdict, "value", verdict)).lower()


def _hook_message(outcome: Any, *, default: str) -> str:
    messages = [str(message) for message in getattr(outcome, "messages", []) if message]
    return "; ".join(messages) if messages else default


def _updated_tool_response(outcome: Any) -> Any | None:
    metadata = getattr(outcome, "metadata", {}) or {}
    if "updated_tool_response" in metadata:
        return metadata["updated_tool_response"]
    if "updated_mcp_tool_output" in metadata:
        return metadata["updated_mcp_tool_output"]
    return None


def _run_permission_dialog(
    *,
    tool_name: str,
    tool: Any,
    tool_input: Mapping[str, Any],
    permissions: PermissionManager,
    dialog_runner: DialogRunner | None,
    include_persist_option: bool,
) -> ToolExecution | None:
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
