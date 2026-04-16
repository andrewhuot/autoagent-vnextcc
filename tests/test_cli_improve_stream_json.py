"""Regression tests asserting that each ``improve`` subcommand's in-process
event stream ends with the expected ``improve_<sub>_complete`` terminal
event (R4.5).

The ``improve`` subcommands don't expose ``--output-format stream-json``
on their Click wrappers today (only ``--json``), so this file verifies the
equivalent guarantee at the in-process function layer — that's the seam
the Workbench ``/improve`` slash handler and any future stream-json CLI
surface will consume. If a future R4.x adds ``--output-format stream-json``
to the CLI wrappers, the assertions here port over directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest


@dataclass
class _FakeAttempt:
    attempt_id: str = "a1b2c3d4"
    status: str = "accepted"
    change_description: str = "tighten"
    config_section: str = "prompt"
    score_before: float = 0.80
    score_after: float = 0.85
    timestamp: float = 0.0
    config_diff: str = "+added\n-removed"
    health_context: str = "{}"
    patch_bundle: str = ""


@pytest.fixture
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAB_MEMORY_DB", str(tmp_path / "m.db"))
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(tmp_path / "l.db"))
    return tmp_path


@pytest.mark.parametrize(
    "sub,terminal_event",
    [
        ("list", "improve_list_complete"),
        ("show", "improve_show_complete"),
        ("diff", "improve_diff_complete"),
        ("lineage", "improve_lineage_complete"),
        ("accept", "improve_accept_complete"),
        ("measure", "improve_measure_complete"),
    ],
)
def test_improve_in_process_event_sequence_ends_with_terminal(
    _isolated, sub: str, terminal_event: str
) -> None:
    """Every ``improve`` subcommand emits ``<event>_complete`` as its final event."""
    from cli.commands.improve import (
        run_improve_accept_in_process,
        run_improve_diff_in_process,
        run_improve_lineage_in_process,
        run_improve_list_in_process,
        run_improve_measure_in_process,
        run_improve_show_in_process,
    )

    events: list[dict[str, Any]] = []
    fake = _FakeAttempt()

    class _V:
        attempt_id = "a1b2c3d4"
        status = "accepted"
        eval_run_id = None
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

    class _V1_undeployed:
        deployment_id = None
        deployed_version = None

    class _V2_deployed:
        deployment_id = "dep_1"
        deployed_version = 5

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch("optimizer.memory.OptimizationMemory") as mem, \
         patch("optimizer.improvement_lineage.ImprovementLineageStore") as lin, \
         patch("cli.commands.improve._run_post_deploy_eval", return_value=0.85):
        mem.return_value.get_all.return_value = [fake]
        lin.return_value.events_for.return_value = []

        if sub == "list":
            run_improve_list_in_process(on_event=events.append)
        elif sub == "show":
            lin.return_value.events_for.return_value = []
            run_improve_show_in_process(
                attempt_id="a1b2", on_event=events.append,
            )
        elif sub == "diff":
            run_improve_diff_in_process(
                attempt_id="a1b2", on_event=events.append,
            )
        elif sub == "lineage":
            lin.return_value.view_attempt.return_value = _V()
            run_improve_lineage_in_process(
                attempt_id="a1b2", on_event=events.append,
            )
        elif sub == "accept":
            # Two view_attempt calls (pre-deploy + post-deploy lookup).
            lin.return_value.view_attempt.side_effect = [
                _V1_undeployed(), _V2_deployed(),
            ]
            run_improve_accept_in_process(
                attempt_id="a1b2", on_event=events.append,
                deploy_invoker=lambda **kw: None,
            )
        elif sub == "measure":
            lin.return_value.view_attempt.return_value = _V2_deployed()
            run_improve_measure_in_process(
                attempt_id="a1b2", on_event=events.append,
            )

    assert events, f"expected at least one event for /improve {sub}"
    names = [e.get("event") for e in events]
    assert names[-1] == terminal_event, (
        f"expected {terminal_event!r} last for /improve {sub}, got names={names!r}"
    )
    final = events[-1]
    assert "status" in final
    assert final["status"] in {"ok", "failed"}


def test_improve_run_in_process_event_sequence_ends_with_terminal(
    _isolated, monkeypatch
) -> None:
    """``improve run`` orchestrates eval+optimize and ends with its terminal."""
    from cli.commands.eval import EvalRunResult
    from cli.commands.improve import run_improve_run_in_process
    from cli.commands.optimize import OptimizeRunResult

    events: list[dict[str, Any]] = []

    def _fake_eval(*, on_event, **_kw) -> EvalRunResult:
        on_event({"event": "phase_started", "phase": "eval"})
        on_event({
            "event": "eval_complete", "run_id": "er_x",
            "config_path": "c.yaml", "mode": "mock",
        })
        return EvalRunResult(
            run_id="er_x", config_path="c.yaml", mode="mock",
            status="ok", composite=0.85, warnings=(), artifacts=(),
            score_payload={},
        )

    def _fake_optimize(*, on_event, **_kw) -> OptimizeRunResult:
        on_event({"event": "phase_started", "phase": "optimize"})
        on_event({
            "event": "optimize_complete",
            "eval_run_id": "er_x", "attempt_id": "att_y",
            "config_path": "c.yaml", "status": "ok",
        })
        return OptimizeRunResult(
            eval_run_id="er_x", attempt_id="att_y", config_path="c.yaml",
            status="ok", composite_before=0.80, composite_after=0.85,
            warnings=(), artifacts=(),
        )

    with patch("cli.commands.eval.run_eval_in_process", side_effect=_fake_eval), \
         patch("cli.commands.optimize.run_optimize_in_process", side_effect=_fake_optimize):
        result = run_improve_run_in_process(
            config_path="c.yaml",
            on_event=events.append,
        )

    assert result.attempt_id == "att_y"
    assert result.eval_run_id == "er_x"
    assert events[-1]["event"] == "improve_run_complete"
    assert events[-1]["attempt_id"] == "att_y"
    assert events[-1]["status"] == "ok"
