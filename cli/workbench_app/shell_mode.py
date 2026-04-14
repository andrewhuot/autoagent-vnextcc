"""Shell-mode input (``!`` prefix) for the Workbench REPL.

When a user types ``!<cmd>`` at the prompt, the rest of the line is
executed as a shell command inside the workspace root. The affordance
mirrors Claude Code's shell escape but is gated by the active permission
mode:

=======================  =============================================
Permission mode           Behavior
=======================  =============================================
``plan``                  Blocked. The user is told to cycle out of plan mode.
``default``               Confirm (``y/N``) before executing.
``acceptEdits`` / ``bypass`` / ``dontAsk``  Execute immediately.
=======================  =============================================

The module deliberately does not rely on prompt_toolkit — callers inject
an ``input_provider`` for the confirmation so the same helper works under
headless tests. The actual subprocess runner is abstracted for the same
reason.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cli.workbench_app import theme


InputProvider = Callable[[str], str]
EchoFn = Callable[[str], None]
Runner = Callable[[str, Path | None], tuple[int, str]]

SHELL_PREFIX = "!"

_MODES_AUTO = frozenset({"acceptEdits", "bypass", "dontAsk"})
_MODES_CONFIRM = frozenset({"default"})
_MODES_BLOCKED = frozenset({"plan"})


@dataclass(frozen=True)
class ShellOutcome:
    """Outcome of one shell-mode turn.

    ``handled`` is ``True`` for any line that looked like shell mode even
    when the command was refused (so the caller doesn't also route it as a
    coordinator turn). ``ran`` is ``True`` only when the subprocess
    actually executed. ``returncode`` is ``None`` unless ``ran``.
    """

    handled: bool
    ran: bool = False
    returncode: int | None = None
    stdout: str = ""
    reason: str = ""


def is_shell_line(line: str) -> bool:
    """Return ``True`` when the line is a shell-mode request."""
    stripped = line.lstrip()
    return stripped.startswith(SHELL_PREFIX)


def _extract_command(line: str) -> str:
    """Strip the leading ``!`` and surrounding whitespace."""
    stripped = line.lstrip()
    if not stripped.startswith(SHELL_PREFIX):
        return ""
    return stripped[len(SHELL_PREFIX):].strip()


def _default_runner(command: str, cwd: Path | None) -> tuple[int, str]:
    """Run ``command`` under ``/bin/sh -c`` and capture combined output."""
    completed = subprocess.run(  # noqa: S602 - shell is intentional here
        command,
        shell=True,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    out = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, out


def run_shell_turn(
    line: str,
    *,
    permission_mode: str,
    echo: EchoFn,
    input_provider: InputProvider | None = None,
    workspace_root: Path | None = None,
    runner: Runner | None = None,
) -> ShellOutcome:
    """Execute one shell-mode turn and return the outcome.

    Parameters
    ----------
    line:
        The raw user input (must start with ``!`` after stripping leading
        whitespace — callers should gate with :func:`is_shell_line` first).
    permission_mode:
        The active workbench permission mode — drives the gate.
    echo:
        Transcript sink for user-visible messages.
    input_provider:
        Callable used to read the confirmation prompt in ``default`` mode.
        When ``None`` the caller is asking us to treat the turn as
        auto-confirmed (useful for tests of the execution path).
    workspace_root:
        Directory to run the shell command in. ``None`` falls back to the
        current working directory.
    runner:
        Injectable subprocess runner. Takes the command string and a cwd
        path, returns ``(returncode, combined_output)``.
    """
    if not is_shell_line(line):
        return ShellOutcome(handled=False)

    command = _extract_command(line)
    mode = (permission_mode or "default").strip() or "default"

    if not command:
        echo(theme.warning("  Shell mode: provide a command after '!'."))
        return ShellOutcome(handled=True, reason="empty")

    if mode in _MODES_BLOCKED:
        echo(theme.error(
            "  Shell mode is blocked in plan permission mode.",
            bold=False,
        ))
        echo(theme.meta(
            "  Press shift+tab to leave plan mode, or use /status to inspect the workspace."
        ))
        return ShellOutcome(handled=True, reason="blocked_plan")

    if mode in _MODES_CONFIRM:
        if input_provider is None:
            echo(theme.warning(
                "  Shell mode: confirmation required but no prompt is bound."
            ))
            return ShellOutcome(handled=True, reason="confirm_unavailable")
        echo(theme.meta(f"  Run shell command: {command}"))
        try:
            answer = input_provider("  Execute? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            echo(theme.meta("  Cancelled."))
            return ShellOutcome(handled=True, reason="cancelled")
        if answer.strip().lower() not in {"y", "yes"}:
            echo(theme.meta("  Skipped."))
            return ShellOutcome(handled=True, reason="declined")
    elif mode not in _MODES_AUTO:
        # Unknown mode → be conservative and refuse.
        echo(theme.warning(
            f"  Shell mode refused: unrecognized permission mode {mode!r}."
        ))
        return ShellOutcome(handled=True, reason="unknown_mode")

    run = runner or _default_runner
    try:
        returncode, output = run(command, workspace_root)
    except Exception as exc:  # noqa: BLE001 - runner errors shouldn't crash loop
        echo(theme.error(f"  Shell mode error: {exc}", bold=False))
        return ShellOutcome(handled=True, reason="runner_error")

    if output:
        for out_line in output.rstrip("\n").splitlines():
            echo(f"  {out_line}")
    suffix = "" if returncode == 0 else f" (exit {returncode})"
    echo(theme.meta(f"  $ {command}{suffix}"))
    return ShellOutcome(
        handled=True,
        ran=True,
        returncode=returncode,
        stdout=output,
    )


def permission_allows_auto(permission_mode: str) -> bool:
    """Return ``True`` when shell mode executes without confirmation."""
    return (permission_mode or "").strip() in _MODES_AUTO


def format_command_preview(line: str) -> str:
    """Return a quoted preview of the command for log/meta messages."""
    command = _extract_command(line)
    if not command:
        return ""
    try:
        return shlex.quote(command)
    except Exception:  # pragma: no cover — defensive
        return repr(command)


__all__ = [
    "SHELL_PREFIX",
    "ShellOutcome",
    "format_command_preview",
    "is_shell_line",
    "permission_allows_auto",
    "run_shell_turn",
]


def _unused_context_hint(_: Any) -> None:  # pragma: no cover
    """Placeholder hook; retained for symmetry with other input-mode modules."""
    return None
