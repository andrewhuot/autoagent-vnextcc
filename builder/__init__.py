"""Builder workspace backend package."""

from builder.artifacts import ArtifactCardFactory
from builder.events import BuilderEvent, BuilderEventType, EventBroker, event_to_dict, serialize_sse_event
from builder.execution import BuilderExecutionEngine
from builder.metrics import BuilderMetricsService, BuilderMetricsSnapshot
from builder.orchestrator import (
    BuilderOrchestrator,
    CoordinatorPlan,
    CoordinatorTask,
    HandoffRecord,
    WorkerCapability,
)
from builder.permissions import (
    ActionLogEntry,
    PermissionGrant,
    PermissionManager,
    TakeoverState,
)
from builder.projects import BuilderProjectManager
from builder.specialists import (
    SpecialistDefinition,
    detect_specialist_by_intent,
    get_specialist,
    list_specialists,
)
from builder.store import BuilderStore
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
    EvalBundle,
    ExecutionMode,
    PrivilegedAction,
    ReleaseCandidate,
    RiskLevel,
    SandboxRun,
    SpecialistRole,
    TaskStatus,
    TraceBookmark,
    WorktreeRef,
    new_id,
    now_ts,
)

__all__ = [
    "ActionLogEntry",
    "ApprovalRequest",
    "ApprovalScope",
    "ApprovalStatus",
    "ArtifactCardFactory",
    "ArtifactRef",
    "ArtifactType",
    "BuilderEvent",
    "BuilderEventType",
    "BuilderExecutionEngine",
    "BuilderMetricsService",
    "BuilderMetricsSnapshot",
    "BuilderOrchestrator",
    "BuilderProject",
    "BuilderProjectManager",
    "BuilderProposal",
    "BuilderSession",
    "BuilderStore",
    "BuilderTask",
    "CoordinatorPlan",
    "CoordinatorTask",
    "EvalBundle",
    "EventBroker",
    "ExecutionMode",
    "HandoffRecord",
    "PermissionGrant",
    "PermissionManager",
    "PrivilegedAction",
    "ReleaseCandidate",
    "RiskLevel",
    "SandboxRun",
    "SpecialistDefinition",
    "SpecialistRole",
    "TakeoverState",
    "TaskStatus",
    "TraceBookmark",
    "WorkerCapability",
    "WorktreeRef",
    "detect_specialist_by_intent",
    "event_to_dict",
    "get_specialist",
    "list_specialists",
    "new_id",
    "now_ts",
    "serialize_sse_event",
]
