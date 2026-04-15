"""Tests for Phase F.1 (SkillTool) and F.2 (ExitPlanModeTool)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

from cli.permissions import PermissionManager
from cli.tools.base import ToolContext, ToolResult
from cli.tools.exit_plan_mode import ExitPlanModeTool, PLAN_WORKFLOW_KEY
from cli.tools.file_edit import FileEditTool
from cli.tools.registry import default_registry, reset_default_registry
from cli.tools.skill_tool import (
    MAX_SKILL_RECURSION,
    ORCHESTRATOR_FACTORY_KEY,
    SKILL_RECURSION_KEY,
    SKILL_REGISTRY_KEY,
    SkillTool,
)
from cli.user_skills.registry import SkillRegistry
from cli.user_skills.store import SkillStore
from cli.workbench_app.plan_mode import PlanState, PlanStore, PlanWorkflow


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


def _write_skill(root: Path, filename: str, body: str) -> None:
    skill_dir = root / ".agentlab" / "skills"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / filename).write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# SkillTool — basics
# ---------------------------------------------------------------------------


def test_skill_tool_requires_slug(workspace: Path) -> None:
    ctx = ToolContext(workspace_root=workspace)
    result = SkillTool().run({}, ctx)
    assert not result.ok
    assert "slug" in result.content.lower()


def test_skill_tool_fails_when_registry_missing(workspace: Path) -> None:
    ctx = ToolContext(workspace_root=workspace, extra={})
    result = SkillTool().run({"slug": "commit"}, ctx)
    assert not result.ok
    assert "unknown skill" in result.content.lower()


def test_skill_tool_fails_for_unknown_slug(workspace: Path) -> None:
    registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))
    ctx = ToolContext(
        workspace_root=workspace,
        extra={SKILL_REGISTRY_KEY: registry},
    )
    result = SkillTool().run({"slug": "nope"}, ctx)
    assert not result.ok
    assert "nope" in result.content


def test_skill_tool_without_factory_returns_expanded_prompt(workspace: Path) -> None:
    _write_skill(
        workspace,
        "commit.md",
        "---\nname: commit\ndescription: Commit helper\n---\n"
        "Write a commit message. Arguments: $ARGUMENTS\n",
    )
    registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))
    ctx = ToolContext(
        workspace_root=workspace,
        extra={SKILL_REGISTRY_KEY: registry},
    )
    result = SkillTool().run({"slug": "commit", "arguments": "wip fix"}, ctx)
    assert result.ok
    assert "Skill 'commit'" in result.content
    assert "wip fix" in result.content
    assert result.metadata["nested"] is False


def test_skill_tool_hits_recursion_cap(workspace: Path) -> None:
    registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))
    ctx = ToolContext(
        workspace_root=workspace,
        extra={
            SKILL_REGISTRY_KEY: registry,
            SKILL_RECURSION_KEY: MAX_SKILL_RECURSION,
        },
    )
    result = SkillTool().run({"slug": "commit"}, ctx)
    assert not result.ok
    assert "recursion limit" in result.content


# ---------------------------------------------------------------------------
# SkillTool — nested orchestrator path
# ---------------------------------------------------------------------------


@dataclass
class _FakeNestedOrchestrator:
    """Stand-in for :class:`LLMOrchestrator` in SkillTool nested tests."""

    permissions: PermissionManager
    response_text: str = "nested complete"
    tool_executions: list[Any] = field(default_factory=list)
    stop_reason: str = "end_turn"
    assistant_text: str = ""
    last_prompt: str | None = None
    last_allowlist: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.assistant_text = self.response_text

    def run_turn(self, user_prompt: str):
        # Capture the allowlist that's active when run_turn fires so tests
        # can assert the scoped overlay was installed.
        self.last_prompt = user_prompt
        overlay = getattr(self.permissions, "_skill_allowlist", None)
        self.last_allowlist = tuple(sorted(overlay)) if overlay else ()

        @dataclass
        class _Result:
            assistant_text: str
            tool_executions: list[Any]
            stop_reason: str

        return _Result(
            assistant_text=self.response_text,
            tool_executions=self.tool_executions,
            stop_reason=self.stop_reason,
        )


def test_skill_tool_runs_nested_orchestrator_with_allowlist(workspace: Path) -> None:
    _write_skill(
        workspace,
        "summarise.md",
        "---\nname: summarise\ndescription: Summarise files\n"
        "allowed-tools: [FileRead, Grep]\n---\n"
        "Summarise the repo state. $ARGUMENTS\n",
    )
    registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))
    permissions = PermissionManager(root=workspace)

    captured_overlay: dict[str, Any] = {}

    def factory(*, system_prompt: str, context_extra: dict[str, Any]):
        captured_overlay["system_prompt"] = system_prompt
        captured_overlay["context_extra"] = context_extra
        return _FakeNestedOrchestrator(
            permissions=permissions,
            response_text="Here is the summary.",
        )

    ctx = ToolContext(
        workspace_root=workspace,
        extra={
            SKILL_REGISTRY_KEY: registry,
            ORCHESTRATOR_FACTORY_KEY: factory,
        },
    )
    result = SkillTool().run({"slug": "summarise", "arguments": "include tests"}, ctx)
    assert result.ok
    assert "Here is the summary." in result.content
    assert result.metadata["nested"] is True
    # Nested recursion counter bumped.
    assert captured_overlay["context_extra"][SKILL_RECURSION_KEY] == 1
    # System prompt names the skill and its allowlist.
    assert "summarise" in captured_overlay["system_prompt"].lower()
    assert "FileRead" in captured_overlay["system_prompt"]


def test_skill_tool_nested_allowlist_blocks_non_whitelisted(workspace: Path) -> None:
    _write_skill(
        workspace,
        "readonly.md",
        "---\nname: readonly\nallowed-tools: [FileRead]\n---\nDo only reads.\n",
    )
    registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))
    permissions = PermissionManager(root=workspace)

    observed_decision: dict[str, str] = {}

    def factory(*, system_prompt: str, context_extra: dict[str, Any]):
        nested = _FakeNestedOrchestrator(permissions=permissions)

        # Override run_turn so it queries the permission manager mid-flight
        # and records what the overlay says about FileEdit.
        def _run_turn(user_prompt: str):
            observed_decision["FileEdit"] = permissions.decision_for_tool(
                FileEditTool(), {"path": "x"}
            )
            return type("R", (), {
                "assistant_text": "did nothing risky",
                "tool_executions": [],
                "stop_reason": "end_turn",
            })()

        nested.run_turn = _run_turn  # type: ignore[assignment]
        return nested

    ctx = ToolContext(
        workspace_root=workspace,
        extra={
            SKILL_REGISTRY_KEY: registry,
            ORCHESTRATOR_FACTORY_KEY: factory,
        },
    )
    SkillTool().run({"slug": "readonly"}, ctx)
    assert observed_decision["FileEdit"] == "deny"

    # After the skill finishes, the overlay is gone — ordinary decision
    # returns to the default-mode "ask".
    assert permissions.decision_for_tool(FileEditTool(), {"path": "x"}) == "ask"


def test_skill_tool_nested_failure_returns_failure(workspace: Path) -> None:
    _write_skill(
        workspace,
        "broken.md",
        "---\nname: broken\n---\nbroken body\n",
    )
    registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))
    permissions = PermissionManager(root=workspace)

    def factory(*, system_prompt: str, context_extra: dict[str, Any]):
        class _Crasher(_FakeNestedOrchestrator):
            def run_turn(self, user_prompt: str):
                raise RuntimeError("nested explosion")

        return _Crasher(permissions=permissions)

    ctx = ToolContext(
        workspace_root=workspace,
        extra={
            SKILL_REGISTRY_KEY: registry,
            ORCHESTRATOR_FACTORY_KEY: factory,
        },
    )
    result = SkillTool().run({"slug": "broken"}, ctx)
    assert not result.ok
    assert "nested explosion" in result.content


# ---------------------------------------------------------------------------
# ExitPlanModeTool
# ---------------------------------------------------------------------------


@pytest.fixture
def workflow(workspace: Path) -> PlanWorkflow:
    store = PlanStore(root=workspace)
    wf = PlanWorkflow(store=store, session_id="session-x")
    return wf


def test_exit_plan_mode_requires_plan_content(workflow: PlanWorkflow, workspace: Path) -> None:
    workflow.begin("Draft one")
    ctx = ToolContext(
        workspace_root=workspace,
        extra={PLAN_WORKFLOW_KEY: workflow},
    )
    result = ExitPlanModeTool().run({"plan": "   "}, ctx)
    assert not result.ok
    assert "plan" in result.content.lower()


def test_exit_plan_mode_fails_when_no_workflow(workspace: Path) -> None:
    ctx = ToolContext(workspace_root=workspace)
    result = ExitPlanModeTool().run({"plan": "1. Do the thing."}, ctx)
    assert not result.ok
    assert "PlanWorkflow" in result.content


def test_exit_plan_mode_fails_when_not_drafting(workflow: PlanWorkflow, workspace: Path) -> None:
    # Without a draft in flight the workflow stays IDLE.
    ctx = ToolContext(
        workspace_root=workspace,
        extra={PLAN_WORKFLOW_KEY: workflow},
    )
    result = ExitPlanModeTool().run({"plan": "1. Step one"}, ctx)
    assert not result.ok
    assert "drafting" in result.content.lower()


def test_exit_plan_mode_approves_and_persists(workflow: PlanWorkflow, workspace: Path) -> None:
    plan = workflow.begin("Ship feature")
    ctx = ToolContext(
        workspace_root=workspace,
        extra={PLAN_WORKFLOW_KEY: workflow},
    )
    result = ExitPlanModeTool().run({"plan": "1. Read code.\n2. Write test."}, ctx)
    assert result.ok
    assert workflow.state is PlanState.APPROVED
    # The plan body on disk now contains the model-supplied content.
    store = PlanStore(root=workspace)
    reloaded = store.load(plan.id)
    assert "Read code" in reloaded.body
    assert result.metadata["state"] == "approved"


def test_exit_plan_mode_permission_action_distinct() -> None:
    tool = ExitPlanModeTool()
    assert tool.permission_action({"plan": "x"}) == "tool:ExitPlanMode"


# ---------------------------------------------------------------------------
# Default registry includes the new tools
# ---------------------------------------------------------------------------


def test_default_registry_includes_phase_f1_f2_tools() -> None:
    reset_default_registry()
    names = {tool.name for tool in default_registry().list()}
    assert "SkillTool" in names
    assert "ExitPlanMode" in names
