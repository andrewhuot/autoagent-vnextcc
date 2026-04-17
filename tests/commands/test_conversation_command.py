"""Tests for the headless ``agentlab conversation`` CLI (R7 Slice C.5).

The conversation subcommands operate on the workspace's
``.agentlab/conversations.db`` SQLite store. We exercise the Click
group end-to-end via :class:`click.testing.CliRunner` and patch
``runner.discover_workspace`` so each test gets an isolated workspace
rooted at ``tmp_path``.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from cli.commands.conversation import register_conversation_commands
from cli.workbench_app.conversation_store import ConversationStore
from cli.workbench_app.session_state import WorkbenchSession


@dataclass
class _FakeWorkspace:
    root: Path


@pytest.fixture
def workspace(tmp_path: Path) -> _FakeWorkspace:
    """Build a workspace fixture with `.agentlab/` carved out."""
    (tmp_path / ".agentlab").mkdir(parents=True, exist_ok=True)
    return _FakeWorkspace(root=tmp_path)


@pytest.fixture
def store(workspace: _FakeWorkspace) -> ConversationStore:
    return ConversationStore(workspace.root / ".agentlab" / "conversations.db")


@pytest.fixture
def cli(workspace: _FakeWorkspace):
    """Build a fresh top-level Click group with the conversation subcommands."""
    @click.group()
    def _cli() -> None:  # pragma: no cover - top-level group
        pass

    register_conversation_commands(_cli)
    return _cli


@pytest.fixture
def runner(workspace: _FakeWorkspace):
    """A CliRunner with discover_workspace patched to return our fixture."""
    with patch("runner.discover_workspace", return_value=workspace):
        yield CliRunner()


def _seed_conversation(
    store: ConversationStore,
    *,
    model: str = "claude-sonnet-4-5",
    with_tool_call: bool = False,
) -> str:
    conv = store.create_conversation(workspace_root="/tmp/ws", model=model)
    store.append_message(conversation_id=conv.id, role="user", content="hello")
    msg = store.append_message(
        conversation_id=conv.id, role="assistant", content="hi"
    )
    if with_tool_call:
        tc = store.start_tool_call(
            message_id=msg.id,
            tool_name="EvalRun",
            arguments={"suite": "default"},
        )
        store.finish_tool_call(
            tool_call_id=tc.id,
            status="succeeded",
            result={"display": "passed 12/12"},
        )
    return conv.id


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_empty_workspace_returns_zero_lines(cli, runner, store):
    result = runner.invoke(cli, ["conversation", "list"])
    assert result.exit_code == 0, result.output
    # No conversations -> empty body (whitespace allowed for header).
    non_blank = [line for line in result.output.splitlines() if line.strip()]
    assert non_blank == [] or all("conv_" not in line for line in non_blank)


def test_list_after_seeding_one_shows_one_line(cli, runner, store):
    cid = _seed_conversation(store, model="claude-sonnet-4-5")
    result = runner.invoke(cli, ["conversation", "list"])
    assert result.exit_code == 0, result.output
    assert cid in result.output
    assert "claude-sonnet-4-5" in result.output


def test_list_json_output_round_trips(cli, runner, store):
    cid = _seed_conversation(store)
    result = runner.invoke(cli, ["conversation", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == 1
    item = payload[0]
    assert item["id"] == cid
    assert "updated_at" in item
    assert item["model"] == "claude-sonnet-4-5"
    assert "message_count" in item


def test_list_respects_limit(cli, runner, store):
    for _ in range(5):
        _seed_conversation(store)
    result = runner.invoke(cli, ["conversation", "list", "--limit", "3", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) == 3


def test_list_orders_newest_first(cli, runner, store):
    first = _seed_conversation(store)
    time.sleep(0.01)
    second = _seed_conversation(store)
    result = runner.invoke(cli, ["conversation", "list", "--json"])
    payload = json.loads(result.output)
    assert payload[0]["id"] == second
    assert payload[1]["id"] == first


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_show_returns_full_history_text(cli, runner, store):
    cid = _seed_conversation(store)
    result = runner.invoke(cli, ["conversation", "show", cid])
    assert result.exit_code == 0, result.output
    assert "hello" in result.output
    assert "hi" in result.output
    assert cid in result.output


def test_show_returns_full_history_json(cli, runner, store):
    cid = _seed_conversation(store, with_tool_call=True)
    result = runner.invoke(cli, ["conversation", "show", cid, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == cid
    assert len(payload["messages"]) == 2
    assistant = payload["messages"][1]
    assert assistant["role"] == "assistant"
    assert len(assistant["tool_calls"]) == 1
    assert assistant["tool_calls"][0]["tool_name"] == "EvalRun"


def test_show_unknown_id_exits_nonzero(cli, runner, store):
    result = runner.invoke(cli, ["conversation", "show", "conv_nonexistent"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_export_json_round_trips(cli, runner, store):
    cid = _seed_conversation(store, with_tool_call=True)
    result = runner.invoke(cli, ["conversation", "export", cid, "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == cid
    assert len(payload["messages"]) == 2


def test_export_markdown_includes_role_headers(cli, runner, store):
    cid = _seed_conversation(store)
    result = runner.invoke(
        cli, ["conversation", "export", cid, "--format", "markdown"]
    )
    assert result.exit_code == 0, result.output
    assert "## User" in result.output
    assert "## Assistant" in result.output
    assert f"# Conversation {cid}" in result.output


def test_export_markdown_fences_tool_results_with_tool_result_tag(
    cli, runner, store
):
    cid = _seed_conversation(store, with_tool_call=True)
    result = runner.invoke(
        cli, ["conversation", "export", cid, "--format", "markdown"]
    )
    assert result.exit_code == 0, result.output
    assert '<tool_result tool="EvalRun"' in result.output
    assert "</tool_result>" in result.output
    assert 'status="succeeded"' in result.output
    assert "passed 12/12" in result.output


def test_export_unknown_id_exits_nonzero(cli, runner, store):
    result = runner.invoke(cli, ["conversation", "export", "conv_nonexistent"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------------


def test_resume_updates_workbench_session_file(cli, runner, store, workspace):
    cid = _seed_conversation(store)
    result = runner.invoke(cli, ["conversation", "resume", cid])
    assert result.exit_code == 0, result.output
    session_path = workspace.root / ".agentlab" / "workbench_session.json"
    assert session_path.exists()
    session = WorkbenchSession.load(session_path)
    assert session.current_conversation_id == cid


def test_resume_unknown_id_exits_nonzero(cli, runner, store):
    result = runner.invoke(cli, ["conversation", "resume", "conv_nonexistent"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# workspace not found
# ---------------------------------------------------------------------------


def test_command_outside_workspace_exits_nonzero(cli):
    """If discover_workspace returns None, every subcommand should fail
    with a clear message instead of crashing on a missing DB."""
    runner = CliRunner()
    with patch("runner.discover_workspace", return_value=None):
        result = runner.invoke(cli, ["conversation", "list"])
    assert result.exit_code != 0
    assert "workspace" in result.output.lower()
