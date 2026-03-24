"""Deterministic judges — regex, state comparison, and invariant checks.

All verdicts have confidence=1.0 since these are exact, deterministic checks.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from core.types import JudgeVerdict


class DeterministicJudge:
    """Deterministic evaluation via regex, state diff, and invariant functions."""

    JUDGE_ID = "deterministic"

    def check_regex(self, pattern: str, text: str) -> JudgeVerdict:
        """Check whether *pattern* matches anywhere in *text*.

        Returns a passing verdict with matched spans as evidence, or a
        failing verdict listing the pattern that was not found.
        """
        try:
            matches = list(re.finditer(pattern, text))
        except re.error as exc:
            return JudgeVerdict(
                score=0.0,
                passed=False,
                judge_id=self.JUDGE_ID,
                failure_reasons=[f"Invalid regex pattern: {exc}"],
                confidence=1.0,
                metadata={"check": "regex", "pattern": pattern},
            )

        if matches:
            evidence = [m.group() for m in matches]
            return JudgeVerdict(
                score=1.0,
                passed=True,
                judge_id=self.JUDGE_ID,
                evidence_spans=evidence,
                confidence=1.0,
                metadata={"check": "regex", "pattern": pattern, "match_count": len(matches)},
            )

        return JudgeVerdict(
            score=0.0,
            passed=False,
            judge_id=self.JUDGE_ID,
            failure_reasons=[f"Pattern not found: {pattern}"],
            confidence=1.0,
            metadata={"check": "regex", "pattern": pattern},
        )

    def check_state(
        self, expected_state: dict[str, Any], actual_state: dict[str, Any]
    ) -> JudgeVerdict:
        """Compare key-value pairs between expected and actual state dicts.

        Every key in *expected_state* must exist in *actual_state* with
        an equal value.  Extra keys in actual are ignored.
        """
        failures: list[str] = []
        evidence: list[str] = []

        for key, expected_val in expected_state.items():
            if key not in actual_state:
                failures.append(f"Missing key: {key}")
            elif actual_state[key] != expected_val:
                failures.append(
                    f"Key '{key}': expected {expected_val!r}, got {actual_state[key]!r}"
                )
            else:
                evidence.append(f"{key}={expected_val!r}")

        total = len(expected_state) or 1
        matched = len(evidence)
        score = matched / total

        return JudgeVerdict(
            score=score,
            passed=len(failures) == 0,
            judge_id=self.JUDGE_ID,
            evidence_spans=evidence,
            failure_reasons=failures,
            confidence=1.0,
            metadata={"check": "state", "total_keys": total, "matched_keys": matched},
        )

    def check_invariant(
        self, invariant_fn: Callable[..., bool], context: dict[str, Any]
    ) -> JudgeVerdict:
        """Run a callable invariant checker against the given context.

        The callable must accept a single dict argument and return a bool.
        Exceptions are caught and treated as failures.
        """
        try:
            result = invariant_fn(context)
        except Exception as exc:
            return JudgeVerdict(
                score=0.0,
                passed=False,
                judge_id=self.JUDGE_ID,
                failure_reasons=[f"Invariant raised exception: {exc}"],
                confidence=1.0,
                metadata={"check": "invariant"},
            )

        passed = bool(result)
        return JudgeVerdict(
            score=1.0 if passed else 0.0,
            passed=passed,
            judge_id=self.JUDGE_ID,
            evidence_spans=["invariant_passed"] if passed else [],
            failure_reasons=[] if passed else ["Invariant check returned False"],
            confidence=1.0,
            metadata={"check": "invariant"},
        )
