"""Tests for cli/workbench_app/improve_slash.py — the `/improve` streaming handler.

The `/improve` slash command is a thin passthrough that forwards
``/improve <sub> [args...]`` to ``agentlab improve <sub> [args...]`` and
streams stream-json events into the transcript. It mirrors the subprocess
streaming pattern established by ``/eval``, ``/optimize``, and ``/deploy``.
"""

from __future__ import annotations

import re
from typing import Iterator, Sequence

import pytest

from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.improve_slash import (
    ImproveCommandError,
    ImproveSummary,
    _format_summary,
    _parse_args,
    _render_event,
    _summarise,
    build_improve_command,
    make_improve_handler,
)
from cli.workbench_app.slash import (
    DispatchResult,
    SlashContext,
    build_builtin_registry,
    dispatch,
)


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


class _EchoCapture:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)

    @property
    def plain(self) -> list[str]:
        return [_strip_ansi(l) for l in self.lines]


def _fake_runner(events: Sequence[dict]) -> "callable":
    """Return a StreamRunner that yields the given events and records args."""

    calls: list[Sequence[str]] = []

    def _run(args: Sequence[str]) -> Iterator[dict]:
        calls.append(list(args))
        yield from events

    _run.calls = calls  # type: ignore[attr-defined]
    return _run


def _failing_runner(exc: Exception) -> "callable":
    def _run(args: Sequence[str]) -> Iterator[dict]:
        if False:  # pragma: no cover — generator
            yield {}
        raise exc

    return _run


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------


def test_parse_args_requires_subcommand() -> None:
    with pytest.raises(ImproveCommandError):
        _parse_args([])


def test_parse_args_rejects_unknown_subcommand() -> None:
    with pytest.raises(ImproveCommandError):
        _parse_args(["not-a-thing"])


def test_parse_args_passes_subcommand_and_trailing_args() -> None:
    assert _parse_args(["run", "configs/foo.yaml"]) == ["run", "configs/foo.yaml"]


def test_parse_args_allows_each_known_subcommand() -> None:
    for sub in ("run", "accept", "measure", "diff", "lineage", "list", "show"):
        assert _parse_args([sub]) == [sub]


# ---------------------------------------------------------------------------
# _render_event
# ---------------------------------------------------------------------------


def test_render_event_formats_phase_started() -> None:
    line = _render_event(
        {"event": "phase_started", "phase": "improve", "message": "go"}
    )
    assert line is not None
    assert "improve" in _strip_ansi(line)


def test_render_event_returns_none_for_missing_name() -> None:
    assert _render_event({"message": "hello"}) is None


# ---------------------------------------------------------------------------
# _summarise
# ---------------------------------------------------------------------------


def test_summarise_counts_artifacts_warnings_errors() -> None:
    events = [
        {"event": "phase_started", "phase": "improve"},
        {"event": "phase_completed", "phase": "improve"},
        {"event": "artifact_written", "path": "/tmp/a.json"},
        {"event": "warning", "message": "slow"},
        {"event": "error", "message": "boom"},
        {"event": "next_action", "message": "agentlab improve accept ..."},
    ]
    summary = list(_summarise(events))[-1][1]
    assert summary.events == 6
    assert summary.phases_completed == 1
    assert summary.artifacts == ("/tmp/a.json",)
    assert summary.warnings == 1
    assert summary.errors == 1
    assert summary.next_action == "agentlab improve accept ..."


def test_summarise_handles_empty_stream() -> None:
    assert list(_summarise([])) == []


# ---------------------------------------------------------------------------
# _format_summary
# ---------------------------------------------------------------------------


def test_format_summary_green_on_clean_run() -> None:
    line = _format_summary(ImproveSummary(events=3, phases_completed=1))
    plain = _strip_ansi(line)
    assert "/improve complete" in plain
    assert "3 events" in plain


def test_format_summary_red_on_errors() -> None:
    line = _format_summary(ImproveSummary(events=2, errors=1))
    plain = _strip_ansi(line)
    assert "/improve failed" in plain
    assert "1 errors" in plain


# ---------------------------------------------------------------------------
# Handler integration — via dispatch()
# ---------------------------------------------------------------------------


@pytest.fixture
def echo() -> _EchoCapture:
    return _EchoCapture()


