"""Canary scoring primitives: paired (baseline, candidate) observations.

Provides the deployment-platform-agnostic interface used to record
``(baseline_output, candidate_output)`` pairs on the SAME input during
a canary rollout, plus a SQLite-backed reference implementation.

The ``CanaryRouter`` Protocol is the seam: a Kubernetes, Cloud Run, or
Lambda adapter can implement it without depending on this module's
storage. ``LocalCanaryRouter`` is the local-mode reference impl and the
fixture used by tests and B.5's scoring aggregator.

This module stands alone: stdlib + ``typing`` + ``dataclasses`` only.
B.5's aggregator imports from here, not the other way around.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from evals.judges.pairwise_judge import PairwiseLLMJudge


DEFAULT_DB_PATH = ".agentlab/canary_pairs.db"


@dataclass(frozen=True)
class CanaryPair:
    """One paired observation: baseline + candidate ran on the same input."""

    pair_id: str
    input_id: str
    baseline_label: str
    candidate_label: str
    baseline_output: str
    candidate_output: str
    metadata: dict[str, Any] = field(default_factory=dict)
    recorded_at: float = 0.0


@runtime_checkable
class CanaryRouter(Protocol):
    """Deploy-platform-specific adapter for paired canary observations.

    Implementations record one ``(baseline_output, candidate_output)`` pair
    per call, keyed by a logical ``input_id`` so the scoring aggregator can
    match them up later.
    """

    def record_pair(
        self,
        *,
        input_id: str,
        baseline_label: str,
        candidate_label: str,
        baseline_output: str,
        candidate_output: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store one pair; return the ``pair_id``."""
        ...


class LocalCanaryRouter:
    """SQLite-backed :class:`CanaryRouter`.

    Reference implementation suitable for tests and local-mode canary
    deploys. Persists every pair so B.5's aggregator can read deterministic
    history without coupling to any specific deployment platform.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS canary_pairs (
                    pair_id TEXT PRIMARY KEY,
                    input_id TEXT NOT NULL,
                    baseline_label TEXT NOT NULL,
                    candidate_label TEXT NOT NULL,
                    baseline_output TEXT NOT NULL,
                    candidate_output TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    recorded_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cp_labels_recorded "
                "ON canary_pairs(baseline_label, candidate_label, recorded_at)"
            )
            conn.commit()

    def record_pair(
        self,
        *,
        input_id: str,
        baseline_label: str,
        candidate_label: str,
        baseline_output: str,
        candidate_output: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist one paired observation; return the new ``pair_id``."""
        pair_id = uuid.uuid4().hex
        metadata_json = json.dumps(metadata or {}, default=str, sort_keys=True)
        recorded_at = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO canary_pairs("
                "pair_id, input_id, baseline_label, candidate_label, "
                "baseline_output, candidate_output, metadata_json, "
                "recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pair_id,
                    input_id,
                    baseline_label,
                    candidate_label,
                    baseline_output,
                    candidate_output,
                    metadata_json,
                    recorded_at,
                ),
            )
            conn.commit()
        return pair_id

    def list_recent(
        self,
        *,
        baseline_label: str,
        candidate_label: str,
        window_s: float | None = None,
        limit: int = 1000,
    ) -> list[CanaryPair]:
        """Return recent pairs for ``(baseline_label, candidate_label)``.

        Ordered most-recent first. When ``window_s`` is set, restrict to
        rows with ``recorded_at > time.time() - window_s``.
        """
        params: list[Any] = [baseline_label, candidate_label]
        sql = (
            "SELECT pair_id, input_id, baseline_label, candidate_label, "
            "baseline_output, candidate_output, metadata_json, recorded_at "
            "FROM canary_pairs "
            "WHERE baseline_label = ? AND candidate_label = ?"
        )
        if window_s is not None:
            sql += " AND recorded_at > ?"
            params.append(time.time() - window_s)
        sql += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            CanaryPair(
                pair_id=row[0],
                input_id=row[1],
                baseline_label=row[2],
                candidate_label=row[3],
                baseline_output=row[4],
                candidate_output=row[5],
                metadata=json.loads(row[6]),
                recorded_at=row[7],
            )
            for row in rows
        ]

    def count(
        self,
        *,
        baseline_label: str,
        candidate_label: str,
        window_s: float | None = None,
    ) -> int:
        """Count pairs for ``(baseline_label, candidate_label)``.

        When ``window_s`` is set, restrict to rows with
        ``recorded_at > time.time() - window_s``.
        """
        params: list[Any] = [baseline_label, candidate_label]
        sql = (
            "SELECT COUNT(*) FROM canary_pairs "
            "WHERE baseline_label = ? AND candidate_label = ?"
        )
        if window_s is not None:
            sql += " AND recorded_at > ?"
            params.append(time.time() - window_s)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row[0])


# ---------------------------------------------------------------------------
# B.5 — CanaryScoringAggregator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CanaryVerdict:
    """Rolled-up verdict across a batch of judged canary pairs.

    ``win_rate_candidate`` is ``candidate_wins / (candidate_wins +
    baseline_wins)`` — ties are excluded from the denominator. When both
    are zero the field is ``float('nan')``.

    ``ci95_candidate_winrate`` is a 95% Wilson score interval for the
    same numerator/denominator; ``(0.0, 0.0)`` when the denominator is
    zero (all ties or no pairs survived).

    ``n_pairs`` is the number of pairs fetched from the router, NOT the
    number that influenced the verdict — pairs whose judge confidence
    fell below ``min_confidence`` still count toward ``n_pairs`` but are
    excluded from wins/losses/ties.
    """

    baseline_label: str
    candidate_label: str
    baseline_wins: int
    candidate_wins: int
    ties: int
    n_pairs: int
    win_rate_candidate: float
    preferred: str  # "baseline" | "candidate" | "tie"
    ci95_candidate_winrate: tuple[float, float]
    judged_at: float


