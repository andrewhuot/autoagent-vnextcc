"""SQLite persistence layer for Builder Workspace objects."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from builder.types import (
    ApprovalRequest,
    ApprovalScope,
    ApprovalStatus,
    ArtifactRef,
    ArtifactType,
    BuilderProject,
    BuilderProposal,
    BuilderSession,
    BuilderTask,
    CoordinatorExecutionRun,
    CoordinatorExecutionStatus,
    EvalBundle,
    ExecutionMode,
    PrivilegedAction,
    ReleaseCandidate,
    RiskLevel,
    SandboxRun,
    SpecialistRole,
    TaskStatus,
    TraceBookmark,
    WorkerExecutionResult,
    WorkerExecutionState,
    WorkerExecutionStatus,
    WorktreeRef,
)

T = TypeVar("T")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def _serialize(model: Any) -> str:
    return json.dumps(asdict(model), default=_json_default, sort_keys=True)


def _deserialize(payload: str) -> dict[str, Any]:
    return json.loads(payload)


def _enum(enum_cls: type[Enum], value: Any, fallback: Enum) -> Enum:
    try:
        return enum_cls(value)
    except Exception:
        return fallback


def _hydrate_project(payload: dict[str, Any]) -> BuilderProject:
    model = BuilderProject()
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    return model


def _hydrate_session(payload: dict[str, Any]) -> BuilderSession:
    model = BuilderSession()
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    model.mode = _enum(ExecutionMode, payload.get("mode", model.mode), model.mode)  # type: ignore[assignment]
    model.active_specialist = _enum(
        SpecialistRole,
        payload.get("active_specialist", model.active_specialist),
        model.active_specialist,
    )  # type: ignore[assignment]
    return model


def _hydrate_task(payload: dict[str, Any]) -> BuilderTask:
    model = BuilderTask()
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    model.mode = _enum(ExecutionMode, payload.get("mode", model.mode), model.mode)  # type: ignore[assignment]
    model.status = _enum(TaskStatus, payload.get("status", model.status), model.status)  # type: ignore[assignment]
    model.active_specialist = _enum(
        SpecialistRole,
        payload.get("active_specialist", model.active_specialist),
        model.active_specialist,
    )  # type: ignore[assignment]
    return model


def _hydrate_proposal(payload: dict[str, Any]) -> BuilderProposal:
    model = BuilderProposal()
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    model.risk_level = _enum(RiskLevel, payload.get("risk_level", model.risk_level), model.risk_level)  # type: ignore[assignment]
    return model


def _hydrate_artifact(payload: dict[str, Any]) -> ArtifactRef:
    model = ArtifactRef()
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    model.artifact_type = _enum(
        ArtifactType,
        payload.get("artifact_type", model.artifact_type),
        model.artifact_type,
    )  # type: ignore[assignment]
    return model


def _hydrate_approval(payload: dict[str, Any]) -> ApprovalRequest:
    model = ApprovalRequest()
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    model.action = _enum(PrivilegedAction, payload.get("action", model.action), model.action)  # type: ignore[assignment]
    model.scope = _enum(ApprovalScope, payload.get("scope", model.scope), model.scope)  # type: ignore[assignment]
    model.status = _enum(ApprovalStatus, payload.get("status", model.status), model.status)  # type: ignore[assignment]
    model.risk_level = _enum(RiskLevel, payload.get("risk_level", model.risk_level), model.risk_level)  # type: ignore[assignment]
    return model


def _hydrate_worktree(payload: dict[str, Any]) -> WorktreeRef:
    model = WorktreeRef()
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    return model


def _hydrate_sandbox(payload: dict[str, Any]) -> SandboxRun:
    model = SandboxRun()
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    return model


def _hydrate_eval_bundle(payload: dict[str, Any]) -> EvalBundle:
    model = EvalBundle()
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    return model


def _hydrate_trace_bookmark(payload: dict[str, Any]) -> TraceBookmark:
    model = TraceBookmark()
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    return model


def _hydrate_release(payload: dict[str, Any]) -> ReleaseCandidate:
    model = ReleaseCandidate()
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    return model


def _hydrate_worker_result(payload: dict[str, Any]) -> WorkerExecutionResult:
    model = WorkerExecutionResult(
        node_id=str(payload.get("node_id") or ""),
        worker_role=_enum(
            SpecialistRole,
            payload.get("worker_role", SpecialistRole.ORCHESTRATOR.value),
            SpecialistRole.ORCHESTRATOR,
        ),  # type: ignore[arg-type]
    )
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    model.worker_role = _enum(
        SpecialistRole,
        payload.get("worker_role", model.worker_role),
        model.worker_role,
    )  # type: ignore[assignment]
    return model


def _hydrate_worker_state(payload: dict[str, Any]) -> WorkerExecutionState:
    model = WorkerExecutionState(
        node_id=str(payload.get("node_id") or ""),
        worker_role=_enum(
            SpecialistRole,
            payload.get("worker_role", SpecialistRole.ORCHESTRATOR.value),
            SpecialistRole.ORCHESTRATOR,
        ),  # type: ignore[arg-type]
    )
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    model.worker_role = _enum(
        SpecialistRole,
        payload.get("worker_role", model.worker_role),
        model.worker_role,
    )  # type: ignore[assignment]
    model.status = _enum(
        WorkerExecutionStatus,
        payload.get("status", model.status),
        model.status,
    )  # type: ignore[assignment]
    result = payload.get("result")
    model.result = _hydrate_worker_result(result) if isinstance(result, dict) else None
    return model


def _hydrate_coordinator_run(payload: dict[str, Any]) -> CoordinatorExecutionRun:
    model = CoordinatorExecutionRun()
    for key, value in payload.items():
        if hasattr(model, key):
            setattr(model, key, value)
    model.status = _enum(
        CoordinatorExecutionStatus,
        payload.get("status", model.status),
        model.status,
    )  # type: ignore[assignment]
    model.worker_states = [
        _hydrate_worker_state(worker)
        for worker in payload.get("worker_states", [])
        if isinstance(worker, dict)
    ]
    return model


class BuilderStore:
    """SQLite store for all Builder first-class objects."""

    def __init__(self, db_path: str = ".agentlab/builder.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with _connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS builder_projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    archived INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_builder_projects_updated
                    ON builder_projects(updated_at DESC);

                CREATE TABLE IF NOT EXISTS builder_sessions (
                    session_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_builder_sessions_project
                    ON builder_sessions(project_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS builder_tasks (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_builder_tasks_session
                    ON builder_tasks(session_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_builder_tasks_project
                    ON builder_tasks(project_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS builder_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_builder_proposals_task
                    ON builder_proposals(task_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS builder_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_builder_artifacts_task
                    ON builder_artifacts(task_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS builder_approvals (
                    approval_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_builder_approvals_task
                    ON builder_approvals(task_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS builder_worktrees (
                    worktree_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS builder_sandbox_runs (
                    sandbox_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS builder_eval_bundles (
                    bundle_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS builder_trace_bookmarks (
                    bookmark_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS builder_release_candidates (
                    release_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS builder_coordinator_runs (
                    run_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    root_task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_builder_coord_runs_plan
                    ON builder_coordinator_runs(plan_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_builder_coord_runs_task
                    ON builder_coordinator_runs(root_task_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_builder_coord_runs_session
                    ON builder_coordinator_runs(session_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_builder_coord_runs_status
                    ON builder_coordinator_runs(status, created_at DESC);
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def save_project(self, project: BuilderProject) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO builder_projects
                    (project_id, name, archived, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project.project_id,
                    project.name,
                    int(project.archived),
                    project.created_at,
                    project.updated_at,
                    _serialize(project),
                ),
            )
            conn.commit()

    def get_project(self, project_id: str) -> BuilderProject | None:
        row = self._get_one("builder_projects", "project_id", project_id)
        if row is None:
            return None
        return _hydrate_project(_deserialize(row["payload"]))

    def list_projects(self, archived: bool | None = None, limit: int = 100) -> list[BuilderProject]:
        params: list[Any] = []
        where = ""
        if archived is not None:
            where = "WHERE archived = ?"
            params.append(int(archived))
        params.append(limit)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM builder_projects {where} ORDER BY updated_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_hydrate_project(_deserialize(row["payload"])) for row in rows]

    def delete_project(self, project_id: str) -> bool:
        return self._delete_one("builder_projects", "project_id", project_id)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def save_session(self, session: BuilderSession) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO builder_sessions
                    (session_id, project_id, status, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.project_id,
                    session.status,
                    session.created_at,
                    session.updated_at,
                    _serialize(session),
                ),
            )
            conn.commit()

    def get_session(self, session_id: str) -> BuilderSession | None:
        row = self._get_one("builder_sessions", "session_id", session_id)
        if row is None:
            return None
        return _hydrate_session(_deserialize(row["payload"]))

    def list_sessions(
        self,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[BuilderSession]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM builder_sessions {where} ORDER BY updated_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_hydrate_session(_deserialize(row["payload"])) for row in rows]

    def delete_session(self, session_id: str) -> bool:
        return self._delete_one("builder_sessions", "session_id", session_id)

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def save_task(self, task: BuilderTask) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO builder_tasks
                    (task_id, session_id, project_id, status, mode, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.session_id,
                    task.project_id,
                    task.status.value,
                    task.mode.value,
                    task.created_at,
                    task.updated_at,
                    _serialize(task),
                ),
            )
            conn.commit()

    def get_task(self, task_id: str) -> BuilderTask | None:
        row = self._get_one("builder_tasks", "task_id", task_id)
        if row is None:
            return None
        return _hydrate_task(_deserialize(row["payload"]))

    def list_tasks(
        self,
        session_id: str | None = None,
        project_id: str | None = None,
        status: TaskStatus | None = None,
        limit: int = 100,
    ) -> list[BuilderTask]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM builder_tasks {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_hydrate_task(_deserialize(row["payload"])) for row in rows]

    def delete_task(self, task_id: str) -> bool:
        return self._delete_one("builder_tasks", "task_id", task_id)

    # ------------------------------------------------------------------
    # Proposals
    # ------------------------------------------------------------------

    def save_proposal(self, proposal: BuilderProposal) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO builder_proposals
                    (proposal_id, task_id, session_id, project_id, status, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.proposal_id,
                    proposal.task_id,
                    proposal.session_id,
                    proposal.project_id,
                    proposal.status,
                    proposal.created_at,
                    proposal.updated_at,
                    _serialize(proposal),
                ),
            )
            conn.commit()

    def get_proposal(self, proposal_id: str) -> BuilderProposal | None:
        row = self._get_one("builder_proposals", "proposal_id", proposal_id)
        if row is None:
            return None
        return _hydrate_proposal(_deserialize(row["payload"]))

    def list_proposals(
        self,
        task_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[BuilderProposal]:
        clauses: list[str] = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM builder_proposals {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_hydrate_proposal(_deserialize(row["payload"])) for row in rows]

    def delete_proposal(self, proposal_id: str) -> bool:
        return self._delete_one("builder_proposals", "proposal_id", proposal_id)

    # ------------------------------------------------------------------
    # Artifacts
    # ------------------------------------------------------------------

    def save_artifact(self, artifact: ArtifactRef) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO builder_artifacts
                    (artifact_id, task_id, session_id, project_id, artifact_type, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.task_id,
                    artifact.session_id,
                    artifact.project_id,
                    artifact.artifact_type.value,
                    artifact.created_at,
                    artifact.updated_at,
                    _serialize(artifact),
                ),
            )
            conn.commit()

    def get_artifact(self, artifact_id: str) -> ArtifactRef | None:
        row = self._get_one("builder_artifacts", "artifact_id", artifact_id)
        if row is None:
            return None
        return _hydrate_artifact(_deserialize(row["payload"]))

    def list_artifacts(
        self,
        task_id: str | None = None,
        session_id: str | None = None,
        artifact_type: ArtifactType | None = None,
        limit: int = 100,
    ) -> list[ArtifactRef]:
        clauses: list[str] = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if artifact_type is not None:
            clauses.append("artifact_type = ?")
            params.append(artifact_type.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM builder_artifacts {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_hydrate_artifact(_deserialize(row["payload"])) for row in rows]

    def delete_artifact(self, artifact_id: str) -> bool:
        return self._delete_one("builder_artifacts", "artifact_id", artifact_id)

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------

    def save_approval(self, approval: ApprovalRequest) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO builder_approvals
                    (approval_id, task_id, session_id, project_id, status, action, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.approval_id,
                    approval.task_id,
                    approval.session_id,
                    approval.project_id,
                    approval.status.value,
                    approval.action.value,
                    approval.created_at,
                    approval.updated_at,
                    _serialize(approval),
                ),
            )
            conn.commit()

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        row = self._get_one("builder_approvals", "approval_id", approval_id)
        if row is None:
            return None
        return _hydrate_approval(_deserialize(row["payload"]))

    def list_approvals(
        self,
        task_id: str | None = None,
        session_id: str | None = None,
        status: ApprovalStatus | None = None,
        limit: int = 100,
    ) -> list[ApprovalRequest]:
        clauses: list[str] = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM builder_approvals {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_hydrate_approval(_deserialize(row["payload"])) for row in rows]

    def delete_approval(self, approval_id: str) -> bool:
        return self._delete_one("builder_approvals", "approval_id", approval_id)

    # ------------------------------------------------------------------
    # Worktrees
    # ------------------------------------------------------------------

    def save_worktree(self, worktree: WorktreeRef) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO builder_worktrees
                    (worktree_id, task_id, project_id, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    worktree.worktree_id,
                    worktree.task_id,
                    worktree.project_id,
                    worktree.created_at,
                    worktree.updated_at,
                    _serialize(worktree),
                ),
            )
            conn.commit()

    def get_worktree(self, worktree_id: str) -> WorktreeRef | None:
        row = self._get_one("builder_worktrees", "worktree_id", worktree_id)
        if row is None:
            return None
        return _hydrate_worktree(_deserialize(row["payload"]))

    def list_worktrees(self, task_id: str | None = None, limit: int = 100) -> list[WorktreeRef]:
        params: list[Any] = []
        where = ""
        if task_id is not None:
            where = "WHERE task_id = ?"
            params.append(task_id)
        params.append(limit)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM builder_worktrees {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_hydrate_worktree(_deserialize(row["payload"])) for row in rows]

    def delete_worktree(self, worktree_id: str) -> bool:
        return self._delete_one("builder_worktrees", "worktree_id", worktree_id)

    # ------------------------------------------------------------------
    # Sandbox runs
    # ------------------------------------------------------------------

    def save_sandbox_run(self, run: SandboxRun) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO builder_sandbox_runs
                    (sandbox_id, task_id, project_id, status, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.sandbox_id,
                    run.task_id,
                    run.project_id,
                    run.status,
                    run.created_at,
                    run.updated_at,
                    _serialize(run),
                ),
            )
            conn.commit()

    def get_sandbox_run(self, sandbox_id: str) -> SandboxRun | None:
        row = self._get_one("builder_sandbox_runs", "sandbox_id", sandbox_id)
        if row is None:
            return None
        return _hydrate_sandbox(_deserialize(row["payload"]))

    def list_sandbox_runs(
        self,
        task_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[SandboxRun]:
        clauses: list[str] = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM builder_sandbox_runs {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_hydrate_sandbox(_deserialize(row["payload"])) for row in rows]

    def delete_sandbox_run(self, sandbox_id: str) -> bool:
        return self._delete_one("builder_sandbox_runs", "sandbox_id", sandbox_id)

    # ------------------------------------------------------------------
    # Eval bundles
    # ------------------------------------------------------------------

    def save_eval_bundle(self, bundle: EvalBundle) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO builder_eval_bundles
                    (bundle_id, task_id, session_id, project_id, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bundle.bundle_id,
                    bundle.task_id,
                    bundle.session_id,
                    bundle.project_id,
                    bundle.created_at,
                    bundle.updated_at,
                    _serialize(bundle),
                ),
            )
            conn.commit()

    def get_eval_bundle(self, bundle_id: str) -> EvalBundle | None:
        row = self._get_one("builder_eval_bundles", "bundle_id", bundle_id)
        if row is None:
            return None
        return _hydrate_eval_bundle(_deserialize(row["payload"]))

    def list_eval_bundles(
        self,
        task_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[EvalBundle]:
        clauses: list[str] = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM builder_eval_bundles {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_hydrate_eval_bundle(_deserialize(row["payload"])) for row in rows]

    def delete_eval_bundle(self, bundle_id: str) -> bool:
        return self._delete_one("builder_eval_bundles", "bundle_id", bundle_id)

    # ------------------------------------------------------------------
    # Trace bookmarks
    # ------------------------------------------------------------------

    def save_trace_bookmark(self, bookmark: TraceBookmark) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO builder_trace_bookmarks
                    (bookmark_id, task_id, session_id, project_id, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bookmark.bookmark_id,
                    bookmark.task_id,
                    bookmark.session_id,
                    bookmark.project_id,
                    bookmark.created_at,
                    bookmark.updated_at,
                    _serialize(bookmark),
                ),
            )
            conn.commit()

    def get_trace_bookmark(self, bookmark_id: str) -> TraceBookmark | None:
        row = self._get_one("builder_trace_bookmarks", "bookmark_id", bookmark_id)
        if row is None:
            return None
        return _hydrate_trace_bookmark(_deserialize(row["payload"]))

    def list_trace_bookmarks(
        self,
        task_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[TraceBookmark]:
        clauses: list[str] = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM builder_trace_bookmarks {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_hydrate_trace_bookmark(_deserialize(row["payload"])) for row in rows]

    def delete_trace_bookmark(self, bookmark_id: str) -> bool:
        return self._delete_one("builder_trace_bookmarks", "bookmark_id", bookmark_id)

    # ------------------------------------------------------------------
    # Release candidates
    # ------------------------------------------------------------------

    def save_release(self, release: ReleaseCandidate) -> None:
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO builder_release_candidates
                    (release_id, task_id, session_id, project_id, status, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    release.release_id,
                    release.task_id,
                    release.session_id,
                    release.project_id,
                    release.status,
                    release.created_at,
                    release.updated_at,
                    _serialize(release),
                ),
            )
            conn.commit()

    def get_release(self, release_id: str) -> ReleaseCandidate | None:
        row = self._get_one("builder_release_candidates", "release_id", release_id)
        if row is None:
            return None
        return _hydrate_release(_deserialize(row["payload"]))

    def list_releases(
        self,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ReleaseCandidate]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM builder_release_candidates {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_hydrate_release(_deserialize(row["payload"])) for row in rows]

    def delete_release(self, release_id: str) -> bool:
        return self._delete_one("builder_release_candidates", "release_id", release_id)

    # ------------------------------------------------------------------
    # Coordinator runs
    # ------------------------------------------------------------------

    def save_coordinator_run(self, run: CoordinatorExecutionRun) -> None:
        """Persist a coordinator run so worker lifecycle state survives restarts."""
        with _connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO builder_coordinator_runs
                    (run_id, plan_id, root_task_id, session_id, project_id, status, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.plan_id,
                    run.root_task_id,
                    run.session_id,
                    run.project_id,
                    run.status.value,
                    run.created_at,
                    run.updated_at,
                    _serialize(run),
                ),
            )
            conn.commit()

    def get_coordinator_run(self, run_id: str) -> CoordinatorExecutionRun | None:
        """Load one coordinator run for API inspection."""
        row = self._get_one("builder_coordinator_runs", "run_id", run_id)
        if row is None:
            return None
        return _hydrate_coordinator_run(_deserialize(row["payload"]))

    def list_coordinator_runs(
        self,
        plan_id: str | None = None,
        root_task_id: str | None = None,
        session_id: str | None = None,
        status: CoordinatorExecutionStatus | None = None,
        limit: int = 100,
    ) -> list[CoordinatorExecutionRun]:
        """Return persisted coordinator runs scoped by plan, task, session, or status."""
        clauses: list[str] = []
        params: list[Any] = []
        if plan_id is not None:
            clauses.append("plan_id = ?")
            params.append(plan_id)
        if root_task_id is not None:
            clauses.append("root_task_id = ?")
            params.append(root_task_id)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT payload FROM builder_coordinator_runs {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [_hydrate_coordinator_run(_deserialize(row["payload"])) for row in rows]

    def delete_coordinator_run(self, run_id: str) -> bool:
        """Delete one coordinator run."""
        return self._delete_one("builder_coordinator_runs", "run_id", run_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_one(self, table: str, id_field: str, object_id: str) -> sqlite3.Row | None:
        with _connect(self.db_path) as conn:
            return conn.execute(
                f"SELECT * FROM {table} WHERE {id_field} = ?",
                (object_id,),
            ).fetchone()

    def _delete_one(self, table: str, id_field: str, object_id: str) -> bool:
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE {id_field} = ?",
                (object_id,),
            )
            conn.commit()
        return cursor.rowcount > 0
