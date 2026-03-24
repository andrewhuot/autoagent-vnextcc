"""Tests for MIPROv2 optimizer and BayesianSurrogate."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from evals.runner import EvalRunner, TestCase
from evals.scorer import CompositeScore, EvalResult
from optimizer.prompt_opt.mipro import MIPROv2, _EARLY_STOP_PATIENCE
from optimizer.prompt_opt.surrogate import BayesianSurrogate
from optimizer.prompt_opt.types import (
    FewShotExample,
    OptimizationResult,
    ProConfig,
    PromptCandidate,
)
from optimizer.providers import LLMRequest, LLMResponse, LLMRouter, ModelConfig


# ======================================================================
# Helpers
# ======================================================================


def _make_score(composite: float, quality: float = 0.7) -> CompositeScore:
    """Build a minimal CompositeScore with controllable composite value."""
    return CompositeScore(
        quality=quality,
        safety=1.0,
        latency=0.9,
        cost=0.8,
        composite=composite,
        total_cases=10,
        passed_cases=8,
    )


def _make_eval_result(case_id: str = "c1", quality: float = 0.8) -> EvalResult:
    return EvalResult(
        case_id=case_id,
        category="happy_path",
        passed=quality >= 0.5,
        quality_score=quality,
        safety_passed=True,
        latency_ms=100.0,
        token_count=50,
    )


def _make_test_case(
    case_id: str = "tc1",
    split: str | None = "train",
    user_message: str = "Hello",
) -> TestCase:
    return TestCase(
        id=case_id,
        category="happy_path",
        user_message=user_message,
        expected_specialist="support",
        expected_behavior="answer",
        split=split,
        reference_answer="Hi there!",
    )


class StubLLMRouter:
    """LLM router that returns predetermined responses."""

    def __init__(
        self,
        text: str = "",
        cost: float = 0.0,
        fail: bool = False,
    ) -> None:
        self._text = text
        self._cost = cost
        self._fail = fail
        self.generate_calls: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.generate_calls.append(request)
        if self._fail:
            raise RuntimeError("LLM unavailable")
        return LLMResponse(
            provider="mock",
            model="mock-model",
            text=self._text,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            latency_ms=50.0,
        )

    def cost_summary(self) -> dict[str, dict[str, float | int]]:
        return {
            "mock:mock-model": {
                "requests": len(self.generate_calls),
                "prompt_tokens": 10 * len(self.generate_calls),
                "completion_tokens": 20 * len(self.generate_calls),
                "total_cost": self._cost,
            }
        }


class SequencedEvalRunner:
    """EvalRunner substitute that returns pre-seeded scores in sequence."""

    def __init__(
        self,
        scores: list[CompositeScore],
        cases: list[TestCase] | None = None,
    ) -> None:
        self._scores = scores
        self._cases = cases or []
        self._call_idx = 0

    def run(self, config: dict | None = None, **kwargs: Any) -> CompositeScore:
        idx = min(self._call_idx, len(self._scores) - 1)
        self._call_idx += 1
        return self._scores[idx]

    def load_cases(self) -> list[TestCase]:
        return self._cases

    def run_cases(
        self, cases: list[TestCase], config: dict | None = None, **kwargs: Any,
    ) -> CompositeScore:
        return self.run(config=config)


# ======================================================================
# Surrogate tests
# ======================================================================


class TestBayesianSurrogateNoObservations:
    """Cold-start behaviour."""

    def test_returns_first_candidate(self) -> None:
        s = BayesianSurrogate()
        candidates = [(0, 0), (1, 0), (0, 1)]
        assert s.suggest(candidates) == (0, 0)

    def test_best_observed_is_none(self) -> None:
        s = BayesianSurrogate()
        assert s.best_observed() is None


class TestBayesianSurrogateObserveAndBest:
    """best_observed tracks the maximum score."""

    def test_single_observation(self) -> None:
        s = BayesianSurrogate()
        s.observe(1, 2, 0.75)
        assert s.best_observed() == ((1, 2), 0.75)

    def test_multiple_observations_tracks_max(self) -> None:
        s = BayesianSurrogate()
        s.observe(0, 0, 0.5)
        s.observe(1, 1, 0.9)
        s.observe(2, 0, 0.3)
        best = s.best_observed()
        assert best is not None
        assert best[0] == (1, 1)
        assert best[1] == 0.9


class TestBayesianSurrogateSuggest:
    """suggest() avoids re-suggesting tried candidates."""

    def test_suggests_untried_candidates(self) -> None:
        s = BayesianSurrogate()
        s.observe(0, 0, 0.5)
        candidates = [(0, 0), (1, 0), (0, 1)]
        result = s.suggest(candidates)
        assert result != (0, 0)
        assert result in [(1, 0), (0, 1)]

    def test_all_tried_still_returns_something(self) -> None:
        s = BayesianSurrogate()
        s.observe(0, 0, 0.5)
        s.observe(1, 0, 0.7)
        candidates = [(0, 0), (1, 0)]
        result = s.suggest(candidates)
        assert result in candidates


class TestBayesianSurrogateUCB:
    """UCB exploration bonus behaviour."""

    def test_exploration_bonus_favors_unexplored(self) -> None:
        s = BayesianSurrogate(exploration_weight=10.0)
        # Observe one region heavily
        for _ in range(5):
            s.observe(0, 0, 0.8)
        # Candidate (2, 2) is completely unexplored — should get high UCB
        candidates = [(0, 0), (2, 2)]
        result = s.suggest(candidates)
        assert result == (2, 2)

    def test_zero_exploration_weight_picks_best_estimate(self) -> None:
        s = BayesianSurrogate(exploration_weight=0.0)
        s.observe(0, 0, 0.9)
        s.observe(1, 1, 0.3)
        candidates = [(0, 0), (1, 1), (2, 2)]
        # (0,0) and (1,1) are tried; untried is (2,2)
        # With zero exploration, estimate for (2,2) is 0 (no similar obs),
        # but it's the only untried candidate
        result = s.suggest(candidates)
        assert result == (2, 2)


class TestBayesianSurrogateSimilarity:
    """Similarity metric correctness."""

    def test_exact_match(self) -> None:
        s = BayesianSurrogate()
        assert s._similarity((1, 2), (1, 2)) == 1.0

    def test_partial_match_first_index(self) -> None:
        s = BayesianSurrogate()
        assert s._similarity((1, 2), (1, 9)) == 0.5

    def test_partial_match_second_index(self) -> None:
        s = BayesianSurrogate()
        assert s._similarity((3, 2), (7, 2)) == 0.5

    def test_no_match(self) -> None:
        s = BayesianSurrogate()
        assert s._similarity((1, 2), (3, 4)) == 0.0


class TestBayesianSurrogateEstimate:
    """kNN estimation correctness."""

    def test_estimate_with_exact_observation(self) -> None:
        s = BayesianSurrogate(k=3)
        s.observe(1, 1, 0.8)
        # Exact match has similarity 1.0, so estimate should be 0.8
        assert s._estimate_score((1, 1)) == pytest.approx(0.8)

    def test_estimate_with_partial_neighbors(self) -> None:
        s = BayesianSurrogate(k=3)
        s.observe(0, 0, 0.6)
        s.observe(0, 1, 0.8)
        # (0, 2) shares first index with both → similarity 0.5 each
        # estimate = (0.5*0.6 + 0.5*0.8) / (0.5+0.5) = 0.7
        assert s._estimate_score((0, 2)) == pytest.approx(0.7)

    def test_estimate_no_similar_returns_zero(self) -> None:
        s = BayesianSurrogate(k=3)
        s.observe(0, 0, 0.9)
        # (5, 5) has no index overlap with (0, 0) → similarity 0.0
        assert s._estimate_score((5, 5)) == pytest.approx(0.0)

    def test_suggest_raises_on_empty_candidates(self) -> None:
        s = BayesianSurrogate()
        with pytest.raises(ValueError, match="empty"):
            s.suggest([])


# ======================================================================
# MIPROv2 tests
# ======================================================================


def _build_mipro(
    scores: list[CompositeScore],
    llm_text: str = "",
    cases: list[TestCase] | None = None,
    config: ProConfig | None = None,
    llm_cost: float = 0.0,
    llm_fail: bool = False,
) -> tuple[MIPROv2, StubLLMRouter, SequencedEvalRunner]:
    """Helper to build a MIPROv2 with test doubles."""
    cfg = config or ProConfig(
        instruction_candidates=2,
        example_candidates=2,
        max_eval_rounds=5,
        budget_dollars=10.0,
    )
    router = StubLLMRouter(text=llm_text, cost=llm_cost, fail=llm_fail)
    runner = SequencedEvalRunner(scores=scores, cases=cases)
    mipro = MIPROv2(llm_router=router, eval_runner=runner, config=cfg)  # type: ignore[arg-type]
    return mipro, router, runner


class TestMIPROReturnsImprovement:
    """Happy path: best candidate improves over baseline."""

    def test_returns_improvement(self) -> None:
        # baseline=0.5, then candidate evals return 0.7, 0.6, 0.8, ...
        scores = [_make_score(0.5), _make_score(0.7), _make_score(0.6), _make_score(0.8)]
        cases = [_make_test_case(f"tc{i}") for i in range(3)]
        mipro, _, _ = _build_mipro(scores, llm_text="INSTRUCTION: Be great", cases=cases)

        result = mipro.optimize({"system_prompt": "Be helpful"})

        assert result.improved
        assert result.best_score > result.baseline_score
        assert result.best_candidate is not None
        assert result.algorithm == "miprov2"


class TestMIPRONoImprovement:
    """All candidates worse than baseline."""

    def test_returns_none_when_no_improvement(self) -> None:
        # baseline=0.8, all candidates worse
        scores = [_make_score(0.8)] + [_make_score(0.3)] * 10
        cases = [_make_test_case(f"tc{i}") for i in range(3)]
        mipro, _, _ = _build_mipro(scores, llm_text="INSTRUCTION: Be great", cases=cases)

        result = mipro.optimize({"system_prompt": "Be helpful"})

        assert not result.improved
        assert result.best_candidate is None


class TestMIPROInstructionCandidates:
    """LLM is called to generate instruction proposals."""

    def test_generates_instruction_candidates(self) -> None:
        scores = [_make_score(0.5)] + [_make_score(0.6)] * 10
        cases = [_make_test_case(f"tc{i}") for i in range(3)]
        llm_text = "INSTRUCTION: Be concise\nINSTRUCTION: Be thorough"
        mipro, router, _ = _build_mipro(scores, llm_text=llm_text, cases=cases)

        mipro.optimize({"system_prompt": "Be helpful"})

        # At least one call should be for instruction generation (contains "Generate")
        assert any(
            "Generate" in call.prompt for call in router.generate_calls
        )


class TestMIPROBootstrapsExampleSets:
    """Example sets are generated from training cases."""

    def test_bootstraps_example_sets(self) -> None:
        scores = [_make_score(0.5)] + [_make_score(0.6)] * 10
        cases = [
            _make_test_case("tc1", split="train", user_message="Q1"),
            _make_test_case("tc2", split="train", user_message="Q2"),
            _make_test_case("tc3", split="train", user_message="Q3"),
        ]
        mipro, router, _ = _build_mipro(
            scores, llm_text="INSTRUCTION: Be great", cases=cases,
        )

        result = mipro.optimize({"system_prompt": "Be helpful"})

        # Teacher calls should include the training case user messages
        teacher_prompts = [c.prompt for c in router.generate_calls]
        # At least some prompts should be the raw user messages from cases
        user_messages = {c.user_message for c in cases}
        assert any(p in user_messages for p in teacher_prompts)


class TestMIPRORespectsMaxEvalRounds:
    """Stops at config.max_eval_rounds."""

    def test_respects_max_eval_rounds(self) -> None:
        max_rounds = 3
        # Provide enough scores: 1 baseline + max_rounds candidate evals
        # Each candidate is better than the last to avoid early stopping
        scores = [_make_score(0.5), _make_score(0.6), _make_score(0.7), _make_score(0.8)]
        cases = [_make_test_case(f"tc{i}") for i in range(3)]
        config = ProConfig(
            instruction_candidates=2,
            example_candidates=2,
            max_eval_rounds=max_rounds,
            budget_dollars=100.0,
        )
        mipro, _, runner = _build_mipro(
            scores, llm_text="INSTRUCTION: A\nINSTRUCTION: B",
            cases=cases, config=config,
        )

        result = mipro.optimize({"system_prompt": "Be helpful"})

        assert result.total_eval_rounds <= max_rounds


class TestMIPROEarlyStopsOnPlateau:
    """Stops after _EARLY_STOP_PATIENCE rounds of no improvement."""

    def test_early_stops_on_plateau(self) -> None:
        # baseline=0.5, then all candidates return same 0.4 (never improves)
        patience = _EARLY_STOP_PATIENCE
        scores = [_make_score(0.5)] + [_make_score(0.4)] * 20
        cases = [_make_test_case(f"tc{i}") for i in range(3)]
        config = ProConfig(
            instruction_candidates=2,
            example_candidates=2,
            max_eval_rounds=20,
            budget_dollars=100.0,
        )
        mipro, _, _ = _build_mipro(
            scores, llm_text="INSTRUCTION: X", cases=cases, config=config,
        )

        result = mipro.optimize({"system_prompt": "Be helpful"})

        assert result.early_stopped
        assert result.total_eval_rounds == patience


class TestMIPRORespectsBudget:
    """Stops when cost exceeds budget."""

    def test_respects_budget(self) -> None:
        scores = [_make_score(0.5)] + [_make_score(0.6)] * 10
        cases = [_make_test_case(f"tc{i}") for i in range(3)]
        config = ProConfig(
            instruction_candidates=2,
            example_candidates=2,
            max_eval_rounds=20,
            budget_dollars=0.01,  # very low budget
        )
        mipro, _, _ = _build_mipro(
            scores,
            llm_text="INSTRUCTION: X",
            cases=cases,
            config=config,
            llm_cost=1.0,  # already over budget
        )

        result = mipro.optimize({"system_prompt": "Be helpful"})

        assert result.early_stopped
        assert result.total_eval_rounds == 0


class TestMIPROIncludesCurrentInstructionAsCandidateZero:
    """Baseline instruction is always candidate 0."""

    def test_includes_current_instruction_as_candidate_zero(self) -> None:
        scores = [_make_score(0.5)] + [_make_score(0.6)] * 10
        cases = [_make_test_case(f"tc{i}") for i in range(3)]
        mipro, _, _ = _build_mipro(
            scores, llm_text="INSTRUCTION: New thing", cases=cases,
        )

        instructions = mipro._propose_instructions(
            {"system_prompt": "Original prompt"},
            "some task",
            [],
        )

        assert instructions[0] == "Original prompt"


class TestMIPROIncludesEmptyExampleSetAsCandidateZero:
    """Empty example set is always candidate 0."""

    def test_includes_empty_example_set_as_candidate_zero(self) -> None:
        scores = [_make_score(0.5)] + [_make_score(0.6)] * 10
        cases = [_make_test_case(f"tc{i}") for i in range(3)]
        mipro, _, _ = _build_mipro(
            scores, llm_text="INSTRUCTION: X", cases=cases,
        )

        example_sets = mipro._bootstrap_example_sets(
            {"system_prompt": "Be helpful"},
        )

        assert example_sets[0] == []


class TestMIPROHandlesEmptyTrainingSet:
    """Graceful with no training cases."""

    def test_handles_empty_training_set(self) -> None:
        scores = [_make_score(0.5)] + [_make_score(0.4)] * 10
        mipro, _, _ = _build_mipro(
            scores, llm_text="INSTRUCTION: X", cases=[],
        )

        result = mipro.optimize({"system_prompt": "Be helpful"})

        # Should not crash; may early-stop due to no improvement
        assert isinstance(result, OptimizationResult)


class TestMIPROHandlesLLMFailure:
    """LLM error doesn't crash the optimizer."""

    def test_handles_llm_failure(self) -> None:
        scores = [_make_score(0.5)] + [_make_score(0.4)] * 10
        cases = [_make_test_case(f"tc{i}") for i in range(3)]
        mipro, _, _ = _build_mipro(
            scores,
            llm_text="",
            cases=cases,
            llm_fail=True,
        )

        result = mipro.optimize({"system_prompt": "Be helpful"})

        assert isinstance(result, OptimizationResult)
        assert result.algorithm == "miprov2"


