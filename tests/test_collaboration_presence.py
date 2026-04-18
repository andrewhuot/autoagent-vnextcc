"""Tests for workbench collaboration/presence state derivation."""

from __future__ import annotations

from dataclasses import replace

from cli.workbench_app.background_panel import BackgroundTask, TaskStatus
from cli.workbench_app.collaboration_presence import (
    CollaborationTeamState,
    build_presence_snapshot,
    render_presence_lines,
)
from cli.workbench_app.store import (
    CoordinatorStatus,
    WorkerPhase,
    WorkerState,
    get_default_app_state,
)


def test_presence_snapshot_counts_running_blocked_review_and_recent_work() -> None:
    """Presence should summarize the states the user needs to understand."""
    state = replace(
        get_default_app_state(),
        coordinator_status=CoordinatorStatus.RUNNING,
        pending_reviews=2,
        coordinator_workers=(
            WorkerState(
                worker_id="node-build",
                role="BUILD_ENGINEER",
                owner="build_engineer",
                title="Implement config change",
                phase=WorkerPhase.ACTING,
                detail="editing config",
            ),
            WorkerState(
                worker_id="node-deploy",
                role="DEPLOYMENT_ENGINEER",
                owner="deployment_engineer",
                title="Prepare canary",
                phase=WorkerPhase.BLOCKED,
                detail="waiting for approval",
            ),
            WorkerState(
                worker_id="node-eval",
                role="EVAL_AUTHOR",
                owner="eval_author",
                title="Write regression eval",
                phase=WorkerPhase.COMPLETED,
                detail="eval bundle ready",
            ),
        ),
        background_tasks=(
            BackgroundTask(
                task_id="bg-1",
                description="Run smoke tests",
                owner="gate_runner",
                status=TaskStatus.RUNNING,
                detail="pytest",
            ),
            BackgroundTask(
                task_id="bg-2",
                description="Publish report",
                owner="release_manager",
                status=TaskStatus.FAILED,
                detail="network timeout",
            ),
        ),
    )

    snapshot = build_presence_snapshot(state)

    assert snapshot.team_state == CollaborationTeamState.NEEDS_ATTENTION
    assert snapshot.running_count == 2
    assert snapshot.blocked_count == 2
    assert snapshot.waiting_review_count == 2
    assert snapshot.finished_recently_count == 1
    assert snapshot.items[0].owner == "build_engineer"
    assert snapshot.items[0].task == "Implement config change"
    assert snapshot.items[1].requires_attention is True


def test_presence_rendering_names_owner_status_and_recent_progress() -> None:
    """Presence rendering should make ownership and progress legible."""
    state = replace(
        get_default_app_state(),
        coordinator_workers=(
            WorkerState(
                worker_id="node-build",
                role="BUILD_ENGINEER",
                owner="build_engineer",
                title="Implement config change",
                phase=WorkerPhase.COMPLETED,
                detail="opened candidate diff",
            ),
        ),
    )

    lines = render_presence_lines(build_presence_snapshot(state), markup=False)
    rendered = "\n".join(lines)

    assert "Team state: finished recently" in rendered
    assert "Finished recently: 1" in rendered
    assert "build engineer owns Implement config change" in rendered
    assert "completed" in rendered
    assert "opened candidate diff" in rendered
