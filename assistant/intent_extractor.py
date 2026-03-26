"""Extract intents and entities from customer support transcripts.

This module analyzes conversation transcripts to discover:
- User intents (billing, shipping, returns, technical support, etc.)
- Entities (order IDs, product names, account numbers, etc.)
- Routing patterns (which topics go where)
- Edge cases and failure modes
- Successful resolution patterns
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from optimizer.providers import LLMRequest, LLMRouter


@dataclass
class Entity:
    """Extracted entity from a conversation."""

    entity_type: str  # "order_id", "product_name", "account_number", etc.
    value: str
    confidence: float = 1.0
    conversation_id: str = ""


@dataclass
class Intent:
    """Discovered user intent."""

    name: str  # "billing_inquiry", "shipping_status", "product_return", etc.
    description: str
    keywords: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    example_utterances: list[str] = field(default_factory=list)
    frequency: int = 0
    success_rate: float = 0.0
    avg_turns: float = 0.0
    requires_tools: list[str] = field(default_factory=list)


@dataclass
class RoutingPattern:
    """Discovered routing pattern from transcripts."""

    intent_name: str
    specialist_name: str
    confidence: float
    supporting_keywords: list[str] = field(default_factory=list)


@dataclass
class FailureMode:
    """Discovered failure pattern."""

    failure_type: str  # "routing_error", "missing_tool", "unclear_response", etc.
    description: str
    frequency: int = 0
    severity: float = 0.0  # 0-1
    example_conversation_ids: list[str] = field(default_factory=list)
    suggested_fix: str = ""


@dataclass
class ConversationAnalysis:
    """Results from analyzing a single conversation."""

    conversation_id: str
    intents: list[str]
    entities: list[Entity]
    success: bool
    turn_count: int
    failure_modes: list[str] = field(default_factory=list)
    resolution_pattern: str = ""


class IntentExtractor:
    """Extract intents and entities from conversation transcripts using LLM analysis."""

    def __init__(self, llm_router: LLMRouter | None = None, use_mock: bool = False):
        """Initialize intent extractor.

        Args:
            llm_router: LLM router for semantic analysis. If None, creates default.
            use_mock: If True, use mock extraction for testing.
        """
        self.llm_router = llm_router
        self.use_mock = use_mock

    async def extract_intents(
        self, conversations: list[dict[str, Any]]
    ) -> tuple[list[Intent], list[RoutingPattern], list[FailureMode], list[str]]:
        """Extract intents, routing patterns, and failure modes from conversations.

        Args:
            conversations: List of conversation dicts with format:
                {
                    "id": str,
                    "messages": [{"role": "user"|"agent", "content": str}, ...],
                    "success": bool (optional),
                    "metadata": dict (optional)
                }

        Returns:
            Tuple of (intents, routing_patterns, failure_modes, required_tools)
        """
        if self.use_mock:
            return self._mock_extract(conversations)

        # Analyze each conversation
        analyses: list[ConversationAnalysis] = []
        for conv in conversations:
            analysis = await self._analyze_conversation(conv)
            analyses.append(analysis)

        # Aggregate results
        intents = self._aggregate_intents(analyses)
        routing_patterns = self._discover_routing(analyses, intents)
        failure_modes = self._discover_failures(analyses, conversations)
        required_tools = self._discover_tools(analyses, conversations)

        return intents, routing_patterns, failure_modes, required_tools

    async def _analyze_conversation(
        self, conversation: dict[str, Any]
    ) -> ConversationAnalysis:
        """Analyze a single conversation using LLM."""
        conv_id = conversation.get("id", "unknown")
        messages = conversation.get("messages", [])
        success = conversation.get("success", True)

        # Build conversation text
        conv_text = "\n".join(
            [f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" for msg in messages]
        )

        # Use LLM to extract intents and entities
        prompt = f"""Analyze this customer support conversation and extract:
