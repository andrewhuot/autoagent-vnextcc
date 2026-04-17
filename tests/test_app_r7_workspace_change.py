"""Tests for the R7.C.7 workspace-change observer.

When the active ``current_config_path`` switches mid-conversation from
one non-None value to another, the boot-registered observer emits a
warning suggesting ``/fork`` (and ``/resume <id>`` to keep going).

Switches *to* None (workspace cleared) and the *initial* set from None
must NOT fire — those aren't real switches, they're workspace lifecycle
transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import click

from cli.workbench_app.app import _register_config_change_observer
from cli.workbench_app.session_state import WorkbenchSession


@dataclass
class _FakeRuntime:
    conversation_id: str | None = None


def _drain(out: list[str]) -> str:
    return "\n".join(click.unstyle(line) for line in out)


def test_observer_fires_on_config_path_change_from_one_path_to_another() -> None:
    session = WorkbenchSession()
    session.update(current_config_path="initial.yaml")
    runtime = _FakeRuntime(conversation_id="conv_old")
    out: list[str] = []
    _register_config_change_observer(session, runtime, out.append)

    session.update(current_config_path="new.yaml")

    rendered = _drain(out)
    assert "switched" in rendered.lower()
    assert "initial.yaml" in rendered
    assert "new.yaml" in rendered


def test_observer_does_not_fire_on_initial_set_from_none() -> None:
    session = WorkbenchSession()
    runtime = _FakeRuntime()
    out: list[str] = []
    _register_config_change_observer(session, runtime, out.append)

    session.update(current_config_path="first.yaml")

    assert out == []


def test_observer_does_not_fire_when_set_to_none() -> None:
    session = WorkbenchSession()
    session.update(current_config_path="initial.yaml")
    runtime = _FakeRuntime()
    out: list[str] = []
    _register_config_change_observer(session, runtime, out.append)

    session.update(current_config_path=None)

    assert out == []


def test_observer_does_not_fire_on_no_op_update() -> None:
    session = WorkbenchSession()
    session.update(current_config_path="x.yaml")
    runtime = _FakeRuntime()
    out: list[str] = []
    _register_config_change_observer(session, runtime, out.append)

    # First switch to "y.yaml" — fires once.
    session.update(current_config_path="y.yaml")
    # Re-set to the same value — observer must not fire again.
    session.update(current_config_path="y.yaml")

    assert len(out) == 1


def test_observer_does_not_fire_on_other_field_changes() -> None:
    session = WorkbenchSession()
    session.update(current_config_path="initial.yaml")
    runtime = _FakeRuntime()
    out: list[str] = []
    _register_config_change_observer(session, runtime, out.append)

    session.update(last_eval_run_id="er_x")

    assert out == []


def test_observer_message_includes_resume_hint_when_old_id_known() -> None:
    session = WorkbenchSession()
    session.update(current_config_path="initial.yaml")
    runtime = _FakeRuntime(conversation_id="conv_old")
    out: list[str] = []
    _register_config_change_observer(session, runtime, out.append)

    session.update(current_config_path="new.yaml")

    rendered = _drain(out)
    assert "/resume conv_old" in rendered
    assert "/fork" in rendered
