#!/usr/bin/env python3
"""Demo script showing how to use the Assistant agent builder modules.

This demonstrates the three core modules:
1. IntentExtractor - Extract intents and entities from transcripts
2. AgentGenerator - Generate agent config from extracted data
3. AgentBuilder - Orchestrate the complete building process
"""

from __future__ import annotations

import asyncio

from assistant import AgentBuilder, IntentExtractor


# Sample customer support transcripts
SAMPLE_TRANSCRIPTS = [
    {
        "id": "conv_001",
        "messages": [
            {"role": "user", "content": "Where is my order #12345?"},
            {
                "role": "agent",
                "content": "Let me check that for you. Order #12345 is currently in transit and will arrive tomorrow by 5 PM.",
            },
            {"role": "user", "content": "Great, thank you!"},
        ],
        "success": True,
    },
    {
        "id": "conv_002",
        "messages": [
            {
                "role": "user",
                "content": "I want to return this broken product and get a refund for order ORD-67890",
            },
            {
                "role": "agent",
                "content": "I'm sorry to hear that. Let me help you with the return process.",
            },
            {"role": "user", "content": "How long will the refund take?"},
            {
                "role": "agent",
                "content": "I've initiated a return for order 67890. You'll receive a refund within 5-7 business days once we receive the item.",
            },
        ],
        "success": True,
    },
    {
        "id": "conv_003",
        "messages": [
            {
                "role": "user",
                "content": "Why was I charged twice for my last bill? This is unacceptable.",
            },
            {
                "role": "agent",
                "content": "I apologize for the confusion. Let me look into your billing history.",
            },
            {
                "role": "user",
                "content": "I need this fixed now.",
            },
        ],
        "success": False,
    },
    {
        "id": "conv_004",
        "messages": [
            {
                "role": "user",
                "content": "Can you recommend a good laptop for video editing?",
            },
            {
                "role": "agent",
                "content": "I'd be happy to help! What's your budget and preferred screen size?",
            },
            {"role": "user", "content": "Around $1500, 15 inches would be ideal"},
            {
                "role": "agent",
                "content": "Based on your needs, I recommend the ProBook X15. It has a powerful processor, 32GB RAM, and excellent display for video editing.",
            },
        ],
        "success": True,
    },
    {
        "id": "conv_005",
        "messages": [
            {
                "role": "user",
                "content": "My laptop won't turn on after the latest update. Error code E-500.",
            },
            {
                "role": "agent",
                "content": "Let me help you troubleshoot. Have you tried holding the power button for 10 seconds to perform a hard reset?",
            },
            {"role": "user", "content": "Yes, but it didn't work."},
            {
                "role": "agent",
                "content": "In that case, let's try booting in safe mode. I'll walk you through the steps.",
            },
        ],
        "success": True,
    },
]


async def demo_intent_extraction():
    """Demonstrate intent extraction from transcripts."""
    print("=" * 60)
    print("DEMO 1: Intent Extraction")
    print("=" * 60)

    # Initialize intent extractor with mock mode for demo
    extractor = IntentExtractor(use_mock=True)

    # Extract intents, routing patterns, and failure modes
    intents, routing_patterns, failure_modes, tools = await extractor.extract_intents(
        SAMPLE_TRANSCRIPTS
    )

    print(f"\nExtracted {len(intents)} intents:")
    for intent in intents:
        print(f"\n  - {intent.name}")
        print(f"    Description: {intent.description}")
        print(f"    Keywords: {', '.join(intent.keywords)}")
        print(f"    Frequency: {intent.frequency} conversations")
        print(f"    Success rate: {intent.success_rate:.1%}")
        print(f"    Avg turns: {intent.avg_turns:.1f}")

    print(f"\n\nDiscovered {len(routing_patterns)} routing patterns:")
    for pattern in routing_patterns:
        print(f"\n  - {pattern.intent_name} → {pattern.specialist_name}")
        print(f"    Confidence: {pattern.confidence:.1%}")
        print(f"    Keywords: {', '.join(pattern.supporting_keywords[:5])}")

    print(f"\n\nIdentified {len(failure_modes)} failure modes:")
    for failure in failure_modes:
        print(f"\n  - {failure.failure_type}")
        print(f"    Description: {failure.description}")
        print(f"    Frequency: {failure.frequency} occurrences")
        print(f"    Severity: {failure.severity:.1%}")
        print(f"    Suggested fix: {failure.suggested_fix}")

    print(f"\n\nRequired tools: {', '.join(tools)}")

    return intents, routing_patterns, failure_modes, tools


