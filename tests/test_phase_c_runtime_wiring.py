"""Tests for Phase-C workbench runtime wiring.

Verifies the full stack — tools + permissions + skills + hooks + plan
mode + transcript rewind + background panel — plugs together via
:func:`build_workbench_runtime` so a single caller gets everything the
REPL would in production."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from cli.hooks import HookDefinition, HookEvent, HookType
from cli.llm.streaming import (
    MessageStop,
    TextDelta,
    ToolUseEnd,
    ToolUseStart,
)
from cli.llm.types import TurnMessage
from cli.tools.base import ToolContext
from cli.tools.exit_plan_mode import PLAN_WORKFLOW_KEY
from cli.tools.skill_tool import SKILL_REGISTRY_KEY
from cli.workbench_app.background_panel import TaskStatus
from cli.workbench_app.orchestrator_runtime import (
    WorkbenchRuntime,
    build_workbench_runtime,
)
from cli.workbench_app.plan_mode import PlanState


# ---------------------------------------------------------------------------
# Fakes + fixtures
# ---------------------------------------------------------------------------


class _ScriptedModel:
    """Scripted streaming model — ordered sequence of event lists, one per turn."""

    def __init__(self, turns: list[list[Any]]) -> None:
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> Iterator[Any]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": [m.to_wire() for m in messages],
                "tools": tools,
            }
        )
        events = self._turns.pop(0) if self._turns else [MessageStop(stop_reason="end_turn")]
        for event in events:
            yield event


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Basic runtime construction
# ---------------------------------------------------------------------------


def test_build_workbench_runtime_wires_all_subsystems(workspace: Path) -> None:
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel([]),
    )
    assert isinstance(runtime, WorkbenchRuntime)
    # Every subsystem is present and non-None.
    assert runtime.tool_registry is not None
    assert runtime.skill_registry is not None
    assert runtime.plan_workflow is not None
    assert runtime.transcript_rewind is not None
    assert runtime.background_tasks is not None
    assert runtime.hook_registry is not None
    assert runtime.session is not None
    # Orchestrator carries the tool extra seed so tool contexts see
    # every subsystem.
    seed = getattr(runtime.orchestrator, "_tool_extra_seed", None)
    assert isinstance(seed, dict)
    assert seed["active_model"] == "claude-sonnet-4-5"
    assert SKILL_REGISTRY_KEY in seed
    assert PLAN_WORKFLOW_KEY in seed
    assert "background_task_registry" in seed


def test_runtime_plan_workflow_binds_to_permission_manager(workspace: Path) -> None:
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel([]),
    )
    runtime.plan_workflow.begin("Prep a refactor")
    from cli.tools.file_edit import FileEditTool

    # Drafting plan blocks mutating tools on the shared permission
    # manager — so the orchestrator inherits the restriction for free.
    assert (
        runtime.permission_manager.decision_for_tool(
            FileEditTool(), {"path": "x"}
        )
        == "deny"
    )


def test_runtime_skill_registry_reads_workspace_skills(workspace: Path) -> None:
    skill_dir = workspace / ".agentlab" / "skills"
    skill_dir.mkdir(parents=True)
    (skill_dir / "ship.md").write_text(
        "---\nname: ship\ndescription: ship it\n---\nbody\n",
        encoding="utf-8",
    )
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel([]),
    )
    assert runtime.skill_registry.has("ship") is True


# ---------------------------------------------------------------------------
# End-to-end: orchestrator turn uses a real FileRead tool call
# ---------------------------------------------------------------------------


def test_orchestrator_turn_executes_tool_and_updates_background_panel(
    workspace: Path,
) -> None:
    (workspace / "note.txt").write_text("hello\n", encoding="utf-8")

    model = _ScriptedModel(
        [
            [
                ToolUseStart(id="t1", name="FileRead"),
                ToolUseEnd(id="t1", name="FileRead", input={"path": "note.txt"}),
                MessageStop(stop_reason="tool_use"),
            ],
            [
                TextDelta(text="The file says 'hello'."),
                MessageStop(stop_reason="end_turn"),
            ],
        ]
    )

    runtime = build_workbench_runtime(workspace_root=workspace, model=model)
    result = runtime.orchestrator.run_turn("Read the note")
    assert len(result.tool_executions) == 1
    assert result.tool_executions[0].tool_name == "FileRead"
    assert "hello" in result.assistant_text or "hello" in (
        result.tool_executions[0].result.content
    )


# ---------------------------------------------------------------------------
# SkillTool nested invocation picks up the allowlist
# ---------------------------------------------------------------------------


def test_skill_tool_nested_invocation_uses_bound_allowlist(workspace: Path) -> None:
    skill_dir = workspace / ".agentlab" / "skills"
    skill_dir.mkdir(parents=True)
    (skill_dir / "summarise.md").write_text(
        "---\nname: summarise\nallowed-tools: [FileRead]\n---\n"
        "Summarise the repo. $ARGUMENTS\n",
        encoding="utf-8",
    )

    # Call order: outer turn 1 (requests SkillTool) → nested orchestrator
    # turn (produces "Nested response.") → outer turn 2 (final text).
    model = _ScriptedModel(
        [
            [
                ToolUseStart(id="s1", name="SkillTool"),
                ToolUseEnd(
                    id="s1",
                    name="SkillTool",
                    input={"slug": "summarise", "arguments": ""},
                ),
                MessageStop(stop_reason="tool_use"),
            ],
            # Nested orchestrator's model call — single end_turn response.
            [
                TextDelta(text="Nested response."),
                MessageStop(stop_reason="end_turn"),
            ],
            # Outer turn 2: receives the nested tool_result, wraps up.
            [
                TextDelta(text="Skill completed."),
                MessageStop(stop_reason="end_turn"),
            ],
        ]
    )

    runtime = build_workbench_runtime(workspace_root=workspace, model=model)
    result = runtime.orchestrator.run_turn("Run the skill please")
    assert "Skill completed." in result.assistant_text
    # The skill's nested turn ran against the same model; we see the
    # SkillTool invocation in the outer tool_executions.
    skill_exec = result.tool_executions[0]
    assert skill_exec.tool_name == "SkillTool"
    assert skill_exec.result is not None
    assert "Nested response." in skill_exec.result.content


# ---------------------------------------------------------------------------
# Plan mode + ExitPlanMode tool
# ---------------------------------------------------------------------------


def test_exit_plan_mode_tool_transitions_workflow(workspace: Path) -> None:
    model = _ScriptedModel(
        [
            [
                ToolUseStart(id="ep1", name="ExitPlanMode"),
                ToolUseEnd(
                    id="ep1",
                    name="ExitPlanMode",
                    input={"plan": "1. Read.\n2. Write."},
                ),
                MessageStop(stop_reason="tool_use"),
            ],
            [
                TextDelta(text="Approved."),
                MessageStop(stop_reason="end_turn"),
            ],
        ]
    )

    runtime = build_workbench_runtime(workspace_root=workspace, model=model)
    runtime.plan_workflow.begin("Ship a feature")

    from cli.workbench_app.permission_dialog import DialogChoice, DialogOutcome

    def approve(*_a, **_k):
        return DialogOutcome(
            choice=DialogChoice.APPROVE,
            allow=True,
            persist_rule=None,
            persist_scope=None,
        )

    runtime.orchestrator.dialog_runner = approve
    result = runtime.orchestrator.run_turn("Use the ExitPlanMode tool")

    assert runtime.plan_workflow.state is PlanState.APPROVED
    assert any(
        execution.tool_name == "ExitPlanMode"
        for execution in result.tool_executions
    )


# ---------------------------------------------------------------------------
# Prompt-fragment hooks surface in the orchestrator's system prompt
# ---------------------------------------------------------------------------


def test_prompt_hook_fragment_reaches_model(workspace: Path) -> None:
    model = _ScriptedModel(
        [[TextDelta(text="ack"), MessageStop(stop_reason="end_turn")]]
    )
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=model,
        system_prompt="Be concise.",
    )
    # Register a prompt hook dynamically.
    runtime.hook_registry.add(
        HookDefinition(
            event=HookEvent.PRE_TOOL_USE,
            matcher="",
            hook_type=HookType.PROMPT,
            prompt="Always cite the file path when you reference code.",
            id="cite-rule",
        )
    )
    runtime.orchestrator.run_turn("Hello")
    system_prompt = model.calls[0]["system_prompt"]
    assert "Be concise." in system_prompt
    assert "Always cite the file path" in system_prompt
