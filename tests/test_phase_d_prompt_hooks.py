"""Tests for Phase-D prompt-fragment hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from cli.hooks import (
    HookDefinition,
    HookEvent,
    HookOutcome,
    HookRegistry,
    HookType,
    HookVerdict,
    load_hook_registry,
)
from cli.llm.orchestrator import LLMOrchestrator
from cli.llm.streaming import (
    MessageStop,
    TextDelta,
    ToolUseDelta,
    ToolUseEnd,
    ToolUseStart,
)
from cli.llm.types import TurnMessage
from cli.permissions import PermissionManager
from cli.sessions import SessionStore
from cli.tools.file_read import FileReadTool
from cli.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Settings loader accepts prompt-type hooks
# ---------------------------------------------------------------------------


def test_load_hook_registry_parses_prompt_hooks() -> None:
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "prompt",
                            "prompt": "Always favour diff-style tool output.",
                            "id": "style-nudge",
                        }
                    ],
                }
            ]
        }
    }
    registry = load_hook_registry(settings)
    hooks = registry.hooks_for(HookEvent.PRE_TOOL_USE)
    assert len(hooks) == 1
    assert hooks[0].hook_type is HookType.PROMPT
    assert hooks[0].prompt == "Always favour diff-style tool output."
    assert hooks[0].id == "style-nudge"


def test_load_hook_registry_skips_empty_prompt() -> None:
    settings = {
        "hooks": {
            "PostToolUse": [
                {"hooks": [{"type": "prompt", "prompt": "   "}]},
            ]
        }
    }
    registry = load_hook_registry(settings)
    assert registry.hooks_for(HookEvent.POST_TOOL_USE) == []


def test_load_hook_registry_preserves_command_hooks_as_default() -> None:
    # Legacy settings without explicit type still parse as COMMAND.
    settings = {
        "hooks": {
            "PreToolUse": [
                {"hooks": [{"command": "./check.sh"}]},
            ]
        }
    }
    registry = load_hook_registry(settings)
    hooks = registry.hooks_for(HookEvent.PRE_TOOL_USE)
    assert hooks[0].hook_type is HookType.COMMAND


# ---------------------------------------------------------------------------
# prompt_fragments_for — dedupe + order
# ---------------------------------------------------------------------------


def test_prompt_fragments_for_returns_matching_prompts_only() -> None:
    registry = HookRegistry()
    registry.add(
        HookDefinition(
            event=HookEvent.PRE_TOOL_USE,
            matcher="",
            hook_type=HookType.COMMAND,
            command="./shell.sh",
        )
    )
    registry.add(
        HookDefinition(
            event=HookEvent.PRE_TOOL_USE,
            matcher="",
            hook_type=HookType.PROMPT,
            prompt="Fragment A",
        )
    )
    fragments = registry.prompt_fragments_for(HookEvent.PRE_TOOL_USE)
    assert fragments == ["Fragment A"]


def test_prompt_fragments_for_dedupes_by_id() -> None:
    registry = HookRegistry()
    for _ in range(3):
        registry.add(
            HookDefinition(
                event=HookEvent.PRE_TOOL_USE,
                matcher="",
                hook_type=HookType.PROMPT,
                prompt="Be terse.",
                id="terse",
            )
        )
    fragments = registry.prompt_fragments_for(HookEvent.PRE_TOOL_USE)
    assert fragments == ["Be terse."]


def test_prompt_fragments_for_dedupes_by_content_when_ids_missing() -> None:
    registry = HookRegistry()
    registry.add(
        HookDefinition(
            event=HookEvent.POST_TOOL_USE,
            matcher="FileRead",
            hook_type=HookType.PROMPT,
            prompt="Summarise the file content.",
        )
    )
    registry.add(
        HookDefinition(
            event=HookEvent.POST_TOOL_USE,
            matcher="*",
            hook_type=HookType.PROMPT,
            prompt="Summarise the file content.",
        )
    )
    fragments = registry.prompt_fragments_for(HookEvent.POST_TOOL_USE, tool_name="FileRead")
    assert fragments == ["Summarise the file content."]


def test_prompt_fragments_for_filters_by_tool_matcher() -> None:
    registry = HookRegistry()
    registry.add(
        HookDefinition(
            event=HookEvent.POST_TOOL_USE,
            matcher="FileEdit",
            hook_type=HookType.PROMPT,
            prompt="Call out the diff.",
            id="edit-diff",
        )
    )
    registry.add(
        HookDefinition(
            event=HookEvent.POST_TOOL_USE,
            matcher="FileRead",
            hook_type=HookType.PROMPT,
            prompt="Summarise the read.",
            id="read-sum",
        )
    )
    for_edit = registry.prompt_fragments_for(HookEvent.POST_TOOL_USE, tool_name="FileEdit")
    for_read = registry.prompt_fragments_for(HookEvent.POST_TOOL_USE, tool_name="FileRead")
    assert for_edit == ["Call out the diff."]
    assert for_read == ["Summarise the read."]


# ---------------------------------------------------------------------------
# Registry.fire() is unchanged for command hooks and ignores prompt hooks
# ---------------------------------------------------------------------------


def test_fire_ignores_prompt_hooks_entirely() -> None:
    ran: list[str] = []

    def runner(hook, payload):
        ran.append(hook.command)
        from cli.hooks.registry import HookProcessResult
        return HookProcessResult(returncode=0, stdout="", stderr="")

    registry = HookRegistry(runner=runner)
    registry.add(
        HookDefinition(
            event=HookEvent.PRE_TOOL_USE,
            matcher="",
            hook_type=HookType.PROMPT,
            prompt="never fires in the shell runner",
        )
    )
    registry.add(
        HookDefinition(
            event=HookEvent.PRE_TOOL_USE,
            matcher="",
            hook_type=HookType.COMMAND,
            command="./run.sh",
        )
    )
    outcome = registry.fire(HookEvent.PRE_TOOL_USE, tool_name="Bash")
    assert outcome.verdict is HookVerdict.ALLOW
    # Only the shell hook fired.
    assert ran == ["./run.sh"]


# ---------------------------------------------------------------------------
# Orchestrator integration — fragments appear in model payload
# ---------------------------------------------------------------------------


class _RecordingModel:
    """Scripted streaming model that captures the system prompt + messages."""

    def __init__(self, event_sequences: list[list[Any]]) -> None:
        self._sequences = list(event_sequences)
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
        events = (
            self._sequences.pop(0)
            if self._sequences
            else [MessageStop(stop_reason="end_turn")]
        )
        for event in events:
            yield event


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


def _build_orchestrator(
    workspace: Path,
    model: _RecordingModel,
    hook_registry: HookRegistry,
    echo_sink: list[str],
) -> LLMOrchestrator:
    session_store = SessionStore(workspace_dir=workspace)
    session = session_store.create(title="prompt hook test")
    tool_registry = ToolRegistry()
    tool_registry.register(FileReadTool())
    return LLMOrchestrator(
        model=model,
        tool_registry=tool_registry,
        permissions=PermissionManager(root=workspace),
        workspace_root=workspace,
        session=session,
        session_store=session_store,
        hook_registry=hook_registry,
        system_prompt="You are helpful.",
        echo=echo_sink.append,
    )


def test_pre_tool_use_prompt_fragments_land_in_system_prompt(
    workspace: Path,
) -> None:
    registry = HookRegistry()
    registry.add(
        HookDefinition(
            event=HookEvent.PRE_TOOL_USE,
            matcher="",
            hook_type=HookType.PROMPT,
            prompt="Prefer bullet points over paragraphs.",
            id="style-bullet",
        )
    )

    model = _RecordingModel([[TextDelta(text="ok"), MessageStop(stop_reason="end_turn")]])
    orchestrator = _build_orchestrator(workspace, model, registry, echo_sink=[])
    orchestrator.run_turn("Hello")

    # Exactly one call made; its system_prompt includes the hook guidance.
    assert len(model.calls) == 1
    system_prompt = model.calls[0]["system_prompt"]
    assert "You are helpful." in system_prompt
    assert "Prefer bullet points over paragraphs." in system_prompt
    assert "Hook Guidance" in system_prompt


def test_post_tool_use_prompt_fragments_attach_to_tool_results(
    workspace: Path,
) -> None:
    (workspace / "note.txt").write_text("hello\n", encoding="utf-8")

    registry = HookRegistry()
    registry.add(
        HookDefinition(
            event=HookEvent.POST_TOOL_USE,
            matcher="FileRead",
            hook_type=HookType.PROMPT,
            prompt="Summarise the file content in one line.",
            id="summarise",
        )
    )

    model = _RecordingModel(
        [
            [
                ToolUseStart(id="t1", name="FileRead"),
                ToolUseDelta(id="t1", input_json='{"path":"note.txt"}'),
                ToolUseEnd(id="t1", name="FileRead", input={"path": "note.txt"}),
                MessageStop(stop_reason="tool_use"),
            ],
            [TextDelta(text="Done."), MessageStop(stop_reason="end_turn")],
        ]
    )
    orchestrator = _build_orchestrator(workspace, model, registry, echo_sink=[])
    orchestrator.run_turn("Read it")

    # Second model call sees a user message whose content is
    # [tool_result, text(fragment)].
    second_call_messages = model.calls[1]["messages"]
    last_user_content = second_call_messages[-1]["content"]
    assert last_user_content[0]["type"] == "tool_result"
    # The last content block should be our injected fragment.
    assert last_user_content[-1]["type"] == "text"
    assert "Summarise the file content" in last_user_content[-1]["text"]


def test_post_tool_use_fragments_respect_tool_matcher(workspace: Path) -> None:
    (workspace / "note.txt").write_text("hi", encoding="utf-8")

    registry = HookRegistry()
    registry.add(
        HookDefinition(
            event=HookEvent.POST_TOOL_USE,
            matcher="FileEdit",  # not FileRead
            hook_type=HookType.PROMPT,
            prompt="Call out the diff explicitly.",
            id="edit-only",
        )
    )
    model = _RecordingModel(
        [
            [
                ToolUseStart(id="t1", name="FileRead"),
                ToolUseEnd(id="t1", name="FileRead", input={"path": "note.txt"}),
                MessageStop(stop_reason="tool_use"),
            ],
            [TextDelta(text="done"), MessageStop(stop_reason="end_turn")],
        ]
    )
    orchestrator = _build_orchestrator(workspace, model, registry, echo_sink=[])
    orchestrator.run_turn("Read it")

    second_call_messages = model.calls[1]["messages"]
    last_user_content = second_call_messages[-1]["content"]
    # No matching fragment → no trailing text block.
    types = [block.get("type") for block in last_user_content if isinstance(block, dict)]
    assert types == ["tool_result"]


def test_no_prompt_fragments_leaves_system_prompt_unchanged(workspace: Path) -> None:
    registry = HookRegistry()  # empty
    model = _RecordingModel([[TextDelta(text="ok"), MessageStop(stop_reason="end_turn")]])
    orchestrator = _build_orchestrator(workspace, model, registry, echo_sink=[])
    orchestrator.run_turn("Hi")
    assert model.calls[0]["system_prompt"] == "You are helpful."


# ---------------------------------------------------------------------------
# Backwards compatibility — command-type hooks still gate as before
# ---------------------------------------------------------------------------


def test_pre_tool_use_command_hook_still_blocks(workspace: Path) -> None:
    from cli.hooks.registry import HookProcessResult

    registry = HookRegistry(
        runner=lambda hook, payload: HookProcessResult(
            returncode=1, stdout="", stderr="blocked"
        )
    )
    registry.add(
        HookDefinition(
            event=HookEvent.PRE_TOOL_USE,
            matcher="",
            hook_type=HookType.COMMAND,
            command="./forbidden.sh",
        )
    )

    from cli.tools.base import ToolContext
    from cli.tools.executor import execute_tool_call
    from cli.tools.file_edit import FileEditTool
    from cli.workbench_app.permission_dialog import DialogChoice, DialogOutcome

    (workspace / "a.txt").write_text("x", encoding="utf-8")
    tool_registry = ToolRegistry()
    tool_registry.register(FileEditTool())
    permissions = PermissionManager(root=workspace)

    execution = execute_tool_call(
        "FileEdit",
        {"path": "a.txt", "old_string": "x", "new_string": "y"},
        registry=tool_registry,
        permissions=permissions,
        context=ToolContext(workspace_root=workspace),
        dialog_runner=lambda *_a, **_k: DialogOutcome(
            choice=DialogChoice.APPROVE,
            allow=True,
            persist_rule=None,
            persist_scope=None,
        ),
        hook_registry=registry,
    )
    assert execution.decision.value == "deny"
    assert execution.denial_reason == "hook_deny"
