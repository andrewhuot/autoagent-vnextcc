"""Ranked opportunity queue for optimization — clusters failures into actionable items."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class FailureFamily(str, Enum):
    """Broad categories of agent failure modes."""

    tool_error = "tool_error"
    routing_failure = "routing_failure"
    safety_violation = "safety_violation"
    latency_spike = "latency_spike"
    quality_degradation = "quality_degradation"
    cost_spike = "cost_spike"
    hallucination = "hallucination"
    transfer_loop = "transfer_loop"


@dataclass
class OptimizationOpportunity:
    """A single ranked opportunity for the optimizer to address."""

    opportunity_id: str
    created_at: float
    cluster_id: str
    failure_family: str
    affected_agent_path: str
    affected_surface_candidates: list[str]
    severity: float  # 0-1, higher = worse
    prevalence: float  # 0-1, fraction of recent traces affected
    recency: float  # 0-1, how recent (1.0 = just happened)
    business_impact: float  # 0-1, estimated user impact
    sample_trace_ids: list[str]
    recommended_operator_families: list[str]
    priority_score: float  # severity*0.3 + prevalence*0.3 + recency*0.2 + business_impact*0.2
    status: str = "open"  # "open", "in_progress", "resolved", "wont_fix"
    resolution_experiment_id: str | None = None


_VALID_STATUSES = {"open", "in_progress", "resolved", "wont_fix"}


class OpportunityQueue:
    """Persistent SQLite-backed priority queue for optimization opportunities."""

    def __init__(self, db_path: str = "opportunities.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Create the opportunities table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS opportunities (
                    opportunity_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    cluster_id TEXT NOT NULL DEFAULT '',
                    failure_family TEXT NOT NULL,
                    affected_agent_path TEXT NOT NULL DEFAULT '',
                    affected_surface_candidates TEXT NOT NULL DEFAULT '[]',
                    severity REAL NOT NULL DEFAULT 0.0,
                    prevalence REAL NOT NULL DEFAULT 0.0,
                    recency REAL NOT NULL DEFAULT 0.0,
                    business_impact REAL NOT NULL DEFAULT 0.0,
                    sample_trace_ids TEXT NOT NULL DEFAULT '[]',
                    recommended_operator_families TEXT NOT NULL DEFAULT '[]',
                    priority_score REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'open',
                    resolution_experiment_id TEXT
                )
                """
            )
            conn.commit()

    def push(self, opportunity: OptimizationOpportunity) -> None:
        """Insert or replace an optimization opportunity."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO opportunities
                    (opportunity_id, created_at, cluster_id, failure_family,
                     affected_agent_path, affected_surface_candidates, severity,
                     prevalence, recency, business_impact, sample_trace_ids,
                     recommended_operator_families, priority_score, status,
                     resolution_experiment_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opportunity.opportunity_id,
                    opportunity.created_at,
                    opportunity.cluster_id,
                    opportunity.failure_family,
                    opportunity.affected_agent_path,
                    json.dumps(opportunity.affected_surface_candidates),
                    opportunity.severity,
                    opportunity.prevalence,
                    opportunity.recency,
                    opportunity.business_impact,
                    json.dumps(opportunity.sample_trace_ids),
                    json.dumps(opportunity.recommended_operator_families),
                    opportunity.priority_score,
                    opportunity.status,
                    opportunity.resolution_experiment_id,
                ),
            )
            conn.commit()

    def pop_top(self, n: int = 1) -> list[OptimizationOpportunity]:
        """Return top N open opportunities by priority_score (highest first)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT opportunity_id, created_at, cluster_id, failure_family,
                       affected_agent_path, affected_surface_candidates, severity,
                       prevalence, recency, business_impact, sample_trace_ids,
                       recommended_operator_families, priority_score, status,
                       resolution_experiment_id
                FROM opportunities
                WHERE status = 'open'
                ORDER BY priority_score DESC
                LIMIT ?
                """,
                (n,),
            ).fetchall()
            return [self._row_to_opportunity(row) for row in rows]

    def list_open(self, limit: int = 50) -> list[OptimizationOpportunity]:
        """List open opportunities sorted by priority_score descending."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT opportunity_id, created_at, cluster_id, failure_family,
                       affected_agent_path, affected_surface_candidates, severity,
                       prevalence, recency, business_impact, sample_trace_ids,
                       recommended_operator_families, priority_score, status,
                       resolution_experiment_id
                FROM opportunities
                WHERE status = 'open'
                ORDER BY priority_score DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._row_to_opportunity(row) for row in rows]

    def list_all(self, limit: int = 100) -> list[OptimizationOpportunity]:
        """List all opportunities sorted by priority_score descending."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT opportunity_id, created_at, cluster_id, failure_family,
                       affected_agent_path, affected_surface_candidates, severity,
                       prevalence, recency, business_impact, sample_trace_ids,
                       recommended_operator_families, priority_score, status,
                       resolution_experiment_id
                FROM opportunities
                ORDER BY priority_score DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [self._row_to_opportunity(row) for row in rows]

    def update_status(
        self,
        opportunity_id: str,
        status: str,
        resolution_experiment_id: str | None = None,
    ) -> None:
        """Update the status (and optionally link a resolution experiment) of an opportunity."""
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {_VALID_STATUSES}"
            )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE opportunities
                SET status = ?, resolution_experiment_id = COALESCE(?, resolution_experiment_id)
                WHERE opportunity_id = ?
                """,
                (status, resolution_experiment_id, opportunity_id),
            )
            conn.commit()

    def count_open(self) -> int:
        """Return the number of open opportunities."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM opportunities WHERE status = 'open'"
            ).fetchone()
            return row[0] if row else 0

    def get(self, opportunity_id: str) -> OptimizationOpportunity | None:
        """Retrieve a single opportunity by ID, or None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT opportunity_id, created_at, cluster_id, failure_family,
                       affected_agent_path, affected_surface_candidates, severity,
                       prevalence, recency, business_impact, sample_trace_ids,
                       recommended_operator_families, priority_score, status,
                       resolution_experiment_id
                FROM opportunities
                WHERE opportunity_id = ?
                """,
                (opportunity_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_opportunity(row)

    @staticmethod
    def _row_to_opportunity(row: tuple) -> OptimizationOpportunity:
        """Convert a database row tuple to an OptimizationOpportunity."""
        return OptimizationOpportunity(
            opportunity_id=row[0],
            created_at=row[1],
            cluster_id=row[2],
            failure_family=row[3],
            affected_agent_path=row[4],
            affected_surface_candidates=json.loads(row[5]),
            severity=row[6],
            prevalence=row[7],
            recency=row[8],
            business_impact=row[9],
            sample_trace_ids=json.loads(row[10]),
            recommended_operator_families=json.loads(row[11]),
            priority_score=row[12],
            status=row[13],
            resolution_experiment_id=row[14],
        )


# ── Mapping from FailureClassifier bucket names to FailureFamily + recommended operators ──

_BUCKET_TO_FAMILY: dict[str, FailureFamily] = {
    "tool_failure": FailureFamily.tool_error,
    "routing_error": FailureFamily.routing_failure,
    "safety_violation": FailureFamily.safety_violation,
    "timeout": FailureFamily.latency_spike,
    "unhelpful_response": FailureFamily.quality_degradation,
    "hallucination": FailureFamily.hallucination,
}

_BUCKET_TO_OPERATORS: dict[str, list[str]] = {
    "tool_failure": ["tool_description_edit"],
    "routing_error": ["routing_edit"],
    "safety_violation": ["instruction_rewrite", "callback_patch"],
    "timeout": ["generation_settings", "model_swap"],
    "unhelpful_response": ["instruction_rewrite", "few_shot_edit"],
    "hallucination": ["instruction_rewrite", "context_caching"],
}

_BUCKET_TO_SURFACES: dict[str, list[str]] = {
    "tool_failure": ["tool_definitions"],
    "routing_error": ["routing_config"],
    "safety_violation": ["system_instructions", "callbacks"],
    "timeout": ["generation_settings", "model_config"],
    "unhelpful_response": ["system_instructions", "few_shot_examples"],
    "hallucination": ["system_instructions", "context_config"],
}

# Severity baseline per bucket — higher for safety/hallucination issues.
_BUCKET_BASE_SEVERITY: dict[str, float] = {
    "tool_failure": 0.5,
    "routing_error": 0.4,
    "safety_violation": 0.9,
    "timeout": 0.3,
    "unhelpful_response": 0.5,
    "hallucination": 0.8,
}


class FailureClusterer:
    """Clusters FailureClassifier output into ranked OptimizationOpportunity items."""

    def __init__(self) -> None:
        pass

    def cluster(
        self,
        failure_records: list,
        failure_buckets: dict[str, int],
    ) -> list[OptimizationOpportunity]:
        """Convert failure classification buckets into ranked optimization opportunities.

        Args:
            failure_records: Raw conversation records (ConversationRecord instances)
                that were classified. Used to extract sample trace IDs and
                affected agent paths.
            failure_buckets: Output of FailureClassifier.classify_batch — maps
                bucket name (e.g. "tool_failure") to count of affected traces.

        Returns:
            List of OptimizationOpportunity sorted by priority_score descending.
        """
        total_records = max(len(failure_records), 1)
        now = time.time()
        opportunities: list[OptimizationOpportunity] = []

        for bucket_name, count in failure_buckets.items():
            if count <= 0:
                continue
            if bucket_name not in _BUCKET_TO_FAMILY:
                continue

            family = _BUCKET_TO_FAMILY[bucket_name]
            prevalence = min(count / total_records, 1.0)
            severity = min(
                _BUCKET_BASE_SEVERITY.get(bucket_name, 0.5)
                + prevalence * 0.2,  # boost severity when prevalent
                1.0,
            )
            # Business impact scales with severity and prevalence.
            business_impact = min(severity * prevalence + 0.1, 1.0)

            # Extract sample trace IDs from matching records (up to 5).
            sample_ids: list[str] = []
            affected_agent = ""
            for record in failure_records:
                record_id = getattr(record, "conversation_id", "") or getattr(
                    record, "id", ""
                )
                if len(sample_ids) < 5 and record_id:
                    sample_ids.append(str(record_id))
                if not affected_agent:
                    affected_agent = getattr(record, "specialist_used", "") or ""

            # Recency: 1.0 because we're processing current batch.
            recency = 1.0

            priority_score = (
                severity * 0.3
                + prevalence * 0.3
                + recency * 0.2
                + business_impact * 0.2
            )

            opportunity = OptimizationOpportunity(
                opportunity_id=uuid.uuid4().hex[:16],
                created_at=now,
                cluster_id=f"{bucket_name}_{int(now)}",
                failure_family=family.value,
                affected_agent_path=affected_agent,
                affected_surface_candidates=_BUCKET_TO_SURFACES.get(
                    bucket_name, []
                ),
                severity=round(severity, 4),
                prevalence=round(prevalence, 4),
                recency=recency,
                business_impact=round(business_impact, 4),
                sample_trace_ids=sample_ids,
                recommended_operator_families=_BUCKET_TO_OPERATORS.get(
                    bucket_name, []
                ),
                priority_score=round(priority_score, 4),
                status="open",
                resolution_experiment_id=None,
            )
            opportunities.append(opportunity)

        # Sort by priority_score descending.
        opportunities.sort(key=lambda o: o.priority_score, reverse=True)
        return opportunities
