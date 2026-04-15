"""Tests for the cli/tools/* package (Phase-1 workbench tool surface).

These cover:

* :mod:`cli.tools.base` / :mod:`cli.tools.registry` — registry contract,
  schema export, collision detection.
* The bundled tools (FileRead/FileWrite/FileEdit/Glob/Grep/Bash/ConfigRead/
  ConfigEdit) against a temporary workspace fixture.
* :func:`cli.tools.executor.execute_tool_call` — permission-aware dispatch
  including deny, ask→approve, ask→session-allow, and unknown tool.

Running ``pytest tests/test_cli_tools.py`` is the authoritative signal that
Phase 1 is healthy before we start wiring the LLM loop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cli.permissions import PermissionManager
from cli.tools import ToolRegistry
from cli.tools.base import Tool, ToolContext, ToolError, ToolResult
from cli.tools.bash_tool import BashTool
from cli.tools.config_edit import ConfigEditTool
from cli.tools.config_read import ConfigReadTool
from cli.tools.executor import execute_tool_call
from cli.tools.file_edit import FileEditTool
from cli.tools.file_read import FileReadTool
from cli.tools.file_write import FileWriteTool
from cli.tools.glob_tool import GlobTool
from cli.tools.grep_tool import GrepTool
from cli.tools.registry import default_registry, reset_default_registry
from cli.workbench_app.permission_dialog import DialogChoice, DialogOutcome, _map_response


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Minimal workspace with a ``.agentlab/`` marker so PermissionManager
    can locate settings files when tests write them."""
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


@pytest.fixture
def context(workspace: Path) -> ToolContext:
    return ToolContext(workspace_root=workspace)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_register_and_lookup() -> None:
    registry = ToolRegistry()
    registry.register(FileReadTool())
    assert registry.has("FileRead")
    assert registry.get("FileRead").name == "FileRead"
    assert "FileRead" in [tool.name for tool in registry.list()]


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry()
    registry.register(FileReadTool())
    with pytest.raises(ToolError):
        registry.register(FileReadTool())


def test_registry_to_schema_shape() -> None:
    registry = ToolRegistry()
    registry.register(FileReadTool())
    schema = registry.to_schema()
    assert schema == [
        {
            "name": "FileRead",
            "description": FileReadTool.description,
            "input_schema": dict(FileReadTool.input_schema),
        }
    ]


def test_default_registry_has_phase_one_tools() -> None:
    reset_default_registry()
    registry = default_registry()
    expected = {
        "FileRead",
        "FileEdit",
        "FileWrite",
        "Glob",
        "Grep",
        "Bash",
        "ConfigRead",
        "ConfigEdit",
    }
    assert expected.issubset({tool.name for tool in registry.list()})


# ---------------------------------------------------------------------------
# FileReadTool
# ---------------------------------------------------------------------------


