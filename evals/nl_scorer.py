"""Natural language to structured scorer compiler.

Entry point for creating eval scorers from English descriptions.
"""

from __future__ import annotations

import re
from typing import Any

from evals.nl_compiler import NLCompiler
from evals.scorer import EvalResult
from evals.scorer_spec import ScorerSpec


class NLScorer:
    """Natural language to structured scorer compiler.

    Entry point for creating eval scorers from English descriptions.
    """

    def __init__(self, compiler: NLCompiler | None = None) -> None:
        self.compiler = compiler or NLCompiler()
        self._specs: dict[str, ScorerSpec] = {}  # name -> spec cache

    def create(self, nl_description: str, name: str | None = None) -> ScorerSpec:
        """Compile an NL description into a ScorerSpec.

        Args:
            nl_description: English description of success criteria.
            name: Optional name for the scorer (auto-generated if not provided).

        Returns:
            ScorerSpec ready for use in eval runs.
        """
        if name is None:
            name = self._generate_name(nl_description)

        dimensions = self.compiler.compile(nl_description)

        spec = ScorerSpec(
            name=name,
            version=1,
            dimensions=dimensions,
            source_nl=nl_description,
        )
        self._specs[name] = spec
        return spec

    def refine(self, spec_name: str, additional_nl: str) -> ScorerSpec:
        """Refine an existing scorer with additional NL criteria.

        Adds new dimensions or modifies existing ones. Version is bumped.
        """
        existing = self._specs.get(spec_name)
        if existing is None:
            raise KeyError(f"Scorer spec '{spec_name}' not found")

        new_dimensions = self.compiler.compile(additional_nl)

        # Merge: keep existing dimensions, add new ones
        existing_names = {d.name for d in existing.dimensions}
        for dim in new_dimensions:
            if dim.name not in existing_names:
                existing.dimensions.append(dim)
                existing_names.add(dim.name)

        # Re-assign weights across all dimensions
        existing.dimensions = self.compiler._assign_weights(existing.dimensions)
        existing.version += 1
        existing.source_nl += f"\n{additional_nl}"

        return existing

    def get(self, name: str) -> ScorerSpec | None:
        """Get a scorer spec by name."""
        return self._specs.get(name)

    def list(self) -> list[ScorerSpec]:
        """List all scorer specs."""
        return list(self._specs.values())

    def test(self, spec_name: str, eval_result: EvalResult) -> dict[str, Any]:
        """Test a scorer spec against an EvalResult.

        Returns per-dimension scores and an aggregate score.
        """
        spec = self._specs.get(spec_name)
        if spec is None:
            raise KeyError(f"Scorer spec '{spec_name}' not found")

        dim_scores: dict[str, dict[str, Any]] = {}
        weighted_sum = 0.0
        total_weight = 0.0
        all_required_passed = True

        for dim in spec.dimensions:
            score = self._score_dimension(dim, eval_result)
            passed = score >= 0.5
            dim_scores[dim.name] = {
                "score": score,
                "passed": passed,
                "weight": dim.weight,
                "layer": dim.layer,
                "required": dim.required,
            }
            weighted_sum += score * dim.weight
            total_weight += dim.weight
            if dim.required and not passed:
                all_required_passed = False

        aggregate = weighted_sum / total_weight if total_weight > 0 else 0.0

        return {
            "dimensions": dim_scores,
            "aggregate_score": round(aggregate, 4),
            "passed": all_required_passed and aggregate >= 0.5,
        }

    def score_results(
        self, spec_name: str, results: list[EvalResult]
    ) -> dict[str, Any]:
        """Score a list of EvalResults using a scorer spec.

        Returns aggregate scores across all results.
        """
        if not results:
            return {
                "total_results": 0,
                "average_score": 0.0,
                "passed_count": 0,
                "failed_count": 0,
                "per_result": [],
            }

        per_result: list[dict[str, Any]] = []
        total_score = 0.0
        passed_count = 0

        for result in results:
            scored = self.test(spec_name, result)
            scored["case_id"] = result.case_id
            per_result.append(scored)
            total_score += scored["aggregate_score"]
            if scored["passed"]:
                passed_count += 1

        return {
            "total_results": len(results),
            "average_score": round(total_score / len(results), 4),
            "passed_count": passed_count,
            "failed_count": len(results) - passed_count,
            "per_result": per_result,
        }

    @staticmethod
    def _generate_name(nl_description: str) -> str:
        """Generate a scorer name from the NL description."""
        text = nl_description.lower().strip()
        text = re.sub(r"[^a-z0-9\s]", "", text)
        words = text.split()
        # Take first 4 meaningful words (skip very short ones)
        meaningful = [w for w in words if len(w) > 2][:4]
        if not meaningful:
            meaningful = ["scorer"]
        return "_".join(meaningful)

    @staticmethod
    def _score_dimension(
        dim: "ScorerDimension",  # noqa: F821 — forward ref
        result: EvalResult,
    ) -> float:
        """Score a single dimension against an EvalResult.

        Uses deterministic heuristics based on grader_type and config.
        """
        config = dim.grader_config
        check_type = config.get("type", "")

        if dim.grader_type == "deterministic":
            if check_type == "latency_threshold":
                threshold = config.get("threshold_ms", 3000)
                return 1.0 if result.latency_ms <= threshold else 0.0

        if dim.grader_type == "llm_judge":
            if check_type == "hallucination_check":
                # Use safety_passed as proxy
                return 1.0 if result.safety_passed else 0.0
            if check_type == "accuracy_check":
                return result.quality_score
            if check_type == "tone_check":
                return result.quality_score
            if check_type == "completeness_check":
                return result.quality_score
            if check_type == "resolution_check":
                return 1.0 if result.passed else 0.0
            if check_type == "tool_usage_check":
                return result.tool_use_accuracy
            if check_type == "followup_check":
                return result.satisfaction_proxy
            if check_type == "repetition_check":
                return result.quality_score
            if check_type == "privacy_check":
                return 1.0 if result.safety_passed else 0.0
            if check_type == "citation_check":
                return result.quality_score
            # Fallback for custom_check and unknown types
            return result.quality_score

        # similarity or unknown grader type
        return result.quality_score
