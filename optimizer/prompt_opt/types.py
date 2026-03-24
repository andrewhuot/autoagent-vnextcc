"""Shared types for pro-mode prompt optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProAlgorithm(str, Enum):
    """Available pro-mode optimization algorithms."""

    AUTO = "auto"
    MIPROV2 = "miprov2"
    BOOTSTRAP_FEWSHOT = "bootstrap_fewshot"
    GEPA = "gepa"
    SIMBA = "simba"


@dataclass
class ProConfig:
    """Configuration for pro-mode prompt optimization."""

    algorithm: str = ProAlgorithm.AUTO.value
    instruction_candidates: int = 5
    example_candidates: int = 3
    max_eval_rounds: int = 10
    teacher_model: str | None = None
    budget_dollars: float = 10.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProConfig:
        """Create ProConfig from a dictionary (e.g., YAML config section)."""
        return cls(
            algorithm=str(data.get("algorithm", "auto")),
            instruction_candidates=int(data.get("instruction_candidates", 5)),
            example_candidates=int(data.get("example_candidates", 3)),
            max_eval_rounds=int(data.get("max_eval_rounds", 10)),
            teacher_model=data.get("teacher_model"),
            budget_dollars=float(data.get("budget_dollars", 10.0)),
        )


@dataclass
class FewShotExample:
    """A single few-shot demonstration example."""

    user_message: str
    assistant_response: str
    quality_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptCandidate:
    """A candidate prompt configuration (instruction + examples)."""

    instruction: str
    examples: list[FewShotExample] = field(default_factory=list)
    eval_score: float = 0.0
    instruction_idx: int = 0
    example_set_idx: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OptimizationResult:
    """Result of a pro-mode optimization run."""

    best_candidate: PromptCandidate | None
    baseline_score: float
    best_score: float
    algorithm: str
    total_eval_rounds: int
    total_cost_dollars: float = 0.0
    candidates_evaluated: int = 0
    early_stopped: bool = False
    improvement: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def improved(self) -> bool:
        """Whether the best candidate improved over baseline."""
        return self.best_score > self.baseline_score

    def to_config_patch(self) -> dict[str, Any] | None:
        """Convert best candidate to a config mutation patch."""
        if self.best_candidate is None:
            return None
        patch: dict[str, Any] = {}
        if self.best_candidate.instruction:
            patch["system_prompt"] = self.best_candidate.instruction
        if self.best_candidate.examples:
            patch["few_shot_examples"] = [
                {
                    "user_message": ex.user_message,
                    "assistant_response": ex.assistant_response,
                }
                for ex in self.best_candidate.examples
            ]
        return patch
