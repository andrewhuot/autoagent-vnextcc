"""Adversarial test generation harness targeting agent weaknesses.

Generates adversarial test cases from failure clusters, attack vectors,
and skill eval contracts. Supports progressive difficulty scaling.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from simulator.attack_vectors import AttackVector, get_templates


@dataclass
class AdversarialCase:
    """A single adversarial test case."""
    case_id: str = field(default_factory=lambda: f"adv_{uuid.uuid4().hex[:8]}")
    attack_vector: str = ""
    difficulty: float = 0.5  # 0-1
    input_text: str = ""
    expected_behavior: str = ""
    failure_cluster: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "attack_vector": self.attack_vector,
            "difficulty": self.difficulty,
            "input_text": self.input_text,
            "expected_behavior": self.expected_behavior,
            "failure_cluster": self.failure_cluster,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AdversarialCase:
        return cls(
            case_id=d.get("case_id", f"adv_{uuid.uuid4().hex[:8]}"),
            attack_vector=d.get("attack_vector", ""),
            difficulty=d.get("difficulty", 0.5),
            input_text=d.get("input_text", ""),
            expected_behavior=d.get("expected_behavior", ""),
            failure_cluster=d.get("failure_cluster"),
            metadata=d.get("metadata", {}),
        )

    def to_eval_case(self) -> dict[str, Any]:
        """Convert to EvalCase-compatible dict."""
        return {
            "case_id": self.case_id,
            "task": self.input_text,
            "category": "adversarial",
            "suite_type": "adversarial",
            "expected_behavior": self.expected_behavior,
            "safety_probe": True,
            "split": "validation",
            "metadata": {
                "attack_vector": self.attack_vector,
                "difficulty": self.difficulty,
                "failure_cluster": self.failure_cluster,
                **self.metadata,
            },
        }


class AdversarialHarness:
    """Generates adversarial test cases targeting agent weaknesses."""

    def generate_from_failures(
        self,
        failure_clusters: list[dict[str, Any]],
        count_per_cluster: int = 5,
    ) -> list[AdversarialCase]:
        """Generate adversarial cases targeting known failure clusters.

        Args:
            failure_clusters: List of failure cluster dicts with 'name', 'pattern', 'count'.
            count_per_cluster: Number of cases to generate per cluster.
        """
        cases: list[AdversarialCase] = []
        for cluster in failure_clusters:
            cluster_name = cluster.get("name", "unknown")
            pattern = cluster.get("pattern", "")
            vector = self._infer_vector_from_pattern(pattern)
            templates = get_templates(vector)

            for i, template in enumerate(templates[:count_per_cluster]):
                case = AdversarialCase(
                    attack_vector=vector.value,
                    difficulty=min(0.3 + (i * 0.15), 1.0),
                    input_text=template.get("input", template.get("template", "")),
                    expected_behavior=template.get("expected", template.get("expected_behavior", "safe_response")),
                    failure_cluster=cluster_name,
                    metadata={"source": "failure_cluster", "template_index": i},
                )
                cases.append(case)

        return cases

    def generate_for_vector(
        self, vector: AttackVector, count: int = 10
    ) -> list[AdversarialCase]:
        """Generate adversarial cases for a specific attack vector."""
        templates = get_templates(vector)
        cases: list[AdversarialCase] = []

        for i, template in enumerate(templates[:count]):
            case = AdversarialCase(
                attack_vector=vector.value,
                difficulty=min(0.2 + (i * 0.1), 1.0),
                input_text=template.get("input", template.get("template", "")),
                expected_behavior=template.get("expected", template.get("expected_behavior", "safe_response")),
                metadata={"source": "vector_specific", "template_index": i},
            )
            cases.append(case)

        return cases

    def generate_progressive(
        self, current_pass_rate: float, count: int = 10
    ) -> list[AdversarialCase]:
        """Generate cases with difficulty scaled to current agent performance.

        Higher pass rate → harder adversarial cases.
        """
        base_difficulty = max(0.1, current_pass_rate - 0.2)
        cases: list[AdversarialCase] = []

        vectors = list(AttackVector)
        for i in range(count):
            vector = vectors[i % len(vectors)]
            templates = get_templates(vector)
            if not templates:
                continue
            template = templates[i % len(templates)]

            difficulty = min(base_difficulty + (i * 0.05), 1.0)
            case = AdversarialCase(
                attack_vector=vector.value,
                difficulty=difficulty,
                input_text=template.get("input", template.get("template", "")),
                expected_behavior=template.get("expected", template.get("expected_behavior", "safe_response")),
                metadata={"source": "progressive", "base_pass_rate": current_pass_rate},
            )
            cases.append(case)

        return cases

    def generate_from_skill_contract(
        self, skill_config: dict[str, Any]
    ) -> list[AdversarialCase]:
        """Generate adversarial cases from a skill's eval contract."""
        cases: list[AdversarialCase] = []
        eval_contract = skill_config.get("eval_contract", {})
        guardrails = skill_config.get("guardrails", [])
        category = skill_config.get("category", "general")

        # Generate cases that test each guardrail
        for guardrail in guardrails:
            case = AdversarialCase(
                attack_vector="guardrail_test",
                difficulty=0.6,
                input_text=f"Test input designed to trigger {guardrail} guardrail violation",
                expected_behavior=f"Guardrail {guardrail} should activate and block",
                metadata={"source": "skill_contract", "guardrail": guardrail},
            )
            cases.append(case)

        # Generate cases from eval criteria
        for criterion in eval_contract.get("criteria", []):
            case = AdversarialCase(
                attack_vector="criteria_boundary",
                difficulty=0.7,
                input_text=f"Edge case for metric: {criterion.get('metric', 'unknown')}",
                expected_behavior=f"Must satisfy {criterion.get('metric')}: {criterion.get('operator', '>')} {criterion.get('target', 0)}",
                metadata={"source": "skill_contract", "criterion": criterion},
            )
            cases.append(case)

        return cases

    # ------------------------------------------------------------------
    # Dedicated vector-specific generators
    # ------------------------------------------------------------------

    def _prompt_injection_cases(self, count: int) -> list[AdversarialCase]:
        """Generate prompt injection test cases."""
        return self.generate_for_vector(AttackVector.PROMPT_INJECTION, count)

    def _data_leakage_cases(self, count: int) -> list[AdversarialCase]:
        """Generate data leakage probe cases."""
        return self.generate_for_vector(AttackVector.DATA_LEAKAGE, count)

    def _tool_misuse_cases(self, count: int) -> list[AdversarialCase]:
        """Generate tool misuse test cases."""
        return self.generate_for_vector(AttackVector.TOOL_MISUSE, count)

    def _timeout_storm_cases(self, count: int) -> list[AdversarialCase]:
        """Generate timeout / resource exhaustion cases."""
        return self.generate_for_vector(AttackVector.TIMEOUT_STORM, count)

    def _handoff_loop_cases(self, count: int) -> list[AdversarialCase]:
        """Generate agent handoff loop cases."""
        return self.generate_for_vector(AttackVector.HANDOFF_LOOP, count)

    def _memory_confusion_cases(self, count: int) -> list[AdversarialCase]:
        """Generate memory/context confusion cases."""
        return self.generate_for_vector(AttackVector.MEMORY_CONFUSION, count)

    def _infer_vector_from_pattern(self, pattern: str) -> AttackVector:
        """Infer attack vector from a failure pattern description."""
        pattern_lower = pattern.lower()
        mapping = {
            "injection": AttackVector.PROMPT_INJECTION,
            "pii": AttackVector.DATA_LEAKAGE,
            "leak": AttackVector.DATA_LEAKAGE,
            "tool": AttackVector.TOOL_MISUSE,
            "timeout": AttackVector.TIMEOUT_STORM,
            "latency": AttackVector.TIMEOUT_STORM,
            "handoff": AttackVector.HANDOFF_LOOP,
            "loop": AttackVector.HANDOFF_LOOP,
            "routing": AttackVector.HANDOFF_LOOP,
            "memory": AttackVector.MEMORY_CONFUSION,
            "context": AttackVector.LONG_CONTEXT_DRIFT,
            "api": AttackVector.DEGRADED_API,
            "social": AttackVector.SOCIAL_ENGINEERING,
            "jailbreak": AttackVector.JAILBREAK,
        }
        for keyword, vector in mapping.items():
            if keyword in pattern_lower:
                return vector
        return AttackVector.PROMPT_INJECTION  # Default
