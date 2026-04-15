"""Tests for Phase-6 polish (themes, output-style, keybindings) and
Phase-7 LLM orchestrator + print mode."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from cli.keybindings import (
    DEFAULT_BINDINGS,
    BindingSet,
    KeyBinding,
    KeyBindingMode,
    load_bindings,
    resolve_bindings,
)
from cli.llm.orchestrator import DEFAULT_MAX_TOOL_LOOPS, LLMOrchestrator
from cli.llm.types import (
    AssistantTextBlock,
    AssistantToolUseBlock,
    ModelResponse,
    OrchestratorResult,
    TurnMessage,
)
from cli.permissions import PermissionManager
from cli.print_mode import EchoModel, PrintResult, run_print
from cli.sessions import Session, SessionStore
from cli.tools.base import Tool, ToolContext, ToolResult
from cli.tools.file_read import FileReadTool
from cli.tools.registry import ToolRegistry
from cli.workbench_app import output_style, theme
from cli.workbench_app.output_style import OutputStyle
from cli.workbench_app.output_style_slash import build_output_style_command
from cli.workbench_app.slash import SlashContext
from cli.workbench_app.theme_slash import build_theme_command


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_output_style() -> None:
    output_style.reset_style()
    yield
    output_style.reset_style()


@pytest.fixture(autouse=True)
def _reset_theme() -> None:
    theme.apply_theme("default")
    yield
    theme.apply_theme("default")


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------


def test_available_themes_lists_default_first() -> None:
    names = theme.available_themes()
    assert names[0] == "default"
    assert "claudelight" in names
    assert "claudedark" in names
    assert "ocean" in names
    assert "nord" in names


def test_get_theme_unknown_raises() -> None:
    with pytest.raises(KeyError):
        theme.get_theme("nope")


def test_apply_theme_switches_palette() -> None:
    theme.apply_theme("claudedark")
    assert theme.current_theme_name() == "claudedark"
    # Roles should now render using the new palette values.
    assert theme.PALETTE.warning == "bright_yellow"


def test_theme_slash_without_args_lists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("cli.settings.USER_CONFIG_DIR", tmp_path)
    monkeypatch.setattr("cli.settings.USER_CONFIG_PATH", tmp_path / "config.json")
    ctx = SlashContext()
    result = build_theme_command().handler(ctx)
    text = _as_text(result)
    assert "claudelight" in text
    assert "ocean" in text


def test_theme_slash_switches_and_persists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("cli.settings.USER_CONFIG_DIR", tmp_path)
    monkeypatch.setattr("cli.settings.USER_CONFIG_PATH", tmp_path / "config.json")
    ctx = SlashContext()
    result = build_theme_command().handler(ctx, "ocean")
    assert "ocean" in _as_text(result)
    assert theme.current_theme_name() == "ocean"
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["theme"]["name"] == "ocean"


def test_theme_slash_unknown_warns() -> None:
    ctx = SlashContext()
    result = build_theme_command().handler(ctx, "midnight")
    assert "Unknown theme" in _as_text(result)


# ---------------------------------------------------------------------------
# Output style
# ---------------------------------------------------------------------------


def test_output_style_default() -> None:
    assert output_style.current_style() is OutputStyle.VERBOSE
    assert output_style.is_verbose() is True


def test_output_style_set_and_query() -> None:
    output_style.set_style("json")
    assert output_style.current_style() is OutputStyle.JSON
    assert output_style.is_machine_readable() is True
    output_style.set_style(OutputStyle.CONCISE)
    assert output_style.is_verbose() is False


def test_output_style_set_unknown_raises() -> None:
    with pytest.raises(ValueError):
        output_style.set_style("rainbow")


def test_output_style_slash_lists_styles() -> None:
    ctx = SlashContext()
    result = build_output_style_command().handler(ctx)
    text = _as_text(result)
    assert "concise" in text
    assert "verbose" in text
    assert "json" in text


def test_output_style_slash_persists_to_workspace(workspace: Path) -> None:
    from dataclasses import dataclass

    @dataclass
    class _Workspace:
        root: Path

    ctx = SlashContext(workspace=_Workspace(root=workspace))
    build_output_style_command().handler(ctx, "concise")
    settings_path = workspace / ".agentlab" / "settings.json"
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["output"]["style"] == "concise"


def test_output_style_slash_unknown_warns() -> None:
    ctx = SlashContext()
    result = build_output_style_command().handler(ctx, "shiny")
    assert "Unknown output style" in _as_text(result)


# ---------------------------------------------------------------------------
# Keybindings
# ---------------------------------------------------------------------------


def test_default_bindings_contain_standard_keys() -> None:
    commands = {binding.command for binding in DEFAULT_BINDINGS}
    assert "submit" in commands
    assert "cancel" in commands
    assert "history-previous" in commands


def test_load_bindings_missing_file_returns_defaults(tmp_path: Path) -> None:
    bindings = load_bindings(tmp_path / "missing.json")
    assert bindings.mode is KeyBindingMode.DEFAULT
    assert all(isinstance(b, KeyBinding) for b in bindings.bindings)


def test_load_bindings_parses_user_overrides(tmp_path: Path) -> None:
    path = tmp_path / "keybindings.json"
    path.write_text(
        json.dumps(
            {
                "mode": "vim",
                "bindings": [
                    {"keys": ["ctrl+k", "ctrl+c"], "command": "clear-transcript"},
                    {"keys": "ctrl+s", "command": "submit", "when": "prompt"},
                ],
            }
        ),
        encoding="utf-8",
    )
    bindings = load_bindings(path)
    assert bindings.mode is KeyBindingMode.VIM
    chord = bindings.lookup(("ctrl+k", "ctrl+c"))
    assert chord is not None
    assert chord.command == "clear-transcript"
    submit = bindings.lookup(("ctrl+s",), when="prompt")
    assert submit is not None
    assert submit.command == "submit"


def test_load_bindings_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "keybindings.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_bindings(path)


def test_load_bindings_rejects_missing_command(tmp_path: Path) -> None:
    path = tmp_path / "keybindings.json"
    path.write_text(
        json.dumps({"bindings": [{"keys": "ctrl+c"}]}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_bindings(path)


def test_resolve_bindings_layers_user_over_defaults() -> None:
    user = (KeyBinding(keys=("enter",), command="custom-submit", when="prompt"),)
    resolved = resolve_bindings(mode=KeyBindingMode.DEFAULT, user_bindings=user)
    found = resolved.lookup(("enter",), when="prompt")
    assert found is not None
    assert found.command == "custom-submit"  # user binding wins via last-wins


# ---------------------------------------------------------------------------
# Phase-7 orchestrator — scripted ModelClient drives the turn loop
# ---------------------------------------------------------------------------


class _ScriptedModel:
    """Test double that returns a queued series of ``ModelResponse`` objects.

    Each ``.complete()`` call pops the next scripted response. Tests use
    this to simulate the pattern "model asks for a tool → orchestrator
    runs it → model emits final text"."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._queue = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, system_prompt, messages, tools):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": [m.to_wire() for m in messages],
                "tools": list(tools),
            }
        )
        if not self._queue:
            return ModelResponse(
                blocks=[AssistantTextBlock(text="…")],
                stop_reason="end_turn",
            )
        return self._queue.pop(0)


