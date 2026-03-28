"""Skill creator meta-skill: generates SKILL.md skills from natural language descriptions.

This module provides a :class:`SkillCreator` that can synthesise a valid SKILL.md document
from a plain-English description or from a set of successful optimisation traces.  The
generated content is intentionally deterministic and rule-based so that it can be used
without an LLM backend; it is meant to bootstrap a new skill that a human (or an LLM)
can then refine.
"""

from __future__ import annotations

import re
import time
from typing import Any

from registry.skill_md import SkillMdSerializer


# ---------------------------------------------------------------------------
# Category-specific heuristics
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "routing": ["route", "routing", "dispatch", "classify", "intent", "handoff", "transfer"],
    "safety": ["safe", "safety", "guardrail", "block", "filter", "pii", "toxic", "harmful", "restrict"],
    "latency": ["latency", "speed", "fast", "slow", "timeout", "cache", "concurren", "parallel"],
    "cost": ["cost", "token", "cheap", "budget", "expensive", "reduc", "compress", "truncat"],
    "quality": ["quality", "accurac", "correct", "improve", "better", "enhance", "optim"],
}

_CATEGORY_EVAL_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "routing": [
        {"metric": "routing_accuracy", "target": 0.9, "operator": "gt", "weight": 1.0},
        {"metric": "false_positive_rate", "target": 0.05, "operator": "lt", "weight": 0.5},
    ],
    "safety": [
        {"metric": "safety_compliance_rate", "target": 0.99, "operator": "gt", "weight": 2.0},
        {"metric": "pii_leak_rate", "target": 0.0, "operator": "eq", "weight": 2.0},
    ],
    "latency": [
        {"metric": "p95_latency_ms", "target": 500, "operator": "lt", "weight": 1.0},
        {"metric": "token_count", "target": 1000, "operator": "lt", "weight": 0.5},
    ],
    "cost": [
        {"metric": "tokens_per_request", "target": 800, "operator": "lt", "weight": 1.0},
        {"metric": "cost_per_1k_requests_usd", "target": 0.5, "operator": "lt", "weight": 1.0},
    ],
    "quality": [
        {"metric": "task_success_rate", "target": 0.85, "operator": "gt", "weight": 1.0},
        {"metric": "user_satisfaction", "target": 4.0, "operator": "gt", "weight": 0.5},
    ],
}

_CATEGORY_TRIGGER_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "routing": [{"failure_family": "routing_error", "metric_name": "routing_accuracy", "threshold": 0.8, "operator": "lt"}],
    "safety": [{"failure_family": "safety_violation", "metric_name": "safety_compliance_rate", "threshold": 0.95, "operator": "lt"}],
    "latency": [{"failure_family": "latency_spike", "metric_name": "p95_latency_ms", "threshold": 1000, "operator": "gt"}],
    "cost": [{"failure_family": "cost_overrun", "metric_name": "tokens_per_request", "threshold": 1500, "operator": "gt"}],
    "quality": [{"failure_family": "quality_degradation", "metric_name": "task_success_rate", "threshold": 0.7, "operator": "lt"}],
}

