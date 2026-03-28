"""Judge governance framework — benchmark sets, accuracy reporting, and drift detection.

Provides the infrastructure to measure judge quality over time: create
benchmark sets with human-scored ground truth, evaluate individual judges
against those benchmarks, track accuracy history, and flag when a judge
has drifted beyond an acceptable threshold.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class JudgeBenchmarkSet:
    """A named collection of ground-truth evaluation examples.

    Each entry pairs an input/output pair with a human-assigned score and
    the judge ID that was evaluated on that entry.

    Attributes:
        benchmark_id: Unique identifier for this benchmark set.
        name: Human-readable name (e.g. "safety_v1").
        entries: List of dicts, each with keys ``input``, ``human_score``,
            and ``judge_id``.
        created_at: ISO-8601 UTC timestamp of creation.
    """

    benchmark_id: str
    name: str
    entries: list[dict] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe plain dict."""
        return {
            "benchmark_id": self.benchmark_id,
            "name": self.name,
            "entries": self.entries,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JudgeBenchmarkSet:
        """Deserialise from a plain dict."""
        return cls(
            benchmark_id=data["benchmark_id"],
            name=data["name"],
            entries=data.get("entries", []),
            created_at=data.get("created_at", ""),
        )


@dataclass
class JudgeAccuracyReport:
    """Accuracy report for a single judge evaluated on a benchmark set.

    Attributes:
        judge_id: Identifier of the judge being evaluated.
        benchmark_id: Identifier of the benchmark set used.
        accuracy: Fraction of entries where judge score is within tolerance.
        correlation: Pearson-like correlation between judge and human scores.
        bias: Mean signed error (judge_score - human_score); positive = over-scoring.
        sample_count: Number of entries evaluated.
        evaluated_at: ISO-8601 UTC timestamp of evaluation.
    """

    judge_id: str
    benchmark_id: str
    accuracy: float
    correlation: float
    bias: float
    sample_count: int
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe plain dict."""
        return {
            "judge_id": self.judge_id,
            "benchmark_id": self.benchmark_id,
            "accuracy": self.accuracy,
            "correlation": self.correlation,
            "bias": self.bias,
            "sample_count": self.sample_count,
            "evaluated_at": self.evaluated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JudgeAccuracyReport:
        """Deserialise from a plain dict."""
        return cls(
            judge_id=data["judge_id"],
            benchmark_id=data["benchmark_id"],
            accuracy=data["accuracy"],
            correlation=data["correlation"],
            bias=data["bias"],
            sample_count=data["sample_count"],
            evaluated_at=data.get("evaluated_at", ""),
        )


class JudgeGovernanceEngine:
    """Governance engine for tracking and auditing judge quality.

    Persists benchmark sets and accuracy reports in SQLite so quality
    trends can be observed across deployments.

    Args:
        db_path: Path to the SQLite database file.  Parent directories are
            created automatically.
    """

    _AGREEMENT_TOLERANCE = 0.1  # judge within ±0.1 of human = "agree"

    def __init__(self, db_path: str = ".autoagent/judge_governance.db") -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_tables(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS benchmarks (
                    benchmark_id  TEXT PRIMARY KEY,
                    name          TEXT NOT NULL,
                    entries       TEXT NOT NULL DEFAULT '[]',
                    created_at    TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS accuracy_reports (
                    rowid         INTEGER PRIMARY KEY AUTOINCREMENT,
                    judge_id      TEXT NOT NULL,
                    benchmark_id  TEXT NOT NULL,
                    accuracy      REAL NOT NULL,
                    correlation   REAL NOT NULL,
                    bias          REAL NOT NULL,
                    sample_count  INTEGER NOT NULL,
                    evaluated_at  TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Benchmarks
    # ------------------------------------------------------------------

    def create_benchmark(
        self, name: str, entries: list[dict]
    ) -> JudgeBenchmarkSet:
        """Create and persist a new benchmark set.

        Args:
            name: Human-readable name for the benchmark.
            entries: Ground-truth entries, each a dict with keys
                ``input``, ``human_score``, and ``judge_id``.

        Returns:
            The newly created :class:`JudgeBenchmarkSet`.
        """
        benchmark = JudgeBenchmarkSet(
            benchmark_id=str(uuid.uuid4()),
            name=name,
            entries=list(entries),
        )
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO benchmarks (benchmark_id, name, entries, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    benchmark.benchmark_id,
                    benchmark.name,
                    json.dumps(benchmark.entries, default=str),
                    benchmark.created_at,
                ),
            )
            conn.commit()
        return benchmark

    def _get_benchmark(self, benchmark_id: str) -> JudgeBenchmarkSet | None:
        """Load a benchmark set from the database."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT benchmark_id, name, entries, created_at FROM benchmarks WHERE benchmark_id = ?",
                (benchmark_id,),
            ).fetchone()
        if row is None:
            return None
        return JudgeBenchmarkSet(
            benchmark_id=row[0],
            name=row[1],
            entries=json.loads(row[2]),
            created_at=row[3],
        )

    # ------------------------------------------------------------------
    # Accuracy evaluation
    # ------------------------------------------------------------------

    def evaluate_judge_accuracy(
        self, judge_id: str, benchmark_id: str
    ) -> JudgeAccuracyReport:
        """Evaluate a judge against a benchmark set and persist the result.

        Filters benchmark entries to those matching *judge_id*, then
        computes accuracy (agreement rate), Pearson correlation, and mean
        signed bias.

        Args:
            judge_id: The judge to evaluate.
            benchmark_id: The benchmark set to evaluate against.

        Returns:
            A :class:`JudgeAccuracyReport` with computed metrics.

        Raises:
            ValueError: If the benchmark is not found or has no matching entries.
        """
        benchmark = self._get_benchmark(benchmark_id)
        if benchmark is None:
            raise ValueError(f"Benchmark not found: {benchmark_id}")

        # Filter entries to those for this judge (or all if no judge_id in entry)
        relevant = [
            e for e in benchmark.entries
            if e.get("judge_id", judge_id) == judge_id
        ]
        if not relevant:
            # Fall back to all entries when none are tagged for this judge
            relevant = benchmark.entries

        if not relevant:
            raise ValueError(
                f"Benchmark {benchmark_id} has no entries for judge {judge_id}"
            )

        judge_scores = [float(e.get("judge_score", e.get("score", 0.0))) for e in relevant]
        human_scores = [float(e["human_score"]) for e in relevant]
        n = len(relevant)

        # Accuracy: fraction where |judge - human| <= tolerance
        agreed = sum(
            1 for js, hs in zip(judge_scores, human_scores)
            if abs(js - hs) <= self._AGREEMENT_TOLERANCE
        )
        accuracy = agreed / n

        # Pearson correlation (gracefully handle zero-variance)
        correlation = self._pearson(judge_scores, human_scores)

        # Bias: mean signed error
        bias = sum(js - hs for js, hs in zip(judge_scores, human_scores)) / n

        report = JudgeAccuracyReport(
            judge_id=judge_id,
            benchmark_id=benchmark_id,
            accuracy=round(accuracy, 6),
            correlation=round(correlation, 6),
            bias=round(bias, 6),
            sample_count=n,
        )
        self._save_report(report)
        return report

    def _save_report(self, report: JudgeAccuracyReport) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO accuracy_reports
                    (judge_id, benchmark_id, accuracy, correlation, bias, sample_count, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.judge_id,
                    report.benchmark_id,
                    report.accuracy,
                    report.correlation,
                    report.bias,
                    report.sample_count,
                    report.evaluated_at,
                ),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # History and drift
    # ------------------------------------------------------------------

    def get_accuracy_history(self, judge_id: str) -> list[JudgeAccuracyReport]:
        """Return all accuracy reports for *judge_id*, oldest first.

        Args:
            judge_id: The judge whose history to retrieve.

        Returns:
            List of :class:`JudgeAccuracyReport`, ordered by ``evaluated_at``.
        """
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT judge_id, benchmark_id, accuracy, correlation, bias, sample_count, evaluated_at
                FROM accuracy_reports
                WHERE judge_id = ?
                ORDER BY rowid ASC
                """,
                (judge_id,),
            ).fetchall()
        return [
            JudgeAccuracyReport(
                judge_id=row[0],
                benchmark_id=row[1],
                accuracy=row[2],
                correlation=row[3],
                bias=row[4],
                sample_count=row[5],
                evaluated_at=row[6],
            )
            for row in rows
        ]

    def flag_drift(self, judge_id: str, threshold: float = 0.1) -> bool:
        """Return True if the judge's accuracy has dropped by more than *threshold*.

        Compares the most recent accuracy report to the baseline (first ever
        report for this judge).  Returns False when there are fewer than two
        reports (insufficient data).

        Args:
            judge_id: The judge to check.
            threshold: Maximum tolerated drop in accuracy (default 0.1 = 10 pp).

        Returns:
            True if drift exceeds threshold, False otherwise.
        """
        history = self.get_accuracy_history(judge_id)
        if len(history) < 2:
            return False
        baseline_accuracy = history[0].accuracy
        latest_accuracy = history[-1].accuracy
        return (baseline_accuracy - latest_accuracy) > threshold

    # ------------------------------------------------------------------
    # Statistics helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pearson(xs: list[float], ys: list[float]) -> float:
        """Compute Pearson correlation coefficient between xs and ys."""
        n = len(xs)
        if n < 2:
            return 0.0
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        den_x = (sum((x - mean_x) ** 2 for x in xs)) ** 0.5
        den_y = (sum((y - mean_y) ** 2 for y in ys)) ** 0.5
        if den_x == 0 or den_y == 0:
            return 0.0
        return num / (den_x * den_y)
