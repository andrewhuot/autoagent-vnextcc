"""Knowledge mining from successful conversations."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logger.store import ConversationRecord, ConversationStore


@dataclass
class KnowledgePattern:
    """An extracted pattern from successful conversations."""

    pattern_id: str
    pattern_type: str  # tool_usage, phrasing, resolution_strategy
    description: str
    evidence_conversations: list[str]  # conversation IDs
    confidence: float
    applicable_intents: list[str]
    suggested_application: str  # few_shot, policy, instruction, tool_ordering


class KnowledgeMiner:
    """Mines patterns from successful conversations."""

    def __init__(self, conversation_store: ConversationStore):
        self.conversation_store = conversation_store

    def mine_successes(self, min_score: float = 0.9, limit: int = 100) -> list[ConversationRecord]:
        """Scan traces for high-scoring conversations."""
        all_records = self.conversation_store.get_recent(limit=1000)

        # Filter for successful conversations (high score, no safety violations)
        successful = []
        for record in all_records:
            if record.success and record.safety_violations == 0:
                # Estimate quality score from latency and cost
                quality_score = 0.8  # Base score for successful conversations
                if record.latency_ms and record.latency_ms < 1000:
                    quality_score += 0.1  # Fast responses
                if record.cost and record.cost < 0.01:
                    quality_score += 0.1  # Low cost

                if quality_score >= min_score:
                    successful.append(record)

                if len(successful) >= limit:
                    break

        return successful

    def extract_patterns(self, conversations: list[ConversationRecord]) -> list[KnowledgePattern]:
        """Identify resolution strategies, tool usage patterns, effective phrasings."""
        patterns: list[KnowledgePattern] = []

        # Group conversations by outcome patterns
        tool_sequences: dict[str, list[str]] = {}
        response_patterns: dict[str, list[str]] = {}

        for conv in conversations:
            conv_id = conv.conversation_id

            # Extract tool usage patterns
            if conv.tool_calls:
                tool_sequence = tuple(conv.tool_calls)
                key = str(tool_sequence)
                if key not in tool_sequences:
                    tool_sequences[key] = []
                tool_sequences[key].append(conv_id)

            # Extract response patterns (simplified)
            if conv.response:
                # Simple pattern: response length category
                length_category = "short" if len(conv.response) < 200 else "medium" if len(conv.response) < 500 else "long"
                if length_category not in response_patterns:
                    response_patterns[length_category] = []
                response_patterns[length_category].append(conv_id)

        # Convert to KnowledgePattern objects
        pattern_id_counter = int(time.time() * 1000)

        # Tool usage patterns
        for tool_seq, conv_ids in tool_sequences.items():
            if len(conv_ids) >= 3:  # Pattern must appear in at least 3 conversations
                pattern_id_counter += 1
                patterns.append(
                    KnowledgePattern(
                        pattern_id=f"tool_pattern_{pattern_id_counter}",
                        pattern_type="tool_usage",
                        description=f"Successful tool sequence: {tool_seq}",
                        evidence_conversations=conv_ids,
                        confidence=min(1.0, len(conv_ids) / 10.0),
                        applicable_intents=["general"],
                        suggested_application="tool_ordering",
                    )
                )

        # Response patterns
        for length_cat, conv_ids in response_patterns.items():
            if len(conv_ids) >= 5:  # Response pattern threshold
                pattern_id_counter += 1
                patterns.append(
                    KnowledgePattern(
                        pattern_id=f"response_pattern_{pattern_id_counter}",
                        pattern_type="phrasing",
                        description=f"Effective {length_cat} responses",
                        evidence_conversations=conv_ids,
                        confidence=min(1.0, len(conv_ids) / 20.0),
                        applicable_intents=["general"],
                        suggested_application="few_shot",
                    )
                )

        return patterns

    def generate_knowledge_entries(
        self, patterns: list[KnowledgePattern]
    ) -> list[dict[str, Any]]:
        """Create structured knowledge entries."""
        entries = []
        for pattern in patterns:
            entry = {
                "pattern_id": pattern.pattern_id,
                "pattern_type": pattern.pattern_type,
                "description": pattern.description,
                "evidence_conversations": pattern.evidence_conversations,
                "confidence": pattern.confidence,
                "applicable_intents": pattern.applicable_intents,
                "suggested_application": pattern.suggested_application,
                "status": "draft",
                "created_at": time.time(),
            }
            entries.append(entry)
        return entries
