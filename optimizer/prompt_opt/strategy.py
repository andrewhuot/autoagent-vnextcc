"""Pro-mode search strategy orchestrator.

Routes to the appropriate algorithm (MIPROv2, BootstrapFewShot, GEPA, SIMBA)
based on configuration and budget constraints.
"""

from __future__ import annotations

import logging
from typing import Any

from evals.runner import EvalRunner
from optimizer.providers import LLMRouter, LLMRequest
from .types import ProAlgorithm, ProConfig, OptimizationResult

logger = logging.getLogger(__name__)


class ProSearchStrategy:
    """Orchestrates pro-mode prompt optimization.

    Algorithm selection logic:
    - AUTO: Use MIPROv2 (best general-purpose), fall back to BootstrapFewShot if budget tight
    - Explicit: Use the named algorithm

    Integrates with existing EvalRunner, Gates, and experiment tracking.
    """

    def __init__(
        self,
        llm_router: LLMRouter,
        eval_runner: EvalRunner,
        config: ProConfig | None = None,
    ):
        self.llm_router = llm_router
        self.eval_runner = eval_runner
        self.config = config or ProConfig()

    def run(self, current_config: dict, task_description: str = "",
            failure_patterns: list[str] | None = None) -> OptimizationResult:
        """Run pro-mode optimization with the configured algorithm."""
        algorithm = self._select_algorithm()
        logger.info("Pro-mode optimization: using algorithm=%s", algorithm.value)

        if algorithm == ProAlgorithm.MIPROV2:
            from .mipro import MIPROv2
            optimizer = MIPROv2(self.llm_router, self.eval_runner, self.config)
            return optimizer.optimize(current_config, task_description)

        elif algorithm == ProAlgorithm.BOOTSTRAP_FEWSHOT:
            from .bootstrap_fewshot import BootstrapFewShot
            optimizer = BootstrapFewShot(self.llm_router, self.eval_runner, self.config)
            return optimizer.optimize(current_config, task_description)

        elif algorithm == ProAlgorithm.GEPA:
            from .gepa import GEPA
            optimizer = GEPA(self.llm_router, self.eval_runner, self.config)
            return optimizer.optimize(current_config, task_description)

        elif algorithm == ProAlgorithm.SIMBA:
            from .simba import SIMBA
            optimizer = SIMBA(self.llm_router, self.eval_runner, self.config)
            return optimizer.optimize(current_config, task_description)

        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

    def _select_algorithm(self) -> ProAlgorithm:
        """Select algorithm based on config and budget."""
        requested = self.config.algorithm.lower().strip()

        if requested != ProAlgorithm.AUTO.value:
            try:
                return ProAlgorithm(requested)
            except ValueError:
                logger.warning("Unknown algorithm %r, falling back to auto", requested)

        # AUTO: use MIPROv2 unless budget is tight
        if self.config.budget_dollars < 1.0:
            return ProAlgorithm.BOOTSTRAP_FEWSHOT
        return ProAlgorithm.MIPROV2
