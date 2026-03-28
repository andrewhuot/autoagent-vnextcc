"""Domain-specific judge routing — map evaluation types to the best judge.

Maintains a registry of judges per domain and routes incoming evaluation
requests to the most accurate judge available.  Accuracy scores can be
updated from :class:`~judges.governance.JudgeAccuracyReport` data so routing
improves over time as judges are calibrated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class JudgeDomain(str, Enum):
    """Evaluation domains that judges can be specialised for."""

    SAFETY = "SAFETY"
    QUALITY = "QUALITY"
    FACTUALITY = "FACTUALITY"
    EMPATHY = "EMPATHY"
    LATENCY = "LATENCY"
    FORMAT = "FORMAT"


# Mapping from free-text eval_type strings to canonical domains.
# Lower-cased partial matches are checked in order.
_EVAL_TYPE_DOMAIN_MAP: list[tuple[str, JudgeDomain]] = [
    ("safe", JudgeDomain.SAFETY),
    ("harm", JudgeDomain.SAFETY),
    ("toxic", JudgeDomain.SAFETY),
    ("quality", JudgeDomain.QUALITY),
    ("relevance", JudgeDomain.QUALITY),
    ("coherence", JudgeDomain.QUALITY),
    ("fact", JudgeDomain.FACTUALITY),
    ("ground", JudgeDomain.FACTUALITY),
    ("accurate", JudgeDomain.FACTUALITY),
    ("empathy", JudgeDomain.EMPATHY),
    ("tone", JudgeDomain.EMPATHY),
    ("sentiment", JudgeDomain.EMPATHY),
    ("latency", JudgeDomain.LATENCY),
    ("speed", JudgeDomain.LATENCY),
    ("perf", JudgeDomain.LATENCY),
    ("format", JudgeDomain.FORMAT),
    ("schema", JudgeDomain.FORMAT),
    ("structure", JudgeDomain.FORMAT),
]


@dataclass
class _JudgeEntry:
    """Internal registry entry for a judge in a domain."""

    judge_id: str
    domain: JudgeDomain
    accuracy: float = 0.0


class JudgeRouter:
    """Route evaluation requests to the most accurate registered judge.

    Judges are registered per domain with an initial accuracy score.  The
    router always selects the judge with the highest accuracy for the
    requested domain.  When no judges are registered for a domain, the
    first globally registered judge is used as a fallback.

    Example::

        router = JudgeRouter()
        router.register_judge(JudgeDomain.SAFETY, "safety_judge_v2", accuracy=0.91)
        router.register_judge(JudgeDomain.SAFETY, "safety_judge_v1", accuracy=0.85)
        judge_id = router.route("safety_check")  # -> "safety_judge_v2"
    """

    def __init__(self) -> None:
        # domain -> list of entries, ordered by insertion
        self._registry: dict[JudgeDomain, list[_JudgeEntry]] = {
            d: [] for d in JudgeDomain
        }

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_judge(
        self,
        domain: JudgeDomain,
        judge_id: str,
        accuracy: float = 0.0,
    ) -> None:
        """Register a judge for a domain with an initial accuracy score.

        If a judge with the same *judge_id* already exists in the domain its
        accuracy is updated rather than creating a duplicate entry.

        Args:
            domain: The :class:`JudgeDomain` this judge is specialised for.
            judge_id: Unique identifier of the judge.
            accuracy: Initial accuracy score in [0, 1] (default 0.0).
        """
        for entry in self._registry[domain]:
            if entry.judge_id == judge_id:
                entry.accuracy = accuracy
                return
        self._registry[domain].append(
            _JudgeEntry(judge_id=judge_id, domain=domain, accuracy=accuracy)
        )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def route(self, eval_type: str) -> str:
        """Return the best judge_id for the given *eval_type* string.

        The eval_type is mapped to a :class:`JudgeDomain` via keyword
        matching.  Within that domain, the judge with the highest accuracy
        is selected.  Falls back to a global best when no domain match
        exists or the domain has no registered judges.

        Args:
            eval_type: Free-text evaluation type (e.g. ``"safety_check"``,
                ``"factuality"``, ``"response_quality"``).

        Returns:
            The ``judge_id`` of the selected judge.

        Raises:
            ValueError: If no judges are registered at all.
        """
        domain = self._infer_domain(eval_type)
        candidates = self._registry.get(domain, [])

        if candidates:
            return max(candidates, key=lambda e: e.accuracy).judge_id

        # Fallback: best judge across all domains
        all_entries: list[_JudgeEntry] = [
            e for entries in self._registry.values() for e in entries
        ]
        if not all_entries:
            raise ValueError("No judges registered. Call register_judge() first.")
        return max(all_entries, key=lambda e: e.accuracy).judge_id

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_domain_judges(self, domain: JudgeDomain) -> list[dict[str, Any]]:
        """Return all judges registered for *domain*, sorted by accuracy desc.

        Args:
            domain: The domain to query.

        Returns:
            List of dicts with keys ``judge_id``, ``domain``, ``accuracy``.
        """
        entries = sorted(
            self._registry.get(domain, []),
            key=lambda e: e.accuracy,
            reverse=True,
        )
        return [
            {
                "judge_id": e.judge_id,
                "domain": e.domain.value,
                "accuracy": e.accuracy,
            }
            for e in entries
        ]

    # ------------------------------------------------------------------
    # Optimisation
    # ------------------------------------------------------------------

    def optimize_routing(self, accuracy_reports: list[dict]) -> None:
        """Update routing accuracy from a list of accuracy report dicts.

        Accepts dicts compatible with
        :meth:`~judges.governance.JudgeAccuracyReport.to_dict`.  For each
        report the corresponding judge's accuracy is updated across all
        domains it is registered in, or it is registered in QUALITY (default)
        if not yet present.

        Args:
            accuracy_reports: List of accuracy report dicts, each with at
                least ``judge_id`` and ``accuracy`` keys.
        """
        for report in accuracy_reports:
            judge_id = report.get("judge_id", "")
            accuracy = float(report.get("accuracy", 0.0))
            if not judge_id:
                continue

            updated = False
            for domain, entries in self._registry.items():
                for entry in entries:
                    if entry.judge_id == judge_id:
                        entry.accuracy = accuracy
                        updated = True

            if not updated:
                # Register under QUALITY as a sensible default
                self.register_judge(JudgeDomain.QUALITY, judge_id, accuracy=accuracy)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_domain(eval_type: str) -> JudgeDomain:
        """Map a free-text eval_type to the best matching :class:`JudgeDomain`."""
        lowered = eval_type.lower()
        for keyword, domain in _EVAL_TYPE_DOMAIN_MAP:
            if keyword in lowered:
                return domain
        # Default domain when no keyword matches
        return JudgeDomain.QUALITY
