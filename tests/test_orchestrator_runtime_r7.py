"""R7 Slice B.7 wiring tests for ``build_workbench_runtime``.

These tests pin down the additive R7 wiring: the 7 AgentLab tool
adapters, the AgentLab permission preset, the lean R7 system prompt
and the ConversationStore + ConversationBridge pair. The pre-existing
``tests/test_phase_c_runtime_wiring.py`` covers the Phase-C contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from cli.llm.types import AssistantToolUseBlock
from cli.llm.streaming import MessageStop
from cli.llm.types import TurnMessage
from cli.workbench_app.agentlab_tools import (
    DeployTool,
    EvalRunTool,
    ImproveAcceptTool,
    ImproveDiffTool,
    ImproveListTool,
    ImproveRunTool,
    ImproveShowTool,
)
from cli.workbench_app.conversation_bridge import ConversationBridge
from cli.workbench_app.conversation_store import ConversationStore
from cli.workbench_app.orchestrator_runtime import (
    WorkbenchRuntime,
    build_workbench_runtime,
)


AGENTLAB_TOOL_NAMES: tuple[str, ...] = (
    "EvalRun",
    "Deploy",
    "ImproveRun",
    "ImproveList",
    "ImproveShow",
    "ImproveDiff",
    "ImproveAccept",
)


class _ScriptedModel:
    """Minimal fake model — never actually streams; used to satisfy the
    ``ModelClient`` protocol while we build a runtime."""

    def __init__(self) -> None:
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
        yield MessageStop(stop_reason="end_turn")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "myws"
    ws.mkdir()
    (ws / ".agentlab").mkdir()
    return ws


# ---------------------------------------------------------------------------
# AgentLab tool registration
# ---------------------------------------------------------------------------


def test_runtime_registers_seven_agentlab_tools(workspace: Path) -> None:
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )
    for name in AGENTLAB_TOOL_NAMES:
        assert name in runtime.tool_registry.tools, (
            f"AgentLab tool {name!r} not registered on tool_registry; "
            f"have {sorted(runtime.tool_registry.tools)}"
        )


def test_runtime_register_idempotent(workspace: Path) -> None:
    """Building twice against the same workspace must not raise on the
    AgentLab tool registration. ``default_registry()`` returns a
    process-wide singleton, so the second call would otherwise hit a
    duplicate-name ToolError."""
    first = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )
    # Should NOT raise.
    second = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )
    for name in AGENTLAB_TOOL_NAMES:
        assert name in first.tool_registry.tools
        assert name in second.tool_registry.tools


# ---------------------------------------------------------------------------
# Permission preset
# ---------------------------------------------------------------------------


def test_runtime_applies_agentlab_permission_preset(workspace: Path) -> None:
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )
    assert runtime.permission_manager.decision_for("tool:EvalRun") == "ask"


def test_runtime_read_only_improve_tools_short_circuit_to_allow(
    workspace: Path,
) -> None:
    """Validates the B.5 invariant — read-only inspection tools never
    prompt even when the preset is active."""
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )
    assert (
        runtime.permission_manager.decision_for_tool(ImproveListTool(), {})
        == "allow"
    )


def test_runtime_wires_classifier_for_safe_bash_auto_approve(
    workspace: Path,
) -> None:
    """The live orchestrator path should pass classifier context into
    execute_tool_call so an allowlisted read-only Bash command does not
    fall through to the interactive dialog."""
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )

    def fail_dialog(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("safe Bash should have auto-approved, not prompted")

    runtime.orchestrator.dialog_runner = fail_dialog
    execution = runtime.orchestrator._execute_tool(
        AssistantToolUseBlock(id="t1", name="Bash", input={"command": "ls"})
    )

    assert execution.decision.value == "allow"


# ---------------------------------------------------------------------------
# System prompt — default-built lean R7 prompt vs explicit override
# ---------------------------------------------------------------------------


def test_runtime_default_system_prompt_includes_workspace_name(
    workspace: Path,
) -> None:
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )
    assert "myws" in runtime.orchestrator.system_prompt


def test_runtime_default_system_prompt_includes_tool_names(
    workspace: Path,
) -> None:
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )
    prompt = runtime.orchestrator.system_prompt
    for name in (
        "eval_run",
        "deploy",
        "improve_run",
        "improve_list",
        "improve_show",
        "improve_diff",
        "improve_accept",
    ):
        assert name in prompt, f"{name!r} missing from default system prompt"


def test_runtime_default_system_prompt_includes_injection_guard(
    workspace: Path,
) -> None:
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )
    assert "<tool_result>" in runtime.orchestrator.system_prompt


def test_runtime_explicit_system_prompt_is_respected(workspace: Path) -> None:
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
        system_prompt="custom",
    )
    assert runtime.orchestrator.system_prompt == "custom"


# ---------------------------------------------------------------------------
# Conversation store + bridge
# ---------------------------------------------------------------------------


def test_runtime_creates_conversation_store_and_bridge(workspace: Path) -> None:
    runtime = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )
    expected_db = workspace / ".agentlab" / "conversations.db"

    assert isinstance(runtime, WorkbenchRuntime)
    assert isinstance(runtime.conversation_store, ConversationStore)
    assert isinstance(runtime.conversation_bridge, ConversationBridge)
    assert isinstance(runtime.conversation_id, str) and runtime.conversation_id

    # The DB file lives at the agreed path.
    assert expected_db.exists()

    # The bridge points at the seeded conversation.
    convo = runtime.conversation_store.get_conversation(runtime.conversation_id)
    assert convo.id == runtime.conversation_id
    assert convo.messages == []


def test_runtime_conversation_id_persists_across_load(workspace: Path) -> None:
    """Two builds against the same workspace get distinct conversation
    ids — auto-resume is R7.10 (Slice C). Both ids land in the DB."""
    first = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )
    second = build_workbench_runtime(
        workspace_root=workspace,
        model=_ScriptedModel(),
    )
    assert first.conversation_id != second.conversation_id

    # Both readable from the same store (point a fresh store at the DB
    # to prove the rows survived the build, not just the in-memory
    # conn).
    db_path = workspace / ".agentlab" / "conversations.db"
    fresh = ConversationStore(db_path)
    ids = {c.id for c in fresh.list_recent(limit=10)}
    assert first.conversation_id in ids
    assert second.conversation_id in ids
