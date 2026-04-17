"""Tests for the ``/fork`` slash handler (R7.C.7 part B).

The handler creates a new conversation in the SQLite store, swaps the
runtime's ``conversation_id``, rebinds ``conversation_bridge`` to the
new id, resets the orchestrator's message buffer, and writes
``current_conversation_id`` back onto the WorkbenchSession.

The previous conversation must remain intact in the store so users can
resume into it via ``/resume <old_id>`` later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import pytest

from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.conversation_bridge import ConversationBridge
from cli.workbench_app.conversation_store import ConversationStore
from cli.workbench_app.fork_slash import build_fork_command
from cli.workbench_app.session_state import WorkbenchSession
from cli.workbench_app.slash import SlashContext, dispatch


@dataclass
class _FakeOrchestrator:
    messages: list[Any] = field(default_factory=list)


@dataclass
class _FakeRuntime:
    orchestrator: _FakeOrchestrator
    conversation_store: ConversationStore
    conversation_bridge: ConversationBridge
    conversation_id: str
    workbench_session: WorkbenchSession | None
    workspace_root: str | None = None
    model_id: str | None = None


@pytest.fixture
def registry() -> CommandRegistry:
    reg = CommandRegistry()
    reg.register(build_fork_command())
    return reg


def _build_runtime(tmp_path: Path) -> _FakeRuntime:
    db = tmp_path / "conv.db"
    store = ConversationStore(db)
    convo = store.create_conversation(
        workspace_root=str(tmp_path), model="claude-sonnet-4-5"
    )
    store.append_message(conversation_id=convo.id, role="user", content="hi")
    store.append_message(
        conversation_id=convo.id, role="assistant", content="hello"
    )
    session = WorkbenchSession()
    session.update(current_conversation_id=convo.id)
    bridge = ConversationBridge(store=store, conversation_id=convo.id)
    runtime = _FakeRuntime(
        orchestrator=_FakeOrchestrator(messages=[{"role": "user", "content": "hi"}]),
        conversation_store=store,
        conversation_bridge=bridge,
        conversation_id=convo.id,
        workbench_session=session,
        workspace_root=str(tmp_path),
        model_id="claude-sonnet-4-5",
    )
    return runtime


def _ctx_for(runtime: _FakeRuntime | None, registry: CommandRegistry) -> SlashContext:
    ctx = SlashContext(echo=lambda _l: None, registry=registry)
    if runtime is not None:
        ctx.meta["workbench_runtime"] = runtime
    return ctx


def test_fork_creates_new_conversation_in_store(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    runtime = _build_runtime(tmp_path)
    old_id = runtime.conversation_id
    ctx = _ctx_for(runtime, registry)

    result = dispatch(ctx, "/fork")
    assert result.handled

    recent_ids = [c.id for c in runtime.conversation_store.list_recent(limit=10)]
    assert old_id in recent_ids
    # The new id is whatever the runtime now points at.
    assert runtime.conversation_id in recent_ids
    assert runtime.conversation_id != old_id


def test_fork_updates_runtime_conversation_id(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    runtime = _build_runtime(tmp_path)
    old_id = runtime.conversation_id
    ctx = _ctx_for(runtime, registry)

    dispatch(ctx, "/fork")

    assert runtime.conversation_id != old_id
    assert runtime.conversation_id.startswith("conv_")


def test_fork_updates_workbench_session_current_conversation_id(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    runtime = _build_runtime(tmp_path)
    ctx = _ctx_for(runtime, registry)

    dispatch(ctx, "/fork")

    assert (
        runtime.workbench_session.current_conversation_id
        == runtime.conversation_id
    )


def test_fork_resets_orchestrator_messages(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    runtime = _build_runtime(tmp_path)
    assert runtime.orchestrator.messages, "precondition: messages exist"
    ctx = _ctx_for(runtime, registry)

    dispatch(ctx, "/fork")

    assert runtime.orchestrator.messages == []


def test_fork_preserves_old_conversation_in_store(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    runtime = _build_runtime(tmp_path)
    old_id = runtime.conversation_id
    ctx = _ctx_for(runtime, registry)

    dispatch(ctx, "/fork")

    old_convo = runtime.conversation_store.get_conversation(old_id)
    assert old_convo.id == old_id
    assert [m.role for m in old_convo.messages] == ["user", "assistant"]


def test_fork_replaces_conversation_bridge_with_new_id(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    runtime = _build_runtime(tmp_path)
    old_bridge = runtime.conversation_bridge
    ctx = _ctx_for(runtime, registry)

    dispatch(ctx, "/fork")

    new_bridge = runtime.conversation_bridge
    assert new_bridge is not old_bridge
    # Recording on the new bridge should land in the new conversation.
    new_bridge.record_user_turn("post-fork hello")
    refreshed = runtime.conversation_store.get_conversation(
        runtime.conversation_id
    )
    assert any(m.content == "post-fork hello" for m in refreshed.messages)


def test_fork_returns_error_when_no_runtime_in_meta(
    registry: CommandRegistry,
) -> None:
    ctx = _ctx_for(None, registry)

    result = dispatch(ctx, "/fork")

    assert result.handled
    rendered = click.unstyle(result.raw_result or "")
    assert "runtime" in rendered.lower() or "not available" in rendered.lower()
