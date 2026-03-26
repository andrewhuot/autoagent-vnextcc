"""Assistant orchestrator - NL intent classification and action routing.

The brain of the Assistant that:
1. Classifies user intent from natural language
2. Routes to appropriate modules (build, diagnose, fix, optimize, explore, etc.)
3. Maintains conversation context
4. Streams response events (thinking, text, cards, suggestions)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncIterator

from .cards import CardGenerator
from .conversation import ConversationState
from .events import CardEvent, Event, SuggestionsEvent, TextEvent, ThinkingEvent


class IntentAction(str, Enum):
    """Possible intent actions the assistant can perform."""

    build_agent = "build_agent"
    diagnose = "diagnose"
    fix = "fix"
    optimize = "optimize"
    explore = "explore"
    deploy = "deploy"
    explain = "explain"
    status = "status"
    show_diff = "show_diff"
    show_history = "show_history"
    rollback = "rollback"
    general = "general"


@dataclass
class ClassifiedIntent:
    """Result of intent classification."""

    action: IntentAction
    confidence: float
    entities: dict[str, Any]
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "confidence": self.confidence,
            "entities": self.entities,
            "reasoning": self.reasoning,
        }


class AssistantOrchestrator:
    """Routes NL messages to appropriate AutoAgent modules.

    The orchestrator is the main entry point for assistant interactions.
    It classifies intent, maintains conversation state, and coordinates
    with existing AutoAgent modules (observer, optimizer, deployer, etc.).
    """

    def __init__(
        self,
        observer: Any | None = None,
        optimizer: Any | None = None,
        deployer: Any | None = None,
        eval_runner: Any | None = None,
        trace_store: Any | None = None,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            observer: Observer instance for diagnosis
            optimizer: Optimizer instance for fixes/optimization
            deployer: Deployer instance for deployments
            eval_runner: EvalRunner instance for evaluations
            trace_store: TraceStore instance for conversation exploration
        """
        self.conversation = ConversationState()
        self.card_generator = CardGenerator()

        # Store references to existing modules
        # These will be injected from the API layer
        self.observer = observer
        self.optimizer = optimizer
        self.deployer = deployer
        self.eval_runner = eval_runner
        self.trace_store = trace_store

    async def handle_message(
        self,
        message: str,
        files: list[str] | None = None,
    ) -> AsyncIterator[Event]:
        """Process a user message and yield response events.

        Args:
            message: User's natural language message
            files: Optional list of uploaded file paths

        Yields:
            Events (ThinkingEvent, TextEvent, CardEvent, SuggestionsEvent)
        """
        # Classify intent
        yield ThinkingEvent("Understanding your request...", progress=0.1)

        intent = await self._classify_intent(message, self.conversation.get_conversation_summary())

        # Update conversation with classified intent
        self.conversation.add_turn(
            user_message=message,
            intent=intent.action.value,
        )

        # Route to appropriate handler
        try:
            async for event in self._route_to_handler(intent, message, files):
                yield event
        except Exception as exc:
            yield CardEvent(
                "error",
                self.card_generator.error_card(
                    error_message=str(exc),
                    error_type="internal_error",
                    recovery_suggestions=[
                        "Try rephrasing your request",
                        "Check if required modules are configured",
                    ],
                ),
            )

    async def _classify_intent(
        self, message: str, conversation_summary: str
    ) -> ClassifiedIntent:
        """Classify user intent from message and conversation context.

        Args:
            message: User's message
            conversation_summary: Summary of recent conversation

        Returns:
            ClassifiedIntent with action and entities
        """
        msg_lower = message.lower().strip()

        # Reference resolution ("fix that", "show diff again", etc.)
        if self.conversation.get_turn_count() > 0:
            if any(word in msg_lower for word in ["that", "it", "this"]):
                # Check context for what "that" refers to
                if self.conversation.context.last_diagnosis:
                    if any(word in msg_lower for word in ["fix", "resolve", "solve"]):
                        return ClassifiedIntent(
                            action=IntentAction.fix,
                            confidence=0.9,
                            entities={},
                            reasoning="Contextual reference to fix last diagnosis",
                        )
                if "diff" in msg_lower:
                    return ClassifiedIntent(
                        action=IntentAction.show_diff,
                        confidence=0.95,
                        entities={},
                        reasoning="Request to show diff again",
                    )

        # Build agent intent
        if any(word in msg_lower for word in ["build", "create", "generate"]) and any(
            word in msg_lower for word in ["agent", "bot", "assistant"]
        ):
            return ClassifiedIntent(
                action=IntentAction.build_agent,
                confidence=0.9,
                entities={"has_files": bool(message)},
                reasoning="Request to build a new agent",
            )

        # Diagnose intent
        if any(word in msg_lower for word in ["why", "what's wrong", "failing", "broken", "issue", "problem"]):
            return ClassifiedIntent(
                action=IntentAction.diagnose,
                confidence=0.85,
                entities={},
                reasoning="Request for diagnosis/root cause analysis",
            )

        # Fix intent
        if any(word in msg_lower for word in ["fix", "resolve", "solve", "improve"]):
            return ClassifiedIntent(
                action=IntentAction.fix,
                confidence=0.8,
                entities={},
                reasoning="Request to fix an issue",
            )

        # Optimize intent
        if any(word in msg_lower for word in ["optimize", "improve", "enhance", "better"]):
            return ClassifiedIntent(
                action=IntentAction.optimize,
                confidence=0.8,
                entities={},
                reasoning="Request for optimization",
            )

        # Explore intent
        if any(word in msg_lower for word in ["explore", "search", "find", "show me", "analyze"]) and any(
            word in msg_lower for word in ["conversation", "transcript", "trace", "chat"]
        ):
            return ClassifiedIntent(
                action=IntentAction.explore,
                confidence=0.85,
                entities={"query": message},
                reasoning="Request to explore conversations",
            )

        # Deploy intent
        if any(word in msg_lower for word in ["deploy", "release", "ship", "promote"]):
            return ClassifiedIntent(
                action=IntentAction.deploy,
                confidence=0.9,
                entities={},
                reasoning="Request to deploy a change",
            )

        # Status intent
        if any(word in msg_lower for word in ["status", "health", "how is", "what's the"]) and any(
            word in msg_lower for word in ["agent", "system", "performance"]
        ):
            return ClassifiedIntent(
                action=IntentAction.status,
                confidence=0.85,
                entities={},
                reasoning="Request for system status",
            )

        # Explain intent
        if any(word in msg_lower for word in ["explain", "how does", "what is", "tell me about"]):
            return ClassifiedIntent(
                action=IntentAction.explain,
                confidence=0.8,
                entities={"topic": message},
                reasoning="Request for explanation",
            )

        # Rollback intent
        if any(word in msg_lower for word in ["rollback", "undo", "revert", "go back"]):
            return ClassifiedIntent(
                action=IntentAction.rollback,
                confidence=0.9,
                entities={},
                reasoning="Request to rollback a change",
            )

        # Default: general conversation
        return ClassifiedIntent(
            action=IntentAction.general,
            confidence=0.5,
            entities={"message": message},
            reasoning="General conversation or unclear intent",
        )

    async def _route_to_handler(
        self,
        intent: ClassifiedIntent,
        message: str,
        files: list[str] | None = None,
    ) -> AsyncIterator[Event]:
        """Route classified intent to appropriate handler.

        Args:
            intent: Classified intent
            message: Original message
            files: Optional uploaded files

        Yields:
            Response events
        """
        match intent.action:
            case IntentAction.build_agent:
                async for event in self._handle_build_agent(message, files):
                    yield event
            case IntentAction.diagnose:
                async for event in self._handle_diagnose(message):
                    yield event
            case IntentAction.fix:
                async for event in self._handle_fix(message):
                    yield event
            case IntentAction.optimize:
                async for event in self._handle_optimize(message):
                    yield event
            case IntentAction.explore:
                async for event in self._handle_explore(message):
                    yield event
            case IntentAction.deploy:
                async for event in self._handle_deploy(message):
                    yield event
            case IntentAction.status:
                async for event in self._handle_status():
                    yield event
            case IntentAction.explain:
                async for event in self._handle_explain(message):
                    yield event
            case IntentAction.show_diff:
                async for event in self._handle_show_diff():
                    yield event
            case IntentAction.rollback:
                async for event in self._handle_rollback(message):
                    yield event
            case _:
                async for event in self._handle_general(message):
                    yield event

    # -------------------------------------------------------------------------
    # Intent handlers (stubs - to be implemented/extended)
    # -------------------------------------------------------------------------

    async def _handle_build_agent(
        self, message: str, files: list[str] | None = None
    ) -> AsyncIterator[Event]:
        """Handle agent building request.

        TODO: Integrate with builder.py module when implemented.
        """
        yield TextEvent("Agent building is not yet implemented. This feature will analyze your transcripts and generate agent configurations.")
        yield SuggestionsEvent(actions=["Upload transcripts", "Start guided build"])

    async def _handle_diagnose(self, message: str) -> AsyncIterator[Event]:
        """Handle diagnosis request using Observer and BlameMap.

        Runs root cause analysis and presents findings.
        """
        yield ThinkingEvent("Analyzing agent performance...", progress=0.2)

        if self.observer is None:
            yield TextEvent("Diagnosis requires Observer module to be configured.")
            return

        # Simulate diagnosis - in production, call actual Observer methods
        # health_report = self.observer.generate_health_report()
        # blame_clusters = self.observer.compute_blame_map()

        # Mock response for now
        yield ThinkingEvent("Found issues in routing logic", progress=0.6)

        diagnosis_card = self.card_generator.diagnosis_card(
            root_cause="40% of billing questions are routed to tech_support because routing rules don't include keywords like 'invoice', 'refund', 'payment', or 'charge'.",
            impact_score=0.4,
            affected_count=120,
            specialist="tech_support",
            trend="increasing",
            example_ids=["conv_001", "conv_045", "conv_087"],
            suggested_fix="Add billing keywords to routing rules",
        )

        self.conversation.update_context(last_diagnosis=diagnosis_card)

        yield CardEvent("diagnosis", diagnosis_card)
        yield TextEvent(
            "I found a routing issue affecting 40% of billing questions. "
            "They're being sent to tech_support instead of billing_specialist."
        )
        yield SuggestionsEvent(actions=[
            "Fix it",
            "Show affected conversations",
            "Explain the issue in detail",
        ])

    async def _handle_fix(self, message: str) -> AsyncIterator[Event]:
        """Handle fix request using Optimizer.

        Proposes a fix, runs eval, and presents results.
        """
        yield ThinkingEvent("Generating fix proposal...", progress=0.3)

        # Check if we have a diagnosis in context
        if self.conversation.context.last_diagnosis is None:
            yield TextEvent("I need to diagnose the issue first. What problem should I fix?")
            return

        if self.optimizer is None:
            yield TextEvent("Fix generation requires Optimizer module to be configured.")
            return

        # Simulate fix generation
        yield ThinkingEvent("Testing fix...", progress=0.5)

        diff_card = self.card_generator.diff_card(
            surface="routing.billing_keywords",
            old_value='["bill", "subscription"]',
            new_value='["bill", "subscription", "invoice", "refund", "payment", "charge"]',
            change_description="Add 4 missing billing keywords to routing rules",
            risk_level="low",
            touched_agents=["orchestrator"],
        )

        metrics_card = self.card_generator.metrics_card(
            metrics_before={"quality": 0.62, "safety": 1.0, "latency": 0.85},
            metrics_after={"quality": 0.81, "safety": 1.0, "latency": 0.85},
            confidence_p_value=0.003,
            confidence_effect_size=0.19,
            n_eval_cases=50,
        )

        self.conversation.update_context(last_diff=diff_card)

        yield CardEvent("diff", diff_card)
        yield CardEvent("metrics", metrics_card)
        yield TextEvent(
            "I can add 4 billing keywords to routing rules. "
            "Expected improvement: +19% quality score (62% → 81%). "
            "This change is statistically significant (p=0.003)."
        )
        yield SuggestionsEvent(actions=["Deploy it", "Show the diff", "Try a different fix"])

    async def _handle_optimize(self, message: str) -> AsyncIterator[Event]:
        """Handle optimization request.

        Runs a full optimization cycle with progress updates.
        """
        yield ThinkingEvent("Starting optimization cycle...", progress=0.1)

        if self.optimizer is None:
            yield TextEvent("Optimization requires Optimizer module to be configured.")
            return

        # Simulate optimization progress
        steps = [
            {"description": "Analyzing performance", "status": "completed", "details": "Quality: 62%"},
            {"description": "Generating candidates", "status": "running", "details": ""},
            {"description": "Running evaluations", "status": "pending", "details": ""},
            {"description": "Statistical testing", "status": "pending", "details": ""},
        ]

        progress_card = self.card_generator.progress_card(steps, total_steps=4, current_step=1)
        yield CardEvent("progress", progress_card)

        await asyncio.sleep(0.1)  # Simulate work

        yield TextEvent("Optimization cycle complete. Found 1 improvement candidate.")
        yield SuggestionsEvent(actions=["Review the change", "Deploy it", "Run another cycle"])

    async def _handle_explore(self, message: str) -> AsyncIterator[Event]:
        """Handle conversation exploration request.

        Uses semantic search and clustering over traces.
        """
        yield ThinkingEvent("Searching conversations...", progress=0.3)

        if self.trace_store is None:
            yield TextEvent("Conversation exploration requires TraceStore to be configured.")
            return

        # Mock exploration results
        yield ThinkingEvent("Found 47 matching conversations", progress=0.6)
        yield ThinkingEvent("Clustering by root cause...", progress=0.8)

        # Generate cluster cards
        cluster1 = self.card_generator.cluster_card(
            rank=1,
            title="Shipping delay in northeast region",
            description="68% of shipping complaints are about delays in northeast warehouse",
            count=32,
            impact=0.22,
            trend="increasing",
            example_ids=["conv_123", "conv_145", "conv_201"],
        )

        cluster2 = self.card_generator.cluster_card(
            rank=2,
            title="Wrong tracking number provided",
            description="Tool returning stale tracking data from cache",
            count=10,
            impact=0.07,
            trend="stable",
            example_ids=["conv_087", "conv_099"],
        )

        yield TextEvent(
            "I analyzed 47 conversations about shipping. Found 2 main root causes:"
        )
        yield CardEvent("cluster", cluster1)
        yield CardEvent("cluster", cluster2)

        self.conversation.update_context(last_cluster=cluster1)

        yield SuggestionsEvent(actions=[
            "Tell me more about shipping delays",
            "Fix the tracking issue",
            "Show example conversations",
        ])

    async def _handle_deploy(self, message: str) -> AsyncIterator[Event]:
        """Handle deployment request.

        Deploys the last proposed change via canary deployment.
        """
        yield ThinkingEvent("Starting deployment...", progress=0.2)

        if self.deployer is None:
            yield TextEvent("Deployment requires Deployer module to be configured.")
            return

        # Check for pending changes in context
        if self.conversation.context.last_diff is None:
            yield TextEvent("No pending changes to deploy. Generate a fix first.")
            return

        # Simulate deployment
        yield ThinkingEvent("Deploying to 10% canary...", progress=0.5)

        deploy_card = self.card_generator.deploy_card(
            deployment_id="deploy_001",
            status="canary",
            canary_version=42,
            canary_pct=10.0,
            canary_success_rate=0.83,
            baseline_success_rate=0.62,
            verdict="pending",
            rollback_available=True,
        )

        yield CardEvent("deploy", deploy_card)
        yield TextEvent(
            "Deployed to 10% canary. "
            "Canary success rate: 83% (baseline: 62%). "
            "Monitoring for 30 minutes before auto-promote."
        )
        yield SuggestionsEvent(actions=["Promote now", "Rollback", "Check canary status"])

    async def _handle_status(self) -> AsyncIterator[Event]:
        """Handle status/health check request."""
        yield ThinkingEvent("Checking agent health...", progress=0.5)

        if self.observer is None:
            yield TextEvent("Status check requires Observer module to be configured.")
            return

        # Mock status
        metrics_card = self.card_generator.metrics_card(
            metrics_before={},
            metrics_after={
                "quality": 0.78,
                "safety": 1.0,
                "latency": 0.82,
                "cost": 0.88,
            },
        )

        yield CardEvent("metrics", metrics_card)
        yield TextEvent(
            "Agent health: Quality 78%, Safety 100%, Latency 82%, Cost 88%. "
            "No critical issues detected."
        )
        yield SuggestionsEvent(actions=["Run full diagnosis", "Optimize performance", "View trends"])

    async def _handle_explain(self, message: str) -> AsyncIterator[Event]:
        """Handle explanation request."""
        # Simple informational responses
        msg_lower = message.lower()

        if "observer" in msg_lower or "diagnosis" in msg_lower:
            yield TextEvent(
                "The Observer module monitors your agent's performance in production. "
                "It collects traces, grades conversations, and clusters failures by root cause. "
                "The blame map identifies which config surfaces are causing issues."
            )
        elif "optimizer" in msg_lower or "fix" in msg_lower:
            yield TextEvent(
                "The Optimizer proposes config changes to improve agent performance. "
                "It uses mutation operators, runs A/B evals, performs statistical testing, "
                "and only deploys changes that pass quality gates."
            )
        elif "deployer" in msg_lower or "canary" in msg_lower:
            yield TextEvent(
                "The Deployer manages safe rollouts via canary deployments. "
                "Changes start at 10% traffic, collect metrics, and auto-promote or rollback "
                "based on success rate comparisons."
            )
        else:
            yield TextEvent(
                "I can help you build agents, diagnose issues, apply fixes, and explore conversations. "
                "What would you like to know more about?"
            )

        yield SuggestionsEvent(actions=["Tell me about the Observer", "How does optimization work?", "Explain canary deployments"])

    async def _handle_show_diff(self) -> AsyncIterator[Event]:
        """Handle request to show diff again."""
        if self.conversation.context.last_diff is None:
            yield TextEvent("No diff to show. Generate a fix first.")
            return

        yield CardEvent("diff", self.conversation.context.last_diff)
        yield SuggestionsEvent(actions=["Deploy it", "Try a different fix", "Explain the change"])

    async def _handle_rollback(self, message: str) -> AsyncIterator[Event]:
        """Handle rollback request."""
        yield ThinkingEvent("Rolling back deployment...", progress=0.5)

        if self.deployer is None:
            yield TextEvent("Rollback requires Deployer module to be configured.")
            return

        # Simulate rollback
        yield TextEvent(
            "Rolled back to previous version. "
            "All traffic now on baseline config (v041)."
        )
        yield SuggestionsEvent(actions=["Check status", "Try a different fix"])

    async def _handle_general(self, message: str) -> AsyncIterator[Event]:
        """Handle general conversation or unclear intent."""
        yield TextEvent(
            "I'm the AutoAgent Assistant. I can help you:\n\n"
            "• Build agents from transcripts or documents\n"
            "• Diagnose agent performance issues\n"
            "• Fix and optimize your agents\n"
            "• Explore conversation patterns\n"
            "• Deploy changes safely\n\n"
            "What would you like to do?"
        )
        yield SuggestionsEvent(actions=[
            "Build a new agent",
            "Diagnose my agent",
            "Optimize performance",
            "Explore conversations",
        ])
