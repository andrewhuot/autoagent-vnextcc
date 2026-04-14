"""Tests for cli/workbench_app/eval_slash.py — the `/eval` streaming handler."""

from __future__ import annotations

import re
from typing import Iterator, Sequence

import pytest

from cli.workbench_app.commands import CommandRegistry, OnDoneResult
from cli.workbench_app.eval_slash import (
    EvalCommandError,
    EvalSummary,
    _format_summary,
    _parse_args,
    _render_event,
    _summarise,
    build_eval_command,
    make_eval_handler,
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


def test_parse_args_passes_through_plain_flags() -> None:
    assert _parse_args(["--category", "safety"]) == ["--category", "safety"]


def test_parse_args_translates_run_id_to_config() -> None:
    assert _parse_args(["--run-id", "v003"]) == ["--config", "v003"]


def test_parse_args_handles_mixed_args() -> None:
    assert _parse_args(
        ["--real-agent", "--run-id", "v004", "--output", "x.json"]
    ) == ["--real-agent", "--config", "v004", "--output", "x.json"]


def test_parse_args_preserves_trailing_run_id_without_value() -> None:
    # When the user types `/eval --run-id` with no value we keep the flag so
    # the subprocess surfaces its own "Missing argument" error.
    assert _parse_args(["--run-id"]) == ["--run-id"]


def test_parse_args_handles_empty() -> None:
    assert _parse_args([]) == []


# ---------------------------------------------------------------------------
# _render_event
# ---------------------------------------------------------------------------


def test_render_event_formats_phase_started() -> None:
    line = _render_event(
        {"event": "phase_started", "phase": "eval", "message": "running"}
    )
    assert line is not None
    assert "[eval]" in _strip_ansi(line)
    assert "running" in _strip_ansi(line)


def test_render_event_formats_artifact_written() -> None:
    line = _render_event(
        {"event": "artifact_written", "artifact": "x", "path": "/tmp/x.json"}
    )
    assert line is not None
    assert "/tmp/x.json" in _strip_ansi(line)


def test_render_event_returns_none_for_missing_name() -> None:
    assert _render_event({"message": "hello"}) is None


def test_render_event_returns_none_for_unknown_event() -> None:
    assert _render_event({"event": "nope", "message": "x"}) is None


# ---------------------------------------------------------------------------
# _summarise
# ---------------------------------------------------------------------------


def test_summarise_counts_phases_artifacts_warnings_errors() -> None:
    events = [
        {"event": "phase_started", "phase": "eval"},
        {"event": "phase_completed", "phase": "eval"},
        {"event": "artifact_written", "path": "/tmp/a.json"},
        {"event": "warning", "message": "slow"},
        {"event": "error", "message": "boom"},
        {"event": "next_action", "message": "agentlab optimize"},
    ]
    summary = list(_summarise(events))[-1][1]
    assert summary.events == 6
    assert summary.phases_completed == 1
    assert summary.artifacts == ("/tmp/a.json",)
    assert summary.warnings == 1
    assert summary.errors == 1
    assert summary.next_action == "agentlab optimize"


def test_summarise_handles_empty_stream() -> None:
    assert list(_summarise([])) == []


def test_summarise_artifact_without_path_falls_back_to_message() -> None:
    events = [{"event": "artifact_written", "message": "inline"}]
    summary = list(_summarise(events))[-1][1]
    assert summary.artifacts == ("inline",)


# ---------------------------------------------------------------------------
# _format_summary
# ---------------------------------------------------------------------------


def test_format_summary_green_on_clean_run() -> None:
    line = _format_summary(EvalSummary(events=3, phases_completed=1))
    plain = _strip_ansi(line)
    assert "/eval complete" in plain
    assert "3 events" in plain


def test_format_summary_red_on_errors() -> None:
    line = _format_summary(EvalSummary(events=2, errors=1))
    plain = _strip_ansi(line)
    assert "/eval failed" in plain
    assert "1 errors" in plain


def test_format_summary_lists_warnings_and_artifacts() -> None:
    line = _format_summary(
        EvalSummary(events=5, artifacts=("a", "b"), warnings=2)
    )
    plain = _strip_ansi(line)
    assert "2 artifacts" in plain
    assert "2 warnings" in plain


# ---------------------------------------------------------------------------
# Handler integration — exercised via dispatch()
# ---------------------------------------------------------------------------


@pytest.fixture
def echo() -> _EchoCapture:
    return _EchoCapture()


@pytest.fixture
def ctx(echo: _EchoCapture) -> SlashContext:
    registry = CommandRegistry()
    return SlashContext(echo=echo, registry=registry)


def _install_eval(ctx: SlashContext, runner) -> None:
    assert ctx.registry is not None
    ctx.registry.register(build_eval_command(runner=runner))


def test_handler_streams_events_then_emits_summary(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [
            {"event": "phase_started", "phase": "eval", "message": "go"},
            {"event": "phase_completed", "phase": "eval", "message": "ok"},
            {"event": "artifact_written", "artifact": "r", "path": "/tmp/r.json"},
            {"event": "next_action", "message": "agentlab optimize"},
        ]
    )
    _install_eval(ctx, runner)

    result = dispatch(ctx, "/eval")

    assert isinstance(result, DispatchResult)
    assert result.handled is True
    assert result.error is None
    assert runner.calls == [[]]  # no args
    # Start banner + 4 event lines + summary = 6 lines, plus meta messages.
    assert any("/eval starting" in _strip_ansi(l) for l in echo.lines)
    plain = "\n".join(echo.plain)
    assert "[eval] starting: go" in plain
    assert "[eval] done: ok" in plain
    assert "/tmp/r.json" in plain
    assert "/eval complete" in plain
    # ``next_action`` surfaces twice: once as an inline event line and once as
    # a meta message on the final summary.
    assert any("Suggested next" in l for l in echo.plain)


def test_handler_forwards_args_and_translates_run_id(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner([{"event": "phase_completed", "phase": "eval"}])
    _install_eval(ctx, runner)

    dispatch(ctx, "/eval --run-id v007 --category safety")

    assert runner.calls == [["--config", "v007", "--category", "safety"]]


def test_handler_reports_subprocess_failure(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _failing_runner(EvalCommandError("exit 2"))
    _install_eval(ctx, runner)

    result = dispatch(ctx, "/eval")

    assert result.error is None  # handler caught the error gracefully
    assert any("/eval failed" in _strip_ansi(l) for l in echo.lines)
    # display="skip" means nothing extra was echoed after the failure line.
    assert result.display == "skip"
    assert result.raw_result is not None
    assert "/eval failed" in result.raw_result


def test_handler_reports_missing_binary(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _failing_runner(FileNotFoundError("agentlab"))
    _install_eval(ctx, runner)

    result = dispatch(ctx, "/eval")

    assert any("/eval failed" in _strip_ansi(l) for l in echo.lines)
    assert result.raw_result is None
    assert result.display == "skip"


def test_handler_surfaces_warnings_and_errors(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [
            {"event": "phase_started", "phase": "eval"},
            {"event": "warning", "message": "slow"},
            {"event": "error", "message": "oops"},
            {"event": "phase_completed", "phase": "eval"},
        ]
    )
    _install_eval(ctx, runner)

    result = dispatch(ctx, "/eval")

    plain = "\n".join(echo.plain)
    assert "/eval failed" in plain
    assert "1 errors" in plain
    assert "1 warnings" in plain
    assert isinstance(result, DispatchResult)


def test_make_eval_handler_uses_default_runner_when_none_passed() -> None:
    handler = make_eval_handler()
    # We don't actually invoke the default runner here (would spawn a real
    # subprocess). Just assert the closure wiring succeeded and is callable.
    assert callable(handler)


def test_handler_includes_last_artifacts_in_meta(ctx: SlashContext) -> None:
    runner = _fake_runner(
        [
            {"event": "artifact_written", "path": f"/tmp/a{i}.json"}
            for i in range(5)
        ]
    )
    _install_eval(ctx, runner)

    result = dispatch(ctx, "/eval")

    # Only the last three artifacts are echoed in the meta block.
    assert isinstance(result, DispatchResult)
    meta_strs = [_strip_ansi(m) for m in result.meta_messages]
    artifact_meta = [m for m in meta_strs if m.startswith("Artifact:")]
    assert len(artifact_meta) == 3
    assert "/tmp/a4.json" in artifact_meta[-1]


def test_default_registry_wires_eval_command() -> None:
    registry = build_builtin_registry()
    eval_cmd = registry.get("/eval")
    assert eval_cmd is not None
    assert eval_cmd.kind == "local"
    assert eval_cmd.source == "builtin"
