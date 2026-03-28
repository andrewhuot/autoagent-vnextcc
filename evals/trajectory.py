"""Trajectory evaluation — was the agent process correct?

Evaluates *how* the agent reached its answer, not just whether the final
answer was correct.  Three scoring modes are supported:

- exact_match   : actual steps must be identical to expected steps in order
- in_order_match: expected steps must appear in order (extra steps allowed)
- any_order_match: expected steps must all appear, order irrelevant
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TrajectoryStep:
    """A single expected or actual step in an agent trajectory.

    Args:
        step_index: Zero-based position in the trajectory.
        action: Human-readable action label, e.g. ``"search_knowledge_base"``.
        tool_name: Tool invoked at this step, or ``None`` for reasoning steps.
        parameters: Key/value parameters passed to the tool or action.
        expected: Whether this step was *expected* (True) or just observed.
    """

    step_index: int
    action: str
    tool_name: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    expected: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "action": self.action,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "expected": self.expected,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrajectoryStep":
        return cls(
            step_index=int(d["step_index"]),
            action=str(d["action"]),
            tool_name=d.get("tool_name"),
            parameters=d.get("parameters") or {},
            expected=bool(d.get("expected", True)),
        )


@dataclass
class TrajectoryExpectation:
    """Declarative specification of what the agent's trajectory should look like.

    Args:
        steps: Ordered list of expected trajectory steps.
        scoring_mode: One of ``"exact_match"``, ``"in_order_match"``, or
            ``"any_order_match"``.
    """

    steps: list[TrajectoryStep] = field(default_factory=list)
    scoring_mode: str = "in_order_match"

    _VALID_MODES = frozenset({"exact_match", "in_order_match", "any_order_match"})

    def __post_init__(self) -> None:
        if self.scoring_mode not in self._VALID_MODES:
            raise ValueError(
                f"scoring_mode must be one of {sorted(self._VALID_MODES)}, "
                f"got {self.scoring_mode!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "scoring_mode": self.scoring_mode,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrajectoryExpectation":
        return cls(
            steps=[TrajectoryStep.from_dict(s) for s in d.get("steps", [])],
            scoring_mode=str(d.get("scoring_mode", "in_order_match")),
        )


@dataclass
class TrajectoryResult:
    """Result of evaluating an actual trajectory against an expectation.

    Args:
        score: Fraction of expected steps that were matched (0.0 – 1.0).
        matched_steps: Number of expected steps that matched.
        total_expected: Total number of expected steps.
        total_actual: Total number of actual steps observed.
        mismatches: List of mismatch detail dicts for debugging.
        scoring_mode: The mode used for this evaluation.
    """

    score: float
    matched_steps: int
    total_expected: int
    total_actual: int
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    scoring_mode: str = "in_order_match"

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "matched_steps": self.matched_steps,
            "total_expected": self.total_expected,
            "total_actual": self.total_actual,
            "mismatches": self.mismatches,
            "scoring_mode": self.scoring_mode,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrajectoryResult":
        return cls(
            score=float(d["score"]),
            matched_steps=int(d["matched_steps"]),
            total_expected=int(d["total_expected"]),
            total_actual=int(d["total_actual"]),
            mismatches=list(d.get("mismatches") or []),
            scoring_mode=str(d.get("scoring_mode", "in_order_match")),
        )


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class TrajectoryEvaluator:
    """Evaluates an actual agent trajectory against a declared expectation.

    Usage::

        evaluator = TrajectoryEvaluator()
        result = evaluator.evaluate(actual_steps, expectation)
        print(result.score)   # 0.0 – 1.0
    """

    def evaluate(
        self,
        actual_steps: list[dict[str, Any]],
        expected: TrajectoryExpectation,
    ) -> TrajectoryResult:
        """Evaluate actual steps against the expectation.

        Args:
            actual_steps: Raw dicts from the agent run (keys: ``action``,
                ``tool_name``, ``parameters``, etc.).
            expected: The declared trajectory expectation.

        Returns:
            A :class:`TrajectoryResult` with score and mismatch details.
        """
        if expected.scoring_mode == "exact_match":
            return self._exact_match(actual_steps, expected)
        if expected.scoring_mode == "in_order_match":
            return self._in_order_match(actual_steps, expected)
        return self._any_order_match(actual_steps, expected)

    # ------------------------------------------------------------------
    # Scoring modes
    # ------------------------------------------------------------------

    def _exact_match(
        self,
        actual: list[dict[str, Any]],
        expected: TrajectoryExpectation,
    ) -> TrajectoryResult:
        """Every actual step must match the corresponding expected step exactly."""
        exp_steps = expected.steps
        total_expected = len(exp_steps)
        total_actual = len(actual)
        mismatches: list[dict[str, Any]] = []
        matched = 0

        for i, exp in enumerate(exp_steps):
            if i >= total_actual:
                mismatches.append({
                    "type": "missing_step",
                    "expected_index": i,
                    "expected_action": exp.action,
                    "expected_tool": exp.tool_name,
                })
                continue

            act = actual[i]
            if self._steps_match(act, exp):
                matched += 1
            else:
                mismatches.append({
                    "type": "step_mismatch",
                    "index": i,
                    "expected_action": exp.action,
                    "expected_tool": exp.tool_name,
                    "actual_action": act.get("action", ""),
                    "actual_tool": act.get("tool_name"),
                })

        # Any extra actual steps are noted as unexpected
        for j in range(total_expected, total_actual):
            mismatches.append({
                "type": "unexpected_step",
                "actual_index": j,
                "actual_action": actual[j].get("action", ""),
                "actual_tool": actual[j].get("tool_name"),
            })

        score = matched / total_expected if total_expected > 0 else 1.0
        return TrajectoryResult(
            score=round(score, 4),
            matched_steps=matched,
            total_expected=total_expected,
            total_actual=total_actual,
            mismatches=mismatches,
            scoring_mode="exact_match",
        )

    def _in_order_match(
        self,
        actual: list[dict[str, Any]],
        expected: TrajectoryExpectation,
    ) -> TrajectoryResult:
        """Expected steps must appear in order within actual; extra steps are allowed."""
        exp_steps = expected.steps
        total_expected = len(exp_steps)
        total_actual = len(actual)
        mismatches: list[dict[str, Any]] = []
        matched = 0

        exp_idx = 0  # pointer into expected steps
        for act_idx, act in enumerate(actual):
            if exp_idx >= total_expected:
                break
            exp = exp_steps[exp_idx]
            if self._steps_match(act, exp):
                matched += 1
                exp_idx += 1

        # Any remaining expected steps were not matched
        for i in range(exp_idx, total_expected):
            exp = exp_steps[i]
            mismatches.append({
                "type": "missing_step",
                "expected_index": i,
                "expected_action": exp.action,
                "expected_tool": exp.tool_name,
            })

        score = matched / total_expected if total_expected > 0 else 1.0
        return TrajectoryResult(
            score=round(score, 4),
            matched_steps=matched,
            total_expected=total_expected,
            total_actual=total_actual,
            mismatches=mismatches,
            scoring_mode="in_order_match",
        )

    def _any_order_match(
        self,
        actual: list[dict[str, Any]],
        expected: TrajectoryExpectation,
    ) -> TrajectoryResult:
        """All expected steps must appear somewhere in actual; order irrelevant."""
        exp_steps = expected.steps
        total_expected = len(exp_steps)
        total_actual = len(actual)
        mismatches: list[dict[str, Any]] = []
        matched = 0

        remaining_actual = list(actual)  # copy so we can consume matches
        for exp in exp_steps:
            found = False
            for j, act in enumerate(remaining_actual):
                if self._steps_match(act, exp):
                    matched += 1
                    remaining_actual.pop(j)
                    found = True
                    break
            if not found:
                mismatches.append({
                    "type": "missing_step",
                    "expected_action": exp.action,
                    "expected_tool": exp.tool_name,
                })

        score = matched / total_expected if total_expected > 0 else 1.0
        return TrajectoryResult(
            score=round(score, 4),
            matched_steps=matched,
            total_expected=total_expected,
            total_actual=total_actual,
            mismatches=mismatches,
            scoring_mode="any_order_match",
        )

    # ------------------------------------------------------------------
    # Utility evaluators
    # ------------------------------------------------------------------

    def evaluate_tool_selection(
        self,
        actual_tools: list[str],
        expected_tools: list[str],
    ) -> float:
        """Score how well actual tool selection matches expected tools.

        Returns the Jaccard similarity (intersection / union) of the two
        tool name sets.  Returns 1.0 when both lists are empty.
        """
        if not expected_tools and not actual_tools:
            return 1.0
        expected_set = set(expected_tools)
        actual_set = set(actual_tools)
        intersection = len(expected_set & actual_set)
        union = len(expected_set | actual_set)
        if union == 0:
            return 1.0
        return round(intersection / union, 4)

    def evaluate_parameter_correctness(
        self,
        actual_params: dict[str, Any],
        expected_params: dict[str, Any],
    ) -> float:
        """Score how closely actual parameters match expected parameters.

        Only keys present in ``expected_params`` are checked.  Extra keys in
        ``actual_params`` are ignored.  Returns 1.0 when ``expected_params``
        is empty.
        """
        if not expected_params:
            return 1.0
        matched = sum(
            1
            for k, v in expected_params.items()
            if actual_params.get(k) == v
        )
        return round(matched / len(expected_params), 4)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _steps_match(actual: dict[str, Any], expected: TrajectoryStep) -> bool:
        """Return True when *actual* satisfies the *expected* step constraints.

        Matching rules:
        - ``action`` must match exactly (case-sensitive).
        - ``tool_name``, when specified in expected, must match actual.
        - No parameter matching here — use
          :meth:`evaluate_parameter_correctness` for that.
        """
        actual_action = str(actual.get("action", "")).strip()
        if actual_action != expected.action.strip():
            return False

        if expected.tool_name is not None:
            actual_tool = actual.get("tool_name")
            if actual_tool != expected.tool_name:
                return False

        return True
