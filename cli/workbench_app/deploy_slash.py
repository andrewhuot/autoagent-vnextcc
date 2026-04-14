"""`/deploy` slash command — streams ``agentlab deploy`` into the transcript.

T12 follows the `/eval` (T09) / `/optimize` (T10) streaming pattern, with one
distinguishing rule: deployment mutates shared state, so the handler always
prompts the user for an explicit ``y/N`` confirmation before spawning the
subprocess. The confirmation is bypassed in two cases:

- ``--dry-run`` is on the args list (no state change, safe to run).
- The user already passed ``-y`` / ``--yes``; they've opted into the advanced
  flow and we respect it.

When the prompt returns ``y`` (case-insensitive), the handler appends ``-y``
to the subprocess args so ``runner.deploy`` does not re-prompt through
:class:`PermissionManager`. Anything else cancels quietly.

The subprocess runner and the prompter are injectable seams so tests never
spawn a real process or block on ``input()``.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Sequence

import click

from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.slash import SlashContext
from cli.workbench_render import format_workbench_event


StreamEvent = dict[str, Any]
"""One JSON event emitted by a stream-json subprocess."""

StreamRunner = Callable[[Sequence[str]], Iterator[StreamEvent]]
"""Given ``(args,)`` yield parsed JSON events until the process exits.

Raise :class:`DeployCommandError` for non-zero exits. Tests inject a generator
in place of the real subprocess.
"""

Prompter = Callable[[str], bool]
"""Renders the confirmation message and returns ``True`` iff the user typed ``y``.

