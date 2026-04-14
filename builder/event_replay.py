"""Coordinator event replay helpers.

Recorded :class:`builder.events.BuilderEvent` streams are the UX contract
for the Workbench coordinator. This module offers two capabilities:

1. **Record** — serialise a tuple of events to a stable JSON envelope
   (:func:`dump_events`) that can be diffed in version control.
2. **Replay** — load a recorded stream (:func:`load_events`) and push it
   through an :class:`EventBroker` so UI tests can exercise the renderer
   without running a real coordinator.

Fixtures live under ``tests/fixtures/coordinator_events/`` and are
produced by :func:`record_fixture` from the deterministic worker mode, so
rerunning the recorder on master must emit byte-identical JSON.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from builder.events import BuilderEvent, BuilderEventType, EventBroker


FIXTURE_SCHEMA_VERSION = 1
"""Bump when the fixture JSON envelope changes incompatibly."""


@dataclass(frozen=True)
class RecordedEventBundle:
    """Header + event list loaded from disk."""

    verb: str
    schema_version: int
    events: tuple[BuilderEvent, ...]


def dump_events(verb: str, events: Sequence[BuilderEvent]) -> str:
    """Serialise ``events`` to the canonical fixture JSON string.

    The envelope includes the verb label and schema version so CI can
    detect stale fixtures and refuse to load them on a mismatch.
    """
    payload = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "verb": verb,
        "events": [
            {
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "session_id": event.session_id,
                "task_id": event.task_id,
                "timestamp": event.timestamp,
                "payload": event.payload,
            }
            for event in events
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


def load_events(path: Path | str) -> RecordedEventBundle:
    """Load a fixture file produced by :func:`dump_events`."""
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    schema = int(data.get("schema_version", 0))
    if schema != FIXTURE_SCHEMA_VERSION:
        raise ValueError(
            f"Fixture schema {schema} does not match expected "
            f"{FIXTURE_SCHEMA_VERSION} for {path}"
        )
    verb = str(data.get("verb") or "unknown")
    events = tuple(
        BuilderEvent(
            event_id=str(entry["event_id"]),
            event_type=BuilderEventType(entry["event_type"]),
            session_id=str(entry.get("session_id") or ""),
            task_id=(
                str(entry["task_id"]) if entry.get("task_id") is not None else None
            ),
            timestamp=float(entry.get("timestamp") or 0.0),
            payload=dict(entry.get("payload") or {}),
        )
        for entry in data.get("events") or []
    )
    return RecordedEventBundle(verb=verb, schema_version=schema, events=events)


class EventReplay:
    """Replay a recorded event stream into an :class:`EventBroker`.

    The broker's public publish signature reassigns a new ``event_id`` and
    timestamp, so replay cannot be byte-identical to the original run.
    That's by design — callers that need hash stability should consume
    :meth:`events` directly and feed them to a renderer that does not care
    about identifiers.
    """

    def __init__(self, bundle: RecordedEventBundle) -> None:
        self._bundle = bundle

    @classmethod
    def from_file(cls, path: Path | str) -> "EventReplay":
        return cls(load_events(path))

    @property
    def verb(self) -> str:
        return self._bundle.verb

    @property
    def events(self) -> tuple[BuilderEvent, ...]:
        return self._bundle.events

    def replay(self, broker: EventBroker) -> tuple[BuilderEvent, ...]:
        """Push the recorded events through ``broker`` and return the new tuple."""
        published: list[BuilderEvent] = []
        for event in self._bundle.events:
            new_event = broker.publish(
                event_type=event.event_type,
                session_id=event.session_id,
                task_id=event.task_id,
                payload=dict(event.payload),
            )
            published.append(new_event)
        return tuple(published)


def record_fixture(
    verb: str,
    events: Iterable[BuilderEvent],
    output_path: Path | str,
) -> Path:
    """Write ``events`` to ``output_path`` in fixture format.

    Returns the resolved path for convenience so the recorder script can
    print it to stdout. Parent directories are created automatically.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_events(verb, tuple(events)), encoding="utf-8")
    return path


def normalize_events(
    events: Sequence[BuilderEvent],
    *,
    session_id: str = "fixture-session",
    task_id: str = "fixture-task",
    base_timestamp: float = 1_700_000_000.0,
) -> tuple[BuilderEvent, ...]:
    """Return events with stable ids, session, task, and timestamps.

    Fixture files are diffable and stored in git; we want the recorder to
    produce byte-identical output on repeated runs. This helper strips
    every non-deterministic field so recordings are reproducible.
    """
    normalized: list[BuilderEvent] = []
    for index, event in enumerate(events):
        normalized.append(
            BuilderEvent(
                event_id=f"evt-{index:04d}",
                event_type=event.event_type,
                session_id=session_id,
                task_id=task_id,
                timestamp=base_timestamp + index,
                payload=_scrub_payload(event.payload),
            )
        )
    return tuple(normalized)


def _scrub_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace runtime-specific identifiers in event payloads.

    The coordinator embeds run and worker ids in event payloads so the SSE
    stream can correlate events to their owning run. Those ids are random
    per execution and would flip the fixture on every re-record. We
    replace them with stable placeholders keyed on first-seen order.
    """
    stable: dict[str, Any] = {}
    id_map: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, str) and _looks_like_identifier(key):
            mapped = id_map.setdefault(value, f"{key}-{len(id_map):04d}")
            stable[key] = mapped
        else:
            stable[key] = value
    return stable


def _looks_like_identifier(key: str) -> bool:
    """Return ``True`` for payload keys whose values are runtime ids."""
    return key in {
        "run_id",
        "node_id",
        "plan_id",
        "task_id",
        "session_id",
        "worker_run_id",
    } or key.endswith("_id")


__all__ = [
    "EventReplay",
    "FIXTURE_SCHEMA_VERSION",
    "RecordedEventBundle",
    "dump_events",
    "load_events",
    "normalize_events",
    "record_fixture",
]
