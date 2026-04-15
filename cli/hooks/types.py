"""Typed records for the hooks framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HookEvent(str, Enum):
    """Lifecycle events that hooks may subscribe to.

    String values match the :mod:`settings.json` keys Claude Code uses so
    an author can copy a configuration between the two tools unchanged."""

    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    ON_PERMISSION_REQUEST = "OnPermissionRequest"
    STOP = "Stop"


class HookVerdict(str, Enum):
    """Decision communicated back to the tool executor.

    * ``ALLOW``   — proceed with the action (default for 0-exit).
    * ``DENY``    — block the tool invocation (non-zero exit for any
                   ``PreToolUse`` / ``OnPermissionRequest`` hook).
    * ``INFORM``  — hook produced output but the event doesn't gate the
                   action (``PostToolUse``, ``Stop``).
    """

    ALLOW = "allow"
    DENY = "deny"
    INFORM = "inform"


@dataclass
class HookDefinition:
    """One registered hook entry.

    The ``matcher`` pattern is matched against the tool name for
    ``PreToolUse``/``PostToolUse``/``OnPermissionRequest`` hooks — empty
    string means "match everything". ``Stop`` hooks ignore the matcher
    because there is no tool at that event."""

    event: HookEvent
    matcher: str
    command: str
    timeout_seconds: int = 30
    """Hard ceiling on shell hooks — we cap the REPL's exposure to a
    buggy validator. Authors who need longer runtimes should move the
    work to a background job and signal completion another way."""

    shell: str = "bash"
    """Interpreter used for ``bash -c <command>``. ``"bash"`` covers the
    macOS/Linux fleet; Windows users can override per-hook via settings."""

    env: dict[str, str] = field(default_factory=dict)
    """Extra env vars injected into the hook process — useful for surfaces
    like ``GITHUB_TOKEN`` or CI-only toggles without exporting them
    globally in the user's shell."""

    def matches_tool(self, tool_name: str) -> bool:
        """``matcher`` is a simple fnmatch expression; empty → match all."""
        if not self.matcher:
            return True
        from fnmatch import fnmatch

        return fnmatch(tool_name, self.matcher)


@dataclass
class HookOutcome:
    """Result of firing all hooks subscribed to one event.

    Aggregating outcomes (rather than returning the last one) means a
    single denying hook wins even when others downstream of it exit 0.
    ``messages`` preserves every hook's stderr so the REPL can relay
    diagnostics, not just the final decision. ``fired`` counts how many
    hooks actually ran so callers can distinguish "no hooks subscribed"
    (the default ALLOW verdict should be ignored) from "every subscribed
    hook approved" (the ALLOW is meaningful)."""

    verdict: HookVerdict = HookVerdict.ALLOW
    messages: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    fired: int = 0

    def record_fired(self) -> None:
        self.fired += 1

    def record_deny(self, message: str) -> None:
        self.verdict = HookVerdict.DENY
        if message:
            self.messages.append(message)

    def record_inform(self, message: str) -> None:
        if self.verdict == HookVerdict.ALLOW:
            self.verdict = HookVerdict.INFORM
        if message:
            self.messages.append(message)


__all__ = ["HookDefinition", "HookEvent", "HookOutcome", "HookVerdict"]
