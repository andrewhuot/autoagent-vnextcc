"""Tests for cli/workbench_app/build_slash.py — the `/build` streaming handler."""

from __future__ import annotations

import re
from typing import Iterator, Sequence

import pytest

from cli.workbench_app.build_slash import (
    BuildCommandError,
    BuildSummary,
    _event_payload,
    _format_summary,
    _parse_args,
    _render_event,
    _summarise,
    build_build_command,
    make_build_handler,
)
from cli.workbench_app.commands import CommandRegistry
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
# _parse_args — pure pass-through guard
# ---------------------------------------------------------------------------


def test_parse_args_passes_brief_and_flags() -> None:
    assert _parse_args(["Add a tool", "--target", "portable"]) == [
        "Add a tool",
        "--target",
        "portable",
    ]


def test_parse_args_empty() -> None:
    assert _parse_args([]) == []


# ---------------------------------------------------------------------------
# _event_payload — workbench emits {"event": name, "data": {...}}
# ---------------------------------------------------------------------------


def test_event_payload_unwraps_nested_data() -> None:
    event = {"event": "task.started", "data": {"task_id": "t1", "title": "Design"}}
    assert _event_payload(event) == {"task_id": "t1", "title": "Design"}


def test_event_payload_falls_back_to_flat_envelope() -> None:
    event = {"event": "task.started", "task_id": "t1"}
    # No nested ``data`` key — fall back to flat envelope minus ``event``.
    assert _event_payload(event) == {"task_id": "t1"}


def test_event_payload_handles_non_dict_data() -> None:
    event = {"event": "task.started", "data": "oops", "title": "Recovered"}
    # Non-dict ``data`` falls back to flat envelope (renderer still gets title).
    assert _event_payload(event) == {"data": "oops", "title": "Recovered"}


# ---------------------------------------------------------------------------
# _render_event
# ---------------------------------------------------------------------------


def test_render_event_formats_task_started_with_nested_data() -> None:
    line = _render_event(
        {"event": "task.started", "data": {"task_id": "t1", "title": "Design"}}
    )
    assert line is not None
    assert "Design" in _strip_ansi(line)


def test_render_event_formats_run_completed() -> None:
    line = _render_event(
        {"event": "run.completed", "data": {"version": "003"}}
    )
    assert line is not None
    assert "Draft v003" in _strip_ansi(line)


def test_render_event_returns_none_for_missing_event_name() -> None:
    assert _render_event({"data": {"title": "x"}}) is None


def test_render_event_returns_none_for_unknown_event() -> None:
    assert _render_event({"event": "nope", "data": {}}) is None


# ---------------------------------------------------------------------------
# _summarise
# ---------------------------------------------------------------------------


def test_summarise_counts_tasks_iterations_artifacts() -> None:
    events = [
        {"event": "turn.started", "data": {"turn_number": 1}},
        {"event": "task.started", "data": {"task_id": "t1", "title": "Design"}},
        {"event": "task.completed", "data": {"task_id": "t1", "title": "Design"}},
        {"event": "task.completed", "data": {"task_id": "t2", "title": "Config"}},
        {"event": "iteration.started", "data": {"iteration": 1}},
        {
            "event": "artifact.updated",
            "data": {"artifact": {"name": "config.yaml", "path": "/tmp/config.yaml"}},
        },
        {"event": "progress.stall", "data": {}},
        {"event": "run.completed", "data": {"project_id": "p1", "version": "004"}},
    ]
    summary = list(_summarise(events))[-1][1]
    assert summary.events == 8
    assert summary.tasks_completed == 2
    assert summary.iterations == 1
    assert summary.artifacts == ("/tmp/config.yaml",)
    assert summary.warnings == 1  # progress.stall
    assert summary.errors == 0
    assert summary.run_status == "completed"
    assert summary.run_version == "004"
    assert summary.project_id == "p1"


def test_summarise_handles_empty_stream() -> None:
    assert list(_summarise([])) == []


