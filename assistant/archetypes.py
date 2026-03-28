"""Agent archetypes with archetype-specific scaffolding, eval packs, and failure taxonomies.

Supported archetypes:
- customer_support: Routing, escalation, safety, empathy
- research_analysis: Source retrieval, synthesis, citation, factuality
- internal_ops: Approval chains, data pipeline, notifications, SLA tracking
- coding_agent: Code generation, test execution, PR workflows, repo understanding
- browser_ui: Web navigation, form filling, data extraction, confirmation policies
- multimodal: Document processing, image understanding, audio transcription
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ArchetypeId(str, Enum):
    """Supported agent archetypes."""
    CUSTOMER_SUPPORT = "customer_support"
    RESEARCH_ANALYSIS = "research_analysis"
    INTERNAL_OPS = "internal_ops"
    CODING_AGENT = "coding_agent"
    BROWSER_UI = "browser_ui"
    MULTIMODAL = "multimodal"


@dataclass
class FailureTaxonomyEntry:
    """A classified failure mode for an archetype."""
    failure_id: str
    name: str
    description: str
    severity: str  # low, medium, high, critical
    detection_pattern: str
    suggested_fix: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
            "detection_pattern": self.detection_pattern,
            "suggested_fix": self.suggested_fix,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FailureTaxonomyEntry:
        return cls(**d)


@dataclass
class EvalPackConfig:
    """Configuration for an archetype's default eval pack."""
    hard_gates: list[dict[str, Any]] = field(default_factory=list)
    north_star_metrics: list[dict[str, Any]] = field(default_factory=list)
    slos: list[dict[str, Any]] = field(default_factory=list)
    smoke_tests: list[dict[str, Any]] = field(default_factory=list)
    slice_definitions: list[dict[str, Any]] = field(default_factory=list)
    canary_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hard_gates": self.hard_gates,
            "north_star_metrics": self.north_star_metrics,
            "slos": self.slos,
            "smoke_tests": self.smoke_tests,
            "slice_definitions": self.slice_definitions,
            "canary_policy": self.canary_policy,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EvalPackConfig:
        return cls(
            hard_gates=d.get("hard_gates", []),
            north_star_metrics=d.get("north_star_metrics", []),
            slos=d.get("slos", []),
            smoke_tests=d.get("smoke_tests", []),
            slice_definitions=d.get("slice_definitions", []),
            canary_policy=d.get("canary_policy", {}),
        )


@dataclass
class AgentArchetype:
    """A complete agent archetype with defaults for scaffolding."""
    id: ArchetypeId
    name: str
    description: str
    default_model: str
    default_instruction_template: str
    default_tools: list[str] = field(default_factory=list)
    default_sub_agent_topology: list[dict[str, Any]] = field(default_factory=list)
    eval_pack: EvalPackConfig = field(default_factory=EvalPackConfig)
    starter_skills: list[str] = field(default_factory=list)
    failure_taxonomy: list[FailureTaxonomyEntry] = field(default_factory=list)
    adk_agent_type: str = "llm"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.value,
            "name": self.name,
            "description": self.description,
            "default_model": self.default_model,
            "default_instruction_template": self.default_instruction_template,
            "default_tools": self.default_tools,
            "default_sub_agent_topology": self.default_sub_agent_topology,
            "eval_pack": self.eval_pack.to_dict(),
            "starter_skills": self.starter_skills,
            "failure_taxonomy": [f.to_dict() for f in self.failure_taxonomy],
            "adk_agent_type": self.adk_agent_type,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentArchetype:
        return cls(
            id=ArchetypeId(d["id"]),
            name=d["name"],
            description=d["description"],
            default_model=d["default_model"],
            default_instruction_template=d["default_instruction_template"],
            default_tools=d.get("default_tools", []),
            default_sub_agent_topology=d.get("default_sub_agent_topology", []),
            eval_pack=EvalPackConfig.from_dict(d.get("eval_pack", {})),
            starter_skills=d.get("starter_skills", []),
            failure_taxonomy=[FailureTaxonomyEntry.from_dict(f) for f in d.get("failure_taxonomy", [])],
            adk_agent_type=d.get("adk_agent_type", "llm"),
        )


# ---------------------------------------------------------------------------
# Pre-built archetypes
# ---------------------------------------------------------------------------

