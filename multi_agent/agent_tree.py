"""Agent tree model for dependency tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentNode:
    """A node in the agent tree."""

    agent_id: str
    agent_type: str  # orchestrator, specialist, tool
    dependencies: list[str] = field(default_factory=list)
    shared_components: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentDependency:
    """A dependency between agents."""

    from_agent: str
    to_agent: str
    dependency_type: str  # routing, shared_tool, shared_context, handoff


class AgentTree:
    """Agent tree for dependency tracking."""

    def __init__(self):
        self.nodes: dict[str, AgentNode] = {}
        self.dependencies: list[AgentDependency] = []

    def add_node(self, node: AgentNode) -> None:
        """Add an agent node."""
        self.nodes[node.agent_id] = node

    def add_dependency(self, dep: AgentDependency) -> None:
        """Add a dependency between agents."""
        self.dependencies.append(dep)

    def get_dependents(self, agent_id: str) -> list[str]:
        """Get all agents that depend on this agent."""
        return [dep.from_agent for dep in self.dependencies if dep.to_agent == agent_id]

    def get_dependencies_of(self, agent_id: str) -> list[str]:
        """Get all agents this agent depends on."""
        return [dep.to_agent for dep in self.dependencies if dep.from_agent == agent_id]

    def get_shared_components(self, agent_id: str) -> list[str]:
        """Get shared components for an agent."""
        node = self.nodes.get(agent_id)
        if not node:
            return []
        return node.shared_components

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> AgentTree:
        """Parse agent tree from config."""
        tree = cls()

        # Simple parsing
        if "orchestrator" in config:
            orch_node = AgentNode(
                agent_id="orchestrator",
                agent_type="orchestrator",
                config=config["orchestrator"],
            )
            tree.add_node(orch_node)

        if "specialists" in config:
            for spec_id, spec_config in config["specialists"].items():
                spec_node = AgentNode(
                    agent_id=spec_id,
                    agent_type="specialist",
                    config=spec_config,
                )
                tree.add_node(spec_node)

                tree.add_dependency(
                    AgentDependency(
                        from_agent="orchestrator",
                        to_agent=spec_id,
                        dependency_type="routing",
                    )
                )

        return tree