def _build_orchestrator(
    workspace: Path,
    model: _ScriptedModel,
    *,
    echo_sink: list[str],
    registry: ToolRegistry | None = None,
) -> LLMOrchestrator:
    session_store = SessionStore(workspace_dir=workspace)
    session = session_store.create(title="orchestrator test")
    permissions = PermissionManager(root=workspace)
    tool_registry = registry or ToolRegistry()
    if registry is None:
        tool_registry.register(FileReadTool())
    return LLMOrchestrator(
        model=model,
        tool_registry=tool_registry,
        permissions=permissions,
        workspace_root=workspace,
        session=session,
        session_store=session_store,
        echo=echo_sink.append,
    )


def test_orchestrator_single_text_turn(workspace: Path) -> None:
    model = _ScriptedModel(
        [
            ModelResponse(
                blocks=[AssistantTextBlock(text="Hello there.")],
                stop_reason="end_turn",
                usage={"input_tokens": 10, "output_tokens": 4},
            )
        ]
    )
    echo_sink: list[str] = []
    orchestrator = _build_orchestrator(workspace, model, echo_sink=echo_sink)
    result = orchestrator.run_turn("Hi!")
    assert result.assistant_text.strip() == "Hello there."
    assert result.stop_reason == "end_turn"
    assert result.tool_executions == []
    assert result.usage == {"input_tokens": 10, "output_tokens": 4}
    assert "Hello there." in "\n".join(echo_sink)
    # Session transcript captured both user and assistant entries.
    assert [e.role for e in orchestrator.session.transcript] == ["user", "assistant"]


