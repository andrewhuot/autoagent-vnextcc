"""Tests for CoordinatorSession multi-turn dialog memory (P0-D)."""

from __future__ import annotations

from pathlib import Path

from builder.events import EventBroker
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from cli.workbench_app.coordinator_session import CoordinatorSession


class _SpyOrchestrator:
    """Thin wrapper around BuilderOrchestrator that records plan_work kwargs."""

    def __init__(self, inner: BuilderOrchestrator) -> None:
        self._inner = inner
        self.plan_calls: list[dict] = []

    def __getattr__(self, name):  # delegate everything else
        return getattr(self._inner, name)

    def plan_work(self, **kwargs):
        self.plan_calls.append({k: v for k, v in kwargs.items()})
        return self._inner.plan_work(**kwargs)


def _make_session(tmp_path: Path) -> tuple[CoordinatorSession, _SpyOrchestrator]:
    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    spy = _SpyOrchestrator(BuilderOrchestrator(store=store))
    session = CoordinatorSession(
        store=store,
        orchestrator=spy,
        events=EventBroker(),
    )
    return session, spy


def test_process_turn_carries_prior_turns_into_next_plan(tmp_path: Path) -> None:
    """Second turn's plan must receive prior_turns with the first turn's run info."""
    session, spy = _make_session(tmp_path)

    first = session.process_turn("Build a support agent", command_intent="build")
    session.process_turn("Evaluate the support agent", command_intent="eval")

    assert len(spy.plan_calls) == 2
    first_context = spy.plan_calls[0]["extra_context"]
    second_context = spy.plan_calls[1]["extra_context"]

    # First call sees no prior turns; second call sees the first turn.
    assert first_context["prior_turns"] == []
    assert len(second_context["prior_turns"]) == 1
    first_entry = second_context["prior_turns"][0]
    assert first_entry["intent"] == "build"
    assert first_entry["goal"] == "Build a support agent"
    assert first_entry["run_id"] == first.run_id
    assert first_entry["status"] == first.status
    assert first_entry["plan_id"] == first.plan_id
    assert first_entry.get("created_at") is not None
    assert "worker_summaries" in first_entry
    assert second_context["latest_synthesis"]["status"] == "completed"


def test_turn_history_capped_at_max_turn_history(tmp_path: Path) -> None:
    """Running more than MAX_TURN_HISTORY turns must drop the oldest."""
    session, _ = _make_session(tmp_path)
    assert CoordinatorSession.MAX_TURN_HISTORY == 5

    run_ids: list[str] = []
    for index in range(6):
        result = session.process_turn(
            f"Build variant {index}",
            command_intent="build",
        )
        run_ids.append(result.run_id)

    assert len(session._turn_history) == CoordinatorSession.MAX_TURN_HISTORY
    history_run_ids = [entry["run_id"] for entry in session._turn_history]
    # Oldest (first) dropped, last 5 retained in order.
    assert history_run_ids == run_ids[1:]


def test_build_session_context_returns_stable_schema(tmp_path: Path) -> None:
    """_build_session_context must always return both keys with expected types."""
    session, _ = _make_session(tmp_path)

    empty_ctx = session._build_session_context()
    assert set(empty_ctx.keys()) == {"prior_turns", "latest_synthesis"}
    assert empty_ctx["prior_turns"] == []
    assert empty_ctx["latest_synthesis"] == {}

    session.process_turn("Build a support agent", command_intent="build")

    populated = session._build_session_context()
    assert set(populated.keys()) == {"prior_turns", "latest_synthesis"}
    assert isinstance(populated["prior_turns"], list)
    assert len(populated["prior_turns"]) == 1
    assert isinstance(populated["latest_synthesis"], dict)
    assert populated["latest_synthesis"].get("status") == "completed"


def test_trim_worker_summary_caps_length_and_sentences() -> None:
    """_trim_worker_summary must bound to 3 sentences or 280 chars."""
    long_sentence = "x" * 400
    trimmed = CoordinatorSession._trim_worker_summary(long_sentence)
    assert len(trimmed) <= 280
    assert trimmed.endswith("...")

    multi = "One. Two. Three. Four. Five."
    trimmed_multi = CoordinatorSession._trim_worker_summary(multi)
    assert "Four" not in trimmed_multi
    assert "Three" in trimmed_multi
