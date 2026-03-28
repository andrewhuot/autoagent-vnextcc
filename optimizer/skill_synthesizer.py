"""Skill synthesis: extract reusable SKILL.md skills from optimizer mutation patterns.

Implements Voyager-style skill synthesis – patterns that worked repeatedly in
optimization history are promoted into self-contained, reusable SKILL.md skills
that future runs can invoke directly, accumulating durable optimization knowledge.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SynthesisCandidate:
    """A mutation pattern that is a candidate for skill synthesis.

    Attributes:
        pattern_name:    Short identifier for the pattern.
        mutation_type:   Type of mutation (instruction_rewrite, routing_edit, …).
        target_surface:  The config surface the mutation operates on.
        success_rate:    Fraction of times this pattern produced a positive outcome.
        sample_count:    Number of observed attempts contributing to the estimate.
        description:     Human-readable description of the pattern.
        template:        Parameterisable mutation template (may contain {placeholders}).
        source_traces:   List of attempt IDs / trace hashes that informed this candidate.
    """

    pattern_name: str
    mutation_type: str
    target_surface: str
    success_rate: float
    sample_count: int
    description: str
    template: str
    source_traces: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_name": self.pattern_name,
            "mutation_type": self.mutation_type,
            "target_surface": self.target_surface,
            "success_rate": self.success_rate,
            "sample_count": self.sample_count,
            "description": self.description,
            "template": self.template,
            "source_traces": self.source_traces,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SynthesisCandidate:
        return cls(
            pattern_name=data["pattern_name"],
            mutation_type=data["mutation_type"],
            target_surface=data["target_surface"],
            success_rate=data["success_rate"],
            sample_count=data["sample_count"],
            description=data["description"],
            template=data["template"],
            source_traces=data.get("source_traces", []),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SURFACE_TO_CATEGORY: dict[str, str] = {
    "routing": "routing",
    "prompts": "quality",
    "tools": "tools",
    "generation_settings": "latency",
    "thresholds": "latency",
    "safety": "safety",
    "skill_optimization": "quality",
}

_SURFACE_TO_KIND: dict[str, str] = {
    "routing": "runtime",
    "prompts": "runtime",
    "tools": "runtime",
    "generation_settings": "runtime",
    "thresholds": "runtime",
    "safety": "runtime",
    "skill_optimization": "buildtime",
}


def _stable_id(name: str) -> str:
    """Generate a short deterministic hex ID from a name."""
    return hashlib.md5(name.encode()).hexdigest()[:12]


class SkillSynthesizer:
    """Extract mutation patterns from optimization history and synthesize SKILL.md skills.

    Workflow
    --------
    1. ``extract_candidates()`` scans ``optimization_history`` (list of attempt dicts),
       clusters repeated mutation types per target surface, and returns
       ``SynthesisCandidate`` objects above the quality thresholds.
    2. ``synthesize_skill()`` converts a candidate into a SKILL.md-compatible dict.
    3. ``synthesize_from_traces()`` builds a skill directly from raw trace dicts.
    4. ``compose_skills()`` merges multiple existing skill dicts into a composite skill.
    """

    def __init__(
        self,
        min_success_rate: float = 0.7,
        min_samples: int = 3,
    ) -> None:
        self.min_success_rate = min_success_rate
        self.min_samples = min_samples

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def extract_candidates(
        self, optimization_history: list[dict]
    ) -> list[SynthesisCandidate]:
        """Identify reusable patterns in optimization history.

        Parameters
        ----------
        optimization_history:
            Each dict should contain at minimum:
            - ``config_section`` (str) – target surface
            - ``mutation_type`` (str, optional) – explicit mutation operator
            - ``accepted`` (bool) – whether the attempt was accepted
            - ``improvement`` (float, optional) – measured improvement delta
            - ``attempt_id`` (str, optional) – unique trace id
            - ``change_description`` (str, optional) – human note
        """
        patterns = self._detect_patterns(optimization_history)
        clusters = self._cluster_mutations(
            [p for p in patterns if p.get("accepted", False)]
        )

        candidates: list[SynthesisCandidate] = []
        for key, mutations in clusters.items():
            if len(mutations) < self.min_samples:
                continue

            surface, mut_type = key.split("|", 1)
            successes = sum(1 for m in mutations if m.get("improvement", 0.0) > 0)
            success_rate = successes / len(mutations)

            if success_rate < self.min_success_rate:
                continue

            # Build a representative template from the most common change_description
            descriptions = [m.get("change_description", "") for m in mutations if m.get("change_description")]
            template = self._build_template(descriptions, surface, mut_type)
            description = descriptions[0] if descriptions else f"Auto-synthesised {mut_type} on {surface}"
            traces = [m.get("attempt_id", "") for m in mutations if m.get("attempt_id")]

            name = f"synth_{surface}_{mut_type}_{_stable_id(key)}"
            candidate = SynthesisCandidate(
                pattern_name=name,
                mutation_type=mut_type,
                target_surface=surface,
                success_rate=round(success_rate, 4),
                sample_count=len(mutations),
                description=description,
                template=template,
                source_traces=traces[:20],  # cap trace list
            )
            candidates.append(candidate)

        # Sort by score descending
        candidates.sort(key=lambda c: self._score_pattern(c.__dict__), reverse=True)
        return candidates

    def synthesize_skill(self, candidate: SynthesisCandidate) -> dict[str, Any]:
        """Produce a SKILL.md-compatible skill dict from a synthesis candidate.

        The resulting dict can be stored directly in ``registry.skill_store.SkillStore``
        or serialised to a ``SKILL.md`` file via ``registry.skill_md.SkillMdSerializer``.
        """
        category = _SURFACE_TO_CATEGORY.get(candidate.target_surface, "general")
        kind = _SURFACE_TO_KIND.get(candidate.target_surface, "runtime")

        skill: dict[str, Any] = {
            # Identity
            "name": candidate.pattern_name,
            "version": 1,
            "kind": kind,
            "status": "draft",
            "author": "skill-synthesizer",
            "provenance": "synthesized",
            "trust_level": "unverified",
            # Description
            "description": candidate.description,
            "category": category,
            "platform": "universal",
            "target_surfaces": [candidate.target_surface],
            # Mutation spec
            "mutations": [
                {
                    "name": f"{candidate.pattern_name}_mutation",
                    "mutation_type": candidate.mutation_type,
                    "target_surface": candidate.target_surface,
                    "description": candidate.description,
                    "template": candidate.template,
                    "parameters": {},
                }
            ],
            # Evidence
            "examples": [
                {
                    "name": f"{candidate.pattern_name}_example",
                    "surface": candidate.target_surface,
                    "before": "(baseline)",
                    "after": candidate.template,
                    "improvement": candidate.success_rate,
                    "context": f"synthesized from {candidate.sample_count} traces",
                }
            ],
            # Quality gates
            "guardrails": [
                "Require statistical significance before promotion.",
                "Reject if safety or regression gates fail.",
                f"Minimum {self.min_samples} successful samples required.",
            ],
            "eval_criteria": [
                {
                    "metric": "composite",
                    "target": 0.0,
                    "operator": "gt",
                    "weight": 1.0,
                }
            ],
            "triggers": [
                {
                    "failure_family": None,
                    "metric_name": None,
                    "threshold": None,
                    "operator": "gt",
                    "blame_pattern": candidate.target_surface,
                }
            ],
            # Effectiveness priors
            "success_rate": candidate.success_rate,
            "times_applied": candidate.sample_count,
            "proven_improvement": None,
            # Metadata
            "tags": ["synthesized", "autolearned", candidate.target_surface],
            "dependencies": [],
            "allowed_tools": [],
            "supported_frameworks": [],
            "required_approvals": [],
            "eval_contract": {},
            "rollout_policy": "gradual",
            "instructions": (
                f"Apply {candidate.mutation_type} to {candidate.target_surface}.\n"
                f"Template: {candidate.template}"
            ),
            "references": f"Derived from traces: {', '.join(candidate.source_traces[:5])}",
            "runtime_effectiveness": candidate.success_rate if kind == "runtime" else 0.0,
            "buildtime_effectiveness": candidate.success_rate if kind == "buildtime" else 0.0,
            "created_at": time.time(),
        }
        return skill

    def synthesize_from_traces(
        self, traces: list[dict], pattern_name: str
    ) -> dict[str, Any]:
        """Build a SKILL.md skill directly from a list of raw trace dicts.

        Parameters
        ----------
        traces:
            Each trace should have ``config_section``, ``accepted``,
            ``improvement``, ``change_description``, and optionally
            ``mutation_type`` and ``attempt_id``.
        pattern_name:
            The desired name for the synthesized skill.
        """
        if not traces:
            raise ValueError("traces must not be empty")

        accepted = [t for t in traces if t.get("accepted", False)]
        if not accepted:
            accepted = traces  # fall back to all

        surface = accepted[0].get("config_section", "prompts")
        mut_type = accepted[0].get("mutation_type", "instruction_rewrite")
        descriptions = [t.get("change_description", "") for t in accepted if t.get("change_description")]
        successes = sum(1 for t in accepted if t.get("improvement", 0.0) > 0)
        success_rate = successes / len(accepted) if accepted else 0.0
        trace_ids = [t.get("attempt_id", "") for t in accepted if t.get("attempt_id")]
        template = self._build_template(descriptions, surface, mut_type)

        candidate = SynthesisCandidate(
            pattern_name=pattern_name,
            mutation_type=mut_type,
            target_surface=surface,
            success_rate=round(success_rate, 4),
            sample_count=len(accepted),
            description=descriptions[0] if descriptions else f"Pattern from {len(accepted)} traces",
            template=template,
            source_traces=trace_ids[:20],
        )
        return self.synthesize_skill(candidate)

    def compose_skills(
        self, skill_names: list[str], new_name: str
    ) -> dict[str, Any]:
        """Compose multiple named skills into a single composite skill dict.

        Parameters
        ----------
        skill_names:
            Names of existing skills whose mutations should be combined.
        new_name:
            The name for the new composite skill.

        Notes
        -----
        The caller must supply skill_names so the method is pure / testable without
        a live store.  The resulting composite contains one mutation per source skill
        with a sequential step index, representing an ordered composition.
        """
        if not skill_names:
            raise ValueError("skill_names must not be empty")

        mutations = []
        for i, sname in enumerate(skill_names):
            mutations.append(
                {
                    "name": f"step_{i+1}_{sname}",
                    "mutation_type": "composite_step",
                    "target_surface": "multi",
                    "description": f"Step {i+1}: apply skill '{sname}'",
                    "template": f"{{{{ skill:{sname} }}}}",
                    "parameters": {"source_skill": sname, "step": i + 1},
                }
            )

        skill: dict[str, Any] = {
            "name": new_name,
            "version": 1,
            "kind": "buildtime",
            "status": "draft",
            "author": "skill-synthesizer",
            "provenance": "composed",
            "trust_level": "unverified",
            "description": f"Composite skill composed from: {', '.join(skill_names)}",
            "category": "quality",
            "platform": "universal",
            "target_surfaces": ["multi"],
            "mutations": mutations,
            "examples": [],
            "guardrails": [
                "All constituent skills must pass their own guardrails.",
                "Validate each step independently before composing.",
            ],
            "eval_criteria": [
                {"metric": "composite", "target": 0.0, "operator": "gt", "weight": 1.0}
            ],
            "triggers": [],
            "success_rate": 0.0,
            "times_applied": 0,
            "proven_improvement": None,
            "tags": ["composed", "autolearned"] + skill_names,
            "dependencies": list(skill_names),
            "allowed_tools": [],
            "supported_frameworks": [],
            "required_approvals": [],
            "eval_contract": {},
            "rollout_policy": "gradual",
            "instructions": (
                f"Execute the following skills in order:\n"
                + "\n".join(f"  {i+1}. {n}" for i, n in enumerate(skill_names))
            ),
            "references": "",
            "runtime_effectiveness": 0.0,
            "buildtime_effectiveness": 0.0,
            "created_at": time.time(),
        }
        return skill

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _detect_patterns(self, history: list[dict]) -> list[dict]:
        """Normalize and annotate each history entry with inferred fields."""
        patterns: list[dict] = []
        for entry in history:
            if not isinstance(entry, dict):
                continue
            surface = entry.get("config_section") or entry.get("target_surface") or "prompts"
            mut_type = entry.get("mutation_type") or self._infer_mutation_type(surface)
            pattern = {
                "config_section": surface,
                "mutation_type": mut_type,
                "accepted": bool(entry.get("accepted", False)),
                "improvement": float(entry.get("improvement", 0.0)),
                "change_description": entry.get("change_description", ""),
                "attempt_id": entry.get("attempt_id", str(uuid.uuid4())[:8]),
            }
            patterns.append(pattern)
        return patterns

    def _cluster_mutations(
        self, mutations: list[dict]
    ) -> dict[str, list[dict]]:
        """Group mutations by (surface, mutation_type) key."""
        clusters: dict[str, list[dict]] = defaultdict(list)
        for m in mutations:
            key = f"{m.get('config_section', 'prompts')}|{m.get('mutation_type', 'instruction_rewrite')}"
            clusters[key].append(m)
        return dict(clusters)

    def _score_pattern(self, pattern: dict) -> float:
        """Score a pattern dict (or SynthesisCandidate.__dict__) for ranking.

        Score = success_rate * log(1 + sample_count) / log(1 + min_samples)
        Rewards both high success rates and larger sample sets.
        """
        import math

        success_rate = float(pattern.get("success_rate", 0.0))
        sample_count = int(pattern.get("sample_count", 0))
        min_s = max(1, self.min_samples)
        scale = math.log(1 + sample_count) / math.log(1 + min_s)
        return success_rate * scale

    @staticmethod
    def _infer_mutation_type(surface: str) -> str:
        """Infer a sensible default mutation_type from a config surface."""
        mapping = {
            "routing": "routing_edit",
            "prompts": "instruction_rewrite",
            "tools": "tool_description_edit",
            "generation_settings": "generation_settings",
            "thresholds": "generation_settings",
            "safety": "policy_edit",
            "skill_optimization": "skill_rewrite",
        }
        return mapping.get(surface, "instruction_rewrite")

    @staticmethod
    def _build_template(
        descriptions: list[str], surface: str, mut_type: str
    ) -> str:
        """Build a parameterisable template from description examples."""
        if not descriptions:
            return f"(draft) apply {mut_type} to {surface}"
        # Use the most common tokens from all descriptions
        token_counts: dict[str, int] = defaultdict(int)
        for desc in descriptions:
            for tok in desc.lower().split():
                if len(tok) > 3:
                    token_counts[tok] += 1
        top_tokens = sorted(token_counts, key=lambda t: -token_counts[t])[:6]
        keyword_str = " ".join(top_tokens) if top_tokens else mut_type
        return f"(draft) {mut_type}: {keyword_str}"
