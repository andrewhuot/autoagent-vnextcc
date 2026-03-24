"""Constrained Pareto Archive for multi-objective optimization.

Maintains separate feasible and infeasible candidate sets.
Provides Pareto dominance checks and knee-point selection.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.types import ArchiveEntry, ArchiveRole


class ObjectiveDirection(str, Enum):
    """Direction for an optimization objective."""

    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


@dataclass
class ParetoCandidate:
    """A candidate in the Pareto archive."""
    candidate_id: str
    objective_vector: list[float]  # from DimensionScores.to_objective_vector()
    constraints_passed: bool
    constraint_violations: list[str]
    config_hash: str
    experiment_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    dominated: bool = False

    def __post_init__(self) -> None:
        if self.created_at == 0.0:
            self.created_at = time.time()


class ParetoArchive:
    """Constrained Pareto Archive (CPA).

    Separates feasible (constraints passed) and infeasible candidates.
    Maintains non-dominated frontier for feasible set.
    Provides knee-point auto-selection for deployment recommendation.
    """

    def __init__(self, max_archive_size: int = 100) -> None:
        self._feasible: list[ParetoCandidate] = []
        self._infeasible: list[ParetoCandidate] = []
        self.max_archive_size = max_archive_size

    def add(self, candidate: ParetoCandidate) -> bool:
        """Add candidate, return True if it's on the Pareto front."""
        if not candidate.constraints_passed:
            self._infeasible.append(candidate)
            self._enforce_size_limit(self._infeasible)
            return False

        self._feasible.append(candidate)
        self._update_frontier()
        self._enforce_size_limit(self._feasible)
        return not candidate.dominated

    def get_frontier(self) -> list[ParetoCandidate]:
        """Return non-dominated feasible candidates."""
        return [c for c in self._feasible if not c.dominated]

    def get_infeasible(self) -> list[ParetoCandidate]:
        """Return infeasible candidates (for learning/diagnostics)."""
        return list(self._infeasible)

    def recommend(self) -> ParetoCandidate | None:
        """Auto-select knee point from Pareto front for deployment.

        Uses maximin approach: normalize each objective to [0,1] on the frontier,
        then find the candidate that maximizes its minimum normalized score.
        This selects the most balanced candidate.
        """
        frontier = self.get_frontier()
        if not frontier:
            return None
        if len(frontier) == 1:
            return frontier[0]

        n_objectives = len(frontier[0].objective_vector)

        # Compute min/max per objective across frontier
        mins = [float("inf")] * n_objectives
        maxs = [float("-inf")] * n_objectives
        for c in frontier:
            for i, v in enumerate(c.objective_vector):
                mins[i] = min(mins[i], v)
                maxs[i] = max(maxs[i], v)

        # Normalize and find maximin candidate
        best_candidate = frontier[0]
        best_min_score = float("-inf")

        for c in frontier:
            min_score = float("inf")
            for i, v in enumerate(c.objective_vector):
                span = maxs[i] - mins[i]
                if span > 0:
                    normalized = (v - mins[i]) / span
                else:
                    normalized = 1.0  # all same -> perfect on this dim
                min_score = min(min_score, normalized)

            if min_score > best_min_score:
                best_min_score = min_score
                best_candidate = c

        return best_candidate

    @staticmethod
    def dominates(a: list[float], b: list[float]) -> bool:
        """True if a Pareto-dominates b (all >= and at least one >)."""
        at_least_one_better = False
        for ai, bi in zip(a, b):
            if ai < bi:
                return False
            if ai > bi:
                at_least_one_better = True
        return at_least_one_better

    def _update_frontier(self) -> None:
        """Recompute non-dominated set among feasible candidates."""
        for c in self._feasible:
            c.dominated = False

        n = len(self._feasible)
        for i in range(n):
            if self._feasible[i].dominated:
                continue
            for j in range(n):
                if i == j or self._feasible[j].dominated:
                    continue
                if self.dominates(
                    self._feasible[j].objective_vector,
                    self._feasible[i].objective_vector,
                ):
                    self._feasible[i].dominated = True
                    break

    def _enforce_size_limit(self, archive: list[ParetoCandidate]) -> None:
        """Remove oldest dominated candidates if archive exceeds max size."""
        if len(archive) <= self.max_archive_size:
            return
        # Remove dominated candidates first (oldest first)
        dominated = [c for c in archive if c.dominated]
        dominated.sort(key=lambda c: c.created_at)
        to_remove = len(archive) - self.max_archive_size
        removed = 0
        for c in dominated:
            if removed >= to_remove:
                break
            archive.remove(c)
            removed += 1
        # If still over limit, remove oldest non-dominated
        if len(archive) > self.max_archive_size:
            archive.sort(key=lambda c: c.created_at)
            del archive[: len(archive) - self.max_archive_size]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API/frontend."""
        frontier = self.get_frontier()
        recommendation = self.recommend()
        return {
            "frontier_size": len(frontier),
            "feasible_total": len(self._feasible),
            "infeasible_total": len(self._infeasible),
            "frontier": [
                {
                    "candidate_id": c.candidate_id,
                    "objective_vector": c.objective_vector,
                    "config_hash": c.config_hash,
                    "experiment_id": c.experiment_id,
                    "metadata": c.metadata,
                }
                for c in frontier
            ],
            "recommended_id": recommendation.candidate_id if recommendation else None,
        }

    def frontier_movement(self, previous_frontier: list[ParetoCandidate]) -> dict[str, Any]:
        """Compare current frontier to previous for observability."""
        current = self.get_frontier()
        current_ids = {c.candidate_id for c in current}
        previous_ids = {c.candidate_id for c in previous_frontier}

        added = current_ids - previous_ids
        removed = previous_ids - current_ids
        retained = current_ids & previous_ids

        # Compute hypervolume proxy: sum of objective vectors L2 norms
        def _avg_l2(candidates: list[ParetoCandidate]) -> float:
            if not candidates:
                return 0.0
            total = 0.0
            for c in candidates:
                total += math.sqrt(sum(v * v for v in c.objective_vector))
            return total / len(candidates)

        return {
            "added": sorted(added),
            "removed": sorted(removed),
            "retained": sorted(retained),
            "frontier_size_before": len(previous_frontier),
            "frontier_size_after": len(current),
            "avg_l2_before": round(_avg_l2(previous_frontier), 4),
            "avg_l2_after": round(_avg_l2(current), 4),
        }


# ---------------------------------------------------------------------------
# Constrained Pareto Archive (direction-aware, used by HSO / loop)
# ---------------------------------------------------------------------------


class ConstrainedParetoArchive:
    """Maintain feasible and infeasible candidates with Pareto-front extraction.

    Feasibility and preference are separate concerns.  A high-utility
    candidate that violates hard constraints still belongs in learning history
    but cannot be promoted for deployment.
    """

    def __init__(self, objective_directions: dict[str, ObjectiveDirection]) -> None:
        if not objective_directions:
            raise ValueError("objective_directions must contain at least one objective")
        self.objective_directions = dict(objective_directions)
        self.feasible_candidates: list[dict[str, Any]] = []
        self.infeasible_candidates: list[dict[str, Any]] = []

    def add_candidate(
        self,
        *,
        candidate_id: str,
        objectives: dict[str, float],
        constraints_passed: bool,
        constraint_violations: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert a candidate and return its stored representation."""
        missing = [k for k in self.objective_directions if k not in objectives]
        if missing:
            raise ValueError(f"Missing objective values for: {', '.join(missing)}")

        candidate = {
            "candidate_id": candidate_id,
            "objectives": {k: float(v) for k, v in objectives.items()},
            "constraints_passed": constraints_passed,
            "constraint_violations": list(constraint_violations or []),
            "metadata": dict(metadata or {}),
        }
        if constraints_passed:
            self.feasible_candidates.append(candidate)
        else:
            self.infeasible_candidates.append(candidate)
        return candidate

    def dominates(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        """Return whether ``left`` Pareto-dominates ``right``."""
        better_or_equal_all = True
        strictly_better_any = False

        for objective, direction in self.objective_directions.items():
            a = left["objectives"][objective]
            b = right["objectives"][objective]

            if direction == ObjectiveDirection.MAXIMIZE:
                if a < b:
                    better_or_equal_all = False
                    break
                if a > b:
                    strictly_better_any = True
            else:
                if a > b:
                    better_or_equal_all = False
                    break
                if a < b:
                    strictly_better_any = True

        return better_or_equal_all and strictly_better_any

    def frontier(self) -> list[dict[str, Any]]:
        """Return the feasible non-dominated candidate set."""
        non_dominated: list[dict[str, Any]] = []
        for c in self.feasible_candidates:
            dominated = False
            for other in self.feasible_candidates:
                if other["candidate_id"] == c["candidate_id"]:
                    continue
                if self.dominates(other, c):
                    dominated = True
                    break
            if not dominated:
                non_dominated.append(c)
        return non_dominated

    def recommend_knee_point(self) -> dict[str, Any] | None:
        """Recommend one balanced candidate from the feasible frontier."""
        front = self.frontier()
        if not front:
            return None
        if len(front) == 1:
            return front[0]

        normalized = self._normalize_frontier(front)
        best_id = min(
            normalized,
            key=lambda cid: self._distance_to_ideal(normalized[cid]),
        )
        for c in front:
            if c["candidate_id"] == best_id:
                return c
        return front[0]

    def as_dict(self) -> dict[str, Any]:
        """Serialize archive state for API/front-end views."""
        rec = self.recommend_knee_point()
        return {
            "objective_directions": {k: v.value for k, v in self.objective_directions.items()},
            "feasible_count": len(self.feasible_candidates),
            "infeasible_count": len(self.infeasible_candidates),
            "frontier": self.frontier(),
            "recommended_candidate_id": rec["candidate_id"] if rec else None,
            "infeasible": list(self.infeasible_candidates),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_frontier(
        self, front: list[dict[str, Any]]
    ) -> dict[str, dict[str, float]]:
        """Normalize frontier objective values into utility scores in [0, 1]."""
        by_obj: dict[str, list[float]] = {n: [] for n in self.objective_directions}
        for c in front:
            for obj, val in c["objectives"].items():
                if obj in by_obj:
                    by_obj[obj].append(val)

        mins = {n: min(vs) if vs else 0.0 for n, vs in by_obj.items()}
        maxs = {n: max(vs) if vs else 0.0 for n, vs in by_obj.items()}

        normalized: dict[str, dict[str, float]] = {}
        for c in front:
            utility: dict[str, float] = {}
            for obj, direction in self.objective_directions.items():
                raw = c["objectives"][obj]
                lo, hi = mins[obj], maxs[obj]
                if math.isclose(hi, lo):
                    scaled = 1.0
                else:
                    scaled = (raw - lo) / (hi - lo)
                if direction == ObjectiveDirection.MINIMIZE:
                    scaled = 1.0 - scaled
                utility[obj] = max(0.0, min(1.0, scaled))
            normalized[c["candidate_id"]] = utility
        return normalized

    @staticmethod
    def _distance_to_ideal(utility: dict[str, float]) -> float:
        """Compute distance from ideal utility point (all 1.0)."""
        if not utility:
            return float("inf")
        return math.sqrt(sum((1.0 - v) ** 2 for v in utility.values()))


# ---------------------------------------------------------------------------
# Elite Pareto Archive (role-aware extension)
# ---------------------------------------------------------------------------


class EliteParetoArchive(ConstrainedParetoArchive):
    """Pareto archive with named roles for non-dominated candidates.

    Extends ConstrainedParetoArchive to assign semantic roles (quality_leader,
    cost_leader, etc.) to frontier members and support branching from any
    non-dominated entry.
    """

    def __init__(
        self,
        objectives: dict[str, ObjectiveDirection],
        constraints: list[str] | None = None,
        directions: dict[str, ObjectiveDirection] | None = None,
    ) -> None:
        super().__init__(objective_directions=directions or objectives)
        self._constraints = list(constraints or [])
        self.entries: dict[str, ArchiveEntry] = {}

    def assign_roles(self) -> None:
        """Assign an ArchiveRole to each non-dominated candidate.

        Role assignment priority:
        - quality_leader: best on first objective (task success)
        - cost_leader: best on cost dimension (lowest)
        - latency_leader: best on latency dimension (lowest)
        - safety_leader: best on safety dimension (highest)
        - incumbent: currently deployed config (marked via metadata)
        - cluster_specialist: any other non-dominated candidate
        """
        front = self.frontier()
        if not front:
            return

        obj_names = list(self.objective_directions.keys())

        # Track which candidate_ids have been assigned a leader role
        assigned: set[str] = set()

        # Quality leader: best on first objective
        if obj_names:
            first_obj = obj_names[0]
            first_dir = self.objective_directions[first_obj]
            best = max(front, key=lambda c: c["objectives"][first_obj])
            if first_dir == ObjectiveDirection.MINIMIZE:
                best = min(front, key=lambda c: c["objectives"][first_obj])
            cid = best["candidate_id"]
            if cid in self.entries:
                self.entries[cid].role = ArchiveRole.quality_leader
                assigned.add(cid)

        # Cost leader: lowest cost
        if "cost" in self.objective_directions:
            best = min(front, key=lambda c: c["objectives"]["cost"])
            cid = best["candidate_id"]
            if cid in self.entries and cid not in assigned:
                self.entries[cid].role = ArchiveRole.cost_leader
                assigned.add(cid)

        # Latency leader: lowest latency
        if "latency" in self.objective_directions:
            best = min(front, key=lambda c: c["objectives"]["latency"])
            cid = best["candidate_id"]
            if cid in self.entries and cid not in assigned:
                self.entries[cid].role = ArchiveRole.latency_leader
                assigned.add(cid)

        # Safety leader: highest safety
        if "safety" in self.objective_directions:
            best = max(front, key=lambda c: c["objectives"]["safety"])
            cid = best["candidate_id"]
            if cid in self.entries and cid not in assigned:
                self.entries[cid].role = ArchiveRole.safety_leader
                assigned.add(cid)

        # Incumbent: marked via metadata
        for c in front:
            cid = c["candidate_id"]
            if cid in self.entries and cid not in assigned:
                if self.entries[cid].metadata.get("is_incumbent", False):
                    self.entries[cid].role = ArchiveRole.incumbent
                    assigned.add(cid)

        # Cluster specialist: all remaining non-dominated entries
        for c in front:
            cid = c["candidate_id"]
            if cid in self.entries and cid not in assigned:
                self.entries[cid].role = ArchiveRole.cluster_specialist

    def get_by_role(self, role: ArchiveRole) -> list[ArchiveEntry]:
        """Return all entries with the given role."""
        return [e for e in self.entries.values() if e.role == role]

    def add_entry(self, entry: ArchiveEntry) -> bool:
        """Add an ArchiveEntry to the archive if it is not dominated.

        Returns True if the entry was added to the feasible set and is
        non-dominated.
        """
        objectives = {
            k: v for k, v in zip(self.objective_directions.keys(), entry.objective_vector)
        }
        candidate = self.add_candidate(
            candidate_id=entry.entry_id,
            objectives=objectives,
            constraints_passed=True,
            metadata=entry.metadata,
        )
        self.entries[entry.entry_id] = entry

        # Check if entry is non-dominated
        front = self.frontier()
        is_on_front = any(c["candidate_id"] == entry.entry_id for c in front)

        if is_on_front:
            self.assign_roles()

        return is_on_front

    def get_branch_candidates(self) -> list[ArchiveEntry]:
        """Return all non-dominated entries that new candidates can branch from.

        Any non-dominated entry is a valid branch point, not just the incumbent.
        """
        front = self.frontier()
        front_ids = {c["candidate_id"] for c in front}
        return [
            entry for eid, entry in self.entries.items()
            if eid in front_ids
        ]

    def to_dict(self) -> dict:
        """Serialize archive state including entries and roles."""
        base = self.as_dict()
        base["entries"] = {
            eid: entry.to_dict() for eid, entry in self.entries.items()
        }
        base["roles"] = {
            role.value: [e.entry_id for e in self.get_by_role(role)]
            for role in ArchiveRole
        }
        return base
