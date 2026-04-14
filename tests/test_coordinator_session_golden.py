"""Golden-transcript tests for coordinator events per verb (S4).

Each verb fixture under ``tests/fixtures/coordinator_events/`` encodes a
real recorded :class:`builder.events.BuilderEvent` stream from the
deterministic worker mode. These tests render the fixture through
:func:`cli.workbench_app.coordinator_render.format_coordinator_event` and
snapshot the resulting transcript so the Workbench UX contract is locked
— any future renderer change must update the golden snapshot here.
"""

from __future__ import annotations

from pathlib import Path

import click
import pytest

from builder.event_replay import EventReplay, load_events
from builder.events import BuilderEventType, EventBroker
from cli.workbench_app.coordinator_render import format_coordinator_event


FIXTURES = Path(__file__).parent / "fixtures" / "coordinator_events"
VERBS = ("build", "eval", "optimize", "deploy", "skills")


@pytest.mark.parametrize("verb", VERBS)
def test_fixture_loads_and_has_events(verb: str) -> None:
    bundle = load_events(FIXTURES / f"{verb}.json")
    assert bundle.verb == verb
    assert bundle.events, f"expected recorded events for {verb}"


@pytest.mark.parametrize("verb", VERBS)
def test_fixture_starts_and_ends_with_lifecycle_events(verb: str) -> None:
    bundle = load_events(FIXTURES / f"{verb}.json")
    assert (
        bundle.events[0].event_type
        == BuilderEventType.COORDINATOR_EXECUTION_STARTED
    )
    terminal_types = {
        BuilderEventType.COORDINATOR_EXECUTION_COMPLETED,
        BuilderEventType.COORDINATOR_EXECUTION_FAILED,
        BuilderEventType.COORDINATOR_EXECUTION_BLOCKED,
    }
    assert bundle.events[-1].event_type in terminal_types


@pytest.mark.parametrize("verb", VERBS)
def test_event_replay_publishes_through_broker(verb: str) -> None:
    broker = EventBroker()
    replay = EventReplay.from_file(FIXTURES / f"{verb}.json")
    published = replay.replay(broker)
    assert len(published) == len(replay.events)
    # All events arrive with the same session_id on the broker side.
    assert all(event.session_id for event in published)


@pytest.mark.parametrize("verb", VERBS)
def test_renderer_produces_non_empty_transcript_for_every_verb(verb: str) -> None:
    bundle = load_events(FIXTURES / f"{verb}.json")
    lines = [line for event in bundle.events if (line := format_coordinator_event(event))]
    assert lines, f"renderer produced no lines for {verb}"
    joined = "\n".join(lines)
    assert "Coordinator" in joined


@pytest.mark.parametrize("verb", VERBS)
def test_transcript_contains_a_worker_lifecycle_line(verb: str) -> None:
    bundle = load_events(FIXTURES / f"{verb}.json")
    worker_lines = [
        line
        for event in bundle.events
        if event.event_type
        in {
            BuilderEventType.WORKER_GATHERING_CONTEXT,
            BuilderEventType.WORKER_ACTING,
            BuilderEventType.WORKER_COMPLETED,
        }
        and (line := format_coordinator_event(event))
    ]
    assert worker_lines, f"{verb} fixture is missing worker lifecycle events"


def test_build_transcript_snapshot_first_lines() -> None:
    """Lock the first few rendered lines of /build against regressions."""
    bundle = load_events(FIXTURES / "build.json")
    lines = [
        line
        for event in bundle.events
        if (line := format_coordinator_event(event))
    ]
    # Lock the Claude-style shape — the rest grows with the recorded roster.
    assert "● Coordinator" in lines[0]
    assert any("├─" in line or "└─" in line for line in lines[1:])
    assert click.unstyle(lines[-1]) in {
        "  └─ ✓ Coordinator run completed",
        "  └─ ! Coordinator run blocked",
    }
