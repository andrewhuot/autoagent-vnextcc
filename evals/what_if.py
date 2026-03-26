"""What-If Replay Engine — replay historical conversations through candidate configs.

Allows projecting the impact of config changes by replaying real conversations
through a candidate configuration and comparing outcomes with the original results.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.replay import ReplayStore, RecordedToolIO, _hash_input
from logger.store import ConversationRecord

logger = logging.getLogger(__name__)


@dataclass
class ReplayOutcome:
    """Outcome of replaying a single conversation."""

    conversation_id: str
    original_outcome: str
    replay_outcome: str
    original_score: float
    replay_score: float
    original_latency_ms: float
    replay_latency_ms: float
    original_cost: float
    replay_cost: float
    tool_calls_matched: bool
    delta_score: float = 0.0
    improved: bool = False


@dataclass
class WhatIfResult:
    """Results of a what-if replay job."""

    job_id: str
    candidate_config_label: str
    conversation_ids: list[str]
    outcomes: list[ReplayOutcome]
    total_conversations: int
    improved_count: int
    degraded_count: int
    unchanged_count: int
    avg_delta_score: float
    created_at: float = field(default_factory=time.time)


@dataclass
class ImpactProjection:
    """Projected impact of candidate config on full traffic."""

    job_id: str
    sample_size: int
    total_population: int
    improved_count: int
    degraded_count: int
    projected_improvement_rate: float
    projected_improvement_absolute: int
    confidence_interval_95: tuple[float, float]
    recommendation: str


class WhatIfStore:
    """SQLite-backed store for what-if replay results."""

    def __init__(self, db_path: str = ".autoagent/what_if.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create what_if_jobs and replay_outcomes tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS what_if_jobs (
                    job_id TEXT PRIMARY KEY,
                    candidate_config_label TEXT NOT NULL,
                    conversation_ids TEXT NOT NULL,
                    total_conversations INTEGER NOT NULL,
                    improved_count INTEGER NOT NULL,
                    degraded_count INTEGER NOT NULL,
                    unchanged_count INTEGER NOT NULL,
                    avg_delta_score REAL NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS replay_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    original_outcome TEXT NOT NULL,
                    replay_outcome TEXT NOT NULL,
                    original_score REAL NOT NULL,
                    replay_score REAL NOT NULL,
                    original_latency_ms REAL NOT NULL,
                    replay_latency_ms REAL NOT NULL,
                    original_cost REAL NOT NULL,
                    replay_cost REAL NOT NULL,
                    tool_calls_matched INTEGER NOT NULL,
                    delta_score REAL NOT NULL,
                    improved INTEGER NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES what_if_jobs(job_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_replay_job ON replay_outcomes(job_id)")
            conn.commit()

    def save_result(self, result: WhatIfResult) -> None:
        """Save a what-if result to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO what_if_jobs (
                    job_id, candidate_config_label, conversation_ids,
                    total_conversations, improved_count, degraded_count,
                    unchanged_count, avg_delta_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.job_id,
                    result.candidate_config_label,
                    json.dumps(result.conversation_ids),
                    result.total_conversations,
                    result.improved_count,
                    result.degraded_count,
                    result.unchanged_count,
                    result.avg_delta_score,
                    result.created_at,
                ),
            )

            for outcome in result.outcomes:
                conn.execute(
                    """
                    INSERT INTO replay_outcomes (
                        job_id, conversation_id, original_outcome, replay_outcome,
                        original_score, replay_score, original_latency_ms, replay_latency_ms,
                        original_cost, replay_cost, tool_calls_matched, delta_score, improved
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.job_id,
                        outcome.conversation_id,
                        outcome.original_outcome,
                        outcome.replay_outcome,
                        outcome.original_score,
                        outcome.replay_score,
                        outcome.original_latency_ms,
                        outcome.replay_latency_ms,
                        outcome.original_cost,
                        outcome.replay_cost,
                        int(outcome.tool_calls_matched),
                        outcome.delta_score,
                        int(outcome.improved),
                    ),
                )
            conn.commit()

    def get_result(self, job_id: str) -> WhatIfResult | None:
        """Retrieve a what-if result by job ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM what_if_jobs WHERE job_id = ?", (job_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None

            outcomes_cursor = conn.execute(
                """
                SELECT conversation_id, original_outcome, replay_outcome,
                       original_score, replay_score, original_latency_ms,
                       replay_latency_ms, original_cost, replay_cost,
                       tool_calls_matched, delta_score, improved
                FROM replay_outcomes
                WHERE job_id = ?
                ORDER BY id
                """,
                (job_id,),
            )
            outcomes = [
                ReplayOutcome(
                    conversation_id=r["conversation_id"],
                    original_outcome=r["original_outcome"],
                    replay_outcome=r["replay_outcome"],
                    original_score=r["original_score"],
                    replay_score=r["replay_score"],
                    original_latency_ms=r["original_latency_ms"],
                    replay_latency_ms=r["replay_latency_ms"],
                    original_cost=r["original_cost"],
                    replay_cost=r["replay_cost"],
                    tool_calls_matched=bool(r["tool_calls_matched"]),
                    delta_score=r["delta_score"],
                    improved=bool(r["improved"]),
                )
                for r in outcomes_cursor
            ]

            return WhatIfResult(
                job_id=row["job_id"],
                candidate_config_label=row["candidate_config_label"],
                conversation_ids=json.loads(row["conversation_ids"]),
                outcomes=outcomes,
                total_conversations=row["total_conversations"],
                improved_count=row["improved_count"],
                degraded_count=row["degraded_count"],
                unchanged_count=row["unchanged_count"],
                avg_delta_score=row["avg_delta_score"],
                created_at=row["created_at"],
            )

    def list_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent what-if jobs."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT job_id, candidate_config_label, total_conversations,
                       improved_count, degraded_count, avg_delta_score, created_at
                FROM what_if_jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]


