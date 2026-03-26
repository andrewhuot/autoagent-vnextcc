"""Conversation state management for assistant interactions.

Tracks conversation history, context, and references to maintain continuity
across turns and enable context-aware responses.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversationTurn:
    """A single turn in a conversation (user message + assistant response)."""

    turn_id: str
    timestamp: float
    user_message: str
    intent: str | None = None
    assistant_response: str = ""
    cards_shown: list[str] = field(default_factory=list)  # card types rendered
    actions_taken: list[str] = field(default_factory=list)  # actions executed
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize turn to dict."""
        return {
            "turn_id": self.turn_id,
            "timestamp": self.timestamp,
            "user_message": self.user_message,
            "intent": self.intent,
            "assistant_response": self.assistant_response,
            "cards_shown": self.cards_shown,
            "actions_taken": self.actions_taken,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationTurn:
        """Deserialize turn from dict."""
        return cls(
            turn_id=data.get("turn_id", ""),
            timestamp=data.get("timestamp", 0.0),
            user_message=data.get("user_message", ""),
            intent=data.get("intent"),
            assistant_response=data.get("assistant_response", ""),
            cards_shown=data.get("cards_shown", []),
            actions_taken=data.get("actions_taken", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ConversationContext:
    """Current conversation context for maintaining continuity."""

    current_agent_id: str | None = None
    current_config: dict[str, Any] | None = None
    last_diagnosis: dict[str, Any] | None = None
    last_diff: dict[str, Any] | None = None
    last_card_id: str | None = None
    last_experiment_id: str | None = None
    last_cluster: dict[str, Any] | None = None
    pending_action: str | None = None
    building_agent: bool = False
    uploaded_files: list[str] = field(default_factory=list)
    extracted_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize context to dict."""
        return {
            "current_agent_id": self.current_agent_id,
            "current_config": self.current_config,
            "last_diagnosis": self.last_diagnosis,
            "last_diff": self.last_diff,
            "last_card_id": self.last_card_id,
            "last_experiment_id": self.last_experiment_id,
            "last_cluster": self.last_cluster,
            "pending_action": self.pending_action,
            "building_agent": self.building_agent,
            "uploaded_files": self.uploaded_files,
            "extracted_data": self.extracted_data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationContext:
        """Deserialize context from dict."""
        return cls(
            current_agent_id=data.get("current_agent_id"),
            current_config=data.get("current_config"),
            last_diagnosis=data.get("last_diagnosis"),
            last_diff=data.get("last_diff"),
            last_card_id=data.get("last_card_id"),
            last_experiment_id=data.get("last_experiment_id"),
            last_cluster=data.get("last_cluster"),
            pending_action=data.get("pending_action"),
            building_agent=data.get("building_agent", False),
            uploaded_files=data.get("uploaded_files", []),
            extracted_data=data.get("extracted_data", {}),
        )


class ConversationState:
    """Manages conversation history and context across turns.

    Provides methods to track conversation flow, maintain references
    to recent actions/cards, and support contextual queries like
    "fix that", "show the diff again", etc.
    """

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id or str(uuid.uuid4())[:12]
        self.turns: list[ConversationTurn] = []
        self.context = ConversationContext()
        self.started_at = time.time()

    def add_turn(
        self,
        user_message: str,
        intent: str | None = None,
        assistant_response: str = "",
        cards_shown: list[str] | None = None,
        actions_taken: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationTurn:
        """Add a new conversation turn and return it.

        Args:
            user_message: The user's input message
            intent: Classified intent (optional)
            assistant_response: Assistant's response text
            cards_shown: List of card types shown (e.g., ["diagnosis", "diff"])
            actions_taken: List of actions executed (e.g., ["run_diagnosis", "apply_fix"])
            metadata: Additional turn metadata

        Returns:
            The created ConversationTurn
        """
        turn = ConversationTurn(
            turn_id=str(uuid.uuid4())[:8],
            timestamp=time.time(),
            user_message=user_message,
            intent=intent,
            assistant_response=assistant_response,
            cards_shown=cards_shown or [],
            actions_taken=actions_taken or [],
            metadata=metadata or {},
        )
        self.turns.append(turn)
        return turn

    def get_context(self) -> ConversationContext:
        """Get current conversation context."""
        return self.context

    def update_context(self, **kwargs: Any) -> None:
        """Update conversation context with provided fields.

        Args:
            **kwargs: Context fields to update (e.g., last_diagnosis=..., current_agent_id=...)
        """
        for key, value in kwargs.items():
            if hasattr(self.context, key):
                setattr(self.context, key, value)

    def get_last_turn(self) -> ConversationTurn | None:
        """Get the most recent conversation turn."""
        return self.turns[-1] if self.turns else None

    def get_recent_turns(self, limit: int = 5) -> list[ConversationTurn]:
        """Get the N most recent turns for context window.

        Args:
            limit: Maximum number of turns to return

        Returns:
            List of recent turns (oldest first)
        """
        return self.turns[-limit:] if self.turns else []

    def get_conversation_summary(self) -> str:
        """Generate a plain-text summary of recent conversation.

        Used for LLM context when classifying intent.
        """
        if not self.turns:
            return "No conversation history."

        lines = []
        for turn in self.turns[-3:]:
            lines.append(f"User: {turn.user_message}")
            if turn.assistant_response:
                response_preview = turn.assistant_response[:100]
                if len(turn.assistant_response) > 100:
                    response_preview += "..."
                lines.append(f"Assistant: {response_preview}")
            if turn.cards_shown:
                lines.append(f"  [Cards shown: {', '.join(turn.cards_shown)}]")
            if turn.actions_taken:
                lines.append(f"  [Actions: {', '.join(turn.actions_taken)}]")
        return "\n".join(lines)

    def clear(self) -> None:
        """Clear conversation history and context."""
        self.turns.clear()
        self.context = ConversationContext()
        self.started_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Serialize conversation state to dict."""
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "turns": [turn.to_dict() for turn in self.turns],
            "context": self.context.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationState:
        """Deserialize conversation state from dict."""
        state = cls(session_id=data.get("session_id"))
        state.started_at = data.get("started_at", time.time())
        state.turns = [
            ConversationTurn.from_dict(turn_data)
            for turn_data in data.get("turns", [])
        ]
        context_data = data.get("context", {})
        state.context = ConversationContext.from_dict(context_data)
        return state

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> ConversationState:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def resolve_reference(self, reference: str) -> dict[str, Any] | None:
        """Resolve contextual references like 'that', 'it', 'the diff'.

        Args:
            reference: Natural language reference to resolve

        Returns:
            Referenced object data or None if not found

        Examples:
            "fix that" -> last_diagnosis
            "show the diff again" -> last_diff
            "deploy it" -> last_card_id or last_experiment_id
        """
        ref_lower = reference.lower().strip()

        # Diagnosis references
        if any(word in ref_lower for word in ["that", "it", "issue", "problem"]):
            if self.context.last_diagnosis:
                return self.context.last_diagnosis

        # Diff references
        if "diff" in ref_lower:
            if self.context.last_diff:
                return self.context.last_diff

        # Cluster/exploration references
        if any(word in ref_lower for word in ["cluster", "group", "pattern"]):
            if self.context.last_cluster:
                return self.context.last_cluster

        # Card/experiment references
        if any(word in ref_lower for word in ["card", "change", "experiment"]):
            return {
                "card_id": self.context.last_card_id,
                "experiment_id": self.context.last_experiment_id,
            }

        return None

    def get_turn_count(self) -> int:
        """Get total number of conversation turns."""
        return len(self.turns)

    def has_recent_action(self, action_type: str, within_turns: int = 3) -> bool:
        """Check if a specific action was taken in recent turns.

        Args:
            action_type: Action type to check for
            within_turns: How many recent turns to check

        Returns:
            True if action was taken recently
        """
        recent = self.get_recent_turns(within_turns)
        return any(action_type in turn.actions_taken for turn in recent)
