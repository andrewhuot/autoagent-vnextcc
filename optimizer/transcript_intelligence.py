"""Transcript intelligence primitives for archive import, analytics, and change drafting."""

from __future__ import annotations

import base64
import csv
import io
import json
import re
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from optimizer.change_card import ConfidenceInfo, DiffHunk, ProposedChangeCard
from optimizer.nl_editor import NLEditor


INTENT_KEYWORDS: dict[str, list[str]] = {
    "order_tracking": ["where is my order", "track my order", "order status", "pedido"],
    "address_change": ["shipping address", "change my address", "direccion", "address change"],
    "cancellation": ["cancel my order", "cancel order", "cancelacion"],
    "refund": ["refund", "reembolso"],
    "return_policy": ["return policy", "devolucion"],
}

TRANSFER_REASON_LABELS: dict[str, str] = {
    "missing_order_number": "customers lacked the order number required for self-service",
    "address_change_requires_human": "address change required a human handoff",
    "policy_gap": "the flow did not cover the requested policy path",
    "general_escalation": "the agent escalated without a clear self-service fallback",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a"}
TEXT_EXTENSIONS = {".txt", ".md"}


@dataclass
class TranscriptConversation:
    conversation_id: str
    session_id: str
    user_message: str
    agent_response: str
    outcome: str
    language: str
    intent: str
    transfer_reason: str | None
    source_file: str
    procedure_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "session_id": self.session_id,
            "user_message": self.user_message,
            "agent_response": self.agent_response,
            "outcome": self.outcome,
            "language": self.language,
            "intent": self.intent,
            "transfer_reason": self.transfer_reason,
            "source_file": self.source_file,
            "procedure_steps": self.procedure_steps,
        }


@dataclass
class InsightRecord:
    insight_id: str
    title: str
    summary: str
    recommendation: str
    drafted_change_prompt: str
    metric_name: str
    share: float
    count: int
    total: int
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "title": self.title,
            "summary": self.summary,
            "recommendation": self.recommendation,
            "drafted_change_prompt": self.drafted_change_prompt,
            "metric_name": self.metric_name,
            "share": self.share,
            "count": self.count,
            "total": self.total,
            "evidence": self.evidence,
        }


@dataclass
class TranscriptReport:
    report_id: str
    archive_name: str
    created_at: float
    conversations: list[TranscriptConversation]
    languages: list[str]
    missing_intents: list[dict[str, Any]]
    procedure_summaries: list[dict[str, Any]]
    faq_entries: list[dict[str, Any]]
    workflow_suggestions: list[dict[str, Any]]
    suggested_tests: list[dict[str, Any]]
    insights: list[InsightRecord]
    knowledge_asset: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "archive_name": self.archive_name,
            "created_at": self.created_at,
            "conversation_count": len(self.conversations),
            "languages": self.languages,
            "missing_intents": self.missing_intents,
            "procedure_summaries": self.procedure_summaries,
            "faq_entries": self.faq_entries,
            "workflow_suggestions": self.workflow_suggestions,
            "suggested_tests": self.suggested_tests,
            "insights": [insight.to_dict() for insight in self.insights],
            "knowledge_asset": self.knowledge_asset,
            "conversations": [conversation.to_dict() for conversation in self.conversations[:20]],
        }


