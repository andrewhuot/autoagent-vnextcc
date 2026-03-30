"""Shared build artifact contract."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(slots=True)
class BuildArtifact:
    """Describe a saved build output for CLI, API, and UI consumers."""

    id: str
    created_at: str
    updated_at: str
    source: str
    status: str
    config_yaml: str
    prompt_used: str | None = None
    transcript_report_id: str | None = None
    builder_session_id: str | None = None
    eval_draft: str | None = None
    starter_config_path: str | None = None
    selector: str = "latest"
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for persistence and transport."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BuildArtifact:
        """Rehydrate a build artifact from persisted JSON-like data."""
        return cls(
            id=data["id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            source=data["source"],
            status=data["status"],
            config_yaml=data["config_yaml"],
            prompt_used=data.get("prompt_used"),
            transcript_report_id=data.get("transcript_report_id"),
            builder_session_id=data.get("builder_session_id"),
            eval_draft=data.get("eval_draft"),
            starter_config_path=data.get("starter_config_path"),
            selector=data.get("selector", "latest"),
            metadata=data.get("metadata"),
        )
