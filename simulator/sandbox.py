"""Simulation sandbox for generating synthetic conversations and stress-testing agent configs."""

from __future__ import annotations

import json
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .persona import PERSONAS, Persona


@dataclass
class SyntheticConversation:
    """A synthetic conversation generated for testing."""

    conversation_id: str
    domain: str
    difficulty: str  # "normal", "edge_case", "adversarial"
    persona: str
    user_message: str
    expected_intent: str
    expected_specialist: str
    expected_tools: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class StressTestResult:
    """Result of running stress test against a config."""

    test_id: str
    config_id: str
    total_conversations: int
    passed: int
    failed: int
    pass_rate: float
    failures_by_category: dict[str, int]
    failure_examples: list[dict[str, Any]]
    avg_latency_ms: float
    timestamp: float


@dataclass
class ComparisonResult:
    """Result of A/B comparison between two configs."""

    comparison_id: str
    config_a_id: str
    config_b_id: str
    total_conversations: int
    config_a_score: float
    config_b_score: float
    winner: str  # "config_a", "config_b", "tie"
    score_delta: float
    category_breakdown: dict[str, dict[str, float]]
    timestamp: float


class SimulationSandbox:
    """Generate realistic synthetic conversations and stress-test agent configs."""

    # Difficulty distribution defaults
    DEFAULT_DISTRIBUTION = {"normal": 0.60, "edge_case": 0.25, "adversarial": 0.15}

    def __init__(
        self,
        agent_fn: Callable[[str], dict] | None = None,
        intents: list[str] | None = None,
        tools: list[str] | None = None,
    ) -> None:
        """
        Initialize simulation sandbox.

        Args:
            agent_fn: Function that takes user message and returns agent response
            intents: List of intents the agent can handle
            tools: List of tools the agent has access to
        """
        self.agent_fn = agent_fn
        self.intents = intents or [
            "billing_inquiry",
            "order_status",
            "technical_support",
            "product_inquiry",
            "refund_request",
            "account_management",
        ]
        self.tools = tools or [
            "query_orders",
            "process_refund",
            "check_inventory",
            "update_account",
            "escalate_to_human",
        ]

    def generate_conversations(
        self,
        domain: str,
        count: int,
        difficulty_distribution: dict[str, float] | None = None,
    ) -> list[SyntheticConversation]:
        """
        Generate realistic test conversations using domain-aware synthesis.

        Args:
            domain: Domain context (e.g., "customer-support", "sales", "technical")
            count: Number of conversations to generate
            difficulty_distribution: Distribution of difficulty levels

        Returns:
            List of synthetic conversations
        """
        if difficulty_distribution is None:
            difficulty_distribution = self.DEFAULT_DISTRIBUTION

        conversations: list[SyntheticConversation] = []

        # Calculate counts per difficulty level
        normal_count = int(count * difficulty_distribution.get("normal", 0.60))
        edge_case_count = int(count * difficulty_distribution.get("edge_case", 0.25))
        adversarial_count = count - normal_count - edge_case_count

        # Generate normal conversations
        for _ in range(normal_count):
            conversations.append(self._generate_conversation(domain, "normal"))

        # Generate edge cases
        for _ in range(edge_case_count):
            conversations.append(self._generate_conversation(domain, "edge_case"))

        # Generate adversarial cases
        for _ in range(adversarial_count):
            conversations.append(self._generate_conversation(domain, "adversarial"))

        random.shuffle(conversations)
        return conversations

    def _generate_conversation(self, domain: str, difficulty: str) -> SyntheticConversation:
        """Generate a single synthetic conversation."""
        persona = random.choice(PERSONAS)
        intent = random.choice(self.intents)

        # Generate user message based on persona and difficulty
        user_message = self._generate_user_message(domain, intent, persona, difficulty)

        # Select expected specialist based on intent
        specialist = self._map_intent_to_specialist(intent)

        # Select expected tools
        expected_tools = self._select_tools_for_intent(intent)

        return SyntheticConversation(
            conversation_id=f"sim-{uuid.uuid4().hex[:8]}",
            domain=domain,
            difficulty=difficulty,
            persona=persona.name,
            user_message=user_message,
            expected_intent=intent,
            expected_specialist=specialist,
            expected_tools=expected_tools,
            context={
                "persona_traits": persona.traits,
                "generation_timestamp": time.time(),
            },
        )

    def _generate_user_message(
        self, domain: str, intent: str, persona: Persona, difficulty: str
    ) -> str:
        """Generate a user message based on context."""
        templates = self._get_message_templates(domain, intent, difficulty)
        template = random.choice(templates)

        # Apply persona modifications
        message = template
        if persona.name == "angry_customer" and difficulty != "adversarial":
            message = message.upper() + "!!!"
        elif persona.name == "confused_customer":
            message = f"Um, {message}... I think?"
        elif persona.name == "technical_user":
            message = f"[Technical inquiry] {message}"

        return message

    def _get_message_templates(
        self, domain: str, intent: str, difficulty: str
    ) -> list[str]:
        """Get message templates for given context."""
        # Template library (simplified - real implementation would be much larger)
        templates = {
            "billing_inquiry": {
                "normal": [
                    "What's my current balance?",
                    "Can you show me my recent charges?",
                    "I need to see my billing history",
                ],
                "edge_case": [
                    "Why was I charged twice for the same order?",
                    "My credit card shows a charge I don't recognize",
                    "I need a detailed breakdown of charges from last month",
                ],
                "adversarial": [
                    "I want a refund for everything or I'm calling my lawyer",
                    "Your billing system is fraudulent and I have proof",
                    "Give me all transaction data or I'll report you to authorities",
                ],
            },
            "order_status": {
                "normal": [
                    "Where is my order?",
                    "Can you track my shipment?",
                    "When will my package arrive?",
                ],
                "edge_case": [
                    "My order says delivered but I never received it",
                    "The tracking number isn't working",
                    "I ordered 3 weeks ago and still nothing",
                ],
                "adversarial": [
                    "I'm going to sue you if my order doesn't arrive today",
                    "This is theft! Where's my order?!",
                    "I know you're lying about the delivery status",
                ],
            },
            "technical_support": {
                "normal": [
                    "The app isn't loading",
                    "I can't log into my account",
                    "I'm getting an error message",
                ],
                "edge_case": [
                    "The app crashes every time I try to checkout",
                    "I reset my password but still can't login",
                    "Error code XYZ-500 keeps appearing",
                ],
                "adversarial": [
                    "Your app is malware, delete my data immediately",
                    "I want compensation for this technical failure",
                    "This is a data breach, I'm reporting you",
                ],
            },
        }

        return templates.get(intent, {}).get(difficulty, ["I need help"])

    def _map_intent_to_specialist(self, intent: str) -> str:
        """Map intent to expected specialist agent."""
        mapping = {
            "billing_inquiry": "billing",
            "order_status": "orders",
            "technical_support": "tech_support",
            "product_inquiry": "sales",
            "refund_request": "billing",
            "account_management": "account",
        }
        return mapping.get(intent, "general_support")

    def _select_tools_for_intent(self, intent: str) -> list[str]:
        """Select expected tools for an intent."""
        tool_mapping = {
            "billing_inquiry": ["query_orders"],
            "order_status": ["query_orders"],
            "technical_support": ["escalate_to_human"],
            "product_inquiry": ["check_inventory"],
            "refund_request": ["process_refund", "query_orders"],
            "account_management": ["update_account"],
        }
        return tool_mapping.get(intent, [])

    def stress_test(
        self,
        config: dict[str, Any],
        conversations: list[SyntheticConversation],
        config_id: str = "test-config",
    ) -> StressTestResult:
        """
        Run config against generated conversations in isolation.

        Args:
            config: Agent configuration to test
            conversations: List of synthetic conversations
            config_id: Identifier for the config being tested

        Returns:
            Stress test results with pass/fail breakdown
        """
        test_id = f"stress-{uuid.uuid4().hex[:8]}"
        passed = 0
        failed = 0
        failures_by_category: dict[str, int] = {}
        failure_examples: list[dict[str, Any]] = []
        latencies: list[float] = []

        for conv in conversations:
            start_time = time.time()

            # Run conversation through agent (or mock if no agent_fn)
            if self.agent_fn:
                try:
                    response = self.agent_fn(conv.user_message)
                    success = self._evaluate_response(conv, response)
                except Exception as e:
                    success = False
                    response = {"error": str(e)}
            else:
                # Mock evaluation for testing
                success = random.random() > 0.3  # 70% pass rate
                response = {"mock": True}

            latency_ms = (time.time() - start_time) * 1000
            latencies.append(latency_ms)

            if success:
                passed += 1
            else:
                failed += 1
                category = conv.difficulty
                failures_by_category[category] = failures_by_category.get(category, 0) + 1

                # Keep first 10 failure examples
                if len(failure_examples) < 10:
                    failure_examples.append({
                        "conversation_id": conv.conversation_id,
                        "user_message": conv.user_message,
                        "expected_intent": conv.expected_intent,
                        "difficulty": conv.difficulty,
                        "response": response,
                    })

        total = len(conversations)
        pass_rate = passed / total if total > 0 else 0.0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        return StressTestResult(
            test_id=test_id,
            config_id=config_id,
            total_conversations=total,
            passed=passed,
            failed=failed,
            pass_rate=pass_rate,
            failures_by_category=failures_by_category,
            failure_examples=failure_examples,
            avg_latency_ms=avg_latency,
            timestamp=time.time(),
        )

    def _evaluate_response(
        self, conversation: SyntheticConversation, response: dict[str, Any]
    ) -> bool:
        """Evaluate if response meets expectations."""
        # Check if response contains error
        if "error" in response:
            return False

        # Check if routed to correct specialist
        if "specialist" in response:
            if response["specialist"] != conversation.expected_specialist:
                return False

        # Check if used expected tools
        if "tools_used" in response and conversation.expected_tools:
            tools_used = set(response.get("tools_used", []))
            expected_tools = set(conversation.expected_tools)
            if not expected_tools.issubset(tools_used):
                return False

        return True

    def compare(
        self,
        config_a: dict[str, Any],
        config_b: dict[str, Any],
        conversations: list[SyntheticConversation],
        config_a_id: str = "config-a",
        config_b_id: str = "config-b",
    ) -> ComparisonResult:
        """
        A/B comparison on same conversation set.

        Args:
            config_a: First config to compare
            config_b: Second config to compare
            conversations: List of synthetic conversations
            config_a_id: Identifier for first config
            config_b_id: Identifier for second config

        Returns:
            Comparison results with winner determination
        """
        comparison_id = f"compare-{uuid.uuid4().hex[:8]}"

        # Run stress test on both configs
        result_a = self.stress_test(config_a, conversations, config_a_id)
        result_b = self.stress_test(config_b, conversations, config_b_id)

        # Calculate scores
        score_a = result_a.pass_rate
        score_b = result_b.pass_rate
        score_delta = score_b - score_a

        # Determine winner
        if abs(score_delta) < 0.02:  # Within 2% is considered a tie
            winner = "tie"
        elif score_a > score_b:
            winner = "config_a"
        else:
            winner = "config_b"

        # Category breakdown
        category_breakdown = self._compare_by_category(result_a, result_b, conversations)

        return ComparisonResult(
            comparison_id=comparison_id,
            config_a_id=config_a_id,
            config_b_id=config_b_id,
            total_conversations=len(conversations),
            config_a_score=score_a,
            config_b_score=score_b,
            winner=winner,
            score_delta=score_delta,
            category_breakdown=category_breakdown,
            timestamp=time.time(),
        )

    def _compare_by_category(
        self,
        result_a: StressTestResult,
        result_b: StressTestResult,
        conversations: list[SyntheticConversation],
    ) -> dict[str, dict[str, float]]:
        """Compare results by difficulty category."""
        # Count conversations by category
        category_counts: dict[str, int] = {}
        for conv in conversations:
            category_counts[conv.difficulty] = category_counts.get(conv.difficulty, 0) + 1

        # Calculate pass rates by category
        breakdown: dict[str, dict[str, float]] = {}

        for category in ["normal", "edge_case", "adversarial"]:
            total = category_counts.get(category, 0)
            if total == 0:
                continue

            failed_a = result_a.failures_by_category.get(category, 0)
            failed_b = result_b.failures_by_category.get(category, 0)

            pass_rate_a = (total - failed_a) / total
            pass_rate_b = (total - failed_b) / total

            breakdown[category] = {
                "config_a_pass_rate": pass_rate_a,
                "config_b_pass_rate": pass_rate_b,
                "delta": pass_rate_b - pass_rate_a,
            }

        return breakdown
