"""Unit tests for dashboard data aggregation payloads."""

from __future__ import annotations

import time

from deployer import Deployer
from evals.runner import EvalRunner
from logger.store import ConversationStore
from optimizer.memory import OptimizationAttempt, OptimizationMemory

from agent.dashboard_data import DashboardDataService
from tests.helpers import build_record


def _build_service(tmp_path, base_config: dict) -> DashboardDataService:
    store = ConversationStore(str(tmp_path / "conversations.db"))
    memory = OptimizationMemory(str(tmp_path / "optimizer_memory.db"))
    deployer = Deployer(configs_dir=str(tmp_path / "configs"), store=store)
    deployer.version_manager.save_version(base_config, scores={"composite": 0.78}, status="active")
    return DashboardDataService(
        store=store,
        memory=memory,
        deployer=deployer,
        eval_runner=EvalRunner(),
        app_started_at=time.time() - 120,
        current_config_provider=lambda: base_config,
    )


def test_health_payload_includes_metrics_and_trends(tmp_path, base_config: dict) -> None:
    """Health payload should return KPI values and 24-point trend arrays."""
    service = _build_service(tmp_path, base_config)
    service.store.log(build_record(outcome="success", latency_ms=100.0, token_count=200, config_version="v001"))
    service.store.log(build_record(outcome="fail", latency_ms=250.0, token_count=300, config_version="v001"))

    payload = service.health_payload()

    assert payload["config_version"].startswith("v")
    assert payload["health_score"]["value"] >= 0
    assert payload["metrics"]["success_rate"] >= 0
    assert len(payload["trends"]["success_rate"]) == 24
    assert len(payload["trends"]["avg_latency_ms"]) == 24
    assert "journey" in payload
    assert payload["journey"]["total_steps"] == 4


def test_health_payload_journey_tracks_progress_and_wins(tmp_path, base_config: dict) -> None:
    """Journey metadata should include next action, checklist, and recent wins."""
    service = _build_service(tmp_path, base_config)
    service.store.log(build_record(outcome="success", config_version="v001"))
    service.memory.log(
        OptimizationAttempt(
            attempt_id="win123",
            timestamp=time.time(),
            change_description="Improve refund routing",
            config_diff="+ route keywords",
            status="accepted",
            config_section="routing",
            score_before=0.71,
            score_after=0.79,
        )
    )

    payload = service.health_payload()
    journey = payload["journey"]
    assert journey["progress_pct"] > 0
    assert journey["next_action"]["command"]
    assert journey["recent_wins"]
    assert len(journey["checklist"]) == 4


def test_history_payload_contains_recent_attempts(tmp_path, base_config: dict) -> None:
    """History payload should expose attempt metadata and config diffs."""
    service = _build_service(tmp_path, base_config)
    service.memory.log(
        OptimizationAttempt(
            attempt_id="abc12345",
            timestamp=time.time(),
            change_description="Improve prompts",
            config_diff="~ prompts.root: 'A' -> 'B'",
            status="accepted",
            config_section="prompts",
            score_before=0.70,
            score_after=0.82,
        )
    )

    payload = service.history_payload()
    assert payload["entries"]
    first = payload["entries"][0]
    assert first["change_description"] == "Improve prompts"
    assert first["config_section"] == "prompts"
    assert first["diff_lines"]


def test_config_payload_includes_yaml_and_version_history(tmp_path, base_config: dict) -> None:
    """Config payload should return active YAML and version metadata."""
    service = _build_service(tmp_path, base_config)
    payload = service.config_payload()

    assert "model:" in payload["active_yaml"]
    assert payload["active_version"].startswith("v")
    assert payload["versions"]


def test_evals_payload_contains_category_breakdown(tmp_path, base_config: dict) -> None:
    """Eval payload should return composite score and per-category summaries."""
    service = _build_service(tmp_path, base_config)
    payload = service.evals_payload()

    assert payload["composite"]["composite"] >= 0
    assert {"happy_path", "edge_case", "safety", "regression"} <= set(payload["categories"].keys())
    assert payload["cases"]


def test_conversations_payload_contains_recent_items(tmp_path, base_config: dict) -> None:
    """Conversation payload should return recent conversation cards with turn counts."""
    service = _build_service(tmp_path, base_config)
    service.store.log(
        build_record(
            session_id="session-a",
            user_message="Where is my order?",
            agent_response="It is in transit and arriving tomorrow.",
            outcome="success",
            tool_calls=[{"tool": "orders_db", "status": "ok"}],
            config_version="v001",
        )
    )
    service.store.log(
        build_record(
            session_id="session-a",
            user_message="Can I cancel?",
            agent_response="Yes, I can cancel that for you.",
            outcome="success",
            config_version="v001",
        )
    )

    payload = service.conversations_payload()
    assert len(payload["conversations"]) == 2
    assert payload["conversations"][0]["turns"] >= 1