def test_orchestrator_runs_tool_and_roundtrips_result(workspace: Path) -> None:
    (workspace / "note.txt").write_text("hello\n", encoding="utf-8")
    model = _ScriptedModel(
        [
            ModelResponse(
                blocks=[
                    AssistantTextBlock(text="I'll read the file."),
                    AssistantToolUseBlock(
                        id="toolu_1",
                        name="FileRead",
                        input={"path": "note.txt"},
                    ),
                ],
                stop_reason="tool_use",
            ),
            ModelResponse(
                blocks=[AssistantTextBlock(text="The file says 'hello'.")],
                stop_reason="end_turn",
            ),
        ]
    )
    echo_sink: list[str] = []
    orchestrator = _build_orchestrator(workspace, model, echo_sink=echo_sink)
    result = orchestrator.run_turn("Summarise note.txt")
    assert len(result.tool_executions) == 1
    assert result.tool_executions[0].tool_name == "FileRead"
    assert "The file says 'hello'." in result.assistant_text
    # Second model call saw the tool_result message.
    second_call_messages = model.calls[1]["messages"]
    assert second_call_messages[-1]["role"] == "user"
    tool_result_block = second_call_messages[-1]["content"][0]
    assert tool_result_block["type"] == "tool_result"
    assert tool_result_block["tool_use_id"] == "toolu_1"
    assert "hello" in tool_result_block["content"]


def test_orchestrator_max_tool_loops_caps_runaway(workspace: Path) -> None:
    infinite_tool_use = ModelResponse(
        blocks=[
            AssistantToolUseBlock(
                id="toolu_loop",
                name="FileRead",
                input={"path": "note.txt"},
            )
        ],
        stop_reason="tool_use",
    )
    (workspace / "note.txt").write_text("x", encoding="utf-8")
    model = _ScriptedModel([infinite_tool_use] * 30)
    echo_sink: list[str] = []
    orchestrator = _build_orchestrator(workspace, model, echo_sink=echo_sink)
    orchestrator.max_tool_loops = 3
    result = orchestrator.run_turn("Go forever")
    assert result.stop_reason == "max_tool_loops"
    assert len(result.tool_executions) == 3


def test_orchestrator_denied_tool_returns_error_block(workspace: Path) -> None:
    class _AlwaysDenyManager(PermissionManager):
        def decision_for_tool(self, tool, tool_input):  # type: ignore[override]
            return "deny"

    model = _ScriptedModel(
        [
            ModelResponse(
                blocks=[
                    AssistantToolUseBlock(
                        id="toolu_x",
                        name="FileRead",
                        input={"path": "x"},
                    )
                ],
                stop_reason="tool_use",
            ),
            ModelResponse(
                blocks=[AssistantTextBlock(text="Aborting.")],
                stop_reason="end_turn",
            ),
        ]
    )
    echo_sink: list[str] = []
    orchestrator = _build_orchestrator(workspace, model, echo_sink=echo_sink)
    orchestrator.permissions = _AlwaysDenyManager(root=workspace)
    result = orchestrator.run_turn("Try it")
    # Tool execution was denied; the model then produced a final text.
    assert len(result.tool_executions) == 1
    assert result.tool_executions[0].decision.value == "deny"
    # The tool_result block the model saw flags is_error=True.
    tool_result = model.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "Permission denied" in tool_result["content"]


def test_orchestrator_aggregates_usage(workspace: Path) -> None:
    model = _ScriptedModel(
        [
            ModelResponse(
                blocks=[AssistantTextBlock(text="one")],
                stop_reason="tool_use",
                usage={"input_tokens": 5, "output_tokens": 1},
            ),
            ModelResponse(
                blocks=[AssistantTextBlock(text="two")],
                stop_reason="end_turn",
                usage={"input_tokens": 7, "output_tokens": 2},
            ),
        ]
    )
    # Second response is an end_turn, so no tool calls happen but the
    # orchestrator still needs to iterate once — adjust by returning a
    # single-shot response that contains no tool_use blocks (first
    # response already triggers termination).
    model = _ScriptedModel(
        [
            ModelResponse(
                blocks=[AssistantTextBlock(text="one")],
                stop_reason="end_turn",
                usage={"input_tokens": 5, "output_tokens": 1},
            )
        ]
    )
    echo_sink: list[str] = []
    orchestrator = _build_orchestrator(workspace, model, echo_sink=echo_sink)
    result = orchestrator.run_turn("Hi")
    assert result.usage == {"input_tokens": 5, "output_tokens": 1}


