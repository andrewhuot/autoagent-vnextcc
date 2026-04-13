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
from optimizer.providers import LLMRequest, LLMRouter
from shared.transcript_report_store import TranscriptReportStore


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
RAW_UPLOAD_EXTENSIONS = {".json", ".csv", ".txt", ".md", ".jsonl"}
KNOWN_INTENTS = tuple(INTENT_KEYWORDS.keys()) + ("general_support",)


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
    reference_intent: str | None = None
    intent_match: bool | None = None

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
    intent_accuracy: float | None = None
    intent_accuracy_samples: int = 0
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
            "intent_accuracy": self.intent_accuracy,
            "intent_accuracy_samples": self.intent_accuracy_samples,
            "knowledge_asset": self.knowledge_asset,
            "conversations": [conversation.to_dict() for conversation in self.conversations[:20]],
        }


def _conversation_from_dict(data: dict[str, Any]) -> TranscriptConversation:
    """Reconstruct a transcript conversation from persisted data."""

    return TranscriptConversation(
        conversation_id=str(data.get("conversation_id", "")),
        session_id=str(data.get("session_id", "")),
        user_message=str(data.get("user_message", "")),
        agent_response=str(data.get("agent_response", "")),
        outcome=str(data.get("outcome", "")),
        language=str(data.get("language", "en")),
        intent=str(data.get("intent", "general_support")),
        transfer_reason=data.get("transfer_reason"),
        source_file=str(data.get("source_file", "")),
        procedure_steps=list(data.get("procedure_steps", [])),
        reference_intent=data.get("reference_intent"),
        intent_match=data.get("intent_match"),
    )


def _report_from_dict(data: dict[str, Any]) -> TranscriptReport:
    """Reconstruct a transcript report from persisted data."""

    conversations = [_conversation_from_dict(item) for item in data.get("conversations", [])]
    insights = [InsightRecord(**item) for item in data.get("insights", [])]
    return TranscriptReport(
        report_id=str(data["report_id"]),
        archive_name=str(data.get("archive_name", "")),
        created_at=float(data.get("created_at", 0.0)),
        conversations=conversations,
        languages=list(data.get("languages", [])),
        missing_intents=list(data.get("missing_intents", [])),
        procedure_summaries=list(data.get("procedure_summaries", [])),
        faq_entries=list(data.get("faq_entries", [])),
        workflow_suggestions=list(data.get("workflow_suggestions", [])),
        suggested_tests=list(data.get("suggested_tests", [])),
        insights=insights,
        intent_accuracy=data.get("intent_accuracy"),
        intent_accuracy_samples=int(data.get("intent_accuracy_samples", 0)),
        knowledge_asset=dict(data.get("knowledge_asset", {})),
    )


