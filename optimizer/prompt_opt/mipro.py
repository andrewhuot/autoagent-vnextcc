"""MIPROv2 prompt optimization algorithm.

Multi-prompt Instruction Proposal and Optimization v2. Searches the joint
space of (instruction x few-shot examples) using Bayesian optimization with
a kNN surrogate model.
"""

from __future__ import annotations

import logging
from typing import Any

from evals.runner import EvalRunner, TestCase
from evals.scorer import CompositeScore
from optimizer.providers import LLMRequest, LLMResponse, LLMRouter

from .surrogate import BayesianSurrogate
from .types import (
    FewShotExample,
    OptimizationResult,
    ProConfig,
    PromptCandidate,
)

logger = logging.getLogger(__name__)

# Number of consecutive rounds without improvement before early stopping.
_EARLY_STOP_PATIENCE = 3


class MIPROv2:
    """Multi-prompt Instruction Proposal and Optimization v2.

    Searches the joint space of (instruction x few-shot examples) using
    Bayesian optimization with a kNN surrogate model.
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(
        self,
        current_config: dict[str, Any],
        task_description: str = "",
        failure_patterns: list[str] | None = None,
    ) -> OptimizationResult:
        """Run MIPROv2 optimization.

        1. Evaluate baseline.
        2. Generate instruction candidates via LLM meta-prompting.
        3. Bootstrap few-shot example sets from training cases.
        4. Bayesian search over (instruction, example_set) space.
        5. Return best result.
        """
        failure_patterns = failure_patterns or []

        # Step 1 — baseline
        baseline_score = self.eval_runner.run(config=current_config)
        baseline_composite = baseline_score.composite

        # Step 2 — instruction candidates
        instructions = self._propose_instructions(
            current_config, task_description, failure_patterns,
        )

        # Step 3 — example set candidates
        example_sets = self._bootstrap_example_sets(current_config)

        # Step 4 — Bayesian search
        surrogate = BayesianSurrogate(exploration_weight=1.0)

        # Build full candidate grid
        all_candidates: list[tuple[int, int]] = [
            (i, j)
            for i in range(len(instructions))
            for j in range(len(example_sets))
        ]

        best_candidate: PromptCandidate | None = None
        best_score = baseline_composite
        rounds_without_improvement = 0
        total_rounds = 0
        early_stopped = False

        for _round in range(self.config.max_eval_rounds):
            # Budget check
            if self._check_budget():
                early_stopped = True
                break

            # Get suggestion from surrogate
            candidate_idx = surrogate.suggest(all_candidates)
            instr_idx, ex_idx = candidate_idx

            # Build config with this candidate's instruction + examples
            candidate_config = dict(current_config)
            candidate_config["system_prompt"] = instructions[instr_idx]
            if example_sets[ex_idx]:
                candidate_config["few_shot_examples"] = [
                    {
                        "user_message": ex.user_message,
                        "assistant_response": ex.assistant_response,
                    }
                    for ex in example_sets[ex_idx]
                ]
            else:
                candidate_config.pop("few_shot_examples", None)

            # Evaluate
            try:
                eval_score = self.eval_runner.run(config=candidate_config)
                score_value = eval_score.composite
            except Exception:
                logger.exception("Eval failed for candidate (%d, %d)", instr_idx, ex_idx)
                score_value = 0.0

            # Record observation
            surrogate.observe(instr_idx, ex_idx, score_value)
            total_rounds += 1

            # Track best
            if score_value > best_score:
                best_score = score_value
                best_candidate = PromptCandidate(
                    instruction=instructions[instr_idx],
                    examples=list(example_sets[ex_idx]),
                    eval_score=score_value,
                    instruction_idx=instr_idx,
                    example_set_idx=ex_idx,
                )
                rounds_without_improvement = 0
            else:
                rounds_without_improvement += 1

            # Early stopping on plateau
            if rounds_without_improvement >= _EARLY_STOP_PATIENCE:
                early_stopped = True
                break

        # Compute total cost
        total_cost = self._total_cost()

        return OptimizationResult(
            best_candidate=best_candidate,
            baseline_score=baseline_composite,
            best_score=best_score,
            algorithm="miprov2",
            total_eval_rounds=total_rounds,
            total_cost_dollars=total_cost,
            candidates_evaluated=total_rounds,
            early_stopped=early_stopped,
            improvement=best_score - baseline_composite,
        )

    # ------------------------------------------------------------------
    # Instruction proposal via LLM
    # ------------------------------------------------------------------

    def _propose_instructions(
        self,
        current_config: dict[str, Any],
        task_description: str,
        failure_patterns: list[str],
    ) -> list[str]:
        """Generate N instruction candidates via LLM meta-prompting."""
        current_instruction = current_config.get(
            "system_prompt", "You are a helpful assistant.",
        )
        n = self.config.instruction_candidates

        prompt = (
            f"Generate {n} different system prompt instructions for an AI assistant.\n\n"
            f"Current instruction: {current_instruction}\n"
            f"Task: {task_description or 'General-purpose AI assistant'}\n"
            f"Known failure patterns: "
            f"{', '.join(failure_patterns) if failure_patterns else 'None identified'}\n\n"
            "Requirements:\n"
            "- Each instruction should be a complete system prompt\n"
            "- Vary the style: some concise, some detailed, some emphasizing different qualities\n"
            "- Address the known failure patterns where possible\n\n"
            f'Output format: Return exactly {n} instructions, each on its own line, '
            'prefixed with "INSTRUCTION: "'
        )

        request = LLMRequest(
            prompt=prompt,
            system="You are a prompt engineering expert.",
            temperature=0.9,
            max_tokens=2000,
        )

        try:
            response = self.llm_router.generate(request)
            text = response.text
        except Exception:
            logger.exception("LLM instruction proposal failed")
            text = ""

        instructions: list[str] = [current_instruction]  # index 0 = current
        for line in text.strip().split("\n"):
            line = line.strip()
            if line.startswith("INSTRUCTION: "):
                instructions.append(line[len("INSTRUCTION: "):].strip())

        # Pad or trim to desired count + 1 (including current)
        target = n + 1
        while len(instructions) < target:
            instructions.append(current_instruction)
        return instructions[:target]

    # ------------------------------------------------------------------
    # Example set bootstrapping
    # ------------------------------------------------------------------

    def _bootstrap_example_sets(
        self, current_config: dict[str, Any],
    ) -> list[list[FewShotExample]]:
        """Generate multiple few-shot example sets from training cases."""
        cases = self.eval_runner.load_cases()
        train_cases = [c for c in cases if c.split == "train"] or cases[:6]

        example_sets: list[list[FewShotExample]] = [[]]  # empty set as index 0

        for set_idx in range(self.config.example_candidates):
            examples: list[FewShotExample] = []
            sample_size = min(3, len(train_cases))
            if sample_size == 0:
                example_sets.append([])
                continue

            start = (set_idx * sample_size) % max(1, len(train_cases))
            sampled = [
                train_cases[(start + i) % len(train_cases)]
                for i in range(sample_size)
            ]

            for case in sampled:
                response = self._generate_teacher_response(case, current_config)
                examples.append(
                    FewShotExample(
                        user_message=case.user_message,
                        assistant_response=response,
                        quality_score=0.0,
                    )
                )
            example_sets.append(examples)

        return example_sets

    def _generate_teacher_response(
        self, case: TestCase, current_config: dict[str, Any],
    ) -> str:
        """Use the teacher LLM to generate a high-quality response for a case."""
        system = current_config.get("system_prompt", "You are a helpful assistant.")
        request = LLMRequest(
            prompt=case.user_message,
            system=system,
            temperature=0.3,
            max_tokens=1000,
        )
        try:
            response = self.llm_router.generate(request)
            return response.text
        except Exception:
            logger.exception("Teacher response generation failed")
            return case.reference_answer or "I can help with that."

    # ------------------------------------------------------------------
    # Budget tracking
    # ------------------------------------------------------------------

    def _check_budget(self) -> bool:
        """Return True if budget is exhausted."""
        return self._total_cost() >= self.config.budget_dollars

    def _total_cost(self) -> float:
        """Compute total cost across all providers."""
        summary = self.llm_router.cost_summary()
        return sum(
            v.get("total_cost", 0.0)  # type: ignore[arg-type]
            for v in summary.values()
        )
