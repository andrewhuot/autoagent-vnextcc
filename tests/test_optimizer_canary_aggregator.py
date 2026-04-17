"""Tests for optimizer.canary_scoring.CanaryScoringAggregator."""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest

from evals.judges.pairwise_judge import PairwiseJudgeVerdict, PairwiseLLMJudge
from optimizer.canary_scoring import (
    CanaryScoringAggregator,
    CanaryVerdict,
    LocalCanaryRouter,
    _wilson95,
)


class FakeJudge:
    """Deterministic fake: emits pre-programmed verdicts in order."""

    def __init__(self, verdicts: list[PairwiseJudgeVerdict]) -> None:
        self._verdicts = iter(verdicts)
        self.calls: list[dict[str, Any]] = []

    def judge_case(self, **kw: Any) -> PairwiseJudgeVerdict:
        self.calls.append(kw)
        return next(self._verdicts)


def _record_n(
    router: LocalCanaryRouter,
    n: int,
    *,
    baseline_label: str = "v1",
    candidate_label: str = "v2",
    metadata: dict[str, Any] | None = None,
) -> None:
    for i in range(n):
        router.record_pair(
            input_id=f"in-{i}",
            baseline_label=baseline_label,
            candidate_label=candidate_label,
            baseline_output=f"a-{i}",
            candidate_output=f"b-{i}",
            metadata=metadata if metadata is not None else {},
        )


# ---------------------------------------------------------------------------
# 1. Below min_pairs => None
# ---------------------------------------------------------------------------
def test_aggregator_returns_none_below_min_pairs(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))
    _record_n(router, 5)

    judge = FakeJudge([])
    agg = CanaryScoringAggregator(router=router, judge=judge)

    result = agg.score_recent(
        baseline_label="v1", candidate_label="v2", min_pairs=10
    )
    assert result is None
    assert judge.calls == []


# ---------------------------------------------------------------------------
# 2. Tally wins by label
# ---------------------------------------------------------------------------
def test_aggregator_tallies_wins_by_label(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))
    _record_n(router, 10)

    verdicts = (
        [PairwiseJudgeVerdict(winner="v2", reasoning="", confidence=0.9)] * 6
        + [PairwiseJudgeVerdict(winner="v1", reasoning="", confidence=0.9)] * 3
        + [PairwiseJudgeVerdict(winner="tie", reasoning="", confidence=0.9)]
    )
    judge = FakeJudge(verdicts)
    agg = CanaryScoringAggregator(router=router, judge=judge)

    verdict = agg.score_recent(
        baseline_label="v1", candidate_label="v2", min_pairs=10
    )
    assert verdict is not None
    assert verdict.baseline_label == "v1"
    assert verdict.candidate_label == "v2"
    assert verdict.candidate_wins == 6
    assert verdict.baseline_wins == 3
    assert verdict.ties == 1
    assert verdict.n_pairs == 10
    assert verdict.preferred == "candidate"
    assert verdict.win_rate_candidate == pytest.approx(6 / 9, rel=1e-6)


# ---------------------------------------------------------------------------
# 3. min_confidence drops low-conf verdicts
# ---------------------------------------------------------------------------
def test_aggregator_min_confidence_drops_low_conf(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))
    _record_n(router, 10)

    verdicts = (
        [PairwiseJudgeVerdict(winner="v2", reasoning="", confidence=0.9)] * 5
        + [PairwiseJudgeVerdict(winner="v1", reasoning="", confidence=0.1)] * 5
    )
    judge = FakeJudge(verdicts)
    agg = CanaryScoringAggregator(
        router=router, judge=judge, min_confidence=0.5
    )

    verdict = agg.score_recent(
        baseline_label="v1", candidate_label="v2", min_pairs=10
    )
    assert verdict is not None
    assert verdict.candidate_wins == 5
    assert verdict.baseline_wins == 0
    assert verdict.ties == 0
    assert verdict.n_pairs == 10
    assert verdict.preferred == "candidate"