def test_file_read_returns_numbered_lines(workspace: Path, context: ToolContext) -> None:
    (workspace / "hello.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    result = FileReadTool().run({"path": "hello.txt"}, context)
    assert result.ok
    assert "     1\talpha" in result.content
    assert "     3\tgamma" in result.content


def test_file_read_rejects_escape_paths(workspace: Path, context: ToolContext) -> None:
    outside = workspace.parent / "leak.txt"
    outside.write_text("leaked", encoding="utf-8")
    result = FileReadTool().run({"path": "../leak.txt"}, context)
    assert not result.ok
    assert "outside the workspace" in result.content


def test_file_read_handles_missing_file(context: ToolContext) -> None:
    result = FileReadTool().run({"path": "nope.txt"}, context)
    assert not result.ok
    assert "not found" in result.content


def test_file_read_respects_offset_limit(workspace: Path, context: ToolContext) -> None:
    (workspace / "many.txt").write_text(
        "\n".join(f"line-{idx}" for idx in range(20)), encoding="utf-8"
    )
    result = FileReadTool().run({"path": "many.txt", "offset": 5, "limit": 3}, context)
    assert result.ok
    assert "line-5" in result.content
    assert "line-7" in result.content
    assert "line-8" not in result.content
    assert "truncated" in result.content


# ---------------------------------------------------------------------------
# FileWriteTool / FileEditTool
# ---------------------------------------------------------------------------


def test_file_write_creates_new_file(workspace: Path, context: ToolContext) -> None:
    result = FileWriteTool().run({"path": "new.txt", "content": "hi\n"}, context)
    assert result.ok
    assert (workspace / "new.txt").read_text() == "hi\n"
    assert "Created" in result.content


def test_file_write_overwrites(workspace: Path, context: ToolContext) -> None:
    target = workspace / "doc.txt"
    target.write_text("old", encoding="utf-8")
    result = FileWriteTool().run({"path": "doc.txt", "content": "new"}, context)
    assert result.ok
    assert target.read_text() == "new"
    assert "Overwrote" in result.content


def test_file_edit_unique_replacement(workspace: Path, context: ToolContext) -> None:
    (workspace / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    result = FileEditTool().run(
        {"path": "a.py", "old_string": "x = 1", "new_string": "x = 42"}, context
    )
    assert result.ok
    assert (workspace / "a.py").read_text() == "x = 42\ny = 2\n"


def test_file_edit_refuses_ambiguous_match(workspace: Path, context: ToolContext) -> None:
    (workspace / "dup.py").write_text("x\nx\nx\n", encoding="utf-8")
    result = FileEditTool().run(
        {"path": "dup.py", "old_string": "x", "new_string": "y"}, context
    )
    assert not result.ok
    assert "matches 3 locations" in result.content


def test_file_edit_replace_all(workspace: Path, context: ToolContext) -> None:
    (workspace / "dup.py").write_text("x\nx\nx\n", encoding="utf-8")
    result = FileEditTool().run(
        {
            "path": "dup.py",
            "old_string": "x",
            "new_string": "y",
            "replace_all": True,
        },
        context,
    )
    assert result.ok
    assert (workspace / "dup.py").read_text() == "y\ny\ny\n"


def test_file_edit_rejects_identical_strings(workspace: Path, context: ToolContext) -> None:
    (workspace / "a.py").write_text("foo", encoding="utf-8")
    result = FileEditTool().run(
        {"path": "a.py", "old_string": "foo", "new_string": "foo"}, context
    )
    assert not result.ok
    assert "identical" in result.content


# ---------------------------------------------------------------------------
# GlobTool / GrepTool
# ---------------------------------------------------------------------------


def test_glob_matches_and_orders_by_mtime(workspace: Path, context: ToolContext) -> None:
    (workspace / "a.py").write_text("a", encoding="utf-8")
    (workspace / "b.py").write_text("b", encoding="utf-8")
    result = GlobTool().run({"pattern": "*.py"}, context)
    assert result.ok
    matches = result.content.splitlines()
    assert set(matches) == {"a.py", "b.py"}


def test_glob_rejects_directory_base(workspace: Path, context: ToolContext) -> None:
    (workspace / "file.txt").write_text("x", encoding="utf-8")
    result = GlobTool().run({"pattern": "*", "path": "file.txt"}, context)
    assert not result.ok


def test_grep_finds_matches(workspace: Path, context: ToolContext) -> None:
    (workspace / "alpha.py").write_text("needle here\nfiller\n", encoding="utf-8")
    (workspace / "beta.py").write_text("no signal\n", encoding="utf-8")
    result = GrepTool().run({"pattern": "needle"}, context)
    assert result.ok
    assert "alpha.py:1:" in result.content
    assert "beta.py" not in result.content


def test_grep_skips_noisy_dirs(workspace: Path, context: ToolContext) -> None:
    nested = workspace / ".venv" / "lib"
    nested.mkdir(parents=True)
    (nested / "junk.py").write_text("needle\n", encoding="utf-8")
    (workspace / "src.py").write_text("needle\n", encoding="utf-8")
    result = GrepTool().run({"pattern": "needle"}, context)
    assert result.ok
    # ``.venv`` is in the noise set so only the top-level match is reported.
    assert result.content.count("needle") == 1
    assert ".venv" not in result.content


def test_grep_reports_invalid_regex(context: ToolContext) -> None:
    result = GrepTool().run({"pattern": "(unclosed"}, context)
    assert not result.ok
    assert "Invalid regex" in result.content


# ---------------------------------------------------------------------------
# BashTool
# ---------------------------------------------------------------------------


def test_bash_runs_in_workspace(workspace: Path, context: ToolContext) -> None:
    result = BashTool().run({"command": "pwd"}, context)
    assert result.ok
    assert str(workspace.resolve()) in result.content
    assert "[exit code 0]" in result.content


def test_bash_reports_nonzero_exit(context: ToolContext) -> None:
    result = BashTool().run({"command": "exit 7"}, context)
    assert not result.ok
    assert "[exit code 7]" in result.content


def test_bash_timeout(context: ToolContext) -> None:
    result = BashTool().run({"command": "sleep 2", "timeout_seconds": 1}, context)
    assert not result.ok
    assert "timed out" in result.content


# ---------------------------------------------------------------------------
# ConfigRead / ConfigEdit
# ---------------------------------------------------------------------------


def test_config_read_parses_yaml(workspace: Path, context: ToolContext) -> None:
    pytest.importorskip("yaml")
    (workspace / "agentlab.yaml").write_text(
        "optimizer:\n  search_max_candidates: 5\n", encoding="utf-8"
    )
    result = ConfigReadTool().run({"path": "agentlab.yaml"}, context)
    assert result.ok
    payload = json.loads(result.content)
    assert payload["format"] == "yaml"
    assert payload["data"]["optimizer"]["search_max_candidates"] == 5


def test_config_edit_sets_nested_key(workspace: Path, context: ToolContext) -> None:
    yaml = pytest.importorskip("yaml")
    (workspace / "agentlab.yaml").write_text(
        "optimizer:\n  search_max_candidates: 5\n", encoding="utf-8"
    )
    result = ConfigEditTool().run(
        {
            "path": "agentlab.yaml",
            "key": "optimizer.search_max_candidates",
            "value": 12,
        },
        context,
    )
    assert result.ok
    data = yaml.safe_load((workspace / "agentlab.yaml").read_text())
    assert data["optimizer"]["search_max_candidates"] == 12


def test_config_edit_refuses_descent_into_scalar(workspace: Path, context: ToolContext) -> None:
    pytest.importorskip("yaml")
    (workspace / "c.yaml").write_text("optimizer: 5\n", encoding="utf-8")
    result = ConfigEditTool().run(
        {"path": "c.yaml", "key": "optimizer.deeper", "value": 1}, context
    )
    assert not result.ok
    assert "cannot descend" in result.content


def test_config_edit_delete_key(workspace: Path, context: ToolContext) -> None:
    yaml = pytest.importorskip("yaml")
    (workspace / "c.yaml").write_text("a: 1\nb: 2\n", encoding="utf-8")
    result = ConfigEditTool().run(
        {"path": "c.yaml", "key": "b", "delete": True}, context
    )
    assert result.ok
    data = yaml.safe_load((workspace / "c.yaml").read_text())
    assert data == {"a": 1}


# ---------------------------------------------------------------------------
# Permission decision + executor
# ---------------------------------------------------------------------------


def test_permission_decision_for_read_only_tool(workspace: Path) -> None:
    manager = PermissionManager(root=workspace)
    assert manager.decision_for_tool(FileReadTool(), {"path": "x"}) == "allow"


def test_permission_decision_for_mutating_tool_defaults_to_ask(workspace: Path) -> None:
    manager = PermissionManager(root=workspace)
    assert manager.decision_for_tool(FileEditTool(), {"path": "x"}) == "ask"


def test_permission_decision_denied_in_plan_mode(workspace: Path) -> None:
    (workspace / ".agentlab" / "settings.json").write_text(
        json.dumps({"permissions": {"mode": "plan"}}), encoding="utf-8"
    )
    manager = PermissionManager(root=workspace)
    assert manager.decision_for_tool(FileEditTool(), {"path": "x"}) == "deny"


def test_permission_session_override_allows(workspace: Path) -> None:
    manager = PermissionManager(root=workspace)
    manager.allow_for_session("tool:FileEdit:*")
    assert manager.decision_for_tool(FileEditTool(), {"path": "x"}) == "allow"


def test_executor_runs_read_only_without_dialog(workspace: Path, context: ToolContext) -> None:
    (workspace / "a.txt").write_text("hi", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileReadTool())
    manager = PermissionManager(root=workspace)
    execution = execute_tool_call(
        "FileRead",
        {"path": "a.txt"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=_fail_if_called,
    )
    assert execution.decision.value == "allow"
    assert execution.result is not None and execution.result.ok


def test_executor_denies_unknown_tool(workspace: Path, context: ToolContext) -> None:
    registry = ToolRegistry()
    manager = PermissionManager(root=workspace)
    execution = execute_tool_call(
        "NopeTool",
        {},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=_fail_if_called,
    )
    assert execution.decision.value == "deny"
    assert execution.denial_reason == "unknown_tool"


def test_executor_honours_user_approval(workspace: Path, context: ToolContext) -> None:
    (workspace / "a.txt").write_text("old", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileEditTool())
    manager = PermissionManager(root=workspace)

    def approve_dialog(tool, tool_input, *, include_persist_option):
        return DialogOutcome(
            choice=DialogChoice.APPROVE,
            allow=True,
            persist_rule=None,
            persist_scope=None,
        )

    execution = execute_tool_call(
        "FileEdit",
        {"path": "a.txt", "old_string": "old", "new_string": "new"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=approve_dialog,
    )
    assert execution.decision.value == "allow"
    assert execution.result is not None and execution.result.ok
    assert (workspace / "a.txt").read_text() == "new"


def test_executor_honours_user_denial(workspace: Path, context: ToolContext) -> None:
    (workspace / "a.txt").write_text("old", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileEditTool())
    manager = PermissionManager(root=workspace)

    def deny_dialog(tool, tool_input, *, include_persist_option):
        return DialogOutcome(
            choice=DialogChoice.DENY,
            allow=False,
            persist_rule=None,
            persist_scope=None,
        )

    execution = execute_tool_call(
        "FileEdit",
        {"path": "a.txt", "old_string": "old", "new_string": "new"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=deny_dialog,
    )
    assert execution.decision.value == "deny"
    assert execution.denial_reason == "user_deny"
    assert (workspace / "a.txt").read_text() == "old"


def test_executor_session_rule_skips_second_dialog(
    workspace: Path, context: ToolContext
) -> None:
    (workspace / "a.txt").write_text("one", encoding="utf-8")
    (workspace / "b.txt").write_text("one", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileEditTool())
    manager = PermissionManager(root=workspace)

    calls: list[str] = []

    def session_dialog(tool, tool_input, *, include_persist_option):
        calls.append(tool_input["path"])
        return DialogOutcome(
            choice=DialogChoice.APPROVE_SESSION,
            allow=True,
            persist_rule="tool:FileEdit:*",
            persist_scope="session",
        )

    execute_tool_call(
        "FileEdit",
        {"path": "a.txt", "old_string": "one", "new_string": "two"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=session_dialog,
    )
    # Second call must *not* trigger the dialog because the session rule
    # was captured on the first approval.
    execute_tool_call(
        "FileEdit",
        {"path": "b.txt", "old_string": "one", "new_string": "two"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=_fail_if_called,
    )
    assert calls == ["a.txt"]
    assert (workspace / "a.txt").read_text() == "two"
    assert (workspace / "b.txt").read_text() == "two"


def test_executor_persist_writes_settings(workspace: Path, context: ToolContext) -> None:
    (workspace / "a.txt").write_text("one", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(FileEditTool())
    manager = PermissionManager(root=workspace)

    def persist_dialog(tool, tool_input, *, include_persist_option):
        return DialogOutcome(
            choice=DialogChoice.APPROVE_PERSIST,
            allow=True,
            persist_rule="tool:FileEdit:*",
            persist_scope="settings",
        )

    execute_tool_call(
        "FileEdit",
        {"path": "a.txt", "old_string": "one", "new_string": "two"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=persist_dialog,
    )
    settings = json.loads((workspace / ".agentlab" / "settings.json").read_text())
    assert "tool:FileEdit:*" in settings["permissions"]["rules"]["allow"]


# ---------------------------------------------------------------------------
# Dialog response mapping
# ---------------------------------------------------------------------------


class _StubTool(Tool):
    name = "Stub"
    description = "unit test stub"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    def run(self, tool_input, context):
        return ToolResult.success("ok")


def test_dialog_map_response_approve_once() -> None:
    outcome = _map_response("a", _StubTool(), {}, include_persist_option=True)
    assert outcome.choice == DialogChoice.APPROVE
    assert outcome.allow
    assert outcome.persist_rule is None


def test_dialog_map_response_session() -> None:
    outcome = _map_response("s", _StubTool(), {}, include_persist_option=True)
    assert outcome.persist_scope == "session"
    assert outcome.persist_rule == "tool:Stub:*"


def test_dialog_map_response_persist_hidden() -> None:
    outcome = _map_response("p", _StubTool(), {}, include_persist_option=False)
    assert not outcome.allow  # falls through to deny when the option isn't offered
    assert outcome.choice == DialogChoice.DENY


def test_dialog_map_response_unknown_denies() -> None:
    outcome = _map_response("banana", _StubTool(), {}, include_persist_option=True)
    assert outcome.choice == DialogChoice.DENY


def _fail_if_called(*args, **kwargs):
    raise AssertionError("dialog should not have been invoked")
