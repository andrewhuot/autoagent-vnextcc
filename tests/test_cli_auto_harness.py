"""Tests for the Claude-style auto-mode harness."""

from __future__ import annotations

import time

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
    session.emit(HarnessEvent("task.started", task_id="model", task="Credential-aware model resolution"))
    session.emit(HarnessEvent("task.completed", task_id="model"))
    session.emit(HarnessEvent("task.started", task_id="api", task="First-run mode + API key onboarding"))
    session.emit(HarnessEvent("metrics.updated", tokens=9900, thinking=True))
    session.emit(HarnessEvent("input.queued", message="Run the broader regression sweep"))

    snapshot = session.snapshot()
    output = HarnessRenderer(width=96).render(snapshot)

    assert "Implementing first-run mode" in output
    assert "9.9k tokens" in output
    assert "thinking" in output
    assert "[x] Credential-aware model resolution" in output
    assert "[>] First-run mode + API key onboarding" in output
    assert "[ ] PhaseSpinner for build/optimize" in output
    assert "> Run the broader regression sweep" in output
    assert "bypass permissions on" in output
    assert "shift+tab to cycle" in output


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


def test_permission_footer_cycles_modes() -> None:
    """The footer owns visible permission state and cycling behavior."""
    footer = PermissionFooter(mode="default")

    assert footer.render() == "default permissions on (shift+tab to cycle)"
    assert footer.cycle().mode == "acceptEdits"
    assert footer.cycle().mode == "dontAsk"


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
    assert resolve_cli_ui("text", requested_ui="auto", is_tty=True, is_ci=False) == "claude"
    assert resolve_cli_ui("text", requested_ui="claude", is_tty=False, is_ci=False) == "claude"


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


def test_long_running_commands_expose_claude_ui_choice() -> None:
    """Auto-mode surfaces should expose the Claude-style UI selector."""
    from click.testing import CliRunner

    runner = CliRunner()

    commands = (("optimize",), ("loop", "run"), ("full-auto",), ("shell",))
    for command in commands:
        result = runner.invoke(cli, [*command, "--help"])
        assert result.exit_code == 0, result.output
        assert "--ui [auto|claude|classic]" in result.output


def test_full_auto_claude_ui_reuses_one_harness(monkeypatch) -> None:
    """Full-auto should behave like one long-lived Claude-style session."""
    from click.testing import CliRunner

    seen_harnesses: list[object] = []

    def fake_optimize(**kwargs) -> None:
        seen_harnesses.append(kwargs["harness"])

    def fake_loop(**kwargs) -> None:
        seen_harnesses.append(kwargs["harness"])

    monkeypatch.setattr(runner_module.optimize, "callback", fake_optimize)
    monkeypatch.setattr(runner_module.loop_run, "callback", fake_loop)

    result = CliRunner().invoke(cli, ["full-auto", "--yes", "--ui", "claude"])

    assert result.exit_code == 0, result.output
    assert "AgentLab Full Auto" in result.output
    assert "FULL AUTO MODE ENABLED" not in result.output
    assert len(seen_harnesses) == 2
    assert seen_harnesses[0] is seen_harnesses[1]