# ---------------------------------------------------------------------------
# 4. All ties => preferred = "tie", NaN win rate
# ---------------------------------------------------------------------------
def test_aggregator_all_ties_preferred_is_tie(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))
    _record_n(router, 10)

    verdicts = [
        PairwiseJudgeVerdict(winner="tie", reasoning="", confidence=0.9)
    ] * 10
    judge = FakeJudge(verdicts)
    agg = CanaryScoringAggregator(router=router, judge=judge)

    verdict = agg.score_recent(
        baseline_label="v1", candidate_label="v2", min_pairs=10
    )
    assert verdict is not None
    assert verdict.preferred == "tie"
    assert math.isnan(verdict.win_rate_candidate)
    assert verdict.ci95_candidate_winrate == (0.0, 0.0)


# ---------------------------------------------------------------------------
# 5. Wilson CI reasonable
# ---------------------------------------------------------------------------
def test_aggregator_wilson_ci_reasonable(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))
    _record_n(router, 100)

    verdicts = (
        [PairwiseJudgeVerdict(winner="v2", reasoning="", confidence=0.9)] * 60
        + [PairwiseJudgeVerdict(winner="v1", reasoning="", confidence=0.9)] * 40
    )
    judge = FakeJudge(verdicts)
    agg = CanaryScoringAggregator(router=router, judge=judge)

    verdict = agg.score_recent(
        baseline_label="v1", candidate_label="v2", min_pairs=10
    )
    assert verdict is not None
    lo, hi = verdict.ci95_candidate_winrate
    assert isinstance(lo, float) and isinstance(hi, float)
    assert 0.0 <= lo < hi <= 1.0
    assert lo <= 0.6 <= hi
    assert (hi - lo) < 0.25


# ---------------------------------------------------------------------------
# 6. window_s filters out old pairs
# ---------------------------------------------------------------------------
def test_aggregator_respects_window_s(tmp_path, monkeypatch) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))

    import optimizer.canary_scoring as cs

    # 10 old pairs (recorded far in the past)
    monkeypatch.setattr(cs.time, "time", lambda: 1_000_000.0)
    _record_n(router, 10)
    # 10 new pairs (recent)
    monkeypatch.setattr(cs.time, "time", lambda: 2_000_000.0)
    _record_n(router, 10)

    verdicts = [
        PairwiseJudgeVerdict(winner="v2", reasoning="", confidence=0.9)
    ] * 10
    judge = FakeJudge(verdicts)
    agg = CanaryScoringAggregator(router=router, judge=judge)

    verdict = agg.score_recent(
        baseline_label="v1",
        candidate_label="v2",
        min_pairs=5,
        window_s=60.0,
    )
    assert verdict is not None
    assert verdict.n_pairs == 10
    assert len(judge.calls) == 10


# ---------------------------------------------------------------------------
# 7. max_pairs caps judging budget
# ---------------------------------------------------------------------------
def test_aggregator_max_pairs_caps_judging_budget(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))
    _record_n(router, 200)

    verdicts = [
        PairwiseJudgeVerdict(winner="v2", reasoning="", confidence=0.9)
    ] * 50
    judge = FakeJudge(verdicts)
    agg = CanaryScoringAggregator(router=router, judge=judge)

    verdict = agg.score_recent(
        baseline_label="v1",
        candidate_label="v2",
        min_pairs=10,
        max_pairs=50,
    )
    assert verdict is not None
    assert verdict.n_pairs == 50
    assert len(judge.calls) == 50


# ---------------------------------------------------------------------------
# 8. Default judge is heuristic-only PairwiseLLMJudge
# ---------------------------------------------------------------------------
def test_aggregator_default_judge_is_heuristic_only(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))
    agg = CanaryScoringAggregator(router=router)
    # Default judge is an actual PairwiseLLMJudge with no LLM router
    assert isinstance(agg._judge, PairwiseLLMJudge)
    assert agg._judge._router is None


