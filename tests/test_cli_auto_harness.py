"""Tests for the Claude-style auto-mode harness."""

from __future__ import annotations

import time
from pathlib import Path

import click
import pytest

from cli.auto_harness import (
    HarnessEvent,
    HarnessRenderer,
    HarnessSession,
    MessageQueue,
    PermissionFooter,
    ToolOutputSummarizer,
    workbench_event_to_harness_event,
    resolve_cli_ui,
)
from runner import cli
import runner as runner_module


def test_harness_event_sequence_renders_active_status_tasks_queue_and_footer() -> None:
    """A Claude-style event stream should reduce into one compact live snapshot."""
    session = HarnessSession(permission_mode="bypass")

    session.emit(HarnessEvent("session.started", message="Full auto"))
    session.emit(HarnessEvent("stage.started", message="Implementing first-run mode"))
    session.emit(
        HarnessEvent(
            "plan.ready",
            payload={
                "tasks": [
                    {"id": "model", "title": "Credential-aware model resolution"},
                    {"id": "api", "title": "First-run mode + API key onboarding"},
                    {"id": "spinner", "title": "PhaseSpinner for build/optimize"},
                ]
            },
        )
    )
    session.emit(
        HarnessEvent(
            "task.started",
            task_id="model",
            task="Credential-aware model resolution",
        )
    )
    session.emit(HarnessEvent("task.completed", task_id="model"))
    session.emit(
        HarnessEvent(
            "task.started",
            task_id="api",
            task="First-run mode + API key onboarding",
        )
    )
    session.emit(HarnessEvent("metrics.updated", tokens=9900, thinking=True))
    session.emit(HarnessEvent("input.queued", message="Run the broader regression sweep"))

    snapshot = session.snapshot()
    output = HarnessRenderer(width=96).render(snapshot)

    assert "Implementing first-run mode" in output
    assert "9.9k tokens" in output
    assert "thinking" in output
    assert "✓ Credential-aware model resolution" in output
    assert "■ First-run mode + API key onboarding" in output
    assert "□ PhaseSpinner for build/optimize" in output
    assert "› Run the broader regression sweep" in output
    assert "⏵ bypass permissions on" in output
    assert "1 shell, 1 monitor, 1 queued" in output
    assert "↓ to manage" in output


def test_task_list_truncation_keeps_current_work_visible() -> None:
    """Old completed tasks may collapse, but active work must stay visible."""
    session = HarnessSession(permission_mode="default")
    session.emit(HarnessEvent("stage.started", message="Optimizing"))
    for index in range(7):
        task_id = f"done-{index}"
        session.emit(HarnessEvent("task.started", task_id=task_id, task=f"Completed task {index}"))
        session.emit(HarnessEvent("task.completed", task_id=task_id))
    session.emit(HarnessEvent("task.started", task_id="active", task="Current task must remain"))
    session.emit(HarnessEvent("task.started", task_id="pending", task="Pending task"))

    output = HarnessRenderer(width=84, max_tasks=4).render(session.snapshot())

    assert "older completed task" in output
    assert "Current task must remain" in output
    assert "Pending task" in output


def test_tool_output_summary_uses_tail_counts_elapsed_and_exit_status() -> None:
    """Verbose command output should collapse into a useful shell progress summary."""
    output = "\n".join(f"line {index}" for index in range(8))

    summary = ToolOutputSummarizer(max_tail_lines=3).summarize(
        command="pytest tests -q",
        output=output,
        exit_code=1,
        elapsed_seconds=12.4,
    )

    assert "Bash pytest tests -q" in summary
    assert "exit 1" in summary
    assert "8 lines" in summary
    assert "12.4s" in summary
    assert "line 5" in summary
    assert "line 7" in summary
    assert "line 1" not in summary


def test_tool_output_summary_can_expand_full_output() -> None:
    """Claude-style Bash rows should collapse by default and expand on demand."""
    output = "\n".join(f"line {index}" for index in range(8))
    summarizer = ToolOutputSummarizer(max_tail_lines=3)

    collapsed = summarizer.summarize(
        command="pytest tests -q",
        output=output,
        exit_code=0,
        elapsed_seconds=3.2,
    )
    expanded = summarizer.summarize(
        command="pytest tests -q",
        output=output,
        exit_code=0,
        elapsed_seconds=3.2,
        expanded=True,
    )

    assert "line 0" not in collapsed
    assert "showing last 3 of 8 lines" in collapsed
    assert "line 0" in expanded
    assert "showing all 8 lines" in expanded


def test_harness_tool_completed_event_summarizes_collapsed_output() -> None:
    """Tool completion events should render Bash output without dumping logs."""
    session = HarnessSession(permission_mode="default")

    session.emit(
        HarnessEvent(
            "tool.completed",
            payload={
                "command": "pytest tests -q",
                "output": "\n".join(f"line {index}" for index in range(6)),
                "exit_code": 0,
                "elapsed_seconds": 4.5,
            },
        )
    )

    output = HarnessRenderer(width=100).render(session.snapshot())

    assert "● Bash pytest tests -q" in output
    assert "showing last" in output
    assert "line 5" in output
    assert "line 0" not in output


