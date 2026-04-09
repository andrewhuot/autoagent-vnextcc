"""Unit tests for TranscriptIntelligenceService Ghostwriter-competitive features."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from optimizer.change_card import ChangeCardStore
from optimizer.transcript_intelligence import TranscriptIntelligenceService
from shared.transcript_report_store import TranscriptReportStore


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


class _StubLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _StubLLMRouter:
    def __init__(
        self,
        responses: list[str],
        *,
        mock_mode: bool = False,
        fail: bool = False,
        models: list[object] | None = None,
    ) -> None:
        self.responses = list(responses)
        self.mock_mode = mock_mode
        self.fail = fail
        self.requests: list[object] = []
        self.models = list(models or [])

    def generate(self, request: object) -> _StubLLMResponse:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("router unavailable")
        if self.responses:
            return _StubLLMResponse(self.responses.pop(0))
        return _StubLLMResponse('{"intent": "general_support", "confidence": 0.5}')


def _archive_base64(
    transcripts: list[dict] | None = None,
    *,
    include_artifacts: bool = True,
) -> str:
    if transcripts is None:
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
        if include_artifacts:
            zf.writestr("playbook.txt", "Step 1: verify identity. Step 2: fallback lookup by email.")
            zf.writestr("whiteboard.jpg", "verify identity -> fallback lookup -> escalate")
            zf.writestr("call.mp3", b"fake-audio")
            zf.writestr("call.txt", "If the order number is missing, use email + zip fallback before escalation.")

    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _service(
    tmp_path: Path,
    *,
    llm_router: object | None = None,
    report_store_path: Path | None = None,
) -> TranscriptIntelligenceService:
    return TranscriptIntelligenceService(
        llm_router=llm_router,
        knowledge_asset_path=str(tmp_path / "intelligence-assets.json"),
        report_store=TranscriptReportStore(report_store_path or (tmp_path / "transcript-reports.json")),
    )


def test_import_archive_creates_knowledge_asset() -> None:
    service = TranscriptIntelligenceService()

    report = service.import_archive("support.zip", _archive_base64())

    assert report.knowledge_asset["asset_id"]
    assert report.knowledge_asset["entry_count"] >= 3

    stored = service.get_knowledge_asset(report.knowledge_asset["asset_id"])
    assert stored is not None
    assert stored["asset_id"] == report.knowledge_asset["asset_id"]
    assert len(stored["entries"]) >= 3


def test_import_archive_persists_report_for_a_fresh_service_instance(tmp_path: Path) -> None:
    report_store_path = tmp_path / "transcript-reports.json"
    service = _service(tmp_path, report_store_path=report_store_path)

    report = service.import_archive("support.zip", _archive_base64())

    fresh_service = _service(tmp_path, report_store_path=report_store_path)

    reports = fresh_service.list_reports()
    assert [item["report_id"] for item in reports] == [report.report_id]

    loaded = fresh_service.get_report(report.report_id)
    assert loaded is not None
    assert loaded.report_id == report.report_id
    assert loaded.archive_name == "support.zip"
    assert len(loaded.conversations) == len(report.conversations)

    generated = fresh_service.generate_agent_config("Build a support agent", transcript_report_id=report.report_id)
    assert generated["metadata"]["created_from"] == "transcript"


def test_generate_agent_config_falls_back_to_prd_reviewer_shape_when_live_router_is_throttled(tmp_path: Path) -> None:
    router = _StubLLMRouter(
        responses=[],
        fail=True,
        models=[
            SimpleNamespace(provider="openai", model="gpt-4o"),
            SimpleNamespace(provider="google", model="gemini-2.5-pro"),
        ],
    )
    service = _service(tmp_path, llm_router=router)

    generated = service.generate_agent_config(
        "Build an agent that reviews product requirement documents, flags missing acceptance criteria, and proposes stronger evaluation cases for regressions."
    )

    assert service.last_generation_used_llm is False
    assert service.last_generation_failure_reason == "router unavailable"
    assert generated["metadata"]["agent_name"] == "PRD Review Agent"
    assert generated["model"] == "gemini-2.5-pro"
    assert "acceptance criteria" in generated["system_prompt"].lower()
    assert {tool["name"] for tool in generated["tools"]} >= {"document_lookup", "eval_case_generator"}


def test_import_archive_uses_llm_intent_classification_when_real_router_available(tmp_path: Path) -> None:
    router = _StubLLMRouter(
        responses=[
            '{"intent": "order_tracking", "confidence": 0.97}',
            '{"intent": "refund", "confidence": 0.94}',
        ]
    )
    service = _service(tmp_path, llm_router=router)

    report = service.import_archive(
        "support.zip",
        _archive_base64(
            [
                {
                    "conversation_id": "svc-101",
                    "session_id": "s101",
                    "user_message": "Where is my package right now?",
                    "agent_response": "Let me check that for you.",
                    "outcome": "success",
                    "intent": "order_tracking",
                },
                {
                    "conversation_id": "svc-102",
                    "session_id": "s102",
                    "user_message": "I want my money back for this order.",
                    "agent_response": "I can help with that refund.",
                    "outcome": "success",
                    "intent": "refund",
                },
            ],
            include_artifacts=False,
        ),
    )

    assert [conversation.intent for conversation in report.conversations[:2]] == ["order_tracking", "refund"]
    assert report.intent_accuracy == 1.0
    assert report.intent_accuracy_samples == 2
    assert len(router.requests) >= 2


def test_import_archive_falls_back_to_keywords_when_router_is_mock(tmp_path: Path) -> None:
    router = _StubLLMRouter(
        responses=['{"intent": "general_support", "confidence": 0.1}'],
        mock_mode=True,
    )
    service = _service(tmp_path, llm_router=router)

    report = service.import_archive(
        "support.zip",
        _archive_base64(
            [
                {
                    "conversation_id": "svc-201",
                    "session_id": "s201",
                    "user_message": "Please cancel my order.",
                    "agent_response": "I can do that after verification.",
                    "outcome": "success",
                    "intent": "cancellation",
                }
            ],
            include_artifacts=False,
        ),
    )

    assert report.conversations[0].intent == "cancellation"
    assert report.intent_accuracy == 1.0
    assert report.intent_accuracy_samples == 1
    assert router.requests == []


def test_import_archive_falls_back_to_keywords_when_llm_payload_is_invalid(tmp_path: Path) -> None:
    router = _StubLLMRouter(responses=["not-json"])
    service = _service(tmp_path, llm_router=router)

    report = service.import_archive(
        "support.zip",
        _archive_base64(
            [
                {
                    "conversation_id": "svc-301",
                    "session_id": "s301",
                    "user_message": "Can I get a refund for this order?",
                    "agent_response": "I can help with that.",
                    "outcome": "success",
                    "intent": "refund",
                }
            ],
            include_artifacts=False,
        ),
    )

    assert report.conversations[0].intent == "refund"
    assert report.intent_accuracy == 1.0
    assert report.intent_accuracy_samples == 1


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

    assert result["cycles_run"] >= 1
    assert result["max_cycles"] == 1
    assert result["final_cycle"]["change_card_id"]
    assert result["pipeline"]["analyze"]["status"] == "completed"
    assert result["pipeline"]["improve"]["status"] == "completed"
    assert result["pipeline"]["test"]["status"] == "completed"
    assert result["pipeline"]["ship"]["status"] in {"recommended", "ready_for_review"}