def test_summarise_captures_run_failed_with_reason() -> None:
    events = [
        {
            "event": "run.failed",
            "data": {"failure_reason": "budget exceeded", "project_id": "p9"},
        }
    ]
    summary = list(_summarise(events))[-1][1]
    assert summary.run_status == "failed"
    assert summary.failure_reason == "budget exceeded"
    assert summary.errors == 1  # run.failed counts as an error
    assert summary.project_id == "p9"


def test_summarise_captures_run_cancelled() -> None:
    events = [
        {
            "event": "run.cancelled",
            "data": {"cancel_reason": "user ctrl-c"},
        }
    ]
    summary = list(_summarise(events))[-1][1]
    assert summary.run_status == "cancelled"
    assert summary.failure_reason == "user ctrl-c"
    # Cancellation is not an error — the user chose it.
    assert summary.errors == 0


def test_summarise_counts_explicit_error_events() -> None:
    events = [
        {"event": "error", "data": {"message": "boom"}},
        {"event": "warning", "data": {"message": "slow"}},
    ]
    summary = list(_summarise(events))[-1][1]
    assert summary.errors == 1
    assert summary.warnings == 1


def test_summarise_artifact_falls_back_to_flat_path() -> None:
    events = [{"event": "artifact.updated", "data": {"path": "/tmp/x"}}]
    summary = list(_summarise(events))[-1][1]
    assert summary.artifacts == ("/tmp/x",)


def test_summarise_uses_newest_project_id() -> None:
    events = [
        {"event": "task.started", "data": {"task_id": "a", "project_id": "old"}},
        {"event": "run.completed", "data": {"project_id": "new", "version": "1"}},
    ]
    summary = list(_summarise(events))[-1][1]
    assert summary.project_id == "new"


# ---------------------------------------------------------------------------
# _format_summary
# ---------------------------------------------------------------------------


def test_format_summary_green_with_version_on_clean_run() -> None:
    line = _format_summary(
        BuildSummary(events=10, tasks_completed=4, run_status="completed", run_version="005")
    )
    plain = _strip_ansi(line)
    assert "/build complete (v005)" in plain
    assert "10 events" in plain
    assert "4 tasks" in plain


def test_format_summary_singular_task_label() -> None:
    line = _format_summary(BuildSummary(events=2, tasks_completed=1, run_status="completed"))
    plain = _strip_ansi(line)
    assert "1 task" in plain
    assert "1 tasks" not in plain


def test_format_summary_singular_iteration_label() -> None:
    line = _format_summary(BuildSummary(events=2, iterations=1, run_status="completed"))
    plain = _strip_ansi(line)
    assert "1 iteration" in plain
    assert "1 iterations" not in plain


def test_format_summary_red_on_errors() -> None:
    line = _format_summary(BuildSummary(events=3, errors=1))
    plain = _strip_ansi(line)
    assert "/build failed" in plain
    assert "1 errors" in plain


def test_format_summary_red_on_run_failed_without_explicit_error_count() -> None:
    line = _format_summary(BuildSummary(events=1, run_status="failed"))
    plain = _strip_ansi(line)
    assert "/build failed" in plain


def test_format_summary_shows_cancelled_label() -> None:
    line = _format_summary(BuildSummary(events=2, run_status="cancelled"))
    plain = _strip_ansi(line)
    assert "/build cancelled" in plain


def test_format_summary_lists_warnings_and_artifacts() -> None:
    line = _format_summary(
        BuildSummary(events=5, artifacts=("a", "b", "c"), warnings=2, run_status="completed")
    )
    plain = _strip_ansi(line)
    assert "3 artifacts" in plain
    assert "2 warnings" in plain


# ---------------------------------------------------------------------------
# Handler integration via dispatch()
# ---------------------------------------------------------------------------


@pytest.fixture
def echo() -> _EchoCapture:
    return _EchoCapture()


@pytest.fixture
def ctx(echo: _EchoCapture) -> SlashContext:
    registry = CommandRegistry()
    return SlashContext(echo=echo, registry=registry)


def _install_build(ctx: SlashContext, runner) -> None:
    assert ctx.registry is not None
    ctx.registry.register(build_build_command(runner=runner))


