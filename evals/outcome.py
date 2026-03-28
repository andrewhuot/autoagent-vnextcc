"""Outcome evaluation — is the final state correct?

Evaluates the *result* of an agent run independently of how the agent got
there.  Works by running a list of :class:`OutcomeCheck` assertions against a
``final_state`` dict and, optionally, comparing environment snapshots before
and after the run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Supported comparison operators
# ---------------------------------------------------------------------------

_SUPPORTED_OPERATORS = frozenset({"eq", "contains", "gt", "lt", "exists", "not_exists"})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OutcomeCheck:
    """A single assertion to run against the final state.

    Args:
        check_type: Logical category, e.g. ``"value"``, ``"side_effect"``.
        key: Dot-path key to look up in the state dict (supports nested dicts
            using ``"parent.child"`` notation).
        expected_value: The value to compare against (ignored for
            ``exists`` / ``not_exists``).
        operator: Comparison operator — one of ``eq``, ``contains``, ``gt``,
            ``lt``, ``exists``, ``not_exists``.
        description: Optional human-readable label for this check.
    """

    check_type: str
    key: str
    expected_value: Any = None
    operator: str = "eq"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_type": self.check_type,
            "key": self.key,
            "expected_value": self.expected_value,
            "operator": self.operator,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OutcomeCheck":
        return cls(
            check_type=str(d["check_type"]),
            key=str(d["key"]),
            expected_value=d.get("expected_value"),
            operator=str(d.get("operator", "eq")),
            description=str(d.get("description", "")),
        )


@dataclass
class OutcomeResult:
    """Result of running all outcome checks for a single evaluation.

    Args:
        passed: True when every check passed.
        score: Fraction of checks that passed (0.0 – 1.0).
        checks_passed: Number of individual checks that passed.
        checks_total: Total number of checks run.
        failures: List of failure detail dicts.
        environment_verified: True when environment side-effects were
            independently verified (rather than relying on agent self-report).
    """

    passed: bool
    score: float
    checks_passed: int
    checks_total: int
    failures: list[dict[str, Any]] = field(default_factory=list)
    environment_verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "checks_passed": self.checks_passed,
            "checks_total": self.checks_total,
            "failures": self.failures,
            "environment_verified": self.environment_verified,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OutcomeResult":
        return cls(
            passed=bool(d["passed"]),
            score=float(d["score"]),
            checks_passed=int(d["checks_passed"]),
            checks_total=int(d["checks_total"]),
            failures=list(d.get("failures") or []),
            environment_verified=bool(d.get("environment_verified", False)),
        )


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class OutcomeEvaluator:
    """Evaluate final state and environment changes against expectations.

    Usage::

        evaluator = OutcomeEvaluator()

        # Simple key/value checks
        result = evaluator.evaluate(
            final_state={"order_status": "shipped", "items_count": 3},
            expected_state={"order_status": "shipped"},
        )

        # Environment snapshot diff
        result = evaluator.evaluate_environment(
            env_before={"balance": 100},
            env_after={"balance": 75},
            expected_changes={"balance": 75},
        )
    """

    def evaluate(
        self,
        final_state: dict[str, Any],
        expected_state: dict[str, Any],
    ) -> OutcomeResult:
        """Compare *final_state* against every key in *expected_state* using equality.

        Each key in ``expected_state`` generates an implicit ``eq`` check.
        Nested keys are supported via dot notation in ``expected_state``.

        Args:
            final_state: The actual end state produced by the agent.
            expected_state: A flat or nested dict of key→expected_value pairs.

        Returns:
            An :class:`OutcomeResult` summarising pass/fail.
        """
        checks = [
            OutcomeCheck(check_type="value", key=k, expected_value=v, operator="eq")
            for k, v in expected_state.items()
        ]
        if not checks:
            return OutcomeResult(
                passed=True,
                score=1.0,
                checks_passed=0,
                checks_total=0,
                failures=[],
                environment_verified=False,
            )
        return self._run_checks(final_state, checks, environment_verified=False)

    def check_value(
        self,
        actual: Any,
        expected: Any,
        operator: str,
    ) -> bool:
        """Apply a comparison operator to *actual* and *expected*.

        Supported operators:

        - ``eq``         : ``actual == expected``
        - ``contains``   : ``expected in actual`` (strings / lists / dicts)
        - ``gt``         : ``actual > expected``
        - ``lt``         : ``actual < expected``
        - ``exists``     : ``actual is not None``
        - ``not_exists`` : ``actual is None``

        Args:
            actual: The value retrieved from the state dict.
            expected: The expected value (may be ``None`` for exists checks).
            operator: One of the supported operator strings.

        Returns:
            ``True`` when the assertion passes, ``False`` otherwise.

        Raises:
            ValueError: When *operator* is not one of the supported values.
        """
        if operator not in _SUPPORTED_OPERATORS:
            raise ValueError(
                f"operator must be one of {sorted(_SUPPORTED_OPERATORS)}, "
                f"got {operator!r}"
            )
        if operator == "eq":
            return actual == expected
        if operator == "contains":
            try:
                return expected in actual
            except TypeError:
                return False
        if operator == "gt":
            try:
                return actual > expected  # type: ignore[operator]
            except TypeError:
                return False
        if operator == "lt":
            try:
                return actual < expected  # type: ignore[operator]
            except TypeError:
                return False
        if operator == "exists":
            return actual is not None
        if operator == "not_exists":
            return actual is None
        return False  # unreachable, but satisfies mypy

    def evaluate_environment(
        self,
        env_snapshot_before: dict[str, Any],
        env_snapshot_after: dict[str, Any],
        expected_changes: dict[str, Any],
    ) -> OutcomeResult:
        """Verify that the agent produced the expected environment changes.

        Computes the diff (``after - before``) and then checks that each key
        in *expected_changes* appears in the diff with the expected value.

        Args:
            env_snapshot_before: State of the environment before agent run.
            env_snapshot_after: State of the environment after agent run.
            expected_changes: Key→expected_value pairs that must have changed.

        Returns:
            An :class:`OutcomeResult` with ``environment_verified=True``.
        """
        # Build a "diff" view: keys whose value changed, or appeared/disappeared
        diff: dict[str, Any] = {}
        all_keys = set(env_snapshot_before) | set(env_snapshot_after)
        for k in all_keys:
            before_val = env_snapshot_before.get(k)
            after_val = env_snapshot_after.get(k)
            if before_val != after_val:
                diff[k] = after_val  # record new value

        checks = [
            OutcomeCheck(check_type="env_change", key=k, expected_value=v, operator="eq")
            for k, v in expected_changes.items()
        ]
        if not checks:
            return OutcomeResult(
                passed=True,
                score=1.0,
                checks_passed=0,
                checks_total=0,
                failures=[],
                environment_verified=True,
            )

        # Evaluate checks against diff (unchanged keys are not in diff)
        result = self._run_checks(diff, checks, environment_verified=True)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_checks(
        self,
        state: dict[str, Any],
        checks: list[OutcomeCheck],
        *,
        environment_verified: bool,
    ) -> OutcomeResult:
        """Execute a list of checks against *state* and aggregate results."""
        passed_count = 0
        failures: list[dict[str, Any]] = []

        for check in checks:
            actual = self._get_nested(state, check.key)
            try:
                ok = self.check_value(actual, check.expected_value, check.operator)
            except Exception as exc:
                ok = False
                failures.append({
                    "key": check.key,
                    "operator": check.operator,
                    "expected": check.expected_value,
                    "actual": actual,
                    "error": str(exc),
                    "description": check.description,
                })
                continue

            if ok:
                passed_count += 1
            else:
                failures.append({
                    "key": check.key,
                    "operator": check.operator,
                    "expected": check.expected_value,
                    "actual": actual,
                    "description": check.description,
                })

        total = len(checks)
        score = passed_count / total if total > 0 else 1.0
        return OutcomeResult(
            passed=len(failures) == 0,
            score=round(score, 4),
            checks_passed=passed_count,
            checks_total=total,
            failures=failures,
            environment_verified=environment_verified,
        )

    @staticmethod
    def _get_nested(state: dict[str, Any], key: str) -> Any:
        """Retrieve a value from *state* using dot-separated *key* notation.

        E.g. ``"order.status"`` → ``state["order"]["status"]``.
        Returns ``None`` if any segment is missing.
        """
        parts = key.split(".")
        current: Any = state
        for part in parts:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current
