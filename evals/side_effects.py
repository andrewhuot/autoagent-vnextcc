"""Side-effect classification for tool calls.

Classifies tools by their side-effect profile so the eval runner can
determine which tool calls are safe to auto-replay during evaluation
and which require human approval or sandboxing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.types import ReplayMode, ToolContractVersion


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


# ---------------------------------------------------------------------------
# Replay mode migration helper
# ---------------------------------------------------------------------------


def side_effect_to_replay_mode(side_effect: SideEffectClass) -> ReplayMode:
    """Map old 4-class SideEffectClass to the new 5-mode ReplayMode.

    This is the canonical migration path from the flat classification to the
    richer replay contract system.
    """
    _mapping = {
        SideEffectClass.pure: ReplayMode.deterministic_stub,
        SideEffectClass.read_only_external: ReplayMode.recorded_stub_with_freshness,
        SideEffectClass.write_external_reversible: ReplayMode.live_sandbox_clone,
        SideEffectClass.write_external_irreversible: ReplayMode.forbidden,
    }
    return _mapping[side_effect]


# ---------------------------------------------------------------------------
# Tool Contract — bridges old ToolClassification to new ToolContractVersion
# ---------------------------------------------------------------------------


@dataclass
class ToolContract:
    """Rich tool contract that bridges the old ToolClassification to the new
    ToolContractVersion domain object.

    Maintains backward compatibility with SideEffectClass while adding
    replay mode, validator, sandbox policy, and freshness window.
    """

    tool_name: str
    side_effect: SideEffectClass  # backward compat
    replay_mode: ReplayMode
    validator: str | None = None
    sandbox_policy: dict = field(default_factory=dict)
    freshness_window_seconds: int | None = None
    description: str = ""

    @property
    def can_auto_replay(self) -> bool:
        """Whether this tool can be replayed automatically during evaluation."""
        return self.replay_mode in (
            ReplayMode.deterministic_stub,
            ReplayMode.recorded_stub_with_freshness,
            ReplayMode.simulator,
        )

    def to_contract_version(self) -> ToolContractVersion:
        """Convert to the canonical ToolContractVersion domain object."""
        return ToolContractVersion(
            tool_name=self.tool_name,
            side_effect_class=self.side_effect.value,
            replay_mode=self.replay_mode,
            validator=self.validator,
            sandbox_policy=self.sandbox_policy,
            freshness_window_seconds=self.freshness_window_seconds,
            description=self.description,
        )


# ---------------------------------------------------------------------------
# Tool Contract Registry — extends ToolClassificationRegistry
# ---------------------------------------------------------------------------


class ToolContractRegistry(ToolClassificationRegistry):
    """Registry of ToolContract objects, extending ToolClassificationRegistry.

    Stores the richer ToolContract alongside the original ToolClassification
    entries, so all existing ToolClassificationRegistry methods continue to
    work unchanged.
    """

    def __init__(self) -> None:
        super().__init__()
        self._contracts: dict[str, ToolContract] = {}

    def register_contract(self, contract: ToolContract) -> None:
        """Register a ToolContract.

        Also registers the underlying ToolClassification for backward
        compatibility with code that uses the base registry interface.
        """
        self._contracts[contract.tool_name] = contract
        # Keep the base registry in sync so inherited methods work.
        super().register(
            tool_name=contract.tool_name,
            side_effect=contract.side_effect,
            description=contract.description,
        )

    def get_contract(self, tool_name: str) -> ToolContract | None:
        """Get a tool's contract, or None if not registered."""
        return self._contracts.get(tool_name)

    def get_by_replay_mode(self, mode: ReplayMode) -> list[ToolContract]:
        """Return all contracts with the given replay mode."""
        return [c for c in self._contracts.values() if c.replay_mode == mode]

    @classmethod
    def from_classification_registry(
        cls, registry: ToolClassificationRegistry
    ) -> "ToolContractRegistry":
        """Migrate a ToolClassificationRegistry to a ToolContractRegistry.

        Each existing ToolClassification is converted to a ToolContract by
        mapping its SideEffectClass to the corresponding ReplayMode.
        """
        new_registry = cls()
        for tc in registry.list_all():
            contract = ToolContract(
                tool_name=tc.tool_name,
                side_effect=tc.side_effect,
                replay_mode=side_effect_to_replay_mode(tc.side_effect),
                description=tc.description,
            )
            new_registry.register_contract(contract)
        return new_registry