1. The primary user intent(s) (e.g., billing_inquiry, shipping_status, product_return, etc.)
2. Any entities mentioned (order IDs, product names, account numbers, etc.)
3. Whether the conversation was successful
4. Any failure modes (routing errors, missing information, unclear responses, etc.)

Conversation:
{conv_text}

Return a JSON object with this structure:
{{
    "intents": ["intent_name1", "intent_name2"],
    "entities": [{{"type": "order_id", "value": "12345"}}, ...],
    "success": true/false,
    "failure_modes": ["failure_type1", ...],
    "resolution_pattern": "brief description of how it was resolved"
}}
"""

        if self.llm_router:
            request = LLMRequest(
                prompt=prompt,
                system="You are an expert at analyzing customer support conversations.",
                temperature=0.1,
                max_tokens=1000,
            )
            response = await self.llm_router.route_async(request)
            result = self._parse_llm_response(response.text)
        else:
            # Fallback to pattern matching if no LLM
            result = self._pattern_based_analysis(conv_text, success)

        entities = [
            Entity(
                entity_type=e.get("type", "unknown"),
                value=e.get("value", ""),
                conversation_id=conv_id,
            )
            for e in result.get("entities", [])
        ]

        return ConversationAnalysis(
            conversation_id=conv_id,
            intents=result.get("intents", []),
            entities=entities,
            success=result.get("success", success),
            turn_count=len(messages),
            failure_modes=result.get("failure_modes", []),
            resolution_pattern=result.get("resolution_pattern", ""),
        )

    def _parse_llm_response(self, text: str) -> dict[str, Any]:
        """Parse LLM JSON response, handling markdown code blocks."""
        # Extract JSON from markdown code blocks if present
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            text = json_match.group(1)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {
                "intents": [],
                "entities": [],
                "success": True,
                "failure_modes": [],
                "resolution_pattern": "",
            }

    def _pattern_based_analysis(
        self, conv_text: str, success: bool
    ) -> dict[str, Any]:
        """Fallback pattern-based analysis when no LLM available."""
        conv_lower = conv_text.lower()

        # Pattern-based intent detection
        intents = []
        if any(
            kw in conv_lower
            for kw in ["order", "tracking", "delivery", "shipping", "shipped"]
        ):
            intents.append("shipping_inquiry")
        if any(kw in conv_lower for kw in ["refund", "return", "send back"]):
            intents.append("product_return")
        if any(
            kw in conv_lower
            for kw in ["bill", "charge", "payment", "invoice", "receipt"]
        ):
            intents.append("billing_inquiry")
        if any(kw in conv_lower for kw in ["recommend", "suggest", "best", "top"]):
            intents.append("product_recommendation")
        if any(
            kw in conv_lower
            for kw in ["broken", "not working", "error", "issue", "problem"]
        ):
            intents.append("technical_support")

        if not intents:
            intents.append("general_inquiry")

        # Pattern-based entity extraction
        entities = []
        # Order IDs (pattern: #12345 or ORD-12345)
        order_ids = re.findall(r"(?:#|ORD-)(\d{5,})", conv_text)
        for oid in order_ids:
            entities.append({"type": "order_id", "value": oid})

        return {
            "intents": intents,
            "entities": entities,
            "success": success,
            "failure_modes": [] if success else ["unsuccessful_resolution"],
            "resolution_pattern": "resolved" if success else "unresolved",
        }

    def _aggregate_intents(self, analyses: list[ConversationAnalysis]) -> list[Intent]:
        """Aggregate individual conversation analyses into intent catalog."""
        intent_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "count": 0,
                "success_count": 0,
                "total_turns": 0,
                "utterances": [],
                "tools": set(),
            }
        )

        for analysis in analyses:
            for intent_name in analysis.intents:
                data = intent_data[intent_name]
                data["count"] += 1
                if analysis.success:
                    data["success_count"] += 1
                data["total_turns"] += analysis.turn_count
                # Store resolution patterns as example utterances
                if analysis.resolution_pattern:
                    data["utterances"].append(analysis.resolution_pattern)

        intents = []
        for intent_name, data in intent_data.items():
            count = data["count"]
            intents.append(
                Intent(
                    name=intent_name,
                    description=self._generate_intent_description(intent_name),
                    keywords=self._generate_intent_keywords(intent_name),
                    example_utterances=data["utterances"][:5],
                    frequency=count,
                    success_rate=data["success_count"] / count if count > 0 else 0.0,
                    avg_turns=data["total_turns"] / count if count > 0 else 0.0,
                    requires_tools=list(data["tools"]),
                )
            )

        # Sort by frequency
        intents.sort(key=lambda x: x.frequency, reverse=True)
        return intents

    def _generate_intent_description(self, intent_name: str) -> str:
        """Generate human-readable description for an intent."""
        descriptions = {
            "shipping_inquiry": "Questions about order shipping status, tracking, and delivery",
            "product_return": "Requests to return or exchange products",
            "billing_inquiry": "Questions about charges, payments, invoices, and refunds",
            "product_recommendation": "Requests for product suggestions and recommendations",
            "technical_support": "Technical issues and troubleshooting",
            "general_inquiry": "General questions and information requests",
            "account_management": "Account settings, profile updates, and access issues",
        }
        return descriptions.get(
            intent_name, f"User intent: {intent_name.replace('_', ' ')}"
        )

    def _generate_intent_keywords(self, intent_name: str) -> list[str]:
        """Generate keyword list for an intent."""
        keywords_map = {
            "shipping_inquiry": [
                "order",
                "tracking",
                "delivery",
                "shipping",
                "shipped",
                "arrive",
            ],
            "product_return": ["refund", "return", "send back", "exchange"],
            "billing_inquiry": [
                "bill",
                "charge",
                "payment",
                "invoice",
                "receipt",
                "refund",
            ],
            "product_recommendation": ["recommend", "suggest", "best", "top", "which"],
            "technical_support": [
                "broken",
                "not working",
                "error",
                "issue",
                "problem",
                "fix",
            ],
            "general_inquiry": ["help", "question", "info", "tell me"],
            "account_management": ["account", "login", "password", "profile", "settings"],
        }
        return keywords_map.get(intent_name, [])

    def _discover_routing(
        self, analyses: list[ConversationAnalysis], intents: list[Intent]
    ) -> list[RoutingPattern]:
        """Discover routing patterns from conversation analyses."""
        routing_patterns = []

        # Map intents to specialist domains
        intent_to_specialist = {
            "shipping_inquiry": "orders",
            "product_return": "orders",
            "billing_inquiry": "billing",
            "product_recommendation": "recommendations",
            "technical_support": "support",
            "general_inquiry": "support",
            "account_management": "support",
        }

        for intent in intents:
            specialist = intent_to_specialist.get(intent.name, "support")
            routing_patterns.append(
                RoutingPattern(
                    intent_name=intent.name,
                    specialist_name=specialist,
                    confidence=intent.success_rate,
                    supporting_keywords=intent.keywords,
                )
            )

        return routing_patterns

    def _discover_failures(
        self, analyses: list[ConversationAnalysis], conversations: list[dict[str, Any]]
    ) -> list[FailureMode]:
        """Discover failure modes from analyses."""
        failure_counts: dict[str, list[str]] = defaultdict(list)

        for analysis in analyses:
            for failure_type in analysis.failure_modes:
                failure_counts[failure_type].append(analysis.conversation_id)

        failures = []
        for failure_type, conv_ids in failure_counts.items():
            failures.append(
                FailureMode(
                    failure_type=failure_type,
                    description=self._generate_failure_description(failure_type),
                    frequency=len(conv_ids),
                    severity=self._estimate_severity(failure_type),
                    example_conversation_ids=conv_ids[:3],
                    suggested_fix=self._suggest_fix(failure_type),
                )
            )

        # Sort by frequency * severity
        failures.sort(key=lambda x: x.frequency * x.severity, reverse=True)
        return failures

    def _generate_failure_description(self, failure_type: str) -> str:
        """Generate description for a failure mode."""
        descriptions = {
            "routing_error": "User routed to wrong specialist agent",
            "missing_tool": "Required tool or API not available",
            "unclear_response": "Agent response was vague or unhelpful",
            "unsuccessful_resolution": "User issue not resolved",
            "timeout": "Conversation exceeded time/turn limits",
        }
        return descriptions.get(
            failure_type, f"Failure mode: {failure_type.replace('_', ' ')}"
        )

    def _estimate_severity(self, failure_type: str) -> float:
        """Estimate severity of a failure mode (0-1)."""
        severity_map = {
            "unsuccessful_resolution": 0.9,
            "routing_error": 0.7,
            "missing_tool": 0.8,
            "unclear_response": 0.6,
            "timeout": 0.5,
        }
        return severity_map.get(failure_type, 0.5)

    def _suggest_fix(self, failure_type: str) -> str:
        """Suggest a fix for a failure mode."""
        fixes = {
            "routing_error": "Improve routing keywords and patterns",
            "missing_tool": "Add required tool integration",
            "unclear_response": "Enhance agent instructions for clarity",
            "unsuccessful_resolution": "Review and improve agent training data",
            "timeout": "Optimize agent instructions and reduce complexity",
        }
        return fixes.get(failure_type, "Manual review required")

    def _discover_tools(
        self, analyses: list[ConversationAnalysis], conversations: list[dict[str, Any]]
    ) -> list[str]:
        """Discover required tools from conversation patterns."""
        tools = set()

        for analysis in analyses:
            for intent_name in analysis.intents:
                if intent_name in ["shipping_inquiry", "product_return"]:
                    tools.add("orders_db")
                elif intent_name == "billing_inquiry":
                    tools.add("billing_system")
                elif intent_name == "product_recommendation":
                    tools.add("catalog")
                elif intent_name == "technical_support":
                    tools.add("knowledge_base")

        return sorted(list(tools))

    def _mock_extract(
        self, conversations: list[dict[str, Any]]
    ) -> tuple[list[Intent], list[RoutingPattern], list[FailureMode], list[str]]:
        """Mock extraction for testing."""
        intents = [
            Intent(
                name="shipping_inquiry",
                description="Questions about order shipping status",
                keywords=["order", "tracking", "delivery", "shipping"],
                frequency=max(1, len(conversations) // 3),
                success_rate=0.85,
                avg_turns=4.2,
            ),
            Intent(
                name="product_return",
                description="Requests to return products",
                keywords=["refund", "return", "send back"],
                frequency=max(1, len(conversations) // 5),
                success_rate=0.75,
                avg_turns=5.8,
            ),
            Intent(
                name="billing_inquiry",
                description="Questions about charges and payments",
                keywords=["bill", "charge", "payment", "invoice"],
                frequency=max(1, len(conversations) // 4),
                success_rate=0.90,
                avg_turns=3.5,
            ),
        ]

        routing_patterns = [
            RoutingPattern(
                intent_name="shipping_inquiry",
                specialist_name="orders",
                confidence=0.85,
                supporting_keywords=["order", "tracking", "delivery"],
            ),
            RoutingPattern(
                intent_name="product_return",
                specialist_name="orders",
                confidence=0.75,
                supporting_keywords=["refund", "return"],
            ),
            RoutingPattern(
                intent_name="billing_inquiry",
                specialist_name="billing",
                confidence=0.90,
                supporting_keywords=["bill", "charge", "payment"],
            ),
        ]

        failure_modes = [
            FailureMode(
                failure_type="routing_error",
                description="User routed to wrong specialist",
                frequency=int(len(conversations) * 0.1),
                severity=0.7,
                suggested_fix="Add more routing keywords",
            )
        ]

        tools = ["orders_db", "catalog", "billing_system"]

        return intents, routing_patterns, failure_modes, tools
