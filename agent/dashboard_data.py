"""Data aggregation helpers that back dashboard API endpoints."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import yaml

from deployer import Deployer
from evals.runner import EvalRunner
from logger.store import ConversationRecord, ConversationStore
from observer import Observer
from observer.metrics import compute_metrics
from optimizer.memory import OptimizationMemory


@dataclass
class DashboardDataService:
    """Collect and normalize dashboard payloads from system stores."""

    store: ConversationStore
    memory: OptimizationMemory
    deployer: Deployer
    eval_runner: EvalRunner
    app_started_at: float
    current_config_provider: Callable[[], dict]

    @staticmethod
    def _iso(timestamp: float) -> str:
        """Format unix timestamp as UTC ISO-8601 string."""
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

    @staticmethod
    def _human_duration(seconds: float) -> str:
        """Format duration in seconds into compact human-readable form."""
        remaining = int(max(0, seconds))
        hours, remaining = divmod(remaining, 3600)
        minutes, secs = divmod(remaining, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        if minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    @staticmethod
    def _health_score(
        *,
        success_rate: float,
        error_rate: float,
        safety_rate: float,
        avg_latency_ms: float,
    ) -> tuple[float, str]:
        """Compute a bounded 0-100 health score plus color bucket."""
        latency_factor = max(0.0, min(1.0, 1.0 - (avg_latency_ms / 5000.0)))
        score = 100.0 * (
            0.45 * success_rate
            + 0.25 * (1.0 - error_rate)
            + 0.15 * (1.0 - safety_rate)
            + 0.15 * latency_factor
        )
        score = max(0.0, min(100.0, score))
        if score >= 85:
            return round(score, 1), "emerald"
        if score >= 70:
            return round(score, 1), "amber"
        return round(score, 1), "rose"

    def _active_config(self) -> dict:
        """Load active config or fallback to startup-loaded config."""
        return self.deployer.get_active_config() or self.current_config_provider()

    def _active_version_label(self) -> str:
        """Return active version label like v001 or v000 when unavailable."""
        active = self.deployer.status().get("active_version")
        if active is None:
            return "v000"
        return f"v{active:03d}"

    def _journey_summary(
        self, total_conversations: int, attempts: list[OptimizationAttempt]
    ) -> dict:
        """Return a UX-friendly progression summary for the happy path."""
        accepted = [attempt for attempt in attempts if attempt.status == "accepted"]
        completed_steps = 0

        if total_conversations > 0:
            completed_steps += 1
        if attempts:
            completed_steps += 1
        if accepted:
            completed_steps += 1
        if len(attempts) >= 3:
            completed_steps += 1

        progress = round((completed_steps / 4) * 100)

        if completed_steps == 0:
            stage = "Set up and collect your first traces"
            next_action = {
                "label": "Run quickstart",
                "command": "autoagent quickstart",
            }
        elif completed_steps == 1:
            stage = "Great start — run your first optimization cycle"
            next_action = {
                "label": "Run one loop cycle",
                "command": "autoagent loop --max-cycles 1",
            }
        elif completed_steps in (2, 3):
            stage = "Build momentum with repeatable improvements"
            next_action = {
                "label": "Run guided quickstart",
                "command": "autoagent quickstart --verbose",
            }
        else:
            stage = "Pro mode unlocked — scale with canaries and automation"
            next_action = {
                "label": "Run continuous loop",
                "command": "autoagent loop --max-cycles 20 --stop-on-plateau",
            }

        momentum_points = round(sum(max(0.0, a.score_after - a.score_before) * 1000 for a in accepted))
        recent_wins = accepted[:3]

        return {
            "progress_pct": progress,
            "completed_steps": completed_steps,
            "total_steps": 4,
            "stage": stage,
            "next_action": next_action,
            "momentum_points": momentum_points,
            "recent_wins": [
                {
                    "change_description": win.change_description,
                    "delta": round(win.score_after - win.score_before, 4),
                }
                for win in recent_wins
            ],
            "checklist": [
                {"label": "Collect traces", "done": total_conversations > 0},
                {"label": "Run optimization", "done": bool(attempts)},
                {"label": "Ship first accepted win", "done": bool(accepted)},
                {"label": "Run 3+ cycles", "done": len(attempts) >= 3},
            ],
        }

    def _trend_series(self, records: list[ConversationRecord]) -> dict[str, list[float]]:
        """Compute 24 hourly metric series for sparklines."""
        now = time.time()
        cutoff = now - 24 * 3600
        buckets: list[list[ConversationRecord]] = [[] for _ in range(24)]

        for record in records:
            if record.timestamp < cutoff:
                continue
            bucket_idx = int((record.timestamp - cutoff) // 3600)
            if 0 <= bucket_idx < 24:
                buckets[bucket_idx].append(record)

        series = {
            "success_rate": [],
            "avg_latency_ms": [],
            "error_rate": [],
            "safety_violation_rate": [],
            "avg_cost": [],
        }
        for bucket in buckets:
            if not bucket:
                series["success_rate"].append(0.0)
                series["avg_latency_ms"].append(0.0)
                series["error_rate"].append(0.0)
                series["safety_violation_rate"].append(0.0)
                series["avg_cost"].append(0.0)
                continue

            metrics = compute_metrics(bucket)
            series["success_rate"].append(round(metrics.success_rate, 4))
            series["avg_latency_ms"].append(round(metrics.avg_latency_ms, 2))
            series["error_rate"].append(round(metrics.error_rate, 4))
            series["safety_violation_rate"].append(round(metrics.safety_violation_rate, 4))
            series["avg_cost"].append(round(metrics.avg_cost, 4))

        return series

    def health_payload(self) -> dict:
        """Build payload for `GET /api/health`."""
        report = Observer(self.store).observe(window=200)
        metrics = report.metrics
        score, score_color = self._health_score(
            success_rate=metrics.success_rate,
            error_rate=metrics.error_rate,
            safety_rate=metrics.safety_violation_rate,
            avg_latency_ms=metrics.avg_latency_ms,
        )
        now = time.time()
        recent_records = self.store.get_recent(limit=1000)
        recent_attempts = self.memory.recent(limit=100)

        return {
            "timestamp": self._iso(now),
            "config_version": self._active_version_label(),
            "uptime_seconds": int(max(0.0, now - self.app_started_at)),
            "uptime_human": self._human_duration(now - self.app_started_at),
            "health_score": {"value": score, "color": score_color},
            "metrics": {
                "success_rate": round(metrics.success_rate, 4),
                "avg_latency_ms": round(metrics.avg_latency_ms, 2),
                "error_rate": round(metrics.error_rate, 4),
                "safety_violation_rate": round(metrics.safety_violation_rate, 4),
                "cost_per_conversation": round(metrics.avg_cost, 4),
                "total_conversations": metrics.total_conversations,
            },
            "trends": self._trend_series(recent_records),
            "anomalies": report.anomalies,
            "needs_optimization": report.needs_optimization,
            "reason": report.reason,
            "failure_buckets": report.failure_buckets,
            "journey": self._journey_summary(metrics.total_conversations, recent_attempts),
        }

    def history_payload(self) -> dict:
        """Build payload for `GET /api/history`."""
        entries = []
        for attempt in self.memory.recent(limit=100):
            entries.append(
                {
                    "attempt_id": attempt.attempt_id,
                    "timestamp": self._iso(attempt.timestamp),
                    "change_description": attempt.change_description,
                    "config_section": attempt.config_section,
                    "status": attempt.status,
                    "score_before": round(attempt.score_before, 4),
                    "score_after": round(attempt.score_after, 4),
                    "delta": round(attempt.score_after - attempt.score_before, 4),
                    "config_diff": attempt.config_diff,
                    "diff_lines": [line for line in attempt.config_diff.splitlines() if line],
                }
            )
        return {"entries": entries}

    def config_payload(self) -> dict:
        """Build payload for `GET /api/config`."""
        active_config = self._active_config()
        versions = sorted(
            self.deployer.version_manager.get_version_history(),
            key=lambda item: item["version"],
            reverse=True,
        )
        canary_status = self.deployer.canary_manager.check_canary()

        return {
            "active_version": self._active_version_label(),
            "active_yaml": yaml.safe_dump(active_config, sort_keys=False),
            "versions": [
                {
                    "version": f"v{entry['version']:03d}",
                    "status": entry["status"],
                    "timestamp": self._iso(entry["timestamp"]),
                    "hash": entry["config_hash"],
                    "scores": entry.get("scores", {}),
                }
                for entry in versions
            ],
            "canary": {
                "is_active": canary_status.is_active,
                "canary_version": (
                    f"v{canary_status.canary_version:03d}"
                    if canary_status.canary_version is not None
                    else None
                ),
                "baseline_version": (
                    f"v{canary_status.baseline_version:03d}"
                    if canary_status.baseline_version is not None
                    else None
                ),
                "traffic_split": self.deployer.canary_manager.canary_percentage,
                "canary_conversations": canary_status.canary_conversations,
                "canary_success_rate": round(canary_status.canary_success_rate, 4),
                "baseline_success_rate": round(canary_status.baseline_success_rate, 4),
                "verdict": canary_status.verdict,
            },
        }

    def evals_payload(self) -> dict:
        """Build payload for `GET /api/evals`."""
        active_config = self._active_config()
        summary = self.eval_runner.run(config=active_config)

        categories: dict[str, dict] = {}
        for category in ("happy_path", "edge_case", "safety", "regression"):
            category_score = self.eval_runner.run_category(category, config=active_config)
            categories[category] = {
                "passed_cases": category_score.passed_cases,
                "total_cases": category_score.total_cases,
                "composite": round(category_score.composite, 4),
                "safety_failures": category_score.safety_failures,
            }

        return {
            "composite": {
                "quality": summary.quality,
                "safety": summary.safety,
                "latency": summary.latency,
                "cost": summary.cost,
                "composite": summary.composite,
                "passed_cases": summary.passed_cases,
                "total_cases": summary.total_cases,
            },
            "categories": categories,
            "cases": [
                {
                    "case_id": result.case_id,
                    "category": result.category,
                    "passed": result.passed,
                    "quality_score": result.quality_score,
                    "safety_passed": result.safety_passed,
                    "latency_ms": result.latency_ms,
                    "token_count": result.token_count,
                    "details": result.details,
                }
                for result in summary.results
            ],
        }

    def conversations_payload(self) -> dict:
        """Build payload for `GET /api/conversations`."""
        records = self.store.get_recent(limit=20)

        turn_counts: dict[str, int] = {}
        for session_id in {record.session_id for record in records}:
            turn_counts[session_id] = len(self.store.get_by_session(session_id))

        return {
            "conversations": [
                {
                    "conversation_id": record.conversation_id,
                    "session_id": record.session_id,
                    "timestamp": self._iso(record.timestamp),
                    "outcome": record.outcome,
                    "latency_ms": round(record.latency_ms, 2),
                    "cost": round(record.token_count * 0.001, 4),
                    "turns": turn_counts.get(record.session_id, 1),
                    "user_message": record.user_message,
                    "agent_response": record.agent_response,
                    "tool_calls": record.tool_calls,
                    "safety_flags": record.safety_flags,
                    "specialist_used": record.specialist_used,
                    "config_version": record.config_version,
                }
                for record in records
            ]
        }