def test_orchestrator_streams_text_through_renderer(workspace: Path) -> None:
    model = _ScriptedModel(
        [
            ModelResponse(
                blocks=[AssistantTextBlock(text="line one\nline two")],
                stop_reason="end_turn",
            )
        ]
    )
    echo_sink: list[str] = []
    orchestrator = _build_orchestrator(workspace, model, echo_sink=echo_sink)
    orchestrator.run_turn("Write two lines")
    assert "line one" in echo_sink[0]
    assert any("line two" in line for line in echo_sink)


# ---------------------------------------------------------------------------
# Phase-7 print mode
# ---------------------------------------------------------------------------


def test_run_print_concise_echoes_text(workspace: Path) -> None:
    lines: list[str] = []
    result = run_print(
        prompt="hello",
        workspace_root=workspace,
        model_factory=lambda _sp: EchoModel(),
        output_style=OutputStyle.CONCISE,
        echo=lines.append,
    )
    assert isinstance(result, PrintResult)
    assert "echo: hello" in "\n".join(lines)
    assert result.stop_reason == "end_turn"


def test_run_print_json_emits_single_record(workspace: Path) -> None:
    lines: list[str] = []
    run_print(
        prompt="hi",
        workspace_root=workspace,
        model_factory=lambda _sp: EchoModel(),
        output_style=OutputStyle.JSON,
        echo=lines.append,
    )
    body = lines[-1]
    payload = json.loads(body)
    assert payload["stop_reason"] == "end_turn"
    assert "echo: hi" in payload["text"]
    assert payload["tool_calls"] == 0


def test_run_print_empty_prompt_raises(workspace: Path) -> None:
    import click

    with pytest.raises(click.ClickException):
        run_print(
            prompt="   ",
            workspace_root=workspace,
            model_factory=lambda _sp: EchoModel(),
        )


def test_run_print_verbose_adds_footer(workspace: Path) -> None:
    lines: list[str] = []
    run_print(
        prompt="ping",
        workspace_root=workspace,
        model_factory=lambda _sp: EchoModel(),
        output_style=OutputStyle.VERBOSE,
        echo=lines.append,
    )
    combined = "\n".join(lines)
    assert "echo: ping" in combined
    assert "stop_reason=end_turn" in combined


def test_run_print_dialog_denies_interactive_approvals(workspace: Path) -> None:
    # Scripted model that requests a tool; the deny_dialog configured by
    # run_print should block it so tool_calls stays at 0.
    (workspace / "a.txt").write_text("x", encoding="utf-8")

    from cli.llm.types import AssistantToolUseBlock

    class _ToolThenText:
        def __init__(self):
            self._turn = 0

        def complete(self, *, system_prompt, messages, tools):
            del system_prompt, tools
            self._turn += 1
            if self._turn == 1:
                return ModelResponse(
                    blocks=[
                        AssistantToolUseBlock(
                            id="toolu_1",
                            name="FileEdit",
                            input={
                                "path": "a.txt",
                                "old_string": "x",
                                "new_string": "y",
                            },
                        )
                    ],
                    stop_reason="tool_use",
                )
            return ModelResponse(
                blocks=[AssistantTextBlock(text="done")],
                stop_reason="end_turn",
            )

    lines: list[str] = []
    result = run_print(
        prompt="edit it",
        workspace_root=workspace,
        model_factory=lambda _sp: _ToolThenText(),
        output_style=OutputStyle.CONCISE,
        echo=lines.append,
    )
    assert result.tool_calls == 1
    # FileEdit was denied by the headless dialog, so the file is unchanged.
    assert (workspace / "a.txt").read_text() == "x"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if hasattr(result, "result"):
        return str(result.result or "")
    return str(result)