# ---------------------------------------------------------------------------
# 9. Synth TestCase uses metadata.user_message / reference_answer
# ---------------------------------------------------------------------------
def test_aggregator_synth_case_uses_metadata_user_message(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))
    router.record_pair(
        input_id="in-x",
        baseline_label="v1",
        candidate_label="v2",
        baseline_output="a",
        candidate_output="b",
        metadata={"user_message": "hello", "reference_answer": "hi"},
    )

    verdicts = [
        PairwiseJudgeVerdict(winner="v2", reasoning="", confidence=0.9)
    ]
    judge = FakeJudge(verdicts)
    agg = CanaryScoringAggregator(router=router, judge=judge)
    verdict = agg.score_recent(
        baseline_label="v1", candidate_label="v2", min_pairs=1
    )
    assert verdict is not None
    assert len(judge.calls) == 1
    case = judge.calls[0]["case"]
    assert case.user_message == "hello"
    assert case.reference_answer == "hi"


# ---------------------------------------------------------------------------
# 10. Synth TestCase defaults when metadata missing
# ---------------------------------------------------------------------------
def test_aggregator_synth_case_defaults_when_metadata_missing(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))
    router.record_pair(
        input_id="in-x",
        baseline_label="v1",
        candidate_label="v2",
        baseline_output="a",
        candidate_output="b",
        metadata={},
    )

    verdicts = [
        PairwiseJudgeVerdict(winner="v2", reasoning="", confidence=0.9)
    ]
    judge = FakeJudge(verdicts)
    agg = CanaryScoringAggregator(router=router, judge=judge)
    verdict = agg.score_recent(
        baseline_label="v1", candidate_label="v2", min_pairs=1
    )
    assert verdict is not None
    case = judge.calls[0]["case"]
    assert case.user_message == ""
    assert case.reference_answer == ""


# ---------------------------------------------------------------------------
# 11. CanaryVerdict is frozen dataclass
# ---------------------------------------------------------------------------
def test_canary_verdict_dataclass_is_frozen() -> None:
    v = CanaryVerdict(
        baseline_label="v1",
        candidate_label="v2",
        baseline_wins=1,
        candidate_wins=2,
        ties=0,
        n_pairs=3,
        win_rate_candidate=2 / 3,
        preferred="candidate",
        ci95_candidate_winrate=(0.1, 0.9),
        judged_at=123.0,
    )
    assert dataclasses.is_dataclass(v)
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.baseline_label = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 12. Correct labels in judge call
# ---------------------------------------------------------------------------
def test_aggregator_uses_correct_labels_in_judge_call(tmp_path) -> None:
    router = LocalCanaryRouter(db_path=str(tmp_path / "cp.db"))
    _record_n(router, 3, baseline_label="baseA", candidate_label="candB")

    verdicts = [
        PairwiseJudgeVerdict(winner="candB", reasoning="", confidence=0.9)
    ] * 3
    judge = FakeJudge(verdicts)
    agg = CanaryScoringAggregator(router=router, judge=judge)

    verdict = agg.score_recent(
        baseline_label="baseA", candidate_label="candB", min_pairs=1
    )
    assert verdict is not None
    for call in judge.calls:
        assert call["label_a"] == "baseA"
        assert call["label_b"] == "candB"


# ---------------------------------------------------------------------------
# 13. _wilson95 helper edge cases
# ---------------------------------------------------------------------------
def test_wilson95_helper_edge_cases() -> None:
    eps = 1e-9

    # n=0 -> (0, 0)
    assert _wilson95(0, 0) == (0.0, 0.0)

    # wins=0, n=10 -> (0, x) with reasonable upper bound
    lo, hi = _wilson95(0, 10)
    assert lo == pytest.approx(0.0, abs=eps)
    assert 0.0 < hi < 0.5

    # wins=n=10 -> (y, 1) with reasonable lower bound
    lo, hi = _wilson95(10, 10)
    assert hi == pytest.approx(1.0, abs=eps)
    assert 0.5 < lo < 1.0
