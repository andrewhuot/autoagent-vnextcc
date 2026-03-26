"""Generate agent configurations from extracted intents and patterns.

This module takes the output of intent extraction and builds a complete
agent configuration including:
- Agent tree structure (orchestrator + specialists)
- Routing rules based on discovered patterns
- Specialist agent instructions
- Few-shot examples from successful conversations
- Tool configurations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.config.schema import (
    AgentConfig,
    PromptsConfig,
    RoutingConfig,
    RoutingRule,
    ToolConfig,
    ToolsConfig,
)
from assistant.intent_extractor import FailureMode, Intent, RoutingPattern


@dataclass
class SpecialistAgent:
    """Configuration for a specialist agent."""

    name: str
    description: str
    instructions: str
    handles_intents: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    few_shot_examples: list[dict[str, str]] = field(default_factory=list)


@dataclass
class GeneratedAgentConfig:
    """Complete generated agent configuration with metadata."""

    config: AgentConfig
    specialists: list[SpecialistAgent]
    routing_logic: str
    coverage_pct: float
    estimated_intents: int
    failure_modes_addressed: list[str] = field(default_factory=list)

    def to_preview(self) -> dict[str, Any]:
        """Convert to preview card format."""
        return {
            "specialists": [
                {
                    "name": s.name,
                    "description": s.description,
                    "handles_intents": s.handles_intents,
                    "required_tools": s.required_tools,
                    "example_count": len(s.few_shot_examples),
                }
                for s in self.specialists
            ],
            "routing_logic": self.routing_logic,
            "coverage_pct": self.coverage_pct,
            "estimated_intents": self.estimated_intents,
            "failure_modes_addressed": self.failure_modes_addressed,
            "config_summary": {
                "model": self.config.model,
                "routing_rules": len(self.config.routing.rules),
                "quality_boost": self.config.quality_boost,
            },
        }


class AgentGenerator:
    """Generate agent configurations from intent extraction results."""

    def __init__(self):
        """Initialize agent generator."""
        pass

    def generate_config(
        self,
        intents: list[Intent],
        routing_patterns: list[RoutingPattern],
        failure_modes: list[FailureMode],
        required_tools: list[str],
        knowledge_base: dict[str, Any] | None = None,
        few_shot_examples: list[dict[str, Any]] | None = None,
    ) -> GeneratedAgentConfig:
        """Generate complete agent configuration.

        Args:
            intents: Discovered user intents
            routing_patterns: Discovered routing patterns
            failure_modes: Discovered failure modes
            required_tools: Required tool integrations
            knowledge_base: Optional knowledge extracted from successful conversations
            few_shot_examples: Optional few-shot examples from transcripts

        Returns:
            Complete agent configuration with metadata
        """
        # Build specialist structure from routing patterns
        specialists = self._build_specialists(
            intents, routing_patterns, required_tools, few_shot_examples or []
        )

        # Generate routing configuration
        routing_config = self._build_routing_config(routing_patterns)

        # Generate prompts for each specialist
        prompts_config = self._build_prompts_config(specialists, knowledge_base or {})

        # Configure tools
        tools_config = self._build_tools_config(required_tools)

        # Build main config
        config = AgentConfig(
            routing=routing_config,
            prompts=prompts_config,
            tools=tools_config,
            model="gemini-2.0-flash",
            quality_boost=False,
        )

        # Calculate coverage
        coverage_pct = self._calculate_coverage(intents, routing_patterns)

        # Build routing logic summary
        routing_logic = self._build_routing_logic_summary(routing_patterns, specialists)

        # Identify addressed failure modes
        addressed_failures = self._identify_addressed_failures(failure_modes, specialists)

        return GeneratedAgentConfig(
            config=config,
            specialists=specialists,
            routing_logic=routing_logic,
            coverage_pct=coverage_pct,
            estimated_intents=len(intents),
            failure_modes_addressed=addressed_failures,
        )

    def _build_specialists(
        self,
        intents: list[Intent],
        routing_patterns: list[RoutingPattern],
        required_tools: list[str],
        few_shot_examples: list[dict[str, Any]],
    ) -> list[SpecialistAgent]:
        """Build specialist agent structure from routing patterns."""
        # Group intents by specialist
        specialist_intents: dict[str, list[str]] = {}
        for pattern in routing_patterns:
            if pattern.specialist_name not in specialist_intents:
                specialist_intents[pattern.specialist_name] = []
            specialist_intents[pattern.specialist_name].append(pattern.intent_name)

        specialists = []
        for specialist_name, intent_names in specialist_intents.items():
            # Find intents for this specialist
            specialist_intent_objs = [i for i in intents if i.name in intent_names]

            # Determine required tools
            tools_for_specialist = []
            for intent in specialist_intent_objs:
                tools_for_specialist.extend(intent.requires_tools)
            tools_for_specialist = list(set(tools_for_specialist))

            # Generate description and instructions
            description = self._generate_specialist_description(
                specialist_name, intent_names
            )
            instructions = self._generate_specialist_instructions(
                specialist_name, specialist_intent_objs, tools_for_specialist
            )

            # Extract relevant few-shot examples
            examples = self._extract_few_shot_examples(
                specialist_name, intent_names, few_shot_examples
            )

            specialists.append(
                SpecialistAgent(
                    name=specialist_name,
                    description=description,
                    instructions=instructions,
                    handles_intents=intent_names,
                    required_tools=tools_for_specialist,
                    few_shot_examples=examples,
                )
            )

        return specialists

    def _generate_specialist_description(
        self, specialist_name: str, intent_names: list[str]
    ) -> str:
        """Generate human-readable description for a specialist."""
        descriptions = {
            "orders": "Handles order management, shipping inquiries, and returns",
            "billing": "Processes billing questions, payment issues, and refunds",
            "support": "Provides technical support and general assistance",
            "recommendations": "Offers product recommendations and suggestions",
        }

        if specialist_name in descriptions:
            return descriptions[specialist_name]

        # Generate from intent names
        intent_summary = ", ".join(
            intent.replace("_", " ") for intent in intent_names[:3]
        )
        return f"Specialist for {intent_summary}"

    def _generate_specialist_instructions(
        self,
        specialist_name: str,
        intents: list[Intent],
        tools: list[str],
    ) -> str:
        """Generate instructions for a specialist agent."""
        base_instructions = {
            "orders": """You are an order management specialist. Help customers with:
