"""Tests for R6.B.2d: ``improve measure`` writes a CalibrationStore row
after recording the lineage measurement.

The calibration row is written only when the attempt has all three
calibration fields populated (``predicted_effectiveness``,
``strategy_surface``, ``strategy_name``) AND the measurement produced a
non-None ``composite_delta``. Legacy attempts and missing-actual cases
skip with a log line; CalibrationStore failures degrade to a warning
without failing the measure command.

Also covers the schema/loop wiring for the new ``strategy_name`` column
on ``OptimizationAttempt`` (mirrors the B.2a/B.2b pattern).
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from optimizer.calibration import CalibrationStore
from optimizer.memory import OptimizationAttempt, OptimizationMemory
from runner import cli


# ---------------------------------------------------------------------------
# Schema test (mirrors B.2a)
# ---------------------------------------------------------------------------


def test_memory_schema_adds_strategy_name_column(tmp_path) -> None:
    db_path = str(tmp_path / "mem.db")
    OptimizationMemory(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("PRAGMA table_info(attempts)").fetchall()
    cols = {row[1]: row[2] for row in rows}
    assert "strategy_name" in cols
    assert cols["strategy_name"].upper() == "TEXT"


def test_memory_strategy_name_roundtrips(tmp_path) -> None:
    db_path = str(tmp_path / "rt.db")
    mem = OptimizationMemory(db_path=db_path)

    attempt = OptimizationAttempt(
        attempt_id="rt-1",
        timestamp=time.time(),
        change_description="x",
        config_diff="{}",
        status="accepted",
        predicted_effectiveness=0.5,
        strategy_surface="system_prompt",
        strategy_name="rewrite_prompt",
    )
    mem.log(attempt)
    latest = mem.recent(1)
    assert len(latest) == 1
    assert latest[0].strategy_name == "rewrite_prompt"


# ---------------------------------------------------------------------------
# Loop wiring meta-test (mirrors B.2b)
# ---------------------------------------------------------------------------


def test_loop_populates_strategy_name() -> None:
    """Every ``OptimizationAttempt(...)`` construction in loop.py must
    pass ``strategy_name=`` (alongside the existing predicted /
    surface kwargs). Guards against future reverts.
    """
    loop_path = (
        Path(__file__).resolve().parent.parent / "optimizer" / "loop.py"
    )
    source = loop_path.read_text()

    construction_starts = [
        m.start() for m in re.finditer(r"OptimizationAttempt\(", source)
    ]
    assert len(construction_starts) >= 2

    for start in construction_starts:
        tail = source[start:]
        snippet = "\n".join(tail.splitlines()[:60])
        closing = re.search(r"^\s*\)\s*$", snippet, re.MULTILINE)
        assert closing
        block = snippet[: closing.end()]
        assert "strategy_name=" in block, (
            "An OptimizationAttempt(...) construction in loop.py is "
            "missing the `strategy_name=` kwarg:\n" + block
        )


# ---------------------------------------------------------------------------
# improve measure calibration-write tests
# ---------------------------------------------------------------------------


@dataclass
class FakeAttempt:
    attempt_id: str
    status: str = "accepted"
    score_before: float | None = 0.50
    score_after: float | None = 0.58
    change_description: str = ""
    config_section: str = "system_prompt"
    timestamp: float = 0.0
    config_diff: str = ""
    health_context: str = "{}"
    predicted_effectiveness: float | None = 0.62
    strategy_surface: str | None = "system_prompt"
    strategy_name: str | None = "rewrite_prompt"


@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    memory_db = tmp_path / "optimizer_memory.db"
    lineage_db = tmp_path / "improvement_lineage.db"
    cal_db = tmp_path / "calibration.db"
    monkeypatch.setenv("AGENTLAB_MEMORY_DB", str(memory_db))
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(lineage_db))
    monkeypatch.setenv("AGENTLAB_CALIBRATION_DB", str(cal_db))
    return memory_db, lineage_db, cal_db


def _patched_run(fake_attempt, *, post_composite: float = 0.58):
    """Common patch context for measure runs."""

    class _DeployedView:
        deployment_id = "dep_1"

    return patch.multiple(
        "cli.commands.improve",
        _lookup_attempt_by_prefix=MagicMock(return_value=[fake_attempt]),
        _run_post_deploy_eval=MagicMock(return_value=post_composite),
    ), _DeployedView


def test_improve_measure_writes_calibration_row(isolated_stores) -> None:
    from cli.commands.improve import run_improve_measure_in_process

    _, _, cal_db = isolated_stores
    fake = FakeAttempt(
        "a1b2c3d4",
        score_before=0.50,
        predicted_effectiveness=0.62,
        strategy_surface="system_prompt",
        strategy_name="rewrite_prompt",
    )

    class _DeployedView:
        deployment_id = "dep_1"

    events: list[dict[str, Any]] = []
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch(
        "optimizer.improvement_lineage.ImprovementLineageStore"
    ) as lin, patch(
        "cli.commands.improve._run_post_deploy_eval", return_value=0.58
    ):
        lin.return_value.view_attempt.return_value = _DeployedView()
        lin.return_value.record_measurement.return_value = None
        run_improve_measure_in_process(
            attempt_id="a1b2c3",
            on_event=events.append,
        )

    # Calibration row written.
    store = CalibrationStore(db_path=str(cal_db))
    with sqlite3.connect(str(cal_db)) as conn:
        rows = conn.execute(
            "SELECT attempt_id, surface, strategy, predicted_effectiveness, "
            "actual_delta FROM predicted_vs_actual"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "a1b2c3d4"
    assert rows[0][1] == "system_prompt"
    assert rows[0][2] == "rewrite_prompt"
    assert rows[0][3] == pytest.approx(0.62)
    assert rows[0][4] == pytest.approx(0.08)  # 0.58 - 0.50

    terminal = events[-1]
    assert terminal["event"] == "improve_measure_complete"
    assert terminal.get("calibration_recorded") is True


def test_improve_measure_skips_calibration_when_predicted_null(
    isolated_stores,
) -> None:
    from cli.commands.improve import run_improve_measure_in_process

    _, _, cal_db = isolated_stores
    fake = FakeAttempt(
        "a1b2c3d4", score_before=0.50, predicted_effectiveness=None,
    )

    class _DeployedView:
        deployment_id = "dep_1"

    events: list[dict[str, Any]] = []
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch(
        "optimizer.improvement_lineage.ImprovementLineageStore"
    ) as lin, patch(
        "cli.commands.improve._run_post_deploy_eval", return_value=0.58
    ):
        lin.return_value.view_attempt.return_value = _DeployedView()
        lin.return_value.record_measurement.return_value = None
        run_improve_measure_in_process(
            attempt_id="a1b2c3",
            on_event=events.append,
        )

    # No row written. (CalibrationStore() will create the file on init,
    # but the table should be empty.)
    if cal_db.exists():
        with sqlite3.connect(str(cal_db)) as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM predicted_vs_actual"
            ).fetchone()[0]
        assert cnt == 0
    terminal = events[-1]
    assert terminal["event"] == "improve_measure_complete"
    assert terminal.get("calibration_recorded") is False


def test_improve_measure_skips_calibration_when_surface_missing(
    isolated_stores,
) -> None:
    from cli.commands.improve import run_improve_measure_in_process

    _, _, cal_db = isolated_stores
    fake = FakeAttempt(
        "a1b2c3d4",
        score_before=0.50,
        predicted_effectiveness=0.5,
        strategy_surface=None,
    )

    class _DeployedView:
        deployment_id = "dep_1"

    events: list[dict[str, Any]] = []
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch(
        "optimizer.improvement_lineage.ImprovementLineageStore"
    ) as lin, patch(
        "cli.commands.improve._run_post_deploy_eval", return_value=0.58
    ):
        lin.return_value.view_attempt.return_value = _DeployedView()
        lin.return_value.record_measurement.return_value = None
        run_improve_measure_in_process(
            attempt_id="a1b2c3",
            on_event=events.append,
        )

    if cal_db.exists():
        with sqlite3.connect(str(cal_db)) as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM predicted_vs_actual"
            ).fetchone()[0]
        assert cnt == 0
    assert events[-1].get("calibration_recorded") is False


def test_improve_measure_skips_calibration_when_strategy_missing(
    isolated_stores,
) -> None:
    from cli.commands.improve import run_improve_measure_in_process

    _, _, cal_db = isolated_stores
    fake = FakeAttempt(
        "a1b2c3d4",
        score_before=0.50,
        predicted_effectiveness=0.5,
        strategy_surface="system_prompt",
        strategy_name=None,
    )

    class _DeployedView:
        deployment_id = "dep_1"

    events: list[dict[str, Any]] = []
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch(
        "optimizer.improvement_lineage.ImprovementLineageStore"
    ) as lin, patch(
        "cli.commands.improve._run_post_deploy_eval", return_value=0.58
    ):
        lin.return_value.view_attempt.return_value = _DeployedView()
        lin.return_value.record_measurement.return_value = None
        run_improve_measure_in_process(
            attempt_id="a1b2c3",
            on_event=events.append,
        )

    if cal_db.exists():
        with sqlite3.connect(str(cal_db)) as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM predicted_vs_actual"
            ).fetchone()[0]
        assert cnt == 0
    assert events[-1].get("calibration_recorded") is False


def test_improve_measure_skips_calibration_when_composite_delta_none(
    isolated_stores,
) -> None:
    from cli.commands.improve import run_improve_measure_in_process

    _, _, cal_db = isolated_stores
    # score_before=None ⇒ composite_delta is None ⇒ skip (do not write 0.0).
    fake = FakeAttempt(
        "a1b2c3d4",
        score_before=None,
        predicted_effectiveness=0.62,
        strategy_surface="system_prompt",
        strategy_name="rewrite_prompt",
    )

    class _DeployedView:
        deployment_id = "dep_1"

    events: list[dict[str, Any]] = []
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch(
        "optimizer.improvement_lineage.ImprovementLineageStore"
    ) as lin, patch(
        "cli.commands.improve._run_post_deploy_eval", return_value=0.58
    ):
        lin.return_value.view_attempt.return_value = _DeployedView()
        lin.return_value.record_measurement.return_value = None
        run_improve_measure_in_process(
            attempt_id="a1b2c3",
            on_event=events.append,
        )

    if cal_db.exists():
        with sqlite3.connect(str(cal_db)) as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM predicted_vs_actual"
            ).fetchone()[0]
        assert cnt == 0
    # composite_delta None ⇒ calibration_recorded is None (skip due to
    # missing actual, not legacy-attempt skip).
    assert events[-1].get("calibration_recorded") is None


def test_improve_measure_calibration_write_failure_is_warning_not_exit(
    isolated_stores,
) -> None:
    from cli.commands.improve import run_improve_measure_in_process

    _, _, _cal_db = isolated_stores
    fake = FakeAttempt(
        "a1b2c3d4",
        score_before=0.50,
        predicted_effectiveness=0.62,
        strategy_surface="system_prompt",
        strategy_name="rewrite_prompt",
    )

    class _DeployedView:
        deployment_id = "dep_1"

    events: list[dict[str, Any]] = []
    text_lines: list[str] = []

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch(
        "optimizer.improvement_lineage.ImprovementLineageStore"
    ) as lin, patch(
        "cli.commands.improve._run_post_deploy_eval", return_value=0.58
    ), patch(
        "optimizer.calibration.CalibrationStore",
        side_effect=RuntimeError("boom"),
    ):
        lin.return_value.view_attempt.return_value = _DeployedView()
        lin.return_value.record_measurement.return_value = None
        result = run_improve_measure_in_process(
            attempt_id="a1b2c3",
            on_event=events.append,
            text_writer=text_lines.append,
        )

    assert result.status == "ok"
    # Warning surfaced.
    joined = "\n".join(text_lines).lower()
    assert "calibration" in joined
    assert events[-1].get("calibration_recorded") is None


# ---------------------------------------------------------------------------
# Click command JSON envelope
# ---------------------------------------------------------------------------


def test_improve_measure_cli_json_includes_calibration_recorded(
    isolated_stores,
) -> None:
    import json as _json
    _, lineage_db, cal_db = isolated_stores

    # Seed a real lineage row so view_attempt returns deployed.
    from optimizer.improvement_lineage import ImprovementLineageStore
    s = ImprovementLineageStore(db_path=str(lineage_db))
    s.record_deployment(attempt_id="a1b2c3d4", deployment_id="d1", version=3)

    fake = FakeAttempt(
        "a1b2c3d4",
        score_before=0.50,
        predicted_effectiveness=0.62,
        strategy_surface="system_prompt",
        strategy_name="rewrite_prompt",
    )

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[fake],
    ), patch(
        "cli.commands.improve._run_post_deploy_eval", return_value=0.58,
    ):
        r = CliRunner().invoke(cli, [
            "improve", "measure", "a1b2c3d4", "--json",
        ])
    assert r.exit_code == 0, r.output
    payload = _json.loads(r.output.strip().split("\n")[-1])
    assert payload["status"] == "ok"
    assert payload["calibration_recorded"] is True

    # Verify the row exists.
    with sqlite3.connect(str(cal_db)) as conn:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM predicted_vs_actual"
        ).fetchone()[0]
    assert cnt == 1
