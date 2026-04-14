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

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable

import click

from cli.branding import get_agentlab_version, render_startup_banner
from cli.workbench_app import theme
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.status_bar import StatusBar, render_snapshot, snapshot_from_workspace

if TYPE_CHECKING:
    from cli.sessions import Session, SessionStore


InputProvider = Callable[[str], str]
"""Callable that returns the next line of input given a prompt string.

Raises ``EOFError`` or ``KeyboardInterrupt`` to end the loop (matching the
built-in ``input()`` contract). Tests inject a generator-backed provider.
"""

EchoFn = Callable[[str], None]
"""Write one line to the transcript. Defaults to :func:`click.echo`."""

DEFAULT_PROMPT = "agentlab> "
EXIT_TOKENS = frozenset({"/exit", "/quit", ":q"})
RESUME_HINT_MAX_AGE_SECONDS = 24 * 60 * 60
"""Cap for the '/resume' startup hint: sessions older than 24h stay quiet."""


@dataclass(frozen=True)
class StubAppResult:
    """Return value for the stub loop — useful for assertions in tests."""

    lines_read: int
    exited_via: str  # "/exit", "eof", "interrupt"
    interrupts: int = 0


def build_status_line(workspace: Any | None, *, color: bool = True) -> str:
    """Render the one-line status shown under the banner.

    Thin wrapper around :mod:`cli.workbench_app.status_bar` that the banner
    uses for its one-shot render. Long-lived callers should hold a
    :class:`StatusBar` instance and call :meth:`StatusBar.render` so state
    can be patched reactively as events arrive.
    """
    snapshot = snapshot_from_workspace(workspace)
    return render_snapshot(snapshot, color=color)


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
    echo(theme.workspace("  AgentLab Workbench"))
    echo(f"  [{build_status_line(workspace)}]")
    echo("  Type /help for commands, /exit to leave. (stub)")
    echo("")


def _format_age(seconds: float) -> str:
    """Turn a delta in seconds into a compact "3h ago" style string."""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = int(seconds // 60)
        return f"{minutes}m ago"
    if seconds < RESUME_HINT_MAX_AGE_SECONDS:
        hours = int(seconds // 3600)
        return f"{hours}h ago"
    days = int(seconds // 86400)
    return f"{days}d ago"


def resume_hint(
    store: "SessionStore | None",
    *,
    current: "Session | None" = None,
    max_age_seconds: float = RESUME_HINT_MAX_AGE_SECONDS,
    now: float | None = None,
) -> str | None:
    """Return a one-line ``/resume`` tip when a recent previous session exists.

    ``None`` when there's no store, no prior session, or the latest session
    is older than ``max_age_seconds`` / is the current one. Used by the
    startup banner; extracted as a pure helper so tests don't need to stand
    up the full loop.
    """
    if store is None:
        return None
    try:
        latest = store.latest()
    except Exception:  # pragma: no cover — defensive
        return None
    if latest is None:
        return None
    if current is not None and latest.session_id == current.session_id:
        return None
    now_ts = time.time() if now is None else now
    age = now_ts - (latest.updated_at or 0.0)
    if age > max_age_seconds:
        return None
    title = latest.title or latest.session_id
    return f"  Tip: /resume to continue \"{title}\" ({_format_age(age)})"


def run_workbench_app(
    workspace: Any | None = None,
    *,
    input_provider: InputProvider | None = None,
    echo: EchoFn | None = None,
    prompt: str = DEFAULT_PROMPT,
    show_banner: bool = True,
    cancellation: CancellationToken | None = None,
    session_store: "SessionStore | None" = None,
    session: "Session | None" = None,
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
        hint = resume_hint(session_store, current=session)
        if hint is not None:
            out(theme.meta(hint))
            out("")

    token = cancellation if cancellation is not None else CancellationToken()
    lines_read = 0
    interrupts = 0
    exited_via = "eof"
    while True:
        try:
            raw = reader(prompt)
        except EOFError:
            exited_via = "eof"
            out("")
            break
        except KeyboardInterrupt:
            # T16 double-ctrl-c semantics:
            #   1st press with an active tool call → cancel it.
            #   1st press at idle → warn the user to press again.
            #   2nd consecutive press (no successful input between) → exit.
            if token.active:
                token.cancel()
                interrupts += 1
                out("")
                out(theme.warning(
                    "  (cancelled active tool call — press ctrl-c again to exit)"
                ))
                continue
            interrupts += 1
            if interrupts >= 2:
                exited_via = "interrupt"
                out("")
                out(theme.warning("  (interrupted)"))
                break
            out("")
            out(theme.warning("  (press ctrl-c again to exit, or /exit)"))
            continue

        # A successful read resets the interrupt streak so the user can
        # recover from a stray ctrl-c without getting forced out.
        interrupts = 0
        token.reset()

        line = raw.strip()
        if not line:
            continue

        lines_read += 1

        if line.lower() in EXIT_TOKENS:
            exited_via = "/exit"
            out(theme.meta("  Goodbye."))
            break

        # Echo-only stub: future tasks dispatch into the slash registry.
        out(f"  echo: {line}")

    return StubAppResult(
        lines_read=lines_read,
        exited_via=exited_via,
        interrupts=interrupts,
    )


__all__ = [
    "DEFAULT_PROMPT",
    "EXIT_TOKENS",
    "RESUME_HINT_MAX_AGE_SECONDS",
    "EchoFn",
    "InputProvider",
    "StubAppResult",
    "build_status_line",
    "resume_hint",
    "run_workbench_app",
]