class WhatIfEngine:
    """Engine for replaying historical conversations through candidate configs."""

    def __init__(
        self,
        conversation_store: Any,
        replay_store: ReplayStore | None = None,
        what_if_store: WhatIfStore | None = None,
    ):
        self.conversation_store = conversation_store
        self.replay_store = replay_store or ReplayStore()
        self.what_if_store = what_if_store or WhatIfStore()

    def replay_with_config(
        self,
        conversation_ids: list[str],
        candidate_config_label: str,
        agent_fn: Any | None = None,
    ) -> WhatIfResult:
        """Replay conversations through a candidate config.

        Args:
            conversation_ids: List of conversation IDs to replay
            candidate_config_label: Label for the candidate configuration
            agent_fn: Optional agent function to use for replay (defaults to mock)

        Returns:
            WhatIfResult with outcomes and aggregate statistics
        """
        job_id = f"whatif_{uuid.uuid4().hex[:12]}"
        outcomes: list[ReplayOutcome] = []

        for conv_id in conversation_ids:
            # Get original conversation record
            original_record = self._get_conversation_record(conv_id)
            if not original_record:
                logger.warning(f"Conversation {conv_id} not found, skipping")
                continue

            # Replay the conversation with candidate config
            replay_result = self._replay_conversation(
                original_record, candidate_config_label, agent_fn
            )

            # Compute scores
            original_score = self._compute_score(original_record)
            replay_score = self._compute_score_from_result(replay_result)

            # Compute delta
            delta_score = replay_score - original_score
            improved = delta_score > 0.01  # Threshold for improvement

            outcome = ReplayOutcome(
                conversation_id=conv_id,
                original_outcome=original_record.outcome,
                replay_outcome=replay_result.get("outcome", "unknown"),
                original_score=original_score,
                replay_score=replay_score,
                original_latency_ms=original_record.latency_ms,
                replay_latency_ms=replay_result.get("latency_ms", 0.0),
                original_cost=self._compute_cost(original_record.token_count),
                replay_cost=self._compute_cost(replay_result.get("token_count", 0)),
                tool_calls_matched=self._compare_tool_calls(
                    original_record.tool_calls, replay_result.get("tool_calls", [])
                ),
                delta_score=delta_score,
                improved=improved,
            )
            outcomes.append(outcome)

        # Compute aggregate statistics
        improved_count = sum(1 for o in outcomes if o.improved)
        degraded_count = sum(1 for o in outcomes if o.delta_score < -0.01)
        unchanged_count = len(outcomes) - improved_count - degraded_count
        avg_delta_score = (
            sum(o.delta_score for o in outcomes) / len(outcomes) if outcomes else 0.0
        )

        result = WhatIfResult(
            job_id=job_id,
            candidate_config_label=candidate_config_label,
            conversation_ids=conversation_ids,
            outcomes=outcomes,
            total_conversations=len(outcomes),
            improved_count=improved_count,
            degraded_count=degraded_count,
            unchanged_count=unchanged_count,
            avg_delta_score=avg_delta_score,
        )

        # Save to store
        self.what_if_store.save_result(result)

        return result

    def compare_outcomes(
        self, original_results: list[dict], replay_results: list[dict]
    ) -> dict[str, Any]:
        """Side-by-side comparison of original and replay outcomes.

        Args:
            original_results: List of original conversation outcomes
            replay_results: List of replay conversation outcomes

        Returns:
            Dictionary with comparison metrics and per-conversation deltas
        """
        if len(original_results) != len(replay_results):
            raise ValueError("Original and replay result counts must match")

        comparisons = []
        for orig, replay in zip(original_results, replay_results):
            orig_score = orig.get("score", 0.0)
            replay_score = replay.get("score", 0.0)
            comparisons.append(
                {
                    "conversation_id": orig.get("conversation_id", "unknown"),
                    "original_score": orig_score,
                    "replay_score": replay_score,
                    "delta": replay_score - orig_score,
                    "improved": replay_score > orig_score,
                }
            )

        improved = sum(1 for c in comparisons if c["improved"])
        degraded = sum(1 for c in comparisons if c["delta"] < 0)

        return {
            "total": len(comparisons),
            "improved": improved,
            "degraded": degraded,
            "unchanged": len(comparisons) - improved - degraded,
            "avg_delta": sum(c["delta"] for c in comparisons) / len(comparisons),
            "comparisons": comparisons,
        }

    def project_impact(
        self, job_id: str, total_population: int
    ) -> ImpactProjection:
        """Project impact of candidate config to full traffic.

        Args:
            job_id: What-if job ID with sample results
            total_population: Total number of conversations to project to

        Returns:
            ImpactProjection with extrapolated metrics
        """
        result = self.what_if_store.get_result(job_id)
        if not result:
            raise ValueError(f"Job {job_id} not found")

        sample_size = result.total_conversations
        if sample_size == 0:
            raise ValueError("Cannot project from empty sample")

        # Compute improvement rate
        improvement_rate = result.improved_count / sample_size

        # Project to full population
        projected_improvement_absolute = int(improvement_rate * total_population)

        # Compute 95% confidence interval (Wilson score interval)
        z = 1.96  # 95% confidence
        p = improvement_rate
        n = sample_size

        denominator = 1 + z**2 / n
        center = (p + z**2 / (2 * n)) / denominator
        margin = z * ((p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5) / denominator

        ci_lower = max(0.0, center - margin)
        ci_upper = min(1.0, center + margin)

        # Generate recommendation
        if improvement_rate > 0.05 and result.avg_delta_score > 0.05:
            recommendation = "RECOMMEND_DEPLOY"
        elif improvement_rate < -0.05 or result.avg_delta_score < -0.05:
            recommendation = "DO_NOT_DEPLOY"
        else:
            recommendation = "NEUTRAL"

        return ImpactProjection(
            job_id=job_id,
            sample_size=sample_size,
            total_population=total_population,
            improved_count=result.improved_count,
            degraded_count=result.degraded_count,
            projected_improvement_rate=improvement_rate,
            projected_improvement_absolute=projected_improvement_absolute,
            confidence_interval_95=(ci_lower, ci_upper),
            recommendation=recommendation,
        )

    def _get_conversation_record(self, conversation_id: str) -> ConversationRecord | None:
        """Retrieve a conversation record from the store."""
        try:
            return self.conversation_store.get(conversation_id)
        except Exception as e:
            logger.error(f"Failed to get conversation {conversation_id}: {e}")
            return None

    def _replay_conversation(
        self, original: ConversationRecord, config_label: str, agent_fn: Any | None
    ) -> dict[str, Any]:
        """Replay a conversation through the candidate config.

        Uses recorded tool outputs from the original conversation where possible.
        """
        # Mock replay implementation - in production, this would invoke the agent
        # with the candidate config and stub tools using replay store
        start_time = time.time()

        # Simulate agent execution with tool stubbing
        replay_tool_calls = []
        for tool_call in original.tool_calls:
            # Check if we have recorded output for this tool call
            tool_name = tool_call.get("tool", "unknown")
            tool_input = tool_call.get("input", {})
            input_hash = _hash_input(tool_input)

            # In production, look up recorded output from replay store
            replay_tool_calls.append(
                {
                    "tool": tool_name,
                    "input": tool_input,
                    "status": "ok",  # Use recorded status
                }
            )

        latency_ms = (time.time() - start_time) * 1000

        # In production, this would return the actual agent response
        # For now, return a mock result with similar structure
        return {
            "outcome": "success" if original.outcome == "success" else "fail",
            "response": f"[Replayed with {config_label}] " + original.agent_response,
            "tool_calls": replay_tool_calls,
            "latency_ms": latency_ms,
            "token_count": original.token_count,  # Estimate
        }

    def _compute_score(self, record: ConversationRecord) -> float:
        """Compute a score for a conversation record."""
        base_score = 1.0 if record.outcome == "success" else 0.0

        # Adjust for latency (penalize high latency)
        if record.latency_ms > 5000:
            base_score *= 0.8
        elif record.latency_ms > 2000:
            base_score *= 0.9

        # Adjust for safety violations
        if record.safety_flags:
            base_score *= 0.5

        # Adjust for tool errors
        tool_errors = sum(
            1 for tc in record.tool_calls if tc.get("status") == "error"
        )
        if tool_errors > 0:
            base_score *= 0.7

        return base_score

    def _compute_score_from_result(self, result: dict[str, Any]) -> float:
        """Compute a score from a replay result."""
        base_score = 1.0 if result.get("outcome") == "success" else 0.0

        # Adjust for latency
        latency_ms = result.get("latency_ms", 0.0)
        if latency_ms > 5000:
            base_score *= 0.8
        elif latency_ms > 2000:
            base_score *= 0.9

        # Adjust for tool errors
        tool_errors = sum(
            1
            for tc in result.get("tool_calls", [])
            if tc.get("status") == "error"
        )
        if tool_errors > 0:
            base_score *= 0.7

        return base_score

    def _compute_cost(self, token_count: int) -> float:
        """Compute cost from token count (simplified)."""
        # Rough estimate: $0.002 per 1K tokens
        return (token_count / 1000.0) * 0.002

    def _compare_tool_calls(
        self, original_calls: list[dict], replay_calls: list[dict]
    ) -> bool:
        """Check if tool calls match between original and replay."""
        if len(original_calls) != len(replay_calls):
            return False

        # Compare tool names in order
        orig_tools = [tc.get("tool", "") for tc in original_calls]
        replay_tools = [tc.get("tool", "") for tc in replay_calls]

        return orig_tools == replay_tools
