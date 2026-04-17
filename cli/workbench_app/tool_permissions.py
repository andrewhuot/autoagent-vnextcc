"""Permission policy for LLM-driven tool calls.

The conversation loop consults a :class:`PermissionTable` before
dispatching every tool call. Three policies:

- ``allow`` — fire immediately, no prompt.
- ``deny`` — refuse silently; the loop returns an error to the model.
- ``ask`` — raise :class:`PermissionPending`; the UI prompts the user;
  the loop resumes (or aborts) based on the response.

Defaults are conservative: read-only inspection tools are ``allow``,
anything that costs money or mutates workspace state is ``ask``.
``deny`` is never a default — it exists for users who want to lock
down a tool they consistently don't want the model touching.

This module is intentionally a pure data structure. It does not own
the prompt UI, does not call the LLM, and does not know what a tool
is beyond its name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Policy(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PermissionPending(Exception):
    """Raised when a tool requires user approval before invocation."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"Tool '{tool_name}' requires user approval")
        self.tool_name = tool_name


class PermissionDenied(Exception):
    """Raised when a tool is explicitly denied. The loop returns an
    error message to the model so it can pick a different action."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"Tool '{tool_name}' is denied for this conversation")
        self.tool_name = tool_name


DEFAULT_POLICIES: dict[str, Policy] = {
    "improve_list": Policy.ALLOW,
    "improve_show": Policy.ALLOW,
    "improve_diff": Policy.ALLOW,
    "eval_run": Policy.ASK,
    "improve_run": Policy.ASK,
    "improve_accept": Policy.ASK,
    "deploy": Policy.ASK,
}


@dataclass
class PermissionTable:
    """Mutable per-conversation policy table.

    Per-conversation overrides (set via :meth:`remember`) take
    precedence over defaults. Overrides do NOT persist across
    conversations — a user trusting ``deploy`` in one conversation
    must re-approve in the next.
    """

    defaults: dict[str, Policy] = field(default_factory=lambda: dict(DEFAULT_POLICIES))
    overrides: dict[str, Policy] = field(default_factory=dict)

    def policy_for(self, tool_name: str) -> Policy:
        if tool_name in self.overrides:
            return self.overrides[tool_name]
        return self.defaults.get(tool_name, Policy.ASK)

    def check(self, tool_name: str) -> None:
        """Raise :class:`PermissionPending` or :class:`PermissionDenied`
        if the tool is not currently allowed. Returns ``None`` on allow."""
        policy = self.policy_for(tool_name)
        if policy is Policy.ALLOW:
            return
        if policy is Policy.DENY:
            raise PermissionDenied(tool_name)
        raise PermissionPending(tool_name)

    def remember(self, tool_name: str, policy: Policy) -> None:
        """Set a per-conversation override (e.g. user clicks 'allow for
        this conversation')."""
        self.overrides[tool_name] = policy

    def forget(self, tool_name: str) -> None:
        """Drop a per-conversation override; the default applies again."""
        self.overrides.pop(tool_name, None)
