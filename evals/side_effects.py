"""Side-effect classification for tool calls.

Classifies tools by their side-effect profile so the eval runner can
determine which tool calls are safe to auto-replay during evaluation
and which require human approval or sandboxing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SideEffectClass(Enum):
    """Classification of a tool's side-effect behavior."""

    pure = "pure"
    read_only_external = "read_only_external"
    write_external_reversible = "write_external_reversible"
    write_external_irreversible = "write_external_irreversible"


@dataclass
class ToolClassification:
    """Classification record for a single tool.

    Attributes:
        tool_name: Unique identifier for the tool.
        side_effect: The tool's side-effect classification.
        description: Human-readable description of what the tool does.
        can_auto_replay: Whether the tool can be replayed automatically
            during eval runs. Computed from side_effect — True for pure
            and read_only_external tools.
    """

    tool_name: str
    side_effect: SideEffectClass
    description: str

    @property
    def can_auto_replay(self) -> bool:
        """Whether this tool is safe to auto-replay during evaluation."""
        return self.side_effect in (
            SideEffectClass.pure,
            SideEffectClass.read_only_external,
        )


class ToolClassificationRegistry:
    """Registry of tool side-effect classifications."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolClassification] = {}

    def register(
        self, tool_name: str, side_effect: SideEffectClass, description: str
    ) -> None:
        """Register a tool's side-effect classification."""
        self._tools[tool_name] = ToolClassification(
            tool_name=tool_name,
            side_effect=side_effect,
            description=description,
        )

    def get(self, tool_name: str) -> ToolClassification | None:
        """Get a tool's classification, or None if not registered."""
        return self._tools.get(tool_name)

    def can_replay(self, tool_name: str) -> bool:
        """Check if a tool can be safely replayed.

        Returns True for pure or read_only_external tools.
        Defaults to False for unknown (unregistered) tools.
        """
        classification = self._tools.get(tool_name)
        if classification is None:
            return False
        return classification.can_auto_replay

    def list_all(self) -> list[ToolClassification]:
        """Return all registered tool classifications."""
        return list(self._tools.values())

    def list_replayable(self) -> list[ToolClassification]:
        """Return only tools that can be auto-replayed."""
        return [tc for tc in self._tools.values() if tc.can_auto_replay]


def create_default_tool_registry() -> ToolClassificationRegistry:
    """Create a ToolClassificationRegistry with the demo agent's tools."""
    registry = ToolClassificationRegistry()

    registry.register(
        tool_name="catalog",
        side_effect=SideEffectClass.read_only_external,
        description="Reads product catalog data. No side effects beyond network I/O.",
    )

    registry.register(
        tool_name="orders_db",
        side_effect=SideEffectClass.write_external_reversible,
        description="Reads and modifies order records. Changes can be reversed.",
    )

    registry.register(
        tool_name="faq",
        side_effect=SideEffectClass.pure,
        description="Deterministic FAQ lookup. No external dependencies.",
    )

    return registry
