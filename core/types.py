"""Canonical domain objects for the AutoAgent experimentation system.

These are framework-neutral internal representations that form the backbone
of the CI/CD-for-agents architecture.  Every object is versioned, immutable
once persisted, and serialisable to JSON/SQLite.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Agent Graph IR
# ---------------------------------------------------------------------------

class AgentNodeType(str, Enum):
    """Typed nodes in the agent graph."""
    router = "router"
    specialist = "specialist"
    guardrail = "guardrail"
    skill = "skill"
    memory = "memory"
    tool_contract = "tool_contract"
    handoff_schema = "handoff_schema"
    judge = "judge"


@dataclass
class AgentNode:
    """A single node in the agent graph IR."""
    node_id: str
    node_type: AgentNodeType
    name: str
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "name": self.name,
            "config": self.config,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentNode":
        return cls(
            node_id=d["node_id"],
            node_type=AgentNodeType(d["node_type"]),
            name=d["name"],
            config=d.get("config", {}),
            metadata=d.get("metadata", {}),
        )


class EdgeType(str, Enum):
    """Typed edges connecting agent graph nodes."""
    routes_to = "routes_to"
    delegates_to = "delegates_to"
    guards = "guards"
    uses_tool = "uses_tool"
    reads_memory = "reads_memory"
    writes_memory = "writes_memory"
    hands_off_to = "hands_off_to"
    judged_by = "judged_by"


@dataclass
class AgentEdge:
    """A directed edge in the agent graph IR."""
    source_id: str
    target_id: str
    edge_type: EdgeType
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentEdge":
        return cls(
            source_id=d["source_id"],
            target_id=d["target_id"],
            edge_type=EdgeType(d["edge_type"]),
            metadata=d.get("metadata", {}),
        )


@dataclass
class AgentGraphVersion:
    """Framework-neutral intermediate representation for an agent system.

    The graph captures the full topology: routers, specialists, guardrails,
    skills, memory, tool contracts, handoff schemas, and judges — plus the
    edges that connect them.
    """
    version_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    nodes: list[AgentNode] = field(default_factory=list)
    edges: list[AgentEdge] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_version_id: Optional[str] = None

    @property
    def content_hash(self) -> str:
        """Deterministic hash of the graph content (excludes version_id and created_at)."""
        payload = json.dumps(
            {"nodes": [n.to_dict() for n in self.nodes],
             "edges": [e.to_dict() for e in self.edges]},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def validate(self) -> list[str]:
        """Validate graph integrity and return a list of error messages."""
        errors: list[str] = []
        node_ids = [node.node_id for node in self.nodes]
        node_id_set = set(node_ids)

        if len(node_ids) != len(node_id_set):
            errors.append("Duplicate node_id values detected in AgentGraphVersion")

        for edge in self.edges:
            if edge.source_id not in node_id_set:
                errors.append(
                    f"Edge source '{edge.source_id}' is missing from graph nodes"
                )
            if edge.target_id not in node_id_set:
                errors.append(
                    f"Edge target '{edge.target_id}' is missing from graph nodes"
                )

        return errors

    def get_nodes_by_type(self, node_type: AgentNodeType) -> list[AgentNode]:
        return [n for n in self.nodes if n.node_type == node_type]

    def get_node(self, node_id: str) -> Optional[AgentNode]:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None

    def get_edges_from(self, node_id: str) -> list[AgentEdge]:
        return [e for e in self.edges if e.source_id == node_id]

    def get_edges_to(self, node_id: str) -> list[AgentEdge]:
        return [e for e in self.edges if e.target_id == node_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "created_at": self.created_at,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "metadata": self.metadata,
            "parent_version_id": self.parent_version_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentGraphVersion":
        return cls(
            version_id=d["version_id"],
            created_at=d["created_at"],
            nodes=[AgentNode.from_dict(n) for n in d.get("nodes", [])],
            edges=[AgentEdge.from_dict(e) for e in d.get("edges", [])],
            metadata=d.get("metadata", {}),
            parent_version_id=d.get("parent_version_id"),
        )


# ---------------------------------------------------------------------------
# Skill Version
# ---------------------------------------------------------------------------

@dataclass
class SkillVersion:
    """A versioned bundle of instructions, scripts, and assets.

    Follows the OpenAI/Anthropic skills/procedures pattern: a skill is a
    self-contained unit of agent capability that can be added, removed,
    or updated independently.
    """
    skill_id: str
    version: str
    name: str
    instructions: str = ""
    scripts: dict[str, str] = field(default_factory=dict)
    assets: dict[str, Any] = field(default_factory=dict)
    validators: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            {"instructions": self.instructions, "scripts": self.scripts,
             "assets": self.assets, "validators": self.validators},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "version": self.version,
            "name": self.name,
            "instructions": self.instructions,
            "scripts": self.scripts,
            "assets": self.assets,
            "validators": self.validators,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Replay Mode (richer than 4-class SideEffectClass)
# ---------------------------------------------------------------------------

class ReplayMode(str, Enum):
    """Five replay modes per tool — replaces the flat SideEffectClass."""
    deterministic_stub = "deterministic_stub"
    recorded_stub_with_freshness = "recorded_stub_with_freshness"
    live_sandbox_clone = "live_sandbox_clone"
    simulator = "simulator"
    forbidden = "forbidden"


# ---------------------------------------------------------------------------
# Tool Contract Version
# ---------------------------------------------------------------------------

@dataclass
class ToolContractVersion:
    """Full contract for a tool: schema, replay behaviour, sandbox policy.

    This replaces the simpler ToolClassification with a richer contract
    that captures everything needed for safe, faithful replay.
    """
    tool_name: str
    version: str = "1"
    schema: dict[str, Any] = field(default_factory=dict)
    side_effect_class: str = "pure"  # backward compat with SideEffectClass
    replay_mode: ReplayMode = ReplayMode.deterministic_stub
    validator: Optional[str] = None  # name of validation function
    sandbox_policy: dict[str, Any] = field(default_factory=dict)
    freshness_window_seconds: Optional[int] = None
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_replayable_at(
        self,
        *,
        now_epoch: float,
        recorded_at_epoch: float | None = None,
    ) -> bool:
        """Return whether this tool can be replayed at ``now_epoch``.

        For ``recorded_stub_with_freshness``, replayability depends on
        ``freshness_window_seconds`` and ``recorded_at_epoch``.
        """
        if self.replay_mode == ReplayMode.forbidden:
            return False

        if self.replay_mode == ReplayMode.recorded_stub_with_freshness:
            if recorded_at_epoch is None:
                return False
            if self.freshness_window_seconds is None:
                return True
            age_seconds = max(0.0, now_epoch - recorded_at_epoch)
            return age_seconds <= float(self.freshness_window_seconds)

        return True

    @property
    def can_auto_replay(self) -> bool:
        return self.replay_mode in (
            ReplayMode.deterministic_stub,
            ReplayMode.recorded_stub_with_freshness,
            ReplayMode.simulator,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "version": self.version,
            "schema": self.schema,
            "side_effect_class": self.side_effect_class,
            "replay_mode": self.replay_mode.value,
            "validator": self.validator,
            "sandbox_policy": self.sandbox_policy,
            "freshness_window_seconds": self.freshness_window_seconds,
            "description": self.description,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ToolContractVersion":
        return cls(
            tool_name=d["tool_name"],
            version=d.get("version", "1"),
            schema=d.get("schema", {}),
            side_effect_class=d.get("side_effect_class", "pure"),
            replay_mode=ReplayMode(d.get("replay_mode", "deterministic_stub")),
            validator=d.get("validator"),
            sandbox_policy=d.get("sandbox_policy", {}),
            freshness_window_seconds=d.get("freshness_window_seconds"),
            description=d.get("description", ""),
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Policy Pack Version
# ---------------------------------------------------------------------------

@dataclass
class PolicyPackVersion:
    """Deployable safety / governance configuration.

    Policies are tested (not just enforced): the eval compiler generates
    adversarial cases against each policy rule.
    """
    pack_id: str
    version: str
    name: str
    safety_rules: list[dict[str, Any]] = field(default_factory=list)
    guardrail_thresholds: dict[str, float] = field(default_factory=dict)
    authorization_policies: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "version": self.version,
            "name": self.name,
            "safety_rules": self.safety_rules,
            "guardrail_thresholds": self.guardrail_thresholds,
            "authorization_policies": self.authorization_policies,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Environment Snapshot
# ---------------------------------------------------------------------------

@dataclass
class EnvironmentSnapshot:
    """Captured state of external systems for deterministic replay.

    Each snapshot is a frozen view of the world at a point in time,
    enabling end-state evaluation by comparing expected vs actual snapshots.
    """
    snapshot_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    state: dict[str, Any] = field(default_factory=dict)
    source: str = ""  # e.g. "orders_db", "crm", "knowledge_base"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "state": self.state,
            "source": self.source,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EnvironmentSnapshot":
        return cls(
            snapshot_id=d.get("snapshot_id", uuid.uuid4().hex[:12]),
            created_at=d.get("created_at", ""),
            state=d.get("state", {}),
            source=d.get("source", ""),
            metadata=d.get("metadata", {}),
        )


@dataclass
class SnapshotDiff:
    """Difference between two environment snapshots."""
    expected_snapshot_id: str
    actual_snapshot_id: str
    added_keys: list[str] = field(default_factory=list)
    removed_keys: list[str] = field(default_factory=list)
    changed_keys: dict[str, dict[str, Any]] = field(default_factory=dict)  # key -> {expected, actual}
    match_score: float = 0.0  # 0-1, fraction of matching fields

    @classmethod
    def compute(cls, expected: EnvironmentSnapshot, actual: EnvironmentSnapshot) -> "SnapshotDiff":
        """Compute the diff between expected and actual snapshots."""
        exp_keys = set(expected.state.keys())
        act_keys = set(actual.state.keys())
        added = sorted(act_keys - exp_keys)
        removed = sorted(exp_keys - act_keys)
        common = exp_keys & act_keys
        changed: dict[str, dict[str, Any]] = {}
        matching = 0
        for k in sorted(common):
            if expected.state[k] == actual.state[k]:
                matching += 1
            else:
                changed[k] = {"expected": expected.state[k], "actual": actual.state[k]}
        total = len(exp_keys | act_keys) or 1
        return cls(
            expected_snapshot_id=expected.snapshot_id,
            actual_snapshot_id=actual.snapshot_id,
            added_keys=added,
            removed_keys=removed,
            changed_keys=changed,
            match_score=matching / total,
        )


# ---------------------------------------------------------------------------
# Grader Bundle
# ---------------------------------------------------------------------------

class GraderType(str, Enum):
    """Types of graders in the ordered stack."""
    deterministic = "deterministic"
    rule_based = "rule_based"
    llm_judge = "llm_judge"
    audit_judge = "audit_judge"
    human_review = "human_review"


@dataclass
class GraderSpec:
    """Specification for a single grader in the bundle."""
    grader_type: GraderType
    grader_id: str
    config: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    required: bool = False  # if True, must pass for overall pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "grader_type": self.grader_type.value,
            "grader_id": self.grader_id,
            "config": self.config,
            "weight": self.weight,
            "required": self.required,
        }


@dataclass
class GraderBundle:
    """Ordered grader stack per eval case.

    Execution order: deterministic → rule-based → LLM judge → human review flag.
    Early-exit on deterministic failure if grader is marked required.
    """
    bundle_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    graders: list[GraderSpec] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_graders_by_type(self, grader_type: GraderType) -> list[GraderSpec]:
        return [g for g in self.graders if g.grader_type == grader_type]

    @property
    def has_human_review(self) -> bool:
        return any(g.grader_type == GraderType.human_review for g in self.graders)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "graders": [g.to_dict() for g in self.graders],
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Eval Case (enriched)
# ---------------------------------------------------------------------------

class EvalSuiteType(str, Enum):
    """Five eval suite types for the eval compiler."""
    contract_regression = "contract_regression"
    capability = "capability"
    adversarial = "adversarial"
    discovery = "discovery"
    judge_calibration = "judge_calibration"


@dataclass
class EvalCase:
    """Enriched eval case with end-state evaluation support.

    This extends the simpler TestCase with environment snapshots,
    grader bundles, and expected end state.
    """
    case_id: str
    task: str  # the user message / instruction
    category: str = "general"
    suite_type: EvalSuiteType = EvalSuiteType.capability
    environment_snapshot: Optional[EnvironmentSnapshot] = None
    grader_bundle: Optional[GraderBundle] = None
    expected_end_state: Optional[dict[str, Any]] = None
    diagnostic_trace_features: dict[str, Any] = field(default_factory=dict)
    expected_specialist: Optional[str] = None
    expected_behavior: Optional[str] = None
    expected_keywords: list[str] = field(default_factory=list)
    expected_tool: Optional[str] = None
    reference_answer: Optional[str] = None
    safety_probe: bool = False
    split: str = "tuning"
    business_impact: float = 1.0
    root_cause_tag: Optional[str] = None
    is_negative_control: bool = False
    solvability: Optional[float] = None  # 0-1, None = unknown
    model_version_hash: Optional[str] = None  # exact API model version string
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "case_id": self.case_id,
            "task": self.task,
            "category": self.category,
            "suite_type": self.suite_type.value,
            "expected_end_state": self.expected_end_state,
            "diagnostic_trace_features": self.diagnostic_trace_features,
            "expected_specialist": self.expected_specialist,
            "expected_behavior": self.expected_behavior,
            "expected_keywords": self.expected_keywords,
            "expected_tool": self.expected_tool,
            "reference_answer": self.reference_answer,
            "safety_probe": self.safety_probe,
            "split": self.split,
            "business_impact": self.business_impact,
            "root_cause_tag": self.root_cause_tag,
            "is_negative_control": self.is_negative_control,
            "solvability": self.solvability,
            "metadata": self.metadata,
        }
        if self.environment_snapshot:
            d["environment_snapshot"] = self.environment_snapshot.to_dict()
        if self.grader_bundle:
            d["grader_bundle"] = self.grader_bundle.to_dict()
        return d

    @classmethod
    def from_test_case(cls, tc: Any) -> "EvalCase":
        """Create an EvalCase from a legacy TestCase."""
        return cls(
            case_id=tc.id,
            task=tc.user_message,
            category=tc.category,
            expected_specialist=tc.expected_specialist,
            expected_behavior=tc.expected_behavior,
            expected_keywords=tc.expected_keywords or [],
            expected_tool=tc.expected_tool,
            reference_answer=getattr(tc, "reference_answer", None),
            safety_probe=tc.safety_probe,
            split=tc.split,
        )


# ---------------------------------------------------------------------------
# Candidate Variant
# ---------------------------------------------------------------------------

@dataclass
class CandidateVariant:
    """A proposed change as a versioned diff against an AgentGraphVersion."""
    variant_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    base_graph_version_id: Optional[str] = None
    description: str = ""
    diff: dict[str, Any] = field(default_factory=dict)  # structured diff
    config_patch: dict[str, Any] = field(default_factory=dict)  # config-level changes
    mutation_surface: str = ""
    risk_class: str = "low"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "base_graph_version_id": self.base_graph_version_id,
            "description": self.description,
            "diff": self.diff,
            "config_patch": self.config_patch,
            "mutation_surface": self.mutation_surface,
            "risk_class": self.risk_class,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Archive Entry (Pareto archive with named roles)
# ---------------------------------------------------------------------------

class ArchiveRole(str, Enum):
    """Named roles in the elite Pareto archive."""
    quality_leader = "quality_leader"
    cost_leader = "cost_leader"
    latency_leader = "latency_leader"
    safety_leader = "safety_leader"
    cluster_specialist = "cluster_specialist"
    incumbent = "incumbent"


@dataclass
class ArchiveEntry:
    """An entry in the elite Pareto archive with a named role."""
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    role: ArchiveRole = ArchiveRole.incumbent
    candidate_id: str = ""
    experiment_id: str = ""
    objective_vector: list[float] = field(default_factory=list)
    config_hash: str = ""
    scores: dict[str, float] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "role": self.role.value,
            "candidate_id": self.candidate_id,
            "experiment_id": self.experiment_id,
            "objective_vector": self.objective_vector,
            "config_hash": self.config_hash,
            "scores": self.scores,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ArchiveEntry":
        return cls(
            entry_id=d.get("entry_id", uuid.uuid4().hex[:12]),
            role=ArchiveRole(d.get("role", "incumbent")),
            candidate_id=d.get("candidate_id", ""),
            experiment_id=d.get("experiment_id", ""),
            objective_vector=d.get("objective_vector", []),
            config_hash=d.get("config_hash", ""),
            scores=d.get("scores", {}),
            created_at=d.get("created_at", ""),
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Judge Verdict (shared output schema for all judges)
# ---------------------------------------------------------------------------

@dataclass
class JudgeVerdict:
    """Structured output from any judge in the grader stack.

    Every judge — deterministic, rule-based, LLM, or audit — returns this
    same structure so the grader stack can compose results uniformly.
    """
    score: float  # 0-1
    passed: bool
    judge_id: str
    evidence_spans: list[str] = field(default_factory=list)
    failure_reasons: list[str] = field(default_factory=list)
    confidence: float = 1.0  # 0-1, deterministic judges always 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "judge_id": self.judge_id,
            "evidence_spans": self.evidence_spans,
            "failure_reasons": self.failure_reasons,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Metric Layer (4-layer hierarchy)
# ---------------------------------------------------------------------------

class MetricLayer(str, Enum):
    """Four-layer metric hierarchy replacing the flat 9-dimension approach."""
    HARD_GATE = "hard_gate"
    OUTCOME = "outcome"
    SLO = "slo"
    DIAGNOSTIC = "diagnostic"

    @property
    def display_name(self) -> str:
        """User-facing label for this metric layer."""
        return METRIC_LAYER_DISPLAY_NAMES.get(self.name, self.value)


METRIC_LAYER_DISPLAY_NAMES: dict[str, str] = {
    "HARD_GATE": "Guardrails",
    "OUTCOME": "Objectives",
    "SLO": "Constraints",
    "DIAGNOSTIC": "Diagnostics",
}


@dataclass
class LayeredMetric:
    """A metric with its layer classification."""
    name: str
    layer: MetricLayer
    direction: str = "maximize"  # "maximize" or "minimize"
    threshold: Optional[float] = None  # for gates and SLOs
    weight: float = 1.0  # for weighted optimization within layer

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "layer": self.layer.value,
            "direction": self.direction,
            "threshold": self.threshold,
            "weight": self.weight,
        }


# ---------------------------------------------------------------------------
# Metric Registry — canonical metric definitions
# ---------------------------------------------------------------------------

METRIC_REGISTRY: list[LayeredMetric] = [
    # Layer 1 — Hard Gates
    LayeredMetric("safety_compliance", MetricLayer.HARD_GATE, "maximize", threshold=1.0),
    LayeredMetric("authorization_privacy", MetricLayer.HARD_GATE, "maximize", threshold=1.0),
    LayeredMetric("state_integrity", MetricLayer.HARD_GATE, "maximize", threshold=1.0),
    LayeredMetric("p0_regressions", MetricLayer.HARD_GATE, "minimize", threshold=0.0),
    # Layer 2 — North-Star Outcomes
    LayeredMetric("task_success_rate", MetricLayer.OUTCOME, "maximize", weight=0.5),
    LayeredMetric("groundedness", MetricLayer.OUTCOME, "maximize", weight=0.3),
    LayeredMetric("user_satisfaction_proxy", MetricLayer.OUTCOME, "maximize", weight=0.2),
    # Layer 3 — Operating SLOs
    LayeredMetric("latency_p50", MetricLayer.SLO, "minimize", threshold=2000.0),
    LayeredMetric("latency_p95", MetricLayer.SLO, "minimize", threshold=5000.0),
    LayeredMetric("latency_p99", MetricLayer.SLO, "minimize", threshold=10000.0),
    LayeredMetric("token_cost", MetricLayer.SLO, "minimize"),
    LayeredMetric("escalation_rate", MetricLayer.SLO, "minimize", threshold=0.2),
    # Layer 4 — Diagnostics (never optimised directly)
    LayeredMetric("tool_correctness", MetricLayer.DIAGNOSTIC, "maximize"),
    LayeredMetric("routing_accuracy", MetricLayer.DIAGNOSTIC, "maximize"),
    LayeredMetric("handoff_fidelity", MetricLayer.DIAGNOSTIC, "maximize"),
    LayeredMetric("recovery_rate", MetricLayer.DIAGNOSTIC, "maximize"),
    LayeredMetric("clarification_quality", MetricLayer.DIAGNOSTIC, "maximize"),
    LayeredMetric("judge_disagreement_rate", MetricLayer.DIAGNOSTIC, "minimize"),
]


@dataclass
class ContextTurnUtilization:
    """Per-turn context usage for one trace event.

    Why: context failures are often turn-local, so we keep this shape explicit
    for analysis, simulation, and UI rendering.
    """

    turn_index: int
    event_id: str
    timestamp: float
    tokens_used: int
    token_budget: int
    utilization_ratio: float
    is_failure: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "tokens_used": self.tokens_used,
            "token_budget": self.token_budget,
            "utilization_ratio": self.utilization_ratio,
            "is_failure": self.is_failure,
        }


@dataclass
class ContextHandoffScore:
    """Handoff quality score between agents for one transfer event."""

    from_agent: str
    to_agent: str
    score: float
    missing_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "score": self.score,
            "missing_fields": self.missing_fields,
        }


@dataclass
class ContextTraceAnalysis:
    """Trace-level context diagnostics used by CLI/API/web."""

    trace_id: str
    token_budget: int
    total_events: int
    total_failures: int
    average_utilization: float
    max_utilization: float
    growth_pattern: str
    turns: list[ContextTurnUtilization] = field(default_factory=list)
    handoff_scores: list[ContextHandoffScore] = field(default_factory=list)
    high_context_threshold: float = 0.75
    high_context_failure_rate: float = 0.0
    low_context_failure_rate: float = 0.0
    context_correlated_failures: bool = False
    insufficient_data: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "token_budget": self.token_budget,
            "total_events": self.total_events,
            "total_failures": self.total_failures,
            "average_utilization": self.average_utilization,
            "max_utilization": self.max_utilization,
            "growth_pattern": self.growth_pattern,
            "turns": [item.to_dict() for item in self.turns],
            "handoff_scores": [item.to_dict() for item in self.handoff_scores],
            "high_context_threshold": self.high_context_threshold,
            "high_context_failure_rate": self.high_context_failure_rate,
            "low_context_failure_rate": self.low_context_failure_rate,
            "context_correlated_failures": self.context_correlated_failures,
            "insufficient_data": self.insufficient_data,
            "metadata": self.metadata,
        }


@dataclass
class ContextSimulationResult:
    """Deterministic context strategy simulation output."""

    trace_id: str
    strategy: str
    token_budget: int
    baseline_average_utilization: float
    simulated_average_utilization: float
    estimated_failure_delta: float
    estimated_compaction_loss: float
    memory_staleness: float
    ttl_seconds: int
    pinned_memory_hits: int = 0
    budget_comparison: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "strategy": self.strategy,
            "token_budget": self.token_budget,
            "baseline_average_utilization": self.baseline_average_utilization,
            "simulated_average_utilization": self.simulated_average_utilization,
            "estimated_failure_delta": self.estimated_failure_delta,
            "estimated_compaction_loss": self.estimated_compaction_loss,
            "memory_staleness": self.memory_staleness,
            "ttl_seconds": self.ttl_seconds,
            "pinned_memory_hits": self.pinned_memory_hits,
            "budget_comparison": self.budget_comparison,
            "notes": self.notes,
        }


@dataclass
class ContextHealthReport:
    """Aggregate context health summary across many traces."""

    traces_analyzed: int
    total_events: int
    average_utilization: float
    growth_pattern_counts: dict[str, int] = field(default_factory=dict)
    context_correlated_failure_traces: list[str] = field(default_factory=list)
    average_handoff_fidelity: float = 0.0
    average_memory_staleness: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "traces_analyzed": self.traces_analyzed,
            "total_events": self.total_events,
            "average_utilization": self.average_utilization,
            "growth_pattern_counts": self.growth_pattern_counts,
            "context_correlated_failure_traces": self.context_correlated_failure_traces,
            "average_handoff_fidelity": self.average_handoff_fidelity,
            "average_memory_staleness": self.average_memory_staleness,
        }


def get_metrics_by_layer(layer: MetricLayer) -> list[LayeredMetric]:
    """Return all metrics in a given layer."""
    return [m for m in METRIC_REGISTRY if m.layer == layer]