The default implementation uses :func:`click.confirm`; tests inject a lambda
that returns a canned decision.
"""


class DeployCommandError(RuntimeError):
    """Raised by a :data:`StreamRunner` when the subprocess fails."""


@dataclass(frozen=True)
class DeploySummary:
    """Counters the `/deploy` handler uses to build the `onDone` result line."""

    events: int = 0
    phases_completed: int = 0
    artifacts: tuple[str, ...] = ()
    warnings: int = 0
    errors: int = 0
    next_action: str | None = None
    strategy: str | None = None


# ---------------------------------------------------------------------------
# Default seams
# ---------------------------------------------------------------------------


def _default_stream_runner(args: Sequence[str]) -> Iterator[StreamEvent]:
    """Spawn ``agentlab deploy`` and yield stream-json events line by line.

    ``--output-format stream-json`` is appended automatically so callers
    don't have to remember the flag.
    """
    cmd: list[str] = [
        sys.executable,
        "-m",
        "runner",
        "deploy",
        *args,
        "--output-format",
        "stream-json",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"event": "warning", "message": line}
        exit_code = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    if exit_code != 0:
        raise DeployCommandError(
            f"deploy exited with status {exit_code}"
        )


def _default_prompter(message: str) -> bool:
    """Block on ``click.confirm`` with a default of ``False``."""
    return click.confirm(message, default=False, show_default=True)


# ---------------------------------------------------------------------------
# Argument inspection
# ---------------------------------------------------------------------------


_CONFIRM_SKIP_FLAGS: frozenset[str] = frozenset({"-y", "--yes"})
_DRY_RUN_FLAG = "--dry-run"


def _infer_strategy(args: Sequence[str]) -> str:
    """Guess the strategy the user will run with, for the confirmation prompt.

    Mirrors ``runner.deploy``'s positional-vs-flag resolution: the positional
    ``workflow`` argument overrides ``--strategy`` when set to ``canary``,
    ``immediate``, or ``release`` (which maps to ``immediate``).
    """
    strategy = "canary"
    skip = False
    for index, token in enumerate(args):
        if skip:
            skip = False
            continue
        if token == "--strategy" and index + 1 < len(args):
            strategy = args[index + 1]
            skip = True
        elif token.startswith("--strategy="):
            strategy = token.split("=", 1)[1]
        elif token in ("canary", "immediate"):
            strategy = token
        elif token == "release":
            strategy = "immediate"
    return strategy


def _is_preconfirmed(args: Sequence[str]) -> bool:
    """Return ``True`` when the user already opted into non-interactive execution."""
    return any(token in _CONFIRM_SKIP_FLAGS for token in args)


def _is_dry_run(args: Sequence[str]) -> bool:
    return _DRY_RUN_FLAG in args


def _parse_args(args: Sequence[str]) -> list[str]:
    """Pass through ``deploy`` args — all flags are already native."""
    return list(args)


# ---------------------------------------------------------------------------
# Event → transcript line rendering
# ---------------------------------------------------------------------------


def _render_event(event: StreamEvent) -> str | None:
    event_name = str(event.get("event", ""))
    if not event_name:
        return None
    payload = {k: v for k, v in event.items() if k != "event"}
    return format_workbench_event(event_name, payload)


def _summarise(
    events: Iterable[StreamEvent], *, strategy: str | None
) -> Iterator[tuple[StreamEvent, DeploySummary]]:
    counters = {
        "events": 0,
        "phases_completed": 0,
        "warnings": 0,
        "errors": 0,
    }
    artifacts: list[str] = []
    next_action: str | None = None
    for event in events:
        counters["events"] += 1
        name = event.get("event")
        if name == "phase_completed":
            counters["phases_completed"] += 1
        elif name == "artifact_written":
            path = event.get("path") or event.get("message")
            if path:
                artifacts.append(str(path))
        elif name == "warning":
            counters["warnings"] += 1
        elif name == "error":
            counters["errors"] += 1
        elif name == "next_action":
            message = event.get("message")
            if message:
                next_action = str(message)
        yield event, DeploySummary(
            events=counters["events"],
            phases_completed=counters["phases_completed"],
            artifacts=tuple(artifacts),
            warnings=counters["warnings"],
            errors=counters["errors"],
            next_action=next_action,
            strategy=strategy,
        )


def _format_summary(summary: DeploySummary) -> str:
    parts: list[str] = [f"{summary.events} events"]
    if summary.strategy:
        parts.append(f"strategy={summary.strategy}")
    if summary.phases_completed:
        label = "phase" if summary.phases_completed == 1 else "phases"
        parts.append(f"{summary.phases_completed} {label}")
    if summary.artifacts:
        parts.append(f"{len(summary.artifacts)} artifacts")
    if summary.warnings:
        parts.append(f"{summary.warnings} warnings")
    if summary.errors:
        parts.append(click.style(f"{summary.errors} errors", fg="red"))
    status = "failed" if summary.errors else "complete"
    return click.style(
        f"  /deploy {status} — {', '.join(parts)}",
        fg=("red" if summary.errors else "green"),
        bold=True,
    )


# ---------------------------------------------------------------------------
# Handler + registration
# ---------------------------------------------------------------------------


def make_deploy_handler(
    runner: StreamRunner | None = None,
    prompter: Prompter | None = None,
) -> Callable[..., OnDoneResult]:
    """Return a slash handler closed over ``runner`` and ``prompter``."""
    active_runner = runner or _default_stream_runner
    active_prompter = prompter or _default_prompter

    def _handle_deploy(ctx: SlashContext, *args: str) -> OnDoneResult:
        stream_args = _parse_args(args)
        strategy = _infer_strategy(stream_args)
        echo = ctx.echo

        needs_confirm = not (
            _is_preconfirmed(stream_args) or _is_dry_run(stream_args)
        )
        if needs_confirm:
            message = f"  Deploy with strategy={strategy}? (y/N)"
            try:
                confirmed = active_prompter(message)
            except (KeyboardInterrupt, EOFError):
                confirmed = False
            if not confirmed:
                cancelled = click.style(
                    "  /deploy cancelled — no changes made.", fg="yellow"
                )
                echo(cancelled)
                return on_done(result=cancelled, display="skip")
            stream_args.append("-y")

        echo(click.style(
            f"  /deploy starting — agentlab deploy {shlex.join(stream_args)}".rstrip(),
            fg="cyan",
        ))

        try:
            final_summary = DeploySummary(strategy=strategy)
            for event, summary in _summarise(
                active_runner(stream_args), strategy=strategy
            ):
                final_summary = summary
                line = _render_event(event)
                if line is not None:
                    echo(line)
        except DeployCommandError as exc:
            echo(click.style(f"  /deploy failed: {exc}", fg="red", bold=True))
            return on_done(
                result=f"  /deploy failed: {exc}",
                display="skip",
                meta_messages=(str(exc),),
            )
        except FileNotFoundError as exc:
            echo(click.style(f"  /deploy failed: {exc}", fg="red", bold=True))
            return on_done(result=None, display="skip")

        summary_line = _format_summary(final_summary)
        meta: list[str] = []
        if final_summary.next_action:
            meta.append(f"Suggested next: {final_summary.next_action}")
        for path in final_summary.artifacts[-3:]:
            meta.append(f"Artifact: {path}")
        return on_done(
            result=summary_line,
            display="user",
            meta_messages=tuple(meta),
        )

    return _handle_deploy


def build_deploy_command(
    runner: StreamRunner | None = None,
    prompter: Prompter | None = None,
    *,
    description: str = "Deploy the active config (prompts before mutating state)",
) -> LocalCommand:
    """Build the :class:`LocalCommand` for `/deploy`."""
    return LocalCommand(
        name="deploy",
        description=description,
        handler=make_deploy_handler(runner, prompter),
        source="builtin",
    )


__all__ = [
    "DeployCommandError",
    "DeploySummary",
    "Prompter",
    "StreamEvent",
    "StreamRunner",
    "build_deploy_command",
    "make_deploy_handler",
]
