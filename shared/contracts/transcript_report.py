"""Shared transcript report contract."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass(slots=True)
class TranscriptReport:
    """Describe a transcript intelligence report and its derived insights."""

    report_id: str
    archive_name: str
    created_at: float
    conversation_count: int
    languages: list[str] = field(default_factory=list)
    missing_intents: list[dict[str, Any]] = field(default_factory=list)
    procedure_summaries: list[dict[str, Any]] = field(default_factory=list)
    faq_entries: list[dict[str, Any]] = field(default_factory=list)
    workflow_suggestions: list[dict[str, Any]] = field(default_factory=list)
    suggested_tests: list[dict[str, Any]] = field(default_factory=list)
    insights: list[dict[str, Any]] = field(default_factory=list)
    knowledge_asset: dict[str, Any] = field(default_factory=dict)
    conversations: list[dict[str, Any]] = field(default_factory=list)
    intent_accuracy: float | None = None
    intent_accuracy_samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for API and CLI persistence."""
        payload = asdict(self)
        if not payload["conversation_count"]:
            payload["conversation_count"] = len(self.conversations)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranscriptReport:
        """Rehydrate a transcript report from persisted data."""
        conversations = list(data.get("conversations", []))
        return cls(
            report_id=data["report_id"],
            archive_name=data["archive_name"],
            created_at=float(data["created_at"]),
            conversation_count=int(data.get("conversation_count", len(conversations))),
            languages=list(data.get("languages", [])),
            missing_intents=list(data.get("missing_intents", [])),
            procedure_summaries=list(data.get("procedure_summaries", [])),
            faq_entries=list(data.get("faq_entries", [])),
            workflow_suggestions=list(data.get("workflow_suggestions", [])),
            suggested_tests=list(data.get("suggested_tests", [])),
            insights=list(data.get("insights", [])),
            knowledge_asset=dict(data.get("knowledge_asset", {})),
            conversations=conversations,
            intent_accuracy=data.get("intent_accuracy"),
            intent_accuracy_samples=int(data.get("intent_accuracy_samples", 0)),
        )
