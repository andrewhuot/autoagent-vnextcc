"""Tests for the conversation-aware ``/resume`` slash handler (R7.C.6 part C).

The handler hydrates ``runtime.orchestrator.messages`` from a persisted
conversation and updates ``runtime.workbench_session`` so subsequent
slash commands and the cost ticker stay coherent.

When the slash context has no runtime / conversation_store on
``ctx.meta``, the legacy session-resume handler (in :mod:`slash`) takes
over — preserving every existing test that drives ``/resume`` via a
``SlashContext`` whose ``session_store`` is a :class:`SessionStore`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import pytest

from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.conversation_store import ConversationStore
from cli.workbench_app.resume_slash import build_resume_command
from cli.workbench_app.session_state import WorkbenchSession
from cli.workbench_app.slash import SlashContext, dispatch


@dataclass
class _FakeOrchestrator:
    messages: list[Any] = field(default_factory=list)


@dataclass
class _FakeRuntime:
    orchestrator: _FakeOrchestrator
    conversation_store: ConversationStore
    workbench_session: WorkbenchSession


@pytest.fixture
def registry() -> CommandRegistry:
    """Single-command registry with the conversation-aware /resume only."""
    reg = CommandRegistry()
    reg.register(build_resume_command())
    return reg


def _seed_runtime(tmp_path: Path) -> tuple[_FakeRuntime, str]:
    db = tmp_path / "conv.db"
    store = ConversationStore(db)
    convo = store.create_conversation()
    store.append_message(conversation_id=convo.id, role="user", content="hi")
    store.append_message(
        conversation_id=convo.id, role="assistant", content="hello"
    )
    runtime = _FakeRuntime(
        orchestrator=_FakeOrchestrator(),
        conversation_store=store,
        workbench_session=WorkbenchSession(),
    )
    return runtime, convo.id


def _ctx_for(runtime: _FakeRuntime, registry: CommandRegistry) -> SlashContext:
    ctx = SlashContext(echo=lambda _l: None, registry=registry)
    ctx.meta["workbench_runtime"] = runtime
    return ctx


def test_resume_handler_loads_history_into_orchestrator_messages(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    runtime, convo_id = _seed_runtime(tmp_path)
    ctx = _ctx_for(runtime, registry)

    result = dispatch(ctx, f"/resume {convo_id}")

    assert result.handled
    assert [m.role for m in runtime.orchestrator.messages] == ["user", "assistant"]
    assert [m.content for m in runtime.orchestrator.messages] == ["hi", "hello"]


def test_resume_handler_updates_session_current_conversation_id(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    runtime, convo_id = _seed_runtime(tmp_path)
    ctx = _ctx_for(runtime, registry)

    dispatch(ctx, f"/resume {convo_id}")

    assert runtime.workbench_session.current_conversation_id == convo_id


def test_resume_handler_with_no_id_uses_most_recent(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    runtime, first_id = _seed_runtime(tmp_path)
    # Add a second, newer conversation; bare /resume should grab it.
    second = runtime.conversation_store.create_conversation()
    runtime.conversation_store.append_message(
        conversation_id=second.id, role="user", content="newer"
    )
    ctx = _ctx_for(runtime, registry)

    dispatch(ctx, "/resume")

    assert runtime.workbench_session.current_conversation_id == second.id
    assert second.id != first_id


def test_resume_handler_unknown_id_returns_error_string(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    runtime, _ = _seed_runtime(tmp_path)
    ctx = _ctx_for(runtime, registry)

    result = dispatch(ctx, "/resume conv_nope-missing")

    assert result.handled
    rendered = click.unstyle(result.raw_result or "")
    assert "conv_nope-missing" in rendered
    # Orchestrator messages should NOT have been overwritten on failure.
    assert runtime.orchestrator.messages == []


def test_resume_handler_confirmation_includes_count(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    runtime, convo_id = _seed_runtime(tmp_path)
    ctx = _ctx_for(runtime, registry)

    result = dispatch(ctx, f"/resume {convo_id}")

    rendered = click.unstyle(result.raw_result or "")
    assert convo_id in rendered
    # Two messages were seeded.
    assert "2" in rendered


def test_resume_handler_no_conversations_returns_error(
    tmp_path: Path, registry: CommandRegistry
) -> None:
    db = tmp_path / "conv.db"
    store = ConversationStore(db)
    runtime = _FakeRuntime(
        orchestrator=_FakeOrchestrator(),
        conversation_store=store,
        workbench_session=WorkbenchSession(),
    )
    ctx = _ctx_for(runtime, registry)

    result = dispatch(ctx, "/resume")

    assert result.handled
    rendered = click.unstyle(result.raw_result or "")
    assert "no" in rendered.lower() or "nothing" in rendered.lower()
