"""Unified skill types for both build-time and run-time capabilities.

This module defines the core Skill model that works for:
- Build-time skills: optimization strategies (e.g., keyword_expansion, safety_hardening)
- Run-time skills: agent capabilities (e.g., order_lookup, refund_processing)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SkillKind(str, Enum):
    """The kind of skill - build-time or run-time."""
    BUILD = "build"
    RUNTIME = "runtime"


@dataclass
class MutationOperator:
    """A mutation operator for build-time skills.

    Encodes HOW to mutate an agent configuration.
    """
    name: str
    description: str
    target_surface: str  # "instruction", "routing", "tool_config", etc.
    operator_type: str   # "append", "replace", "delete", "merge"
    template: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"  # "low", "medium", "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "target_surface": self.target_surface,
            "operator_type": self.operator_type,
            "template": self.template,
            "parameters": self.parameters,
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MutationOperator:
        return cls(
            name=data["name"],
            description=data["description"],
            target_surface=data["target_surface"],
            operator_type=data["operator_type"],
            template=data.get("template"),
            parameters=data.get("parameters", {}),
            risk_level=data.get("risk_level", "low"),
        )


@dataclass
class TriggerCondition:
    """When to activate a build-time skill."""
    failure_family: str | None = None
    metric_name: str | None = None
    threshold: float | None = None
    operator: str = "gt"  # "gt", "lt", "gte", "lte", "eq"
    blame_pattern: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_family": self.failure_family,
            "metric_name": self.metric_name,
            "threshold": self.threshold,
            "operator": self.operator,
            "blame_pattern": self.blame_pattern,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriggerCondition:
        return cls(
            failure_family=data.get("failure_family"),
            metric_name=data.get("metric_name"),
            threshold=data.get("threshold"),
            operator=data.get("operator", "gt"),
            blame_pattern=data.get("blame_pattern"),
        )


@dataclass
class EvalCriterion:
    """How to measure success for a build-time skill."""
    metric: str
    target: float
    operator: str = "gt"  # "gt", "lt", "gte", "lte", "eq"
    weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "target": self.target,
            "operator": self.operator,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalCriterion:
        return cls(
            metric=data["metric"],
            target=data["target"],
            operator=data.get("operator", "gt"),
            weight=data.get("weight", 1.0),
        )


@dataclass
class ToolDefinition:
    """A tool definition for run-time skills."""
    name: str
    description: str
    parameters: dict[str, Any]
    returns: dict[str, Any] | None = None
    implementation: str | None = None  # Python code or reference
    sandbox_policy: str = "read_only"  # "pure", "read_only", "write_reversible", "write_irreversible"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "returns": self.returns,
            "implementation": self.implementation,
            "sandbox_policy": self.sandbox_policy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolDefinition:
        return cls(
            name=data["name"],
            description=data["description"],
            parameters=data["parameters"],
            returns=data.get("returns"),
            implementation=data.get("implementation"),
            sandbox_policy=data.get("sandbox_policy", "read_only"),
        )


@dataclass
class Policy:
    """A policy/guardrail for run-time skills."""
    name: str
    description: str
    rule_type: str  # "allow", "deny", "require", "limit"
    condition: str
    action: str
    severity: str = "medium"  # "low", "medium", "high", "critical"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "rule_type": self.rule_type,
            "condition": self.condition,
            "action": self.action,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Policy:
        return cls(
            name=data["name"],
            description=data["description"],
            rule_type=data["rule_type"],
            condition=data["condition"],
            action=data["action"],
            severity=data.get("severity", "medium"),
        )


@dataclass
class TestCase:
    """A test case for validating run-time skills."""
    name: str
    description: str
    input: dict[str, Any]
    expected_output: dict[str, Any] | None = None
    expected_behavior: str | None = None
    assertions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input": self.input,
            "expected_output": self.expected_output,
            "expected_behavior": self.expected_behavior,
            "assertions": self.assertions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestCase:
        return cls(
            name=data["name"],
            description=data["description"],
            input=data["input"],
            expected_output=data.get("expected_output"),
            expected_behavior=data.get("expected_behavior"),
            assertions=data.get("assertions", []),
        )


@dataclass
class EffectivenessMetrics:
    """Track record of a skill's effectiveness."""
    times_applied: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    avg_improvement: float = 0.0
    total_improvement: float = 0.0
    last_applied: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "times_applied": self.times_applied,
            "success_count": self.success_count,
            "success_rate": self.success_rate,
            "avg_improvement": self.avg_improvement,
            "total_improvement": self.total_improvement,
            "last_applied": self.last_applied,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EffectivenessMetrics:
        return cls(
            times_applied=data.get("times_applied", 0),
            success_count=data.get("success_count", 0),
            success_rate=data.get("success_rate", 0.0),
            avg_improvement=data.get("avg_improvement", 0.0),
            total_improvement=data.get("total_improvement", 0.0),
            last_applied=data.get("last_applied"),
        )