def _wilson95(wins: int, n: int) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion.

    Returns ``(0.0, 0.0)`` when ``n == 0``. Clamped to ``[0, 1]``.
    Inline-implemented so this module stays scipy-free.
    """
    if n <= 0:
        return (0.0, 0.0)
    z = 1.96
    phat = wins / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return (lo, hi)


class CanaryScoringAggregator:
    """Read recent pairs from a :class:`CanaryRouter` and judge them.

    The aggregator asks a pluggable :class:`PairwiseLLMJudge` to compare
    each ``(baseline_output, candidate_output)`` pair and tallies wins,
    losses, and ties. It returns a rolled-up :class:`CanaryVerdict` with
    a Wilson-95 confidence interval on the candidate's head-to-head win
    rate (ties excluded from the denominator).

    The judge interface expects a ``TestCase`` and two ``EvalResult``
    arguments per pair. Canary pairs carry neither natively, so the
    aggregator synthesizes both from the pair's ``metadata`` — the judge
    only really consumes ``user_message`` / ``reference_answer`` on the
    LLM path, and ``passed`` / ``quality_score`` on the heuristic
    fallback, so minimal defaults suffice.

    When no judge is injected, the aggregator constructs a
    ``PairwiseLLMJudge()`` with no LLM router, which forces the
    heuristic code path (no LLM cost, deterministic).
    """

    def __init__(
        self,
        router: CanaryRouter,
        judge: "PairwiseLLMJudge | None" = None,
        min_confidence: float = 0.0,
    ) -> None:
        self._router = router
        if judge is None:
            # Local import to keep module-level deps free of evals/.
            from evals.judges.pairwise_judge import PairwiseLLMJudge

            judge = PairwiseLLMJudge()
        self._judge = judge
        self._min_confidence = float(min_confidence)

    def score_recent(
        self,
        *,
        baseline_label: str,
        candidate_label: str,
        min_pairs: int = 10,
        window_s: float | None = None,
        max_pairs: int = 500,
    ) -> CanaryVerdict | None:
        """Fetch and judge recent pairs; return a rolled-up verdict.

        Returns ``None`` when fewer than ``min_pairs`` pairs are
        available so callers can surface a "pending" message. The
        judging budget is capped at ``max_pairs`` pairs.
        """
        pairs = self._router.list_recent(
            baseline_label=baseline_label,
            candidate_label=candidate_label,
            window_s=window_s,
            limit=max_pairs,
        )
        if len(pairs) < min_pairs:
            return None

        baseline_wins = 0
        candidate_wins = 0
        ties = 0

        for pair in pairs:
            case = _synth_case(pair)
            eval_a = _synth_eval(case.id)
            eval_b = _synth_eval(case.id)
            output_a = {"response": pair.baseline_output}
            output_b = {"response": pair.candidate_output}

            verdict = self._judge.judge_case(
                case=case,
                label_a=baseline_label,
                label_b=candidate_label,
                output_a=output_a,
                output_b=output_b,
                eval_a=eval_a,
                eval_b=eval_b,
            )

            if verdict.confidence < self._min_confidence:
                continue

            if verdict.winner == candidate_label:
                candidate_wins += 1
            elif verdict.winner == baseline_label:
                baseline_wins += 1
            elif verdict.winner == "tie":
                ties += 1
            # Unknown winner labels are silently dropped.

        denom = candidate_wins + baseline_wins
        if denom > 0:
            win_rate = candidate_wins / denom
            ci = _wilson95(candidate_wins, denom)
        else:
            win_rate = float("nan")
            ci = (0.0, 0.0)

        if candidate_wins > baseline_wins:
            preferred = "candidate"
        elif baseline_wins > candidate_wins:
            preferred = "baseline"
        else:
            preferred = "tie"

        return CanaryVerdict(
            baseline_label=baseline_label,
            candidate_label=candidate_label,
            baseline_wins=baseline_wins,
            candidate_wins=candidate_wins,
            ties=ties,
            n_pairs=len(pairs),
            win_rate_candidate=win_rate,
            preferred=preferred,
            ci95_candidate_winrate=ci,
            judged_at=time.time(),
        )


def _synth_case(pair: CanaryPair) -> Any:
    """Synthesize a minimal ``TestCase`` from a canary pair.

    Local import: keeps ``optimizer/canary_scoring``'s module-level
    import graph free of ``evals/``.
    """
    from evals.runner import TestCase

    return TestCase(
        id=pair.pair_id,
        category="canary",
        user_message=str(pair.metadata.get("user_message", "")),
        expected_specialist="",
        expected_behavior="answer",
        reference_answer=str(pair.metadata.get("reference_answer", "")),
    )


def _synth_eval(case_id: str) -> Any:
    """Synthesize a minimal ``EvalResult`` for the pairwise judge."""
    from evals.scorer import EvalResult

    return EvalResult(
        case_id=case_id,
        category="canary",
        passed=True,
        quality_score=0.5,
        safety_passed=True,
        latency_ms=0.0,
        token_count=0,
    )