class TestMIPROResultMetadata:
    """Result has correct metadata fields."""

    def test_result_has_correct_metadata(self) -> None:
        scores = [_make_score(0.5), _make_score(0.7), _make_score(0.6)]
        cases = [_make_test_case(f"tc{i}") for i in range(3)]
        mipro, _, _ = _build_mipro(
            scores, llm_text="INSTRUCTION: Better", cases=cases,
        )

        result = mipro.optimize({"system_prompt": "Be helpful"})

        assert result.algorithm == "miprov2"
        assert result.total_eval_rounds >= 1
        assert isinstance(result.total_cost_dollars, float)
        assert result.baseline_score == 0.5
        assert result.candidates_evaluated == result.total_eval_rounds


class TestMIPRODefaultSystemPrompt:
    """Uses default system prompt when none provided."""

    def test_default_system_prompt(self) -> None:
        scores = [_make_score(0.5)] + [_make_score(0.6)] * 10
        cases = [_make_test_case(f"tc{i}") for i in range(3)]
        mipro, _, _ = _build_mipro(
            scores, llm_text="INSTRUCTION: New", cases=cases,
        )

        instructions = mipro._propose_instructions({}, "task", [])

        assert instructions[0] == "You are a helpful assistant."


class TestMIPROFailurePatternsPassedToLLM:
    """Failure patterns are included in the instruction proposal prompt."""

    def test_failure_patterns_in_prompt(self) -> None:
        scores = [_make_score(0.5)] + [_make_score(0.6)] * 10
        cases = [_make_test_case(f"tc{i}") for i in range(3)]
        mipro, router, _ = _build_mipro(
            scores, llm_text="INSTRUCTION: Better", cases=cases,
        )

        mipro.optimize(
            {"system_prompt": "Be helpful"},
            failure_patterns=["too verbose", "misroutes safety"],
        )

        # The instruction-proposal call should mention failure patterns
        instruction_call = next(
            (c for c in router.generate_calls if "Generate" in c.prompt), None,
        )
        assert instruction_call is not None
        assert "too verbose" in instruction_call.prompt


