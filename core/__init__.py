"""Core domain objects for AutoAgent — CI/CD for agents.

First-class objects: AgentGraphVersion, SkillVersion, ToolContractVersion,
PolicyPackVersion, EnvironmentSnapshot, GraderBundle, EvalCase,
CandidateVariant, ArchiveEntry, HandoffArtifact.
"""

from core.types import (
    AgentNodeType,
    AgentNode,
    EdgeType,
    AgentEdge,
    AgentGraphVersion,
    SkillVersion,
    ReplayMode,
    ToolContractVersion,
    PolicyPackVersion,
    EnvironmentSnapshot,
    SnapshotDiff,
    GraderType,
    GraderSpec,
    GraderBundle,
    EvalCase,
    EvalSuiteType,
    CandidateVariant,
    ArchiveRole,
    ArchiveEntry,
    JudgeVerdict,
    MetricLayer,
    LayeredMetric,
)
from core.handoff import HandoffArtifact, HandoffComparator
