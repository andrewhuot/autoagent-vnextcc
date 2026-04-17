"""R7 Slice C.1 tests for :mod:`cli.workbench_app.session_state`.

Additive coverage on top of ``tests/test_workbench_session_state.py``:
``current_conversation_id`` field plus the ``add_observer`` /
``remove_observer`` change-notification hook used by the workspace-change
notice and the ``/resume`` slash command in later C tasks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.workbench_app.session_state import WorkbenchSession


def test_current_conversation_id_defaults_none() -> None:
    s = WorkbenchSession()
    assert s.current_conversation_id is None


def test_current_conversation_id_round_trips_to_disk(tmp_path: Path) -> None:
    path = tmp_path / "ws.json"
    s = WorkbenchSession.load(path)
    s.update(current_conversation_id="conv_xyz")

    reloaded = WorkbenchSession.load(path)
    assert reloaded.current_conversation_id == "conv_xyz"


def test_observer_fires_on_field_change() -> None:
    s = WorkbenchSession()
    observed: list[tuple[str, object]] = []
    s.add_observer(lambda name, value: observed.append((name, value)))

    s.update(current_conversation_id="conv_a")

    assert observed == [("current_conversation_id", "conv_a")]


def test_observer_fires_once_per_changed_field_with_multiple_fields() -> None:
    s = WorkbenchSession()
    observed: list[tuple[str, object]] = []
    s.add_observer(lambda name, value: observed.append((name, value)))

    s.update(current_conversation_id="x", last_eval_run_id="er_y")

    assert set(observed) == {
        ("current_conversation_id", "x"),
        ("last_eval_run_id", "er_y"),
    }


def test_observer_does_not_fire_when_value_unchanged() -> None:
    s = WorkbenchSession()
    observed: list[tuple[str, object]] = []
    s.add_observer(lambda name, value: observed.append((name, value)))

    s.update(current_conversation_id="x")
    s.update(current_conversation_id="x")

    assert observed == [("current_conversation_id", "x")]


def test_observer_does_not_fire_on_increment_cost() -> None:
    s = WorkbenchSession()
    observed: list[tuple[str, object]] = []
    s.add_observer(lambda name, value: observed.append((name, value)))

    s.increment_cost(0.01)

    assert observed == []


def test_remove_observer_stops_callbacks() -> None:
    s = WorkbenchSession()
    observed: list[tuple[str, object]] = []

    def listener(name: str, value: object) -> None:
        observed.append((name, value))

    s.add_observer(listener)
    s.update(current_conversation_id="first")
    assert observed == [("current_conversation_id", "first")]

    s.remove_observer(listener)
    s.update(current_conversation_id="second")
    assert observed == [("current_conversation_id", "first")]


def test_observer_exception_does_not_block_other_observers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    s = WorkbenchSession()
    observed: list[tuple[str, object]] = []

    def boom(name: str, value: object) -> None:
        raise RuntimeError("boom")

    def good(name: str, value: object) -> None:
        observed.append((name, value))

    s.add_observer(boom)
    s.add_observer(good)

    # Must not raise even though the first observer blew up.
    s.update(current_conversation_id="x")

    assert observed == [("current_conversation_id", "x")]


def test_add_observer_idempotent_fires_twice_when_registered_twice() -> None:
    """Bonus: adding the same observer fn twice fires it twice.

    Choice: ``add_observer`` is intentionally NOT deduplicating. The
    list-of-callables pattern matches stdlib ``logging.Logger`` and
    ``tkinter`` bindings — callers that want one-shot registration are
    responsible for tracking that themselves. This keeps the API
    minimal and predictable; no hidden identity check.
    """
    s = WorkbenchSession()
    observed: list[tuple[str, object]] = []

    def listener(name: str, value: object) -> None:
        observed.append((name, value))

    s.add_observer(listener)
    s.add_observer(listener)

    s.update(current_conversation_id="x")

    assert observed == [
        ("current_conversation_id", "x"),
        ("current_conversation_id", "x"),
    ]
