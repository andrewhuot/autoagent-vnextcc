"""Core data model for the Builder Workspace.

This module defines the canonical enums and first-class objects used by the
Builder backend, API routes, and frontend type bindings.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExecutionMode(str, Enum):
    """Execution behavior for a builder task."""

    ASK = "ask"
    DRAFT = "draft"
    APPLY = "apply"
    DELEGATE = "delegate"


class TaskStatus(str, Enum):
    """Lifecycle state of a builder task."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactType(str, Enum):
    """Artifact kinds emitted by builder tasks."""

    PLAN = "plan"
    SOURCE_DIFF = "source_diff"
    ADK_GRAPH_DIFF = "adk_graph_diff"
    SKILL = "skill"
    GUARDRAIL = "guardrail"
    EVAL = "eval"
    TRACE_EVIDENCE = "trace_evidence"
    BENCHMARK = "benchmark"
    RELEASE = "release"


class ApprovalScope(str, Enum):
    """How long an approval grant should remain active."""

    ONCE = "once"
    TASK = "task"
    PROJECT = "project"


class SpecialistRole(str, Enum):
    """Specialist subagent roles used by the builder orchestrator."""

    ORCHESTRATOR = "orchestrator"
    BUILD_ENGINEER = "build_engineer"
    REQUIREMENTS_ANALYST = "requirements_analyst"
    PROMPT_ENGINEER = "prompt_engineer"
    ADK_ARCHITECT = "adk_architect"
    TOOL_ENGINEER = "tool_engineer"
    SKILL_AUTHOR = "skill_author"
    GUARDRAIL_AUTHOR = "guardrail_author"
    EVAL_AUTHOR = "eval_author"
    OPTIMIZATION_ENGINEER = "optimization_engineer"
    TRACE_ANALYST = "trace_analyst"
    DEPLOYMENT_ENGINEER = "deployment_engineer"
    RELEASE_MANAGER = "release_manager"


class ApprovalStatus(str, Enum):
    """Status values for approval requests."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RiskLevel(str, Enum):
    """Risk level used in plans and approvals."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PrivilegedAction(str, Enum):
    """Privileged actions that require explicit approval."""

    SOURCE_WRITE = "source_write"
    EXTERNAL_NETWORK = "external_network"
    SECRET_ACCESS = "secret_access"
    DEPLOYMENT = "deployment"
    BENCHMARK_SPEND = "benchmark_spend"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def now_ts() -> float:
    """Return the current UNIX timestamp in seconds."""

    return time.time()


def new_id() -> str:
    """Return a random UUID4 string suitable for object IDs."""

    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# First-class objects
# ---------------------------------------------------------------------------


@dataclass
class BuilderProject:
    """Persistent project workspace that sessions and tasks inherit from."""

    project_id: str = field(default_factory=new_id)
    name: str = ""
    description: str = ""
    root_path: str = "."
    master_instruction: str = ""
    folder_instructions: dict[str, str] = field(default_factory=dict)
    knowledge_files: list[str] = field(default_factory=list)
    buildtime_skills: list[str] = field(default_factory=list)
    runtime_skills: list[str] = field(default_factory=list)
    eval_defaults: dict[str, Any] = field(default_factory=dict)
    benchmark_defaults: dict[str, Any] = field(default_factory=dict)
    permission_defaults: dict[str, Any] = field(default_factory=dict)
    preferred_models: dict[str, str] = field(default_factory=dict)
    deployment_targets: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    archived: bool = False
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuilderSession:
    """Conversation container scoped to one builder project."""

    session_id: str = field(default_factory=new_id)
    project_id: str = ""
    title: str = ""
    mode: ExecutionMode = ExecutionMode.ASK
    active_specialist: SpecialistRole = SpecialistRole.ORCHESTRATOR
    status: str = "open"  # open | closed
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    closed_at: float | None = None
    message_count: int = 0
    task_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuilderTask:
    """Unit of work tracked and executed inside a builder session."""

    task_id: str = field(default_factory=new_id)
    session_id: str = ""
    project_id: str = ""
    title: str = ""
    description: str = ""
    mode: ExecutionMode = ExecutionMode.ASK
    status: TaskStatus = TaskStatus.PENDING
    active_specialist: SpecialistRole = SpecialistRole.ORCHESTRATOR
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    started_at: float | None = None
    paused_at: float | None = None
    completed_at: float | None = None
    elapsed_seconds: float = 0.0
    eta_seconds: float | None = None
    progress: int = 0
    current_step: str = ""
    tool_in_use: str = ""
    token_count: int = 0
    cost_usd: float = 0.0
    artifact_ids: list[str] = field(default_factory=list)
    proposal_ids: list[str] = field(default_factory=list)
    approval_ids: list[str] = field(default_factory=list)
    error: str | None = None
    parent_task_id: str | None = None
    duplicate_of_task_id: str | None = None
    forked_from_task_id: str | None = None
    worktree_ref: str | None = None
    sandbox_run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuilderProposal:
    """Pre-mutation proposal describing intended builder changes."""

    proposal_id: str = field(default_factory=new_id)
    task_id: str = ""
    session_id: str = ""
    project_id: str = ""
    goal: str = ""
    assumptions: list[str] = field(default_factory=list)
    targeted_artifacts: list[str] = field(default_factory=list)
    targeted_surfaces: list[str] = field(default_factory=list)
    expected_impact: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    required_approvals: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    status: str = "pending"  # pending | approved | rejected | revision_requested
    accepted: bool = False
    rejected: bool = False
    revision_count: int = 0
    revision_comments: list[str] = field(default_factory=list)


