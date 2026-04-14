"""Live-streaming REPL rendering for coordinator worker events.

P0-A splits ``CoordinatorSession.process_turn`` into
``plan``/``execute_iter``/``finalize`` so the Workbench REPL can echo each
worker state transition the moment it's produced instead of staying silent
until the full turn finishes. These tests pin that contract:

- the runtime's streaming generator yields events and returns the final
  ``CoordinatorTurnResult`` via ``StopIteration.value``;
- the app's ``_run_agent_turn`` echoes a progress line for each event
  before returning;
- ``EffortIndicator.set_verb`` is called with the role-phase string of
  every worker transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import click

from builder.events import BuilderEvent, BuilderEventType
from cli.workbench_app import run_workbench_app
from cli.workbench_app.coordinator_render import (
    render_progress_line,
    worker_phase_verb,
)
from cli.workbench_app.effort import EffortIndicator


def _make_event(
    event_type: BuilderEventType,
    *,
    worker_role: str = "build_worker",
    timestamp: float = 0.0,
    extra: dict[str, Any] | None = None,
) -> BuilderEvent:
    """Build a minimal synthetic ``BuilderEvent`` for the render path."""
    payload: dict[str, Any] = {"worker_role": worker_role}
    if extra:
        payload.update(extra)
    event = BuilderEvent(
        event_type=event_type,
        session_id="sess-live",
        task_id="task-live",
        payload=payload,
    )
    # ``BuilderEvent.timestamp`` defaults to ``now_ts``; overwrite so the
    # rendered elapsed metadata is deterministic in assertions.
    event.timestamp = timestamp
    return event


@dataclass
class _FakeTurnResult:
    """Minimal stand-in for ``CoordinatorTurnResult`` used by the fake runtime."""

    transcript_lines: tuple[str, ...]
    task_id: str = "task-live"
    plan_id: str = "plan-live"
    run_id: str = "run-live"
    active_tasks: int = 0
    review_cards: tuple[Any, ...] = ()
    project_id: str = "project-live"
    session_id: str = "sess-live"


class _FakeStreamingRuntime:
    """Runtime whose ``stream=True`` call yields 4 synthetic worker events.

    Mirrors the shape that ``WorkbenchAgentRuntime.process_turn`` exposes
    once streaming is wired up: a generator that yields each event and
    returns the final ``CoordinatorTurnResult`` via ``StopIteration.value``.
    """

    def __init__(self) -> None:
        self.stream_calls: list[str] = []
        self.batched_calls: list[str] = []

    def process_turn(
        self,
        message: str,
        *,
        ctx: Any = None,
        command_intent: str | None = None,
        dry_run: bool = False,
        stream: bool = False,
    ):
        if stream and not dry_run:
            self.stream_calls.append(message)
            return self._iter_events(ctx=ctx)
        self.batched_calls.append(message)
        return _FakeTurnResult(
            transcript_lines=(
                "  Coordinator plan plan-live created for 1 worker.",
                "  Next: /eval to test the candidate",
            ),
        )

    def _iter_events(self, *, ctx: Any):
        events = (
            _make_event(
                BuilderEventType.COORDINATOR_EXECUTION_STARTED,
                timestamp=0.0,
                extra={"worker_count": 1},
            ),
            _make_event(
                BuilderEventType.WORKER_GATHERING_CONTEXT,
                timestamp=1.0,
            ),
            _make_event(BuilderEventType.WORKER_ACTING, timestamp=2.0),
            _make_event(
                BuilderEventType.WORKER_COMPLETED,
                timestamp=3.0,
                extra={"summary": "built guardrail"},
            ),
        )
        for event in events:
            yield event
        # Mirror the real runtime — stamp ctx.meta and hand the caller
        # back a materialized result via ``StopIteration.value``.
        if ctx is not None and hasattr(ctx, "meta"):
            ctx.meta["latest_coordinator_run_id"] = "run-live"
        return _FakeTurnResult(
            transcript_lines=(
                "  Coordinator plan plan-live created for 1 worker.",
                "  Next: /eval to test the candidate",
            ),
        )


def test_render_progress_line_uses_claude_style_tree_line() -> None:
    """The live transcript line should use Claude-style tree glyphs, not log prefixes."""
    start = 100.0
    event = _make_event(BuilderEventType.WORKER_ACTING, timestamp=102.0)

    line = render_progress_line(event, start)

    assert line is not None
    plain = click.unstyle(line)
    assert plain.startswith("  ├─ ")
    assert "[2s]" not in plain
    assert "build worker" in plain
    assert "acting" in line


def test_worker_phase_verb_maps_transitions_to_effort_indicator_strings() -> None:
    """Every worker transition should map to a ``role phase`` verb string."""
    transitions = [
        (BuilderEventType.WORKER_GATHERING_CONTEXT, "build worker gathering context"),
        (BuilderEventType.WORKER_ACTING, "build worker acting"),
        (BuilderEventType.WORKER_VERIFYING, "build worker verifying"),
        (BuilderEventType.WORKER_COMPLETED, "build worker completed"),
    ]

    for event_type, expected in transitions:
        event = _make_event(event_type)
        assert worker_phase_verb(event) == expected


def test_streaming_runtime_yields_events_then_returns_final_result() -> None:
    """``process_turn(stream=True)`` must yield events and return the result."""
    runtime = _FakeStreamingRuntime()

    generator = runtime.process_turn("Build it", stream=True)
    events: list[BuilderEvent] = []
    final: Any = None
    while True:
        try:
            events.append(next(generator))
        except StopIteration as stop:
            final = stop.value
            break

    assert [event.event_type for event in events] == [
        BuilderEventType.COORDINATOR_EXECUTION_STARTED,
        BuilderEventType.WORKER_GATHERING_CONTEXT,
        BuilderEventType.WORKER_ACTING,
        BuilderEventType.WORKER_COMPLETED,
    ]
    assert isinstance(final, _FakeTurnResult)
    assert final.run_id == "run-live"


def test_live_worker_events_echo_before_final_result() -> None:
    """Each worker transition should echo a progress line during the turn."""
    runtime = _FakeStreamingRuntime()
    captured: list[str] = []

    def echo(text: str = "") -> None:
        captured.append(text)

    result = run_workbench_app(
        workspace=None,
        input_provider=iter(["Build a support agent", "/exit"]),
        echo=echo,
        show_banner=False,
        agent_runtime=runtime,
    )

    joined = click.unstyle("\n".join(captured))
    assert result.exited_via == "/exit"
    assert runtime.stream_calls == ["Build a support agent"]
    assert runtime.batched_calls == []

    # Progress lines should appear — one per rendered event — using the
    # Claude-style tree glyphs rather than raw elapsed-time log prefixes.
    assert "gathering context" in joined
    assert "acting" in joined
    assert "completed" in joined
    assert any("├─" in click.unstyle(line) or "└─" in click.unstyle(line) for line in captured)
    assert not any("[0s]" in line or "[1s]" in line or "[2s]" in line for line in captured)


def test_live_rendering_drives_effort_indicator_verb_sequence() -> None:
    """``EffortIndicator.set_verb`` must fire for each worker transition."""
    verbs: list[str | None] = []

    class _RecordingIndicator(EffortIndicator):
        def set_verb(self, verb: str | None) -> None:
            verbs.append(verb)
            super().set_verb(verb)

    # Simulate what ``_stream_turn_with_live_echo`` does: walk events,
    # call ``worker_phase_verb``/``set_verb`` for each transition.
    indicator = _RecordingIndicator()
    indicator.start()
    events = [
        _make_event(BuilderEventType.COORDINATOR_EXECUTION_STARTED, timestamp=0.0),
        _make_event(BuilderEventType.WORKER_GATHERING_CONTEXT, timestamp=1.0),
        _make_event(BuilderEventType.WORKER_ACTING, timestamp=2.0),
        _make_event(BuilderEventType.WORKER_COMPLETED, timestamp=3.0),
    ]
    for event in events:
        verb = worker_phase_verb(event)
        if verb is not None:
            indicator.set_verb(verb)
    indicator.stop()

    assert verbs == [
        "coordinator starting",
        "build worker gathering context",
        "build worker acting",
        "build worker completed",
    ]
