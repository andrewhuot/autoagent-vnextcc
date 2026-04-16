"""Tests for cli/workbench_app/deploy_slash.py — the `/deploy` streaming handler."""

from __future__ import annotations

import re
from typing import Iterator, Sequence

import pytest

from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.deploy_slash import (
    DeployCommandError,
    DeploySummary,
    _format_summary,
    _infer_strategy,
    _is_dry_run,
    _is_preconfirmed,
    _parse_args,
    _render_event,
    _summarise,
    build_deploy_command,
    make_deploy_handler,
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


class _Prompter:
    """Records prompts and returns a canned decision."""

    def __init__(self, decision: bool = True) -> None:
        self.decision = decision
        self.messages: list[str] = []

    def __call__(self, message: str) -> bool:
        self.messages.append(message)
        return self.decision


# ---------------------------------------------------------------------------
# _parse_args — pass-through
# ---------------------------------------------------------------------------


def test_parse_args_passes_through_strategy_flag() -> None:
    assert _parse_args(["--strategy", "immediate"]) == ["--strategy", "immediate"]


def test_parse_args_passes_through_positional_workflow() -> None:
    assert _parse_args(["canary"]) == ["canary"]


def test_parse_args_empty() -> None:
    assert _parse_args([]) == []


# ---------------------------------------------------------------------------
# _infer_strategy
# ---------------------------------------------------------------------------


def test_infer_strategy_defaults_to_canary() -> None:
    assert _infer_strategy([]) == "canary"


def test_infer_strategy_reads_flag_with_space() -> None:
    assert _infer_strategy(["--strategy", "immediate"]) == "immediate"


def test_infer_strategy_reads_flag_with_equals() -> None:
    assert _infer_strategy(["--strategy=immediate"]) == "immediate"


def test_infer_strategy_reads_positional_workflow() -> None:
    assert _infer_strategy(["immediate"]) == "immediate"


def test_infer_strategy_maps_release_to_immediate() -> None:
    assert _infer_strategy(["release"]) == "immediate"


def test_infer_strategy_positional_overrides_default() -> None:
    assert _infer_strategy(["canary", "--target", "agentlab"]) == "canary"


# ---------------------------------------------------------------------------
# _is_preconfirmed / _is_dry_run
# ---------------------------------------------------------------------------


def test_is_preconfirmed_true_for_short_flag() -> None:
    assert _is_preconfirmed(["-y"]) is True


def test_is_preconfirmed_true_for_long_flag() -> None:
    assert _is_preconfirmed(["--yes"]) is True


def test_is_preconfirmed_false_when_absent() -> None:
    assert _is_preconfirmed(["--strategy", "immediate"]) is False


def test_is_dry_run_true_when_present() -> None:
    assert _is_dry_run(["--dry-run"]) is True


def test_is_dry_run_false_when_absent() -> None:
    assert _is_dry_run(["--strategy", "canary"]) is False


# ---------------------------------------------------------------------------
# _render_event
# ---------------------------------------------------------------------------


def test_render_event_formats_phase_completed() -> None:
    line = _render_event(
        {"event": "phase_completed", "phase": "deploy", "message": "Deployed v007 as canary"}
    )
    assert line is not None
    assert "Deployed v007 as canary" in _strip_ansi(line)


def test_render_event_returns_none_for_missing_name() -> None:
    assert _render_event({"message": "orphan"}) is None


# ---------------------------------------------------------------------------
# _summarise
# ---------------------------------------------------------------------------


def test_summarise_counts_phases_artifacts_warnings_errors() -> None:
    events = [
        {"event": "phase_started", "phase": "deploy"},
        {"event": "phase_completed", "phase": "deploy", "message": "CX package ready"},
        {"event": "artifact_written", "path": "/tmp/cx_export_v007.json"},
        {"event": "warning", "message": "CX preview unavailable"},
        {"event": "next_action", "message": "agentlab status"},
    ]
    summary = list(_summarise(events, strategy="canary"))[-1][1]
    assert summary.events == 5
    assert summary.phases_completed == 1
    assert summary.artifacts == ("/tmp/cx_export_v007.json",)
    assert summary.warnings == 1
    assert summary.errors == 0
    assert summary.next_action == "agentlab status"
    assert summary.strategy == "canary"


def test_summarise_preserves_strategy_in_every_tuple() -> None:
    events = [{"event": "phase_started", "phase": "deploy"}]
    pairs = list(_summarise(events, strategy="immediate"))
    assert all(p[1].strategy == "immediate" for p in pairs)


def test_summarise_artifact_without_path_falls_back_to_message() -> None:
    events = [{"event": "artifact_written", "message": "inline"}]
    summary = list(_summarise(events, strategy="canary"))[-1][1]
    assert summary.artifacts == ("inline",)


def test_summarise_handles_empty_stream() -> None:
    assert list(_summarise([], strategy="canary")) == []


# ---------------------------------------------------------------------------
# _format_summary
# ---------------------------------------------------------------------------


def test_format_summary_green_on_clean_run() -> None:
    line = _format_summary(
        DeploySummary(events=3, phases_completed=1, strategy="canary")
    )
    plain = _strip_ansi(line)
    assert "/deploy complete" in plain
    assert "3 events" in plain
    assert "strategy=canary" in plain
    assert "1 phase" in plain


def test_format_summary_singular_phase_label() -> None:
    line = _format_summary(DeploySummary(events=1, phases_completed=1))
    plain = _strip_ansi(line)
    assert "1 phase" in plain
    assert "1 phases" not in plain


def test_format_summary_red_on_errors() -> None:
    line = _format_summary(DeploySummary(events=2, errors=1, strategy="immediate"))
    plain = _strip_ansi(line)
    assert "/deploy failed" in plain
    assert "1 errors" in plain


def test_format_summary_lists_warnings_and_artifacts() -> None:
    line = _format_summary(
        DeploySummary(events=4, artifacts=("a", "b"), warnings=1, strategy="canary")
    )
    plain = _strip_ansi(line)
    assert "2 artifacts" in plain
    assert "1 warnings" in plain


# ---------------------------------------------------------------------------
# Handler integration — exercised via dispatch()
# ---------------------------------------------------------------------------


@pytest.fixture
def echo() -> _EchoCapture:
    return _EchoCapture()


@pytest.fixture
def ctx(echo: _EchoCapture) -> SlashContext:
    registry = CommandRegistry()
    ctx = SlashContext(echo=echo, registry=registry)
    # R4.6: pre-install a session with last_attempt_id so the new
    # session-aware gate doesn't short-circuit legacy tests that predate
    # it. Tests that exercise the missing-attempt path install their own
    # empty session in ctx.meta.
    from cli.workbench_app.session_state import WorkbenchSession

    _session = WorkbenchSession()
    _session.update(last_attempt_id="att_test")
    ctx.meta["workbench_session"] = _session
    return ctx


def _install_deploy(
    ctx: SlashContext, runner, prompter: _Prompter | None = None
) -> _Prompter:
    p = prompter or _Prompter(decision=True)
    assert ctx.registry is not None
    ctx.registry.register(build_deploy_command(runner=runner, prompter=p))
    return p


def test_handler_prompts_and_appends_yes_on_confirmation(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [
            {"event": "phase_started", "phase": "deploy"},
            {"event": "phase_completed", "phase": "deploy", "message": "Deployed v007 as canary"},
            {"event": "next_action", "message": "agentlab status"},
        ]
    )
    prompter = _install_deploy(ctx, runner, _Prompter(decision=True))

    result = dispatch(ctx, "/deploy --strategy canary")

    assert isinstance(result, DispatchResult)
    assert result.error is None
    assert len(prompter.messages) == 1
    assert "strategy=canary" in _strip_ansi(prompter.messages[0])
    # -y appended by the handler so runner.deploy doesn't re-prompt.
    # Session then injects --attempt-id att_test (see ctx fixture).
    assert runner.calls == [["--strategy", "canary", "-y", "--attempt-id", "att_test"]]
    plain = "\n".join(echo.plain)
    assert "/deploy starting" in plain
    assert "/deploy complete" in plain
    assert any("Suggested next" in l for l in echo.plain)


def test_handler_cancels_when_prompt_returns_false(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner([{"event": "phase_started", "phase": "deploy"}])
    prompter = _install_deploy(ctx, runner, _Prompter(decision=False))

    result = dispatch(ctx, "/deploy")

    assert len(prompter.messages) == 1
    assert runner.calls == []  # subprocess never ran
    assert any("/deploy cancelled" in _strip_ansi(l) for l in echo.lines)
    assert result.display == "skip"


def test_handler_cancels_cleanly_on_keyboard_interrupt(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner([{"event": "phase_started", "phase": "deploy"}])

    def _raising_prompter(_message: str) -> bool:
        raise KeyboardInterrupt()

    assert ctx.registry is not None
    ctx.registry.register(build_deploy_command(runner=runner, prompter=_raising_prompter))

    result = dispatch(ctx, "/deploy")

    assert runner.calls == []
    assert any("/deploy cancelled" in _strip_ansi(l) for l in echo.lines)
    assert result.display == "skip"


def test_handler_skips_prompt_when_yes_already_passed(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [
            {"event": "phase_completed", "phase": "deploy", "message": "Deployed v007 immediately"},
        ]
    )
    prompter = _install_deploy(ctx, runner, _Prompter(decision=False))

    dispatch(ctx, "/deploy --strategy immediate --yes")

    # Prompter never consulted; -y not double-appended.
    assert prompter.messages == []
    # Session injects --attempt-id att_test (see ctx fixture).
    assert runner.calls == [["--strategy", "immediate", "--yes", "--attempt-id", "att_test"]]
    assert any("/deploy complete" in _strip_ansi(l) for l in echo.lines)


def test_handler_skips_prompt_on_dry_run(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [
            {"event": "phase_completed", "phase": "deploy", "message": "Dry-run deployment preview ready"},
        ]
    )
    prompter = _install_deploy(ctx, runner, _Prompter(decision=False))

    dispatch(ctx, "/deploy --dry-run")

    assert prompter.messages == []
    # No -y appended on dry-run — the subprocess itself won't prompt.
    # Session injects --attempt-id att_test (see ctx fixture).
    assert runner.calls == [["--dry-run", "--attempt-id", "att_test"]]


def test_handler_reports_subprocess_failure(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _failing_runner(DeployCommandError("exit 2"))
    _install_deploy(ctx, runner)

    result = dispatch(ctx, "/deploy --yes")

    assert result.error is None
    assert any("/deploy failed" in _strip_ansi(l) for l in echo.lines)
    assert result.display == "skip"
    assert result.raw_result is not None
    assert "/deploy failed" in result.raw_result


def test_handler_reports_missing_binary(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _failing_runner(FileNotFoundError("agentlab"))
    _install_deploy(ctx, runner)

    result = dispatch(ctx, "/deploy --yes")

    assert any("/deploy failed" in _strip_ansi(l) for l in echo.lines)
    assert result.raw_result is None
    assert result.display == "skip"


def test_handler_surfaces_errors_in_summary(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    runner = _fake_runner(
        [
            {"event": "phase_started", "phase": "deploy"},
            {"event": "error", "message": "permission denied"},
        ]
    )
    _install_deploy(ctx, runner)

    dispatch(ctx, "/deploy --yes")

    plain = "\n".join(echo.plain)
    assert "/deploy failed" in plain
    assert "1 errors" in plain


def test_handler_truncates_artifact_meta_to_last_three(
    ctx: SlashContext,
) -> None:
    runner = _fake_runner(
        [{"event": "artifact_written", "path": f"/tmp/a{i}.json"} for i in range(5)]
    )
    _install_deploy(ctx, runner)

    result = dispatch(ctx, "/deploy --yes")

    assert isinstance(result, DispatchResult)
    artifact_meta = [
        _strip_ansi(m) for m in result.meta_messages if m.startswith(("\x1b", "Artifact:"))
    ]
    artifact_meta = [m for m in artifact_meta if m.startswith("Artifact:")]
    assert len(artifact_meta) == 3
    assert "/tmp/a4.json" in artifact_meta[-1]


def test_make_deploy_handler_uses_defaults_when_none_passed() -> None:
    handler = make_deploy_handler()
    assert callable(handler)


def test_default_registry_wires_deploy_command() -> None:
    registry = build_builtin_registry()
    cmd = registry.get("/deploy")
    assert cmd is not None
    assert cmd.kind == "local"
    assert cmd.source == "builtin"


def test_summary_dataclass_is_frozen() -> None:
    summary = DeploySummary(events=1)
    with pytest.raises(Exception):
        summary.events = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# R4.6 — in-process runner: subprocess-free, session-aware, error-bounded
# ---------------------------------------------------------------------------


def test_deploy_slash_does_not_spawn_subprocess() -> None:
    """The refactored /deploy handler must NOT invoke ``subprocess.Popen``."""
    import subprocess
    from unittest.mock import patch

    from cli.workbench_app.session_state import WorkbenchSession

    echo = _EchoCapture()
    registry = CommandRegistry()
    ctx = SlashContext(echo=echo, registry=registry)
    session = WorkbenchSession()
    session.update(last_attempt_id="att_test")
    ctx.meta["workbench_session"] = session

    runner = _fake_runner(
        [
            {"event": "phase_started", "phase": "deploy"},
            {
                "event": "deploy_complete",
                "attempt_id": "att_test",
                "deployment_id": "canary-v001",
                "status": "ok",
                "verdict": "approved",
            },
        ]
    )
    registry.register(
        build_deploy_command(runner=runner, prompter=_Prompter(decision=True))
    )

    with patch.object(subprocess, "Popen") as popen_mock:
        popen_mock.side_effect = AssertionError("subprocess spawned!")
        dispatch(ctx, "/deploy -y")

    popen_mock.assert_not_called()


def test_deploy_slash_auto_injects_session_attempt_id() -> None:
    """When session has last_attempt_id, it's auto-injected into kwargs."""
    from cli.workbench_app.deploy_slash import (
        _args_to_kwargs,
        _resolve_session_attempt_id,
    )
    from cli.workbench_app.session_state import WorkbenchSession

    session = WorkbenchSession()
    session.update(last_attempt_id="att_abc")

    kwargs = _args_to_kwargs(["--dry-run"])
    resolved = _resolve_session_attempt_id(kwargs, session)
    assert resolved["attempt_id"] == "att_abc"


def test_deploy_slash_user_override_beats_session() -> None:
    """User --attempt-id wins over session state."""
    from cli.workbench_app.deploy_slash import (
        _args_to_kwargs,
        _resolve_session_attempt_id,
    )
    from cli.workbench_app.session_state import WorkbenchSession

    session = WorkbenchSession()
    session.update(last_attempt_id="att_session")

    kwargs = _args_to_kwargs(["--attempt-id", "att_user"])
    resolved = _resolve_session_attempt_id(kwargs, session)
    assert resolved["attempt_id"] == "att_user"


def test_deploy_slash_errors_when_session_missing_attempt_id(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    """No user flag and no session id → transcript error + no runner call."""
    from cli.workbench_app.session_state import WorkbenchSession

    session = WorkbenchSession()  # no last_attempt_id
    ctx.meta["workbench_session"] = session

    runner = _fake_runner([])
    _install_deploy(ctx, runner)

    result = dispatch(ctx, "/deploy -y")

    plain = "\n".join(echo.plain)
    assert "no attempt in session" in plain
    assert runner.calls == []
    assert isinstance(result, DispatchResult)
    assert result.display == "skip"


def test_deploy_slash_handles_missing_session_gracefully(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    """No session in ctx.meta + explicit --attempt-id must not raise."""
    ctx.meta.pop("workbench_session", None)

    runner = _fake_runner(
        [
            {"event": "phase_started", "phase": "deploy"},
            {
                "event": "deploy_complete",
                "attempt_id": "att_x",
                "deployment_id": "canary-v001",
                "status": "ok",
                "verdict": "approved",
            },
        ]
    )
    _install_deploy(ctx, runner)

    result = dispatch(ctx, "/deploy --attempt-id att_x -y")
    assert isinstance(result, DispatchResult)


def test_deploy_slash_preserves_verdict_gate_block(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    """Verdict-blocked from the runner must surface as a transcript error."""
    from cli.workbench_app.session_state import WorkbenchSession

    session = WorkbenchSession()
    session.update(last_attempt_id="att_x")
    ctx.meta["workbench_session"] = session

    runner = _failing_runner(DeployCommandError("deploy blocked: verdict=blocked"))
    _install_deploy(ctx, runner)

    result = dispatch(ctx, "/deploy -y")

    assert isinstance(result, DispatchResult)
    assert result.error is None
    plain = "\n".join(echo.plain)
    assert "/deploy failed" in plain
    assert "blocked" in plain
    assert result.display == "skip"
    assert result.raw_result is not None


def test_deploy_slash_error_boundary_catches_unexpected(
    ctx: SlashContext, echo: _EchoCapture
) -> None:
    """Unexpected exception from runner must be caught and rendered."""
    from cli.workbench_app.session_state import WorkbenchSession

    session = WorkbenchSession()
    session.update(last_attempt_id="att_x")
    ctx.meta["workbench_session"] = session

    runner = _failing_runner(ValueError("boom"))
    _install_deploy(ctx, runner)

    result = dispatch(ctx, "/deploy -y")

    assert isinstance(result, DispatchResult)
    assert result.error is None
    plain = "\n".join(echo.plain)
    assert "crashed" in plain.lower() or "/deploy failed" in plain
    assert result.raw_result is not None


def test_args_to_kwargs_parses_attempt_id_and_environment() -> None:
    """Unit test: /deploy argv → kwargs maps --attempt-id + --strategy."""
    from cli.workbench_app.deploy_slash import _args_to_kwargs

    kwargs = _args_to_kwargs(
        [
            "--attempt-id",
            "att_42",
            "--strategy",
            "immediate",
            "--dry-run",
        ]
    )
    assert kwargs["attempt_id"] == "att_42"
    assert kwargs["strategy"] == "immediate"
    assert kwargs["dry_run"] is True


def test_resolve_session_attempt_id_injects_from_session() -> None:
    from cli.workbench_app.deploy_slash import _resolve_session_attempt_id
    from cli.workbench_app.session_state import WorkbenchSession

    session = WorkbenchSession()
    session.update(last_attempt_id="att_session")

    kwargs: dict = {"attempt_id": None}
    resolved = _resolve_session_attempt_id(kwargs, session)
    assert resolved["attempt_id"] == "att_session"


def test_resolve_session_attempt_id_preserves_user_value() -> None:
    from cli.workbench_app.deploy_slash import _resolve_session_attempt_id
    from cli.workbench_app.session_state import WorkbenchSession

    session = WorkbenchSession()
    session.update(last_attempt_id="att_session")

    kwargs = {"attempt_id": "att_user"}
    resolved = _resolve_session_attempt_id(kwargs, session)
    assert resolved["attempt_id"] == "att_user"


def test_resolve_session_attempt_id_raises_when_both_missing() -> None:
    from cli.workbench_app.deploy_slash import (
        DeployCommandError,
        _resolve_session_attempt_id,
    )
    from cli.workbench_app.session_state import WorkbenchSession

    session = WorkbenchSession()  # no attempt id
    kwargs: dict = {"attempt_id": None}
    with pytest.raises(DeployCommandError, match="no attempt in session"):
        _resolve_session_attempt_id(kwargs, session)
