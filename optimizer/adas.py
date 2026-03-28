"""Automated Design of Agentic Systems (ADAS) – meta-agent architecture search."""

from __future__ import annotations

import copy
import random
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ArchitectureCandidate:
    """A single candidate architecture discovered during ADAS search."""

    arch_id: str
    topology: dict[str, Any]
    agent_count: int
    agent_types: list[str]
    tree_depth: int
    fan_out: int
    performance_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "arch_id": self.arch_id,
            "topology": self.topology,
            "agent_count": self.agent_count,
            "agent_types": self.agent_types,
            "tree_depth": self.tree_depth,
            "fan_out": self.fan_out,
            "performance_score": self.performance_score,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArchitectureCandidate":
        return cls(
            arch_id=data["arch_id"],
            topology=data["topology"],
            agent_count=data["agent_count"],
            agent_types=data["agent_types"],
            tree_depth=data["tree_depth"],
            fan_out=data["fan_out"],
            performance_score=data.get("performance_score", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ArchitectureSearchConfig:
    """Configuration controlling the breadth and depth of ADAS search."""

    max_candidates: int = 10
    search_depth: int = 3
    mutation_types: list[str] = field(
        default_factory=lambda: ["add_agent", "remove_agent", "change_type", "reorder"]
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AGENT_TYPES = [
    "llm_agent",
    "sequential_agent",
    "parallel_agent",
    "loop_agent",
    "retrieval_agent",
    "critic_agent",
    "router_agent",
]


def _measure_depth(topology: dict[str, Any], node: str | None = None, visited: set[str] | None = None) -> int:
    """Return the maximum tree depth starting from *node* (or root)."""
    if visited is None:
        visited = set()
    if node is None:
        node = topology.get("root", "")
    if not node or node in visited:
        return 0
    visited.add(node)
    children: list[str] = topology.get("edges", {}).get(node, [])
    if not children:
        return 1
    return 1 + max(_measure_depth(topology, c, visited) for c in children)


def _measure_fan_out(topology: dict[str, Any]) -> int:
    edges: dict[str, list[str]] = topology.get("edges", {})
    if not edges:
        return 0
    return max(len(v) for v in edges.values())


def _extract_agent_types(topology: dict[str, Any]) -> list[str]:
    return list(topology.get("agent_types", {}).values())


def _topology_agent_ids(topology: dict[str, Any]) -> list[str]:
    return list(topology.get("agent_types", {}).keys())


# ---------------------------------------------------------------------------
# Searcher
# ---------------------------------------------------------------------------

class MetaAgentSearcher:
    """Search for better agent architectures by mutating a given topology."""

    def search(
        self,
        current_arch: dict[str, Any],
        eval_fn: Callable[[ArchitectureCandidate], float],
        config: ArchitectureSearchConfig | None = None,
    ) -> list[ArchitectureCandidate]:
        """Generate and evaluate up to *config.max_candidates* mutations."""
        if config is None:
            config = ArchitectureSearchConfig()

        candidates: list[ArchitectureCandidate] = []
        seen: set[str] = set()

        for _ in range(config.max_candidates * config.search_depth):
            if len(candidates) >= config.max_candidates:
                break
            mutated = self.propose_mutation(current_arch)
            key = str(sorted(mutated.items()))
            if key in seen:
                continue
            seen.add(key)

            agent_ids = _topology_agent_ids(mutated)
            candidate = ArchitectureCandidate(
                arch_id=uuid.uuid4().hex[:12],
                topology=mutated,
                agent_count=len(agent_ids),
                agent_types=_extract_agent_types(mutated),
                tree_depth=_measure_depth(mutated),
                fan_out=_measure_fan_out(mutated),
            )
            score = self.evaluate_candidate(candidate, eval_fn)
            candidate.performance_score = score
            candidates.append(candidate)

        candidates.sort(key=lambda c: c.performance_score, reverse=True)
        return candidates

    def propose_mutation(self, arch: dict[str, Any]) -> dict[str, Any]:
        """Randomly pick one mutation and apply it."""
        mutations = {
            "add_agent": self._add_agent,
            "remove_agent": self._remove_agent,
            "change_type": self._change_agent_type,
            "reorder": self._reorder_agents,
        }
        chosen = random.choice(list(mutations.values()))
        return chosen(arch)

    def _add_agent(self, arch: dict[str, Any]) -> dict[str, Any]:
        """Insert a new agent node into the topology."""
        result = copy.deepcopy(arch)
        new_id = f"agent_{uuid.uuid4().hex[:6]}"
        new_type = random.choice(_AGENT_TYPES)

        result.setdefault("agent_types", {})[new_id] = new_type
        edges: dict[str, list[str]] = result.setdefault("edges", {})

        existing_ids = [k for k in result["agent_types"] if k != new_id]
        if existing_ids:
            parent = random.choice(existing_ids)
            edges.setdefault(parent, []).append(new_id)
        else:
            result["root"] = new_id

        return result

    def _remove_agent(self, arch: dict[str, Any]) -> dict[str, Any]:
        """Remove a random non-root agent from the topology."""
        result = copy.deepcopy(arch)
        agent_ids = _topology_agent_ids(result)
        root = result.get("root", "")
        removable = [a for a in agent_ids if a != root]
        if not removable:
            return result

        victim = random.choice(removable)
        result["agent_types"].pop(victim, None)
        edges: dict[str, list[str]] = result.get("edges", {})
        edges.pop(victim, None)
        for node, children in edges.items():
            if victim in children:
                children.remove(victim)
        return result

    def _change_agent_type(self, arch: dict[str, Any]) -> dict[str, Any]:
        """Change the type of a random agent to a different type."""
        result = copy.deepcopy(arch)
        agent_ids = _topology_agent_ids(result)
        if not agent_ids:
            return result
        target = random.choice(agent_ids)
        current_type = result["agent_types"].get(target, "")
        alternatives = [t for t in _AGENT_TYPES if t != current_type]
        if alternatives:
            result["agent_types"][target] = random.choice(alternatives)
        return result

    def _reorder_agents(self, arch: dict[str, Any]) -> dict[str, Any]:
        """Shuffle the child order for a random parent node."""
        result = copy.deepcopy(arch)
        edges: dict[str, list[str]] = result.get("edges", {})
        parents_with_children = [p for p, ch in edges.items() if len(ch) > 1]
        if not parents_with_children:
            return result
        parent = random.choice(parents_with_children)
        random.shuffle(edges[parent])
        return result

    def evaluate_candidate(
        self,
        candidate: ArchitectureCandidate,
        eval_fn: Callable[[ArchitectureCandidate], float],
    ) -> float:
        """Call *eval_fn* and return the score, defaulting to 0.0 on error."""
        try:
            return float(eval_fn(candidate))
        except Exception:
            return 0.0