class TestMIPROExampleSetDiversity:
    """Example sets sample different subsets of training data."""

    def test_example_sets_have_diversity(self) -> None:
        scores = [_make_score(0.5)] + [_make_score(0.6)] * 10
        cases = [
            _make_test_case(f"tc{i}", split="train", user_message=f"Question {i}")
            for i in range(6)
        ]
        config = ProConfig(
            instruction_candidates=1,
            example_candidates=3,
            max_eval_rounds=5,
            budget_dollars=100.0,
        )
        mipro, _, _ = _build_mipro(
            scores, llm_text="INSTRUCTION: X", cases=cases, config=config,
        )

        example_sets = mipro._bootstrap_example_sets({"system_prompt": "X"})

        # Should have 1 (empty) + 3 example sets
        assert len(example_sets) == 4
        assert example_sets[0] == []
        # Non-empty sets should have examples
        for es in example_sets[1:]:
            assert len(es) > 0
            assert all(isinstance(e, FewShotExample) for e in es)


class TestMIPROImprovementCalculation:
    """improvement field is best_score - baseline_score."""

    def test_improvement_calculation(self) -> None:
        scores = [_make_score(0.5), _make_score(0.9)]
        cases = [_make_test_case("tc1")]
        mipro, _, _ = _build_mipro(
            scores, llm_text="INSTRUCTION: Great", cases=cases,
        )

        result = mipro.optimize({"system_prompt": "X"})

        assert result.improvement == pytest.approx(result.best_score - result.baseline_score)