def test_handler_requires_brief(ctx: SlashContext, echo: _EchoCapture) -> None:
    runner = _fake_runner([])
    _install_build(ctx, runner)

    result = dispatch(ctx, "/build")

    assert result.handled is True
    assert result.display == "skip"
    # No subprocess should be attempted.
    assert runner.calls == []  # type: ignore[attr-defined]
    assert any("requires a brief" in _strip_ansi(l) for l in echo.lines)


def test_handler_streams_events_then_emits_summary(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [
            {"event": "turn.started", "data": {"turn_number": 1}},
            {"event": "task.started", "data": {"task_id": "t1", "title": "Design"}},
            {"event": "task.completed", "data": {"task_id": "t1", "title": "Design"}},
            {"event": "run.completed", "data": {"project_id": "p1", "version": "004"}},
        ]
    )
    _install_build(ctx, runner)

    result = dispatch(ctx, "/build \"Add a flight tool\"")

    assert isinstance(result, DispatchResult)
    assert result.handled is True
    assert result.error is None
    assert runner.calls == [["Add a flight tool"]]  # type: ignore[attr-defined]
    plain = "\n".join(echo.plain)
    assert "/build starting" in plain
    assert "Design" in plain
    assert "Draft v004" in plain
    assert "/build complete (v004)" in plain
    meta = [_strip_ansi(m) for m in result.meta_messages]
    assert any("Next: /save" in m and "p1" in m for m in meta)


def test_handler_forwards_flags_verbatim(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [{"event": "run.completed", "data": {"project_id": "p1", "version": "1"}}]
    )
    _install_build(ctx, runner)

    dispatch(ctx, "/build \"brief text\" --target portable --max-iterations 2")

    assert runner.calls == [  # type: ignore[attr-defined]
        ["brief text", "--target", "portable", "--max-iterations", "2"],
    ]


def test_handler_reports_subprocess_failure(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _failing_runner(BuildCommandError("exit 2"))
    _install_build(ctx, runner)

    result = dispatch(ctx, "/build brief")

    assert result.error is None
    assert any("/build failed" in _strip_ansi(l) for l in echo.lines)
    assert result.display == "skip"
    assert result.raw_result is not None
    assert "/build failed" in result.raw_result


def test_handler_reports_missing_binary(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _failing_runner(FileNotFoundError("python"))
    _install_build(ctx, runner)

    result = dispatch(ctx, "/build brief")

    assert any("/build failed" in _strip_ansi(l) for l in echo.lines)
    assert result.raw_result is None
    assert result.display == "skip"


def test_handler_surfaces_failure_reason_in_meta(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [
            {
                "event": "run.failed",
                "data": {"failure_reason": "budget exceeded", "project_id": "p3"},
            }
        ]
    )
    _install_build(ctx, runner)

    result = dispatch(ctx, "/build brief")

    assert isinstance(result, DispatchResult)
    meta = [_strip_ansi(m) for m in result.meta_messages]
    assert any("Reason: budget exceeded" in m for m in meta)
    # Failed runs do not suggest /save.
    assert not any("Next: /save" in m for m in meta)


def test_handler_includes_last_artifacts_in_meta(ctx: SlashContext) -> None:
    runner = _fake_runner(
        [{"event": "artifact.updated", "data": {"path": f"/tmp/a{i}.json"}} for i in range(5)]
        + [{"event": "run.completed", "data": {"project_id": "p1", "version": "1"}}]
    )
    _install_build(ctx, runner)

    result = dispatch(ctx, "/build brief")

    assert isinstance(result, DispatchResult)
    meta = [_strip_ansi(m) for m in result.meta_messages]
    artifact_meta = [m for m in meta if m.startswith("Artifact:")]
    assert len(artifact_meta) == 3
    assert "/tmp/a4.json" in artifact_meta[-1]


def test_make_build_handler_uses_default_runner_when_none_passed() -> None:
    handler = make_build_handler()
    assert callable(handler)


def test_default_registry_wires_build_command() -> None:
    registry = build_builtin_registry()
    cmd = registry.get("/build")
    assert cmd is not None
    assert cmd.kind == "local"
    assert cmd.source == "builtin"


def test_summary_dataclass_is_frozen() -> None:
    summary = BuildSummary(events=1)
    with pytest.raises(Exception):
        summary.events = 2  # type: ignore[misc]