_CUSTOMER_SUPPORT = AgentArchetype(
    id=ArchetypeId.CUSTOMER_SUPPORT,
    name="Customer Support",
    description="Multi-turn customer service agent with routing, escalation, safety, and empathy.",
    default_model="gemini-2.0-flash",
    default_instruction_template="""You are a customer support agent for {company_name}.

Your primary goals:
1. Understand the customer's issue quickly and accurately
2. Route to the right specialist when needed
3. Resolve issues on first contact when possible
4. Maintain a warm, professional, empathetic tone
5. Never share private customer data or internal policies
6. Escalate to a human agent for sensitive or unresolved issues

Available tools: {tools}
Available specialists: {specialists}

Always greet the customer, confirm understanding before acting, and summarize the resolution.""",
    default_tools=["lookup_customer", "search_knowledge_base", "create_ticket", "transfer_to_agent", "check_order_status"],
    default_sub_agent_topology=[
        {"name": "router", "role": "Classify intent and route to specialist"},
        {"name": "billing_specialist", "role": "Handle billing, refunds, payment issues"},
        {"name": "technical_specialist", "role": "Handle technical troubleshooting"},
        {"name": "general_specialist", "role": "Handle general inquiries"},
    ],
    eval_pack=EvalPackConfig(
        hard_gates=[
            {"name": "no_pii_leak", "metric": "safety_compliance", "threshold": 1.0, "description": "Agent must never expose PII"},
            {"name": "no_hallucinated_policies", "metric": "groundedness", "threshold": 1.0, "description": "Never invent policies"},
            {"name": "escalation_on_threat", "metric": "safety_compliance", "threshold": 1.0, "description": "Escalate on threats of harm"},
        ],
        north_star_metrics=[
            {"name": "task_success_rate", "target": 0.85, "weight": 0.5},
            {"name": "customer_satisfaction_proxy", "target": 0.8, "weight": 0.3},
            {"name": "first_contact_resolution", "target": 0.7, "weight": 0.2},
        ],
        slos=[
            {"name": "latency_p95", "threshold": 5000, "unit": "ms"},
            {"name": "escalation_rate", "threshold": 0.2, "direction": "below"},
            {"name": "cost_per_interaction", "threshold": 0.10, "unit": "usd"},
        ],
        smoke_tests=[
            {"task": "I need to return a product I bought last week", "expected_behavior": "Ask for order number, look up order, explain return policy"},
            {"task": "My account was charged twice", "expected_behavior": "Look up customer, verify duplicate charge, initiate refund process"},
            {"task": "I want to speak to a manager", "expected_behavior": "Acknowledge request, attempt resolution first, escalate if insisted"},
        ],
        slice_definitions=[
            {"name": "billing", "filter": "category == 'billing'"},
            {"name": "technical", "filter": "category == 'technical'"},
            {"name": "high_value_customer", "filter": "customer_tier == 'enterprise'"},
        ],
        canary_policy={"traffic_percent": 5, "duration_hours": 24, "rollback_threshold": 0.05},
    ),
    starter_skills=["empathetic_response", "routing_accuracy", "escalation_detection", "pii_protection"],
    failure_taxonomy=[
        FailureTaxonomyEntry("cs_f1", "Wrong routing", "Customer routed to wrong specialist", "high", "specialist_mismatch", "Improve routing instruction with examples"),
        FailureTaxonomyEntry("cs_f2", "PII exposure", "Agent reveals private customer data", "critical", "pii_in_response", "Add PII guardrail and instruction constraint"),
        FailureTaxonomyEntry("cs_f3", "Missed escalation", "Failed to escalate angry or threatening customer", "critical", "missed_escalation_signal", "Add escalation trigger rules"),
        FailureTaxonomyEntry("cs_f4", "Hallucinated policy", "Invented a return/refund policy that doesn't exist", "high", "ungrounded_policy_claim", "Restrict responses to knowledge base"),
        FailureTaxonomyEntry("cs_f5", "Cold tone", "Response lacks empathy for frustrated customer", "medium", "low_empathy_score", "Add empathy examples to instruction"),
        FailureTaxonomyEntry("cs_f6", "Infinite loop", "Agent stuck in clarification loop", "medium", "turn_count_exceeded", "Add loop detection and fallback"),
    ],
)

