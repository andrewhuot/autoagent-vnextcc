"""Agent building orchestrator for the Assistant.

This module orchestrates the complete agent building process:
1. Parse input (transcripts, documents, or guided conversation)
2. Extract intents and entities
3. Discover routing patterns and failure modes
4. Generate agent configuration
5. Present preview with coverage statistics

Supports three building modes:
- build_from_transcripts: Analyze conversation transcripts
- build_guided: Interactive guided building
- build_from_documents: Extract from SOP/knowledge documents
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from assistant.agent_generator import AgentGenerator, GeneratedAgentConfig
from assistant.events import CardEvent, Event, SuggestionsEvent, TextEvent, ThinkingEvent
from assistant.intent_extractor import IntentExtractor


class AgentBuilder:
    """Orchestrates agent building from various input sources."""

    def __init__(
        self,
        intent_extractor: IntentExtractor | None = None,
        agent_generator: AgentGenerator | None = None,
    ):
        """Initialize agent builder.

        Args:
            intent_extractor: Intent extractor instance. If None, creates default.
            agent_generator: Agent generator instance. If None, creates default.
        """
        self.intent_extractor = intent_extractor or IntentExtractor(use_mock=False)
        self.agent_generator = agent_generator or AgentGenerator()

    async def build_from_transcripts(
        self, transcripts: list[dict[str, Any]]
    ) -> AsyncIterator[Event]:
        """Build agent configuration from conversation transcripts.

        Args:
            transcripts: List of conversation transcripts with format:
                {
                    "id": str,
                    "messages": [{"role": "user"|"agent", "content": str}, ...],
                    "success": bool (optional),
                    "metadata": dict (optional)
                }

        Yields:
            Progress events, thinking updates, and final agent preview card
        """
        yield ThinkingEvent(step="Parsing transcripts...", progress=0.1)

        # Parse and validate transcripts
        conversations = self._parse_transcripts(transcripts)

        yield ThinkingEvent(
            step=f"Extracted {len(conversations)} conversations", progress=0.2
        )

        # Extract intents and entities
        yield ThinkingEvent(step="Extracting intents and entities...", progress=0.3)

        (
            intents,
            routing_patterns,
            failure_modes,
            required_tools,
        ) = await self.intent_extractor.extract_intents(conversations)

        yield ThinkingEvent(
            step=f"Found {len(intents)} intents",
            progress=0.5,
            details={
                "intents": [
                    {
                        "name": i.name,
                        "description": i.description,
                        "frequency": i.frequency,
                        "success_rate": i.success_rate,
                    }
                    for i in intents[:10]
                ]
            },
        )

        # Identify routing patterns
        yield ThinkingEvent(step="Identifying routing patterns...", progress=0.6)

        yield ThinkingEvent(
            step=f"Discovered {len(routing_patterns)} routing patterns",
            progress=0.65,
            details={
                "patterns": [
                    {
                        "intent": p.intent_name,
                        "specialist": p.specialist_name,
                        "confidence": p.confidence,
                    }
                    for p in routing_patterns[:10]
                ]
            },
        )

        # Discover failure modes
        if failure_modes:
            yield ThinkingEvent(
                step=f"Identified {len(failure_modes)} failure modes",
                progress=0.7,
                details={
                    "failures": [
                        {
                            "type": f.failure_type,
                            "description": f.description,
                            "frequency": f.frequency,
                            "severity": f.severity,
                        }
                        for f in failure_modes[:5]
                    ]
                },
            )

        # Extract knowledge from successful conversations
        yield ThinkingEvent(step="Learning from successful resolutions...", progress=0.75)

        knowledge = self._extract_knowledge(conversations, intents)

        # Identify required tools
        yield ThinkingEvent(step="Identifying required tools...", progress=0.8)

        if required_tools:
            yield ThinkingEvent(
                step=f"Found {len(required_tools)} required tools: {', '.join(required_tools)}",
                progress=0.85,
            )

        # Generate agent configuration
        yield ThinkingEvent(step="Generating agent configuration...", progress=0.9)

        agent_config = self.agent_generator.generate_config(
            intents=intents,
            routing_patterns=routing_patterns,
            failure_modes=failure_modes,
            required_tools=required_tools,
            knowledge_base=knowledge,
        )

        # Present preview
        yield CardEvent(card_type="agent_preview", data=agent_config.to_preview())

        specialist_count = len(agent_config.specialists)
        intent_count = len(intents)
        tool_count = len(required_tools)

        yield TextEvent(
            content=f"I built a {specialist_count}-specialist agent covering {intent_count} intents with {tool_count} tools. "
            f"Estimated coverage: {agent_config.coverage_pct:.1f}% of your transcripts."
        )

        if failure_modes:
            addressed = len(agent_config.failure_modes_addressed)
            total_failures = len(failure_modes)
            yield TextEvent(
                content=f"This configuration addresses {addressed} of {total_failures} discovered failure modes."
            )

        yield SuggestionsEvent(
            actions=[
                "Looks good, save it",
                "Add more specialists",
                "Show routing logic",
                "Run baseline eval",
            ]
        )

    async def build_guided(
        self, domain: str, goal: str
    ) -> AsyncIterator[Event]:
        """Build agent through guided conversation.

        Args:
            domain: Domain description (e.g., "e-commerce customer support")
            goal: Primary goal (e.g., "help customers with orders and returns")

        Yields:
            Interactive conversation events guiding user through agent creation
        """
        yield ThinkingEvent(step="Analyzing domain and goal...", progress=0.2)

        # Ask targeted questions based on domain
        yield TextEvent(
            content=f"I'll help you build a {domain} agent focused on: {goal}"
        )

        yield TextEvent(
            content="To build the best agent, I need to understand a few things:"
        )

        # Generate domain-specific questions
        questions = self._generate_domain_questions(domain)

        for i, question in enumerate(questions[:3]):
            yield TextEvent(content=f"{i+1}. {question}")

        yield SuggestionsEvent(
            actions=[
                "I handle orders, shipping, and returns",
                "I need billing and technical support",
                "Just build a general support agent",
            ]
        )

    async def build_from_documents(
        self, documents: list[dict[str, Any]]
    ) -> AsyncIterator[Event]:
        """Build agent from SOP documents and knowledge bases.

        Args:
            documents: List of document dicts with format:
                {
                    "content": str,
                    "type": "sop" | "faq" | "policy" | "knowledge",
                    "title": str (optional),
                    "metadata": dict (optional)
                }

        Yields:
            Progress events and agent preview card
        """
        yield ThinkingEvent(step="Parsing documents...", progress=0.1)

        # Parse documents
        parsed_docs = self._parse_documents(documents)

        yield ThinkingEvent(
            step=f"Processed {len(parsed_docs)} documents", progress=0.3
        )

        # Extract procedures and policies
        yield ThinkingEvent(step="Extracting procedures and policies...", progress=0.5)

        procedures = self._extract_procedures(parsed_docs)
        policies = self._extract_policies(parsed_docs)

        yield ThinkingEvent(
            step=f"Found {len(procedures)} procedures and {len(policies)} policies",
            progress=0.7,
        )

        # Generate agent configuration with knowledge grounding
        yield ThinkingEvent(
            step="Generating knowledge-grounded agent...", progress=0.9
        )

        # For now, build a basic config
        # TODO: Implement full document-based generation
        yield TextEvent(
            content="Document-based agent building is under development. "
            "For now, I can help you build from transcripts or through guided conversation."
        )

        yield SuggestionsEvent(
            actions=[
                "Upload transcripts instead",
                "Start guided building",
                "Tell me more about document-based building",
            ]
        )

    def _parse_transcripts(
        self, transcripts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Parse and validate transcript data."""
        conversations = []

        for i, transcript in enumerate(transcripts):
            # Handle different transcript formats
            if "messages" in transcript:
                # Already in correct format
                conversations.append(transcript)
            elif "conversation" in transcript:
                # Nested format
                conversations.append(
                    {
                        "id": transcript.get("id", f"conv_{i}"),
                        "messages": transcript["conversation"],
                        "success": transcript.get("success", True),
                        "metadata": transcript.get("metadata", {}),
                    }
                )
            elif isinstance(transcript, str):
                # Plain text format - parse into messages
                messages = self._parse_plain_text_conversation(transcript)
                conversations.append(
                    {
                        "id": f"conv_{i}",
                        "messages": messages,
                        "success": True,
                        "metadata": {},
                    }
                )
            else:
                # Unknown format - skip with warning
                continue

        return conversations

    def _parse_plain_text_conversation(self, text: str) -> list[dict[str, str]]:
        """Parse plain text conversation into messages."""
        messages = []
        current_role = None
        current_content = []

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Detect role switches
            if line.lower().startswith(("user:", "customer:", "client:")):
                if current_role and current_content:
                    messages.append(
                        {"role": current_role, "content": " ".join(current_content)}
                    )
                current_role = "user"
                current_content = [line.split(":", 1)[1].strip()]
            elif line.lower().startswith(("agent:", "assistant:", "support:")):
                if current_role and current_content:
                    messages.append(
                        {"role": current_role, "content": " ".join(current_content)}
                    )
                current_role = "agent"
                current_content = [line.split(":", 1)[1].strip()]
            else:
                # Continue current message
                if current_role:
                    current_content.append(line)

        # Add final message
        if current_role and current_content:
            messages.append({"role": current_role, "content": " ".join(current_content)})

        return messages

    def _extract_knowledge(
        self, conversations: list[dict[str, Any]], intents: list[Any]
    ) -> dict[str, Any]:
        """Extract knowledge base from successful conversations."""
        knowledge = {
            "successful_patterns": [],
            "common_resolutions": [],
            "best_practices": [],
        }

        # Find successful conversations
        successful = [c for c in conversations if c.get("success", True)]

        if successful:
            # Extract resolution patterns
            for conv in successful[:10]:
                messages = conv.get("messages", [])
                if messages:
                    # Last agent message is often the resolution
                    agent_messages = [m for m in messages if m.get("role") == "agent"]
                    if agent_messages:
                        knowledge["successful_patterns"].append(
                            agent_messages[-1].get("content", "")
                        )

        return knowledge

    def _generate_domain_questions(self, domain: str) -> list[str]:
        """Generate domain-specific questions for guided building."""
        common_questions = [
            "What are the main types of customer requests you handle?",
            "Do you need to integrate with any external systems (order database, billing, etc.)?",
            "Are there specific policies or procedures the agent should follow?",
        ]

        domain_specific = {
            "e-commerce": [
                "Do you handle order tracking, returns, and exchanges?",
                "Should the agent have access to inventory and product catalogs?",
            ],
            "support": [
                "What types of technical issues do you troubleshoot?",
                "Do you need integration with a ticketing system?",
            ],
            "sales": [
                "What products or services do you sell?",
                "Should the agent qualify leads or schedule demos?",
            ],
        }

        # Match domain to specific questions
        for key, questions in domain_specific.items():
            if key in domain.lower():
                return common_questions + questions

        return common_questions

    def _parse_documents(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parse and normalize document data."""
        parsed = []

        for doc in documents:
            parsed.append(
                {
                    "content": doc.get("content", ""),
                    "type": doc.get("type", "knowledge"),
                    "title": doc.get("title", "Untitled"),
                    "metadata": doc.get("metadata", {}),
                }
            )

        return parsed

    def _extract_procedures(self, documents: list[dict[str, Any]]) -> list[str]:
        """Extract procedures from documents."""
        procedures = []

        for doc in documents:
            if doc["type"] in ["sop", "procedure"]:
                # Simple extraction - in production would use more sophisticated parsing
                content = doc["content"]
                # Look for numbered steps, bullet points, etc.
                if any(marker in content for marker in ["1.", "Step 1", "- "]):
                    procedures.append(doc["title"])

        return procedures

    def _extract_policies(self, documents: list[dict[str, Any]]) -> list[str]:
        """Extract policies from documents."""
        policies = []

        for doc in documents:
            if doc["type"] in ["policy", "guideline"]:
                policies.append(doc["title"])

        return policies
