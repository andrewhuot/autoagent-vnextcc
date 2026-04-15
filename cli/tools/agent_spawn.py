"""AgentSpawnTool — spawn a subagent for a focused task.

Mirrors Claude Code's ``AgentTool``: the LLM asks for a worker agent with
a description and a prompt; we register the request as a background task
and hand it off to an injected spawner that actually runs the agent.

Why the tool is mostly a **registration** step in Phase 5: the real
subagent runtime lives in :mod:`multi_agent` / the coordinator, and
wiring those up requires the Phase-7 LLM loop. The tool today:

1. Validates the input.
2. Registers the task with :class:`BackgroundTaskRegistry` so
   ``/background`` surfaces it.
3. Calls an optional spawner callable that the REPL publishes via
   :attr:`ToolContext.extra['agent_spawner']`. The spawner is expected
   to be fast-return (enqueue, don't block) — the work happens
   asynchronously and the spawner later updates the task status via
   :meth:`BackgroundTaskRegistry.update`.

When no spawner is published the tool still records the task so tests
and headless smoke runs can assert the registration happened; the tool
result clearly states that no spawner was bound so the LLM knows not to
expect immediate output.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from cli.tools.base import Tool, ToolContext, ToolResult
from cli.workbench_app.background_panel import (
    BackgroundTaskRegistry,
    TaskStatus,
)


AGENT_SPAWNER_KEY = "agent_spawner"
BACKGROUND_REGISTRY_KEY = "background_task_registry"


Spawner = Callable[..., Any]
"""Function injected by the REPL. Expected signature::

    spawner(*, task_id: str, description: str, prompt: str,
            subagent_type: str | None, workspace_root) -> None

The return value is ignored; the spawner is fire-and-forget. It updates
the task status through the registry as progress comes in."""


class AgentSpawnTool(Tool):
    """Register a subagent task for asynchronous execution."""

    name = "AgentSpawn"
    description = (
        "Spawn a subagent to work on a focused task. Describe the work "
        "and supply the prompt. The subagent runs in the background — "
        "use /background to monitor progress and TaskGet to fetch "
        "results once complete."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Short label for the task (shown in /background).",
            },
            "prompt": {
                "type": "string",
                "description": "Full instructions the subagent should act on.",
            },
            "subagent_type": {
                "type": "string",
                "description": "Optional subagent role name (e.g. 'reviewer').",
            },
        },
        "required": ["description", "prompt"],
        "additionalProperties": False,
    }

    def permission_action(self, tool_input: Mapping[str, Any]) -> str:
        return f"tool:AgentSpawn:{tool_input.get('subagent_type') or 'default'}"

    def render_preview(self, tool_input: Mapping[str, Any]) -> str:
        description = str(tool_input.get("description", ""))
        subagent = tool_input.get("subagent_type")
        suffix = f" [{subagent}]" if subagent else ""
        return f"Spawn subagent{suffix}: {description[:120]}"

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        description = str(tool_input.get("description") or "").strip()
        prompt = str(tool_input.get("prompt") or "").strip()
        subagent_type = (tool_input.get("subagent_type") or "").strip() or None

        if not description:
            return ToolResult.failure("AgentSpawn requires a 'description'.")
        if not prompt:
            return ToolResult.failure("AgentSpawn requires a 'prompt'.")

        registry = _registry_from_context(context)
        if registry is None:
            # No panel means no way to report progress — refuse rather than
            # silently swallowing the request. The REPL publishes the
            # registry at startup, so a missing one indicates a wiring bug.
            return ToolResult.failure(
                "AgentSpawn: no background-task registry bound to this session. "
                "The REPL should publish one via ToolContext.extra."
            )

        task = registry.register(
            description=description,
            owner=f"agent:{subagent_type}" if subagent_type else "agent:default",
            detail=(prompt[:120] + "…") if len(prompt) > 120 else prompt,
        )

        spawner = _spawner_from_context(context)
        if spawner is None:
            task.touch(status=TaskStatus.QUEUED, detail="queued (no spawner bound)")
            return ToolResult.success(
                f"Registered subagent task {task.task_id}. No spawner is "
                "bound to this session — the task will stay queued until "
                "the LLM loop attaches one.",
                task_id=task.task_id,
                queued=True,
            )

        try:
            spawner(
                task_id=task.task_id,
                description=description,
                prompt=prompt,
                subagent_type=subagent_type,
                workspace_root=context.workspace_root,
            )
        except Exception as exc:  # pragma: no cover - defensive
            registry.update(task.task_id, status=TaskStatus.FAILED, detail=str(exc))
            return ToolResult.failure(
                f"AgentSpawn spawner raised: {exc}"
            )

        task.touch(status=TaskStatus.RUNNING, detail="dispatched to spawner")
        return ToolResult.success(
            f"Dispatched subagent task {task.task_id}. Monitor with /background.",
            task_id=task.task_id,
            queued=False,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registry_from_context(context: ToolContext) -> BackgroundTaskRegistry | None:
    value = context.extra.get(BACKGROUND_REGISTRY_KEY) if context.extra else None
    return value if isinstance(value, BackgroundTaskRegistry) else None


def _spawner_from_context(context: ToolContext) -> Spawner | None:
    value = context.extra.get(AGENT_SPAWNER_KEY) if context.extra else None
    return value if callable(value) else None


__all__ = ["AGENT_SPAWNER_KEY", "BACKGROUND_REGISTRY_KEY", "AgentSpawnTool"]
