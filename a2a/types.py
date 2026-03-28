"""A2A Protocol type definitions for AutoAgent VNextCC.

Follows the Agent-to-Agent (A2A) protocol specification for interoperable
agent discovery and task execution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class TaskStatus(str, Enum):
    """Lifecycle states for an A2A task."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass
class AgentSkill:
    """A single capability advertised by an agent."""

    id: str
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "examples": self.examples,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentSkill":
        return cls(
            id=d["id"],
            name=d["name"],
            description=d["description"],
            tags=d.get("tags", []),
            examples=d.get("examples", []),
        )


@dataclass
class AgentCapabilities:
    """Feature flags indicating what protocol features an agent supports."""

    streaming: bool = True
    push_notifications: bool = False
    state_transition_history: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "streaming": self.streaming,
            "pushNotifications": self.push_notifications,
            "stateTransitionHistory": self.state_transition_history,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentCapabilities":
        return cls(
            streaming=d.get("streaming", True),
            push_notifications=d.get("pushNotifications", d.get("push_notifications", False)),
            state_transition_history=d.get(
                "stateTransitionHistory", d.get("state_transition_history", True)
            ),
        )


@dataclass
class AgentCard:
    """Public identity and capability descriptor for an A2A-compatible agent."""

    name: str
    description: str
    url: str
    version: str = "1.0"
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = field(default_factory=list)
    default_input_modes: list[str] = field(default_factory=lambda: ["text"])
    default_output_modes: list[str] = field(default_factory=lambda: ["text"])
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "capabilities": self.capabilities.to_dict(),
            "skills": [s.to_dict() for s in self.skills],
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentCard":
        caps_raw = d.get("capabilities", {})
        caps = AgentCapabilities.from_dict(caps_raw) if caps_raw else AgentCapabilities()
        skills_raw = d.get("skills", [])
        return cls(
            name=d["name"],
            description=d["description"],
            url=d["url"],
            version=d.get("version", "1.0"),
            capabilities=caps,
            skills=[AgentSkill.from_dict(s) for s in skills_raw],
            default_input_modes=d.get("defaultInputModes", d.get("default_input_modes", ["text"])),
            default_output_modes=d.get(
                "defaultOutputModes", d.get("default_output_modes", ["text"])
            ),
            metadata=d.get("metadata", {}),
        )


@dataclass
class A2AMessage:
    """A message exchanged between agents or between user and agent."""

    role: str  # "user" | "agent"
    parts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "parts": self.parts,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "A2AMessage":
        return cls(
            role=d["role"],
            parts=d.get("parts", []),
            metadata=d.get("metadata", {}),
        )

    @classmethod
    def text(cls, role: str, content: str) -> "A2AMessage":
        """Convenience constructor for a plain-text message."""
        return cls(role=role, parts=[{"type": "text", "text": content}])


@dataclass
class A2ATask:
    """Full lifecycle record for a task submitted via the A2A protocol."""

    task_id: str
    status: str  # TaskStatus value
    input_message: str
    output_message: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.task_id,
            "status": self.status,
            "inputMessage": self.input_message,
            "outputMessage": self.output_message,
            "artifacts": self.artifacts,
            "history": self.history,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "A2ATask":
        return cls(
            task_id=d.get("id", d.get("task_id", uuid.uuid4().hex)),
            status=d.get("status", TaskStatus.SUBMITTED.value),
            input_message=d.get("inputMessage", d.get("input_message", "")),
            output_message=d.get("outputMessage", d.get("output_message", "")),
            artifacts=d.get("artifacts", []),
            history=d.get("history", []),
            created_at=d.get("createdAt", d.get("created_at", "")),
            updated_at=d.get("updatedAt", d.get("updated_at", "")),
            metadata=d.get("metadata", {}),
        )
