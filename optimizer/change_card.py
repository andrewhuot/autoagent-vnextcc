"""Reviewable change cards — human-friendly optimization proposals.

A ProposedChangeCard wraps an ExperimentCard with plain-English reasoning,
unified diffs, metric comparisons, confidence stats, and rollout plans.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConfidenceInfo:
    """Statistical confidence for a proposed change."""

    p_value: float = 1.0
    effect_size: float = 0.0
    judge_agreement: float = 0.0
    n_eval_cases: int = 0


@dataclass
class DiffHunk:
    """A single hunk of a unified diff."""

    hunk_id: str = ""
    surface: str = ""        # e.g., "instructions.returns_agent"
    old_value: str = ""
    new_value: str = ""
    status: str = "pending"  # pending, accepted, rejected

    def to_dict(self) -> dict[str, Any]:
        return {
            "hunk_id": self.hunk_id,
            "surface": self.surface,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiffHunk:
        return cls(
            hunk_id=data.get("hunk_id", ""),
            surface=data.get("surface", ""),
            old_value=data.get("old_value", ""),
            new_value=data.get("new_value", ""),
            status=data.get("status", "pending"),
        )


@dataclass
class ProposedChangeCard:
    """Human-readable change card for optimization proposals."""

    card_id: str = ""
    title: str = ""
    why: str = ""
    diff_hunks: list[DiffHunk] = field(default_factory=list)
    metrics_before: dict[str, float] = field(default_factory=dict)
    metrics_after: dict[str, float] = field(default_factory=dict)
    metrics_by_slice: dict[str, dict[str, float]] = field(default_factory=dict)
    confidence: ConfidenceInfo = field(default_factory=ConfidenceInfo)
    risk_class: str = "low"
    cost_delta: float = 0.0
    latency_delta: float = 0.0
    rollout_plan: str = "2h canary \u2192 auto-promote if metrics hold"
    rollback_condition: str = ""
    experiment_card_id: str = ""
    attempt_id: str | None = None
    candidate_config_version: int | None = None
    candidate_config_path: str = ""
    source_eval_path: str = ""
    memory_context: str | None = None
    patch_bundle: dict[str, Any] | None = None
    status: str = "pending"  # pending, applied, rejected
    created_at: float = field(default_factory=time.time)
    rejection_reason: str = ""

    # Audit trail fields (Feature 3)
    dimension_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)  # {dimension: {before, after, delta}}
    gate_results: list[dict[str, Any]] = field(default_factory=list)  # [{gate, passed, reason}, ...]
    adversarial_results: dict[str, Any] | None = None  # {passed, score_drop, num_cases}
    composite_breakdown: dict[str, Any] | None = None  # {weights, components, contributions}
    timeline: list[dict[str, Any]] = field(default_factory=list)  # [{phase, timestamp, status}, ...]

    def __post_init__(self) -> None:
        if not self.card_id:
            self.card_id = str(uuid.uuid4())[:8]

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "title": self.title,
            "why": self.why,
            "diff_hunks": [h.to_dict() for h in self.diff_hunks],
            "metrics_before": self.metrics_before,
            "metrics_after": self.metrics_after,
            "metrics_by_slice": self.metrics_by_slice,
            "confidence": {
                "p_value": self.confidence.p_value,
                "effect_size": self.confidence.effect_size,
                "judge_agreement": self.confidence.judge_agreement,
                "n_eval_cases": self.confidence.n_eval_cases,
            },
            "risk_class": self.risk_class,
            "cost_delta": self.cost_delta,
            "latency_delta": self.latency_delta,
            "rollout_plan": self.rollout_plan,
            "rollback_condition": self.rollback_condition,
            "experiment_card_id": self.experiment_card_id,
            "attempt_id": self.attempt_id,
            "candidate_config_version": self.candidate_config_version,
            "candidate_config_path": self.candidate_config_path,
            "source_eval_path": self.source_eval_path,
            "memory_context": self.memory_context,
            "patch_bundle": self.patch_bundle,
            "status": self.status,
            "created_at": self.created_at,
            "rejection_reason": self.rejection_reason,
            "dimension_breakdown": self.dimension_breakdown,
            "gate_results": self.gate_results,
            "adversarial_results": self.adversarial_results,
            "composite_breakdown": self.composite_breakdown,
            "timeline": self.timeline,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProposedChangeCard:
        confidence_data = data.get("confidence", {})
        return cls(
            card_id=data.get("card_id", ""),
            title=data.get("title", ""),
            why=data.get("why", ""),
            diff_hunks=[DiffHunk.from_dict(h) for h in data.get("diff_hunks", [])],
            metrics_before=data.get("metrics_before", {}),
            metrics_after=data.get("metrics_after", {}),
            metrics_by_slice=data.get("metrics_by_slice", {}),
            confidence=ConfidenceInfo(
                p_value=confidence_data.get("p_value", 1.0),
                effect_size=confidence_data.get("effect_size", 0.0),
                judge_agreement=confidence_data.get("judge_agreement", 0.0),
                n_eval_cases=confidence_data.get("n_eval_cases", 0),
            ),
            risk_class=data.get("risk_class", "low"),
            cost_delta=data.get("cost_delta", 0.0),
            latency_delta=data.get("latency_delta", 0.0),
            rollout_plan=data.get("rollout_plan", ""),
            rollback_condition=data.get("rollback_condition", ""),
            experiment_card_id=data.get("experiment_card_id", ""),
            attempt_id=data.get("attempt_id"),
            candidate_config_version=data.get("candidate_config_version"),
            candidate_config_path=data.get("candidate_config_path", ""),
            source_eval_path=data.get("source_eval_path", ""),
            memory_context=data.get("memory_context"),
            patch_bundle=data.get("patch_bundle"),
            status=data.get("status", "pending"),
            created_at=data.get("created_at", 0.0),
            rejection_reason=data.get("rejection_reason", ""),
            dimension_breakdown=data.get("dimension_breakdown", {}),
            gate_results=data.get("gate_results", []),
            adversarial_results=data.get("adversarial_results"),
            composite_breakdown=data.get("composite_breakdown"),
            timeline=data.get("timeline", []),
        )

    @classmethod
    def from_experiment_card(
        cls,
        card: Any,
        baseline_scores: dict[str, float] | None = None,
        candidate_scores: dict[str, float] | None = None,
        memory_context: str | None = None,
    ) -> ProposedChangeCard:
        """Create a ProposedChangeCard from an ExperimentCard.

        Args:
            card: ExperimentCard instance.
            baseline_scores: Optional dict of baseline metric scores.
            candidate_scores: Optional dict of candidate metric scores.
            memory_context: Optional AGENTLAB.md context string.
        """
        b_scores = baseline_scores or card.baseline_scores or {}
        c_scores = candidate_scores or card.candidate_scores or {}

        # Compute deltas
        cost_before = b_scores.get("cost", 0.0)
        cost_after = c_scores.get("cost", 0.0)
        latency_before = b_scores.get("latency", 0.0)
        latency_after = c_scores.get("latency", 0.0)

        # Build diff hunks from experiment card's diff_summary
        hunks: list[DiffHunk] = []
        if card.diff_summary:
            hunk = DiffHunk(
                hunk_id=str(uuid.uuid4())[:8],
                surface=(
                    ", ".join(card.touched_surfaces)
                    if card.touched_surfaces
                    else "config"
                ),
                old_value="(see diff)",
                new_value=card.diff_summary,
                status="pending",
            )
            hunks.append(hunk)

        # Build rollback condition from risk class
        rollback = "Auto-rollback if safety drops below 1.0"
        if card.risk_class in ("high", "critical"):
            rollback += " or quality drops > 3% from baseline"
        else:
            rollback += " or quality drops > 5% from baseline"

        return cls(
            title=card.hypothesis or f"Optimization: {card.operator_name}",
            why=card.result_summary or card.hypothesis,
            diff_hunks=hunks,
            metrics_before=b_scores,
            metrics_after=c_scores,
            confidence=ConfidenceInfo(
                p_value=card.significance_p_value,
                effect_size=card.significance_delta,
            ),
            risk_class=card.risk_class or "low",
            cost_delta=cost_after - cost_before,
            latency_delta=latency_after - latency_before,
            rollback_condition=rollback,
            experiment_card_id=card.experiment_id,
            attempt_id=None,
            candidate_config_version=None,
            candidate_config_path="",
            source_eval_path="",
            memory_context=memory_context,
        )

    def to_terminal(self) -> str:
        """Render the change card for terminal display with box drawing."""
        width = 60
        lines: list[str] = []
        lines.append("\u250c" + "\u2500" * (width - 2) + "\u2510")
        lines.append(
            "\u2502"
            + f" Proposed Change: {self.title}"[: width - 3].ljust(width - 3)
            + " \u2502"
        )
        lines.append("\u251c" + "\u2500" * (width - 2) + "\u2524")

        # WHY section
        lines.append("\u2502" + " WHY:".ljust(width - 3) + " \u2502")
        why_lines = _wrap_text(self.why, width - 8)
        for wl in why_lines[:4]:
            lines.append(
                "\u2502" + f"   {wl}"[: width - 3].ljust(width - 3) + " \u2502"
            )

        if self.memory_context:
            ctx_lines = _wrap_text(
                f"AGENTLAB.md: {self.memory_context}", width - 8
            )
            for cl in ctx_lines[:2]:
                lines.append(
                    "\u2502"
                    + f"   {cl}"[: width - 3].ljust(width - 3)
                    + " \u2502"
                )

        lines.append("\u2502" + "".ljust(width - 3) + " \u2502")

        # DIFF section
        if self.diff_hunks:
            lines.append(
                "\u2502" + " WHAT CHANGES:".ljust(width - 3) + " \u2502"
            )
            for hunk in self.diff_hunks[:3]:
                lines.append(
                    "\u2502"
                    + f"   {hunk.surface}"[: width - 3].ljust(width - 3)
                    + " \u2502"
                )
                if hunk.old_value and hunk.old_value != "(see diff)":
                    lines.append(
                        "\u2502"
                        + f"   - {hunk.old_value}"[: width - 3].ljust(width - 3)
                        + " \u2502"
                    )
                if hunk.new_value:
                    for nv_line in hunk.new_value.splitlines()[:3]:
                        lines.append(
                            "\u2502"
                            + f"   + {nv_line}"[: width - 3].ljust(width - 3)
                            + " \u2502"
                        )
            lines.append("\u2502" + "".ljust(width - 3) + " \u2502")

        # METRICS section
        lines.append(
            "\u2502"
            + " METRICS (before \u2192 after):".ljust(width - 3)
            + " \u2502"
        )

        # Group by metric layer
        objectives = ["quality", "task_success_rate", "groundedness"]
        guardrails = ["safety", "safety_compliance"]
        constraints = ["latency", "latency_p95", "cost", "token_cost"]

        for label, metrics in [
            ("Objectives", objectives),
            ("Guardrails", guardrails),
            ("Constraints", constraints),
        ]:
            shown = False
            for m in metrics:
                before = self.metrics_before.get(m)
                after = self.metrics_after.get(m)
                if before is not None or after is not None:
                    if not shown:
                        lines.append(
                            "\u2502"
                            + f"   {label}:".ljust(width - 3)
                            + " \u2502"
                        )
                        shown = True
                    b = f"{before:.4f}" if before is not None else "\u2014"
                    a = f"{after:.4f}" if after is not None else "\u2014"
                    delta = ""
                    if (
                        before is not None
                        and after is not None
                        and before > 0
                    ):
                        pct = ((after - before) / before) * 100
                        delta = f" ({pct:+.1f}%)"
                        if m in guardrails and after >= before:
                            delta += " \u2713"
                    lines.append(
                        "\u2502"
                        + f"     {m}: {b} \u2192 {a}{delta}"[: width - 3].ljust(
                            width - 3
                        )
                        + " \u2502"
                    )

        lines.append("\u2502" + "".ljust(width - 3) + " \u2502")

        # CONFIDENCE section
        lines.append("\u2502" + " CONFIDENCE:".ljust(width - 3) + " \u2502")
        lines.append(
            "\u2502"
            + f"   p-value: {self.confidence.p_value:.4f}, effect: {self.confidence.effect_size:.4f}"[
                : width - 3
            ].ljust(width - 3)
            + " \u2502"
        )
        if self.confidence.judge_agreement > 0:
            lines.append(
                "\u2502"
                + f"   Judge agreement: {self.confidence.judge_agreement:.0%}"[
                    : width - 3
                ].ljust(width - 3)
                + " \u2502"
            )
        lines.append("\u2502" + "".ljust(width - 3) + " \u2502")

        # RISK + COST
        cost_str = (
            f"${self.cost_delta:+.4f}/conv"
            if self.cost_delta != 0
            else "no change"
        )
        lines.append(
            "\u2502"
            + f" RISK: {self.risk_class} | COST DELTA: {cost_str}"[
                : width - 3
            ].ljust(width - 3)
            + " \u2502"
        )
        lines.append("\u2502" + "".ljust(width - 3) + " \u2502")

        # ROLLOUT
        if self.rollout_plan:
            lines.append(
                "\u2502"
                + f" ROLLOUT: {self.rollout_plan}"[: width - 3].ljust(width - 3)
                + " \u2502"
            )
        if self.rollback_condition:
            rollback_lines = _wrap_text(
                f"ROLLBACK: {self.rollback_condition}", width - 6
            )
            for rl in rollback_lines[:2]:
                lines.append(
                    "\u2502"
                    + f" {rl}"[: width - 3].ljust(width - 3)
                    + " \u2502"
                )
        lines.append("\u2502" + "".ljust(width - 3) + " \u2502")

        # STATUS
        lines.append(
            "\u2502"
            + f" [{self.status.upper()}]".ljust(width - 3)
            + " \u2502"
        )
        lines.append("\u2514" + "\u2500" * (width - 2) + "\u2518")

        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Render the change card as markdown for sharing."""
        lines = [f"# Proposed Change: {self.title}", ""]
        lines.append(f"**Status:** {self.status}")
        lines.append(f"**Risk:** {self.risk_class}")
        lines.append(f"**Card ID:** {self.card_id}")
        lines.append("")

        lines.append("## Why")
        lines.append(self.why)
        if self.memory_context:
            lines.append(f"\n*AGENTLAB.md context:* {self.memory_context}")
        lines.append("")

        if self.diff_hunks:
            lines.append("## What Changes")
            for hunk in self.diff_hunks:
                lines.append(f"### {hunk.surface}")
                lines.append("```diff")
                if hunk.old_value and hunk.old_value != "(see diff)":
                    lines.append(f"- {hunk.old_value}")
                if hunk.new_value:
                    for nv_line in hunk.new_value.splitlines():
                        lines.append(f"+ {nv_line}")
                lines.append("```")
            lines.append("")

        lines.append("## Metrics")
        lines.append("| Metric | Before | After | Delta |")
        lines.append("|--------|--------|-------|-------|")
        all_metrics = set(self.metrics_before.keys()) | set(
            self.metrics_after.keys()
        )
        for m in sorted(all_metrics):
            before = self.metrics_before.get(m, 0.0)
            after = self.metrics_after.get(m, 0.0)
            delta = after - before
            lines.append(f"| {m} | {before:.4f} | {after:.4f} | {delta:+.4f} |")
        lines.append("")

        lines.append("## Confidence")
        lines.append(f"- p-value: {self.confidence.p_value:.4f}")
        lines.append(f"- Effect size: {self.confidence.effect_size:.4f}")
        if self.confidence.judge_agreement > 0:
            lines.append(
                f"- Judge agreement: {self.confidence.judge_agreement:.0%}"
            )
        lines.append("")

        if self.rollout_plan:
            lines.append(f"## Rollout\n{self.rollout_plan}")
        if self.rollback_condition:
            lines.append(f"\n## Rollback Condition\n{self.rollback_condition}")

        return "\n".join(lines)


