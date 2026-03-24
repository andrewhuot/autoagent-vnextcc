"""Tests for BootstrapFewShot prompt optimization algorithm."""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from evals.runner import TestCase
from evals.scorer import CompositeScore, EvalResult
from optimizer.prompt_opt.bootstrap_fewshot import BootstrapFewShot
from optimizer.prompt_opt.types import ProConfig
from optimizer.providers import (
    LLMRequest,
    LLMResponse,
    LLMRouter,
    ModelConfig,
    RetryPolicy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_case(
    case_id: str,
    user_message: str = "Hello",
    split: str | None = "train",
    reference_answer: str = "",
) -> TestCase:
    return TestCase(
        id=case_id,
        category="happy_path",
        user_message=user_message,
        expected_specialist="support",
        expected_behavior="answer",
        split=split,
        reference_answer=reference_answer,
    )


def _make_score(composite: float, quality: float = 0.7) -> CompositeScore:
    """Build a minimal CompositeScore with controllable composite value."""
    return CompositeScore(
        quality=quality,
        safety=1.0,
        latency=0.8,
        cost=0.9,
        composite=composite,
        total_cases=5,
        passed_cases=4,
    )


def _make_llm_response(text: str = "Teacher response") -> LLMResponse:
    return LLMResponse(
        provider="mock",
        model="mock-teacher",
        text=text,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        latency_ms=5.0,
    )


class StubEvalRunner:
    """Eval runner stub that returns pre-configured scores.

    Accepts a list of scores; successive run() calls return them in order.
    Falls back to the last score when exhausted.
    """

    def __init__(
        self,
        cases: list[TestCase],
        scores: list[CompositeScore],
    ) -> None:
        self._cases = cases
        self._scores = list(scores)
        self._call_idx = 0
        self.run_configs: list[dict | None] = []

    def load_cases(self) -> list[TestCase]:
        return list(self._cases)

    def run(self, config: dict | None = None, **kwargs: Any) -> CompositeScore:
        self.run_configs.append(config)
        score = self._scores[min(self._call_idx, len(self._scores) - 1)]
        self._call_idx += 1
        return score

    def run_cases(
        self, cases: list[TestCase], config: dict | None = None, **kwargs: Any
    ) -> CompositeScore:
        return self.run(config=config)


class StubLLMRouter:
    """LLM router stub that records calls and returns predetermined responses."""

    def __init__(
        self,
        responses: list[LLMResponse] | None = None,
        cost: float = 0.0,
    ) -> None:
        self._responses = responses or [_make_llm_response()]
        self._call_idx = 0
        self._cost = cost
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        resp = self._responses[min(self._call_idx, len(self._responses) - 1)]
        self._call_idx += 1
        return resp

    def cost_summary(self) -> dict[str, dict[str, float | int]]:
        return {"mock:mock-teacher": {"total_cost": self._cost, "requests": self._call_idx}}


class FailingLLMRouter(StubLLMRouter):
    """LLM router that raises on generate()."""

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        raise RuntimeError("LLM call failed")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_bootstrap_generates_examples_from_training_cases() -> None:
    """Teacher LLM is called once per training case (up to limit)."""
    cases = [_make_case(f"case_{i}") for i in range(4)]
    config = ProConfig(example_candidates=2)  # limit = 2*3 = 6, but only 4 cases
    # baseline + 4 individual scores + up to 2 subset scores
    scores = [_make_score(0.5)] * 10
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = StubLLMRouter()

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    optimizer.optimize({"system_prompt": "Be helpful."})

    # Teacher should be called once per case
    assert len(llm_router.requests) == 4


def test_bootstrap_selects_best_examples_by_score() -> None:
    """Examples should be ranked by quality_score; top-k used for subsets."""
    cases = [_make_case(f"case_{i}", user_message=f"Q{i}") for i in range(3)]
    config = ProConfig(example_candidates=2)

    # baseline=0.5, then individual scores: 0.6, 0.9, 0.3, then subset scores
    scores = [
        _make_score(0.5),   # baseline
        _make_score(0.6),   # case_0 individual
        _make_score(0.9),   # case_1 individual
        _make_score(0.3),   # case_2 individual
        _make_score(0.85),  # subset k=1 (top example = case_1 with 0.9)
        _make_score(0.88),  # subset k=2
    ]
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = StubLLMRouter(
        responses=[
            _make_llm_response("Response 0"),
            _make_llm_response("Response 1"),
            _make_llm_response("Response 2"),
        ]
    )

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    result = optimizer.optimize({"system_prompt": "Be helpful."})

    assert result.best_candidate is not None
    # Best subset should be k=2 with score 0.88
    assert result.best_score == 0.88
    # First example in the sorted list should be the one with quality_score=0.9
    assert result.best_candidate.examples[0].quality_score == 0.9


def test_bootstrap_returns_improvement_when_candidate_beats_baseline() -> None:
    """Happy path: best candidate beats baseline."""
    cases = [_make_case("case_0")]
    config = ProConfig(example_candidates=1)

    scores = [
        _make_score(0.5),   # baseline
        _make_score(0.7),   # individual score
        _make_score(0.8),   # subset k=1
    ]
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = StubLLMRouter()

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    result = optimizer.optimize({"system_prompt": "test"})

    assert result.improved is True
    assert result.best_candidate is not None
    assert result.best_score == 0.8
    assert result.baseline_score == 0.5
    assert result.improvement == pytest.approx(0.3)
    assert result.algorithm == "bootstrap_fewshot"


def test_bootstrap_returns_none_when_no_improvement() -> None:
    """When no candidate beats baseline, best_candidate should be None."""
    cases = [_make_case("case_0")]
    config = ProConfig(example_candidates=1)

    scores = [
        _make_score(0.8),   # baseline (high)
        _make_score(0.5),   # individual score
        _make_score(0.6),   # subset k=1 (still below baseline)
    ]
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = StubLLMRouter()

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    result = optimizer.optimize({"system_prompt": "test"})

    assert result.improved is False
    assert result.best_candidate is None
    assert result.best_score == 0.8  # stays at baseline
    assert result.improvement == 0.0


def test_bootstrap_respects_example_candidates_limit() -> None:
    """Number of examples tried should not exceed config.example_candidates."""
    cases = [_make_case(f"case_{i}") for i in range(20)]
    config = ProConfig(example_candidates=2)  # max 2*3=6 cases processed

    scores = [_make_score(0.5)] * 20
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = StubLLMRouter()

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    optimizer.optimize({"system_prompt": "test"})

    # Teacher called for min(20, 2*3) = 6 cases
    assert len(llm_router.requests) == 6


def test_bootstrap_handles_empty_training_set() -> None:
    """Graceful handling when no training cases are available."""
    config = ProConfig(example_candidates=3)
    eval_runner = StubEvalRunner(cases=[], scores=[_make_score(0.5)])
    llm_router = StubLLMRouter()

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    result = optimizer.optimize({"system_prompt": "test"})

    assert result.best_candidate is None
    assert result.total_eval_rounds == 0
    assert len(llm_router.requests) == 0


def test_bootstrap_handles_llm_failure_gracefully() -> None:
    """LLM errors should be caught and skipped, not crash the optimizer."""
    cases = [_make_case("case_0"), _make_case("case_1")]
    config = ProConfig(example_candidates=2)

    scores = [_make_score(0.5)] * 5
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = FailingLLMRouter()

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    result = optimizer.optimize({"system_prompt": "test"})

    # Should not crash; no examples generated since LLM failed
    assert result.best_candidate is None
    assert result.baseline_score == 0.5


def test_bootstrap_tracks_cost() -> None:
    """Cost tracking via LLMRouter.cost_summary() is reflected in result."""
    cases = [_make_case("case_0")]
    config = ProConfig(example_candidates=1)

    scores = [_make_score(0.5), _make_score(0.6), _make_score(0.7)]
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = StubLLMRouter(cost=0.42)

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    result = optimizer.optimize({"system_prompt": "test"})

    assert result.total_cost_dollars == 0.42


def test_bootstrap_result_to_config_patch() -> None:
    """OptimizationResult.to_config_patch() returns correct patch structure."""
    cases = [_make_case("case_0")]
    config = ProConfig(example_candidates=1)

    scores = [
        _make_score(0.5),   # baseline
        _make_score(0.7),   # individual
        _make_score(0.8),   # subset k=1
    ]
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = StubLLMRouter(responses=[_make_llm_response("Great answer")])

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    result = optimizer.optimize({"system_prompt": "test"})

    patch = result.to_config_patch()
    assert patch is not None
    assert "few_shot_examples" in patch
    assert len(patch["few_shot_examples"]) == 1
    assert patch["few_shot_examples"][0]["assistant_response"] == "Great answer"
    # No instruction was set, so system_prompt should not be in patch
    assert "system_prompt" not in patch


def test_bootstrap_uses_reference_answer_in_prompt() -> None:
    """When a case has a reference_answer, it should appear in the teacher prompt."""
    cases = [_make_case("case_0", reference_answer="The answer is 42.")]
    config = ProConfig(example_candidates=1)

    scores = [_make_score(0.5), _make_score(0.6), _make_score(0.7)]
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = StubLLMRouter()

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    optimizer.optimize({"system_prompt": "test"})

    assert len(llm_router.requests) >= 1
    prompt = llm_router.requests[0].prompt
    assert "The answer is 42." in prompt
    assert "Reference:" in prompt


def test_bootstrap_tries_multiple_subset_sizes() -> None:
    """Optimizer should try k=1, k=2, ..., k=example_candidates subsets."""
    cases = [_make_case(f"case_{i}") for i in range(5)]
    config = ProConfig(example_candidates=3)

    # baseline + 5 individual + 3 subset evals
    scores = [
        _make_score(0.5),   # baseline
        _make_score(0.6),   # case_0
        _make_score(0.7),   # case_1
        _make_score(0.65),  # case_2
        _make_score(0.55),  # case_3
        _make_score(0.58),  # case_4
        _make_score(0.72),  # subset k=1
        _make_score(0.75),  # subset k=2
        _make_score(0.73),  # subset k=3
    ]
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = StubLLMRouter()

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    result = optimizer.optimize({"system_prompt": "test"})

    # Should have run: 1 baseline + 5 individual + 3 subset = 9 eval runs
    assert eval_runner._call_idx == 9
    assert result.candidates_evaluated == 3
    # Best subset is k=2 with score 0.75
    assert result.best_score == 0.75
    assert result.best_candidate is not None
    assert result.best_candidate.metadata["subset_size"] == 2


def test_bootstrap_preserves_base_config() -> None:
    """The original config dict must not be mutated during optimization."""
    cases = [_make_case("case_0")]
    config = ProConfig(example_candidates=1)

    scores = [_make_score(0.5), _make_score(0.6), _make_score(0.8)]
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = StubLLMRouter()

    original = {"system_prompt": "Be helpful.", "nested": {"key": "value"}}
    frozen = copy.deepcopy(original)

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    optimizer.optimize(original)

    assert original == frozen, "Base config was mutated during optimization"


def test_bootstrap_budget_stops_generation() -> None:
    """When budget is exceeded, optimization stops early."""
    cases = [_make_case(f"case_{i}") for i in range(10)]
    config = ProConfig(example_candidates=5, budget_dollars=0.01)

    scores = [_make_score(0.5)] * 20
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    # Cost exceeds budget immediately
    llm_router = StubLLMRouter(cost=100.0)

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    result = optimizer.optimize({"system_prompt": "test"})

    # Should have stopped early — only baseline eval + possibly first case
    assert result.total_eval_rounds <= 2


def test_bootstrap_filters_train_split() -> None:
    """When cases have split annotations, only 'train' cases are used."""
    cases = [
        _make_case("train_0", split="train"),
        _make_case("train_1", split="train"),
        _make_case("test_0", split="test"),
        _make_case("test_1", split="test"),
    ]
    config = ProConfig(example_candidates=3)

    scores = [_make_score(0.5)] * 10
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = StubLLMRouter()

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    optimizer.optimize({"system_prompt": "test"})

    # Only 2 train cases, so teacher should be called twice
    assert len(llm_router.requests) == 2


def test_bootstrap_uses_all_cases_when_no_splits() -> None:
    """When no cases have split annotations, all cases are used."""
    cases = [
        _make_case("case_0", split=None),
        _make_case("case_1", split=None),
        _make_case("case_2", split=None),
    ]
    config = ProConfig(example_candidates=3)

    scores = [_make_score(0.5)] * 15
    eval_runner = StubEvalRunner(cases=cases, scores=scores)
    llm_router = StubLLMRouter()

    optimizer = BootstrapFewShot(llm_router, eval_runner, config)
    optimizer.optimize({"system_prompt": "test"})

    assert len(llm_router.requests) == 3