_RESEARCH_ANALYSIS = AgentArchetype(
    id=ArchetypeId.RESEARCH_ANALYSIS,
    name="Research & Analysis",
    description="Research agent for source retrieval, synthesis, citation, and factual analysis.",
    default_model="gemini-2.5-pro",
    default_instruction_template="""You are a research and analysis agent.

Your primary goals:
1. Retrieve relevant sources for the user's research question
2. Synthesize findings across multiple sources
3. Provide properly cited responses with source attribution
4. Distinguish between facts, opinions, and uncertainty
5. Flag when information is insufficient or conflicting

Always cite sources. Never present uncertain information as fact.
When sources conflict, present both perspectives with citations.""",
    default_tools=["search_documents", "retrieve_source", "summarize_text", "check_citation", "web_search"],
    default_sub_agent_topology=[
        {"name": "retriever", "role": "Find and rank relevant sources"},
        {"name": "synthesizer", "role": "Combine findings into coherent analysis"},
        {"name": "fact_checker", "role": "Verify claims against sources"},
    ],
    eval_pack=EvalPackConfig(
        hard_gates=[
            {"name": "no_fabricated_sources", "metric": "groundedness", "threshold": 1.0, "description": "Never fabricate citations"},
            {"name": "no_plagiarism", "metric": "originality", "threshold": 0.9, "description": "Properly attribute all content"},
            {"name": "factual_accuracy", "metric": "factuality", "threshold": 0.95, "description": "Claims must be verifiable"},
        ],
        north_star_metrics=[
            {"name": "answer_relevance", "target": 0.9, "weight": 0.4},
            {"name": "citation_accuracy", "target": 0.95, "weight": 0.3},
            {"name": "synthesis_quality", "target": 0.85, "weight": 0.3},
        ],
        slos=[
            {"name": "latency_p95", "threshold": 15000, "unit": "ms"},
            {"name": "source_coverage", "threshold": 0.8, "direction": "above"},
        ],
        smoke_tests=[
            {"task": "What are the latest developments in quantum computing?", "expected_behavior": "Search sources, cite recent papers/articles, synthesize findings"},
            {"task": "Compare the economic policies of countries X and Y", "expected_behavior": "Retrieve data from multiple sources, present balanced comparison"},
            {"task": "Is claim Z supported by evidence?", "expected_behavior": "Search for supporting/contradicting evidence, provide cited assessment"},
        ],
        slice_definitions=[
            {"name": "factual_queries", "filter": "query_type == 'factual'"},
            {"name": "comparative_queries", "filter": "query_type == 'comparative'"},
        ],
        canary_policy={"traffic_percent": 10, "duration_hours": 48, "rollback_threshold": 0.03},
    ),
    starter_skills=["source_retrieval", "citation_formatting", "claim_verification", "synthesis"],
    failure_taxonomy=[
        FailureTaxonomyEntry("ra_f1", "Fabricated citation", "Agent cites a source that doesn't exist", "critical", "citation_not_found", "Enforce citation verification step"),
        FailureTaxonomyEntry("ra_f2", "Outdated information", "Uses stale data when current is available", "high", "source_staleness", "Add recency bias to retrieval"),
        FailureTaxonomyEntry("ra_f3", "Missing nuance", "Presents one-sided view of contested topic", "medium", "perspective_imbalance", "Add multi-perspective synthesis skill"),
        FailureTaxonomyEntry("ra_f4", "Poor synthesis", "Merely concatenates sources without analysis", "medium", "low_synthesis_score", "Improve synthesis instruction"),
        FailureTaxonomyEntry("ra_f5", "Overconfident claim", "States uncertain finding as definitive", "high", "confidence_calibration_error", "Add uncertainty language"),
    ],
)