async def demo_agent_generation(intents, routing_patterns, failure_modes, tools):
    """Demonstrate agent configuration generation."""
    print("\n\n" + "=" * 60)
    print("DEMO 2: Agent Configuration Generation")
    print("=" * 60)

    from assistant import AgentGenerator

    generator = AgentGenerator()

    # Generate complete agent configuration
    agent_config = generator.generate_config(
        intents=intents,
        routing_patterns=routing_patterns,
        failure_modes=failure_modes,
        required_tools=tools,
    )

    print(f"\nGenerated agent with {len(agent_config.specialists)} specialists:")
    for specialist in agent_config.specialists:
        print(f"\n  {specialist.name.upper()}:")
        print(f"    {specialist.description}")
        print(f"    Handles: {', '.join(specialist.handles_intents)}")
        print(f"    Tools: {', '.join(specialist.required_tools) or 'none'}")

    print(f"\n\nRouting Logic:")
    print(agent_config.routing_logic)

    print(f"\n\nCoverage: {agent_config.coverage_pct:.1f}% of intents")
    print(f"Failure modes addressed: {len(agent_config.failure_modes_addressed)}/{len(failure_modes)}")

    print(f"\n\nAgent Configuration:")
    print(f"  Model: {agent_config.config.model}")
    print(f"  Routing rules: {len(agent_config.config.routing.rules)}")
    print(f"  Quality boost: {agent_config.config.quality_boost}")

    return agent_config


async def demo_full_builder():
    """Demonstrate complete agent building with streaming events."""
    print("\n\n" + "=" * 60)
    print("DEMO 3: Complete Agent Building with Streaming")
    print("=" * 60)

    # Initialize builder
    builder = AgentBuilder(intent_extractor=IntentExtractor(use_mock=True))

    print("\nBuilding agent from transcripts...\n")

    # Build agent with streaming progress
    async for event in builder.build_from_transcripts(SAMPLE_TRANSCRIPTS):
        event_dict = event.to_dict()
        event_type = event_dict["type"]

        if event_type == "thinking":
            step = event_dict["step"]
            progress = event_dict.get("progress", 0.0)
            bar_length = 40
            filled = int(bar_length * progress)
            bar = "█" * filled + "░" * (bar_length - filled)
            print(f"  [{bar}] {progress:.0%} - {step}")

        elif event_type == "card":
            card_type = event_dict["card_type"]
            if card_type == "agent_preview":
                print(f"\n  ✓ Agent Preview Card Generated")

        elif event_type == "text":
            print(f"\n  → {event_dict['content']}")

        elif event_type == "suggestions":
            print(f"\n  Suggested actions:")
            for action in event_dict["actions"]:
                print(f"    - {action}")


async def main():
    """Run all demos."""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 10 + "AutoAgent Assistant Builder Demo" + " " * 14 + "║")
    print("╚" + "═" * 58 + "╝")

    # Demo 1: Intent extraction
    intents, routing_patterns, failure_modes, tools = await demo_intent_extraction()

    # Demo 2: Agent generation
    agent_config = await demo_agent_generation(
        intents, routing_patterns, failure_modes, tools
    )

    # Demo 3: Full builder with streaming
    await demo_full_builder()

    print("\n\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)
    print(
        "\nThe assistant builder modules provide production-ready components for:"
    )
    print("  1. Extracting intents from customer conversations")
    print("  2. Generating agent configurations automatically")
    print("  3. Streaming progress and results to users")
    print(
        "\nNext steps: Integrate with the frontend Assistant page for a"
    )
    print("conversational agent building experience.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