class TranscriptIntelligenceService:
    """Import transcript archives and turn them into analyzable agent intelligence."""

    def __init__(
        self,
        knowledge_asset_path: str = ".agentlab/intelligence_knowledge_assets.json",
        report_store: TranscriptReportStore | None = None,
        llm_router: LLMRouter | None = None,
    ) -> None:
        self._report_store = report_store or TranscriptReportStore()
        self._knowledge_asset_path = Path(knowledge_asset_path)
        self._knowledge_asset_path.parent.mkdir(parents=True, exist_ok=True)
        self._knowledge_assets: dict[str, dict[str, Any]] = self._load_knowledge_assets()
        self._llm_router = llm_router
        self._reports: dict[str, TranscriptReport] = self._load_reports_from_store()
        self.last_generation_used_llm = False
        self.last_refinement_used_llm = False
        self.last_generation_failure_reason = ""
        self.last_refinement_failure_reason = ""

    def list_reports(self) -> list[dict[str, Any]]:
        self._reports = self._load_reports_from_store()
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
        report = self._reports.get(report_id)
        if report is not None:
            return report
        stored_report = self._report_store.get_report(report_id)
        if stored_report is None:
            return None
        report = _report_from_dict(stored_report)
        self._reports[report_id] = report
        return report

    def get_knowledge_asset(self, asset_id: str) -> dict[str, Any] | None:
        """Return a durable knowledge asset by ID."""
        return self._knowledge_assets.get(asset_id)

    def import_archive(self, archive_name: str, archive_base64: str) -> TranscriptReport:
        """Import transcript archive from base64-encoded zip file.

        Raises:
            ValueError: If archive format is invalid or cannot be parsed.
        """
        try:
            archive_bytes = base64.b64decode(archive_base64.encode("ascii"))
        except Exception as exc:
            raise ValueError(f"Invalid base64 encoding: {exc}") from exc

        conversations = self._parse_uploaded_payload(archive_name, archive_bytes)
        if not conversations:
            raise ValueError("Archive contains no parseable conversations")
        languages = sorted({conversation.language for conversation in conversations})
        missing_intents = self._mine_missing_intents(conversations)
        procedure_summaries = self._extract_procedures(conversations)
        faq_entries = self._generate_faq(conversations)
        workflow_suggestions = self._suggest_workflows(conversations, missing_intents)
        suggested_tests = self._suggest_tests(conversations, missing_intents)
        insights = self._generate_insights(conversations)
        intent_accuracy, intent_accuracy_samples = self._compute_intent_accuracy(conversations)
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
            intent_accuracy=intent_accuracy,
            intent_accuracy_samples=intent_accuracy_samples,
            knowledge_asset=knowledge_asset,
        )
        self._reports[report.report_id] = report
        self._report_store.save_report(report)
        return report

    def _load_reports_from_store(self) -> dict[str, TranscriptReport]:
        """Load durable transcript reports into the in-memory cache."""

        reports: dict[str, TranscriptReport] = {}
        for report_data in self._report_store.list_reports():
            report = _report_from_dict(report_data)
            reports[report.report_id] = report
        return reports

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

    def _looks_like_saas_support_prompt(self, lower_prompt: str) -> bool:
        """Return whether a prompt describes a SaaS FAQ/support agent.

        WHY: Words like "billing" appear in both finance and SaaS support
        prompts. This guard keeps fallback generation anchored to the broader
        requested product-support shape instead of drifting into banking.
        """
        has_support_context = any(
            term in lower_prompt
            for term in (
                "faq",
                "knowledge base",
                "kb",
                "product setup",
                "troubleshooting",
                "help center",
                "support agent",
            )
        )
        has_saas_context = any(
            term in lower_prompt
            for term in (
                "saas",
                "b2b",
                "account plan",
                "plan status",
                "security question",
                "billing plan",
            )
        )
        return has_support_context and has_saas_context

    def _extract_requested_agent_name(self, prompt: str) -> str | None:
        """Extract an explicitly named agent from leading build/create phrasing."""
        match = re.search(
            r"\b(?i:build|create|make)\s+([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,3})(?=,|\s+(?:a|an|for|that|to)\b|$)",
            prompt.strip(),
        )
        if match is None:
            return None
        name = re.sub(r"\s+", " ", match.group(1)).strip()
        return name or None

    def generate_agent_config(
        self,
        prompt: str,
        transcript_report_id: str | None = None,
        *,
        instruction_xml: str | None = None,
        requested_model: str | None = None,
        requested_agent_name: str | None = None,
        tool_hints: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate a structured agent config dict from a natural language prompt.

        Args:
            prompt: Natural language description of the desired agent.
            transcript_report_id: Optional report ID whose insights should be incorporated.

        Returns:
            YAML-friendly dict with system_prompt, tools, routing_rules, policies,
            eval_criteria, and metadata keys.
        """
        llm_generated = self._generate_agent_config_with_llm(
            prompt=prompt,
            transcript_report_id=transcript_report_id,
            instruction_xml=instruction_xml,
            requested_model=requested_model,
            requested_agent_name=requested_agent_name,
            tool_hints=tool_hints,
        )
        if llm_generated is not None:
            self.last_generation_used_llm = True
            return llm_generated
        self.last_generation_used_llm = False

        lower = prompt.lower()

        # --- domain detection (scored matcher) ---
        # Score each domain by keyword hits; ties break by list order (priority).
        _domain_keywords: list[tuple[str, tuple[str, ...]]] = [
            ("customer_service", ("customer service", "customer support", "support", "help desk", "helpdesk", "faq", "knowledge base")),
            ("product_review", (
                "prd",
                "product requirement",
                "product requirements",
                "requirements document",
                "acceptance criteria",
                "regression eval",
                "regression test",
                "review product",
                "review requirement",
            )),
            ("healthcare", ("health", "medical", "patient", "clinic", "doctor")),
            ("hr", ("hr", "human resource", "employee", "onboard", "payroll")),
            ("sales", ("sales", "lead", "prospect", "crm", "deal")),
            ("ecommerce", ("ecommerce", "e-commerce", "shop", "order", "shipping", "cart")),
            ("finance", ("finance", "banking", "invoice", "accounting", "wire transfer", "fraud", "billing", "payment")),
        ]
        _scores: list[tuple[int, int, str]] = []  # (-hits, priority_idx, domain)
        for idx, (candidate, keywords) in enumerate(_domain_keywords):
            hits = sum(1 for kw in keywords if kw in lower)
            if hits:
                _scores.append((-hits, idx, candidate))
        _scores.sort()
        domain = _scores[0][2] if _scores else "general"
        if self._looks_like_saas_support_prompt(lower):
            domain = "saas_support"

        # --- derive a short agent name from the prompt ---
        explicit_agent_name = self._extract_requested_agent_name(prompt)
        agent_name_words = [w.capitalize() for w in re.findall(r"[a-z]+", lower) if len(w) > 3][:3]
        if requested_agent_name:
            agent_name = requested_agent_name
        elif explicit_agent_name:
            agent_name = explicit_agent_name
        elif any(term in lower for term in ("airline", "flight", "travel", "booking", "reservation")):
            agent_name = "AirlineCustomerSupportAgent"
        elif domain == "product_review":
            agent_name = "PRD Review Agent"
        elif domain == "saas_support":
            agent_name = "SaaS FAQ Support Agent"
        else:
            agent_name = "".join(agent_name_words) + "Agent" if agent_name_words else "AgentLab"

        # ---- domain-specific system prompts ----
        _system_prompts: dict[str, str] = {
            "customer_service": (
                "You are a friendly and efficient customer service agent. "
                "Your primary goal is to resolve customer issues quickly and accurately on the first interaction. "
                "Always greet the customer warmly, identify their issue, and provide a clear resolution path.\n\n"
                "Verify customer identity before accessing or modifying account details. "
                "Prefer self-service resolution over escalation. When escalation is necessary, "
                "transfer full context so the customer does not have to repeat themselves.\n\n"
                "Maintain a professional and empathetic tone at all times. "
                "If you cannot resolve an issue, acknowledge it clearly and set realistic expectations."
            ),
            "sales": (
                "You are a consultative sales assistant. Your role is to understand prospect needs, "
                "qualify leads, and guide potential customers toward the right solution.\n\n"
                "Ask open-ended discovery questions before pitching. Focus on value and outcomes, "
                "not features. Never apply high-pressure tactics. "
                "Qualify prospects using BANT (Budget, Authority, Need, Timeline) criteria.\n\n"
                "When a prospect is ready to proceed, guide them through the next steps clearly "
                "and hand off to a human account executive when the deal value warrants it."
            ),
            "healthcare": (
                "You are a healthcare information assistant. You provide general health information "
                "and help patients navigate scheduling, billing, and administrative tasks.\n\n"
                "You do NOT provide medical diagnoses or prescribe treatments. "
                "Always recommend consulting a qualified healthcare professional for medical decisions. "
                "Handle patient data with strict confidentiality in compliance with HIPAA regulations.\n\n"
                "For urgent or emergency situations, immediately direct the patient to call emergency services "
                "or visit the nearest emergency room."
            ),
            "finance": (
                "You are a financial services assistant. You help customers understand their accounts, "
                "transactions, and available financial products.\n\n"
                "Never share sensitive financial information without proper identity verification. "
                "All advice is informational only and does not constitute financial advice. "
                "Direct customers to a certified financial advisor for investment decisions.\n\n"
                "Flag and escalate any suspected fraudulent activity immediately."
            ),
            "ecommerce": (
                "You are an e-commerce support agent. You assist customers with order tracking, "
                "returns, exchanges, shipping, and product questions.\n\n"
                "Verify customer identity using order number or email before accessing order details. "
                "Follow the return and refund policy strictly. "
                "Proactively provide order updates and shipping estimates.\n\n"
                "Escalate to a human agent for complex disputes, high-value orders, or when policy "
                "does not cover the customer's situation."
            ),
            "hr": (
                "You are an HR assistant helping employees with questions about benefits, policies, "
                "payroll, and onboarding.\n\n"
                "Maintain strict confidentiality with all employee data. "
                "Provide accurate information about company policies and direct employees to the "
                "appropriate HR specialist for complex matters.\n\n"
                "For sensitive issues such as workplace disputes or performance matters, "
                "immediately escalate to an HR Business Partner."
            ),
            "product_review": (
                "You are a PRD review and evaluation design assistant. "
                "Your job is to inspect product requirement documents, identify missing or weak acceptance criteria, "
                "and propose stronger regression-oriented evaluation cases.\n\n"
                "Ground every review comment in the supplied PRD text or referenced evidence. "
                "When information is missing, say exactly what is missing instead of inventing requirements. "
                "Separate factual observations from recommendations.\n\n"
                "When asked for stronger tests, produce concrete eval ideas that target likely regressions, edge cases, "
                "and ambiguity in the document."
            ),
            "saas_support": (
                "You are a calm, concise B2B SaaS FAQ support agent. "
                "You answer product setup, plan and billing, security, and troubleshooting questions using approved "
                "internal knowledge base guidance.\n\n"
                "Cite the relevant knowledge base article or policy summary when giving an answer. "
                "For unclear billing, account plan, or security requests, create an escalation ticket with a concise "
                "context summary instead of guessing. Do not expose internal-only notes or unsupported security claims.\n\n"
                "Keep responses practical and easy to follow. When a user needs a step-by-step setup answer, provide "
                "numbered steps and confirm the next action."
            ),
            "general": (
                "You are a helpful, accurate, and professional AI assistant. "
                "Your goal is to provide clear and actionable responses to user requests.\n\n"
                "When you are uncertain, say so clearly and offer to help find the right information. "
                "Maintain a consistent, friendly tone. Respect user privacy and handle sensitive "
                "information with care.\n\n"
                "Escalate to a human operator when you cannot confidently resolve the user's request."
            ),
        }

        # ---- domain-specific tools ----
        _tools_by_domain: dict[str, list[dict[str, Any]]] = {
            "customer_service": [
                {
                    "name": "lookup_customer",
                    "description": "Look up a customer record by email or account ID.",
                    "parameters": {"identifier": "string — email or account_id"},
                },
                {
                    "name": "get_ticket_history",
                    "description": "Retrieve previous support tickets for a customer.",
                    "parameters": {"customer_id": "string"},
                },
                {
                    "name": "create_ticket",
                    "description": "Open a new support ticket and assign to the correct queue.",
                    "parameters": {"customer_id": "string", "subject": "string", "body": "string", "priority": "low|medium|high"},
                },
                {
                    "name": "escalate_to_human",
                    "description": "Transfer the conversation to a live agent with full context.",
                    "parameters": {"reason": "string", "context_summary": "string"},
                },
            ],
            "sales": [
                {
                    "name": "lookup_crm_record",
                    "description": "Retrieve CRM data for a prospect or contact.",
                    "parameters": {"email": "string"},
                },
                {
                    "name": "create_lead",
                    "description": "Create or update a lead record in the CRM.",
                    "parameters": {"name": "string", "email": "string", "company": "string", "notes": "string"},
                },
                {
                    "name": "schedule_demo",
                    "description": "Book a product demo with an account executive.",
                    "parameters": {"prospect_email": "string", "preferred_times": "list[string]"},
                },
                {
                    "name": "send_proposal",
                    "description": "Generate and send a product proposal to the prospect.",
                    "parameters": {"prospect_email": "string", "package": "string"},
                },
            ],
            "healthcare": [
                {
                    "name": "get_appointment_slots",
                    "description": "Retrieve available appointment slots for a provider.",
                    "parameters": {"provider_id": "string", "date_range": "string"},
                },
                {
                    "name": "book_appointment",
                    "description": "Schedule an appointment for a patient.",
                    "parameters": {"patient_id": "string", "provider_id": "string", "slot": "string"},
                },
                {
                    "name": "get_patient_info",
                    "description": "Retrieve non-clinical patient administrative data.",
                    "parameters": {"patient_id": "string"},
                },
            ],
            "finance": [
                {
                    "name": "get_account_summary",
                    "description": "Retrieve account balance and recent transaction summary.",
                    "parameters": {"account_id": "string"},
                },
                {
                    "name": "initiate_transfer",
                    "description": "Initiate a funds transfer between verified accounts.",
                    "parameters": {"from_account": "string", "to_account": "string", "amount": "number"},
                },
                {
                    "name": "flag_fraud",
                    "description": "Flag a transaction or account for fraud review.",
                    "parameters": {"account_id": "string", "reason": "string"},
                },
            ],
            "ecommerce": [
                {
                    "name": "lookup_order",
                    "description": "Retrieve order details by order ID or customer email.",
                    "parameters": {"order_id": "string | null", "email": "string | null"},
                },
                {
                    "name": "initiate_return",
                    "description": "Start a return or exchange for an eligible order.",
                    "parameters": {"order_id": "string", "reason": "string", "items": "list[string]"},
                },
                {
                    "name": "process_refund",
                    "description": "Issue a refund to the original payment method.",
                    "parameters": {"order_id": "string", "amount": "number | null"},
                },
                {
                    "name": "update_shipping_address",
                    "description": "Update the shipping address for an unshipped order.",
                    "parameters": {"order_id": "string", "new_address": "object"},
                },
            ],
            "hr": [
                {
                    "name": "get_employee_profile",
                    "description": "Look up an employee's HR profile and benefits enrollment.",
                    "parameters": {"employee_id": "string"},
                },
                {
                    "name": "submit_time_off_request",
                    "description": "Submit a PTO or leave request on behalf of an employee.",
                    "parameters": {"employee_id": "string", "start_date": "string", "end_date": "string", "type": "string"},
                },
                {
                    "name": "get_policy_document",
                    "description": "Retrieve a specific HR policy document by name.",
                    "parameters": {"policy_name": "string"},
                },
            ],
            "product_review": [
                {
                    "name": "document_lookup",
                    "description": "Inspect a PRD section, referenced requirement, or evidence snippet before making a review comment.",
                    "parameters": {"input": "string"},
                },
                {
                    "name": "eval_case_generator",
                    "description": "Draft stronger regression-oriented evaluation cases for the product document under review.",
                    "parameters": {"input": "string"},
                },
                {
                    "name": "escalate_to_human",
                    "description": "Escalate unclear product decisions or missing business context to a human reviewer.",
                    "parameters": {"reason": "string", "context_summary": "string"},
                },
            ],
            "saas_support": [
                {
                    "name": "search_knowledge_base",
                    "description": "Search approved SaaS help center and internal KB guidance for product, billing, security, and troubleshooting answers.",
                    "parameters": {"query": "string", "topic": "product_setup|billing|security|troubleshooting|general"},
                },
                {
                    "name": "check_account_plan",
                    "description": "Check the customer's current plan, feature entitlements, and billing status after identity verification.",
                    "parameters": {"account_id": "string", "requested_capability": "string | null"},
                },
                {
                    "name": "create_escalation_ticket",
                    "description": "Create an escalation ticket for unclear billing, security, or account-specific issues with full conversation context.",
                    "parameters": {"account_id": "string | null", "reason": "string", "context_summary": "string", "priority": "low|medium|high"},
                },
            ],
            "general": [
                {
                    "name": "search_knowledge_base",
                    "description": "Search the internal knowledge base for relevant articles.",
                    "parameters": {"query": "string"},
                },
                {
                    "name": "escalate_to_human",
                    "description": "Transfer the session to a human operator.",
                    "parameters": {"reason": "string", "context_summary": "string"},
                },
            ],
        }

        # ---- domain-specific routing rules ----
        _routing_by_domain: dict[str, list[dict[str, Any]]] = {
            "customer_service": [
                {"condition": "intent == 'complaint' and sentiment == 'negative'", "action": "escalate_to_human", "priority": 1},
                {"condition": "identity_verified == false and action_required == true", "action": "request_verification", "priority": 2},
                {"condition": "ticket_age_hours > 48", "action": "flag_for_manager_review", "priority": 3},
                {"condition": "default", "action": "self_service_resolution", "priority": 99},
            ],
            "sales": [
                {"condition": "deal_value > 50000", "action": "route_to_enterprise_ae", "priority": 1},
                {"condition": "lead_score < 20", "action": "nurture_sequence", "priority": 2},
                {"condition": "prospect_stage == 'demo_requested'", "action": "schedule_demo", "priority": 3},
                {"condition": "default", "action": "qualify_lead", "priority": 99},
            ],
            "healthcare": [
                {"condition": "urgency == 'emergency'", "action": "direct_to_emergency_services", "priority": 1},
                {"condition": "topic == 'clinical_advice'", "action": "decline_and_refer_to_provider", "priority": 2},
                {"condition": "patient_verified == false", "action": "verify_patient_identity", "priority": 3},
                {"condition": "default", "action": "handle_administrative_request", "priority": 99},
            ],
            "finance": [
                {"condition": "fraud_signals_detected == true", "action": "flag_fraud_and_escalate", "priority": 1},
                {"condition": "identity_verified == false", "action": "require_mfa_verification", "priority": 2},
                {"condition": "transaction_amount > 10000", "action": "require_additional_approval", "priority": 3},
                {"condition": "default", "action": "self_service_banking", "priority": 99},
            ],
            "ecommerce": [
                {"condition": "order_value > 500 and issue_type == 'dispute'", "action": "escalate_to_human", "priority": 1},
                {"condition": "order_status == 'delivered' and return_window_expired == true", "action": "apply_goodwill_policy", "priority": 2},
                {"condition": "identity_verified == false", "action": "verify_via_order_number_or_email", "priority": 3},
                {"condition": "default", "action": "standard_order_support", "priority": 99},
            ],
            "hr": [
                {"condition": "topic == 'workplace_dispute'", "action": "escalate_to_hrbp", "priority": 1},
                {"condition": "employee_verified == false", "action": "verify_employee_identity", "priority": 2},
                {"condition": "topic == 'payroll_discrepancy'", "action": "route_to_payroll_team", "priority": 3},
                {"condition": "default", "action": "answer_policy_question", "priority": 99},
            ],
            "product_review": [
                {"condition": "request mentions missing acceptance criteria or unclear requirements", "action": "review_acceptance_criteria", "priority": 1},
                {"condition": "request asks for evidence, cited sections, or referenced requirements", "action": "document_lookup", "priority": 2},
                {"condition": "request asks for harder tests, regressions, or eval coverage", "action": "generate_regression_evals", "priority": 3},
                {"condition": "default", "action": "review_and_summarize_prd", "priority": 99},
            ],
            "saas_support": [
                {"condition": "topic in ['product_setup', 'troubleshooting'] and kb_article_found == true", "action": "answer_product_faq", "priority": 1},
                {"condition": "topic in ['billing', 'account_plan'] and identity_verified == true", "action": "check_account_plan", "priority": 2},
                {"condition": "topic in ['billing', 'security'] and confidence_score < 0.7", "action": "escalate_billing_or_security", "priority": 3},
                {"condition": "default", "action": "answer_from_knowledge_base", "priority": 99},
            ],
            "general": [
                {"condition": "confidence_score < 0.4", "action": "escalate_to_human", "priority": 1},
                {"condition": "topic == 'sensitive'", "action": "apply_safety_guardrails", "priority": 2},
                {"condition": "default", "action": "answer_from_knowledge_base", "priority": 99},
            ],
        }

        # ---- domain-specific policies ----
        _policies_by_domain: dict[str, list[dict[str, Any]]] = {
            "customer_service": [
                {"name": "identity_verification", "description": "Verify customer identity before accessing or modifying account data.", "enforcement": "hard_block"},
                {"name": "no_pii_in_logs", "description": "Strip PII from all logs and analytics pipelines.", "enforcement": "hard_block"},
                {"name": "escalation_with_context", "description": "Always pass a context summary when escalating to a human agent.", "enforcement": "required"},
                {"name": "response_time_sla", "description": "Initial response must be within 30 seconds.", "enforcement": "monitored"},
            ],
            "sales": [
                {"name": "no_high_pressure_tactics", "description": "Prohibit urgency manipulation or false scarcity claims.", "enforcement": "hard_block"},
                {"name": "accurate_pricing", "description": "Only quote prices from the current approved price book.", "enforcement": "hard_block"},
                {"name": "gdpr_consent", "description": "Capture explicit consent before storing prospect data.", "enforcement": "required"},
            ],
            "healthcare": [
                {"name": "hipaa_compliance", "description": "All patient data handling must comply with HIPAA privacy and security rules.", "enforcement": "hard_block"},
                {"name": "no_clinical_advice", "description": "Do not provide diagnoses, treatment plans, or prescription guidance.", "enforcement": "hard_block"},
                {"name": "emergency_referral", "description": "Always direct emergency situations to emergency services immediately.", "enforcement": "hard_block"},
            ],
            "finance": [
                {"name": "strong_authentication", "description": "Require MFA for any account modification or fund transfer.", "enforcement": "hard_block"},
                {"name": "fraud_monitoring", "description": "Apply real-time fraud detection on all transactions.", "enforcement": "hard_block"},
                {"name": "no_investment_advice", "description": "Do not provide investment recommendations without required licensing disclosures.", "enforcement": "hard_block"},
                {"name": "transaction_limits", "description": "Enforce per-session transaction limits as defined by compliance policy.", "enforcement": "required"},
            ],
            "ecommerce": [
                {"name": "return_policy_adherence", "description": "Follow the published return policy; escalate exceptions for manager approval.", "enforcement": "required"},
                {"name": "no_unauthorized_refunds", "description": "Refunds must meet policy criteria and be logged for audit.", "enforcement": "hard_block"},
                {"name": "order_verification", "description": "Verify order ownership before disclosing or modifying order details.", "enforcement": "hard_block"},
            ],
            "hr": [
                {"name": "employee_confidentiality", "description": "Never disclose one employee's information to another without authorization.", "enforcement": "hard_block"},
                {"name": "equal_treatment", "description": "Provide consistent policy information to all employees regardless of level.", "enforcement": "required"},
                {"name": "escalate_sensitive_topics", "description": "Workplace disputes, harassment claims, and performance issues must be escalated to HR.", "enforcement": "hard_block"},
            ],
            "product_review": [
                {"name": "evidence_grounding", "description": "Every review comment must cite the supplied PRD text, section, or referenced evidence.", "enforcement": "hard_block"},
                {"name": "no_fabricated_requirements", "description": "Never invent product requirements, acceptance criteria, owners, or timelines that are not in evidence.", "enforcement": "hard_block"},
                {"name": "regression_focus", "description": "Favor concrete regression risks, edge cases, and measurable acceptance checks over generic feedback.", "enforcement": "required"},
            ],
            "saas_support": [
                {"name": "kb_grounding", "description": "Answers must be grounded in approved knowledge base guidance or clearly state that the answer is unavailable.", "enforcement": "required"},
                {"name": "billing_security_escalation", "description": "Unclear billing, account plan, or security issues must be escalated with full context instead of guessed.", "enforcement": "hard_block"},
                {"name": "no_internal_notes", "description": "Never expose internal-only KB notes, security implementation details, or private ticket metadata.", "enforcement": "hard_block"},
            ],
            "general": [
                {"name": "safety_guardrails", "description": "Refuse requests for harmful, illegal, or unethical content.", "enforcement": "hard_block"},
                {"name": "hallucination_prevention", "description": "Do not fabricate facts; acknowledge uncertainty when knowledge is incomplete.", "enforcement": "required"},
                {"name": "user_privacy", "description": "Do not store or repeat sensitive personal information unnecessarily.", "enforcement": "required"},
            ],
        }

        # ---- domain-specific eval criteria ----
        _evals_by_domain: dict[str, list[dict[str, Any]]] = {
            "customer_service": [
                {"name": "first_contact_resolution", "weight": 0.35, "description": "Percentage of issues resolved without requiring a follow-up or escalation."},
                {"name": "customer_satisfaction_score", "weight": 0.30, "description": "Post-interaction CSAT score from 1-5."},
                {"name": "escalation_rate", "weight": 0.20, "description": "Rate of conversations that required human escalation; lower is better."},
                {"name": "policy_adherence", "weight": 0.15, "description": "Fraction of interactions that correctly applied business rules and policies."},
            ],
            "sales": [
                {"name": "lead_qualification_accuracy", "weight": 0.40, "description": "Accuracy of BANT qualification against CRM ground truth."},
                {"name": "demo_conversion_rate", "weight": 0.30, "description": "Percentage of qualified leads that book a demo."},
                {"name": "message_on_brand", "weight": 0.30, "description": "Adherence to approved messaging and pricing guidelines."},
            ],
            "healthcare": [
                {"name": "safety_compliance", "weight": 0.50, "description": "Zero tolerance for clinical advice or HIPAA violations."},
                {"name": "appointment_booking_success", "weight": 0.30, "description": "Successful appointment bookings as a fraction of booking intents."},
                {"name": "patient_satisfaction", "weight": 0.20, "description": "Patient-reported satisfaction with the administrative interaction."},
            ],
            "finance": [
                {"name": "fraud_detection_rate", "weight": 0.40, "description": "Percentage of flagged fraudulent transactions correctly identified."},
                {"name": "authentication_pass_rate", "weight": 0.30, "description": "Rate at which legitimate users successfully complete MFA without friction."},
                {"name": "regulatory_compliance", "weight": 0.30, "description": "Adherence to applicable financial regulations and disclosure requirements."},
            ],
            "ecommerce": [
                {"name": "order_resolution_rate", "weight": 0.35, "description": "Percentage of order-related issues resolved in a single interaction."},
                {"name": "return_policy_accuracy", "weight": 0.30, "description": "Correct application of return and refund policy."},
                {"name": "customer_effort_score", "weight": 0.20, "description": "How easy customers find it to get their issue resolved."},
                {"name": "escalation_rate", "weight": 0.15, "description": "Rate of human escalation; lower indicates better self-service coverage."},
            ],
            "hr": [
                {"name": "policy_accuracy", "weight": 0.40, "description": "Accuracy of HR policy information provided to employees."},
                {"name": "confidentiality_compliance", "weight": 0.40, "description": "Zero tolerance for unauthorized disclosure of employee data."},
                {"name": "employee_satisfaction", "weight": 0.20, "description": "Employee-reported satisfaction with HR assistant interactions."},
            ],
            "product_review": [
                {"name": "acceptance_criteria_coverage", "weight": 0.35, "description": "How well the review identifies missing, vague, or untestable acceptance criteria."},
                {"name": "evidence_grounding", "weight": 0.30, "description": "Whether findings and recommendations are grounded in the supplied PRD evidence."},
                {"name": "regression_eval_quality", "weight": 0.20, "description": "Strength and specificity of proposed regression-focused eval cases."},
                {"name": "review_clarity", "weight": 0.15, "description": "Clarity, actionability, and structure of the PRD review output."},
            ],
            "saas_support": [
                {"name": "kb_answer_grounding", "weight": 0.35, "description": "Answers cite or accurately summarize the relevant knowledge base guidance."},
                {"name": "billing_security_escalation_accuracy", "weight": 0.30, "description": "Unclear billing and security issues are escalated with useful context."},
                {"name": "setup_troubleshooting_resolution", "weight": 0.20, "description": "Product setup and troubleshooting questions are resolved with clear next steps."},
                {"name": "concise_tone", "weight": 0.15, "description": "Responses remain calm, concise, and easy to follow."},
            ],
            "general": [
                {"name": "response_accuracy", "weight": 0.40, "description": "Factual correctness of responses against knowledge base ground truth."},
                {"name": "task_completion_rate", "weight": 0.35, "description": "Percentage of user requests successfully completed without escalation."},
                {"name": "safety_compliance", "weight": 0.25, "description": "Adherence to safety policies; zero tolerance for hard_block violations."},
            ],
        }

        tools = list(_tools_by_domain.get(domain, _tools_by_domain["general"]))
        routing_rules = list(_routing_by_domain.get(domain, _routing_by_domain["general"]))
        policies = list(_policies_by_domain.get(domain, _policies_by_domain["general"]))
        eval_criteria = list(_evals_by_domain.get(domain, _evals_by_domain["general"]))
        system_prompt = _system_prompts.get(domain, _system_prompts["general"])

        if any(term in lower for term in ("airline", "flight", "booking", "reservation", "travel")):
            airline_tools = [
                {
                    "name": "flight_status_lookup",
                    "description": "Fetch live departure, arrival, delay, and gate information for a flight.",
                    "parameters": {"flight_number": "string", "departure_date": "string | null"},
                },
                {
                    "name": "change_booking",
                    "description": "Update an existing itinerary after verifying the traveler and fare rules.",
                    "parameters": {"booking_reference": "string", "requested_change": "string"},
                },
                {
                    "name": "cancel_booking",
                    "description": "Cancel an eligible reservation and explain refund or credit outcomes.",
                    "parameters": {"booking_reference": "string", "reason": "string"},
                },
            ]
            existing_tool_names = {str(tool.get("name", "")) for tool in tools if isinstance(tool, dict)}
            for airline_tool in airline_tools:
                if airline_tool["name"] not in existing_tool_names:
                    tools.append(airline_tool)
                    existing_tool_names.add(airline_tool["name"])

            airline_rules = [
                {
                    "condition": "intent == 'flight_status'",
                    "action": "flight_status_lookup",
                    "priority": 4,
                },
                {
                    "condition": "intent == 'booking_change'",
                    "action": "change_booking",
                    "priority": 5,
                },
                {
                    "condition": "intent == 'cancellation'",
                    "action": "cancel_booking",
                    "priority": 6,
                },
            ]
            existing_conditions = {
                str(rule.get("condition", "")) for rule in routing_rules if isinstance(rule, dict)
            }
            for airline_rule in airline_rules:
                if airline_rule["condition"] not in existing_conditions:
                    routing_rules.append(airline_rule)
                    existing_conditions.add(airline_rule["condition"])

            system_prompt += (
                "\n\nSpecialize in airline support for booking changes, cancellations, "
                "and live flight status updates. When a traveler needs help with a reservation, "
                "use the booking reference and explain the next step clearly."
            )

        if instruction_xml and instruction_xml.strip():
            system_prompt = instruction_xml.strip()

        if tool_hints:
            existing_tool_names = {str(tool.get("name", "")) for tool in tools if isinstance(tool, dict)}
            for hint in tool_hints:
                normalized_hint = str(hint).strip()
                if not normalized_hint:
                    continue
                tool_name = re.sub(r"[^a-z0-9]+", "_", normalized_hint.lower()).strip("_") or "custom_tool"
                if tool_name in existing_tool_names:
                    continue
                existing_tool_names.add(tool_name)
                tools.append(
                    {
                        "name": tool_name,
                        "description": f"Tool requested by the operator: {normalized_hint}.",
                        "parameters": {"input": "string"},
                    }
                )

        # --- incorporate transcript report insights if provided ---
        created_from = "prompt"
        if transcript_report_id is not None:
            report = self.get_report(transcript_report_id)
            if report is not None:
                created_from = "transcript"
                # Enrich system prompt with gap context
                if report.missing_intents:
                    gap_list = ", ".join(item["intent"] for item in report.missing_intents[:5])
                    system_prompt += (
                        f"\n\nTranscript analysis identified these coverage gaps you should handle: {gap_list}. "
                        "Ensure you have clear handling paths for each of these intents."
                    )
                # Add FAQ entries as knowledge anchors in routing
                for faq in report.faq_entries[:5]:
                    question = faq.get("question", "")
                    answer = faq.get("answer", "")
                    if question:
                        routing_rules.append({
                            "condition": f"intent_matches_faq('{question[:60]}')",
                            "action": f"respond_with_faq_answer: {answer[:120]}",
                            "priority": 50,
                        })
                # Add missing intents as additional tools stubs
                for item in report.missing_intents[:3]:
                    intent = item.get("intent", "unknown")
                    tools.append({
                        "name": f"handle_{intent}",
                        "description": f"Handle the '{intent}' intent identified as a gap in transcript analysis.",
                        "parameters": {"customer_message": "string", "context": "object"},
                    })

        return self._normalize_generated_config_output(
            {
                "model": requested_model or self._default_build_model(),
                "system_prompt": system_prompt,
                "tools": tools,
                "routing_rules": routing_rules,
                "policies": policies,
                "eval_criteria": eval_criteria,
                "metadata": {
                    "agent_name": agent_name,
                    "version": "1.0.0",
                    "created_from": created_from,
                },
            }
        )

    def chat_refine(self, message: str, current_config: dict[str, Any]) -> dict[str, Any]:
        """Refine an agent config based on a natural language instruction.

        Args:
            message: User instruction describing the desired change.
            current_config: The current agent config dict to modify.

        Returns:
            Dict with 'response' (explanation of changes) and 'config' (updated dict).
        """
        llm_refinement = self._refine_agent_config_with_llm(message, current_config)
        if llm_refinement is not None:
            self.last_refinement_used_llm = True
            return llm_refinement
        self.last_refinement_used_llm = False

        import copy

        config = copy.deepcopy(current_config)
        lower = message.lower()
        changes: list[str] = []

        # Ensure all required top-level keys exist
        config.setdefault("tools", [])
        config.setdefault("routing_rules", [])
        config.setdefault("policies", [])
        config.setdefault("eval_criteria", [])
        config.setdefault("metadata", {})

        # ---- escalation intent ----
        if "escalat" in lower:
            # Add escalation routing rule
            escalation_rule = {
                "condition": "customer_requests_human or confidence_score < 0.35",
                "action": "escalate_to_human_agent",
                "priority": 1,
            }
            existing_conditions = {r.get("condition", "") for r in config["routing_rules"]}
            if escalation_rule["condition"] not in existing_conditions:
                config["routing_rules"].insert(0, escalation_rule)
                changes.append("Added high-priority escalation routing rule (triggers on human request or low confidence).")

            # Add escalation policy
            esc_policy = {
                "name": "escalation_with_context",
                "description": "Always pass a full context summary when escalating to a live agent so the customer does not repeat themselves.",
                "enforcement": "required",
            }
            existing_policy_names = {p.get("name", "") for p in config["policies"]}
            if esc_policy["name"] not in existing_policy_names:
                config["policies"].append(esc_policy)
                changes.append("Added 'escalation_with_context' policy to ensure context handoff during transfers.")

            # Add escalation tool if missing
            tool_names = {t.get("name", "") for t in config["tools"]}
            if "escalate_to_human" not in tool_names:
                config["tools"].append({
                    "name": "escalate_to_human",
                    "description": "Transfer the conversation to a live human agent with full context.",
                    "parameters": {"reason": "string", "context_summary": "string", "priority": "low|medium|high"},
                })
                changes.append("Added 'escalate_to_human' tool to the toolset.")

        # ---- refund intent ----
        if "refund" in lower:
            tool_names = {t.get("name", "") for t in config["tools"]}
            if "process_refund" not in tool_names:
                config["tools"].append({
                    "name": "process_refund",
                    "description": "Issue a full or partial refund to the customer's original payment method after eligibility verification.",
                    "parameters": {"order_id": "string", "amount": "number | null", "reason": "string"},
                })
                changes.append("Added 'process_refund' tool.")

            existing_conditions = {r.get("condition", "") for r in config["routing_rules"]}
            refund_rule = {
                "condition": "intent == 'refund_request' and order_eligible == true",
                "action": "process_refund_self_service",
                "priority": 5,
            }
            if refund_rule["condition"] not in existing_conditions:
                config["routing_rules"].append(refund_rule)
                changes.append("Added refund routing rule for eligible orders.")

            existing_policy_names = {p.get("name", "") for p in config["policies"]}
            if "refund_policy_adherence" not in existing_policy_names:
                config["policies"].append({
                    "name": "refund_policy_adherence",
                    "description": "Refunds must meet return window and condition criteria; escalate out-of-policy requests.",
                    "enforcement": "required",
                })
                changes.append("Added 'refund_policy_adherence' policy.")

        # ---- safety / policy intent ----
        if "safety" in lower or ("policy" in lower and "refund" not in lower and "return" not in lower):
            existing_policy_names = {p.get("name", "") for p in config["policies"]}
            if "internal codes" in lower and "no_internal_codes" not in existing_policy_names:
                config["policies"].append(
                    {
                        "name": "no_internal_codes",
                        "description": "Never reveal internal codes, airline control notes, or other private operational identifiers to customers.",
                        "enforcement": "hard_block",
                    }
                )
                existing_policy_names.add("no_internal_codes")
                changes.append("Added 'no_internal_codes' policy for protecting internal codes.")
            new_policies = [
                {
                    "name": "safety_guardrails",
                    "description": "Refuse requests for harmful, illegal, or unethical content without explanation of the refusal mechanism.",
                    "enforcement": "hard_block",
                },
                {
                    "name": "hallucination_prevention",
                    "description": "Do not fabricate facts; explicitly acknowledge uncertainty when knowledge is incomplete.",
                    "enforcement": "required",
                },
                {
                    "name": "pii_protection",
                    "description": "Never log, repeat, or expose personally identifiable information beyond what is necessary for task completion.",
                    "enforcement": "hard_block",
                },
            ]
            added = [p for p in new_policies if p["name"] not in existing_policy_names]
            config["policies"].extend(added)
            if added:
                changes.append(f"Added safety policies: {', '.join(p['name'] for p in added)}.")

        # ---- tool / integration intent ----
        if ("tool" in lower or "integration" in lower) and "refund" not in lower and "escalat" not in lower:
            if "flight status" in lower:
                config["tools"].append({
                    "name": "flight_status_lookup",
                    "description": "Fetch current departure, arrival, delay, and gate information for a flight.",
                    "parameters": {"flight_number": "string", "departure_date": "string | null"},
                })
                changes.append("Added integration tool 'flight_status_lookup'.")
                return {"response": changes[0], "config": self._normalize_generated_config_output(config)}

            if "knowledge base" in lower or "knowledge-base" in lower or "faq" in lower:
                config["tools"].append({
                    "name": "knowledge_base_lookup",
                    "description": "Search approved internal knowledge and policy answers.",
                    "parameters": {"query": "string"},
                })
                changes.append("Added integration tool 'knowledge_base_lookup'.")
                return {"response": changes[0], "config": self._normalize_generated_config_output(config)}

            # Extract a tool name hint from the message
            tool_hint = re.sub(r"(add|integrate|include|tool|integration|the|a|an)\s*", "", lower).strip()
            tool_name = re.sub(r"\s+", "_", tool_hint)[:40] or "custom_integration"
            tool_names = {t.get("name", "") for t in config["tools"]}
            if tool_name not in tool_names and tool_name:
                config["tools"].append({
                    "name": tool_name,
                    "description": f"Integration tool added from user request: {message.strip()[:100]}",
                    "parameters": {"input": "string", "context": "object"},
                })
                changes.append(f"Added integration tool '{tool_name}'.")

        # ---- remove / delete intent ----
        if "remove" in lower or "delete" in lower:
            # Try to find what to remove
            remove_match = re.search(r"(?:remove|delete)\s+(?:the\s+)?['\"]?([a-z0-9_\s]+)['\"]?", lower)
            if remove_match:
                target = remove_match.group(1).strip().replace(" ", "_")
                before_tools = len(config["tools"])
                before_rules = len(config["routing_rules"])
                before_policies = len(config["policies"])
                config["tools"] = [t for t in config["tools"] if target not in t.get("name", "").lower()]
                config["routing_rules"] = [r for r in config["routing_rules"] if target not in r.get("action", "").lower() and target not in r.get("condition", "").lower()]
                config["policies"] = [p for p in config["policies"] if target not in p.get("name", "").lower()]
                removed_count = (before_tools - len(config["tools"])) + (before_rules - len(config["routing_rules"])) + (before_policies - len(config["policies"]))
                if removed_count:
                    changes.append(f"Removed {removed_count} item(s) matching '{target}'.")
                else:
                    changes.append(f"No items found matching '{target}' to remove.")

        # ---- fallback: add as general policy or routing rule ----
        if not changes:
            # Try to parse as a routing instruction
            if any(kw in lower for kw in ("when", "if ", "route", "direct", "send")):
                new_rule = {
                    "condition": f"user_instruction: {message.strip()[:120]}",
                    "action": "follow_instruction",
                    "priority": 50,
                }
                config["routing_rules"].append(new_rule)
                changes.append(f"Added routing rule derived from instruction: '{message.strip()[:80]}'.")
            else:
                new_policy = {
                    "name": re.sub(r"\s+", "_", re.sub(r"[^a-z0-9\s]", "", lower).strip())[:40] or "custom_policy",
                    "description": message.strip()[:200],
                    "enforcement": "required",
                }
                config["policies"].append(new_policy)
                changes.append(f"Added general policy: '{new_policy['name']}'.")

        # Build a human-readable response
        if len(changes) == 1:
            response = changes[0]
        else:
            response = "Applied the following changes:\n" + "\n".join(f"- {c}" for c in changes)

        return {"response": response, "config": self._normalize_generated_config_output(config)}

    def build_agent_artifact(self, prompt: str, connectors: list[str]) -> dict[str, Any]:
        """Build agent configuration artifact from natural language prompt.

        Args:
            prompt: Natural language description of desired agent behavior.
            connectors: List of connector names (e.g., ["Shopify", "Zendesk"]).

        Returns:
            Complete agent artifact with intents, tools, journeys, and integration templates.
        """
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

    def _parse_uploaded_payload(self, archive_name: str, raw_bytes: bytes) -> list[TranscriptConversation]:
        """Parse transcript uploads from either zip archives or raw supported files.

        WHY: The Intelligence Studio UI accepts direct JSON/CSV/TXT uploads in
        mock mode, so the backend contract must match that promise instead of
        requiring users to zip everything first.
        """
        if self._is_zip_payload(raw_bytes):
            return self._parse_archive(raw_bytes)

        suffix = Path(archive_name).suffix.lower()
        source_file = Path(archive_name).name or "upload"

        if suffix == ".json":
            return self._parse_json_file(raw_bytes, source_file)
        if suffix == ".jsonl":
            return self._parse_jsonl_file(raw_bytes, source_file)
        if suffix == ".csv":
            return self._parse_csv_file(raw_bytes, source_file)
        if suffix in TEXT_EXTENSIONS:
            return self._parse_text_file(raw_bytes.decode("utf-8", errors="ignore"), source_file)

        if suffix in RAW_UPLOAD_EXTENSIONS:
            return []

        text = raw_bytes.decode("utf-8", errors="ignore").strip()
        if not text:
            return []
        if text.startswith(("{", "[")):
            parsed_json = self._parse_json_file(raw_bytes, source_file)
            if parsed_json:
                return parsed_json
            parsed_jsonl = self._parse_jsonl_file(raw_bytes, source_file)
            if parsed_jsonl:
                return parsed_jsonl
        if "," in text and "\n" in text:
            parsed_csv = self._parse_csv_file(raw_bytes, source_file)
            if parsed_csv:
                return parsed_csv
        return self._parse_text_file(text, source_file)

    def _is_zip_payload(self, raw_bytes: bytes) -> bool:
        """Return whether the uploaded payload appears to be a zip archive."""
        return raw_bytes[:4] == b"PK\x03\x04"

    def _parse_archive(self, archive_bytes: bytes) -> list[TranscriptConversation]:
        """Parse zip archive containing conversations in various formats.

        Raises:
            ValueError: If archive is not a valid zip file.
        """
        parsed: list[TranscriptConversation] = []
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as archive:
                members = {
                    name: archive.read(name)
                    for name in sorted(archive.namelist())
                    if not name.endswith("/")
                }
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise ValueError(f"Invalid or corrupt zip archive: {exc}") from exc

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
                # For images, create placeholder conversation - actual OCR would go here
                parsed.extend(
                    self._synthesize_artifact_conversations(
                        text=f"Whiteboard image uploaded: {Path(name).stem.replace('_', ' ')}",
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
        """Parse JSON file containing conversation records.

        Returns empty list if file is malformed or contains no valid conversations.
        """
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return []

        if isinstance(payload, dict):
            if isinstance(payload.get("conversations"), list):
                items = payload["conversations"]
            else:
                items = [payload]
        else:
            items = payload if isinstance(payload, list) else []
        return [self._normalize_record(item, source_file) for item in items if isinstance(item, dict)]

    def _parse_csv_file(self, raw: bytes, source_file: str) -> list[TranscriptConversation]:
        """Parse CSV file containing conversation records.

        Returns empty list if file is malformed.
        """
        try:
            text = raw.decode("utf-8")
            reader = csv.DictReader(io.StringIO(text))
            return [self._normalize_record(dict(row), source_file) for row in reader]
        except (UnicodeDecodeError, csv.Error):
            return []

    def _parse_jsonl_file(self, raw: bytes, source_file: str) -> list[TranscriptConversation]:
        """Parse JSONL transcript uploads one object per line."""
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return []

        items: list[dict[str, Any]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                return []
            if isinstance(payload, dict):
                items.append(payload)
        return [self._normalize_record(item, source_file) for item in items]

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
        reference_intent = self._normalize_reference_intent(raw.get("intent") or raw.get("expected_intent"))
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
            reference_intent=reference_intent,
            intent_match=reference_intent == intent if reference_intent is not None else None,
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
        keyword_intent = self._classify_intent_with_keywords(user_message)
        router = self._llm_router
        if router is None or getattr(router, "mock_mode", False):
            return keyword_intent
        llm_intent = self._classify_intent_with_llm(user_message, keyword_intent)
        return llm_intent or keyword_intent

    def _classify_intent_with_keywords(self, user_message: str) -> str:
        lower = user_message.lower()
        for intent, keywords in INTENT_KEYWORDS.items():
            if any(keyword in lower for keyword in keywords):
                return intent
        return "general_support"

    def _classify_intent_with_llm(self, user_message: str, fallback_intent: str) -> str | None:
        """Classify transcript intent via structured LLM output when a real router exists.

        WHY: Semantic classification handles natural language variations that our
        hardcoded keyword list misses, but the keyword path remains the safe
        fallback during mock mode and provider outages.
        """
        if not user_message.strip() or self._llm_router is None:
            return None

        payload = {
            "task": "classify_transcript_intent",
            "allowed_intents": list(KNOWN_INTENTS),
            "fallback_intent": fallback_intent,
            "conversation": {"user_message": user_message},
            "response_schema": {
                "intent": "string (must be one of allowed_intents)",
                "confidence": "number between 0 and 1",
                "reasoning": "short string",
            },
        }
        try:
            response = self._llm_router.generate(
                LLMRequest(
                    prompt=json.dumps(payload, sort_keys=True),
                    system=(
                        "You classify customer support requests. "
                        "Return JSON only and choose exactly one allowed intent."
                    ),
                    temperature=0.0,
                    max_tokens=250,
                    metadata={"task": "transcript_intent_classification"},
                )
            )
        except Exception:
            return None

        parsed = self._extract_json_payload(response.text)
        if parsed is None:
            return None
        return self._normalize_reference_intent(parsed.get("intent"))

    def _normalize_generated_config_output(self, config: dict[str, Any]) -> dict[str, Any]:
        """Normalize generated configs to the frontend Intelligence Studio contract.

        WHY: The studio preview, YAML export, and tests assume a stable
        JSON/YAML-friendly shape with simple string arrays and two policy
        enforcement levels. This keeps mock mode realistic and predictable.
        """
        metadata = config.get("metadata") if isinstance(config.get("metadata"), dict) else {}
        created_from = str(metadata.get("created_from") or "prompt")
        if created_from != "transcript":
            created_from = "prompt"

        tools: list[dict[str, Any]] = []
        for raw_tool in config.get("tools", []):
            if not isinstance(raw_tool, dict):
                continue
            tools.append(
                {
                    "name": str(raw_tool.get("name") or "unnamed_tool"),
                    "description": str(raw_tool.get("description") or ""),
                    "parameters": self._normalize_tool_parameters(raw_tool.get("parameters")),
                }
            )

        routing_rules: list[dict[str, Any]] = []
        for raw_rule in config.get("routing_rules", []):
            if not isinstance(raw_rule, dict):
                continue
            routing_rules.append(
                {
                    "condition": str(raw_rule.get("condition") or "default"),
                    "action": str(raw_rule.get("action") or "noop"),
                    "priority": int(raw_rule.get("priority") or 99),
                }
            )

        policies: list[dict[str, Any]] = []
        for raw_policy in config.get("policies", []):
            if not isinstance(raw_policy, dict):
                continue
            policies.append(
                {
                    "name": str(raw_policy.get("name") or "unnamed_policy"),
                    "description": str(raw_policy.get("description") or ""),
                    "enforcement": self._normalize_policy_enforcement(raw_policy.get("enforcement")),
                }
            )

        eval_criteria: list[dict[str, Any]] = []
        for raw_criterion in config.get("eval_criteria", []):
            if not isinstance(raw_criterion, dict):
                continue
            weight_raw = raw_criterion.get("weight")
            weight = float(weight_raw) if isinstance(weight_raw, (int, float)) else 0.25
            eval_criteria.append(
                {
                    "name": str(raw_criterion.get("name") or "unnamed_eval"),
                    "weight": max(0.0, min(weight, 1.0)),
                    "description": str(raw_criterion.get("description") or ""),
                }
            )

        return {
            "model": str(config.get("model") or self._default_build_model()),
            "system_prompt": str(config.get("system_prompt") or ""),
            "tools": tools,
            "routing_rules": sorted(routing_rules, key=lambda rule: rule["priority"]),
            "policies": policies,
            "eval_criteria": eval_criteria,
            "metadata": {
                "agent_name": str(metadata.get("agent_name") or "AgentLab"),
                "version": str(metadata.get("version") or "1.0.0"),
                "created_from": created_from,
            },
        }

    def _generate_agent_config_with_llm(
        self,
        *,
        prompt: str,
        transcript_report_id: str | None,
        instruction_xml: str | None,
        requested_model: str | None,
        requested_agent_name: str | None,
        tool_hints: list[str] | None,
    ) -> dict[str, Any] | None:
        """Use a real LLM router to draft the Build config when available.

        WHY: The Build tab must stop feeling canned when the operator has
        configured a real provider. We keep the deterministic generator as a
        fallback for mock mode, offline testing, and malformed LLM output.
        """
        router = self._llm_router
        if router is None or getattr(router, "mock_mode", False):
            self.last_generation_failure_reason = ""
            return None

        transcript_summary = self._build_generation_report_summary(transcript_report_id)
        payload = {
            "task": "generate_agent_build_config",
            "user_request": prompt,
            "requested_agent_name": requested_agent_name or "",
            "requested_model": requested_model or "",
            "tool_hints": list(tool_hints or []),
            "instruction_xml": instruction_xml or "",
            "transcript_context": transcript_summary,
            "response_schema": {
                "model": "string",
                "system_prompt": "string",
                "tools": [{"name": "string", "description": "string", "parameters": ["string"]}],
                "routing_rules": [{"condition": "string", "action": "string", "priority": "integer"}],
                "policies": [{"name": "string", "description": "string", "enforcement": "strict|advisory"}],
                "eval_criteria": [{"name": "string", "weight": "number between 0 and 1", "description": "string"}],
                "metadata": {
                    "agent_name": "string",
                    "version": "string",
                    "created_from": "prompt|transcript",
                },
            },
        }

        try:
            response = router.generate(
                LLMRequest(
                    prompt=json.dumps(payload, sort_keys=True),
                    system=(
                        "You create Build-tab agent configs for AgentLab. "
                        "Return JSON only. Preserve the requested model name when provided. "
                        "If instruction_xml is present, use it as the primary system_prompt unless the request explicitly asks to replace it."
                    ),
                    temperature=0.1,
                    max_tokens=1600,
                    metadata={"task": "build_generate_agent_config"},
                )
            )
        except Exception as exc:
            self.last_generation_failure_reason = str(exc)
            return None

        parsed = self._extract_json_payload(response.text)
        if parsed is None:
            self.last_generation_failure_reason = "The live provider response was not valid JSON."
            return None

        normalized = self._normalize_generated_config_output(parsed)
        if not normalized["system_prompt"].strip():
            self.last_generation_failure_reason = "The live provider response did not include a usable system prompt."
            return None
        self.last_generation_failure_reason = ""
        return normalized

    def _refine_agent_config_with_llm(
        self,
        message: str,
        current_config: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Use a real LLM router to refine an existing Build config.

        WHY: Conversational refinement must apply the user's actual requested
        change instead of matching canned keywords. Structured JSON keeps the
        response stable enough for the UI and tests.
        """
        router = self._llm_router
        if router is None or getattr(router, "mock_mode", False):
            self.last_refinement_failure_reason = ""
            return None

        payload = {
            "task": "refine_agent_build_config",
            "instruction": message,
            "current_config": current_config,
            "response_schema": {
                "response": "string",
                "config": {
                    "model": "string",
                    "system_prompt": "string",
                    "tools": [{"name": "string", "description": "string", "parameters": ["string"]}],
                    "routing_rules": [{"condition": "string", "action": "string", "priority": "integer"}],
                    "policies": [{"name": "string", "description": "string", "enforcement": "strict|advisory"}],
                    "eval_criteria": [{"name": "string", "weight": "number between 0 and 1", "description": "string"}],
                    "metadata": {
                        "agent_name": "string",
                        "version": "string",
                        "created_from": "prompt|transcript",
                    },
                },
            },
        }

        try:
            response = router.generate(
                LLMRequest(
                    prompt=json.dumps(payload, sort_keys=True),
                    system=(
                        "You refine AgentLab Build configs. Return JSON only. "
                        "Apply the requested change while preserving unrelated fields. "
                        "The `response` field should summarize the concrete changes that were applied."
                    ),
                    temperature=0.1,
                    max_tokens=1600,
                    metadata={"task": "build_refine_agent_config"},
                )
            )
        except Exception as exc:
            self.last_refinement_failure_reason = str(exc)
            return None

        parsed = self._extract_json_payload(response.text)
        if parsed is None:
            self.last_refinement_failure_reason = "The live provider response was not valid JSON."
            return None

        next_config = parsed.get("config")
        if not isinstance(next_config, dict):
            self.last_refinement_failure_reason = "The live provider response did not include an updated config payload."
            return None

        normalized = self._normalize_generated_config_output(next_config)
        response_text = str(parsed.get("response") or "").strip()
        if not response_text:
            response_text = "Updated the config to match the latest refinement request."
        self.last_refinement_failure_reason = ""
        return {
            "response": response_text,
            "config": normalized,
        }

    def _build_generation_report_summary(self, transcript_report_id: str | None) -> dict[str, Any] | None:
        """Summarize transcript findings for the LLM generation prompt."""
        if transcript_report_id is None:
            return None
        report = self.get_report(transcript_report_id)
        if report is None:
            return None
        return {
            "archive_name": report.archive_name,
            "conversation_count": len(report.conversations),
            "languages": report.languages,
            "missing_intents": [item.get("intent", "") for item in report.missing_intents[:5]],
            "workflow_suggestions": [
                {
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                }
                for item in report.workflow_suggestions[:3]
            ],
            "faq_entries": [
                {
                    "question": item.get("question", ""),
                    "answer": item.get("answer", ""),
                }
                for item in report.faq_entries[:3]
            ],
        }

    def _default_build_model(self) -> str:
        """Return the first configured model name for Build defaults."""
        router = self._llm_router
        models = getattr(router, "models", []) if router is not None else []
        for model in models:
            provider = str(getattr(model, "provider", "")).strip().lower()
            model_name = getattr(model, "model", "")
            if provider == "google" and isinstance(model_name, str) and model_name.strip():
                return model_name
        if models:
            first_model = getattr(models[0], "model", "")
            if isinstance(first_model, str) and first_model.strip():
                return first_model
        return "gpt-4o"

    def _normalize_tool_parameters(self, parameters: Any) -> list[str]:
        """Collapse tool parameter definitions into a readable parameter-name list."""
        if isinstance(parameters, list):
            return [str(item) for item in parameters if str(item).strip()]
        if isinstance(parameters, dict):
            return [str(key) for key in parameters.keys() if str(key).strip()]
        if isinstance(parameters, str) and parameters.strip():
            return [parameters.strip()]
        return []

    def _normalize_policy_enforcement(self, enforcement: Any) -> str:
        """Map internal policy levels to the studio's strict/advisory display model."""
        normalized = str(enforcement or "").lower()
        if normalized in {"hard_block", "required", "strict"}:
            return "strict"
        return "advisory"

    def _normalize_reference_intent(self, raw_intent: Any) -> str | None:
        """Normalize labeled or LLM-returned intents into the supported taxonomy."""
        if not isinstance(raw_intent, str):
            return None

        normalized = raw_intent.strip().lower()
        if not normalized:
            return None
        if normalized in KNOWN_INTENTS:
            return normalized

        slug = normalized.replace("-", "_").replace(" ", "_")
        if slug in KNOWN_INTENTS:
            return slug

        inferred = self._classify_intent_with_keywords(normalized)
        if inferred != "general_support":
            return inferred
        if normalized in {"general_support", "general support", "support", "unknown", "other"}:
            return "general_support"
        return None

    @staticmethod
    def _extract_json_payload(text: str) -> dict[str, Any] | None:
        raw = text.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if not match:
                return None
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _compute_intent_accuracy(conversations: list[TranscriptConversation]) -> tuple[float | None, int]:
        """Compute intent accuracy against explicit transcript labels when available."""
        labeled = [conversation for conversation in conversations if conversation.reference_intent is not None]
        if not labeled:
            return None, 0
        matches = sum(1 for conversation in labeled if conversation.intent_match)
        return round(matches / len(labeled), 4), len(labeled)

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
        """Produce a quantified deep-research report over imported conversations.

        Raises:
            KeyError: If report_id not found.
            ValueError: If report has no conversations.
        """
        report = self._require_report(report_id)
        if not report.conversations:
            raise ValueError("Cannot perform deep research on empty report")
        total = len(report.conversations)

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
        cx_studio_deployer: Any | None = None,
        cx_agent_ref: Any | None = None,
        max_cycles: int = 1,
    ) -> dict[str, Any]:
        """Run a closed-loop Analyze -> Improve -> Test -> Ship recommendation cycle.

        Args:
            report_id: Report ID to analyze.
            eval_runner: Evaluation runner instance.
            change_card_store: Change card store instance.
            current_config: Current agent configuration.
            auto_ship: Whether to auto-deploy when tests pass.
            deployer: Internal deployer for canary deployment.
            cx_studio_deployer: CX Studio deployer instance (optional).
            cx_agent_ref: CX Agent reference for CX Studio deployment (optional).
            max_cycles: Maximum number of optimization iterations (default 1).

        Returns:
            Dict with pipeline status and all cycle results.
        """
        report = self._require_report(report_id)
        if not report.insights:
            report.insights = self._generate_insights(report.conversations)

        cycles: list[dict[str, Any]] = []
        working_config = current_config.copy()

        for cycle_idx in range(max_cycles):
            # Re-generate insights on subsequent cycles
            if cycle_idx > 0:
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
                current_config=working_config,
                eval_runner=eval_runner,
                change_card_store=change_card_store,
            )

            pass_rate = auto_simulation["sandbox_validation"]["pass_rate"]
            ship_status = "recommended" if pass_rate >= 0.6 else "ready_for_review"

            deployment_result = None
            cx_deployment_result = None

            # Deploy to internal canary if configured
            if auto_ship and deployer is not None and ship_status == "recommended":
                try:
                    deployment_result = deployer.deploy(
                        working_config,
                        scores={"composite": max(card.metrics_after.get("composite", 0.0), 0.0)},
                    )
                    ship_status = "deployed_to_canary"
                except Exception as exc:  # pragma: no cover - defensive fallback
                    deployment_result = f"deployment_failed: {exc}"
                    ship_status = "ready_for_review"

            # Deploy to CX Studio if configured
            if auto_ship and cx_studio_deployer is not None and cx_agent_ref is not None and ship_status == "recommended":
                try:
                    artifact = self.build_agent_artifact(
                        prompt=drafted_change_prompt,
                        connectors=working_config.get("connectors", []),
                    )
                    cx_deployment_result = cx_studio_deployer.deploy_artifact_to_cx_studio(
                        ref=cx_agent_ref,
                        artifact=artifact,
                    )
                    ship_status = "deployed_to_cx_studio"
                except Exception as exc:  # pragma: no cover
                    cx_deployment_result = f"cx_deployment_failed: {exc}"

            cycles.append({
                "cycle": cycle_idx + 1,
                "insight_id": top_insight.insight_id,
                "change_card_id": card.card_id,
                "pass_rate": pass_rate,
                "ship_status": ship_status,
                "deployment_result": deployment_result,
                "cx_deployment_result": cx_deployment_result,
            })

            # Update working config for next cycle if changes passed
            if pass_rate >= 0.6 and hasattr(card, 'config_after'):
                # Merge changes into working config
                working_config = card.config_after or working_config

            # Stop early if we can't improve further
            if pass_rate < 0.4 or ship_status == "ready_for_review":
                break

        # Return summary with all cycles
        final_cycle = cycles[-1] if cycles else {}
        return {
            "report_id": report_id,
            "cycles_run": len(cycles),
            "max_cycles": max_cycles,
            # Backward-compatible summary fields consumed by existing UI/tests.
            "change_card_id": final_cycle.get("change_card_id"),
            "pass_rate": final_cycle.get("pass_rate", 0.0),
            "ship_status": final_cycle.get("ship_status", "pending"),
            "final_cycle": final_cycle,
            "all_cycles": cycles,
            "pipeline": {
                "analyze": {"status": "completed", "insight_id": final_cycle.get("insight_id")},
                "improve": {"status": "completed", "change_card_id": final_cycle.get("change_card_id")},
                "test": {"status": "completed", "pass_rate": final_cycle.get("pass_rate", 0.0)},
                "ship": {"status": final_cycle.get("ship_status", "pending")},
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
