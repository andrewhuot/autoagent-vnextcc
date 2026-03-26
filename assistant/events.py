"""Event types for streaming assistant responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ThinkingEvent:
    """Progress event showing current thinking step."""

    step: str
    progress: float = 0.0
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "thinking",
            "step": self.step,
            "progress": self.progress,
            "details": self.details or {},
        }


@dataclass
class CardEvent:
    """Rich card data event."""

    card_type: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "card",
            "card_type": self.card_type,
            "data": self.data,
        }


@dataclass
class TextEvent:
    """Plain text message event."""

    content: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "text",
            "content": self.content,
        }


@dataclass
class SuggestionsEvent:
    """Suggested user actions event."""

    actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "suggestions",
            "actions": self.actions,
        }


@dataclass
class ErrorEvent:
    """Error notification event."""

    error: str
    recoverable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "error",
            "error": self.error,
            "recoverable": self.recoverable,
        }


Event = ThinkingEvent | CardEvent | TextEvent | SuggestionsEvent | ErrorEvent
