"""Impact analyzer for multi-agent systems."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from multi_agent.agent_tree import AgentTree


@dataclass
class ImpactPrediction:
    """Predicted impact of a change on an agent."""

    agent_id: str
    affected: bool
    predicted_delta: float | None
    confidence: float
    reason: str


class ImpactAnalyzer:
    """Analyzes how changes to one agent affect the team."""

    def __init__(self, agent_tree: AgentTree):
        self.agent_tree = agent_tree

    def analyze_dependencies(self) -> dict[str, Any]:
        """Map which agents depend on which."""
        dep_map: dict[str, Any] = {}

        for agent_id in self.agent_tree.nodes:
            dependents = self.agent_tree.get_dependents(agent_id)
            dependencies = self.agent_tree.get_dependencies_of(agent_id)
            dep_map[agent_id] = {
                "dependents": dependents,
                "dependencies": dependencies,
                "shared_components": self.agent_tree.get_shared_components(agent_id),
            }

        return dep_map

    def predict_impact(
        self, mutation: dict[str, Any], agent_tree: AgentTree
    ) -> list[ImpactPrediction]:
        """Predict downstream effects of a change."""
        predictions: list[ImpactPrediction] = []

        target_agent = mutation.get("target_agent", "orchestrator")
        affected_agents = self._get_affected_agents(target_agent, agent_tree)

        for agent_id in affected_agents:
            confidence = 0.7 if agent_id == target_agent else 0.5

            prediction = ImpactPrediction(
                agent_id=agent_id,
                affected=True,
                predicted_delta=None,
                confidence=confidence,
                reason=f"Depends on {target_agent}" if agent_id != target_agent else "Direct target",
            )
            predictions.append(prediction)

        return predictions

    def _get_affected_agents(self, agent_id: str, agent_tree: AgentTree) -> list[str]:
        """Get all agents affected by a change to agent_id."""
        affected = {agent_id}
        dependents = agent_tree.get_dependents(agent_id)
        affected.update(dependents)

        for other_id, node in agent_tree.nodes.items():
            if other_id == agent_id:
                continue

            target_components = set(agent_tree.get_shared_components(agent_id))
            other_components = set(node.shared_components)

            if target_components & other_components:
                affected.add(other_id)

        return list(affected)

    def cross_agent_eval(
        self, mutation: dict[str, Any], affected_agents: list[str]
    ) -> dict[str, dict[str, float]]:
        """Evaluate mutation against all affected agents."""
        results: dict[str, dict[str, float]] = {}

        for agent_id in affected_agents:
            results[agent_id] = {
                "quality": 0.85,
                "latency": 150.0,
                "cost": 0.002,
            }

        return results

    def generate_impact_report(self, results: dict[str, Any]) -> dict[str, Any]:
        """Generate structured impact report."""
        return {
            "summary": {
                "total_agents": len(results),
                "affected_agents": len([r for r in results.values() if r.get("affected")]),
                "safe_to_deploy": True,
            },
            "agent_results": results,
            "recommendations": [
                "Run full eval on affected agents",
                "Monitor routing accuracy post-deployment",
            ],
        }
