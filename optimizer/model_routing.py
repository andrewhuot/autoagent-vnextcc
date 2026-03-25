"""Phase-aware model routing for the optimization pipeline.

Different optimization phases have different model requirements:

* **Diagnosis / Planning** — needs the best available reasoner for complex
  analysis (e.g. root-cause attribution, opportunity ranking).
* **Search / Execution** — benefits from cheaper, faster models that can
  generate many candidates in parallel.
* **Evaluation / Judging** — requires *pinned* model versions so that scores
  remain comparable across cycles (no silent provider upgrades).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums & data classes
# ---------------------------------------------------------------------------


class OptimizationPhase(str, Enum):
    """Phases of a single optimization cycle."""

    DIAGNOSIS = "diagnosis"
    SEARCH = "search"
    EVALUATION = "evaluation"


@dataclass
class ModelSpec:
    """Specification for a model to use in a given phase."""

    provider: str
    model: str
    role: str = "default"
    pinned_version: str | None = None  # For eval phase: hash-locked version

    @property
    def key(self) -> str:
        """Unique provider/model identifier."""
        return f"{self.provider}/{self.model}"


@dataclass
class PhaseRoutingConfig:
    """Configuration for phase-aware model routing."""

    diagnosis_models: list[ModelSpec] = field(default_factory=list)
    search_models: list[ModelSpec] = field(default_factory=list)
    evaluation_models: list[ModelSpec] = field(default_factory=list)
    default_model: ModelSpec | None = None


# ---------------------------------------------------------------------------
# Phase router
# ---------------------------------------------------------------------------


class PhaseRouter:
    """Routes model selection based on optimization phase.

    - Diagnosis/Planning: Best available reasoner (complex analysis)
    - Search/Execution: Cheaper/faster models (high throughput)
    - Evaluation/Judging: Pinned versions (consistency, no silent upgrades)
    """

    _PHASE_PREFERENCES: dict[OptimizationPhase, dict[str, str]] = {
        OptimizationPhase.DIAGNOSIS: {"prefer": "reasoning", "tier": "high"},
        OptimizationPhase.SEARCH: {"prefer": "fast", "tier": "low"},
        OptimizationPhase.EVALUATION: {"prefer": "pinned", "tier": "medium"},
    }

    def __init__(self, config: PhaseRoutingConfig | None = None) -> None:
        self._config = config or PhaseRoutingConfig()
        self._phase_models: dict[OptimizationPhase, list[ModelSpec]] = {
            OptimizationPhase.DIAGNOSIS: self._config.diagnosis_models,
            OptimizationPhase.SEARCH: self._config.search_models,
            OptimizationPhase.EVALUATION: self._config.evaluation_models,
        }

    def select_model(self, phase: OptimizationPhase) -> ModelSpec | None:
        """Select the best model for the given optimization phase."""
        models = self._phase_models.get(phase, [])
        if models:
            return models[0]
        if self._config.default_model:
            return self._config.default_model
        return None

    def get_phase_preference(self, phase: OptimizationPhase) -> dict[str, str]:
        """Return the preference hints for a phase."""
        return self._PHASE_PREFERENCES.get(phase, {"prefer": "default", "tier": "medium"})

    def get_eval_model_pin(self) -> str | None:
        """Return the pinned model version for evaluation, if configured."""
        eval_models = self._phase_models.get(OptimizationPhase.EVALUATION, [])
        for m in eval_models:
            if m.pinned_version:
                return m.pinned_version
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize routing config for API/logging."""
        return {
            "diagnosis": [
                {"provider": m.provider, "model": m.model}
                for m in self._phase_models.get(OptimizationPhase.DIAGNOSIS, [])
            ],
            "search": [
                {"provider": m.provider, "model": m.model}
                for m in self._phase_models.get(OptimizationPhase.SEARCH, [])
            ],
            "evaluation": [
                {"provider": m.provider, "model": m.model, "pinned": m.pinned_version}
                for m in self._phase_models.get(OptimizationPhase.EVALUATION, [])
            ],
        }
