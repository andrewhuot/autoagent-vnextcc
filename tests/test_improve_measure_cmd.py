"""agentlab improve measure <attempt_id> — post-deploy composite_delta."""
from __future__ import annotations

from unittest.mock import patch
from dataclasses import dataclass

import pytest
from click.testing import CliRunner

from runner import cli


@dataclass
class FakeAttempt:
    attempt_id: str
    status: str = "accepted"
    score_before: float | None = 0.80
    score_after: float | None = 0.85
    change_description: str = ""
    config_section: str = "prompt"
    timestamp: float = 0.0
    config_diff: str = ""
    health_context: str = "{}"


@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    memory_db = tmp_path / "optimizer_memory.db"
    lineage_db = tmp_path / "improvement_lineage.db"
    monkeypatch.setenv("AGENTLAB_MEMORY_DB", str(memory_db))
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(lineage_db))
    return memory_db, lineage_db


def _seed_deployment(lineage_db, attempt_id):
    from optimizer.improvement_lineage import ImprovementLineageStore
    s = ImprovementLineageStore(db_path=str(lineage_db))
    s.record_deployment(attempt_id=attempt_id, deployment_id="d1", version=3)


def test_measure_errors_when_attempt_not_found(isolated_stores):
    with patch("cli.commands.improve._lookup_attempt_by_prefix", return_value=[]):
        r = CliRunner().invoke(cli, ["improve", "measure", "ghost000"])
    assert r.exit_code != 0


def test_measure_errors_when_not_deployed(isolated_stores):
    with patch("cli.commands.improve._lookup_attempt_by_prefix",
               return_value=[FakeAttempt("a1b2c3d4")]):
        r = CliRunner().invoke(cli, ["improve", "measure", "a1b2c3d4"])
    assert r.exit_code != 0
    out = (r.output + (r.stderr_bytes or b"").decode()).lower()
    assert "not" in out and "deploy" in out


def test_measure_writes_measurement_event(isolated_stores):
    _, lineage_db = isolated_stores
    _seed_deployment(lineage_db, "a1b2c3d4")

    with patch("cli.commands.improve._lookup_attempt_by_prefix",
               return_value=[FakeAttempt("a1b2c3d4", score_before=0.80)]), \
         patch("cli.commands.improve._run_post_deploy_eval", return_value=0.87):
        r = CliRunner().invoke(cli, ["improve", "measure", "a1b2c3d4"])
    assert r.exit_code == 0, r.output
    from optimizer.improvement_lineage import (
        EVENT_MEASUREMENT, ImprovementLineageStore)
    lineage = ImprovementLineageStore(db_path=str(lineage_db))
    events = [e for e in lineage.events_for("a1b2c3d4")
              if e.event_type == EVENT_MEASUREMENT
              and e.payload.get("scheduled") is not True]
    assert len(events) == 1
    assert events[0].payload["composite_delta"] == pytest.approx(0.07, abs=1e-6)


def test_measure_handles_missing_score_before(isolated_stores):
    """When attempt.score_before is None, composite_delta is None but the
    measurement is still recorded (with a warning)."""
    _, lineage_db = isolated_stores
    _seed_deployment(lineage_db, "a1b2c3d4")

    with patch("cli.commands.improve._lookup_attempt_by_prefix",
               return_value=[FakeAttempt("a1b2c3d4", score_before=None)]), \
         patch("cli.commands.improve._run_post_deploy_eval", return_value=0.9):
        r = CliRunner().invoke(cli, ["improve", "measure", "a1b2c3d4"])
    assert r.exit_code == 0
    from optimizer.improvement_lineage import (
        EVENT_MEASUREMENT, ImprovementLineageStore)
    lineage = ImprovementLineageStore(db_path=str(lineage_db))
    events = [e for e in lineage.events_for("a1b2c3d4")
              if e.event_type == EVENT_MEASUREMENT
              and e.payload.get("scheduled") is not True]
    assert len(events) == 1
    assert events[0].payload["composite_delta"] is None


def test_measure_json_output(isolated_stores):
    _, lineage_db = isolated_stores
    _seed_deployment(lineage_db, "a1b2c3d4")
    with patch("cli.commands.improve._lookup_attempt_by_prefix",
               return_value=[FakeAttempt("a1b2c3d4", score_before=0.8)]), \
         patch("cli.commands.improve._run_post_deploy_eval", return_value=0.85):
        r = CliRunner().invoke(cli, ["improve", "measure", "a1b2c3d4", "--json"])
    import json as _json
    payload = _json.loads(r.output.strip().split("\n")[-1])
    assert payload["status"] == "ok"
    assert payload["attempt_id"] == "a1b2c3d4"
    assert payload["composite_delta"] == pytest.approx(0.05, abs=1e-6)


def test_measure_view_attempt_reflects_delta_after_measure(isolated_stores):
    _, lineage_db = isolated_stores
    _seed_deployment(lineage_db, "a1b2c3d4")
    with patch("cli.commands.improve._lookup_attempt_by_prefix",
               return_value=[FakeAttempt("a1b2c3d4", score_before=0.80)]), \
         patch("cli.commands.improve._run_post_deploy_eval", return_value=0.85):
        CliRunner().invoke(cli, ["improve", "measure", "a1b2c3d4"])
    from optimizer.improvement_lineage import ImprovementLineageStore
    lineage = ImprovementLineageStore(db_path=str(lineage_db))
    view = lineage.view_attempt("a1b2c3d4")
    assert view.composite_delta == pytest.approx(0.05, abs=1e-6)