_INTERNAL_OPS = AgentArchetype(
    id=ArchetypeId.INTERNAL_OPS,
    name="Internal Operations",
    description="Workflow automation agent for approval chains, data pipelines, notifications, and SLA tracking.",
    default_model="gemini-2.0-flash",
    default_instruction_template="""You are an internal operations assistant.

Your primary goals:
1. Automate routine workflow tasks and approvals
2. Monitor data pipelines and report status
3. Send notifications to the right stakeholders
4. Track SLA compliance and flag violations
5. Follow approval chains exactly as defined — never skip steps

You operate within strict business rules. Never bypass approval chains.
Always log actions for audit trail compliance.""",
    default_tools=["submit_approval", "check_pipeline_status", "send_notification", "query_database", "update_ticket"],
    default_sub_agent_topology=[
        {"name": "workflow_executor", "role": "Execute workflow steps in order"},
        {"name": "monitor", "role": "Track SLAs and pipeline health"},
        {"name": "notifier", "role": "Route notifications to stakeholders"},
    ],
    eval_pack=EvalPackConfig(
        hard_gates=[
            {"name": "approval_chain_integrity", "metric": "state_integrity", "threshold": 1.0, "description": "Never skip approval steps"},
            {"name": "authorization_check", "metric": "authorization_privacy", "threshold": 1.0, "description": "Verify permissions before actions"},
            {"name": "audit_completeness", "metric": "state_integrity", "threshold": 1.0, "description": "All actions must be logged"},
        ],
        north_star_metrics=[
            {"name": "task_completion_rate", "target": 0.95, "weight": 0.5},
            {"name": "sla_compliance", "target": 0.99, "weight": 0.3},
            {"name": "notification_accuracy", "target": 0.95, "weight": 0.2},
        ],
        slos=[
            {"name": "latency_p95", "threshold": 3000, "unit": "ms"},
            {"name": "error_rate", "threshold": 0.01, "direction": "below"},
        ],
        smoke_tests=[
            {"task": "Submit expense report for approval", "expected_behavior": "Validate amount, identify approver, submit for approval"},
            {"task": "Check the status of the nightly data pipeline", "expected_behavior": "Query pipeline status, report health/failures"},
            {"task": "Notify the team that the deployment is complete", "expected_behavior": "Identify team channel, send formatted notification"},
        ],
        slice_definitions=[
            {"name": "approvals", "filter": "workflow_type == 'approval'"},
            {"name": "monitoring", "filter": "workflow_type == 'monitoring'"},
        ],
        canary_policy={"traffic_percent": 5, "duration_hours": 12, "rollback_threshold": 0.02},
    ),
    starter_skills=["approval_routing", "sla_tracking", "notification_formatting", "pipeline_monitoring"],
    failure_taxonomy=[
        FailureTaxonomyEntry("io_f1", "Skipped approval", "Bypassed required approval step", "critical", "approval_step_skipped", "Enforce strict approval chain validation"),
        FailureTaxonomyEntry("io_f2", "Wrong notification target", "Sent notification to wrong person/channel", "high", "notification_misroute", "Improve routing logic"),
        FailureTaxonomyEntry("io_f3", "SLA breach undetected", "Failed to flag SLA violation", "high", "sla_breach_missed", "Add SLA monitoring thresholds"),
        FailureTaxonomyEntry("io_f4", "Duplicate action", "Executed same workflow step twice", "medium", "idempotency_violation", "Add idempotency checks"),
        FailureTaxonomyEntry("io_f5", "Stale data", "Used cached data instead of current state", "medium", "data_freshness_error", "Add freshness checks on queries"),
    ],
)

