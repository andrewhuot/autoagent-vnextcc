"""Rich card data generation for assistant responses.

Generates structured card data for rendering in the UI:
- Diagnosis cards (root cause analysis)
- Diff cards (config changes)
- Metrics cards (before/after comparison)
- Agent preview cards (agent structure visualization)
- Conversation cards (transcript with highlights)
- Progress cards (step-by-step operations)
- Deploy cards (deployment status)
- Cluster cards (failure clustering)
"""

from __future__ import annotations

import time
from typing import Any


class CardGenerator:
    """Generates structured card data for various assistant responses."""

    def diagnosis_card(
        self,
        root_cause: str,
        impact_score: float,
        affected_count: int,
        specialist: str | None = None,
        trend: str = "stable",
        example_ids: list[str] | None = None,
        suggested_fix: str | None = None,
    ) -> dict[str, Any]:
        """Generate a diagnosis card showing root cause analysis.

        Args:
            root_cause: Plain English description of the issue
            impact_score: Impact score (0-1, frequency × severity)
            affected_count: Number of affected conversations
            specialist: Which specialist agent is affected
            trend: "increasing", "stable", or "decreasing"
            example_ids: List of example conversation IDs
            suggested_fix: Brief description of suggested fix

        Returns:
            Structured diagnosis card data
        """
        return {
            "type": "diagnosis",
            "root_cause": root_cause,
            "impact_score": round(impact_score, 4),
            "affected_count": affected_count,
            "specialist": specialist,
            "trend": trend,
            "example_conversation_ids": example_ids or [],
            "suggested_fix": suggested_fix,
            "severity": self._impact_to_severity(impact_score),
            "timestamp": time.time(),
        }

    def diff_card(
        self,
        surface: str,
        old_value: str,
        new_value: str,
        change_description: str,
        risk_level: str = "low",
        touched_agents: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate a diff card showing config changes.

        Args:
            surface: Config surface being changed (e.g., "routing.billing_keywords")
            old_value: Current value
            new_value: Proposed new value
            change_description: Plain English description
            risk_level: "low", "medium", "high", or "critical"
            touched_agents: List of affected agent paths

        Returns:
            Structured diff card data
        """
        return {
            "type": "diff",
            "surface": surface,
            "old_value": old_value,
            "new_value": new_value,
            "change_description": change_description,
            "risk_level": risk_level,
            "touched_agents": touched_agents or [],
            "line_count": len(new_value.splitlines()) if new_value else 0,
            "timestamp": time.time(),
        }

    def metrics_card(
        self,
        metrics_before: dict[str, float],
        metrics_after: dict[str, float],
        confidence_p_value: float = 1.0,
        confidence_effect_size: float = 0.0,
        n_eval_cases: int = 0,
    ) -> dict[str, Any]:
        """Generate a metrics comparison card.

        Args:
            metrics_before: Baseline metric scores
            metrics_after: Candidate metric scores
            confidence_p_value: Statistical significance p-value
            confidence_effect_size: Effect size (delta)
            n_eval_cases: Number of evaluation cases

        Returns:
            Structured metrics card data
        """
        deltas = {
            metric: metrics_after.get(metric, 0.0) - metrics_before.get(metric, 0.0)
            for metric in set(metrics_before.keys()) | set(metrics_after.keys())
        }

        return {
            "type": "metrics",
            "metrics_before": {k: round(v, 4) for k, v in metrics_before.items()},
            "metrics_after": {k: round(v, 4) for k, v in metrics_after.items()},
            "deltas": {k: round(v, 4) for k, v in deltas.items()},
            "confidence": {
                "p_value": round(confidence_p_value, 4),
                "effect_size": round(confidence_effect_size, 4),
                "n_eval_cases": n_eval_cases,
                "is_significant": confidence_p_value < 0.05,
            },
            "primary_metric": "quality",
            "improved": metrics_after.get("quality", 0.0) > metrics_before.get("quality", 0.0),
            "timestamp": time.time(),
        }

    def agent_preview_card(
        self,
        agent_name: str,
        specialist_count: int,
        intent_count: int,
        tool_count: int,
        coverage_pct: float,
        specialists: list[dict[str, Any]] | None = None,
        routing_summary: str | None = None,
    ) -> dict[str, Any]:
        """Generate an agent preview card for newly built agents.

        Args:
            agent_name: Name of the agent
            specialist_count: Number of specialist agents
            intent_count: Number of identified intents
            tool_count: Number of tools defined
            coverage_pct: Estimated coverage of input data (0-100)
            specialists: List of specialist definitions
            routing_summary: Plain English routing logic summary

        Returns:
            Structured agent preview card data
        """
        return {
            "type": "agent_preview",
            "agent_name": agent_name,
            "specialist_count": specialist_count,
            "intent_count": intent_count,
            "tool_count": tool_count,
            "coverage_pct": round(coverage_pct, 1),
            "specialists": specialists or [],
            "routing_summary": routing_summary,
            "timestamp": time.time(),
        }

    def conversation_card(
        self,
        conversation_id: str,
        transcript: str,
        failure_spans: list[dict[str, Any]] | None = None,
        quality_score: float | None = None,
        specialist_used: str | None = None,
    ) -> dict[str, Any]:
        """Generate a conversation transcript card with highlighted failures.

        Args:
            conversation_id: Unique conversation identifier
            transcript: Full conversation text
            failure_spans: List of highlighted failure spans with positions
            quality_score: Overall quality score (0-1)
            specialist_used: Which specialist handled this

        Returns:
            Structured conversation card data
        """
        return {
            "type": "conversation",
            "conversation_id": conversation_id,
            "transcript": transcript,
            "failure_spans": failure_spans or [],
            "quality_score": round(quality_score, 4) if quality_score is not None else None,
            "specialist_used": specialist_used,
            "turn_count": transcript.count("User:") + transcript.count("Assistant:"),
            "timestamp": time.time(),
        }

    def progress_card(
        self,
        steps: list[dict[str, Any]],
        total_steps: int | None = None,
        current_step: int | None = None,
    ) -> dict[str, Any]:
        """Generate a progress card showing step-by-step operation status.

        Args:
            steps: List of step dictionaries with status, description, details
            total_steps: Total number of steps (if known)
            current_step: Current step index (if known)

        Returns:
            Structured progress card data

        Step format:
            {
                "description": "Analyzing transcripts...",
                "status": "completed" | "running" | "pending" | "failed",
                "details": "Found 500 conversations",
                "substeps": [...] (optional)
            }
        """
        completed = sum(1 for s in steps if s.get("status") == "completed")
        failed = sum(1 for s in steps if s.get("status") == "failed")
        running = any(s.get("status") == "running" for s in steps)

        return {
            "type": "progress",
            "steps": steps,
            "total_steps": total_steps or len(steps),
            "current_step": current_step,
            "completed_count": completed,
            "failed_count": failed,
            "is_running": running,
            "is_complete": completed == len(steps) and not failed,
            "timestamp": time.time(),
        }

    def deploy_card(
        self,
        deployment_id: str,
        status: str,
        canary_version: int | None = None,
        canary_pct: float = 10.0,
        canary_success_rate: float | None = None,
        baseline_success_rate: float | None = None,
        verdict: str = "pending",
        rollback_available: bool = True,
    ) -> dict[str, Any]:
        """Generate a deployment status card.

        Args:
            deployment_id: Unique deployment identifier
            status: "pending", "canary", "promoted", "rolled_back", "failed"
            canary_version: Version number of canary
            canary_pct: Percentage of traffic on canary
            canary_success_rate: Success rate of canary
            baseline_success_rate: Success rate of baseline
            verdict: "pending", "promote", "rollback"
            rollback_available: Whether rollback is possible

        Returns:
            Structured deploy card data
        """
        return {
            "type": "deploy",
            "deployment_id": deployment_id,
            "status": status,
            "canary_version": canary_version,
            "canary_pct": round(canary_pct, 1),
            "canary_success_rate": round(canary_success_rate, 4) if canary_success_rate else None,
            "baseline_success_rate": round(baseline_success_rate, 4) if baseline_success_rate else None,
            "verdict": verdict,
            "rollback_available": rollback_available,
            "timestamp": time.time(),
        }

    def cluster_card(
        self,
        rank: int,
        title: str,
        description: str,
        count: int,
        impact: float,
        trend: str = "stable",
        example_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate a failure cluster card.

        Args:
            rank: Cluster rank by impact (1-based)
            title: Short cluster title
            description: Detailed cluster description
            count: Number of conversations in cluster
            impact: Impact score (0-1)
            trend: "increasing", "stable", "decreasing"
            example_ids: Example conversation IDs

        Returns:
            Structured cluster card data
        """
        return {
            "type": "cluster",
            "rank": rank,
            "title": title,
            "description": description,
            "count": count,
            "impact_score": round(impact, 4),
            "trend": trend,
            "example_conversation_ids": example_ids or [],
            "severity": self._impact_to_severity(impact),
            "timestamp": time.time(),
        }

    @staticmethod
    def _impact_to_severity(impact_score: float) -> str:
        """Convert impact score to severity label.

        Args:
            impact_score: Impact score (0-1)

        Returns:
            Severity label: "low", "medium", "high", or "critical"
        """
        if impact_score >= 0.3:
            return "critical"
        if impact_score >= 0.15:
            return "high"
        if impact_score >= 0.05:
            return "medium"
        return "low"

    def suggestion_card(
        self,
        suggestions: list[str],
        primary_action: str | None = None,
    ) -> dict[str, Any]:
        """Generate a suggestions card with action buttons.

        Args:
            suggestions: List of suggested action labels
            primary_action: Primary suggested action (first in list if None)

        Returns:
            Structured suggestions card data
        """
        return {
            "type": "suggestions",
            "suggestions": suggestions,
            "primary_action": primary_action or (suggestions[0] if suggestions else None),
            "timestamp": time.time(),
        }

    def error_card(
        self,
        error_message: str,
        error_type: str = "general",
        recovery_suggestions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate an error card.

        Args:
            error_message: Error message to display
            error_type: Type of error ("general", "validation", "not_found", etc.)
            recovery_suggestions: Suggested recovery actions

        Returns:
            Structured error card data
        """
        return {
            "type": "error",
            "error_message": error_message,
            "error_type": error_type,
            "recovery_suggestions": recovery_suggestions or [],
            "timestamp": time.time(),
        }

    def text_card(self, content: str) -> dict[str, Any]:
        """Generate a plain text card.

        Args:
            content: Text content to display

        Returns:
            Structured text card data
        """
        return {
            "type": "text",
            "content": content,
            "timestamp": time.time(),
        }
