"""Tests for ``cli.commands.improve.run_improve_*_in_process`` (R4.5).

Exercises the extracted pure business-logic functions shared by the Click
wrappers (``agentlab improve <sub>``) and the ``/improve`` slash handler.
The subprocess path is replaced by in-process calls that fire an
``on_event`` callback for every event the improve subcommand would
normally emit. Every function emits a terminal ``improve_<sub>_complete``
event the slash handler keys session updates off.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@dataclass
class FakeAttempt:
    attempt_id: str
    status: str = "accepted"
    change_description: str = "tighten prompt"
    config_section: str = "prompt"
    score_before: float = 0.80
    score_after: float = 0.85
    timestamp: float = 0.0
    config_diff: str = "+foo\n-bar"
    health_context: str = "{}"
    patch_bundle: str = ""


@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    memory_db = tmp_path / "optimizer_memory.db"
    lineage_db = tmp_path / "improvement_lineage.db"
    monkeypatch.setenv("AGENTLAB_MEMORY_DB", str(memory_db))
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(lineage_db))
    return memory_db, lineage_db


# ---------------------------------------------------------------------------
# run / accept / measure / diff / lineage / list / show
# ---------------------------------------------------------------------------


def test_run_improve_list_in_process_returns_attempts(isolated_stores) -> None:
    from cli.commands.improve import run_improve_list_in_process

    events: list[dict[str, Any]] = []
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4")],
    ), patch("optimizer.memory.OptimizationMemory") as mem, \
         patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin:
        mem.return_value.get_all.return_value = [FakeAttempt("a1b2c3d4")]
        lin.return_value.events_for.return_value = []
        result = run_improve_list_in_process(
            on_event=events.append,
        )

    assert result.status == "ok"
    assert len(result.attempts) == 1
    assert result.attempts[0]["attempt_id"] == "a1b2c3d4"
    # Terminal event must be last and named improve_list_complete.
    assert events[-1]["event"] == "improve_list_complete"
    assert events[-1]["status"] == "ok"


def test_run_improve_show_in_process_returns_attempt(isolated_stores) -> None:
    from cli.commands.improve import run_improve_show_in_process

    events: list[dict[str, Any]] = []
    fake = FakeAttempt("a1b2c3d4")
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch("optimizer.memory.OptimizationMemory") as mem, \
         patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin:
        mem.return_value.get_all.return_value = [fake]
        lin.return_value.events_for.return_value = []
        result = run_improve_show_in_process(
            attempt_id="a1b2c3",
            on_event=events.append,
        )

    assert result.status == "ok"
    assert result.attempt_id == "a1b2c3d4"
    assert result.attempt is not None
    assert result.attempt["attempt_id"] == "a1b2c3d4"
    assert events[-1]["event"] == "improve_show_complete"
    assert events[-1]["attempt_id"] == "a1b2c3d4"


def test_run_improve_diff_in_process_returns_diff_text(isolated_stores) -> None:
    from cli.commands.improve import run_improve_diff_in_process

    events: list[dict[str, Any]] = []
    fake = FakeAttempt("a1b2c3d4", config_diff="+added\n-removed")
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ):
        result = run_improve_diff_in_process(
            attempt_id="a1b2c3",
            on_event=events.append,
        )

    assert result.status == "ok"
    assert result.attempt_id == "a1b2c3d4"
    assert result.diff_text == "+added\n-removed"
    assert events[-1]["event"] == "improve_diff_complete"
    assert events[-1]["attempt_id"] == "a1b2c3d4"


def test_run_improve_lineage_in_process_returns_nodes(isolated_stores) -> None:
    from cli.commands.improve import run_improve_lineage_in_process

    events: list[dict[str, Any]] = []
    fake = FakeAttempt("a1b2c3d4")

    class _FakeView:
        attempt_id = "a1b2c3d4"
        status = "accepted"
        eval_run_id = "er_xxx"
        deployment_id = "d1"
        deployed_version = 3
        measurement_id = None
        composite_delta = None
        score_before = 0.80
        score_after = 0.85
        parent_attempt_id = None
        rejection_reason = None
        rejection_detail = None
        rolled_back = False
        events: list = []

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin:
        lin.return_value.view_attempt.return_value = _FakeView()
        result = run_improve_lineage_in_process(
            attempt_id="a1b2c3",
            on_event=events.append,
        )

    assert result.status == "ok"
    assert result.attempt_id == "a1b2c3d4"
    assert isinstance(result.nodes, tuple)
    assert events[-1]["event"] == "improve_lineage_complete"
    assert events[-1]["attempt_id"] == "a1b2c3d4"


def test_run_improve_accept_in_process_emits_terminal_event(isolated_stores) -> None:
    from cli.commands.improve import run_improve_accept_in_process

    events: list[dict[str, Any]] = []
    fake = FakeAttempt("a1b2c3d4")

    class _View1:
        deployment_id = None
        deployed_version = None

    class _View2:
        deployment_id = "dep_1"
        deployed_version = 5

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin:
        # view_attempt called twice: once before, once after deploy.
        lin.return_value.view_attempt.side_effect = [_View1(), _View2()]
        lin.return_value.record_measurement.return_value = None

        def fake_deploy(
            *,
            attempt_id: str,
            strategy: str,
            config_version: int | None = None,
        ) -> None:
            return None

        result = run_improve_accept_in_process(
            attempt_id="a1b2c3",
            strategy="canary",
            on_event=events.append,
            deploy_invoker=fake_deploy,
        )

    assert result.status == "ok"
    assert result.attempt_id == "a1b2c3d4"
    assert result.deployment_id == "dep_1"
    assert events[-1]["event"] == "improve_accept_complete"
    assert events[-1]["deployment_id"] == "dep_1"
    assert events[-1]["attempt_id"] == "a1b2c3d4"


def test_run_improve_accept_in_process_already_deployed(isolated_stores) -> None:
    from cli.commands.improve import run_improve_accept_in_process

    events: list[dict[str, Any]] = []
    fake = FakeAttempt("a1b2c3d4")

    class _AlreadyDeployed:
        deployment_id = "dep_existing"
        deployed_version = 2

    called = {"count": 0}

    def fake_deploy(
        *,
        attempt_id: str,
        strategy: str,
        config_version: int | None = None,
    ) -> None:
        called["count"] += 1

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin:
        lin.return_value.view_attempt.return_value = _AlreadyDeployed()
        result = run_improve_accept_in_process(
            attempt_id="a1b2c3",
            strategy="canary",
            on_event=events.append,
            deploy_invoker=fake_deploy,
        )

    assert result.already_deployed is True
    assert called["count"] == 0  # deploy not re-invoked
    assert events[-1]["event"] == "improve_accept_complete"


def test_run_improve_measure_in_process_emits_terminal_event(isolated_stores) -> None:
    from cli.commands.improve import run_improve_measure_in_process

    events: list[dict[str, Any]] = []
    fake = FakeAttempt("a1b2c3d4", score_before=0.80)

    class _DeployedView:
        deployment_id = "dep_1"

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin, \
         patch("cli.commands.improve._run_post_deploy_eval", return_value=0.85):
        lin.return_value.view_attempt.return_value = _DeployedView()
        lin.return_value.record_measurement.return_value = None
        result = run_improve_measure_in_process(
            attempt_id="a1b2c3",
            on_event=events.append,
        )

    assert result.status == "ok"
    assert result.post_composite == 0.85
    assert result.composite_delta is not None
    assert abs(result.composite_delta - 0.05) < 1e-9
    assert events[-1]["event"] == "improve_measure_complete"
    assert events[-1]["attempt_id"] == "a1b2c3d4"


def test_run_improve_measure_in_process_raises_when_not_deployed(
    isolated_stores,
) -> None:
    from cli.commands.improve import (
        ImproveCommandError, run_improve_measure_in_process,
    )

    events: list[dict[str, Any]] = []
    fake = FakeAttempt("a1b2c3d4")

    class _UndeployedView:
        deployment_id = None

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin:
        lin.return_value.view_attempt.return_value = _UndeployedView()
        with pytest.raises(ImproveCommandError):
            run_improve_measure_in_process(
                attempt_id="a1b2c3",
                on_event=events.append,
            )
    # Terminal event must still fire before raise.
    assert any(e["event"] == "improve_measure_complete" for e in events)
    assert events[-1]["status"] == "failed"


def test_run_improve_run_in_process_emits_failure_when_config_cannot_be_resolved() -> None:
    from cli.commands.improve import (
        ImproveCommandError, run_improve_run_in_process,
    )

    events: list[dict[str, Any]] = []
    with patch(
        "cli.commands.improve._resolve_improve_run_config_path",
        side_effect=ImproveCommandError("missing config"),
    ), pytest.raises(ImproveCommandError):
        run_improve_run_in_process(config_path=None, on_event=events.append)
    # Terminal event must be emitted with status=failed before the raise.
    assert any(e["event"] == "improve_run_complete" for e in events)
    assert events[-1]["status"] == "failed"


# ---------------------------------------------------------------------------
# No subprocess spawned (parametrised over all 7 subcommands)
# ---------------------------------------------------------------------------


def test_list_never_calls_subprocess_popen(
    isolated_stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cli.commands.improve import run_improve_list_in_process

    sentinel = MagicMock(side_effect=AssertionError("subprocess spawned!"))
    monkeypatch.setattr(subprocess, "Popen", sentinel)

    with patch("optimizer.memory.OptimizationMemory") as mem, \
         patch("optimizer.improvement_lineage.ImprovementLineageStore"):
        mem.return_value.get_all.return_value = []
        run_improve_list_in_process(on_event=lambda _: None)
    sentinel.assert_not_called()


def test_show_never_calls_subprocess_popen(
    isolated_stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cli.commands.improve import run_improve_show_in_process

    sentinel = MagicMock(side_effect=AssertionError("subprocess spawned!"))
    monkeypatch.setattr(subprocess, "Popen", sentinel)
    fake = FakeAttempt("a1b2c3d4")

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch("optimizer.memory.OptimizationMemory") as mem, \
         patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin:
        mem.return_value.get_all.return_value = [fake]
        lin.return_value.events_for.return_value = []
        run_improve_show_in_process(attempt_id="a1b2", on_event=lambda _: None)
    sentinel.assert_not_called()


def test_diff_never_calls_subprocess_popen(
    isolated_stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cli.commands.improve import run_improve_diff_in_process

    sentinel = MagicMock(side_effect=AssertionError("subprocess spawned!"))
    monkeypatch.setattr(subprocess, "Popen", sentinel)
    fake = FakeAttempt("a1b2c3d4")
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ):
        run_improve_diff_in_process(attempt_id="a1b2", on_event=lambda _: None)
    sentinel.assert_not_called()


def test_lineage_never_calls_subprocess_popen(
    isolated_stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cli.commands.improve import run_improve_lineage_in_process

    sentinel = MagicMock(side_effect=AssertionError("subprocess spawned!"))
    monkeypatch.setattr(subprocess, "Popen", sentinel)
    fake = FakeAttempt("a1b2c3d4")

    class _V:
        attempt_id = "a1b2c3d4"
        status = "accepted"
        eval_run_id = None
        deployment_id = None
        deployed_version = None
        measurement_id = None
        composite_delta = None
        score_before = None
        score_after = None
        parent_attempt_id = None
        rejection_reason = None
        rejection_detail = None
        rolled_back = False
        events: list = []

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin:
        lin.return_value.view_attempt.return_value = _V()
        run_improve_lineage_in_process(attempt_id="a1b2", on_event=lambda _: None)
    sentinel.assert_not_called()


def test_accept_never_calls_subprocess_popen(
    isolated_stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cli.commands.improve import run_improve_accept_in_process

    sentinel = MagicMock(side_effect=AssertionError("subprocess spawned!"))
    monkeypatch.setattr(subprocess, "Popen", sentinel)
    fake = FakeAttempt("a1b2c3d4")

    class _V1:
        deployment_id = None
        deployed_version = None

    class _V2:
        deployment_id = "d1"
        deployed_version = 3

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin:
        lin.return_value.view_attempt.side_effect = [_V1(), _V2()]
        run_improve_accept_in_process(
            attempt_id="a1b2",
            on_event=lambda _: None,
            deploy_invoker=lambda **kw: None,
        )
    sentinel.assert_not_called()


def test_measure_never_calls_subprocess_popen(
    isolated_stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cli.commands.improve import run_improve_measure_in_process

    sentinel = MagicMock(side_effect=AssertionError("subprocess spawned!"))
    monkeypatch.setattr(subprocess, "Popen", sentinel)
    fake = FakeAttempt("a1b2c3d4")

    class _V:
        deployment_id = "d1"

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin, \
         patch("cli.commands.improve._run_post_deploy_eval", return_value=0.85):
        lin.return_value.view_attempt.return_value = _V()
        run_improve_measure_in_process(attempt_id="a1b2", on_event=lambda _: None)
    sentinel.assert_not_called()


def test_run_never_calls_subprocess_popen(
    isolated_stores, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from cli.commands.improve import run_improve_run_in_process

    sentinel = MagicMock(side_effect=AssertionError("subprocess spawned!"))
    monkeypatch.setattr(subprocess, "Popen", sentinel)

    # Fake the downstream runners rather than run full eval+optimize.
    with patch("cli.commands.eval.run_eval_in_process") as eval_fn, \
         patch("cli.commands.optimize.run_optimize_in_process") as opt_fn:
        from cli.commands.eval import EvalRunResult
        from cli.commands.optimize import OptimizeRunResult
        eval_fn.return_value = EvalRunResult(
            run_id="er_x", config_path="c.yaml", mode="mock",
            status="ok", composite=0.85, warnings=(), artifacts=(),
            score_payload={},
        )
        opt_fn.return_value = OptimizeRunResult(
            eval_run_id="er_x", attempt_id="att_y", config_path="c.yaml",
            status="ok", composite_before=0.80, composite_after=0.85,
            warnings=(), artifacts=(),
        )
        run_improve_run_in_process(
            config_path="c.yaml",
            on_event=lambda _: None,
        )
    sentinel.assert_not_called()