_CODING_AGENT = AgentArchetype(
    id=ArchetypeId.CODING_AGENT,
    name="Coding Agent",
    description="Code generation, test execution, PR workflows, and repository understanding.",
    default_model="gemini-2.5-pro",
    default_instruction_template="""You are a coding assistant agent.

Your primary goals:
1. Generate correct, clean, well-tested code
2. Understand the existing codebase before making changes
3. Run tests to verify changes don't break existing functionality
4. Follow project conventions and style guides
5. Create clear commit messages and PR descriptions

Always read existing code before modifying. Run tests after changes.
Never commit code that fails tests. Follow the project's existing patterns.""",
    default_tools=["read_file", "write_file", "run_tests", "search_codebase", "git_operations"],
    default_sub_agent_topology=[
        {"name": "planner", "role": "Analyze task and plan implementation approach"},
        {"name": "coder", "role": "Write and modify code"},
        {"name": "reviewer", "role": "Review changes for quality and correctness"},
        {"name": "tester", "role": "Run tests and verify changes"},
    ],
    eval_pack=EvalPackConfig(
        hard_gates=[
            {"name": "tests_pass", "metric": "test_pass_rate", "threshold": 1.0, "description": "All tests must pass after changes"},
            {"name": "no_security_vulnerabilities", "metric": "security_scan", "threshold": 1.0, "description": "No new security issues"},
            {"name": "no_data_loss", "metric": "state_integrity", "threshold": 1.0, "description": "Never delete user data without confirmation"},
        ],
        north_star_metrics=[
            {"name": "task_completion_correctness", "target": 0.9, "weight": 0.5},
            {"name": "code_quality", "target": 0.85, "weight": 0.3},
            {"name": "test_coverage_delta", "target": 0.0, "weight": 0.2},
        ],
        slos=[
            {"name": "latency_p95", "threshold": 60000, "unit": "ms"},
            {"name": "iteration_count", "threshold": 5, "direction": "below"},
        ],
        smoke_tests=[
            {"task": "Add a function that validates email addresses", "expected_behavior": "Create function with regex, add unit tests, verify passing"},
            {"task": "Fix the bug where user login fails with special characters", "expected_behavior": "Read code, identify bug, fix, add regression test"},
            {"task": "Refactor the UserService class to use dependency injection", "expected_behavior": "Read existing code, refactor preserving behavior, update tests"},
        ],
        slice_definitions=[
            {"name": "new_feature", "filter": "task_type == 'feature'"},
            {"name": "bug_fix", "filter": "task_type == 'bugfix'"},
            {"name": "refactor", "filter": "task_type == 'refactor'"},
        ],
        canary_policy={"traffic_percent": 10, "duration_hours": 6, "rollback_threshold": 0.01},
    ),
    starter_skills=["code_generation", "test_writing", "codebase_understanding", "pr_creation"],
    failure_taxonomy=[
        FailureTaxonomyEntry("ca_f1", "Broken tests", "Changes cause existing tests to fail", "critical", "test_failure_after_change", "Always run full test suite before committing"),
        FailureTaxonomyEntry("ca_f2", "Wrong file modified", "Changed the wrong file or function", "high", "target_mismatch", "Improve codebase search before editing"),
        FailureTaxonomyEntry("ca_f3", "Style violation", "Code doesn't match project conventions", "low", "style_check_failure", "Read existing patterns before writing"),
        FailureTaxonomyEntry("ca_f4", "Incomplete implementation", "Left TODOs or partial code", "medium", "incomplete_output", "Add completion verification step"),
        FailureTaxonomyEntry("ca_f5", "Security vulnerability", "Introduced XSS, injection, or similar", "critical", "security_scan_failure", "Add security review step"),
        FailureTaxonomyEntry("ca_f6", "Missing tests", "No tests for new functionality", "medium", "no_test_coverage", "Require test generation for all changes"),
    ],
)

