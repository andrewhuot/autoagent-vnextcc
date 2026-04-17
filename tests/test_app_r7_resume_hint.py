"""Tests for the R7.C.6 boot-time resume hint.

When ``run_workbench_app`` starts and there is a previous conversation
with interrupted tool calls, a one-line dim hint should appear in the
banner area pointing the user at ``/resume <id>``. A clean conversation
or a brand-new workspace must NOT render a hint — silence is golden
when nothing is broken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click

from cli.workbench_app.app import run_workbench_app
from cli.workbench_app.conversation_store import ConversationStore
from cli.workbench_app.session_state import WorkbenchSession


@dataclass
class _FakeOrchestrator:
    messages: list[Any] = field(default_factory=list)


@dataclass
class _FakeRuntime:
    """Mimics the public surface ``_resolve_orchestrator`` reads."""

    orchestrator: _FakeOrchestrator
    conversation_store: ConversationStore
    workbench_session: WorkbenchSession | None = None

    def run_turn(self, line: str) -> Any:  # pragma: no cover — never called in these tests
        raise NotImplementedError


def _drain_lines(out: list[str]) -> str:
    return "\n".join(click.unstyle(line) for line in out)


def _seed_interrupted_conversation(db_path: Path) -> str:
    """Seed an interrupted conversation; return its id."""
    store = ConversationStore(db_path)
    convo = store.create_conversation()
    msg = store.append_message(
        conversation_id=convo.id, role="assistant", content="working"
    )
    store.start_tool_call(message_id=msg.id, tool_name="Bash", arguments={})
    # Reopen — flips pending → interrupted on the now-orphaned tool call.
    ConversationStore(db_path)
    return convo.id


def _build_runtime(db_path: Path) -> _FakeRuntime:
    return _FakeRuntime(
        orchestrator=_FakeOrchestrator(),
        conversation_store=ConversationStore(db_path),
        workbench_session=WorkbenchSession(),
    )


def test_resume_hint_echoed_when_interrupted_calls_present(tmp_path: Path) -> None:
    db = tmp_path / "conv.db"
    convo_id = _seed_interrupted_conversation(db)
    runtime = _build_runtime(db)

    out: list[str] = []
    run_workbench_app(
        workspace=None,
        input_provider=iter([]),  # EOF immediately
        echo=out.append,
        show_banner=True,
        orchestrator=runtime,
    )

    rendered = _drain_lines(out)
    assert convo_id in rendered
    assert "/resume" in rendered
    assert "interrupted" in rendered.lower() or "pending" in rendered.lower()


def test_no_resume_hint_when_clean_history(tmp_path: Path) -> None:
    db = tmp_path / "conv.db"
    store = ConversationStore(db)
    convo = store.create_conversation()
    msg = store.append_message(
        conversation_id=convo.id, role="assistant", content=""
    )
    tc = store.start_tool_call(message_id=msg.id, tool_name="Bash", arguments={})
    store.finish_tool_call(tool_call_id=tc.id, status="succeeded", result=None)

    runtime = _build_runtime(db)

    out: list[str] = []
    run_workbench_app(
        workspace=None,
        input_provider=iter([]),
        echo=out.append,
        show_banner=True,
        orchestrator=runtime,
    )

    rendered = _drain_lines(out)
    assert "interrupted" not in rendered.lower()
    assert "pending tool call" not in rendered.lower()


def test_no_resume_hint_when_no_conversations_at_all(tmp_path: Path) -> None:
    db = tmp_path / "conv.db"
    # Create a fresh store but no conversations.
    ConversationStore(db)
    runtime = _build_runtime(db)

    out: list[str] = []
    run_workbench_app(
        workspace=None,
        input_provider=iter([]),
        echo=out.append,
        show_banner=True,
        orchestrator=runtime,
    )

    rendered = _drain_lines(out)
    assert "interrupted" not in rendered.lower()
    assert "pending tool call" not in rendered.lower()
