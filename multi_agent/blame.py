"""Multi-agent failure attribution (blame mapping)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentBlameEntry:
    """Failure attribution record for a single agent.

    Attributes:
        agent_name: Identifier of the agent.
        failure_count: Total number of traces in which this agent was blamed.
        failure_rate: Fraction of all evaluated traces attributed to this agent.
        failure_types: Distinct failure categories observed for this agent.
        impact_score: Composite severity score in [0, 1] — higher means the
            agent's failures had a larger downstream impact.
    """

    agent_name: str
    failure_count: int = 0
    failure_rate: float = 0.0
    failure_types: list[str] = field(default_factory=list)
    impact_score: float = 0.0

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "agent_name": self.agent_name,
            "failure_count": self.failure_count,
            "failure_rate": round(self.failure_rate, 6),
            "failure_types": list(self.failure_types),
            "impact_score": round(self.impact_score, 6),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentBlameEntry":
        """Deserialise from a plain dictionary."""
        return cls(
            agent_name=data.get("agent_name", ""),
            failure_count=data.get("failure_count", 0),
            failure_rate=data.get("failure_rate", 0.0),
            failure_types=list(data.get("failure_types", [])),
            impact_score=data.get("impact_score", 0.0),
        )


class MultiAgentBlameMap:
    """Attributes failures in multi-agent traces to specific agents.

    The blame map analyses a corpus of execution traces and, for each failing
    trace, determines which agent in the hierarchy is most likely responsible.
    It then aggregates per-agent statistics into :class:`AgentBlameEntry`
    objects sorted by impact.
    """

    # Failure-type keywords searched in trace error/status fields
    _FAILURE_KEYWORDS: dict[str, str] = {
        "timeout": "timeout",
        "timed out": "timeout",
        "error": "error",
        "exception": "error",
        "invalid": "invalid_output",
        "hallucination": "hallucination",
        "safety": "safety_violation",
        "refused": "safety_violation",
        "loop": "infinite_loop",
        "no response": "no_response",
        "empty": "no_response",
        "tool": "tool_failure",
        "routing": "routing_error",
    }

    # Hierarchical position weights: root agents have higher impact
    _HIERARCHY_WEIGHTS: dict[str, float] = {
        "orchestrator": 1.0,
        "root": 1.0,
        "coordinator": 0.9,
        "specialist": 0.7,
        "tool": 0.5,
        "leaf": 0.4,
    }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        traces: list[dict],
        agent_hierarchy: dict,
    ) -> list[AgentBlameEntry]:
        """Compute blame attribution across a corpus of traces.

        Args:
            traces: List of trace dicts. Each trace must contain at minimum a
                ``success`` (bool) or ``outcome`` field and optionally
                ``agents_involved`` (list[str]), ``error`` (str), and
                ``failure_type`` (str).
            agent_hierarchy: Dict mapping agent name -> metadata dict with
                optional ``role`` (str) and ``parent`` (str) fields.

        Returns:
            List of :class:`AgentBlameEntry` sorted by ``impact_score``
            descending (most culpable first).
        """
        total = len(traces)
        if total == 0:
            return []

        blame_counts: dict[str, int] = defaultdict(int)
        blame_types: dict[str, list[str]] = defaultdict(list)

        failing_traces = [t for t in traces if self._is_failure(t)]

        for trace in failing_traces:
            agents = trace.get("agents_involved", list(agent_hierarchy.keys()))
            if not agents:
                agents = list(agent_hierarchy.keys())

            blamed = self.attribute_failure(trace, agents)
            if blamed:
                blame_counts[blamed] += 1
                ftype = self._classify_failure_type(trace)
                if ftype not in blame_types[blamed]:
                    blame_types[blamed].append(ftype)

        entries: list[AgentBlameEntry] = []
        for agent_name, count in blame_counts.items():
            failure_rate = count / total
            impact = self._compute_impact(
                agent_name=agent_name,
                failure_rate=failure_rate,
                failure_types=blame_types[agent_name],
                hierarchy=agent_hierarchy,
            )
            entries.append(AgentBlameEntry(
                agent_name=agent_name,
                failure_count=count,
                failure_rate=round(failure_rate, 6),
                failure_types=list(blame_types[agent_name]),
                impact_score=round(impact, 6),
            ))

        entries.sort(key=lambda e: e.impact_score, reverse=True)
        return entries

    def attribute_failure(self, trace: dict, agents: list[str]) -> str:
        """Determine which agent most likely caused the failure in a trace.

        Attribution strategy (in priority order):
        1. If the trace has an explicit ``blamed_agent`` field, use it.
        2. If the trace has a ``last_agent`` field and it is in agents, use it.
        3. Match the failure type to the most plausible agent role using the
           hierarchy information embedded in agent names.
        4. Fall back to the last agent in the list.

        Args:
            trace: Trace dict describing a failed execution.
            agents: List of agent identifiers that participated in the trace.

        Returns:
            The agent identifier most responsible for the failure, or an empty
            string if agents is empty.
        """
        if not agents:
            return ""

        # Explicit blame override
        if trace.get("blamed_agent") in agents:
            return trace["blamed_agent"]

        # Explicit last-agent hint
        last_agent = trace.get("last_agent") or trace.get("failed_agent", "")
        if last_agent in agents:
            return last_agent

        failure_type = self._classify_failure_type(trace)

        # Route-level failures typically originate in the orchestrator/router
        if failure_type in ("routing_error", "no_response"):
            for agent in agents:
                if any(kw in agent.lower() for kw in ("orchestrator", "router", "coordinator")):
                    return agent

        # Tool failures are attributed to the tool-calling specialist
        if failure_type == "tool_failure":
            for agent in agents:
                if any(kw in agent.lower() for kw in ("tool", "executor", "runner")):
                    return agent

        # Safety violations attributed to the safety/guardrail layer
        if failure_type == "safety_violation":
            for agent in agents:
                if any(kw in agent.lower() for kw in ("safety", "guard", "filter")):
                    return agent

        # Default to last agent in the list (deepest in execution chain)
        return agents[-1]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_failure(self, trace: dict) -> bool:
        """Return True if the trace represents a failed execution."""
        outcome = trace.get("outcome", "")
        success = trace.get("success")
        if success is not None:
            return not bool(success)
        return outcome in {"fail", "error", "abandon", "failure", "failed"}

    def _classify_failure_type(self, trace: dict) -> str:
        """Derive a failure type label from trace fields."""
        # Prefer explicit field
        if trace.get("failure_type"):
            return str(trace["failure_type"])

        text = " ".join([
            str(trace.get("error", "")),
            str(trace.get("error_message", "")),
            str(trace.get("status", "")),
            str(trace.get("outcome", "")),
        ]).lower()

        for keyword, ftype in self._FAILURE_KEYWORDS.items():
            if keyword in text:
                return ftype

        return "unknown"

    def _compute_impact(
        self,
        agent_name: str,
        failure_rate: float,
        failure_types: list[str],
        hierarchy: dict,
    ) -> float:
        """Compute a composite impact score for an agent.

        Impact = failure_rate * hierarchy_weight * severity_multiplier

        Args:
            agent_name: Agent identifier.
            failure_rate: Fraction of total traces attributed to this agent.
            failure_types: Failure type labels for this agent.
            hierarchy: Agent hierarchy metadata dict.

        Returns:
            Impact score in approximately [0, 1].
        """
        # Determine hierarchy weight from role metadata
        agent_meta = hierarchy.get(agent_name, {})
        role = agent_meta.get("role", "").lower()

        hierarchy_weight = 0.6  # default
        for role_kw, weight in self._HIERARCHY_WEIGHTS.items():
            if role_kw in role or role_kw in agent_name.lower():
                hierarchy_weight = weight
                break

        # Severity multiplier: some failure types are worse than others
        severity_map = {
            "safety_violation": 1.5,
            "hallucination": 1.3,
            "infinite_loop": 1.2,
            "routing_error": 1.1,
            "timeout": 1.0,
            "error": 1.0,
            "tool_failure": 0.9,
            "invalid_output": 0.8,
            "no_response": 0.7,
            "unknown": 0.6,
        }
        severity = max(
            (severity_map.get(ft, 0.6) for ft in failure_types),
            default=0.6,
        )

        # Clamp to [0, 1]
        return min(1.0, failure_rate * hierarchy_weight * severity)