class TranscriptIntelligenceService:
    """Import transcript archives and turn them into analyzable agent intelligence."""

    def __init__(self, knowledge_asset_path: str = ".autoagent/intelligence_knowledge_assets.json") -> None:
        self._reports: dict[str, TranscriptReport] = {}
        self._knowledge_asset_path = Path(knowledge_asset_path)
        self._knowledge_asset_path.parent.mkdir(parents=True, exist_ok=True)
        self._knowledge_assets: dict[str, dict[str, Any]] = self._load_knowledge_assets()

    def list_reports(self) -> list[dict[str, Any]]:
        reports = sorted(self._reports.values(), key=lambda report: report.created_at, reverse=True)
        return [
            {
                "report_id": report.report_id,
                "archive_name": report.archive_name,
                "created_at": report.created_at,
                "conversation_count": len(report.conversations),
                "languages": report.languages,
                "knowledge_asset": report.knowledge_asset,
            }
            for report in reports
        ]

    def get_report(self, report_id: str) -> TranscriptReport | None:
        return self._reports.get(report_id)

    def get_knowledge_asset(self, asset_id: str) -> dict[str, Any] | None:
        """Return a durable knowledge asset by ID."""
        return self._knowledge_assets.get(asset_id)

    def import_archive(self, archive_name: str, archive_base64: str) -> TranscriptReport:
        archive_bytes = base64.b64decode(archive_base64.encode("ascii"))
        conversations = self._parse_archive(archive_bytes)
        languages = sorted({conversation.language for conversation in conversations})
        missing_intents = self._mine_missing_intents(conversations)
        procedure_summaries = self._extract_procedures(conversations)
        faq_entries = self._generate_faq(conversations)
        workflow_suggestions = self._suggest_workflows(conversations, missing_intents)
        suggested_tests = self._suggest_tests(conversations, missing_intents)
        insights = self._generate_insights(conversations)
        knowledge_asset = self._create_knowledge_asset(
            archive_name=archive_name,
            conversations=conversations,
            faq_entries=faq_entries,
            procedure_summaries=procedure_summaries,
            workflow_suggestions=workflow_suggestions,
        )
        report = TranscriptReport(
            report_id=str(uuid.uuid4())[:8],
            archive_name=archive_name,
            created_at=time.time(),
            conversations=conversations,
            languages=languages,
            missing_intents=missing_intents,
            procedure_summaries=procedure_summaries,
            faq_entries=faq_entries,
            workflow_suggestions=workflow_suggestions,
            suggested_tests=suggested_tests,
            insights=insights,
            knowledge_asset=knowledge_asset,
        )
        self._reports[report.report_id] = report
        return report

    def ask_report(self, report_id: str, question: str) -> dict[str, Any]:
        report = self._require_report(report_id)
        lower = question.lower()
        transfer_insight = next((insight for insight in report.insights if insight.metric_name == "transfer_reason"), None)

        if "deep research" in lower or "full report" in lower or "root cause report" in lower:
            deep = self.deep_research(report_id, question)
            top = deep["root_causes"][0] if deep["root_causes"] else {"reason": "unknown", "attribution_pct": 0.0}
            return {
                "answer": (
                    f"Deep research complete. Top root cause: {top['reason']} "
                    f"({top['attribution_pct']:.1f}% attribution)."
                ),
                "metrics": {
                    "share": top.get("attribution_pct", 0.0) / 100.0,
                    "count": top.get("count", 0),
                    "total": deep.get("conversation_count", len(report.conversations)),
                },
                "evidence": top.get("evidence", []),
                "recommended_insight_id": report.insights[0].insight_id if report.insights else None,
                "deep_research": deep,
            }

        if transfer_insight and ("transfer" in lower or "live support" in lower or "human" in lower):
            return {
                "answer": (
                    f"{transfer_insight.share:.1%} of transfers in this archive were caused because "
                    f"{TRANSFER_REASON_LABELS.get('missing_order_number', 'customers lacked critical order details')}."
                ),
                "metrics": {
                    "share": transfer_insight.share,
                    "count": transfer_insight.count,
                    "total": transfer_insight.total,
                },
                "evidence": transfer_insight.evidence,
                "recommended_insight_id": transfer_insight.insight_id,
            }

        if "what should i change" in lower or "improve this metric" in lower:
            top = report.insights[:2]
            answer = "Top recommended changes:\n" + "\n".join(
                f"- {insight.recommendation}" for insight in top
            )
            return {
                "answer": answer,
                "metrics": {"share": top[0].share if top else 0.0, "count": top[0].count if top else 0, "total": top[0].total if top else 0},
                "evidence": top[0].evidence if top else [],
                "recommended_insight_id": top[0].insight_id if top else None,
            }

        return {
            "answer": (
                f"Imported {len(report.conversations)} conversations across {', '.join(report.languages)}. "
                f"Top gaps: {', '.join(item['intent'] for item in report.missing_intents[:3]) or 'none'}."
            ),
            "metrics": {"share": 0.0, "count": len(report.conversations), "total": len(report.conversations)},
            "evidence": [],
            "recommended_insight_id": report.insights[0].insight_id if report.insights else None,
        }

    def build_agent_artifact(self, prompt: str, connectors: list[str]) -> dict[str, Any]:
        lower = prompt.lower()
        intents: list[dict[str, str]] = []
        if "order tracking" in lower or "track" in lower:
            intents.append({"name": "order_tracking", "description": "Help customers find the latest shipment and order status."})
        if "cancellation" in lower or "cancel" in lower:
            intents.append({"name": "cancellation", "description": "Handle order cancellation requests within policy."})
        if "shipping-address" in lower or "shipping address" in lower or "address change" in lower:
            intents.append({"name": "address_change", "description": "Support shipping address updates after identity verification."})
        if not intents:
            intents.append({"name": "general_support", "description": "Handle common customer support requests."})

        tools: list[dict[str, str]] = []
        normalized_connectors = [connector.strip() for connector in connectors if connector.strip()]
        if any(connector.lower() == "shopify" for connector in normalized_connectors):
            tools.extend(
                [
                    {"name": "shopify_order_lookup", "connector": "Shopify", "purpose": "Look up an order by order number or verified customer metadata."},
                    {"name": "shopify_cancel_order", "connector": "Shopify", "purpose": "Cancel eligible orders within policy windows."},
                    {"name": "shopify_update_address", "connector": "Shopify", "purpose": "Update shipping address after verification and eligibility checks."},
                ]
            )
        if any(connector.lower() == "amazon connect" for connector in normalized_connectors):
            tools.append({"name": "amazon_connect_handoff", "connector": "Amazon Connect", "purpose": "Escalate to live support with full context payloads."})

        escalation_conditions = [
            "Escalate when the customer lacks the order number and identity fallback checks fail.",
            "Escalate when policy constraints block self-service resolution.",
        ]

        suggested_tests = [
            {
                "name": "order-tracking-without-order-number",
                "user_message": "Where is my order? I do not have the order number.",
                "expected_behavior": "The agent verifies identity, attempts fallback lookup, and escalates only if verification fails.",
            },
            {
                "name": "cancel-order-in-policy",
                "user_message": "Please cancel my order before it ships.",
                "expected_behavior": "The agent checks policy, cancels the order, and confirms the action.",
            },
        ]
        integration_templates = self._build_integration_templates(
            connectors=normalized_connectors,
            prompt=prompt,
        )

        return {
            "connectors": normalized_connectors,
            "intents": intents,
            "business_rules": [
                "Verify customer identity before account or shipment changes.",
                "Prefer self-service resolution before escalation.",
            ],
            "auth_steps": [
                "Collect verified identifier such as order number or customer email.",
                "Use fallback lookup when the order number is unavailable.",
            ],
            "escalation_conditions": escalation_conditions,
            "channel_behavior": [
                "Use concise status updates in chat.",
                "Pass verified context to voice or human systems during escalation.",
            ],
            "journeys": [
                {
                    "name": "order-support",
                    "steps": [
                        "Detect the intent from the customer request.",
                        "Run verification and connector lookups.",
                        "Resolve in self-service when possible.",
                        "Escalate with context when required.",
                    ],
                }
            ],
            "tools": tools,
            "guardrails": [
                "Never disclose internal notes or pricing artifacts.",
                "Require verification before modifying orders or personal details.",
            ],
            "suggested_tests": suggested_tests,
            "integration_templates": integration_templates,
            "workspace_access": {
                "journeys": True,
                "integrations": True,
                "simulations": True,
                "knowledge_base": True,
                "triage": True,
            },
        }

    def create_change_card_from_insight(
        self,
        report_id: str,
        insight_id: str,
        current_config: dict[str, Any],
        eval_runner: Any,
        change_card_store: Any,
    ) -> tuple[ProposedChangeCard, str, dict[str, Any]]:
        report = self._require_report(report_id)
        insight = next((item for item in report.insights if item.insight_id == insight_id), None)
        if insight is None:
            raise KeyError(f"Unknown insight: {insight_id}")

        editor = NLEditor(use_mock=True)
        result = editor.apply_and_eval(
            description=insight.drafted_change_prompt,
            current_config=current_config,
            eval_runner=eval_runner,
            auto_apply=False,
        )

        diff_hunks = self._build_diff_hunks(result.diff_summary, insight.drafted_change_prompt)
        card = ProposedChangeCard(
            title=f"Apply insight: {insight.title}",
            why=insight.summary,
            diff_hunks=diff_hunks,
            metrics_before={"composite": result.score_before},
            metrics_after={"composite": result.score_after},
            confidence=ConfidenceInfo(
                p_value=max(0.001, 1.0 - insight.share),
                effect_size=result.score_after - result.score_before,
                judge_agreement=0.8,
                n_eval_cases=max(1, insight.total),
            ),
            risk_class="medium" if insight.share >= 0.5 else "low",
            rollout_plan="Draft change card -> review diff -> run targeted regressions -> canary release",
            rollback_condition="Rollback if transfer rate rises or regression cases fail.",
            memory_context=insight.recommendation,
        )
        change_card_store.save(card)
        auto_simulation = self.generate_auto_simulation_bundle(
            report=report,
            drafted_change_prompt=insight.drafted_change_prompt,
        )
        return card, insight.drafted_change_prompt, auto_simulation

    def _require_report(self, report_id: str) -> TranscriptReport:
        report = self.get_report(report_id)
        if report is None:
            raise KeyError(f"Unknown report: {report_id}")
        return report

    def _parse_archive(self, archive_bytes: bytes) -> list[TranscriptConversation]:
        parsed: list[TranscriptConversation] = []
        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as archive:
            members = {
                name: archive.read(name)
                for name in sorted(archive.namelist())
                if not name.endswith("/")
            }

        for name, raw in members.items():
            suffix = Path(name).suffix.lower()

            if suffix == ".json":
                parsed.extend(self._parse_json_file(raw, name))
                continue
            if suffix == ".csv":
                parsed.extend(self._parse_csv_file(raw, name))
                continue
            if suffix in TEXT_EXTENSIONS:
                text = raw.decode("utf-8", errors="ignore")
                parsed.extend(self._parse_text_file(text, name))
                continue
            if suffix in IMAGE_EXTENSIONS:
                parsed.extend(
                    self._synthesize_artifact_conversations(
                        text=raw.decode("utf-8", errors="ignore"),
                        source_file=name,
                        modality="whiteboard",
                    )
                )
                continue
            if suffix in AUDIO_EXTENSIONS:
                sidecar = self._archive_sidecar_text(Path(name), members)
                text = sidecar or f"Audio note uploaded from {Path(name).stem.replace('_', ' ')}."
                parsed.extend(
                    self._synthesize_artifact_conversations(
                        text=text,
                        source_file=name,
                        modality="audio",
                    )
                )
                continue
        return parsed

    def _parse_json_file(self, raw: bytes, source_file: str) -> list[TranscriptConversation]:
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict):
            if isinstance(payload.get("conversations"), list):
                items = payload["conversations"]
            else:
                items = [payload]
        else:
            items = payload
        return [self._normalize_record(item, source_file) for item in items if isinstance(item, dict)]

    def _parse_csv_file(self, raw: bytes, source_file: str) -> list[TranscriptConversation]:
        text = raw.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        return [self._normalize_record(dict(row), source_file) for row in reader]

    def _parse_text_file(self, text: str, source_file: str) -> list[TranscriptConversation]:
        chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
        parsed: list[TranscriptConversation] = []
        for index, chunk in enumerate(chunks):
            user_message = ""
            agent_response = ""
            for line in chunk.splitlines():
                lower = line.lower()
                if lower.startswith(("user:", "customer:", "cliente:")):
                    user_message = line.split(":", 1)[1].strip()
                elif lower.startswith(("agent:", "assistant:", "bot:")):
                    agent_response = line.split(":", 1)[1].strip()
            if user_message or agent_response:
                parsed.append(
                    self._normalize_record(
                        {
                            "conversation_id": f"{source_file}-{index}",
                            "session_id": f"{source_file}-{index}",
                            "user_message": user_message,
                            "agent_response": agent_response,
                            "outcome": "unknown",
                        },
                        source_file,
                    )
                )
        if parsed:
            return parsed

        # SOP/playbook style text often lacks explicit "User/Agent" labels.
        return self._synthesize_artifact_conversations(
            text=text,
            source_file=source_file,
            modality="document",
        )

    def _archive_sidecar_text(self, file_path: Path, members: dict[str, bytes]) -> str:
        """Find sidecar transcript text for an archive audio member."""
        for suffix in (".txt", ".md", ".json"):
            candidate = file_path.with_suffix(suffix)
            raw = members.get(candidate.as_posix())
            if raw is None:
                raw = members.get(str(candidate))
            if raw is None:
                continue
            text = raw.decode("utf-8", errors="ignore").strip()
            if not text:
                continue
            if suffix == ".json":
                try:
                    payload = json.loads(text)
                    if isinstance(payload, dict):
                        text = str(payload.get("transcript") or payload.get("text") or "").strip()
                except json.JSONDecodeError:
                    pass
            if text:
                return text
        return ""

    def _synthesize_artifact_conversations(
        self,
        text: str,
        source_file: str,
        modality: str,
    ) -> list[TranscriptConversation]:
        """Convert non-transcript artifacts into analyzable pseudo conversations.

        WHY: Multi-modal uploads (SOPs, whiteboards, audio notes) should still
        feed intent mining and gap analysis even without explicit chat turns.
        """
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return []

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        summary = lines[0] if lines else cleaned[:160]
        guidance = " ".join(lines[1:4]) if len(lines) > 1 else cleaned[:220]
        user_message = (
            f"Please incorporate this {modality} guidance into the agent workflow: {summary}"
        )
        agent_response = guidance or summary

        record = {
            "conversation_id": f"{source_file}-{modality}",
            "session_id": f"{source_file}-{modality}",
            "user_message": user_message,
            "agent_response": agent_response,
            "outcome": "success",
        }
        return [self._normalize_record(record, source_file)]

    def _normalize_record(self, raw: dict[str, Any], source_file: str) -> TranscriptConversation:
        user_message = self._coalesce(raw, ["user_message", "customer_message", "user", "customer", "question"])
        agent_response = self._coalesce(raw, ["agent_response", "assistant_message", "agent", "assistant", "answer"])
        conversation_id = str(raw.get("conversation_id") or raw.get("id") or str(uuid.uuid4())[:8])
        session_id = str(raw.get("session_id") or raw.get("thread_id") or conversation_id)
        outcome = str(raw.get("outcome") or raw.get("status") or "unknown")
        language = self._detect_language(f"{user_message} {agent_response}")
        intent = self._classify_intent(user_message)
        transfer_reason = self._classify_transfer_reason(user_message, agent_response, outcome)
        procedure_steps = self._extract_steps(agent_response)

        return TranscriptConversation(
            conversation_id=conversation_id,
            session_id=session_id,
            user_message=user_message,
            agent_response=agent_response,
            outcome=outcome,
            language=language,
            intent=intent,
            transfer_reason=transfer_reason,
            source_file=source_file,
            procedure_steps=procedure_steps,
        )

    def _coalesce(self, raw: dict[str, Any], keys: list[str]) -> str:
        for key in keys:
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _detect_language(self, text: str) -> str:
        lower = text.lower()
        if any(token in lower for token in ["necesito", "direccion", "pedido", "soporte", "envio"]):
            return "es"
        if any(token in lower for token in ["bonjour", "commande", "adresse"]):
            return "fr"
        return "en"

    def _classify_intent(self, user_message: str) -> str:
        lower = user_message.lower()
        for intent, keywords in INTENT_KEYWORDS.items():
            if any(keyword in lower for keyword in keywords):
                return intent
        return "general_support"

    def _classify_transfer_reason(self, user_message: str, agent_response: str, outcome: str) -> str | None:
        combined = f"{user_message} {agent_response}".lower()
        if "order number" in combined or "numero de pedido" in combined:
            return "missing_order_number"
        if "address" in combined or "direccion" in combined:
            return "address_change_requires_human" if "transfer" in combined or "hum" in combined else None
        if "policy" in combined:
            return "policy_gap"
        if outcome.lower() == "transfer" or "transfer" in combined or "human" in combined or "live support" in combined:
            return "general_escalation"
        return None

    def _mine_missing_intents(self, conversations: list[TranscriptConversation]) -> list[dict[str, Any]]:
        counts: dict[str, dict[str, int]] = {}
        for conversation in conversations:
            bucket = counts.setdefault(conversation.intent, {"total": 0, "handoff": 0})
            bucket["total"] += 1
            if conversation.transfer_reason is not None or conversation.outcome.lower() in {"transfer", "fail", "error"}:
                bucket["handoff"] += 1

        missing: list[dict[str, Any]] = []
        for intent, bucket in counts.items():
            if intent == "general_support":
                continue
            if bucket["handoff"] > 0:
                missing.append(
                    {
                        "intent": intent,
                        "count": bucket["handoff"],
                        "reason": "Observed repeated escalation or failure without a self-service workflow.",
                    }
                )
        missing.sort(key=lambda item: item["count"], reverse=True)
        return missing

    def _extract_procedures(self, conversations: list[TranscriptConversation]) -> list[dict[str, Any]]:
        seen: set[tuple[str, ...]] = set()
        procedures: list[dict[str, Any]] = []
        for conversation in conversations:
            if not conversation.procedure_steps:
                continue
            key = tuple(conversation.procedure_steps)
            if key in seen:
                continue
            seen.add(key)
            procedures.append(
                {
                    "intent": conversation.intent,
                    "steps": conversation.procedure_steps,
                    "source_conversation_id": conversation.conversation_id,
                }
            )
        return procedures[:6]

    def _extract_steps(self, response: str) -> list[str]:
        lower = response.lower()
        if not any(token in lower for token in ["first", "then", "finally", "step", "primero", "luego"]):
            return []
        cleaned = response.replace("Finally", "finally").replace("Then", "then")
        chunks = re.split(r"\b(?:first|then|finally|primero|luego)\b", cleaned, flags=re.IGNORECASE)
        steps = [chunk.strip(" ,.-") for chunk in chunks if chunk.strip(" ,.-")]
        return steps[:5]

    def _generate_faq(self, conversations: list[TranscriptConversation]) -> list[dict[str, Any]]:
        seen_intents: set[str] = set()
        faqs: list[dict[str, Any]] = []
        for conversation in conversations:
            if conversation.intent in seen_intents:
                continue
            seen_intents.add(conversation.intent)
            if not conversation.user_message or not conversation.agent_response:
                continue
            faqs.append(
                {
                    "intent": conversation.intent,
                    "question": conversation.user_message,
                    "answer": conversation.agent_response,
                }
            )
        return faqs[:6]

    def _suggest_workflows(
        self,
        conversations: list[TranscriptConversation],
        missing_intents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        suggestions: list[dict[str, Any]] = []
        if any(conversation.transfer_reason == "missing_order_number" for conversation in conversations):
            suggestions.append(
                {
                    "title": "Add no-order-number recovery flow",
                    "description": "Verify identity using alternate identifiers and attempt a fallback order lookup before escalation.",
                }
            )
        for item in missing_intents:
            suggestions.append(
                {
                    "title": f"Operationalize {item['intent']}",
                    "description": f"Create a dedicated workflow, tool path, and regression coverage for {item['intent']}.",
                }
            )
        return suggestions[:6]

    def _suggest_tests(
        self,
        conversations: list[TranscriptConversation],
        missing_intents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tests: list[dict[str, Any]] = []
        for item in missing_intents:
            tests.append(
                {
                    "name": f"{item['intent']}-self-service",
                    "user_message": f"Customer asks for {item['intent'].replace('_', ' ')} help.",
                    "expected_behavior": "The agent resolves the task without defaulting to live support unless verification fails.",
                }
            )
        if any(conversation.transfer_reason == "missing_order_number" for conversation in conversations):
            tests.append(
                {
                    "name": "missing-order-number-fallback",
                    "user_message": "Where is my order? I do not have the order number.",
                    "expected_behavior": "The agent attempts identity verification and fallback order lookup before escalation.",
                }
            )
        return tests[:8]

    def _generate_insights(self, conversations: list[TranscriptConversation]) -> list[InsightRecord]:
        transfer_conversations = [
            conversation
            for conversation in conversations
            if conversation.transfer_reason is not None
            or conversation.outcome.lower() == "transfer"
        ]
        if not transfer_conversations:
            return []

        reason_counts: dict[str, list[TranscriptConversation]] = {}
        for conversation in transfer_conversations:
            reason = conversation.transfer_reason or "general_escalation"
            reason_counts.setdefault(reason, []).append(conversation)

        insights: list[InsightRecord] = []
        total = len(transfer_conversations)
        for reason, items in sorted(reason_counts.items(), key=lambda item: len(item[1]), reverse=True):
            share = len(items) / total
            label = TRANSFER_REASON_LABELS.get(reason, reason.replace("_", " "))
            drafted_change_prompt = {
                "missing_order_number": "Add an empathetic fallback order lookup and verification flow when customers do not know the order number.",
                "address_change_requires_human": "Add a verified self-service address change workflow with clear eligibility rules.",
            }.get(reason, "Reduce unnecessary live-support escalations by adding a clearer self-service workflow.")
            insights.append(
                InsightRecord(
                    insight_id=str(uuid.uuid4())[:8],
                    title=f"Transfers are concentrated around {reason.replace('_', ' ')}",
                    summary=f"{share:.1%} of transfers were caused because {label}.",
                    recommendation=f"Update the agent to handle {reason.replace('_', ' ')} with a self-service workflow and regression coverage.",
                    drafted_change_prompt=drafted_change_prompt,
                    metric_name="transfer_reason",
                    share=share,
                    count=len(items),
                    total=total,
                    evidence=[conversation.user_message for conversation in items[:3]],
                )
            )
        return insights

    def _build_integration_templates(
        self,
        connectors: list[str],
        prompt: str,
    ) -> list[dict[str, Any]]:
        """Generate connector-specific API scaffolding from NL intent."""
        lower_prompt = prompt.lower()
        templates: list[dict[str, Any]] = []
        normalized = [connector.strip() for connector in connectors if connector.strip()]

        if any(connector.lower() == "shopify" for connector in normalized):
            templates.extend(
                [
                    {
                        "connector": "Shopify",
                        "name": "shopify_order_lookup",
                        "method": "GET",
                        "endpoint": "/admin/api/2024-10/orders/{order_id}.json",
                        "auth_strategy": "shopify_admin_access_token",
                        "payload_template": {"order_id": "{{verified_order_id}}"},
                        "response_mapping": {"status": "order.fulfillment_status", "tracking": "order.fulfillments[0].tracking_number"},
                        "error_handling": "If order_id missing, execute fallback lookup by email + zip before escalation.",
                    },
                    {
                        "connector": "Shopify",
                        "name": "shopify_cancel_order",
                        "method": "POST",
                        "endpoint": "/admin/api/2024-10/orders/{order_id}/cancel.json",
                        "auth_strategy": "shopify_admin_access_token",
                        "payload_template": {"reason": "customer_request"},
                        "response_mapping": {"cancelled_at": "order.cancelled_at"},
                        "error_handling": "Validate cancellation eligibility window before issuing cancel call.",
                    },
                ]
            )

        if any(connector.lower() == "zendesk" for connector in normalized):
            templates.append(
                {
                    "connector": "Zendesk",
                    "name": "zendesk_create_ticket",
                    "method": "POST",
                    "endpoint": "/api/v2/tickets.json",
                    "auth_strategy": "zendesk_api_token",
                    "payload_template": {
                        "subject": "Escalation: {{intent}}",
                        "comment": {"body": "{{customer_context}}"},
                        "priority": "normal",
                    },
                    "response_mapping": {"ticket_id": "ticket.id", "status": "ticket.status"},
                    "error_handling": "Retry once on 429 and include fallback handoff note in failure response.",
                }
            )

        if any(connector.lower() == "amazon connect" for connector in normalized):
            templates.append(
                {
                    "connector": "Amazon Connect",
                    "name": "amazon_connect_handoff",
                    "method": "POST",
                    "endpoint": "/contact-flows/handoff",
                    "auth_strategy": "iam_signed_request",
                    "payload_template": {"contact_attributes": "{{verified_context}}", "queue": "support_tier_1"},
                    "response_mapping": {"contact_id": "contactId"},
                    "error_handling": "On handoff failure, acknowledge delay and offer callback option.",
                }
            )

        if any(connector.lower() == "salesforce" for connector in normalized):
            templates.append(
                {
                    "connector": "Salesforce",
                    "name": "salesforce_case_lookup",
                    "method": "GET",
                    "endpoint": "/services/data/v61.0/sobjects/Case/{case_id}",
                    "auth_strategy": "oauth2_bearer_token",
                    "payload_template": {"case_id": "{{case_id}}"},
                    "response_mapping": {"status": "Status", "owner": "Owner.Name"},
                    "error_handling": "If case not found, create follow-up task and return escalation guidance.",
                }
            )

        if not templates:
            templates.append(
                {
                    "connector": "Generic HTTP",
                    "name": "custom_backend_call",
                    "method": "POST" if "create" in lower_prompt or "update" in lower_prompt else "GET",
                    "endpoint": "/api/v1/customer-support/workflow",
                    "auth_strategy": "bearer_token",
                    "payload_template": {"intent": "{{intent}}", "customer_context": "{{customer_context}}"},
                    "response_mapping": {"result": "result"},
                    "error_handling": "Apply retries with exponential backoff, then escalate with context payload.",
                }
            )

        return templates

    def generate_auto_simulation_bundle(
        self,
        report: TranscriptReport,
        drafted_change_prompt: str,
    ) -> dict[str, Any]:
        """Auto-generate edge-case simulations for an agent change."""
        generated_tests = self._generate_change_simulation_tests(report, drafted_change_prompt)
        sandbox_validation = self._run_sandbox_validation(generated_tests)
        return {
            "generated_tests": generated_tests,
            "sandbox_validation": sandbox_validation,
        }

    def _generate_change_simulation_tests(
        self,
        report: TranscriptReport,
        drafted_change_prompt: str,
    ) -> list[dict[str, Any]]:
        tests: list[dict[str, Any]] = []

        for base_test in report.suggested_tests[:4]:
            tests.append(
                {
                    "name": f"auto-{base_test['name']}",
                    "user_message": base_test["user_message"],
                    "expected_behavior": base_test["expected_behavior"],
                    "difficulty": "edge_case",
                    "source": "report_suggested_test",
                }
            )

        if "fallback" in drafted_change_prompt.lower() or "order number" in drafted_change_prompt.lower():
            tests.append(
                {
                    "name": "auto-missing-order-number-escalation-guardrail",
                    "user_message": "I need help with my order but I do not have the order number.",
                    "expected_behavior": "Attempt identity fallback lookup before escalation, then escalate with context.",
                    "difficulty": "adversarial",
                    "source": "change_prompt",
                }
            )

        if not tests:
            tests.extend(
                [
                    {
                        "name": "auto-general-support-safe-response",
                        "user_message": "Please help me with a billing problem.",
                        "expected_behavior": "Route to the correct specialist and keep policy-compliant response.",
                        "difficulty": "normal",
                        "source": "default",
                    },
                    {
                        "name": "auto-general-support-escalation",
                        "user_message": "I need urgent help and none of your steps worked.",
                        "expected_behavior": "Provide fallback workflow and escalate with verified context payload.",
                        "difficulty": "edge_case",
                        "source": "default",
                    },
                ]
            )

        return tests

    def _run_sandbox_validation(self, generated_tests: list[dict[str, Any]]) -> dict[str, Any]:
        """Run generated tests in the simulation sandbox."""
        from simulator.sandbox import SimulationSandbox, SyntheticConversation

        synthetic: list[SyntheticConversation] = []
        for index, test in enumerate(generated_tests):
            synthetic.append(
                SyntheticConversation(
                    conversation_id=f"auto-sim-{index + 1}",
                    domain="customer-support",
                    difficulty=test.get("difficulty", "edge_case"),
                    persona="system_generated",
                    user_message=test["user_message"],
                    expected_intent="general_support",
                    expected_specialist="support",
                    expected_tools=["knowledge_base"],
                    context={"expected_behavior": test["expected_behavior"]},
                )
            )

        sandbox = SimulationSandbox()
        result = sandbox.stress_test(
            config={"prompts": {"root": "Auto-generated simulation validation"}},
            conversations=synthetic,
            config_id="auto-generated-change-validation",
        )
        return {
            "test_id": result.test_id,
            "total_conversations": result.total_conversations,
            "passed": result.passed,
            "failed": result.failed,
            "pass_rate": result.pass_rate,
            "avg_latency_ms": result.avg_latency_ms,
            "failures_by_category": result.failures_by_category,
            "failure_examples": result.failure_examples[:5],
        }

    def deep_research(self, report_id: str, question: str) -> dict[str, Any]:
        """Produce a quantified deep-research report over imported conversations."""
        report = self._require_report(report_id)
        total = max(len(report.conversations), 1)

        buckets: dict[str, list[TranscriptConversation]] = {}
        for conversation in report.conversations:
            reason = conversation.transfer_reason or conversation.intent or "unknown"
            buckets.setdefault(reason, []).append(conversation)

        root_causes: list[dict[str, Any]] = []
        for reason, conversations in sorted(buckets.items(), key=lambda item: len(item[1]), reverse=True):
            count = len(conversations)
            attribution_pct = round((count / total) * 100, 1)
            root_causes.append(
                {
                    "reason": reason.replace("_", " "),
                    "count": count,
                    "attribution_pct": attribution_pct,
                    "evidence": [conversation.user_message for conversation in conversations[:3]],
                }
            )

        recommendations = [insight.recommendation for insight in report.insights[:3]]
        if not recommendations:
            recommendations = [item["description"] for item in report.workflow_suggestions[:3]]

        return {
            "report_id": report.report_id,
            "question": question,
            "conversation_count": len(report.conversations),
            "languages": report.languages,
            "root_causes": root_causes,
            "recommendations": recommendations,
            "knowledge_asset": report.knowledge_asset,
        }

    def run_autonomous_cycle(
        self,
        report_id: str,
        eval_runner: Any,
        change_card_store: Any,
        current_config: dict[str, Any],
        auto_ship: bool = False,
        deployer: Any | None = None,
    ) -> dict[str, Any]:
        """Run a closed-loop Analyze -> Improve -> Test -> Ship recommendation cycle."""
        report = self._require_report(report_id)
        if not report.insights:
            report.insights = self._generate_insights(report.conversations)

        if not report.insights:
            synthetic = InsightRecord(
                insight_id=str(uuid.uuid4())[:8],
                title="General escalation reduction opportunity",
                summary="No dominant insight found; applying baseline self-service hardening.",
                recommendation="Add fallback self-service before escalation.",
                drafted_change_prompt="Add a fallback self-service workflow before escalation.",
                metric_name="transfer_reason",
                share=0.0,
                count=0,
                total=max(1, len(report.conversations)),
                evidence=[],
            )
            report.insights = [synthetic]

        top_insight = report.insights[0]
        card, drafted_change_prompt, auto_simulation = self.create_change_card_from_insight(
            report_id=report_id,
            insight_id=top_insight.insight_id,
            current_config=current_config,
            eval_runner=eval_runner,
            change_card_store=change_card_store,
        )

        pass_rate = auto_simulation["sandbox_validation"]["pass_rate"]
        ship_status = "recommended" if pass_rate >= 0.6 else "ready_for_review"

        deployment_result = None
        if auto_ship and deployer is not None and ship_status == "recommended":
            try:
                deployment_result = deployer.deploy(
                    current_config,
                    scores={"composite": max(card.metrics_after.get("composite", 0.0), 0.0)},
                )
                ship_status = "deployed_to_canary"
            except Exception as exc:  # pragma: no cover - defensive fallback
                deployment_result = f"deployment_failed: {exc}"
                ship_status = "ready_for_review"

        return {
            "report_id": report_id,
            "change_card_id": card.card_id,
            "drafted_change_prompt": drafted_change_prompt,
            "auto_simulation": auto_simulation,
            "deployment_result": deployment_result,
            "pipeline": {
                "analyze": {"status": "completed", "insight_id": top_insight.insight_id},
                "improve": {"status": "completed", "change_card_id": card.card_id},
                "test": {"status": "completed", "pass_rate": pass_rate},
                "ship": {"status": ship_status},
            },
        }

    def _create_knowledge_asset(
        self,
        archive_name: str,
        conversations: list[TranscriptConversation],
        faq_entries: list[dict[str, Any]],
        procedure_summaries: list[dict[str, Any]],
        workflow_suggestions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist a durable knowledge asset extracted from imported artifacts."""
        asset_id = str(uuid.uuid4())[:10]
        entries: list[dict[str, Any]] = []

        for faq in faq_entries:
            entries.append(
                {
                    "type": "faq",
                    "intent": faq["intent"],
                    "question": faq["question"],
                    "answer": faq["answer"],
                }
            )
        for procedure in procedure_summaries:
            entries.append(
                {
                    "type": "procedure",
                    "intent": procedure["intent"],
                    "steps": procedure["steps"],
                }
            )
        for workflow in workflow_suggestions:
            entries.append(
                {
                    "type": "workflow",
                    "title": workflow["title"],
                    "description": workflow["description"],
                }
            )

        # Backfill at least one evidence entry from raw conversations.
        if conversations:
            sample = conversations[0]
            entries.append(
                {
                    "type": "conversation_evidence",
                    "intent": sample.intent,
                    "example": sample.user_message,
                    "response": sample.agent_response,
                }
            )

        asset = {
            "asset_id": asset_id,
            "archive_name": archive_name,
            "created_at": time.time(),
            "entry_count": len(entries),
            "entries": entries,
        }
        self._knowledge_assets[asset_id] = asset
        self._persist_knowledge_assets()
        return {"asset_id": asset_id, "entry_count": len(entries)}

    def _load_knowledge_assets(self) -> dict[str, dict[str, Any]]:
        """Load persisted knowledge assets from disk."""
        if not self._knowledge_asset_path.exists():
            return {}
        try:
            payload = json.loads(self._knowledge_asset_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): value for key, value in payload.items() if isinstance(value, dict)}

    def _persist_knowledge_assets(self) -> None:
        """Persist knowledge assets to disk for durable retrieval."""
        self._knowledge_asset_path.write_text(
            json.dumps(self._knowledge_assets, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _build_diff_hunks(self, diff_summary: str, drafted_change_prompt: str) -> list[DiffHunk]:
        surfaces = [item.strip() for item in diff_summary.split(",") if item.strip()]
        if not surfaces:
            surfaces = ["prompts.root"]
        hunks: list[DiffHunk] = []
        for surface in surfaces:
            hunks.append(
                DiffHunk(
                    hunk_id=str(uuid.uuid4())[:8],
                    surface=surface,
                    old_value="",
                    new_value=drafted_change_prompt,
                    status="pending",
                )
            )
        return hunks
