"""Stub entry point for the Claude-Code-style workbench REPL.

T04: banner, status line, input prompt — echo-only. Later tasks wire slash
commands (T05), status bar (T06), transcript pane (T07), tool-call blocks
(T08), and screens (T08b) onto this loop.

The loop is intentionally minimal but exposes the seams downstream tasks
need: an injectable ``input_provider`` and ``echo`` so tests drive it
without a TTY, and a ``run_workbench_app`` signature stable enough to wire
into ``cli/workbench.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

import click

from cli.branding import get_agentlab_version, render_startup_banner


InputProvider = Callable[[str], str]
"""Callable that returns the next line of input given a prompt string.

Raises ``EOFError`` or ``KeyboardInterrupt`` to end the loop (matching the
built-in ``input()`` contract). Tests inject a generator-backed provider.
"""

EchoFn = Callable[[str], None]
"""Write one line to the transcript. Defaults to :func:`click.echo`."""

DEFAULT_PROMPT = "agentlab> "
EXIT_TOKENS = frozenset({"/exit", "/quit", ":q"})


@dataclass(frozen=True)
class StubAppResult:
    """Return value for the stub loop — useful for assertions in tests."""

    lines_read: int
    exited_via: str  # "/exit", "eof", "interrupt"


def build_status_line(workspace: Any | None) -> str:
    """Render the one-line status shown under the banner.

    This is the stub version; T06 replaces it with a reactive status bar.
    Kept here (not in ``cli/repl.py``) so the workbench app has no reverse
    dependency on the legacy shell.
    """
    parts: list[str] = []
    if workspace is None:
        parts.append(click.style("no workspace", fg="yellow"))
    else:
        label = getattr(workspace, "workspace_label", None) or "workspace"
        parts.append(click.style(label, fg="cyan", bold=True))
        try:
            active = workspace.resolve_active_config()
        except Exception:
            active = None
        if active is not None:
            parts.append(f"v{active.version:03d}")
    parts.append(f"agentlab {get_agentlab_version()}")
    return " | ".join(parts)


def _default_input_provider(prompt: str) -> str:
    return input(prompt)


def _iter_input_provider(lines: Iterable[str]) -> InputProvider:
    """Wrap an iterable so it can stand in for ``input()`` in tests."""
    iterator = iter(lines)

    def _provider(_prompt: str) -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise EOFError from exc

    return _provider


def _render_banner(echo: EchoFn, workspace: Any | None) -> None:
    echo(render_startup_banner(get_agentlab_version()))
    echo("")
    echo(click.style("  AgentLab Workbench", fg="cyan", bold=True))
    echo(f"  [{build_status_line(workspace)}]")
    echo("  Type /help for commands, /exit to leave. (stub)")
    echo("")


def run_workbench_app(
    workspace: Any | None = None,
    *,
    input_provider: InputProvider | None = None,
    echo: EchoFn | None = None,
    prompt: str = DEFAULT_PROMPT,
    show_banner: bool = True,
) -> StubAppResult:
    """Run the echo-only workbench stub loop.

    Parameters
    ----------
    workspace:
        Active :class:`AgentLabWorkspace` or ``None``. Only used to render
        the status line — the stub does not yet run commands against it.
    input_provider:
        Callable returning the next input line. Accepts an iterable as a
        convenience for tests: ``run_workbench_app(input_provider=["hi"])``.
    echo:
        Callable that writes a transcript line. Defaults to ``click.echo``.
    prompt:
        Prompt text shown before each line. The real app will replace this
        with a prompt_toolkit ``PromptSession`` in a later task.
    show_banner:
        Suppress the banner for test scenarios that only care about loop
        behavior.
    """
    out: EchoFn = echo if echo is not None else click.echo
    if input_provider is None:
        reader: InputProvider = _default_input_provider
    elif callable(input_provider):
        reader = input_provider
    else:
        reader = _iter_input_provider(input_provider)  # type: ignore[arg-type]

    if show_banner:
        _render_banner(out, workspace)

    lines_read = 0
    exited_via = "eof"
    while True:
        try:
            raw = reader(prompt)
        except EOFError:
            exited_via = "eof"
            out("")
            break
        except KeyboardInterrupt:
            exited_via = "interrupt"
            out("")
            out(click.style("  (interrupted)", fg="yellow"))
            break

        line = raw.strip()
        if not line:
            continue

        lines_read += 1

        if line.lower() in EXIT_TOKENS:
            exited_via = "/exit"
            out(click.style("  Goodbye.", dim=True))
            break

        # Echo-only stub: future tasks dispatch into the slash registry.
        out(f"  echo: {line}")

    return StubAppResult(lines_read=lines_read, exited_via=exited_via)


__all__ = [
    "DEFAULT_PROMPT",
    "EXIT_TOKENS",
    "EchoFn",
    "InputProvider",
    "StubAppResult",
    "build_status_line",
    "run_workbench_app",
]