@dataclass
class SkillDependency:
    """A dependency on another skill."""
    skill_id: str
    version_constraint: str = "*"  # Semver constraint: "1.2", ">=1.0,<2.0", etc.
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "version_constraint": self.version_constraint,
            "optional": self.optional,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillDependency:
        return cls(
            skill_id=data["skill_id"],
            version_constraint=data.get("version_constraint", "*"),
            optional=data.get("optional", False),
        )


@dataclass
class SkillExample:
    """Before/after example for a skill."""
    name: str
    description: str
    before: str | dict[str, Any]
    after: str | dict[str, Any]
    improvement: float
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "before": self.before,
            "after": self.after,
            "improvement": self.improvement,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillExample:
        return cls(
            name=data["name"],
            description=data["description"],
            before=data["before"],
            after=data["after"],
            improvement=data["improvement"],
            context=data.get("context", ""),
        )


@dataclass
class Skill:
    """Unified skill model for both build-time and run-time capabilities.

    Build-time skills encode HOW to optimize (mutation operators, triggers, eval criteria).
    Run-time skills encode WHAT the agent can do (tools, instructions, policies).
    """
    id: str
    name: str
    kind: SkillKind
    version: str
    description: str
    capabilities: list[str] = field(default_factory=list)

    # Build-time specific
    mutations: list[MutationOperator] = field(default_factory=list)
    triggers: list[TriggerCondition] = field(default_factory=list)
    eval_criteria: list[EvalCriterion] = field(default_factory=list)
    guardrails: list[str] = field(default_factory=list)
    examples: list[SkillExample] = field(default_factory=list)

    # Run-time specific
    tools: list[ToolDefinition] = field(default_factory=list)
    instructions: str = ""
    policies: list[Policy] = field(default_factory=list)
    dependencies: list[SkillDependency] = field(default_factory=list)
    test_cases: list[TestCase] = field(default_factory=list)

    # Shared metadata
    tags: list[str] = field(default_factory=list)
    domain: str = "general"  # "customer-support", "sales", "general", etc.
    effectiveness: EffectivenessMetrics = field(default_factory=EffectivenessMetrics)
    metadata: dict[str, Any] = field(default_factory=dict)

    author: str = "autoagent"
    status: str = "active"  # "active", "draft", "deprecated"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "version": self.version,
            "description": self.description,
            "capabilities": self.capabilities,
            "mutations": [m.to_dict() for m in self.mutations],
            "triggers": [t.to_dict() for t in self.triggers],
            "eval_criteria": [e.to_dict() for e in self.eval_criteria],
            "guardrails": self.guardrails,
            "examples": [e.to_dict() for e in self.examples],
            "tools": [t.to_dict() for t in self.tools],
            "instructions": self.instructions,
            "policies": [p.to_dict() for p in self.policies],
            "dependencies": [d.to_dict() for d in self.dependencies],
            "test_cases": [t.to_dict() for t in self.test_cases],
            "tags": self.tags,
            "domain": self.domain,
            "effectiveness": self.effectiveness.to_dict(),
            "metadata": self.metadata,
            "author": self.author,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        kind_str = data.get("kind", "build")
        kind = SkillKind.BUILD if kind_str == "build" else SkillKind.RUNTIME

        return cls(
            id=data["id"],
            name=data["name"],
            kind=kind,
            version=data["version"],
            description=data["description"],
            capabilities=data.get("capabilities", []),
            mutations=[MutationOperator.from_dict(m) for m in data.get("mutations", [])],
            triggers=[TriggerCondition.from_dict(t) for t in data.get("triggers", [])],
            eval_criteria=[EvalCriterion.from_dict(e) for e in data.get("eval_criteria", [])],
            guardrails=data.get("guardrails", []),
            examples=[SkillExample.from_dict(e) for e in data.get("examples", [])],
            tools=[ToolDefinition.from_dict(t) for t in data.get("tools", [])],
            instructions=data.get("instructions", ""),
            policies=[Policy.from_dict(p) for p in data.get("policies", [])],
            dependencies=[SkillDependency.from_dict(d) for d in data.get("dependencies", [])],
            test_cases=[TestCase.from_dict(t) for t in data.get("test_cases", [])],
            tags=data.get("tags", []),
            domain=data.get("domain", "general"),
            effectiveness=EffectivenessMetrics.from_dict(data.get("effectiveness", {})),
            metadata=data.get("metadata", {}),
            author=data.get("author", "autoagent"),
            status=data.get("status", "active"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )

    def is_build_time(self) -> bool:
        """Check if this is a build-time skill."""
        return self.kind == SkillKind.BUILD

    def is_runtime(self) -> bool:
        """Check if this is a run-time skill."""
        return self.kind == SkillKind.RUNTIME
