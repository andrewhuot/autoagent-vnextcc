"""Generate complete eval packs from archetypes and agent descriptions.

Every agent creation must emit a complete eval pack alongside the agent definition:
hard gates, north-star metrics, SLOs, smoke tests, slice definitions, and canary policy.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import yaml

from assistant.archetypes import AgentArchetype, ArchetypeId, get_archetype


@dataclass
class EvalPack:
    """Complete evaluation pack generated for an agent."""
    agent_name: str
    archetype: str
    hard_gates: list[dict[str, Any]] = field(default_factory=list)
    north_star_cases: list[dict[str, Any]] = field(default_factory=list)
    slo_checks: list[dict[str, Any]] = field(default_factory=list)
    smoke_tests: list[dict[str, Any]] = field(default_factory=list)
    adversarial_cases: list[dict[str, Any]] = field(default_factory=list)
    slice_definitions: list[dict[str, Any]] = field(default_factory=list)
    canary_policy: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "archetype": self.archetype,
            "hard_gates": self.hard_gates,
            "north_star_cases": self.north_star_cases,
            "slo_checks": self.slo_checks,
            "smoke_tests": self.smoke_tests,
            "adversarial_cases": self.adversarial_cases,
            "slice_definitions": self.slice_definitions,
            "canary_policy": self.canary_policy,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EvalPack:
        return cls(
            agent_name=d["agent_name"],
            archetype=d["archetype"],
            hard_gates=d.get("hard_gates", []),
            north_star_cases=d.get("north_star_cases", []),
            slo_checks=d.get("slo_checks", []),
            smoke_tests=d.get("smoke_tests", []),
            adversarial_cases=d.get("adversarial_cases", []),
            slice_definitions=d.get("slice_definitions", []),
            canary_policy=d.get("canary_policy", {}),
            created_at=d.get("created_at", ""),
        )

    def to_eval_cases(self) -> list[dict[str, Any]]:
        """Convert all eval pack items to EvalCase-compatible dicts."""
        cases: list[dict[str, Any]] = []
        for gate in self.hard_gates:
            cases.append(gate)
        for case in self.north_star_cases:
            cases.append(case)
        for check in self.slo_checks:
            cases.append(check)
        for test in self.smoke_tests:
            cases.append(test)
        for adv in self.adversarial_cases:
            cases.append(adv)
        return cases

    @property
    def total_cases(self) -> int:
        return len(self.hard_gates) + len(self.north_star_cases) + len(self.slo_checks) + len(self.smoke_tests) + len(self.adversarial_cases)


def _make_case_id(prefix: str) -> str:
    """Generate a unique case ID with prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class EvalPackGenerator:
    """Generates complete eval packs from archetypes and agent descriptions."""

    def generate(
        self,
        agent_name: str,
        archetype_id: str,
        agent_description: str = "",
        custom_criteria: dict[str, Any] | None = None,
    ) -> EvalPack:
        """Generate a complete eval pack for an agent.

        Args:
            agent_name: Name of the agent being created.
            archetype_id: Archetype ID string.
            agent_description: Optional NL description for customization.
            custom_criteria: Optional custom eval criteria to merge.

        Returns:
            Complete EvalPack with all eval case types.
        """
        archetype = get_archetype(archetype_id)

        hard_gates = self.generate_hard_gates(archetype)
        smoke_tests = self.generate_smoke_tests(archetype, agent_name)
        adversarial_cases = self.generate_adversarial_cases(archetype)
        slo_checks = self.generate_slo_checks(archetype)
        north_star_cases = self._generate_north_star_cases(archetype, agent_name)

        pack = EvalPack(
            agent_name=agent_name,
            archetype=archetype_id,
            hard_gates=hard_gates,
            north_star_cases=north_star_cases,
            slo_checks=slo_checks,
            smoke_tests=smoke_tests,
            adversarial_cases=adversarial_cases,
            slice_definitions=archetype.eval_pack.slice_definitions,
            canary_policy=archetype.eval_pack.canary_policy,
        )

        return pack

    def generate_hard_gates(self, archetype: AgentArchetype) -> list[dict[str, Any]]:
        """Generate hard gate eval cases from archetype config."""
        cases = []
        for gate in archetype.eval_pack.hard_gates:
            case = {
                "case_id": _make_case_id("gate"),
                "task": f"[Hard Gate] {gate['description']}",
                "category": "safety",
                "suite_type": "contract_regression",
                "expected_behavior": f"Must satisfy: {gate['name']} (threshold: {gate['threshold']})",
                "safety_probe": True,
                "split": "holdout",
                "metadata": {"gate_name": gate["name"], "metric": gate["metric"], "threshold": gate["threshold"]},
            }
            cases.append(case)
        return cases

    def generate_smoke_tests(self, archetype: AgentArchetype, agent_name: str) -> list[dict[str, Any]]:
        """Generate smoke test eval cases from archetype config."""
        cases = []
        for i, test in enumerate(archetype.eval_pack.smoke_tests):
            case = {
                "case_id": _make_case_id("smoke"),
                "task": test["task"],
                "category": "smoke",
                "suite_type": "capability",
                "expected_behavior": test["expected_behavior"],
                "safety_probe": False,
                "split": "tuning",
                "metadata": {"archetype": archetype.id.value, "test_index": i},
            }
            cases.append(case)
        return cases

    def generate_adversarial_cases(self, archetype: AgentArchetype) -> list[dict[str, Any]]:
        """Generate adversarial test cases from archetype failure taxonomy."""
        cases = []
        for failure in archetype.failure_taxonomy:
            case = {
                "case_id": _make_case_id("adv"),
                "task": f"[Adversarial] Trigger: {failure.name} — {failure.description}",
                "category": "adversarial",
                "suite_type": "adversarial",
                "expected_behavior": f"Agent should NOT exhibit: {failure.name}. Detection: {failure.detection_pattern}",
                "safety_probe": failure.severity in ("critical", "high"),
                "split": "validation",
                "metadata": {
                    "failure_id": failure.failure_id,
                    "severity": failure.severity,
                    "detection_pattern": failure.detection_pattern,
                    "suggested_fix": failure.suggested_fix,
                },
            }
            cases.append(case)
        return cases

    def generate_slo_checks(self, archetype: AgentArchetype) -> list[dict[str, Any]]:
        """Generate SLO check eval cases from archetype config."""
        cases = []
        for slo in archetype.eval_pack.slos:
            case = {
                "case_id": _make_case_id("slo"),
                "task": f"[SLO Check] {slo['name']}: threshold {slo['threshold']}",
                "category": "slo",
                "suite_type": "contract_regression",
                "expected_behavior": f"SLO {slo['name']} must be {'below' if slo.get('direction') == 'below' else 'within'} {slo['threshold']} {slo.get('unit', '')}",
                "safety_probe": False,
                "split": "holdout",
                "metadata": {"slo_name": slo["name"], "threshold": slo["threshold"]},
            }
            cases.append(case)
        return cases

    def _generate_north_star_cases(self, archetype: AgentArchetype, agent_name: str) -> list[dict[str, Any]]:
        """Generate north star metric eval cases."""
        cases = []
        for metric in archetype.eval_pack.north_star_metrics:
            case = {
                "case_id": _make_case_id("ns"),
                "task": f"[North Star] {metric['name']}: target {metric['target']}",
                "category": "outcome",
                "suite_type": "capability",
                "expected_behavior": f"Agent {agent_name} should achieve {metric['name']} >= {metric['target']}",
                "safety_probe": False,
                "split": "tuning",
                "metadata": {"metric_name": metric["name"], "target": metric["target"], "weight": metric["weight"]},
            }
            cases.append(case)
        return cases

    def export_to_evalset_json(self, pack: EvalPack, output_path: str) -> str:
        """Export eval pack as ADK .evalset.json format.

        Args:
            pack: The eval pack to export.
            output_path: Path to write the file.

        Returns:
            The output path.
        """
        evalset = {
            "name": f"{pack.agent_name}_eval_pack",
            "description": f"Auto-generated eval pack for {pack.agent_name} ({pack.archetype} archetype)",
            "created_at": pack.created_at,
            "eval_cases": pack.to_eval_cases(),
            "metadata": {
                "archetype": pack.archetype,
                "total_cases": pack.total_cases,
                "generator": "autoagent_eval_pack_generator",
            },
        }
        with open(output_path, "w") as f:
            json.dump(evalset, f, indent=2)
        return output_path

    def export_to_yaml(self, pack: EvalPack, output_path: str) -> str:
        """Export eval pack as YAML.

        Args:
            pack: The eval pack to export.
            output_path: Path to write the file.

        Returns:
            The output path.
        """
        with open(output_path, "w") as f:
            yaml.dump(pack.to_dict(), f, default_flow_style=False, sort_keys=False)
        return output_path
