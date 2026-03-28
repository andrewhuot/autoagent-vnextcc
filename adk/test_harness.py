"""Test harness for running eval cases against ADK agents.

An eval case is a plain dict with at minimum a ``user_message`` key.
Optional keys:

- ``case_id``: string identifier (auto-generated if absent)
- ``expected_output``: string to compare against actual output
- ``expected_contains``: list of substrings that must appear in the output
- ``session_state``: initial session state dict
- ``max_latency_ms``: latency budget in milliseconds

The harness runs each case through an ``AdkRuntimeAdapter``, computes a
0–1 score, and returns a ``HarnessResult``.  The ``summarize`` method
aggregates a suite of results into a single metrics dict.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .runtime import AdkRuntimeAdapter


@dataclass
class HarnessResult:
    """Result of running a single eval case through the test harness.

    Attributes:
        case_id: Identifier taken from the case dict or auto-generated.
        passed: ``True`` if the case met all pass criteria.
        score: Float in [0, 1] representing how well the case was answered.
        output: The agent's final output string.
        trace_events: Full execution trace as AutoAgent-format event dicts.
        latency_ms: Wall-clock time from request to final response.
        errors: Any errors raised during execution.
    """

    case_id: str
    passed: bool
    score: float
    output: str
    trace_events: list[dict] = field(default_factory=list)
    latency_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


class AdkTestHarness:
    """Runs eval cases against an ``AdkRuntimeAdapter`` and scores results.

    Example::

        runtime = AdkRuntimeAdapter(agent_config)
        harness = AdkTestHarness(runtime)
        results = harness.run_suite([
            {"case_id": "c1", "user_message": "Hello"},
            {"case_id": "c2", "user_message": "What is 2+2?",
             "expected_contains": ["4"]},
        ])
        print(harness.summarize(results))
    """

    def __init__(self, runtime: "AdkRuntimeAdapter") -> None:
        """Initialise the harness.

        Args:
            runtime: The ``AdkRuntimeAdapter`` that will execute each case.
        """
        self._runtime = runtime

    # ------------------------------------------------------------------
    # Case execution
    # ------------------------------------------------------------------

    def run_case(self, case: dict) -> HarnessResult:
        """Run a single eval case and return a scored ``HarnessResult``.

        The scoring logic:

        1. Start with a base score of 1.0 (full credit).
        2. If ``expected_output`` is provided and the output does not match
           exactly (case-insensitive strip), deduct 0.5.
        3. For each string in ``expected_contains`` that is absent from the
           output, deduct ``0.5 / len(expected_contains)``.
        4. If ``max_latency_ms`` is set and the actual latency exceeds it,
           deduct 0.1.
        5. Clamp the final score to [0, 1].

        Args:
            case: Eval case dict.  Required key: ``user_message``.

        Returns:
            A ``HarnessResult`` with ``passed = (score >= 0.5 and no errors)``.
        """
        case_id = str(case.get("case_id", str(uuid.uuid4())))
        user_message: str = case.get("user_message", "")
        session_state: dict | None = case.get("session_state")
        expected_output: str | None = case.get("expected_output")
        expected_contains: list[str] = list(case.get("expected_contains") or [])
        max_latency_ms: float | None = case.get("max_latency_ms")

        result = self._runtime.execute(
            user_message=user_message,
            session_state=session_state,
        )

        score = 1.0
        output = result.output
        lower_output = output.lower()

        # Deduct for exact-match mismatch.
        if expected_output is not None:
            if output.strip().lower() != expected_output.strip().lower():
                score -= 0.5

        # Deduct proportionally for missing substrings.
        if expected_contains:
            deduction_per_miss = 0.5 / len(expected_contains)
            for substring in expected_contains:
                if substring.lower() not in lower_output:
                    score -= deduction_per_miss

        # Deduct for latency overrun.
        if max_latency_ms is not None and result.latency_ms > max_latency_ms:
            score -= 0.1

        score = max(0.0, min(1.0, score))
        passed = score >= 0.5 and not result.errors

        return HarnessResult(
            case_id=case_id,
            passed=passed,
            score=score,
            output=output,
            trace_events=result.trace_events,
            latency_ms=result.latency_ms,
            errors=result.errors,
        )

    def run_suite(self, cases: list[dict]) -> list[HarnessResult]:
        """Run a list of eval cases in order.

        Args:
            cases: List of eval case dicts.

        Returns:
            List of ``HarnessResult`` objects in the same order as *cases*.
        """
        return [self.run_case(case) for case in cases]

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def summarize(self, results: list[HarnessResult]) -> dict[str, Any]:
        """Aggregate a list of results into a metrics summary dict.

        Args:
            results: List of ``HarnessResult`` objects.

        Returns:
            Dict with keys:
            - ``total``: number of cases
            - ``passed``: number of cases where ``passed`` is ``True``
            - ``failed``: number of cases where ``passed`` is ``False``
            - ``pass_rate``: fraction of passing cases (0–1)
            - ``avg_score``: mean score across all cases
            - ``avg_latency_ms``: mean latency in milliseconds
            - ``error_count``: total number of errors across all cases
            - ``case_ids_failed``: list of case IDs that did not pass
        """
        if not results:
            return {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "pass_rate": 0.0,
                "avg_score": 0.0,
                "avg_latency_ms": 0.0,
                "error_count": 0,
                "case_ids_failed": [],
            }

        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        pass_rate = passed / total
        avg_score = sum(r.score for r in results) / total
        avg_latency = sum(r.latency_ms for r in results) / total
        error_count = sum(len(r.errors) for r in results)
        failed_ids = [r.case_id for r in results if not r.passed]

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(pass_rate, 4),
            "avg_score": round(avg_score, 4),
            "avg_latency_ms": round(avg_latency, 2),
            "error_count": error_count,
            "case_ids_failed": failed_ids,
        }