@dataclass
class ArtifactRef:
    """Reference to one generated artifact including provenance metadata."""

    artifact_id: str = field(default_factory=new_id)
    task_id: str = ""
    session_id: str = ""
    project_id: str = ""
    artifact_type: ArtifactType = ArtifactType.PLAN
    title: str = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    skills_used: list[str] = field(default_factory=list)
    source_versions: dict[str, str] = field(default_factory=dict)
    release_candidate_id: str | None = None
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    selected: bool = False
    comments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ApprovalRequest:
    """Request for human approval before a privileged action executes."""

    approval_id: str = field(default_factory=new_id)
    task_id: str = ""
    session_id: str = ""
    project_id: str = ""
    action: PrivilegedAction = PrivilegedAction.SOURCE_WRITE
    description: str = ""
    scope: ApprovalScope = ApprovalScope.ONCE
    status: ApprovalStatus = ApprovalStatus.PENDING
    risk_level: RiskLevel = RiskLevel.LOW
    details: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    resolved_at: float | None = None
    resolved_by: str | None = None
    expires_at: float | None = None


@dataclass
class WorktreeRef:
    """Isolated git worktree metadata for delegate-mode tasks."""

    worktree_id: str = field(default_factory=new_id)
    task_id: str = ""
    project_id: str = ""
    branch_name: str = ""
    base_sha: str = ""
    worktree_path: str = ""
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    merged_at: float | None = None
    abandoned_at: float | None = None
    diff_stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class SandboxRun:
    """Metadata for one sandboxed delegate execution."""

    sandbox_id: str = field(default_factory=new_id)
    task_id: str = ""
    project_id: str = ""
    image: str = ""
    command: str = ""
    environment: dict[str, str] = field(default_factory=dict)
    status: str = "pending"  # pending | running | completed | failed | cancelled
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    started_at: float | None = None
    completed_at: float | None = None
    cost_usd: float = 0.0


@dataclass
class EvalBundle:
    """Eval summary bundle attached to a mutating builder task."""

    bundle_id: str = field(default_factory=new_id)
    task_id: str = ""
    session_id: str = ""
    project_id: str = ""
    eval_run_ids: list[str] = field(default_factory=list)
    baseline_scores: dict[str, float] = field(default_factory=dict)
    candidate_scores: dict[str, float] = field(default_factory=dict)
    hard_gate_passed: bool = False
    trajectory_quality: float = 0.0
    outcome_quality: float = 0.0
    eval_coverage_pct: float = 0.0
    cost_delta_pct: float = 0.0
    latency_delta_pct: float = 0.0
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    notes: str = ""


@dataclass
class TraceBookmark:
    """Pinned trace evidence promoted during builder investigation."""

    bookmark_id: str = field(default_factory=new_id)
    task_id: str = ""
    session_id: str = ""
    project_id: str = ""
    trace_id: str = ""
    span_id: str = ""
    label: str = ""
    failure_family: str = ""
    blame_target: str = ""
    evidence_links: list[str] = field(default_factory=list)
    promoted_to_eval: bool = False
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    notes: str = ""


class ReleaseStatus(str, Enum):
    """Lifecycle states for release candidates.

    Matches the PRD promotion model:
    Draft → Reviewed → Candidate → Staging → Production → Archived
    Plus rolled_back as an exit state from any active stage.
    """

    DRAFT = "draft"
    REVIEWED = "reviewed"
    CANDIDATE = "candidate"
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"
    ROLLED_BACK = "rolled_back"


# Valid forward transitions in the promotion lifecycle.
RELEASE_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"reviewed", "archived"},
    "reviewed": {"candidate", "draft", "archived"},
    "candidate": {"staging", "reviewed", "archived"},
    "staging": {"production", "candidate", "rolled_back"},
    "production": {"archived", "rolled_back"},
    "archived": set(),
    "rolled_back": {"draft"},
}


@dataclass
class ReleaseCandidate:
    """Release artifact linking changes, evals, and deployment target."""

    release_id: str = field(default_factory=new_id)
    task_id: str = ""
    session_id: str = ""
    project_id: str = ""
    version: str = ""
    artifact_ids: list[str] = field(default_factory=list)
    eval_bundle_id: str | None = None
    status: str = "draft"
    deployment_target: str = ""
    created_at: float = field(default_factory=now_ts)
    updated_at: float = field(default_factory=now_ts)
    approved_at: float | None = None
    approved_by: str | None = None
    deployed_at: float | None = None
    rolled_back_at: float | None = None
    rollback_from_id: str | None = None
    changelog: str = ""
    promotion_evidence: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ExecutionMode",
    "TaskStatus",
    "ArtifactType",
    "ApprovalScope",
    "SpecialistRole",
    "ApprovalStatus",
    "RiskLevel",
    "PrivilegedAction",
    "ReleaseStatus",
    "RELEASE_TRANSITIONS",
    "BuilderProject",
    "BuilderSession",
    "BuilderTask",
    "BuilderProposal",
    "ArtifactRef",
    "ApprovalRequest",
    "WorktreeRef",
    "SandboxRun",
    "EvalBundle",
    "TraceBookmark",
    "ReleaseCandidate",
    "now_ts",
    "new_id",
]
