"""Tests for cli/workbench_app/optimize_slash.py — the `/optimize` streaming handler."""

from __future__ import annotations

import re
from typing import Iterator, Sequence

import pytest

from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.optimize_slash import (
    OptimizeCommandError,
    OptimizeSummary,
    _format_summary,
    _parse_args,
    _render_event,
    _summarise,
    build_optimize_command,
    make_optimize_handler,
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
# _parse_args — currently a pass-through; guard against accidental rewrites.
# ---------------------------------------------------------------------------


def test_parse_args_passes_through_cycles() -> None:
    assert _parse_args(["--cycles", "3"]) == ["--cycles", "3"]


def test_parse_args_passes_through_mode() -> None:
    assert _parse_args(["--mode", "advanced"]) == ["--mode", "advanced"]


def test_parse_args_handles_continuous_flag() -> None:
    assert _parse_args(["--continuous"]) == ["--continuous"]


def test_parse_args_handles_empty() -> None:
    assert _parse_args([]) == []


def test_parse_args_preserves_order() -> None:
    assert _parse_args(
        ["--cycles", "5", "--mode", "research", "--config", "v007.yaml"]
    ) == ["--cycles", "5", "--mode", "research", "--config", "v007.yaml"]


# ---------------------------------------------------------------------------
# _render_event
# ---------------------------------------------------------------------------


def test_render_event_formats_phase_started() -> None:
    line = _render_event(
        {"event": "phase_started", "phase": "optimize", "message": "running"}
    )
    assert line is not None
    assert "[optimize]" in _strip_ansi(line)
    assert "running" in _strip_ansi(line)


def test_render_event_formats_cycle_phase() -> None:
    line = _render_event(
        {"event": "phase_completed", "phase": "optimize-cycle", "message": "Cycle 1 keep (+0.05)"}
    )
    assert line is not None
    assert "Cycle 1 keep" in _strip_ansi(line)


def test_render_event_returns_none_for_missing_name() -> None:
    assert _render_event({"message": "hi"}) is None


def test_render_event_returns_none_for_unknown_event() -> None:
    assert _render_event({"event": "nope"}) is None


# ---------------------------------------------------------------------------
# _summarise
# ---------------------------------------------------------------------------


def test_summarise_counts_cycles_and_non_cycle_phases_separately() -> None:
    events = [
        {"event": "phase_started", "phase": "optimize"},
        {"event": "phase_completed", "phase": "optimize-cycle", "message": "Cycle 1 keep"},
        {"event": "phase_completed", "phase": "optimize-cycle", "message": "Cycle 2 discard"},
        {"event": "phase_completed", "phase": "optimize", "message": "done"},
        {"event": "artifact_written", "path": "/tmp/cycle.json"},
        {"event": "warning", "message": "slow"},
        {"event": "error", "message": "boom"},
        {"event": "next_action", "message": "agentlab status"},
    ]
    summary = list(_summarise(events))[-1][1]
    assert summary.events == 8
    assert summary.cycles_completed == 2
    assert summary.phases_completed == 3  # two cycle phases + one wrapper
    assert summary.artifacts == ("/tmp/cycle.json",)
    assert summary.warnings == 1
    assert summary.errors == 1
    assert summary.next_action == "agentlab status"


def test_summarise_handles_empty_stream() -> None:
    assert list(_summarise([])) == []


def test_summarise_artifact_without_path_falls_back_to_message() -> None:
    events = [{"event": "artifact_written", "message": "inline"}]
    summary = list(_summarise(events))[-1][1]
    assert summary.artifacts == ("inline",)


def test_summarise_ignores_phase_completed_without_cycle_phase() -> None:
    events = [{"event": "phase_completed", "phase": "optimize"}]
    summary = list(_summarise(events))[-1][1]
    assert summary.cycles_completed == 0
    assert summary.phases_completed == 1


# ---------------------------------------------------------------------------
# _format_summary
# ---------------------------------------------------------------------------


def test_format_summary_green_on_clean_run() -> None:
    line = _format_summary(OptimizeSummary(events=4, cycles_completed=3))
    plain = _strip_ansi(line)
    assert "/optimize complete" in plain
    assert "4 events" in plain
    assert "3 cycles" in plain


def test_format_summary_singular_cycle_label() -> None:
    line = _format_summary(OptimizeSummary(events=2, cycles_completed=1))
    plain = _strip_ansi(line)
    assert "1 cycle" in plain
    assert "1 cycles" not in plain


def test_format_summary_red_on_errors() -> None:
    line = _format_summary(OptimizeSummary(events=2, errors=1))
    plain = _strip_ansi(line)
    assert "/optimize failed" in plain
    assert "1 errors" in plain


def test_format_summary_lists_warnings_and_artifacts() -> None:
    line = _format_summary(
        OptimizeSummary(events=5, artifacts=("a", "b"), warnings=2)
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


def _install_optimize(ctx: SlashContext, runner) -> None:
    assert ctx.registry is not None
    ctx.registry.register(build_optimize_command(runner=runner))


def test_handler_streams_events_then_emits_summary(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [
            {"event": "phase_started", "phase": "optimize", "message": "go"},
            {"event": "phase_completed", "phase": "optimize-cycle", "message": "Cycle 1 keep"},
            {"event": "phase_completed", "phase": "optimize", "message": "run complete"},
            {"event": "artifact_written", "artifact": "log", "path": "/tmp/log.tsv"},
            {"event": "next_action", "message": "agentlab status"},
        ]
    )
    _install_optimize(ctx, runner)

    result = dispatch(ctx, "/optimize")

    assert isinstance(result, DispatchResult)
    assert result.handled is True
    assert result.error is None
    assert runner.calls == [[]]
    assert any("/optimize starting" in _strip_ansi(l) for l in echo.lines)
    plain = "\n".join(echo.plain)
    assert "[optimize] starting: go" in plain
    assert "Cycle 1 keep" in plain
    assert "/tmp/log.tsv" in plain
    assert "/optimize complete" in plain
    assert "1 cycle" in plain
    assert any("Suggested next" in l for l in echo.plain)


def test_handler_forwards_args_verbatim(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [{"event": "phase_completed", "phase": "optimize-cycle", "message": "Cycle 1 keep"}]
    )
    _install_optimize(ctx, runner)

    dispatch(ctx, "/optimize --cycles 3 --mode advanced")

    assert runner.calls == [["--cycles", "3", "--mode", "advanced"]]


def test_handler_reports_subprocess_failure(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _failing_runner(OptimizeCommandError("exit 2"))
    _install_optimize(ctx, runner)

    result = dispatch(ctx, "/optimize")

    assert result.error is None
    assert any("/optimize failed" in _strip_ansi(l) for l in echo.lines)
    assert result.display == "skip"
    assert result.raw_result is not None
    assert "/optimize failed" in result.raw_result


def test_handler_reports_missing_binary(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _failing_runner(FileNotFoundError("agentlab"))
    _install_optimize(ctx, runner)

    result = dispatch(ctx, "/optimize")

    assert any("/optimize failed" in _strip_ansi(l) for l in echo.lines)
    assert result.raw_result is None
    assert result.display == "skip"


def test_handler_surfaces_warnings_and_errors(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [
            {"event": "phase_started", "phase": "optimize"},
            {"event": "warning", "message": "slow"},
            {"event": "error", "message": "oops"},
            {"event": "phase_completed", "phase": "optimize-cycle", "message": "Cycle 1 crash"},
        ]
    )
    _install_optimize(ctx, runner)

    result = dispatch(ctx, "/optimize")

    plain = "\n".join(echo.plain)
    assert "/optimize failed" in plain
    assert "1 errors" in plain
    assert "1 warnings" in plain
    assert isinstance(result, DispatchResult)


def test_make_optimize_handler_uses_default_runner_when_none_passed() -> None:
    handler = make_optimize_handler()
    # Don't actually invoke the default runner (would spawn a real
    # subprocess). Just confirm the closure wiring succeeded.
    assert callable(handler)


def test_handler_includes_last_artifacts_in_meta(ctx: SlashContext) -> None:
    runner = _fake_runner(
        [
            {"event": "artifact_written", "path": f"/tmp/c{i}.json"}
            for i in range(5)
        ]
    )
    _install_optimize(ctx, runner)

    result = dispatch(ctx, "/optimize")

    assert isinstance(result, DispatchResult)
    meta_strs = [_strip_ansi(m) for m in result.meta_messages]
    artifact_meta = [m for m in meta_strs if m.startswith("Artifact:")]
    assert len(artifact_meta) == 3
    assert "/tmp/c4.json" in artifact_meta[-1]


def test_default_registry_wires_optimize_command() -> None:
    registry = build_builtin_registry()
    cmd = registry.get("/optimize")
    assert cmd is not None
    assert cmd.kind == "local"
    assert cmd.source == "builtin"


def test_summary_dataclass_is_frozen() -> None:
    summary = OptimizeSummary(events=1)
    with pytest.raises(Exception):
        summary.events = 2  # type: ignore[misc]
