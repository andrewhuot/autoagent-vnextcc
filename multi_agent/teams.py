"""Multi-agent team formation and orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentTeam:
    """A named group of agents that collaborate on shared tasks.

    Attributes:
        team_id: Unique identifier for the team.
        agents: List of agent identifiers belonging to this team.
        communication_mode: How agents share information.
            - ``shared_state``: All agents read/write a common state dict.
            - ``message_passing``: Agents exchange typed messages.
            - ``broadcast``: One agent broadcasts findings to all peers.
        metadata: Arbitrary extra information (name, description, tags, etc.).
    """

    team_id: str
    agents: list[str] = field(default_factory=list)
    communication_mode: str = "shared_state"
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "team_id": self.team_id,
            "agents": list(self.agents),
            "communication_mode": self.communication_mode,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentTeam":
        """Deserialise from a plain dictionary."""
        return cls(
            team_id=data.get("team_id", ""),
            agents=list(data.get("agents", [])),
            communication_mode=data.get("communication_mode", "shared_state"),
            metadata=dict(data.get("metadata", {})),
        )


class TeamOrchestrator:
    """Creates and manages agent teams and coordinates task execution.

    The orchestrator maintains an in-memory registry of :class:`AgentTeam`
    instances and a shared-state store for ``shared_state`` teams.  In
    production, both would be backed by persistent storage.
    """

    def __init__(self) -> None:
        self._teams: dict[str, AgentTeam] = {}
        # Per-team shared state: team_id -> {agent_id -> findings list}
        self._shared_state: dict[str, dict[str, Any]] = {}
        # Per-team task results: team_id -> list of task result dicts
        self._task_results: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------
    # Team management
    # ------------------------------------------------------------------

    def create_team(
        self,
        agents: list[str],
        mode: str = "shared_state",
        metadata: dict[str, Any] | None = None,
    ) -> AgentTeam:
        """Create a new agent team.

        Args:
            agents: List of agent identifiers to include in the team.
            mode: Communication mode (``shared_state``, ``message_passing``,
                or ``broadcast``).
            metadata: Optional extra metadata to attach to the team.

        Returns:
            The newly created :class:`AgentTeam`.
        """
        team_id = str(uuid.uuid4())
        team = AgentTeam(
            team_id=team_id,
            agents=list(agents),
            communication_mode=mode,
            metadata=metadata or {},
        )
        self._teams[team_id] = team
        self._shared_state[team_id] = {}
        self._task_results[team_id] = []
        return team

    def get_team(self, team_id: str) -> AgentTeam | None:
        """Return the team with the given ID, or None if not found."""
        return self._teams.get(team_id)

    def list_teams(self) -> list[AgentTeam]:
        """Return all registered teams."""
        return list(self._teams.values())

    def disband_team(self, team_id: str) -> bool:
        """Remove a team and its associated state.

        Args:
            team_id: Team identifier.

        Returns:
            True if the team existed and was removed, False otherwise.
        """
        if team_id not in self._teams:
            return False
        del self._teams[team_id]
        self._shared_state.pop(team_id, None)
        self._task_results.pop(team_id, None)
        return True

    # ------------------------------------------------------------------
    # Task execution
    # ------------------------------------------------------------------

    def run_task(self, team_id: str, task: str) -> dict:
        """Run a task against a registered team.

        The orchestrator dispatches the task to each agent in the team
        sequentially (simulated), collecting findings along the way.  In
        production this would invoke the real agent runtimes.

        Args:
            team_id: Identifier of the team that should execute the task.
            task: Natural-language task description.

        Returns:
            Result dict with ``team_id``, ``task``, ``agents_involved``,
            ``findings``, ``status``, and ``result_summary`` fields.
        """
        team = self._teams.get(team_id)
        if team is None:
            return {
                "team_id": team_id,
                "task": task,
                "agents_involved": [],
                "findings": [],
                "status": "error",
                "result_summary": f"Team '{team_id}' not found.",
            }

        findings: list[dict] = []
        shared = self._shared_state.setdefault(team_id, {})

        for agent_id in team.agents:
            # Simulate agent processing: in production call the agent runtime
            finding = {
                "agent": agent_id,
                "task": task,
                "output": f"[simulated output from {agent_id}]",
                "status": "completed",
            }
            findings.append(finding)

            # Persist finding in shared state when using shared_state mode
            if team.communication_mode == "shared_state":
                shared.setdefault(agent_id, []).append(finding)

        result = {
            "team_id": team_id,
            "task": task,
            "agents_involved": list(team.agents),
            "findings": findings,
            "status": "completed",
            "result_summary": f"Task completed by {len(findings)} agent(s).",
        }
        self._task_results.setdefault(team_id, []).append(result)
        return result

    # ------------------------------------------------------------------
    # Finding sharing
    # ------------------------------------------------------------------

    def share_findings(
        self,
        team_id: str,
        from_agent: str,
        finding: dict,
    ) -> None:
        """Record a finding from one agent into the team's shared state.

        In ``broadcast`` mode the finding is also copied to every other agent's
        inbox so that peers can act on it.

        Args:
            team_id: Team identifier.
            from_agent: Identifier of the agent sharing the finding.
            finding: Arbitrary finding dict to share.
        """
        team = self._teams.get(team_id)
        if team is None:
            return

        shared = self._shared_state.setdefault(team_id, {})
        shared.setdefault(from_agent, []).append(finding)

        if team.communication_mode == "broadcast":
            for agent_id in team.agents:
                if agent_id != from_agent:
                    inbox_key = f"__inbox_{agent_id}"
                    shared.setdefault(inbox_key, []).append({
                        **finding,
                        "_from": from_agent,
                    })

    def get_shared_state(self, team_id: str) -> dict[str, Any]:
        """Return the full shared state for a team.

        Args:
            team_id: Team identifier.

        Returns:
            Shared state dict (may be empty if team does not exist or has no
            findings yet).
        """
        return dict(self._shared_state.get(team_id, {}))

    def get_task_history(self, team_id: str) -> list[dict]:
        """Return the list of past task results for a team.

        Args:
            team_id: Team identifier.

        Returns:
            List of result dicts from prior :meth:`run_task` calls.
        """
        return list(self._task_results.get(team_id, []))
