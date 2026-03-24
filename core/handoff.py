"""Structured handoff artifacts for agent-to-agent transfers.

Replaces scalar handoff_fidelity with field-level completeness and
accuracy scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class HandoffArtifact:
    """Structured artifact passed between agents during handoff.

    Each field captures a distinct aspect of the handoff context,
    enabling field-level quality measurement.
    """
    goal: str = ""
    constraints: list[str] = field(default_factory=list)
    known_facts: dict[str, Any] = field(default_factory=dict)
    unresolved_questions: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    expected_deliverable: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    _SCORED_FIELDS = (
        "goal", "constraints", "known_facts", "unresolved_questions",
        "allowed_tools", "expected_deliverable", "evidence_refs",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "constraints": self.constraints,
            "known_facts": self.known_facts,
            "unresolved_questions": self.unresolved_questions,
            "allowed_tools": self.allowed_tools,
            "expected_deliverable": self.expected_deliverable,
            "evidence_refs": self.evidence_refs,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HandoffArtifact":
        return cls(
            goal=d.get("goal", ""),
            constraints=d.get("constraints", []),
            known_facts=d.get("known_facts", {}),
            unresolved_questions=d.get("unresolved_questions", []),
            allowed_tools=d.get("allowed_tools", []),
            expected_deliverable=d.get("expected_deliverable", ""),
            evidence_refs=d.get("evidence_refs", []),
            metadata=d.get("metadata", {}),
        )

    @property
    def completeness(self) -> float:
        """Fraction of scored fields that are non-empty."""
        filled = 0
        for f in self._SCORED_FIELDS:
            val = getattr(self, f)
            if val:  # truthy: non-empty string, non-empty list/dict
                filled += 1
        return filled / len(self._SCORED_FIELDS)


class HandoffComparator:
    """Compare actual vs expected handoff artifacts field by field."""

    @staticmethod
    def compare(expected: HandoffArtifact, actual: HandoffArtifact) -> dict[str, Any]:
        """Return per-field scores and an aggregate handoff quality score.

        Returns:
            dict with keys:
              - field_scores: dict[str, float]  (0-1 per field)
              - aggregate_score: float           (mean of field scores)
              - missing_fields: list[str]        (fields empty in actual but present in expected)
              - extra_fields: list[str]          (fields present in actual but not expected)
        """
        field_scores: dict[str, float] = {}
        missing: list[str] = []
        extra: list[str] = []

        for f in HandoffArtifact._SCORED_FIELDS:
            exp_val = getattr(expected, f)
            act_val = getattr(actual, f)
            score = HandoffComparator._field_score(f, exp_val, act_val)
            field_scores[f] = score
            if exp_val and not act_val:
                missing.append(f)
            elif act_val and not exp_val:
                extra.append(f)

        scores = list(field_scores.values())
        aggregate = sum(scores) / len(scores) if scores else 0.0

        return {
            "field_scores": field_scores,
            "aggregate_score": aggregate,
            "missing_fields": missing,
            "extra_fields": extra,
        }

    @staticmethod
    def _field_score(field_name: str, expected: Any, actual: Any) -> float:
        """Score a single field comparison."""
        if not expected and not actual:
            return 1.0  # both empty is fine
        if not expected:
            return 1.0  # extra info is not penalised
        if not actual:
            return 0.0  # missing expected info is bad

        if isinstance(expected, str) and isinstance(actual, str):
            return 1.0 if expected.strip().lower() == actual.strip().lower() else _string_overlap(expected, actual)

        if isinstance(expected, list) and isinstance(actual, list):
            if not expected:
                return 1.0
            exp_set = set(str(x).lower() for x in expected)
            act_set = set(str(x).lower() for x in actual)
            if not exp_set:
                return 1.0
            return len(exp_set & act_set) / len(exp_set)

        if isinstance(expected, dict) and isinstance(actual, dict):
            if not expected:
                return 1.0
            matching = sum(1 for k in expected if k in actual and actual[k] == expected[k])
            return matching / len(expected)

        # fallback: exact match
        return 1.0 if expected == actual else 0.0


def _string_overlap(a: str, b: str) -> float:
    """Simple word-overlap similarity between two strings."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a:
        return 1.0
    return len(words_a & words_b) / len(words_a)
