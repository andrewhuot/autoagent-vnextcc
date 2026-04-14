"""Tests for the plan-mode approval gate (F3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import pytest

from builder.coordinator_turn import CoordinatorTurnResult
from cli.workbench_app.plan_gate import PlanGate, PlanGateOutcome


@dataclass
class _StubRuntime:
    """Minimal runtime stub that records process_turn calls."""

    calls: list[tuple[str, bool]] = field(default_factory=list)
    counter: int = 0

    def process_turn(
        self,
        message: str,
        *,
        ctx=None,
        command_intent=None,
        dry_run: bool = False,
    ) -> CoordinatorTurnResult:
        self.calls.append((message, dry_run))
        self.counter += 1
        status = "planned" if dry_run else "completed"
        run_id = "" if dry_run else f"run-{self.counter}"
        transcript = (
            f"  Coordinator plan plan-{self.counter} ready — 2 workers queued.",
            "  • build engineer: drafted",
            "  Approve with y to execute, n to abort, or edit to refine.",
        )
        return CoordinatorTurnResult(
            message=message,
            command_intent=command_intent or "build",
            project_id="proj-1",
            session_id="sess-1",
            task_id=f"task-{self.counter}",
            plan_id=f"plan-{self.counter}",
            run_id=run_id,
            status=status,
            transcript_lines=transcript,
            worker_roles=("build_engineer", "prompt_engineer"),
            active_tasks=0,
            next_actions=("Reply y to approve.",),
            review_cards=(),
            metadata={"dry_run": dry_run},
        )


def _make_prompt(answers: Iterable[str]):
    """Build a prompt callback that returns canned operator answers."""
    iterator = iter(answers)

    def _prompt(_message: str) -> str:
        try:
            return next(iterator)
        except StopIteration:
            return ""

    return _prompt


def test_plan_gate_approves_and_executes() -> None:
    """Typing ``y`` should trigger a real (non-dry-run) coordinator call."""
    runtime = _StubRuntime()
    echoed: list[str] = []
    gate = PlanGate(
        runtime,
        prompt_fn=_make_prompt(["y"]),
        echo_fn=echoed.append,
    )

    outcome = gate.run("Ship a support agent", command_intent="build")

    assert isinstance(outcome, PlanGateOutcome)
    assert outcome.decision == "approved"
    assert outcome.rounds == 0
    assert outcome.result.status == "completed"
    # Two process_turn calls: one dry run, one real.
    assert [call[1] for call in runtime.calls] == [True, False]


def test_plan_gate_aborts_without_executing() -> None:
    """Typing ``n`` should return the planned result without executing."""
    runtime = _StubRuntime()
    echoed: list[str] = []
    gate = PlanGate(
        runtime,
        prompt_fn=_make_prompt(["n"]),
        echo_fn=echoed.append,
    )

    outcome = gate.run("Ship a support agent", command_intent="build")

    assert outcome.decision == "aborted"
    assert outcome.result.status == "planned"
    assert [call[1] for call in runtime.calls] == [True]
    assert any("aborted" in line for line in echoed)


def test_plan_gate_edit_appends_annotation_and_replans() -> None:
    """Edit input should re-run the plan with the annotation appended."""
    runtime = _StubRuntime()
    gate = PlanGate(
        runtime,
        prompt_fn=_make_prompt(["edit also add guardrail for PII", "y"]),
        echo_fn=lambda _line: None,
    )

    outcome = gate.run("Ship a support agent", command_intent="build")

    assert outcome.decision == "approved"
    assert outcome.rounds == 1
    messages = [call[0] for call in runtime.calls]
    assert messages[0] == "Ship a support agent"
    # Second dry-run (after edit) must contain the appended annotation.
    assert "also add guardrail for PII" in messages[1]
    # Execution must use the edited message too.
    assert messages[2].endswith("also add guardrail for PII")


def test_plan_gate_edit_limit_returns_planned() -> None:
    """Loops past the max edit rounds should return the last planned result."""
    runtime = _StubRuntime()
    answers = ["edit a", "edit b", "edit c"]
    gate = PlanGate(
        runtime,
        prompt_fn=_make_prompt(answers),
        echo_fn=lambda _line: None,
        max_edit_rounds=2,
    )

    outcome = gate.run("Ship a support agent")

    assert outcome.decision == "edit_limit_reached"
    assert outcome.rounds == 3
    assert outcome.result.status == "planned"


def test_plan_gate_unrecognized_input_is_treated_as_edit() -> None:
    """Free text (no verb) should be treated as an edit annotation."""
    runtime = _StubRuntime()
    gate = PlanGate(
        runtime,
        prompt_fn=_make_prompt(["make it safer", "y"]),
        echo_fn=lambda _line: None,
    )

    outcome = gate.run("Ship a support agent")

    assert outcome.decision == "approved"
    assert outcome.rounds == 1
    # Dry-run after annotation must contain the free-text edit.
    assert "make it safer" in runtime.calls[1][0]