def test_permission_footer_cycles_modes() -> None:
    """The footer owns visible permission state and cycling behavior."""
    footer = PermissionFooter(mode="default")

    assert footer.render() == "⏵ default permissions on (shift+tab to cycle)"
    assert (
        footer.render_status("1 shell, 1 monitor")
        == "⏵ default permissions on · 1 shell, 1 monitor · ↓ to manage"
    )
    assert footer.cycle().mode == "acceptEdits"
    assert footer.cycle().mode == "dontAsk"


def test_permission_footer_renders_prompt_toolbar_like_claude_code() -> None:
    """The live prompt toolbar should have a border line and status footer."""
    session = HarnessSession(permission_mode="bypass")
    session.emit(HarnessEvent("stage.started", message="Running tests"))
    session.emit(HarnessEvent("task.started", task_id="run", task="Run selected AgentLab workflow"))

    toolbar = PermissionFooter(mode="bypass").render_toolbar(session.snapshot(), width=48)

    assert toolbar.splitlines()[0] == "─" * 48
    assert (
        toolbar.splitlines()[1]
        == "⏵ bypass permissions on · 1 shell, 1 monitor · ↓ to manage"
    )


def test_permission_footer_exposes_styled_prompt_toolkit_fragments() -> None:
    """The live footer should carry Claude-like color roles, not plain text only."""
    session = HarnessSession(permission_mode="bypass")
    session.emit(HarnessEvent("stage.started", message="Running tests"))
    session.emit(HarnessEvent("task.started", task_id="run", task="Run tests"))

    fragments = PermissionFooter(mode="bypass").render_toolbar_fragments(
        session.snapshot(),
        width=32,
    )

    assert ("class:prompt.border", "─" * 32) in fragments
    assert ("class:permission.danger", "⏵ bypass permissions on") in fragments
    assert ("class:activity", "1 shell, 1 monitor") in fragments
    assert ("class:hint", "↓ to manage") in fragments


def test_manage_panel_toggles_and_renders_live_work() -> None:
    """The down-arrow manage hint should reveal a real monitor panel."""
    session = HarnessSession(permission_mode="bypass")
    session.emit(HarnessEvent("stage.started", message="Running tests"))
    session.emit(HarnessEvent("task.started", task_id="run", task="Run tests"))
    session.emit(HarnessEvent("input.queued", message="follow up"))
    session.emit(
        HarnessEvent(
            "agent.progress",
            payload={"name": "builder", "status": "running", "tool": "pytest"},
        )
    )

    session.emit(HarnessEvent("manage.toggled"))
    output = HarnessRenderer(width=100).render(session.snapshot())

    assert "Shells and tasks" in output
    assert "Active: Running tests" in output
    assert "Queued: follow up" in output
    assert "Agent: builder | running | pytest" in output


def test_renderer_can_omit_footer_for_live_prompt_toolkit_shell() -> None:
    """The live shell avoids printing a duplicate footer into the transcript."""
    session = HarnessSession(permission_mode="default")
    session.emit(HarnessEvent("message.delta", message="Ready."))

    output = HarnessRenderer(width=80, include_footer=False).render(session.snapshot())

    assert "Ready." in output
    assert "default permissions" not in output


def test_harness_renderer_can_style_transcript_blocks() -> None:
    """Styled rendering should add ANSI roles for Claude-like transcript blocks."""
    session = HarnessSession(permission_mode="default")
    session.emit(HarnessEvent("message.delta", message="Ready."))
    session.emit(HarnessEvent("input.queued", message="follow up"))

    output = HarnessRenderer(width=80, styled=True).render(session.snapshot())

    assert "\x1b[" in output
    assert "Ready." in output
    assert "› follow up" in output


def test_message_queue_orders_priorities_and_tracks_age() -> None:
    """Queued input should keep Claude-style now/next/later ordering."""
    queue = MessageQueue(clock=time.monotonic)
    queue.add("later item", priority="later")
    queue.add("next item", priority="next")
    queue.add("now item", priority="now")

    assert [item.text for item in queue.items()] == ["now item", "next item", "later item"]
    assert queue.pop_next().text == "now item"
    assert [item.text for item in queue.items()] == ["next item", "later item"]


