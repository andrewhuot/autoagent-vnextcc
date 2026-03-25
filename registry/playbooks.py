"""Playbook registry — user-facing bundles of skills, policies, and tool contracts."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Playbook:
    """A user-facing bundle that groups related registry items."""

    name: str
    description: str
    version: int = 1
    tags: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    policies: list[str] = field(default_factory=list)
    tool_contracts: list[str] = field(default_factory=list)
    triggers: list[dict[str, Any]] = field(default_factory=list)
    surfaces: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    deprecated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": self.tags,
            "skills": self.skills,
            "policies": self.policies,
            "tool_contracts": self.tool_contracts,
            "triggers": self.triggers,
            "surfaces": self.surfaces,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "deprecated": self.deprecated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Playbook:
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", 1),
            tags=data.get("tags", []),
            skills=data.get("skills", []),
            policies=data.get("policies", []),
            tool_contracts=data.get("tool_contracts", []),
            triggers=data.get("triggers", []),
            surfaces=data.get("surfaces", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", 0.0),
            deprecated=data.get("deprecated", False),
        )


class PlaybookStore:
    """SQLite-backed storage for playbooks."""

    def __init__(self, db_path: str = "registry.db") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS playbooks (
                name       TEXT    NOT NULL,
                version    INTEGER NOT NULL,
                data       TEXT    NOT NULL,
                created_at TEXT    NOT NULL,
                deprecated INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (name, version)
            )
        """)
        self._conn.commit()

    def register(self, playbook: Playbook) -> tuple[str, int]:
        """Register a new playbook version. Returns (name, version)."""
        # Get latest version
        row = self._conn.execute(
            "SELECT MAX(version) as max_v FROM playbooks WHERE name = ?",
            (playbook.name,),
        ).fetchone()
        latest = row["max_v"] if row and row["max_v"] is not None else 0
        new_version = latest + 1
        playbook.version = new_version

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        self._conn.execute(
            "INSERT INTO playbooks (name, version, data, created_at) VALUES (?, ?, ?, ?)",
            (playbook.name, new_version, json.dumps(playbook.to_dict(), sort_keys=True), now),
        )
        self._conn.commit()
        return playbook.name, new_version

    def get(self, name: str, version: int | None = None) -> Playbook | None:
        """Get a playbook by name and optional version."""
        if version is None:
            row = self._conn.execute(
                "SELECT * FROM playbooks WHERE name = ? ORDER BY version DESC LIMIT 1",
                (name,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM playbooks WHERE name = ? AND version = ?",
                (name, version),
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row["data"])
        data["deprecated"] = bool(row["deprecated"])
        return Playbook.from_dict(data)

    def list(self, include_deprecated: bool = False) -> list[Playbook]:
        """List all playbooks (latest versions only by default)."""
        if include_deprecated:
            rows = self._conn.execute(
                "SELECT * FROM playbooks ORDER BY name, version"
            ).fetchall()
        else:
            # Get latest non-deprecated version of each playbook
            rows = self._conn.execute("""
                SELECT p.* FROM playbooks p
                INNER JOIN (
                    SELECT name, MAX(version) as max_v
                    FROM playbooks WHERE deprecated = 0
                    GROUP BY name
                ) latest ON p.name = latest.name AND p.version = latest.max_v
                ORDER BY p.name
            """).fetchall()

        result = []
        for r in rows:
            data = json.loads(r["data"])
            data["deprecated"] = bool(r["deprecated"])
            result.append(Playbook.from_dict(data))
        return result

    def deprecate(self, name: str, version: int) -> bool:
        cursor = self._conn.execute(
            "UPDATE playbooks SET deprecated = 1 WHERE name = ? AND version = ?",
            (name, version),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def search(self, query: str) -> list[Playbook]:
        """Search playbooks by name or data content."""
        pattern = f"%{query}%"
        rows = self._conn.execute(
            "SELECT * FROM playbooks WHERE (name LIKE ? OR data LIKE ?) AND deprecated = 0 ORDER BY name, version",
            (pattern, pattern),
        ).fetchall()
        result = []
        for r in rows:
            data = json.loads(r["data"])
            data["deprecated"] = bool(r["deprecated"])
            result.append(Playbook.from_dict(data))
        return result

    def close(self) -> None:
        self._conn.close()


# Built-in starter playbooks
STARTER_PLAYBOOKS: list[dict[str, Any]] = [
    {
        "name": "fix-retrieval-grounding",
        "description": "Improve retrieval quality and reduce hallucination from RAG",
        "tags": ["retrieval", "grounding", "quality"],
        "skills": ["retrieval_query_rewriting", "context_relevance_filtering"],
        "policies": ["no_hallucination_policy", "citation_required_policy"],
        "tool_contracts": ["vector_search_contract", "document_retriever_contract"],
        "triggers": [
            {"failure_family": "quality_degradation", "root_cause": "retrieval_quality"},
            {"blame_cluster": "stale or irrelevant retrieved context"},
        ],
        "surfaces": ["instructions.retrieval_agent", "examples.retrieval_queries", "tool_descriptions.vector_search"],
    },
    {
        "name": "reduce-tool-latency",
        "description": "Optimize tool timeout and retry settings to reduce end-to-end latency",
        "tags": ["latency", "tools", "performance"],
        "skills": ["tool_timeout_tuning", "retry_backoff_optimization"],
        "policies": ["latency_budget_policy"],
        "tool_contracts": [],
        "triggers": [
            {"failure_family": "latency_degradation", "root_cause": "tool_timeout"},
        ],
        "surfaces": ["generation_settings.timeout", "tool_descriptions"],
    },
    {
        "name": "tighten-safety-policy",
        "description": "Enforce safety guardrails and reduce policy violations",
        "tags": ["safety", "compliance", "guardrails"],
        "skills": ["safety_prompt_hardening", "refusal_calibration"],
        "policies": ["zero_tolerance_safety", "content_filtering_policy"],
        "tool_contracts": [],
        "triggers": [
            {"failure_family": "safety_violation", "root_cause": "policy_gap"},
        ],
        "surfaces": ["instructions.safety", "instructions.guardrail_agent"],
    },
    {
        "name": "improve-routing-accuracy",
        "description": "Improve agent routing precision and reduce misroutes",
        "tags": ["routing", "accuracy", "multi-agent"],
        "skills": ["routing_prompt_optimization", "intent_classification_tuning"],
        "policies": ["routing_fallback_policy"],
        "tool_contracts": [],
        "triggers": [
            {"failure_family": "routing_error", "root_cause": "intent_misclassification"},
        ],
        "surfaces": ["instructions.router", "routing"],
    },
    {
        "name": "optimize-cost-efficiency",
        "description": "Reduce token usage and cost without sacrificing quality",
        "tags": ["cost", "efficiency", "tokens"],
        "skills": ["prompt_compression", "context_pruning"],
        "policies": ["cost_budget_policy"],
        "tool_contracts": [],
        "triggers": [
            {"failure_family": "cost_overrun", "root_cause": "token_bloat"},
        ],
        "surfaces": ["instructions", "generation_settings", "context_caching"],
    },
    {
        "name": "enhance-few-shot-examples",
        "description": "Curate and optimize few-shot examples for better task performance",
        "tags": ["few-shot", "examples", "quality"],
        "skills": ["example_selection", "example_diversity_optimization"],
        "policies": [],
        "tool_contracts": [],
        "triggers": [
            {"failure_family": "quality_degradation", "root_cause": "poor_examples"},
        ],
        "surfaces": ["examples"],
    },
    {
        "name": "stabilize-multilingual-support",
        "description": "Improve multilingual quality and reduce language-specific regressions",
        "tags": ["multilingual", "quality", "localization"],
        "skills": ["locale_aware_prompting", "fewshot_language_refresh"],
        "policies": ["language_consistency_policy"],
        "tool_contracts": [],
        "triggers": [
            {"failure_family": "quality_degradation", "root_cause": "language_mismatch"},
        ],
        "surfaces": ["examples.multilingual", "instructions.multilingual_agent"],
    },
]


def seed_starter_playbooks(store: PlaybookStore) -> int:
    """Seed the store with built-in starter playbooks. Returns count of seeded playbooks."""
    count = 0
    for pb_data in STARTER_PLAYBOOKS:
        existing = store.get(pb_data["name"])
        if existing is None:
            playbook = Playbook.from_dict(pb_data)
            store.register(playbook)
            count += 1
    return count