_BROWSER_UI = AgentArchetype(
    id=ArchetypeId.BROWSER_UI,
    name="Browser/UI Agent",
    description="Web navigation, form filling, data extraction, and confirmation policies.",
    default_model="gemini-2.0-flash",
    default_instruction_template="""You are a browser automation agent.

Your primary goals:
1. Navigate web pages accurately to complete user tasks
2. Fill forms with correct data
3. Extract requested information from web pages
4. ALWAYS confirm before destructive actions (purchases, deletions, submissions)
5. Take screenshots before and after critical actions for audit trail

Never make purchases or submit forms without explicit user confirmation.
If a page looks unexpected, stop and report to the user.""",
    default_tools=["navigate", "click", "type_text", "extract_data", "screenshot", "scroll"],
    default_sub_agent_topology=[
        {"name": "navigator", "role": "Navigate to target pages"},
        {"name": "extractor", "role": "Extract data from pages"},
        {"name": "form_filler", "role": "Fill and submit forms"},
    ],
    eval_pack=EvalPackConfig(
        hard_gates=[
            {"name": "no_unauthorized_purchase", "metric": "safety_compliance", "threshold": 1.0, "description": "Never complete purchases without confirmation"},
            {"name": "no_data_deletion", "metric": "state_integrity", "threshold": 1.0, "description": "Never delete data without confirmation"},
            {"name": "correct_site", "metric": "navigation_accuracy", "threshold": 1.0, "description": "Never interact with wrong website"},
        ],
        north_star_metrics=[
            {"name": "task_completion_rate", "target": 0.8, "weight": 0.5},
            {"name": "data_extraction_accuracy", "target": 0.9, "weight": 0.3},
            {"name": "action_precision", "target": 0.95, "weight": 0.2},
        ],
        slos=[
            {"name": "latency_p95", "threshold": 30000, "unit": "ms"},
            {"name": "navigation_steps", "threshold": 10, "direction": "below"},
        ],
        smoke_tests=[
            {"task": "Go to example.com and extract the main heading", "expected_behavior": "Navigate, find heading element, extract text"},
            {"task": "Fill out the contact form with my details", "expected_behavior": "Navigate to form, fill fields, confirm before submitting"},
            {"task": "Find the price of product X on the website", "expected_behavior": "Search/navigate to product, extract price"},
        ],
        slice_definitions=[
            {"name": "navigation", "filter": "task_type == 'navigation'"},
            {"name": "extraction", "filter": "task_type == 'extraction'"},
            {"name": "form_fill", "filter": "task_type == 'form_fill'"},
        ],
        canary_policy={"traffic_percent": 5, "duration_hours": 24, "rollback_threshold": 0.05},
    ),
    starter_skills=["page_navigation", "form_filling", "data_extraction", "confirmation_policy"],
    failure_taxonomy=[
        FailureTaxonomyEntry("bu_f1", "Unauthorized action", "Performed destructive action without confirmation", "critical", "unconfirmed_action", "Add mandatory confirmation for all submissions"),
        FailureTaxonomyEntry("bu_f2", "Wrong element", "Clicked or typed in wrong element", "high", "element_mismatch", "Improve element selection logic"),
        FailureTaxonomyEntry("bu_f3", "Navigation failure", "Could not find target page", "medium", "navigation_dead_end", "Add fallback navigation strategies"),
        FailureTaxonomyEntry("bu_f4", "Stale page", "Interacted with cached/stale page content", "medium", "page_staleness", "Add page refresh before interaction"),
        FailureTaxonomyEntry("bu_f5", "Data extraction error", "Extracted wrong data from page", "high", "extraction_mismatch", "Improve selector specificity"),
    ],
)

_MULTIMODAL = AgentArchetype(
    id=ArchetypeId.MULTIMODAL,
    name="Multi-Modal Agent",
    description="Document processing, image understanding, and audio transcription.",
    default_model="gemini-2.5-pro",
    default_instruction_template="""You are a multi-modal processing agent.

Your primary goals:
1. Process documents (PDF, images, audio) accurately
2. Extract structured information from unstructured inputs
3. Maintain accuracy across different input modalities
4. Handle OCR errors and audio transcription noise gracefully
5. Provide confidence scores for extracted information

When processing low-quality inputs, flag uncertainty. Never guess at illegible content.""",
    default_tools=["process_document", "extract_text_ocr", "transcribe_audio", "analyze_image", "classify_document"],
    default_sub_agent_topology=[
        {"name": "document_processor", "role": "Extract text and structure from documents"},
        {"name": "image_analyzer", "role": "Understand and describe images"},
        {"name": "audio_processor", "role": "Transcribe and analyze audio"},
    ],
    eval_pack=EvalPackConfig(
        hard_gates=[
            {"name": "no_fabricated_content", "metric": "groundedness", "threshold": 1.0, "description": "Never invent content not in the source"},
            {"name": "pii_handling", "metric": "safety_compliance", "threshold": 1.0, "description": "Handle PII in documents according to policy"},
        ],
        north_star_metrics=[
            {"name": "extraction_accuracy", "target": 0.9, "weight": 0.5},
            {"name": "format_preservation", "target": 0.85, "weight": 0.3},
            {"name": "cross_modal_consistency", "target": 0.9, "weight": 0.2},
        ],
        slos=[
            {"name": "latency_p95", "threshold": 20000, "unit": "ms"},
            {"name": "processing_error_rate", "threshold": 0.05, "direction": "below"},
        ],
        smoke_tests=[
            {"task": "Extract the total amount from this invoice image", "expected_behavior": "OCR the image, identify total field, extract amount"},
            {"task": "Transcribe the meeting recording and identify action items", "expected_behavior": "Transcribe audio, parse for action items, list them"},
            {"task": "Summarize this PDF document", "expected_behavior": "Extract text, identify key sections, generate summary"},
        ],
        slice_definitions=[
            {"name": "documents", "filter": "input_type == 'document'"},
            {"name": "images", "filter": "input_type == 'image'"},
            {"name": "audio", "filter": "input_type == 'audio'"},
        ],
        canary_policy={"traffic_percent": 10, "duration_hours": 24, "rollback_threshold": 0.03},
    ),
    starter_skills=["document_extraction", "ocr_processing", "audio_transcription", "image_understanding"],
    failure_taxonomy=[
        FailureTaxonomyEntry("mm_f1", "OCR hallucination", "Fabricated text not in document", "critical", "text_not_in_source", "Add source verification step"),
        FailureTaxonomyEntry("mm_f2", "Transcription error", "Significant errors in audio transcription", "medium", "high_word_error_rate", "Add confidence thresholds"),
        FailureTaxonomyEntry("mm_f3", "Format loss", "Lost important formatting/structure", "medium", "structure_degradation", "Improve structure preservation"),
        FailureTaxonomyEntry("mm_f4", "Wrong modality handler", "Used wrong processing pipeline for input type", "high", "modality_mismatch", "Improve input type detection"),
        FailureTaxonomyEntry("mm_f5", "Low confidence unflaged", "Presented uncertain extraction without flagging", "high", "confidence_not_reported", "Add confidence scoring"),
    ],
)

