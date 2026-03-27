"""Unit tests for TranscriptIntelligenceService Ghostwriter-competitive features."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from dataclasses import dataclass

from optimizer.change_card import ChangeCardStore
from optimizer.transcript_intelligence import TranscriptIntelligenceService


@dataclass
class _Score:
    quality: float
    safety: float
    latency: float
    cost: float
    composite: float


class _FakeEvalRunner:
    def run(self, config: dict | None = None) -> _Score:
        cfg = config or {}
        root = str(cfg.get("prompts", {}).get("root", "")).lower()
        score = 0.72
        if "fallback" in root:
            score += 0.05
        if "verify" in root:
            score += 0.03
        return _Score(quality=score, safety=1.0, latency=0.8, cost=0.8, composite=score)


def _archive_base64() -> str:
    transcripts = [
        {
            "conversation_id": "svc-001",
            "session_id": "s1",
            "user_message": "Where is my order? I do not have the order number.",
            "agent_response": "I need to transfer you to live support.",
            "outcome": "transfer",
        },
        {
            "conversation_id": "svc-002",
            "session_id": "s2",
            "user_message": "Please cancel my order.",
            "agent_response": "First verify identity, then open the order and cancel it.",
            "outcome": "success",
        },
    ]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        zf.writestr("transcripts.json", json.dumps(transcripts))
        zf.writestr("playbook.txt", "Step 1: verify identity. Step 2: fallback lookup by email.")
        zf.writestr("whiteboard.jpg", "verify identity -> fallback lookup -> escalate")
        zf.writestr("call.mp3", b"fake-audio")
        zf.writestr("call.txt", "If the order number is missing, use email + zip fallback before escalation.")

    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_import_archive_creates_knowledge_asset() -> None:
    service = TranscriptIntelligenceService()

    report = service.import_archive("support.zip", _archive_base64())

    assert report.knowledge_asset["asset_id"]
    assert report.knowledge_asset["entry_count"] >= 3

    stored = service.get_knowledge_asset(report.knowledge_asset["asset_id"])
    assert stored is not None
    assert stored["asset_id"] == report.knowledge_asset["asset_id"]
    assert len(stored["entries"]) >= 3


def test_build_agent_artifact_emits_integration_templates() -> None:
    service = TranscriptIntelligenceService()

    artifact = service.build_agent_artifact(
        prompt=(
            "Build an order support agent. Verify identity, look up Shopify orders, "
            "cancel eligible orders, and create Zendesk tickets when escalation is needed."
        ),
        connectors=["Shopify", "Zendesk"],
    )

    templates = artifact.get("integration_templates", [])
    assert len(templates) >= 2
    assert any(t["connector"].lower() == "shopify" for t in templates)
    assert all("endpoint" in t and "method" in t for t in templates)


def test_deep_research_quantifies_root_causes() -> None:
    service = TranscriptIntelligenceService()
    report = service.import_archive("support.zip", _archive_base64())

    research = service.deep_research(report.report_id, "Why are transfers increasing?")

    assert research["question"]
    assert len(research["root_causes"]) >= 1
    assert all("attribution_pct" in cause for cause in research["root_causes"])
    assert len(research["recommendations"]) >= 1


def test_autonomous_cycle_runs_closed_loop(tmp_path) -> None:
    service = TranscriptIntelligenceService()
    report = service.import_archive("support.zip", _archive_base64())

    change_card_store = ChangeCardStore(db_path=str(tmp_path / "change_cards.db"))
    result = service.run_autonomous_cycle(
        report_id=report.report_id,
        eval_runner=_FakeEvalRunner(),
        change_card_store=change_card_store,
        current_config={"prompts": {"root": "You are a support assistant."}},
        auto_ship=False,
    )

    assert result["pipeline"]["analyze"]["status"] == "completed"
    assert result["pipeline"]["improve"]["status"] == "completed"
    assert result["pipeline"]["test"]["status"] == "completed"
    assert result["pipeline"]["ship"]["status"] in {"recommended", "ready_for_review"}
    assert result["change_card_id"]
