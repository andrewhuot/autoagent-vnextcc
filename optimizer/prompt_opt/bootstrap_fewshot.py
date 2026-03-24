"""BootstrapFewShot prompt optimization (DSPy-inspired).

Generates high-quality demonstrations via a teacher model, scores them
through eval, and selects the best subset to inject as few-shot examples.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from evals.runner import EvalRunner, TestCase
from evals.scorer import CompositeScore
from optimizer.providers import LLMRequest, LLMRouter

from .types import (
    FewShotExample,
    OptimizationResult,
    ProConfig,
    PromptCandidate,
)

logger = logging.getLogger(__name__)


class BootstrapFewShot:
    """Bootstrap few-shot optimizer that generates and selects demonstrations.

    Algorithm:
    1. Load training cases and establish baseline score.
    2. Use a teacher LLM to generate high-quality responses for each case.
    3. Score each demonstration via eval.
    4. Try increasing subset sizes of the best demonstrations.
    5. Return the best-scoring subset if it beats baseline.
    """

    def __init__(
        self,
        llm_router: LLMRouter,
        eval_runner: EvalRunner,
        config: ProConfig,
    ) -> None:
        self.llm_router = llm_router
        self.eval_runner = eval_runner
        self.config = config

    def optimize(
        self,
        current_config: dict[str, Any],
        task_description: str = "",
    ) -> OptimizationResult:
        """Run bootstrap few-shot optimization.

        Args:
            current_config: The current agent/prompt configuration dict.
            task_description: Optional description of the task for context.

        Returns:
            OptimizationResult with the best candidate (or None if no improvement).
        """
        # Step 1: Load training cases
        training_cases = self._load_training_cases()
        if not training_cases:
            logger.warning("No training cases found; returning no-improvement result.")
            return OptimizationResult(
                best_candidate=None,
                baseline_score=0.0,
                best_score=0.0,
                algorithm="bootstrap_fewshot",
                total_eval_rounds=0,
                total_cost_dollars=self._total_cost(),
            )

        # Step 2: Get baseline score
        baseline_score = self.eval_runner.run(config=current_config)
        baseline_composite = baseline_score.composite
        eval_rounds = 1

        # Step 3: Generate and score demonstrations
        max_cases = min(len(training_cases), self.config.example_candidates * 3)
        examples: list[FewShotExample] = []

        for case in training_cases[:max_cases]:
            if self._budget_exceeded():
                logger.info("Budget exceeded; stopping example generation.")
                break

            try:
                teacher_response = self._generate_teacher_response(case)
            except Exception:
                logger.warning("Teacher LLM failed for case %s; skipping.", case.id)
                continue

            example = FewShotExample(
                user_message=case.user_message,
                assistant_response=teacher_response,
                metadata={"source_case_id": case.id},
            )

            # Score this single example by running eval with it included
            candidate_config = self._build_candidate_config(
                current_config, "", [example],
            )
            try:
                score = self.eval_runner.run(config=candidate_config)
                eval_rounds += 1
                example.quality_score = score.composite
            except Exception:
                logger.warning("Eval failed for example from case %s; skipping.", case.id)
                continue

            examples.append(example)

        if not examples:
            return OptimizationResult(
                best_candidate=None,
                baseline_score=baseline_composite,
                best_score=baseline_composite,
                algorithm="bootstrap_fewshot",
                total_eval_rounds=eval_rounds,
                total_cost_dollars=self._total_cost(),
            )

        # Step 4: Rank examples by quality score (descending)
        examples.sort(key=lambda ex: ex.quality_score, reverse=True)

        # Step 5: Try different subset sizes
        best_score = baseline_composite
        best_candidate: PromptCandidate | None = None
        max_k = min(len(examples), self.config.example_candidates)

        for k in range(1, max_k + 1):
            if self._budget_exceeded():
                logger.info("Budget exceeded; stopping subset evaluation.")
                break

            top_k = examples[:k]
            candidate_config = self._build_candidate_config(
                current_config, "", top_k,
            )
            try:
                score = self.eval_runner.run(config=candidate_config)
                eval_rounds += 1
            except Exception:
                logger.warning("Eval failed for subset size %d; skipping.", k)
                continue

            if score.composite > best_score:
                best_score = score.composite
                best_candidate = PromptCandidate(
                    instruction="",
                    examples=list(top_k),
                    eval_score=score.composite,
                    example_set_idx=k,
                    metadata={"subset_size": k},
                )

        # Step 6/7: Return result
        improvement = best_score - baseline_composite
        return OptimizationResult(
            best_candidate=best_candidate,
            baseline_score=baseline_composite,
            best_score=best_score,
            algorithm="bootstrap_fewshot",
            total_eval_rounds=eval_rounds,
            total_cost_dollars=self._total_cost(),
            candidates_evaluated=max_k,
            improvement=improvement,
        )

    def _load_training_cases(self) -> list[TestCase]:
        """Load training cases from the eval runner.

        Filters to split=='train' if any cases have splits; otherwise returns all.
        """
        all_cases = self.eval_runner.load_cases()
        train_cases = [c for c in all_cases if c.split == "train"]
        if train_cases:
            return train_cases
        # No split annotations — use all cases
        return all_cases

    def _generate_teacher_response(self, case: TestCase) -> str:
        """Use the teacher LLM to generate a high-quality demonstration response."""
        prompt = (
            f"You are an expert assistant. Provide a high-quality response.\n\n"
            f"User: {case.user_message}"
        )
        if case.reference_answer:
            prompt += (
                f"\n\nReference: {case.reference_answer}\n"
                f"Provide a response that covers these points."
            )

        request = LLMRequest(
            prompt=prompt,
            system="Generate a perfect demonstration response.",
            temperature=0.7,
            max_tokens=500,
        )
        response = self.llm_router.generate(request)
        return response.text

    def _build_candidate_config(
        self,
        base_config: dict[str, Any],
        instruction: str,
        examples: list[FewShotExample],
    ) -> dict[str, Any]:
        """Build a new config with the given instruction and examples injected."""
        config = copy.deepcopy(base_config)
        if instruction:
            config["system_prompt"] = instruction
        if examples:
            config["few_shot_examples"] = [
                {
                    "user_message": ex.user_message,
                    "assistant_response": ex.assistant_response,
                }
                for ex in examples
            ]
        return config

    def _budget_exceeded(self) -> bool:
        """Check whether total LLM cost has exceeded the configured budget."""
        cost_summary = self.llm_router.cost_summary()
        total = sum(
            float(entry.get("total_cost", 0.0))
            for entry in cost_summary.values()
        )
        return total > self.config.budget_dollars

    def _total_cost(self) -> float:
        """Return the total LLM cost accumulated so far."""
        cost_summary = self.llm_router.cost_summary()
        return sum(
            float(entry.get("total_cost", 0.0))
            for entry in cost_summary.values()
        )
