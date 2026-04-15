"""Per-tool permission dialog.

Claude Code's permission UI is a rich Ink component. We implement a pragmatic
text-mode equivalent that:

* Prints the tool's preview (``tool.render_preview(input)``) so the user sees
  what's about to run.
* Presents the four standard verbs — Approve, Approve always (session),
  Approve always (save), Deny — as a single-letter menu.
* Returns a typed :class:`DialogOutcome` so the caller (workbench loop) can
  update the :class:`PermissionManager` session state or persist a rule
  without the dialog knowing about settings.

The dialog is pure: no global state, no side effects on the registry. It
accepts an injectable ``prompter`` (defaults to :func:`click.prompt`) so
tests run without a TTY. This mirrors ``app.py``'s ``input_provider`` pattern.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

import click


class DialogChoice(str, Enum):
    """User's selection from the dialog."""

    APPROVE = "approve"
    APPROVE_SESSION = "approve_session"
    APPROVE_PERSIST = "approve_persist"
    DENY = "deny"


@dataclass(frozen=True)
class DialogOutcome:
    """Structured dialog result consumed by the tool-call loop."""

    choice: DialogChoice
    """The user's selection."""

    allow: bool
    """Convenience flag: ``True`` when the tool should run."""

    persist_rule: str | None
    """When set, the caller should append this pattern to the allow list
    (session or persistent, depending on ``persist_scope``)."""

    persist_scope: str | None
    """One of ``"session"`` or ``"settings"``. ``None`` when no rule should
    be remembered."""


Prompter = Callable[[str], str]
"""Callable that returns one line of user input for a given prompt string.

Defaults to :func:`click.prompt`. Tests inject a lambda that returns canned
responses so the dialog exercises every branch without a TTY."""


def _default_prompter(prompt: str) -> str:
    return click.prompt(prompt, default="a", show_default=True, type=str).strip().lower()


def request_permission(
    tool: Any,
    tool_input: Mapping[str, Any],
    *,
    echo: Callable[[str], None] = click.echo,
    prompter: Prompter | None = None,
    include_persist_option: bool = True,
) -> DialogOutcome:
    """Run the permission dialog for one tool invocation.

    ``include_persist_option`` should be ``False`` when there is no
    workspace ``settings.json`` to write to (e.g. ephemeral test harnesses);
    the "persist" verb is hidden so the user can't select an option the
    caller cannot honour.
    """
    prompter = prompter or _default_prompter

    echo("")
    echo(f"  Permission requested: {tool.name}")
    preview = tool.render_preview(tool_input)
    for line in str(preview).splitlines() or [""]:
        echo(f"    {line}")
    echo("")
    echo("  [a] Approve once")
    echo("  [s] Approve always (this session)")
    if include_persist_option:
        echo("  [p] Approve always (save to settings.json)")
    echo("  [d] Deny")

    response = prompter("Choose").strip().lower()
    return _map_response(response, tool, tool_input, include_persist_option)


def _map_response(
    response: str,
    tool: Any,
    tool_input: Mapping[str, Any],
    include_persist_option: bool,
) -> DialogOutcome:
    """Translate the user's keystroke into a :class:`DialogOutcome`.

    Kept separate from :func:`request_permission` so tests can assert the
    mapping without re-running the echo side effects.
    """
    pattern = _session_pattern_for(tool, tool_input)

    if response in {"a", "approve", "y", "yes", ""}:
        return DialogOutcome(
            choice=DialogChoice.APPROVE,
            allow=True,
            persist_rule=None,
            persist_scope=None,
        )
    if response in {"s", "session"}:
        return DialogOutcome(
            choice=DialogChoice.APPROVE_SESSION,
            allow=True,
            persist_rule=pattern,
            persist_scope="session",
        )
    if include_persist_option and response in {"p", "persist", "save"}:
        return DialogOutcome(
            choice=DialogChoice.APPROVE_PERSIST,
            allow=True,
            persist_rule=pattern,
            persist_scope="settings",
        )
    # Any unrecognised or "deny" token denies — explicit default minimises
    # the risk of a stray keystroke auto-approving a destructive tool.
    return DialogOutcome(
        choice=DialogChoice.DENY,
        allow=False,
        persist_rule=None,
        persist_scope=None,
    )


def _session_pattern_for(tool: Any, tool_input: Mapping[str, Any]) -> str:
    """Return the pattern to remember when the user approves "always".

    For path-scoped tools (FileEdit, FileWrite, ConfigEdit) we widen the
    pattern to ``tool:<Name>:*`` so "always allow edits" remembers the
    intent rather than a single file. BashTool stays on its specific
    command string — "always allow ``rm -rf``" is never a useful policy.
    """
    name = getattr(tool, "name", "?")
    if name in {"Bash"}:
        return tool.permission_action(tool_input)
    return f"tool:{name}:*"
