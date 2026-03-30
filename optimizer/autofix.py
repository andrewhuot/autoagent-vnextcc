"""AutoFix engine for proposing and applying configuration mutations.

Analyzes eval failures, generates fix proposals via pluggable proposer
strategies, and applies approved mutations through the MutationRegistry.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class AutoFixProposal:
    """A single proposed fix for an observed eval failure pattern."""

    proposal_id: str
    mutation_name: str
    surface: str
    params: dict = field(default_factory=dict)
    expected_lift: float = 0.0
    risk_class: str = "low"
    affected_eval_slices: list[str] = field(default_factory=list)
    cost_impact_estimate: float = 0.0
    diff_preview: str = ""
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    evaluated_at: float | None = None
    eval_result: dict | None = None
    applied_at: float | None = None

    def to_dict(self) -> dict:
        """Serialize the proposal to a plain dict."""
        return {
            "proposal_id": self.proposal_id,
            "mutation_name": self.mutation_name,
            "surface": self.surface,
            "params": self.params,
            "expected_lift": self.expected_lift,
            "risk_class": self.risk_class,
            "affected_eval_slices": self.affected_eval_slices,
            "cost_impact_estimate": self.cost_impact_estimate,
            "diff_preview": self.diff_preview,
            "status": self.status,
            "created_at": self.created_at,
            "evaluated_at": self.evaluated_at,
            "eval_result": self.eval_result,
            "applied_at": self.applied_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AutoFixProposal:
        """Deserialize a proposal from a plain dict."""
        return cls(
            proposal_id=data["proposal_id"],
            mutation_name=data["mutation_name"],
            surface=data["surface"],
            params=data.get("params", {}),
            expected_lift=data.get("expected_lift", 0.0),
            risk_class=data.get("risk_class", "low"),
            affected_eval_slices=data.get("affected_eval_slices", []),
            cost_impact_estimate=data.get("cost_impact_estimate", 0.0),
            diff_preview=data.get("diff_preview", ""),
            status=data.get("status", "pending"),
            created_at=data.get("created_at", 0.0),
            evaluated_at=data.get("evaluated_at"),
            eval_result=data.get("eval_result"),
            applied_at=data.get("applied_at"),
        )


@dataclass
class AutoFixHistoryEntry:
    """Outcome record for applied proposals."""

    history_id: str
    proposal_id: str
    applied_at: float
    status: str
    message: str
    baseline_composite: float = 0.0
    candidate_composite: float = 0.0
    significance_p_value: float = 1.0
    significance_delta: float = 0.0
    canary_verdict: str = ""
    deploy_message: str = ""


@dataclass
class AutoFixApplyOutcome:
    """Structured response from apply execution."""

    proposal_id: str
    status: str
    message: str
    baseline_composite: float = 0.0
    candidate_composite: float = 0.0
    significance_p_value: float = 1.0
    significance_delta: float = 0.0
    canary_verdict: str = ""
    deploy_message: str = ""


_VALID_STATUSES = {"pending", "evaluating", "evaluated", "applied", "rejected", "expired", "reverted"}


class AutoFixStore:
    """Persistent SQLite store for autofix proposals."""

    def __init__(self, db_path: str = ".autoagent/autofix.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Create the proposals table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    mutation_name TEXT NOT NULL,
                    surface TEXT NOT NULL DEFAULT '',
                    params TEXT NOT NULL DEFAULT '{}',
                    expected_lift REAL DEFAULT 0.0,
                    risk_class TEXT NOT NULL DEFAULT 'low',
                    affected_eval_slices TEXT NOT NULL DEFAULT '[]',
                    cost_impact_estimate REAL DEFAULT 0.0,
                    diff_preview TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    evaluated_at REAL,
                    eval_result TEXT,
                    applied_at REAL
                )
                """
            )
            conn.commit()

    def save(self, proposal: AutoFixProposal) -> None:
        """Insert or replace a proposal."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO proposals
                    (proposal_id, mutation_name, surface, params, expected_lift,
                     risk_class, affected_eval_slices, cost_impact_estimate,
                     diff_preview, status, created_at, evaluated_at,
                     eval_result, applied_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.proposal_id,
                    proposal.mutation_name,
                    proposal.surface,
                    json.dumps(proposal.params, sort_keys=True, default=str),
                    proposal.expected_lift,
                    proposal.risk_class,
                    json.dumps(proposal.affected_eval_slices, sort_keys=True, default=str),
                    proposal.cost_impact_estimate,
                    proposal.diff_preview,
                    proposal.status,
                    proposal.created_at,
                    proposal.evaluated_at,
                    json.dumps(proposal.eval_result, sort_keys=True, default=str)
                    if proposal.eval_result is not None
                    else None,
                    proposal.applied_at,
                ),
            )
            conn.commit()

    def get(self, proposal_id: str) -> AutoFixProposal | None:
        """Retrieve a single proposal by ID, or None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT proposal_id, mutation_name, surface, params, expected_lift,
                       risk_class, affected_eval_slices, cost_impact_estimate,
                       diff_preview, status, created_at, evaluated_at,
                       eval_result, applied_at
                FROM proposals
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_proposal(row)

    def list_proposals(
        self, status: str | None = None, limit: int = 50
    ) -> list[AutoFixProposal]:
        """Get proposals, optionally filtered by status, ordered by created_at descending."""
        with sqlite3.connect(self.db_path) as conn:
            if status is not None:
                rows = conn.execute(
                    """
                    SELECT proposal_id, mutation_name, surface, params, expected_lift,
                           risk_class, affected_eval_slices, cost_impact_estimate,
                           diff_preview, status, created_at, evaluated_at,
                           eval_result, applied_at
                    FROM proposals
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT proposal_id, mutation_name, surface, params, expected_lift,
                           risk_class, affected_eval_slices, cost_impact_estimate,
                           diff_preview, status, created_at, evaluated_at,
                           eval_result, applied_at
                    FROM proposals
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [self._row_to_proposal(row) for row in rows]

    def update_status(self, proposal_id: str, status: str, **kwargs: object) -> None:
        """Update the status and optional fields of a proposal."""
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: {_VALID_STATUSES}"
            )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE proposals SET status = ? WHERE proposal_id = ?",
                (status, proposal_id),
            )
            for col in ("evaluated_at", "eval_result", "applied_at"):
                if col in kwargs:
                    value = kwargs[col]
                    if col == "eval_result" and value is not None:
                        value = json.dumps(value, sort_keys=True, default=str)
                    conn.execute(
                        f"UPDATE proposals SET {col} = ? WHERE proposal_id = ?",  # noqa: S608
                        (value, proposal_id),
                    )
            conn.commit()

    @staticmethod
    def _row_to_proposal(row: tuple) -> AutoFixProposal:
        """Convert a database row tuple to an AutoFixProposal."""
        return AutoFixProposal(
            proposal_id=row[0],
            mutation_name=row[1],
            surface=row[2],
            params=json.loads(row[3]),
            expected_lift=row[4],
            risk_class=row[5],
            affected_eval_slices=json.loads(row[6]),
            cost_impact_estimate=row[7],
            diff_preview=row[8],
            status=row[9],
            created_at=row[10],
            evaluated_at=row[11],
            eval_result=json.loads(row[12]) if row[12] is not None else None,
            applied_at=row[13],
        )


class AutoFixEngine:
    """Coordinates proposers, mutation registry, and storage for autofix suggestions."""

    def __init__(
        self,
        proposers: list,
        mutation_registry: object,
        eval_runner: object | None = None,
        store: AutoFixStore | None = None,
    ) -> None:
        self.proposers = proposers
        self.mutation_registry = mutation_registry
        self.eval_runner = eval_runner
        self.store = store

    def suggest(
        self, failures: list[dict], current_config: dict
    ) -> list[AutoFixProposal]:
        """Run all proposers, store proposals, and return them."""
        proposals: list[AutoFixProposal] = []
        for proposer in self.proposers:
            new_proposals = proposer.propose(failures, current_config)
            proposals.extend(new_proposals)

        if self.store is not None:
            for proposal in proposals:
                self.store.save(proposal)

        return proposals

    def apply(
        self, proposal_id: str, current_config: dict
    ) -> tuple[dict, str]:
        """Look up a proposal and apply its mutation via the registry.

        Returns (new_config, status_message).
        """
        if self.store is None:
            raise RuntimeError("AutoFixStore is required to apply proposals")

        proposal = self.store.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Proposal '{proposal_id}' not found")

        operator = self.mutation_registry.get(proposal.mutation_name)
        if operator is None:
            raise KeyError(
                f"Mutation operator '{proposal.mutation_name}' not found in registry"
            )

        new_config = operator.apply(copy.deepcopy(current_config), proposal.params)

        now = time.time()
        self.store.update_status(proposal_id, "applied", applied_at=now)

        return new_config, f"Applied {proposal.mutation_name} (proposal {proposal_id})"

    def reject(self, proposal_id: str) -> str:
        """Mark a proposal as rejected so it is removed from the apply queue."""
        if self.store is None:
            raise RuntimeError("AutoFixStore is required to reject proposals")

        proposal = self.store.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Proposal '{proposal_id}' not found")
        if proposal.status in {"applied", "rejected", "expired"}:
            raise ValueError(f"Proposal '{proposal_id}' is already {proposal.status}")

        self.store.update_status(proposal_id, "rejected")
        return f"Rejected {proposal.mutation_name} (proposal {proposal_id})"

    def history(self, limit: int = 50) -> list[AutoFixProposal]:
        """Return past proposals from the store."""
        if self.store is None:
            return []
        return self.store.list_proposals(limit=limit)


def _generate_proposal_id() -> str:
    """Generate a short unique proposal ID."""
    return uuid.uuid4().hex[:12]