_KIND_MUTATION_TYPES: dict[str, str] = {
    "runtime": "instruction_rewrite",
    "buildtime": "prompt_template_rewrite",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# SkillCreator
# ---------------------------------------------------------------------------


class SkillCreator:
    """Generates SKILL.md content from natural-language descriptions or traces.

    All output is a valid SKILL.md string ready to be written to disk or
    registered via :class:`~registry.skill_store.SkillStore`.
    """

    def __init__(self) -> None:
        self._serializer = SkillMdSerializer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_from_description(
        self,
        description: str,
        category: str = "quality",
        kind: str = "runtime",
    ) -> str:
        """Generate a SKILL.md document from a plain-English description.

        The method infers a skill name, suitable mutation templates, and eval
        criteria from the description text and the supplied category/kind.

        Args:
            description: Human-readable description of what this skill does.
            category: One of ``routing``, ``safety``, ``latency``, ``quality``,
                ``cost``.  Defaults to ``quality``.
            kind: ``runtime`` or ``buildtime``.  Defaults to ``runtime``.

        Returns:
            SKILL.md formatted string.
        """
        # Infer category from description if not explicitly given or if default
        inferred = self._infer_category(description)
        if inferred and category == "quality":
            category = inferred

        name = self._description_to_name(description)
        fm = self._generate_frontmatter(name, description, category, kind)
        mutations = self._infer_mutations(description)
        eval_criteria = self._infer_eval_criteria(description, category)
        triggers = _CATEGORY_TRIGGER_DEFAULTS.get(category, [])

        skill: dict[str, Any] = {
            **fm,
            "mutations": mutations,
            "eval_criteria": eval_criteria,
            "triggers": triggers,
            "examples": [],
            "guardrails": self._infer_guardrails(description, category),
            "target_surfaces": ["system_prompt"],
            "instructions": self._generate_instructions(description, category, kind),
            "references": "",
            "tags": [category, kind],
            "times_applied": 0,
            "success_rate": 0.0,
            "status": "draft",
        }

        return self._serializer.serialize(skill)

    def create_from_traces(self, traces: list[dict[str, Any]], pattern_name: str) -> str:
        """Extract a reusable skill from a set of successful optimisation traces.

        Each trace dict should have at minimum:
        - ``before``: the original prompt/instruction text
        - ``after``: the improved text
        - ``improvement``: numeric delta (e.g. 0.12 for +12% task success rate)
        - ``metric``: name of the metric that improved

        Args:
            traces: List of trace dicts recording before/after optimisations.
            pattern_name: Human-readable name for the discovered pattern.

        Returns:
            SKILL.md formatted string.
        """
        if not traces:
            return self.create_from_description(pattern_name)

        # Derive description from the pattern name + traces
        description = self._traces_to_description(traces, pattern_name)

        # Determine dominant metric from traces to infer category
        metrics = [t.get("metric", "") for t in traces if t.get("metric")]
        category = self._metric_to_category(metrics[0]) if metrics else "quality"

        name = self._description_to_name(pattern_name)
        avg_improvement = sum(float(t.get("improvement", 0.0)) for t in traces) / len(traces)

        fm = self._generate_frontmatter(name, description, category, "runtime")
        fm["provenance"] = "traces"
        fm["trust_level"] = "community-tested" if len(traces) >= 5 else "unverified"

        # Build examples from traces (up to 3)
        examples: list[dict[str, Any]] = []
        for i, trace in enumerate(traces[:3]):
            examples.append(
                {
                    "name": f"Trace Example {i + 1}",
                    "surface": trace.get("surface", "system_prompt"),
                    "before": str(trace.get("before", "")),
                    "after": str(trace.get("after", "")),
                    "improvement": float(trace.get("improvement", 0.0)),
                    "context": str(trace.get("context", "")),
                }
            )

        mutations = self._infer_mutations(description)
        eval_criteria = self._infer_eval_criteria(description, category)
        triggers = _CATEGORY_TRIGGER_DEFAULTS.get(category, [])

        skill: dict[str, Any] = {
            **fm,
            "mutations": mutations,
            "eval_criteria": eval_criteria,
            "triggers": triggers,
            "examples": examples,
            "guardrails": self._infer_guardrails(description, category),
            "target_surfaces": ["system_prompt"],
            "proven_improvement": avg_improvement,
            "instructions": self._generate_instructions(description, category, "runtime"),
            "references": "",
            "tags": [category, "from-traces"],
            "times_applied": len(traces),
            "success_rate": min(1.0, avg_improvement * 5),  # heuristic
            "status": "active" if avg_improvement > 0.05 else "draft",
        }

        return self._serializer.serialize(skill)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _infer_mutations(self, description: str) -> list[dict[str, Any]]:
        """Infer mutation templates from a description string.

        Args:
            description: Natural-language description of the skill.

        Returns:
            List of mutation dicts compatible with :class:`~registry.skill_types.MutationTemplate`.
        """
        lower = description.lower()
        mutations: list[dict[str, Any]] = []

        # Always include a system-prompt rewrite mutation
        mutations.append(
            {
                "name": "system-prompt-rewrite",
                "mutation_type": "instruction_rewrite",
                "target_surface": "system_prompt",
                "description": f"Rewrite system prompt to apply: {description[:120]}",
                "template": None,
            }
        )

        # Add a few-shot example injection if description mentions examples or demos
        if any(kw in lower for kw in ("example", "demo", "sample", "few-shot", "illustrat")):
            mutations.append(
                {
                    "name": "few-shot-injection",
                    "mutation_type": "few_shot_injection",
                    "target_surface": "user_message",
                    "description": "Inject carefully curated few-shot examples before the user turn.",
                    "template": None,
                }
            )

        # Add a parameter-tuning mutation for latency/cost related skills
        if any(kw in lower for kw in ("temperature", "token", "max", "latency", "cost", "fast")):
            mutations.append(
                {
                    "name": "parameter-tuning",
                    "mutation_type": "parameter_override",
                    "target_surface": "model_parameters",
                    "description": "Tune model parameters (temperature, max_tokens) for this skill.",
                    "template": None,
                }
            )

        return mutations

    def _infer_eval_criteria(
        self, description: str, category: str
    ) -> list[dict[str, Any]]:
        """Infer eval criteria from description text and category.

        Args:
            description: Natural-language description of the skill.
            category: Skill category.

        Returns:
            List of eval criterion dicts.
        """
        # Start with category defaults
        criteria: list[dict[str, Any]] = list(_CATEGORY_EVAL_DEFAULTS.get(category, []))

        # If a specific metric is mentioned in description, add a bespoke criterion
        metric_patterns = [
            (r"\baccurac(?:y|ies)\b", "accuracy", 0.85, "gt"),
            (r"\bf1[\s_-]?score\b", "f1_score", 0.8, "gt"),
            (r"\bprecision\b", "precision", 0.9, "gt"),
            (r"\brecall\b", "recall", 0.8, "gt"),
            (r"\blatency\b", "p95_latency_ms", 500, "lt"),
            (r"\bcost\b", "cost_per_1k_requests_usd", 1.0, "lt"),
        ]
        existing_metrics = {c["metric"] for c in criteria}
        for pattern, metric, target, operator in metric_patterns:
            if re.search(pattern, description, re.IGNORECASE) and metric not in existing_metrics:
                criteria.append({"metric": metric, "target": target, "operator": operator, "weight": 1.0})
                existing_metrics.add(metric)

        return criteria

    def _infer_guardrails(self, description: str, category: str) -> list[str]:
        """Infer appropriate guardrails from the description and category.

        Args:
            description: Skill description text.
            category: Skill category.

        Returns:
            List of guardrail identifier strings.
        """
        guardrails: list[str] = []
        lower = description.lower()

        if category == "safety" or any(kw in lower for kw in ("pii", "personal", "private", "sensitive")):
            guardrails.append("no_pii_exposure")

        if any(kw in lower for kw in ("topic", "restrict", "domain", "out-of-scope", "scope")):
            guardrails.append("topic_restriction")

        if any(kw in lower for kw in ("harm", "toxic", "abuse", "violence", "illegal")):
            guardrails.append("content_safety_filter")

        # Universal guardrail for all skills
        guardrails.append("preserve_existing_behavior")

        return guardrails

    def _generate_frontmatter(
        self,
        name: str,
        description: str,
        category: str,
        kind: str,
    ) -> dict[str, Any]:
        """Build the frontmatter dict for a new skill.

        Args:
            name: Slugified skill name.
            description: Skill description.
            category: Skill category.
            kind: ``runtime`` or ``buildtime``.

        Returns:
            Frontmatter dict (subset of what :meth:`Skill.to_dict` produces).
        """
        return {
            "name": name,
            "version": 1,
            "kind": kind,
            "category": category,
            "platform": "universal",
            "description": description,
            "author": "skill-creator",
            "dependencies": [],
            "allowed_tools": [],
            "supported_frameworks": ["adk", "claude-code", "codex"],
            "required_approvals": [],
            "eval_contract": {},
            "rollout_policy": "gradual",
            "provenance": "autoagent",
            "trust_level": "unverified",
            "runtime_effectiveness": 0.0,
            "buildtime_effectiveness": 0.0,
            "created_at": time.time(),
        }

    def _generate_instructions(self, description: str, category: str, kind: str) -> str:
        """Generate Layer 2 instructions text for the skill.

        Args:
            description: Skill description.
            category: Skill category.
            kind: ``runtime`` or ``buildtime``.

        Returns:
            Instructions markdown string.
        """
        context_noun = "runtime agent" if kind == "runtime" else "build-time prompt generator"
        return (
            f"This skill targets a {context_noun} in the **{category}** domain.\n\n"
            f"**Objective**: {description}\n\n"
            "**Application steps**:\n"
            "1. Identify the target surface (e.g. system_prompt, user_message).\n"
            "2. Apply the mutation template that best matches the failure mode.\n"
            "3. Run the eval suite against the modified surface.\n"
            "4. Accept if all eval criteria are met; rollback otherwise.\n"
        )

    # ------------------------------------------------------------------
    # Private utility methods
    # ------------------------------------------------------------------

    def _description_to_name(self, description: str) -> str:
        """Convert a free-form description to a slug suitable for use as a skill name."""
        # Take first N significant words
        words = description.lower().split()
        stop_words = {"a", "an", "the", "to", "for", "of", "in", "on", "and", "or", "is", "that"}
        significant = [w for w in words if w not in stop_words][:5]
        slug = "-".join(significant)
        slug = _SLUG_RE.sub("-", slug).strip("-")
        return slug or "unnamed-skill"

    def _infer_category(self, description: str) -> str | None:
        """Guess category from keywords in the description."""
        lower = description.lower()
        scores: dict[str, int] = {}
        for cat, keywords in _CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in lower)
            if score:
                scores[cat] = score
        if scores:
            return max(scores, key=lambda k: scores[k])
        return None

    def _metric_to_category(self, metric: str) -> str:
        """Map a metric name to a skill category."""
        m = metric.lower()
        if any(kw in m for kw in ("routing", "intent", "classif")):
            return "routing"
        if any(kw in m for kw in ("safety", "pii", "toxic", "harm")):
            return "safety"
        if any(kw in m for kw in ("latency", "ms", "speed")):
            return "latency"
        if any(kw in m for kw in ("cost", "token", "budget")):
            return "cost"
        return "quality"

    def _traces_to_description(self, traces: list[dict[str, Any]], pattern_name: str) -> str:
        """Summarise a set of traces into a short description string."""
        metrics = list({t.get("metric", "") for t in traces if t.get("metric")})
        avg = sum(float(t.get("improvement", 0.0)) for t in traces) / len(traces)
        metric_str = ", ".join(metrics[:3]) if metrics else "task success"
        return (
            f"{pattern_name}: pattern extracted from {len(traces)} successful optimisation trace(s). "
            f"Targets {metric_str}. Average measured improvement: {avg:+.1%}."
        )
