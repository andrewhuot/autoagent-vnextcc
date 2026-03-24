"""Grader stack — orchestrates the ordered judge pipeline.

Execution order: deterministic -> rule_based -> llm -> audit.
Early-exits on required grader failure.
"""

from __future__ import annotations

from typing import Any

from core.types import GraderBundle, GraderType, JudgeVerdict

from .audit_judge import AuditJudge
from .deterministic import DeterministicJudge
from .llm_judge import LLMJudge
from .rule_based import RuleBasedJudge


class GraderStack:
    """Executes an ordered grader bundle and aggregates verdicts."""

    def __init__(
        self,
        bundle: GraderBundle,
        deterministic: DeterministicJudge,
        rule_based: RuleBasedJudge,
        llm: LLMJudge | None = None,
        audit: AuditJudge | None = None,
    ) -> None:
        self.bundle = bundle
        self.deterministic = deterministic
        self.rule_based = rule_based
        self.llm = llm
        self.audit = audit

    def execute(
        self,
        task: str,
        response: str,
        context: dict[str, Any] | None = None,
    ) -> list[JudgeVerdict]:
        """Run graders in stack order, collecting verdicts.

        Execution order follows the GraderBundle spec list, grouped by type:
        deterministic -> rule_based -> llm_judge -> audit_judge.

        If a grader spec is marked ``required=True`` and its verdict fails,
        execution stops immediately (early-exit).

        Args:
            task: The original task / user message.
            response: The agent's response text.
            context: Optional context dict for deterministic checks.

        Returns:
            List of JudgeVerdict objects from each grader that ran.
        """
        ctx = context or {}
        verdicts: list[JudgeVerdict] = []

        # Process graders in type order
        ordered_types = [
            GraderType.deterministic,
            GraderType.rule_based,
            GraderType.llm_judge,
            GraderType.audit_judge,
        ]

        for grader_type in ordered_types:
            specs = self.bundle.get_graders_by_type(grader_type)
            for spec in specs:
                verdict = self._run_grader(spec.grader_type, task, response, ctx, verdicts)
                if verdict is None:
                    continue
                verdicts.append(verdict)

                # Early-exit on required grader failure
                if spec.required and not verdict.passed:
                    return verdicts

        return verdicts

    def _run_grader(
        self,
        grader_type: GraderType,
        task: str,
        response: str,
        context: dict[str, Any],
        previous_verdicts: list[JudgeVerdict],
    ) -> JudgeVerdict | None:
        """Dispatch to the appropriate judge based on grader type."""
        if grader_type == GraderType.deterministic:
            # Run regex check if pattern is in context, otherwise state check
            if "pattern" in context:
                return self.deterministic.check_regex(context["pattern"], response)
            if "expected_state" in context and "actual_state" in context:
                return self.deterministic.check_state(
                    context["expected_state"], context["actual_state"]
                )
            # Default: check that response is non-empty
            return self.deterministic.check_regex(r".+", response)

        if grader_type == GraderType.rule_based:
            rules = context.get("format_rules", {})
            if rules:
                return self.rule_based.check_format(response, rules)
            required_fields = context.get("required_fields")
            if required_fields and isinstance(context.get("data"), dict):
                return self.rule_based.check_required_fields(
                    context["data"], required_fields
                )
            # Default: basic format check (non-empty, reasonable length)
            return self.rule_based.check_format(
                response, {"min_length": 1}
            )

        if grader_type == GraderType.llm_judge:
            if self.llm is None:
                return None
            reference = context.get("reference")
            criteria = context.get("criteria")
            return self.llm.evaluate(task, response, reference, criteria)

        if grader_type == GraderType.audit_judge:
            if self.audit is None:
                return None
            # Audit the last LLM verdict, or the last verdict overall
            primary = self._find_primary_verdict(previous_verdicts)
            if primary is None:
                return None
            return self.audit.audit(task, response, primary)

        return None

    @staticmethod
    def _find_primary_verdict(verdicts: list[JudgeVerdict]) -> JudgeVerdict | None:
        """Find the primary LLM judge verdict to audit, falling back to last."""
        # Prefer the LLM judge verdict
        for v in reversed(verdicts):
            if "llm_judge" in v.judge_id:
                return v
        # Fall back to the most recent verdict
        return verdicts[-1] if verdicts else None

    def aggregate(self, verdicts: list[JudgeVerdict]) -> JudgeVerdict:
        """Produce a weighted aggregate verdict from individual verdicts.

        Weights are taken from the GraderBundle specs.  If a verdict's
        judge cannot be matched to a spec, it gets weight 1.0.
        """
        if not verdicts:
            return JudgeVerdict(
                score=0.0,
                passed=False,
                judge_id="grader_stack_aggregate",
                failure_reasons=["No verdicts to aggregate"],
                confidence=0.0,
            )

        # Build weight map from bundle specs
        weight_map: dict[str, float] = {}
        for spec in self.bundle.graders:
            weight_map[spec.grader_id] = spec.weight
            # Also map by type for fallback matching
            weight_map[spec.grader_type.value] = spec.weight

        total_weight = 0.0
        weighted_score = 0.0
        all_evidence: list[str] = []
        all_failures: list[str] = []
        min_confidence = 1.0

        for verdict in verdicts:
            weight = weight_map.get(
                verdict.judge_id,
                weight_map.get(verdict.judge_id.split("_")[0], 1.0),
            )
            total_weight += weight
            weighted_score += verdict.score * weight
            all_evidence.extend(verdict.evidence_spans)
            all_failures.extend(verdict.failure_reasons)
            min_confidence = min(min_confidence, verdict.confidence)

        final_score = weighted_score / total_weight if total_weight > 0 else 0.0

        # Any required grader failure means overall failure
        required_ids = {
            spec.grader_id for spec in self.bundle.graders if spec.required
        }
        required_failed = any(
            not v.passed for v in verdicts if v.judge_id in required_ids
        )

        passed = final_score >= 0.5 and not required_failed

        return JudgeVerdict(
            score=round(final_score, 4),
            passed=passed,
            judge_id="grader_stack_aggregate",
            evidence_spans=all_evidence[:20],  # cap for sanity
            failure_reasons=all_failures,
            confidence=round(min_confidence, 4),
            metadata={
                "bundle_id": self.bundle.bundle_id,
                "verdict_count": len(verdicts),
                "total_weight": total_weight,
                "required_failed": required_failed,
            },
        )