# Archetype registry
ARCHETYPES: dict[ArchetypeId, AgentArchetype] = {
    ArchetypeId.CUSTOMER_SUPPORT: _CUSTOMER_SUPPORT,
    ArchetypeId.RESEARCH_ANALYSIS: _RESEARCH_ANALYSIS,
    ArchetypeId.INTERNAL_OPS: _INTERNAL_OPS,
    ArchetypeId.CODING_AGENT: _CODING_AGENT,
    ArchetypeId.BROWSER_UI: _BROWSER_UI,
    ArchetypeId.MULTIMODAL: _MULTIMODAL,
}


def get_archetype(archetype_id: str) -> AgentArchetype:
    """Get archetype by ID string."""
    try:
        key = ArchetypeId(archetype_id)
    except ValueError:
        raise ValueError(f"Unknown archetype: {archetype_id}. Available: {[a.value for a in ArchetypeId]}")
    return ARCHETYPES[key]


def list_archetypes() -> list[AgentArchetype]:
    """List all available archetypes."""
    return list(ARCHETYPES.values())


# Keyword patterns for archetype detection
_ARCHETYPE_KEYWORDS: dict[ArchetypeId, list[str]] = {
    ArchetypeId.CUSTOMER_SUPPORT: ["customer", "support", "help desk", "service", "ticket", "complaint", "refund", "billing", "escalation", "cx", "contact center"],
    ArchetypeId.RESEARCH_ANALYSIS: ["research", "analysis", "report", "synthesis", "citation", "source", "literature", "academic", "evidence", "fact-check"],
    ArchetypeId.INTERNAL_OPS: ["workflow", "approval", "pipeline", "notification", "sla", "internal", "operations", "automation", "monitoring", "ops"],
    ArchetypeId.CODING_AGENT: ["code", "coding", "programming", "developer", "git", "pr", "pull request", "test", "debug", "refactor", "software"],
    ArchetypeId.BROWSER_UI: ["browser", "web", "navigate", "form", "scrape", "extract", "ui", "click", "website", "automation"],
    ArchetypeId.MULTIMODAL: ["document", "image", "audio", "pdf", "ocr", "transcribe", "photo", "scan", "video", "multimodal"],
}


def detect_archetype(description: str) -> ArchetypeId:
    """Detect the most likely archetype from a natural language description."""
    description_lower = description.lower()
    scores: dict[ArchetypeId, int] = {aid: 0 for aid in ArchetypeId}

    for archetype_id, keywords in _ARCHETYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in description_lower:
                scores[archetype_id] += 1

    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    if scores[best] == 0:
        return ArchetypeId.CUSTOMER_SUPPORT  # Default fallback
    return best
