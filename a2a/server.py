"""A2A protocol server — exposes registered agents over JSON-RPC style endpoints.

The A2AServer accepts task requests from external callers, routes them to
locally registered agents, and manages the full task lifecycle via TaskManager.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from a2a.task import TaskManager
from a2a.types import A2ATask, TaskStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class A2AServer:
    """Lightweight A2A-protocol server for locally registered agents.

    Args:
        agents: Mapping of agent_name -> config dict.  Each config may
                optionally contain a ``handler`` callable
                ``(message: str) -> str`` that is invoked when a task arrives.
    """

    def __init__(self, agents: dict[str, dict[str, Any]]) -> None:
        self._agents = agents
        self._task_manager = TaskManager()

    # ------------------------------------------------------------------
    # Public API (JSON-RPC style)
    # ------------------------------------------------------------------

    def handle_task_send(self, request: dict[str, Any]) -> A2ATask:
        """Accept a new task submission (JSON-RPC ``tasks/send``).

        Expected request shape::

            {
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {
                    "message": {"role": "user", "parts": [{"type": "text", "text": "..."}]},
                    "agentName": "my_agent",       # optional
                    "skillId": "skill_id",         # optional
                    "metadata": {}                 # optional
                },
                "id": "req-1"
            }

        Args:
            request: Parsed JSON-RPC request dict.

        Returns:
            The created/updated A2ATask.
        """
        params = request.get("params", {})
        message_payload = params.get("message", {})
        input_text = self._extract_text(message_payload)
        agent_name = params.get("agentName", params.get("agent_name", ""))
        metadata = dict(params.get("metadata", {}))
        if params.get("skillId") or params.get("skill_id"):
            metadata["skill_id"] = params.get("skillId") or params.get("skill_id")

        # Resolve agent
        if not agent_name:
            agent_name = next(iter(self._agents), "")
        if agent_name not in self._agents and self._agents:
            agent_name = next(iter(self._agents))

        task = self._task_manager.create_task(
            input_message=input_text,
            agent_name=agent_name,
            metadata=metadata,
        )

        # Transition to WORKING immediately
        self._task_manager.update_status(task.task_id, TaskStatus.WORKING)

        # Execute synchronously (callers may wrap in a thread/async layer)
        try:
            output = self._execute_agent(agent_name, input_text)
            task = self._task_manager.update_status(
                task.task_id, TaskStatus.COMPLETED, output=output
            )
        except Exception as exc:  # noqa: BLE001
            task = self._task_manager.update_status(
                task.task_id,
                TaskStatus.FAILED,
                output=f"Agent execution failed: {exc}",
            )

        return task

    def handle_task_get(self, task_id: str) -> A2ATask:
        """Retrieve the current state of a task.

        Args:
            task_id: Unique task identifier.

        Returns:
            The A2ATask record.

        Raises:
            KeyError: If the task is not found.
        """
        task = self._task_manager.get_task(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")
        return task

    def handle_task_cancel(self, task_id: str) -> A2ATask:
        """Cancel a task that is not yet terminal.

        Args:
            task_id: Unique task identifier.

        Returns:
            The updated A2ATask with CANCELED status.

        Raises:
            KeyError: If the task is not found.
            ValueError: If the task is already in a terminal state.
        """
        task = self._task_manager.get_task(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")

        terminal = {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELED.value,
        }
        if task.status in terminal:
            raise ValueError(
                f"Task '{task_id}' is already in terminal state '{task.status}'"
            )

        return self._task_manager.update_status(task_id, TaskStatus.CANCELED)

    def list_agents(self) -> list[str]:
        """Return the names of all registered agents.

        Returns:
            Sorted list of agent name strings.
        """
        return sorted(self._agents.keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_agent(self, agent_name: str, message: str) -> str:
        """Dispatch a message to the named agent and return its response.

        If the agent config contains a ``handler`` callable it is invoked
        directly.  Otherwise a placeholder response is returned so the
        server is functional even without wired-up handlers.

        Args:
            agent_name: Key in ``self._agents``.
            message: The input text to send to the agent.

        Returns:
            Agent response string.
        """
        config = self._agents.get(agent_name, {})
        handler = config.get("handler")
        if callable(handler):
            return str(handler(message))

        # Fallback stub — real deployment wires up handlers via config
        description = config.get("description", agent_name)
        return (
            f"[{agent_name}] Received: {message!r}. "
            f"Agent description: {description}. "
            "(No handler configured — this is a stub response.)"
        )

    @staticmethod
    def _extract_text(message: dict[str, Any] | str) -> str:
        """Extract plain text from a message dict or raw string."""
        if isinstance(message, str):
            return message
        parts = message.get("parts", [])
        texts = [
            p.get("text", "")
            for p in parts
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        if texts:
            return " ".join(texts)
        # Fallback: stringify the whole message
        return str(message)
