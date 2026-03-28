"""Browser skill evaluation harness — cases, runner, and scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BrowserEvalCase:
    """A single browser task evaluation case."""

    task: str
    start_url: str
    expected_actions: list[dict[str, Any]] = field(default_factory=list)
    success_criteria: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "start_url": self.start_url,
            "expected_actions": self.expected_actions,
            "success_criteria": self.success_criteria,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BrowserEvalCase":
        return cls(
            task=data["task"],
            start_url=data["start_url"],
            expected_actions=data.get("expected_actions", []),
            success_criteria=data.get("success_criteria", {}),
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class BrowserEvalRunner:
    """Run BrowserEvalCases against an executor and score the results."""

    def run_case(self, case: BrowserEvalCase, executor: Any) -> dict[str, Any]:
        """Execute a single *case* using *executor* and return a result dict.

        The executor must expose ``execute_sequence(steps)``; steps are
        reconstructed from ``case.expected_actions`` so the runner can
        re-play expected sequences and check outputs.
        """
        from agent_skills.browser.actions import BrowserActionStep

        steps = [BrowserActionStep.from_dict(a) for a in case.expected_actions]

        start = datetime.now(timezone.utc).isoformat()
        action_results = executor.execute_sequence(steps)
        end = datetime.now(timezone.utc).isoformat()

        passed = self._check_criteria(action_results, case.success_criteria)
        return {
            "task": case.task,
            "start_url": case.start_url,
            "passed": passed,
            "action_results": action_results,
            "actions_attempted": len(action_results),
            "actions_succeeded": sum(1 for r in action_results if r.get("success")),
            "started_at": start,
            "finished_at": end,
        }

    def score(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute aggregate metrics over a list of run_case results."""
        if not results:
            return {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0}
        total = len(results)
        passed = sum(1 for r in results if r.get("passed"))
        failed = total - passed
        action_success_rates = []
        for r in results:
            attempted = r.get("actions_attempted", 0)
            succeeded = r.get("actions_succeeded", 0)
            if attempted > 0:
                action_success_rates.append(succeeded / attempted)
        avg_action_success = (
            sum(action_success_rates) / len(action_success_rates)
            if action_success_rates
            else 0.0
        )
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / total, 4),
            "avg_action_success_rate": round(avg_action_success, 4),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_criteria(
        self,
        action_results: list[dict[str, Any]],
        criteria: dict[str, Any],
    ) -> bool:
        """Evaluate success criteria against action results.

        Supported criteria keys:
        - ``all_succeeded`` (bool): all actions must have succeeded.
        - ``min_succeeded`` (int): minimum number of successful actions.
        - ``contains_output`` (str): at least one action output contains this string.
        """
        if not criteria:
            # Default: all actions succeeded
            return all(r.get("success", False) for r in action_results)

        if criteria.get("all_succeeded", False):
            if not all(r.get("success", False) for r in action_results):
                return False

        min_succeeded = criteria.get("min_succeeded")
        if min_succeeded is not None:
            succeeded = sum(1 for r in action_results if r.get("success"))
            if succeeded < int(min_succeeded):
                return False

        contains_output = criteria.get("contains_output")
        if contains_output:
            outputs = " ".join(str(r.get("output", "")) for r in action_results)
            if contains_output.lower() not in outputs.lower():
                return False

        return True