def _wrap_text(text: str, width: int) -> list[str]:
    """Simple word-wrap for terminal rendering."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            if current:
                lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return lines or [""]


class ChangeCardStore:
    """SQLite-backed store for proposed change cards."""

    def __init__(self, db_path: str = ".agentlab/change_cards.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS change_cards (
                    card_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL
                )
            """)
            conn.commit()

    def save(self, card: ProposedChangeCard) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO change_cards"
                " (card_id, data, status, created_at) VALUES (?, ?, ?, ?)",
                (
                    card.card_id,
                    json.dumps(card.to_dict()),
                    card.status,
                    card.created_at,
                ),
            )
            conn.commit()

    def get(self, card_id: str) -> ProposedChangeCard | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT data FROM change_cards WHERE card_id = ?",
                (card_id,),
            ).fetchone()
            if row is None:
                return None
            return ProposedChangeCard.from_dict(json.loads(row[0]))

    def list_pending(self, limit: int = 50) -> list[ProposedChangeCard]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT data FROM change_cards"
                " WHERE status = 'pending'"
                " ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [ProposedChangeCard.from_dict(json.loads(r[0])) for r in rows]

    def list_all(self, limit: int = 100) -> list[ProposedChangeCard]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT data FROM change_cards ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [ProposedChangeCard.from_dict(json.loads(r[0])) for r in rows]

    def update_status(
        self, card_id: str, status: str, reason: str = ""
    ) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            card = self.get(card_id)
            if card is None:
                return False
            card.status = status
            if reason:
                card.rejection_reason = reason
            conn.execute(
                "UPDATE change_cards SET data = ?, status = ? WHERE card_id = ?",
                (json.dumps(card.to_dict()), status, card_id),
            )
            conn.commit()
            return True

    def update_hunk_status(
        self, card_id: str, hunk_id: str, status: str
    ) -> bool:
        card = self.get(card_id)
        if card is None:
            return False
        for hunk in card.diff_hunks:
            if hunk.hunk_id == hunk_id:
                hunk.status = status
                self.save(card)
                return True
        return False

    def approve(self, card_id: str) -> bool:
        """Compatibility helper for flows that expect an explicit approve method."""
        return self.update_status(card_id, "applied")
