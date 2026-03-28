"""Dataclasses for the executable skills registry (Track A).

These types are serialization-friendly: every class has to_dict() and from_dict()
so skills can be persisted as JSON blobs in SQLite and round-tripped faithfully.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MutationTemplate:
    name: str
    mutation_type: str
    target_surface: str
    description: str
    template: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mutation_type": self.mutation_type,
            "target_surface": self.target_surface,
            "description": self.description,
            "template": self.template,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MutationTemplate:
        return cls(
            name=data["name"],
            mutation_type=data["mutation_type"],
            target_surface=data["target_surface"],
            description=data["description"],
            template=data.get("template"),
            parameters=data.get("parameters", {}),
        )


@dataclass
class SkillExample:
    name: str
    surface: str
    before: str | dict[str, Any]
    after: str | dict[str, Any]
    improvement: float
    context: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "surface": self.surface,
            "before": self.before,
            "after": self.after,
            "improvement": self.improvement,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillExample:
        return cls(
            name=data["name"],
            surface=data["surface"],
            before=data["before"],
            after=data["after"],
            improvement=data["improvement"],
            context=data.get("context", ""),
        )


@dataclass
class TriggerCondition:
    failure_family: str | None = None
    metric_name: str | None = None
    threshold: float | None = None
    operator: str = "gt"
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
    metric: str
    target: float
    operator: str = "gt"
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
class Skill:
    name: str
    version: int
    description: str
    category: str               # "routing", "safety", "latency", "quality", "cost"
    platform: str               # "universal", "cx-agent-studio", "vertex-ai"
    target_surfaces: list[str]
    mutations: list[MutationTemplate]
    examples: list[SkillExample]
    guardrails: list[str]
    eval_criteria: list[EvalCriterion]
    triggers: list[TriggerCondition]
    author: str = "autoagent-builtin"
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    proven_improvement: float | None = None
    times_applied: int = 0
    success_rate: float = 0.0
    status: str = "active"      # "active", "draft", "deprecated"
    # SKILL.md portable format fields
    kind: str = "runtime"       # "runtime" or "buildtime"
    dependencies: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    supported_frameworks: list[str] = field(default_factory=list)
    required_approvals: list[str] = field(default_factory=list)
    eval_contract: dict[str, Any] = field(default_factory=dict)
    rollout_policy: str = "gradual"
    provenance: str = ""
    trust_level: str = "unverified"   # unverified, community-tested, benchmark-validated, enterprise-certified
    instructions: str = ""            # Full instructions (Layer 2 content)
    references: str = ""              # Reference material (Layer 3 content)
    runtime_effectiveness: float = 0.0    # Track runtime behaviour improvement
    buildtime_effectiveness: float = 0.0  # Track builder output improvement

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "category": self.category,
            "platform": self.platform,
            "target_surfaces": self.target_surfaces,
            "mutations": [m.to_dict() for m in self.mutations],
            "examples": [e.to_dict() for e in self.examples],
            "guardrails": self.guardrails,
            "eval_criteria": [c.to_dict() for c in self.eval_criteria],
            "triggers": [t.to_dict() for t in self.triggers],
            "author": self.author,
            "tags": self.tags,
            "created_at": self.created_at,
            "proven_improvement": self.proven_improvement,
            "times_applied": self.times_applied,
            "success_rate": self.success_rate,
            "status": self.status,
            # SKILL.md portable format fields
            "kind": self.kind,
            "dependencies": self.dependencies,
            "allowed_tools": self.allowed_tools,
            "supported_frameworks": self.supported_frameworks,
            "required_approvals": self.required_approvals,
            "eval_contract": self.eval_contract,
            "rollout_policy": self.rollout_policy,
            "provenance": self.provenance,
            "trust_level": self.trust_level,
            "instructions": self.instructions,
            "references": self.references,
            "runtime_effectiveness": self.runtime_effectiveness,
            "buildtime_effectiveness": self.buildtime_effectiveness,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        return cls(
            name=data["name"],
            version=data["version"],
            description=data["description"],
            category=data["category"],
            platform=data["platform"],
            target_surfaces=data.get("target_surfaces", []),
            mutations=[MutationTemplate.from_dict(m) for m in data.get("mutations", [])],
            examples=[SkillExample.from_dict(e) for e in data.get("examples", [])],
            guardrails=data.get("guardrails", []),
            eval_criteria=[EvalCriterion.from_dict(c) for c in data.get("eval_criteria", [])],
            triggers=[TriggerCondition.from_dict(t) for t in data.get("triggers", [])],
            author=data.get("author", "autoagent-builtin"),
            tags=data.get("tags", []),
            created_at=data.get("created_at", time.time()),
            proven_improvement=data.get("proven_improvement"),
            times_applied=data.get("times_applied", 0),
            success_rate=data.get("success_rate", 0.0),
            status=data.get("status", "active"),
            # SKILL.md portable format fields
            kind=data.get("kind", "runtime"),
            dependencies=data.get("dependencies", []),
            allowed_tools=data.get("allowed_tools", []),
            supported_frameworks=data.get("supported_frameworks", []),
            required_approvals=data.get("required_approvals", []),
            eval_contract=data.get("eval_contract", {}),
            rollout_policy=data.get("rollout_policy", "gradual"),
            provenance=data.get("provenance", ""),
            trust_level=data.get("trust_level", "unverified"),
            instructions=data.get("instructions", ""),
            references=data.get("references", ""),
            runtime_effectiveness=data.get("runtime_effectiveness", 0.0),
            buildtime_effectiveness=data.get("buildtime_effectiveness", 0.0),
        )
