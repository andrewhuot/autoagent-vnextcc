"""Tests for LLM-backed pairwise judge with SQLite cache + strict-live (R3.7)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from evals.judges.pairwise_judge import (
    PairwiseJudgeCache,
    PairwiseJudgeVerdict,
    PairwiseLLMJudge,
)
from evals.runner import TestCase
from evals.scorer import EvalResult


def _case(case_id: str = "c1") -> TestCase:
    return TestCase(
        id=case_id,
        category="happy_path",
        user_message="hello",
        expected_specialist="support",
        expected_behavior="answer",
        reference_answer="hi there",
    )


def _eval_result(*, safety_passed: bool = True, quality_score: float = 0.5) -> EvalResult:
    return EvalResult(
        case_id="c1",
        category="happy_path",
        passed=True,
        quality_score=quality_score,
        safety_passed=safety_passed,
        latency_ms=100.0,
        token_count=50,
    )


def _kwargs(**overrides):
    base = dict(
        case=_case(),
        label_a="variant_a",
        label_b="variant_b",
        output_a={"response": "short answer A"},
        output_b={"response": "short answer B"},
        eval_a=_eval_result(),
        eval_b=_eval_result(),
    )
    base.update(overrides)
    return base


def _json_llm_response(winner: str, confidence: float, rationale: str) -> MagicMock:
    resp = MagicMock()
    resp.text = json.dumps(
        {"winner": winner, "confidence": confidence, "rationale": rationale}
    )
    resp.model = "mock"
    return resp


def test_cache_miss_calls_llm_then_caches_second_hit(tmp_path) -> None:
    router = MagicMock()
    router.generate.return_value = _json_llm_response(
        "variant_a", 0.82, "tighter wording"
    )
    cache = PairwiseJudgeCache(db_path=str(tmp_path / "c.db"))
    judge = PairwiseLLMJudge(llm_router=router, cache=cache)

    v1 = judge.judge_case(**_kwargs())
    assert v1.winner == "variant_a"
    assert v1.confidence == 0.82
    assert "tighter" in v1.reasoning
    assert router.generate.call_count == 1

    v2 = judge.judge_case(**_kwargs())  # identical inputs
    assert v2.winner == "variant_a"
    assert router.generate.call_count == 1, "second identical call must hit cache"


def test_cache_ttl_expires_after_30_days(tmp_path, monkeypatch) -> None:
    clock = [1_700_000_000.0]
    monkeypatch.setattr(
        "evals.judges.pairwise_judge.time.time", lambda: clock[0]
    )
    router = MagicMock()
    router.generate.return_value = _json_llm_response("variant_b", 0.5, "x")
    cache = PairwiseJudgeCache(db_path=str(tmp_path / "c.db"))
    judge = PairwiseLLMJudge(llm_router=router, cache=cache)

    judge.judge_case(**_kwargs())
    assert router.generate.call_count == 1

    clock[0] += 31 * 86400  # 31 days later
    judge.judge_case(**_kwargs())
    assert router.generate.call_count == 2, "expired entry must trigger re-call"


def test_cache_key_differs_for_different_responses(tmp_path) -> None:
    router = MagicMock()
    router.generate.side_effect = [
        _json_llm_response("variant_a", 0.7, "first"),
        _json_llm_response("variant_b", 0.7, "second"),
    ]
    cache = PairwiseJudgeCache(db_path=str(tmp_path / "c.db"))
    judge = PairwiseLLMJudge(llm_router=router, cache=cache)

    judge.judge_case(**_kwargs(output_a={"response": "aaa"}))
    judge.judge_case(**_kwargs(output_a={"response": "bbb"}))
    assert router.generate.call_count == 2, "different responses -> different keys"


def test_llm_invalid_json_falls_back_to_heuristic(tmp_path) -> None:
    router = MagicMock()
    bad = MagicMock()
    bad.text = "not json at all"
    router.generate.return_value = bad
    cache = PairwiseJudgeCache(db_path=str(tmp_path / "c.db"))
    judge = PairwiseLLMJudge(llm_router=router, cache=cache, strict_live=False)
    v = judge.judge_case(**_kwargs())
    assert isinstance(v, PairwiseJudgeVerdict)


def test_llm_schema_violation_falls_back_to_heuristic(tmp_path) -> None:
    router = MagicMock()
    invalid = MagicMock()
    invalid.text = json.dumps(
        {"winner": "neither", "confidence": 0.5, "rationale": "x"}
    )
    router.generate.return_value = invalid
    cache = PairwiseJudgeCache(db_path=str(tmp_path / "c.db"))
    judge = PairwiseLLMJudge(llm_router=router, cache=cache, strict_live=False)
    v = judge.judge_case(**_kwargs())
    assert isinstance(v, PairwiseJudgeVerdict)


def test_strict_live_raises_when_llm_fails(tmp_path) -> None:
    router = MagicMock()
    router.generate.side_effect = RuntimeError("provider 500")
    cache = PairwiseJudgeCache(db_path=str(tmp_path / "c.db"))
    judge = PairwiseLLMJudge(llm_router=router, cache=cache, strict_live=True)
    with pytest.raises(RuntimeError):
        judge.judge_case(**_kwargs())


def test_strict_live_raises_on_schema_violation(tmp_path) -> None:
    router = MagicMock()
    bad = MagicMock()
    bad.text = "{"
    router.generate.return_value = bad
    cache = PairwiseJudgeCache(db_path=str(tmp_path / "c.db"))
    judge = PairwiseLLMJudge(llm_router=router, cache=cache, strict_live=True)
    with pytest.raises(RuntimeError):
        judge.judge_case(**_kwargs())


def test_heuristic_path_when_router_none() -> None:
    """Without a router (today's default), heuristic still works byte-for-byte."""
    judge = PairwiseLLMJudge()
    v = judge.judge_case(**_kwargs())
    assert isinstance(v, PairwiseJudgeVerdict)
    assert v.winner in ("variant_a", "variant_b", "tie")


def test_backwards_compat_zero_arg_constructor() -> None:
    """PairwiseLLMJudge() — today's caller shape — still works."""
    judge = PairwiseLLMJudge()
    assert judge._router is None
    assert judge._cache is None
    assert judge._strict_live is False


def test_cache_survives_process_restart(tmp_path) -> None:
    """The cache is SQLite-backed; two PairwiseJudgeCache instances on the same
    db_path share entries."""
    db_path = str(tmp_path / "c.db")
    router = MagicMock()
    router.generate.return_value = _json_llm_response("variant_a", 0.7, "persist")
    cache1 = PairwiseJudgeCache(db_path=db_path)
    judge1 = PairwiseLLMJudge(llm_router=router, cache=cache1)
    judge1.judge_case(**_kwargs())

    cache2 = PairwiseJudgeCache(db_path=db_path)
    judge2 = PairwiseLLMJudge(llm_router=router, cache=cache2)
    judge2.judge_case(**_kwargs())
    assert router.generate.call_count == 1