- Order status and tracking
- Shipping and delivery questions
- Returns and exchanges
- Order modifications

Be proactive in looking up order information and provide specific details.""",
            "billing": """You are a billing specialist. Help customers with:
- Payment questions and issues
- Refund requests and processing
- Invoice inquiries
- Charge disputes

Always verify account information before discussing billing details.""",
            "support": """You are a customer support specialist. Help customers with:
- Technical issues and troubleshooting
- Product questions
- General inquiries
- Account management

Be patient and thorough in understanding and resolving issues.""",
            "recommendations": """You are a product recommendation specialist. Help customers:
- Find products that match their needs
- Compare product options
- Understand product features
- Make informed purchase decisions

Ask clarifying questions to understand customer needs before recommending.""",
        }

        if specialist_name in base_instructions:
            instructions = base_instructions[specialist_name]
        else:
            # Generate generic instructions
            intent_list = "\n".join(f"- {i.description}" for i in intents[:5])
            instructions = f"""You are a specialist agent handling:
{intent_list}

Provide clear, helpful responses and use available tools when needed."""

        # Add tool usage notes if tools are available
        if tools:
            tool_names = ", ".join(tools)
            instructions += f"\n\nYou have access to these tools: {tool_names}. Use them to provide accurate, data-driven responses."

        return instructions

    def _extract_few_shot_examples(
        self,
        specialist_name: str,
        intent_names: list[str],
        all_examples: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Extract relevant few-shot examples for a specialist."""
        relevant_examples = []

        for example in all_examples:
            if example.get("intent") in intent_names:
                relevant_examples.append(
                    {
                        "user": example.get("user_message", ""),
                        "assistant": example.get("agent_response", ""),
                    }
                )

        # Return top 3-5 examples
        return relevant_examples[:5]

    def _build_routing_config(
        self, routing_patterns: list[RoutingPattern]
    ) -> RoutingConfig:
        """Build routing configuration from patterns."""
        rules = []

        # Group patterns by specialist
        specialist_patterns: dict[str, list[RoutingPattern]] = {}
        for pattern in routing_patterns:
            if pattern.specialist_name not in specialist_patterns:
                specialist_patterns[pattern.specialist_name] = []
            specialist_patterns[pattern.specialist_name].append(pattern)

        # Create routing rules
        for specialist_name, patterns in specialist_patterns.items():
            # Combine all keywords for this specialist
            all_keywords = []
            for pattern in patterns:
                all_keywords.extend(pattern.supporting_keywords)

            # Remove duplicates while preserving order
            keywords = []
            seen = set()
            for kw in all_keywords:
                if kw not in seen:
                    keywords.append(kw)
                    seen.add(kw)

            rules.append(
                RoutingRule(
                    specialist=specialist_name,
                    keywords=keywords,
                    patterns=[],
                )
            )

        return RoutingConfig(rules=rules)

    def _build_prompts_config(
        self, specialists: list[SpecialistAgent], knowledge_base: dict[str, Any]
    ) -> PromptsConfig:
        """Build prompts configuration for all agents."""
        # Build root orchestrator prompt
        specialist_list = ", ".join(s.name for s in specialists)
        root_prompt = f"""You are a helpful customer service orchestrator agent. You coordinate with specialist agents to help customers.

Available specialists: {specialist_list}

Route customer requests to the appropriate specialist based on their needs. If unsure, ask clarifying questions before routing."""

        # Build specialist prompts - only use fields that exist in PromptsConfig
        prompts_dict = {"root": root_prompt}

        # Map specialists to known PromptsConfig fields
        known_fields = {"root", "support", "orders", "recommendations"}

        for specialist in specialists:
            if specialist.name in known_fields:
                prompts_dict[specialist.name] = specialist.instructions

        # Set defaults for any missing known fields
        if "support" not in prompts_dict:
            prompts_dict["support"] = "You are a customer support specialist."
        if "orders" not in prompts_dict:
            prompts_dict["orders"] = "You are an order management specialist."
        if "recommendations" not in prompts_dict:
            prompts_dict["recommendations"] = "You are a product recommendation specialist."

        # Create PromptsConfig with known fields only
        return PromptsConfig(**prompts_dict)

    def _build_tools_config(self, required_tools: list[str]) -> ToolsConfig:
        """Build tools configuration."""
        tools_dict = {}

        for tool_name in required_tools:
            # Map discovered tools to config field names
            config_name = self._map_tool_name(tool_name)
            tools_dict[config_name] = ToolConfig(enabled=True, timeout_ms=5000)

        return ToolsConfig(**tools_dict)

    def _map_tool_name(self, tool_name: str) -> str:
        """Map discovered tool name to config field name."""
        mapping = {
            "orders_db": "orders_db",
            "catalog": "catalog",
            "billing_system": "faq",  # Map to existing field
            "knowledge_base": "faq",
        }
        return mapping.get(tool_name, "faq")

    def _calculate_coverage(
        self, intents: list[Intent], routing_patterns: list[RoutingPattern]
    ) -> float:
        """Calculate percentage of intents covered by routing patterns."""
        if not intents:
            return 100.0

        covered_intents = set(p.intent_name for p in routing_patterns)
        total_intents = len(intents)
        covered_count = len(covered_intents)

        return (covered_count / total_intents) * 100.0

    def _build_routing_logic_summary(
        self, routing_patterns: list[RoutingPattern], specialists: list[SpecialistAgent]
    ) -> str:
        """Build human-readable routing logic summary."""
        lines = ["Routing Logic:"]

        for specialist in specialists:
            specialist_patterns = [
                p for p in routing_patterns if p.specialist_name == specialist.name
            ]

            if specialist_patterns:
                keywords = []
                for p in specialist_patterns:
                    keywords.extend(p.supporting_keywords[:3])
                keywords = list(set(keywords))[:5]

                lines.append(
                    f"- {specialist.name}: Routes on keywords {', '.join(keywords)}"
                )

        return "\n".join(lines)

    def _identify_addressed_failures(
        self, failure_modes: list[FailureMode], specialists: list[SpecialistAgent]
    ) -> list[str]:
        """Identify which failure modes are addressed by the config."""
        addressed = []

        for failure in failure_modes:
            if failure.failure_type == "routing_error" and len(specialists) > 1:
                addressed.append(failure.failure_type)
            elif failure.failure_type == "missing_tool":
                # Check if any specialist has tools
                if any(s.required_tools for s in specialists):
                    addressed.append(failure.failure_type)
            elif failure.failure_type == "unclear_response":
                # Addressed by specialist instructions
                addressed.append(failure.failure_type)

        return addressed
