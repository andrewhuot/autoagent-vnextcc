"""AutoAgent Assistant — conversational AI interface for the platform.

This package provides a natural language interface to all AutoAgent capabilities:
- Build agents from transcripts, documents, or guided conversation
- Iterate on agents (diagnose, fix, optimize)
- Explore conversations with semantic search and clustering

Main modules:
- orchestrator: NL intent classification and action routing
- conversation: Conversation state management across turns
- builder: Agent building from various inputs
- explorer: Conversational exploration over traces
- cards: Rich card data generation
- file_processor: File upload handling (CSV, PDF, audio, etc.)
- intent_extractor: Extract intents/entities from transcripts
- agent_generator: Generate agent config from extracted data
"""

from __future__ import annotations

from assistant.agent_generator import AgentGenerator, GeneratedAgentConfig, SpecialistAgent
from assistant.builder import AgentBuilder
from assistant.cards import CardGenerator
from assistant.conversation import ConversationContext, ConversationState, ConversationTurn
from assistant.events import (
    CardEvent,
    ErrorEvent,
    Event,
    SuggestionsEvent,
    TextEvent,
    ThinkingEvent,
)
from assistant.file_processor import FileProcessor, ProcessedFile
from assistant.intent_extractor import (
    ConversationAnalysis,
    Entity,
    FailureMode,
    Intent,
    IntentExtractor,
    RoutingPattern,
)
from assistant.orchestrator import AssistantOrchestrator, ClassifiedIntent, IntentAction

__all__ = [
    # Core orchestration
    "AssistantOrchestrator",
    "IntentAction",
    "ClassifiedIntent",
    "ConversationState",
    "ConversationContext",
    "ConversationTurn",
    "CardGenerator",
    "FileProcessor",
    "ProcessedFile",
    # Builder modules
    "AgentBuilder",
    "IntentExtractor",
    "AgentGenerator",
    # Data classes
    "Intent",
    "Entity",
    "RoutingPattern",
    "FailureMode",
    "ConversationAnalysis",
    "SpecialistAgent",
    "GeneratedAgentConfig",
    # Event types
    "Event",
    "ThinkingEvent",
    "CardEvent",
    "TextEvent",
    "SuggestionsEvent",
    "ErrorEvent",
]