def test_resolve_cli_ui_keeps_structured_output_non_interactive(monkeypatch) -> None:
    """JSON-oriented formats must never opt into the interactive harness."""
    monkeypatch.setenv("AGENTLAB_CLI_UI", "claude")

    assert resolve_cli_ui("stream-json", requested_ui="auto", is_tty=True, is_ci=False) == "classic"
    assert resolve_cli_ui("text", requested_ui=None, is_tty=True, is_ci=False) == "claude"
    assert resolve_cli_ui("text", requested_ui="auto", is_tty=True, is_ci=False) == "claude"
    monkeypatch.setenv("AGENTLAB_CLI_UI", "classic")
    assert resolve_cli_ui("text", requested_ui=None, is_tty=True, is_ci=False) == "classic"
    assert resolve_cli_ui("text", requested_ui="auto", is_tty=False, is_ci=False) == "classic"
    with pytest.raises(click.ClickException):
        resolve_cli_ui("text", requested_ui="claude", is_tty=False, is_ci=False)


def test_workbench_events_adapt_to_harness_events() -> None:
    """Workbench streams should be able to feed the shared Claude-style reducer."""
    plan = workbench_event_to_harness_event(
        "plan.ready",
        {"tasks": [{"id": "draft", "title": "Draft agent"}]},
    )
    task = workbench_event_to_harness_event(
        "task.started",
        {"task_id": "draft", "title": "Draft agent"},
    )
    metrics = workbench_event_to_harness_event(
        "harness.metrics",
        {"tokens": 4200, "cost_usd": 0.12},
    )

    assert plan is not None
    assert plan.event == "plan.ready"
    assert plan.payload["tasks"] == [{"id": "draft", "title": "Draft agent"}]
    assert task is not None
    assert task.event == "task.started"
    assert task.task_id == "draft"
    assert task.task == "Draft agent"
    assert metrics is not None
    assert metrics.event == "metrics.updated"
    assert metrics.tokens == 4200
    assert metrics.cost_usd == 0.12


def test_workbench_tool_events_adapt_to_harness_events() -> None:
    """Workbench and runner tool events should flow into Bash-style summaries."""
    adapted = workbench_event_to_harness_event(
        "tool.completed",
        {
            "command": "pytest tests -q",
            "output": "one\ntwo\nthree",
            "exit_code": 0,
            "elapsed_seconds": 1.25,
        },
    )

    assert adapted is not None
    assert adapted.event == "tool.completed"
    assert adapted.payload["command"] == "pytest tests -q"


def test_claude_style_terminal_snapshot_matches_fixture() -> None:
    """A representative frame should stay visually close to the Claude reference."""
    session = HarnessSession(permission_mode="bypass")
    session.emit(HarnessEvent("message.delta", message="› is it still running?"))
    session.emit(
        HarnessEvent(
            "tool.completed",
            payload={
                "command": "ps aux | grep ralph",
                "output": "ralph.sh\nclaude child\nshell",
                "exit_code": 0,
                "elapsed_seconds": 2.0,
            },
        )
    )
    session.emit(HarnessEvent("stage.started", message="Letting it run"))
    session.emit(HarnessEvent("task.started", task_id="run", task="Monitor existing run"))
    session.emit(HarnessEvent("input.queued", message="yeah let it run"))
    session.emit(HarnessEvent("manage.toggled"))

    output = HarnessRenderer(width=72, now=lambda: session.snapshot().started_at + 4).render(
        session.snapshot()
    )

    fixture = Path(__file__).parent / "fixtures" / "claude_shell_snapshot.txt"
    assert output == fixture.read_text(encoding="utf-8").rstrip("\n")


def test_long_running_commands_expose_claude_ui_choice() -> None:
    """Auto-mode surfaces should expose the Claude-style UI selector."""
    from click.testing import CliRunner

    runner = CliRunner()

    commands = (("optimize",), ("loop", "run"), ("full-auto",), ("shell",))
    for command in commands:
        result = runner.invoke(cli, [*command, "--help"])
        assert result.exit_code == 0, result.output
        assert "--ui [auto|claude|classic]" in result.output
        normalized_output = " ".join(result.output.split())
        assert "default:" in normalized_output
        assert "auto" in normalized_output


def test_full_auto_claude_ui_reuses_one_harness(monkeypatch) -> None:
    """Full-auto should behave like one long-lived Claude-style session."""
    from click.testing import CliRunner

    seen_harnesses: list[object] = []

    def fake_optimize(**kwargs) -> None:
        seen_harnesses.append(kwargs["harness"])

    def fake_loop(**kwargs) -> None:
        seen_harnesses.append(kwargs["harness"])

    monkeypatch.setattr("cli.auto_harness._stdout_is_tty", lambda: True)
    monkeypatch.setattr(runner_module.optimize, "callback", fake_optimize)
    monkeypatch.setattr(runner_module.loop_run, "callback", fake_loop)

    result = CliRunner().invoke(cli, ["full-auto", "--yes", "--ui", "claude"])

    assert result.exit_code == 0, result.output
    assert "AgentLab Full Auto" in result.output
    assert "FULL AUTO MODE ENABLED" not in result.output
    assert len(seen_harnesses) == 2
    assert seen_harnesses[0] is seen_harnesses[1]
