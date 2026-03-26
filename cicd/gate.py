"""CI/CD gate for agent quality regression detection."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


class CICDGate:
    """CI/CD gate that fails builds on agent quality regression."""

    def __init__(self):
        self.exit_code = 0
        self.results: dict[str, Any] = {}

    def run_gate(
        self,
        config_path: str,
        baseline_path: str | None = None,
        fail_threshold: float | None = None,
    ) -> dict[str, Any]:
        """Run evaluation and compare to baseline.

        Args:
            config_path: Path to agent config to evaluate
            baseline_path: Path to baseline config for comparison
            fail_threshold: Regression threshold (e.g., 0.05 for 5%)

        Returns:
            Structured JSON summary with scores, deltas, and gate decision
        """
        from evals.runner import EvalRunner

        eval_runner = EvalRunner()

        # Run eval on candidate config
        candidate_score = eval_runner.run(config_path=config_path)

        results: dict[str, Any] = {
            "config_path": config_path,
            "candidate_scores": {
                "composite": candidate_score.composite,
                "quality": candidate_score.quality,
                "safety": candidate_score.safety,
                "latency": candidate_score.latency,
                "cost": candidate_score.cost,
            },
            "gate_passed": True,
            "regression_detected": False,
            "failure_reasons": [],
        }

        # Compare to baseline if provided
        if baseline_path:
            baseline_score = eval_runner.run(config_path=baseline_path)
            results["baseline_scores"] = {
                "composite": baseline_score.composite,
                "quality": baseline_score.quality,
                "safety": baseline_score.safety,
                "latency": baseline_score.latency,
                "cost": baseline_score.cost,
            }

            # Calculate deltas
            delta = candidate_score.composite - baseline_score.composite
            results["delta"] = delta

            # Check for regression
            threshold = fail_threshold or 0.0
            if delta < -threshold:
                results["gate_passed"] = False
                results["regression_detected"] = True
                results["failure_reasons"].append(
                    f"Quality regression detected: {delta:.4f} < -{threshold}"
                )
                self.exit_code = 1

        # Hard gate: Safety must not regress
        if baseline_path and candidate_score.safety < results["baseline_scores"]["safety"]:
            results["gate_passed"] = False
            results["failure_reasons"].append("Safety score regressed")
            self.exit_code = 1

        # Hard gate: Safety violations
        if candidate_score.safety < 1.0:
            results["gate_passed"] = False
            results["failure_reasons"].append("Safety violations detected")
            self.exit_code = 1

        self.results = results
        return results

    def output_json(self, output_path: str | None = None) -> None:
        """Output results as JSON."""
        json_str = json.dumps(self.results, indent=2)

        if output_path:
            Path(output_path).write_text(json_str)
        else:
            print(json_str)

    def exit(self) -> None:
        """Exit with appropriate code."""
        sys.exit(self.exit_code)
