"""Integration test for the R7 conversation bridge wired into the chat loop.

Validates that ``_run_orchestrator_turn`` records both the user prompt
and the assistant turn into the runtime's :class:`ConversationStore`
when a bridge is supplied. The bridge is opt-in (kwarg defaults to
``None``), so legacy callers without a bundle stay unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from cli.llm.streaming import MessageStop
from cli.llm.types import OrchestratorResult, TurnMessage
from cli.tools.base import PermissionDecision, ToolResult
from cli.tools.executor import ToolExecution
from cli.tools.rendering import StructuredDiffRenderable
from cli.workbench_app.app import _run_orchestrator_turn
from cli.workbench_app.cancellation import CancellationToken
from cli.workbench_app.orchestrator_runtime import build_workbench_runtime
from cli.workbench_app.slash import SlashContext


class _ScriptedModel:
    """Trivial fake — never runs, since we monkeypatch ``run_turn``."""

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[TurnMessage],
        tools: list[dict[str, Any]],
    ) -> Iterator[Any]:
        yield MessageStop(stop_reason="end_turn")


@pytest.fixture
def runtime(tmp_path: Path):
    ws = tmp_path / "myws"
    ws.mkdir()
    (ws / ".agentlab").mkdir()
    return build_workbench_runtime(
        workspace_root=ws,
        model=_ScriptedModel(),
    )


def test_run_orchestrator_turn_with_bridge_records_user_and_assistant(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One ``_run_orchestrator_turn`` call → user + assistant rows."""
    fake = OrchestratorResult(
        assistant_text="hello",
        tool_executions=[],
        stop_reason="end_turn",
    )
    monkeypatch.setattr(
        runtime.orchestrator,
        "run_turn",
        lambda _line: fake,
    )

    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=None,
        line="ping",
        echo=lambda _l: None,
        bridge=runtime.conversation_bridge,
    )

    convo = runtime.conversation_store.get_conversation(runtime.conversation_id)
    assert len(convo.messages) == 2
    assert convo.messages[0].role == "user"
    assert convo.messages[0].content == "ping"
    assert convo.messages[0].position == 0
    assert convo.messages[1].role == "assistant"
    assert convo.messages[1].content == "hello"
    assert convo.messages[1].position == 1


def test_run_orchestrator_turn_without_bridge_is_silent(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy callers (no bundle) leave the conversation_store untouched."""
    fake = OrchestratorResult(
        assistant_text="hi",
        tool_executions=[],
        stop_reason="end_turn",
    )
    monkeypatch.setattr(runtime.orchestrator, "run_turn", lambda _l: fake)

    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=None,
        line="ping",
        echo=lambda _l: None,
        # no bridge kwarg
    )

    convo = runtime.conversation_store.get_conversation(runtime.conversation_id)
    assert convo.messages == []


def test_run_orchestrator_turn_threads_ctx_cancellation_into_orchestrator(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The workbench loop should hand the live Ctrl+C token to the orchestrator."""
    token = CancellationToken()
    observed: dict[str, Any] = {}
    ctx = SlashContext(cancellation=token)
    prior = CancellationToken()
    runtime.orchestrator.tool_cancellation = prior

    fake = OrchestratorResult(
        assistant_text="hello",
        tool_executions=[],
        stop_reason="end_turn",
    )

    def _run(_line: str) -> OrchestratorResult:
        observed["during"] = runtime.orchestrator.tool_cancellation
        return fake

    monkeypatch.setattr(runtime.orchestrator, "run_turn", _run)

    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=ctx,
        line="ping",
        echo=lambda _l: None,
    )

    assert observed["during"] is token
    assert runtime.orchestrator.tool_cancellation is prior


def test_run_orchestrator_turn_skips_blank_cancelled_assistant_rows(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelled turns with no visible output should not persist blank assistants."""
    fake = OrchestratorResult(
        assistant_text="",
        tool_executions=[],
        stop_reason="cancelled",
    )
    monkeypatch.setattr(runtime.orchestrator, "run_turn", lambda _line: fake)

    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=None,
        line="ping",
        echo=lambda _l: None,
        bridge=runtime.conversation_bridge,
    )

    convo = runtime.conversation_store.get_conversation(runtime.conversation_id)
    assert len(convo.messages) == 1
    assert convo.messages[0].role == "user"
    assert convo.messages[0].content == "ping"


def test_run_orchestrator_turn_echoes_tool_display_fallback(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Line-mode workbench should surface readable tool displays."""
    execution = ToolExecution(
        tool_name="FileEdit",
        decision=PermissionDecision.ALLOW,
        result=ToolResult(
            ok=True,
            content="ok",
            display="--- a/demo.py\n+++ b/demo.py\n-hello\n+world\n",
            metadata={
                "renderable": StructuredDiffRenderable(
                    old="hello\n",
                    new="world\n",
                    file_path="demo.py",
                    language="python",
                ).to_payload()
            },
        ),
    )
    fake = OrchestratorResult(
        assistant_text="done",
        tool_executions=[execution],
        stop_reason="end_turn",
    )
    monkeypatch.setattr(runtime.orchestrator, "run_turn", lambda _line: fake)
    echoed: list[str] = []

    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=None,
        line="ping",
        echo=echoed.append,
    )

    assert any("--- a/demo.py" in line for line in echoed)