@pytest.fixture
def ctx(echo: _EchoCapture) -> SlashContext:
    registry = CommandRegistry()
    return SlashContext(echo=echo, registry=registry)


def _install_improve(ctx: SlashContext, runner) -> None:
    assert ctx.registry is not None
    ctx.registry.register(build_improve_command(runner=runner))


def test_improve_handler_registered() -> None:
    registry = CommandRegistry()
    cmd = build_improve_command()
    registry.register(cmd)
    assert registry.get("improve") is cmd


def test_improve_forwards_first_arg_as_subcommand(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner([{"event": "phase_completed", "phase": "improve"}])
    _install_improve(ctx, runner)

    dispatch(ctx, "/improve run configs/foo.yaml")

    assert runner.calls == [["run", "configs/foo.yaml"]]


def test_improve_streams_events_then_summary(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [
            {"event": "phase_started", "phase": "improve", "message": "go"},
            {"event": "phase_completed", "phase": "improve", "message": "ok"},
            {"event": "artifact_written", "artifact": "r", "path": "/tmp/r.json"},
            {"event": "next_action", "message": "agentlab improve accept foo"},
        ]
    )
    _install_improve(ctx, runner)

    result = dispatch(ctx, "/improve run")

    assert isinstance(result, DispatchResult)
    assert result.handled is True
    assert result.error is None
    assert runner.calls == [["run"]]
    plain = "\n".join(echo.plain)
    assert "/improve starting" in plain
    assert "/tmp/r.json" in plain
    assert "/improve complete" in plain
    assert any("Suggested next" in l for l in echo.plain)


def test_improve_missing_subcommand_reports_usage(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner([])
    _install_improve(ctx, runner)

    result = dispatch(ctx, "/improve")

    assert runner.calls == []  # never invoked
    plain = "\n".join(echo.plain)
    assert "/improve" in plain
    assert "usage" in plain.lower() or "missing" in plain.lower()
    assert result.display == "skip"


def test_improve_unknown_subcommand_reports_usage(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner([])
    _install_improve(ctx, runner)

    result = dispatch(ctx, "/improve bogus")

    assert runner.calls == []
    plain = "\n".join(echo.plain)
    assert "bogus" in plain or "usage" in plain.lower()
    assert result.display == "skip"


def test_improve_reports_subprocess_failure(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _failing_runner(ImproveCommandError("exit 2"))
    _install_improve(ctx, runner)

    result = dispatch(ctx, "/improve run")

    assert result.error is None
    assert any("/improve failed" in _strip_ansi(l) for l in echo.lines)
    assert result.display == "skip"
    assert result.raw_result is not None
    assert "/improve failed" in result.raw_result


def test_improve_reports_missing_binary(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _failing_runner(FileNotFoundError("agentlab"))
    _install_improve(ctx, runner)

    result = dispatch(ctx, "/improve run")

    assert any("/improve failed" in _strip_ansi(l) for l in echo.lines)
    assert result.raw_result is None
    assert result.display == "skip"


def test_improve_surfaces_warnings_and_errors(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [
            {"event": "phase_started", "phase": "improve"},
            {"event": "warning", "message": "slow"},
            {"event": "error", "message": "oops"},
            {"event": "phase_completed", "phase": "improve"},
        ]
    )
    _install_improve(ctx, runner)

    dispatch(ctx, "/improve run")

    plain = "\n".join(echo.plain)
    assert "/improve failed" in plain
    assert "1 errors" in plain
    assert "1 warnings" in plain


def test_make_improve_handler_uses_default_runner_when_none_passed() -> None:
    handler = make_improve_handler()
    assert callable(handler)


def test_improve_forwards_trailing_args_verbatim(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner([{"event": "phase_completed", "phase": "improve"}])
    _install_improve(ctx, runner)

    dispatch(ctx, "/improve diff attempt_abc --verbose")

    assert runner.calls == [["diff", "attempt_abc", "--verbose"]]


def test_default_registry_wires_improve_command() -> None:
    registry = build_builtin_registry()
    improve_cmd = registry.get("/improve")
    assert improve_cmd is not None
    assert improve_cmd.kind == "local"
    assert improve_cmd.source == "builtin"
