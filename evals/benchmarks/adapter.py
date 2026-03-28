"""Base benchmark adapter and result types for AutoAgent standard benchmarks."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class BenchmarkResult:
    """Result of running a benchmark suite.

    Attributes:
        benchmark_name: Name of the benchmark (e.g. "tau2", "webarena").
        scores: Mapping of metric name to score value.
        cases_run: Total number of cases executed.
        cases_passed: Number of cases that passed / met the success threshold.
        duration_ms: Wall-clock time spent running all cases, in milliseconds.
        metadata: Arbitrary extra information (e.g. version, config snapshot).
    """

    benchmark_name: str
    scores: dict[str, float] = field(default_factory=dict)
    cases_run: int = 0
    cases_passed: int = 0
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "benchmark_name": self.benchmark_name,
            "scores": self.scores,
            "cases_run": self.cases_run,
            "cases_passed": self.cases_passed,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkResult":
        """Deserialise from a plain dictionary."""
        return cls(
            benchmark_name=data.get("benchmark_name", ""),
            scores=data.get("scores", {}),
            cases_run=data.get("cases_run", 0),
            cases_passed=data.get("cases_passed", 0),
            duration_ms=data.get("duration_ms", 0.0),
            metadata=data.get("metadata", {}),
        )

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def pass_rate(self) -> float:
        """Fraction of cases that passed (0.0–1.0)."""
        if self.cases_run == 0:
            return 0.0
        return self.cases_passed / self.cases_run


class BenchmarkAdapter(ABC):
    """Abstract base class for benchmark adapters.

    Subclasses implement :meth:`load_dataset` and :meth:`score`; the
    :meth:`run_all` orchestration method is provided here.
    """

    #: Human-readable benchmark name
    name: str = ""
    #: Short description of what the benchmark tests
    description: str = ""
    #: Benchmark version string
    version: str = "1.0.0"

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def load_dataset(self) -> list[dict]:
        """Load and return the list of benchmark cases.

        Returns:
            List of case dicts, each containing at minimum an ``id`` field.
        """

    @abstractmethod
    def run_case(self, agent_fn: Callable, case: dict) -> dict:
        """Run a single benchmark case.

        Args:
            agent_fn: Callable that accepts a case dict and returns an output
                dict (or string).
            case: A single case dict from :meth:`load_dataset`.

        Returns:
            Result dict containing at minimum ``case_id``, ``passed``, and
            ``output``.
        """

    @abstractmethod
    def score(self, results: list[dict]) -> dict:
        """Compute aggregate scores from a list of case results.

        Args:
            results: List of result dicts produced by :meth:`run_case`.

        Returns:
            Dictionary of metric name -> float score.
        """

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def run_all(
        self,
        agent_fn: Callable,
        cases: list[dict] | None = None,
    ) -> dict:
        """Run all (or a subset of) benchmark cases and return a result dict.

        Args:
            agent_fn: Callable used to run each case.
            cases: Optional subset of cases to run. Defaults to all cases
                returned by :meth:`load_dataset`.

        Returns:
            Dictionary with keys ``benchmark_name``, ``scores``,
            ``cases_run``, ``cases_passed``, ``duration_ms``, and ``results``
            (the per-case result list).
        """
        if cases is None:
            cases = self.load_dataset()

        results: list[dict] = []
        t0 = time.perf_counter()

        for case in cases:
            try:
                result = self.run_case(agent_fn, case)
            except Exception as exc:  # noqa: BLE001
                result = {
                    "case_id": case.get("id", ""),
                    "passed": False,
                    "output": None,
                    "error": str(exc),
                }
            results.append(result)

        duration_ms = (time.perf_counter() - t0) * 1000.0
        scores = self.score(results)
        cases_passed = sum(1 for r in results if r.get("passed", False))

        return {
            "benchmark_name": self.name,
            "scores": scores,
            "cases_run": len(results),
            "cases_passed": cases_passed,
            "duration_ms": duration_ms,
            "results": results,
        }
