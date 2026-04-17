"""Tests for the per-turn cost-ticker hook in ``_run_orchestrator_turn`` (R7.C.3).

The conversation loop must increment ``WorkbenchSession.cost_ticker_usd``
after every assistant turn. Failures (unknown model, calculator raising,
session writes failing) must NEVER block the user — they are silently
swallowed so the conversation continues.

These tests construct a real ``WorkbenchRuntime`` so the orchestrator and
bridge are wired identically to production, but the model is a scripted
fake and ``run_turn`` is monkeypatched to return a controlled
``OrchestratorResult``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from cli.llm.streaming import MessageStop
from cli.llm.types import OrchestratorResult, TurnMessage
from cli.workbench_app.app import _run_follow_up_turns, _run_orchestrator_turn
from cli.workbench_app.orchestrator_runtime import build_workbench_runtime
from cli.workbench_app.session_state import WorkbenchSession


SONNET = "claude-sonnet-4-5"  # input 3.0 / output 15.0 per 1M


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


def _scripted_result(usage: dict[str, int] | None = None) -> OrchestratorResult:
    return OrchestratorResult(
        assistant_text="hi",
        tool_executions=[],
        stop_reason="end_turn",
        usage=usage if usage is not None else {},
    )


def test_cost_ticker_advances_after_assistant_turn(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn with usage tokens bumps ``cost_ticker_usd`` by the computed delta."""
    session = WorkbenchSession()
    fake = _scripted_result({"input_tokens": 1000, "output_tokens": 500})
    monkeypatch.setattr(runtime.orchestrator, "run_turn", lambda _l: fake)

    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=None,
        line="ping",
        echo=lambda _l: None,
        session=session,
        model_id=SONNET,
    )

    # 1000/1e6*3 + 500/1e6*15 = 0.003 + 0.0075 = 0.0105
    assert session.cost_ticker_usd == pytest.approx(0.0105)


def test_cost_ticker_unchanged_when_no_session(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``session=None`` must not crash — turn completes silently."""
    fake = _scripted_result({"input_tokens": 1000, "output_tokens": 500})
    monkeypatch.setattr(runtime.orchestrator, "run_turn", lambda _l: fake)

    # Should not raise even with no session.
    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=None,
        line="ping",
        echo=lambda _l: None,
        session=None,
        model_id=SONNET,
    )


def test_cost_ticker_unchanged_when_no_model_id(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a model_id, the calculator can't price → ticker stays at 0.0."""
    session = WorkbenchSession()
    fake = _scripted_result({"input_tokens": 1000, "output_tokens": 500})
    monkeypatch.setattr(runtime.orchestrator, "run_turn", lambda _l: fake)

    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=None,
        line="ping",
        echo=lambda _l: None,
        session=session,
        model_id=None,
    )

    assert session.cost_ticker_usd == 0.0


def test_cost_ticker_unchanged_when_unknown_model(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown model → calculator returns 0.0 → ticker stays at 0.0."""
    session = WorkbenchSession()
    fake = _scripted_result({"input_tokens": 1000, "output_tokens": 500})
    monkeypatch.setattr(runtime.orchestrator, "run_turn", lambda _l: fake)

    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=None,
        line="ping",
        echo=lambda _l: None,
        session=session,
        model_id="bogus-model",
    )

    assert session.cost_ticker_usd == 0.0


def test_cost_ticker_does_not_block_on_compute_failure(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising compute_turn_cost must not break the turn; ticker untouched."""
    session = WorkbenchSession()
    session.cost_ticker_usd = 0.42  # prior value to confirm it's preserved
    fake = _scripted_result({"input_tokens": 1000, "output_tokens": 500})
    monkeypatch.setattr(runtime.orchestrator, "run_turn", lambda _l: fake)

    def _boom(*_args: Any, **_kwargs: Any) -> float:
        raise RuntimeError("boom")

    # The cost block does ``from cli.workbench_app.cost_calculator import
    # compute_turn_cost`` inside the try, so patching the module attribute
    # is what the import resolves to.
    monkeypatch.setattr(
        "cli.workbench_app.cost_calculator.compute_turn_cost",
        _boom,
    )

    # Must not raise.
    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=None,
        line="ping",
        echo=lambda _l: None,
        session=session,
        model_id=SONNET,
    )

    assert session.cost_ticker_usd == 0.42


def test_cost_ticker_skips_zero_cost(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn with empty usage must leave the ticker exactly at 0.0."""
    session = WorkbenchSession()
    fake = _scripted_result({})  # no usage data
    monkeypatch.setattr(runtime.orchestrator, "run_turn", lambda _l: fake)

    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=None,
        line="ping",
        echo=lambda _l: None,
        session=session,
        model_id=SONNET,
    )

    assert session.cost_ticker_usd == 0.0


def test_cost_ticker_accumulates_across_turns(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two consecutive turns advance the ticker additively (0 → 0.0105 → 0.021)."""
    session = WorkbenchSession()
    fake = _scripted_result({"input_tokens": 1000, "output_tokens": 500})
    monkeypatch.setattr(runtime.orchestrator, "run_turn", lambda _l: fake)

    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=None,
        line="ping",
        echo=lambda _l: None,
        session=session,
        model_id=SONNET,
    )
    assert session.cost_ticker_usd == pytest.approx(0.0105)

    _run_orchestrator_turn(
        orchestrator=runtime.orchestrator,
        ctx=None,
        line="ping again",
        echo=lambda _l: None,
        session=session,
        model_id=SONNET,
    )
    assert session.cost_ticker_usd == pytest.approx(0.021)


def test_cost_ticker_works_via_followup_turn_path(
    runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_run_follow_up_turns`` also threads session/model_id and ticks."""
    session = WorkbenchSession()
    fake = _scripted_result({"input_tokens": 1000, "output_tokens": 500})
    monkeypatch.setattr(runtime.orchestrator, "run_turn", lambda _l: fake)

    # Build a fake "slash result" that triggers a follow-up prompt.
    class _SlashResult:
        submit_next_input = True
        next_input = "follow-up text"

    _run_follow_up_turns(
        orchestrator=runtime.orchestrator,
        ctx=None,
        result=_SlashResult(),
        echo=lambda _l: None,
        session=session,
        model_id=SONNET,
    )

    assert session.cost_ticker_usd == pytest.approx(0.0105)
