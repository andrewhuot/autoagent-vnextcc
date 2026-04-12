"""Task execution engine for Builder Workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from builder.events import BuilderEventType, EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.permissions import PermissionManager
from builder.store import BuilderStore
from builder.types import (
    BuilderTask,
    ExecutionMode,
    SandboxRun,
    TaskStatus,
    WorktreeRef,
    now_ts,
)


class BuilderExecutionEngine:
    """Creates and drives task lifecycle transitions across execution modes."""

    def __init__(
        self,
        store: BuilderStore,
        orchestrator: BuilderOrchestrator,
        permissions: PermissionManager,
        events: EventBroker,
        worktree_root: str = ".agentlab/builder/worktrees",
    ) -> None:
        self._store = store
        self._orchestrator = orchestrator
        self._permissions = permissions
        self._events = events
        self._worktree_root = Path(worktree_root)
        self._worktree_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Task creation and lifecycle
    # ------------------------------------------------------------------

    def create_task(
        self,
        session_id: str,
        project_id: str,
        title: str,
        description: str,
        mode: ExecutionMode,
        parent_task_id: str | None = None,
    ) -> BuilderTask:
        """Create a new task and attach it to session state."""

        task = BuilderTask(
            session_id=session_id,
            project_id=project_id,
            title=title,
            description=description,
            mode=mode,
            parent_task_id=parent_task_id,
        )
        self._store.save_task(task)

        session = self._store.get_session(session_id)
        if session is not None and task.task_id not in session.task_ids:
            session.task_ids.append(task.task_id)
            session.updated_at = now_ts()
            self._store.save_session(session)

        if mode == ExecutionMode.DELEGATE:
            worktree = self._create_worktree_for_task(task)
            task.worktree_ref = worktree.worktree_id
            task.updated_at = now_ts()
            self._store.save_task(task)

        return task

    def start_task(self, task_id: str, step: str = "Planning") -> BuilderTask | None:
        """Transition a task to running state."""

        task = self._store.get_task(task_id)
        if task is None:
            return None

        task.status = TaskStatus.RUNNING
        task.started_at = task.started_at or now_ts()
        task.updated_at = now_ts()
        task.current_step = step
        task.progress = max(task.progress, 1)

        self._store.save_task(task)
        self._events.publish(
            BuilderEventType.TASK_STARTED,
            session_id=task.session_id,
            task_id=task.task_id,
            payload={"status": task.status.value, "step": step},
        )
        return task

    def pause_task(self, task_id: str, reason: str = "") -> BuilderTask | None:
        """Pause an actively running task."""

        task = self._store.get_task(task_id)
        if task is None:
            return None

        task.status = TaskStatus.PAUSED
        task.paused_at = now_ts()
        task.updated_at = now_ts()
        if reason:
            task.metadata["pause_reason"] = reason
        self._store.save_task(task)

        self._events.publish(
            BuilderEventType.TASK_PROGRESS,
            session_id=task.session_id,
            task_id=task.task_id,
            payload={"status": task.status.value, "reason": reason},
        )
        return task

    def resume_task(self, task_id: str) -> BuilderTask | None:
        """Resume a paused task."""

        task = self._store.get_task(task_id)
        if task is None:
            return None

        task.status = TaskStatus.RUNNING
        task.updated_at = now_ts()
        task.paused_at = None
        self._store.save_task(task)

        self._events.publish(
            BuilderEventType.TASK_PROGRESS,
            session_id=task.session_id,
            task_id=task.task_id,
            payload={"status": task.status.value},
        )
        return task

    def cancel_task(self, task_id: str, reason: str = "") -> BuilderTask | None:
        """Cancel a task and mark it terminal."""

        task = self._store.get_task(task_id)
        if task is None:
            return None

        task.status = TaskStatus.CANCELLED
        task.completed_at = now_ts()
        task.updated_at = now_ts()
        self._clear_completion_blockers(task)
        task.error = reason or task.error
        self._store.save_task(task)

        self._events.publish(
            BuilderEventType.TASK_FAILED,
            session_id=task.session_id,
            task_id=task.task_id,
            payload={"status": task.status.value, "reason": reason},
        )
        return task

    def complete_task(self, task_id: str, artifact_ids: list[str] | None = None) -> BuilderTask | None:
        """Mark task complete with optional artifact references."""

        task = self._store.get_task(task_id)
        if task is None:
            return None

        task.status = TaskStatus.COMPLETED
        task.completed_at = now_ts()
        task.updated_at = now_ts()
        task.progress = 100
        self._clear_completion_blockers(task)
        if artifact_ids:
            task.artifact_ids = artifact_ids

        self._store.save_task(task)
        self._events.publish(
            BuilderEventType.TASK_COMPLETED,
            session_id=task.session_id,
            task_id=task.task_id,
            payload={"status": task.status.value, "artifacts": task.artifact_ids},
        )
        return task

    def fail_task(self, task_id: str, error: str) -> BuilderTask | None:
        """Mark a task as failed."""

        task = self._store.get_task(task_id)
        if task is None:
            return None

        task.status = TaskStatus.FAILED
        task.completed_at = now_ts()
        task.updated_at = now_ts()
        task.error = error
        self._clear_completion_blockers(task)
        self._store.save_task(task)

        self._events.publish(
            BuilderEventType.TASK_FAILED,
            session_id=task.session_id,
            task_id=task.task_id,
            payload={"status": task.status.value, "error": error},
        )
        return task

    # ------------------------------------------------------------------
    # Utility task operations
    # ------------------------------------------------------------------

    def duplicate_task(self, task_id: str) -> BuilderTask | None:
        """Create a pending duplicate of an existing task."""

        task = self._store.get_task(task_id)
        if task is None:
            return None

        duplicate = BuilderTask(
            session_id=task.session_id,
            project_id=task.project_id,
            title=f"{task.title} (copy)",
            description=task.description,
            mode=task.mode,
            parent_task_id=task.parent_task_id,
            duplicate_of_task_id=task.task_id,
            metadata={**task.metadata, "duplicated_from": task.task_id},
        )
        self._store.save_task(duplicate)
        return duplicate

    def fork_task(self, task_id: str, mode: ExecutionMode | None = None) -> BuilderTask | None:
        """Fork a task into a parallel candidate branch."""

        task = self._store.get_task(task_id)
        if task is None:
            return None

        forked_mode = mode or task.mode
        fork = BuilderTask(
            session_id=task.session_id,
            project_id=task.project_id,
            title=f"{task.title} (fork)",
            description=task.description,
            mode=forked_mode,
            parent_task_id=task.task_id,
            forked_from_task_id=task.task_id,
            metadata={**task.metadata, "forked_from": task.task_id},
        )
        self._store.save_task(fork)

        if fork.mode == ExecutionMode.DELEGATE:
            worktree = self._create_worktree_for_task(fork)
            fork.worktree_ref = worktree.worktree_id
            fork.updated_at = now_ts()
            self._store.save_task(fork)

        return fork

    # ------------------------------------------------------------------
    # Delegate mode support
    # ------------------------------------------------------------------

    def run_delegate_sandbox(
        self,
        task_id: str,
        command: str,
        image: str = "python:3.11",
        environment: dict[str, str] | None = None,
    ) -> SandboxRun | None:
        """Create a sandbox run record for delegate execution."""

        task = self._store.get_task(task_id)
        if task is None:
            return None

        run = SandboxRun(
            task_id=task.task_id,
            project_id=task.project_id,
            image=image,
            command=command,
            environment=environment or {},
            status="running",
            started_at=now_ts(),
        )
        run.updated_at = now_ts()
        self._store.save_sandbox_run(run)

        # Simulated execution completion with deterministic logs.
        run.status = "completed"
        run.stdout = f"executed: {command}"
        run.stderr = ""
        run.exit_code = 0
        run.completed_at = now_ts()
        run.updated_at = now_ts()
        self._store.save_sandbox_run(run)

        task.sandbox_run_id = run.sandbox_id
        task.updated_at = now_ts()
        self._store.save_task(task)

        return run

    def _create_worktree_for_task(self, task: BuilderTask) -> WorktreeRef:
        """Create and persist isolated worktree metadata for delegate tasks."""

        worktree_path = self._worktree_root / f"task-{task.task_id[:8]}"
        worktree_path.mkdir(parents=True, exist_ok=True)
        worktree = WorktreeRef(
            task_id=task.task_id,
            project_id=task.project_id,
            branch_name=f"builder/{task.task_id[:8]}",
            base_sha="HEAD",
            worktree_path=str(worktree_path),
        )
        worktree.updated_at = now_ts()
        self._store.save_worktree(worktree)
        return worktree

    def _has_completion_evidence(self, task: BuilderTask) -> bool:
        """Return whether a task has durable proof that completion is real."""
        if task.artifact_ids or task.proposal_ids or task.approval_ids or task.sandbox_run_id:
            return True
        evidence_keys = (
            "validation_result",
            "eval_bundle_id",
            "verified_no_artifact_reason",
        )
        return any(bool(task.metadata.get(key)) for key in evidence_keys)

    def _clear_completion_blockers(self, task: BuilderTask) -> None:
        """Remove progress-blocker metadata once a task reaches terminal state."""
        task.metadata.pop("progress_clamped_from", None)
        task.metadata.pop("completion_blocked_reason", None)

    # ------------------------------------------------------------------
    # Dispatch helpers
    # ------------------------------------------------------------------

    def progress_task(
        self,
        task_id: str,
        progress: int,
        current_step: str,
        tool_in_use: str = "",
        specialist_message: str | None = None,
    ) -> BuilderTask | None:
        """Update task progress and optionally invoke orchestrator routing."""

        task = self._store.get_task(task_id)
        if task is None:
            return None

        requested_progress = progress
        next_progress = max(0, min(progress, 100))
        terminal_statuses = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
        if (
            next_progress >= 100
            and task.status not in terminal_statuses
            and not self._has_completion_evidence(task)
        ):
            next_progress = 99
            task.metadata["progress_clamped_from"] = requested_progress
            task.metadata[
                "completion_blocked_reason"
            ] = (
                "Progress cannot reach 100 without completion evidence; use complete_task() "
                "or attach an artifact, proposal, approval, sandbox run, validation result, "
                "eval bundle, or verified no-artifact reason."
            )
        else:
            task.metadata.pop("progress_clamped_from", None)
            task.metadata.pop("completion_blocked_reason", None)

        task.progress = next_progress
        task.current_step = current_step
        task.tool_in_use = tool_in_use
        task.updated_at = now_ts()

        if specialist_message:
            specialist_payload = self._orchestrator.invoke_specialist(task, specialist_message)
            task.active_specialist = type(task.active_specialist)(specialist_payload["specialist"])

        self._store.save_task(task)

        self._events.publish(
            BuilderEventType.TASK_PROGRESS,
            session_id=task.session_id,
            task_id=task.task_id,
            payload={
                "progress": task.progress,
                "current_step": task.current_step,
                "tool_in_use": task.tool_in_use,
                "active_specialist": task.active_specialist.value,
                "progress_clamped_from": task.metadata.get("progress_clamped_from"),
                "completion_blocked_reason": task.metadata.get("completion_blocked_reason"),
            },
        )
        return task

    def check_privileged_action(
        self,
        task: BuilderTask,
        action: Any,
        description: str,
    ) -> bool:
        """Check grants for privileged action and log the decision."""

        allowed = self._permissions.is_action_allowed(task.project_id, task.task_id, action)
        self._permissions.log_action(
            task_id=task.task_id,
            project_id=task.project_id,
            action=action,
            allowed=allowed,
            details={"description": description},
        )
        return allowed
