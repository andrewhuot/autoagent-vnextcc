"""Lifecycle hooks for the workbench.

Mirrors Claude Code's ``settings.json::hooks`` block: authors register
shell commands to run before/after tool use, on permission requests, and
at session stop. Hooks receive the event payload on stdin as JSON and can
block the action via a non-zero exit code (with an optional message on
stderr that the REPL surfaces to the user).

Design notes:

* :class:`HookDefinition` is a plain dataclass so test fixtures can build
  one without parsing JSON.
* :class:`HookRegistry` owns the config; the tool executor calls
  :meth:`HookRegistry.fire` with the event name and payload.
* Hook commands run synchronously with a tight timeout. Long-running
  validators should be factored into scheduled jobs; the REPL should not
  block on them.

Events supported:

* ``beforeQuery``        — before a model turn starts. Hook output can
                           annotate or gate the upcoming turn.
* ``afterQuery``         — after a model turn completes. Useful for
                           turn-level telemetry.
* ``PreToolUse``         — before a tool is permitted to run. Exit 0 →
                           allow. Exit 1 → treat as deny. Stderr text is
                           passed back to the user.
* ``PostToolUse``        — after a tool completes. Output is captured for
                           the transcript but cannot alter the result.
* ``OnPermissionRequest``— before the interactive dialog fires. A
                           successful exit auto-approves; a non-zero exit
                           auto-denies. Letting a hook pre-decide reduces
                           dialog spam for known-safe patterns.
* ``Stop``               — at session end. Fire-and-forget for cleanup
                           or autosave scripts.
* ``SubagentStop`` /
  ``SessionEnd``         — lifecycle cleanup hooks for nested agents and
                           full sessions.
"""

from __future__ import annotations

from cli.hooks.types import HookDefinition, HookEvent, HookOutcome, HookType, HookVerdict
from cli.hooks.registry import HookRegistry, load_hook_registry

__all__ = [
    "HookDefinition",
    "HookEvent",
    "HookOutcome",
    "HookRegistry",
    "HookType",
    "HookVerdict",
    "load_hook_registry",
]
