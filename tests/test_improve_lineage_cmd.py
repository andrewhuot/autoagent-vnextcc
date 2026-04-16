"""agentlab improve lineage <attempt_id> — render the ancestry chain."""
from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from runner import cli


@dataclass
class FakeAttempt:
    attempt_id: str
    change_description: str = "tighten prompt"
    config_diff: str = ""
    patch_bundle: str = ""
    config_section: str = "prompt"
    status: str = "accepted"
    score_before: float | None = 0.80
    score_after: float | None = 0.85
    timestamp: float = 0.0
    health_context: str = "{}"


@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    memory_db = tmp_path / "optimizer_memory.db"
    lineage_db = tmp_path / "improvement_lineage.db"
    monkeypatch.setenv("AGENTLAB_MEMORY_DB", str(memory_db))
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(lineage_db))
    return memory_db, lineage_db


def _seed_full_chain(lineage_db, attempt_id: str) -> None:
    from optimizer.improvement_lineage import ImprovementLineageStore
    s = ImprovementLineageStore(db_path=str(lineage_db))
    s.record_eval_run(
        eval_run_id="run-abc", attempt_id=attempt_id, composite_score=0.80
    )
    s.record_attempt(
        attempt_id=attempt_id, status="accepted",
        score_before=0.80, score_after=0.85, eval_run_id="run-abc",
    )
    s.record_deployment(
        attempt_id=attempt_id, deployment_id="dep-1", version=3
    )
    s.record_measurement(
        attempt_id=attempt_id, measurement_id="meas-xyz",
        composite_delta=0.04, eval_run_id="run-xyz",
    )


def test_lineage_renders_full_chain(isolated_stores):
    _, lineage_db = isolated_stores
    _seed_full_chain(lineage_db, "a1b2c3d4")
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4")],
    ):
        r = CliRunner().invoke(cli, ["improve", "lineage", "a1b2c3d4"])
    assert r.exit_code == 0, r.output
    assert "eval_run" in r.output
    assert "attempt" in r.output
    assert "deployment" in r.output
    assert "measurement" in r.output
    assert "v003" in r.output


def test_lineage_errors_when_attempt_not_found(isolated_stores):
    with patch("cli.commands.improve._lookup_attempt_by_prefix", return_value=[]):
        r = CliRunner().invoke(cli, ["improve", "lineage", "ghost000"])
    assert r.exit_code != 0


def test_lineage_ambiguous_prefix(isolated_stores):
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4"), FakeAttempt("a1b2c3d5")],
    ):
        r = CliRunner().invoke(cli, ["improve", "lineage", "a1b"])
    assert r.exit_code != 0


def test_lineage_partial_chain_renders_gracefully(isolated_stores):
    """An attempt with no lineage events still renders a stub view."""
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4")],
    ):
        r = CliRunner().invoke(cli, ["improve", "lineage", "a1b2c3d4"])
    assert r.exit_code == 0
    assert "a1b2c3d4" in r.output


def test_lineage_json_output(isolated_stores):
    _, lineage_db = isolated_stores
    _seed_full_chain(lineage_db, "a1b2c3d4")
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4")],
    ):
        r = CliRunner().invoke(cli, ["improve", "lineage", "a1b2c3d4", "--json"])
    assert r.exit_code == 0
    payload = json.loads(r.output.strip().split("\n")[-1])
    assert payload["status"] == "ok"
    assert payload["attempt_id"] == "a1b2c3d4"
    assert payload["eval_run_id"] == "run-abc"
    assert payload["deployment_id"] == "dep-1"
    assert payload["deployed_version"] == 3
    assert payload["measurement_id"] == "meas-xyz"
    assert payload["composite_delta"] == pytest.approx(0.04, abs=1e-6)
    assert payload["status_classified"] == "accepted"
    assert isinstance(payload["events"], list)
    assert len(payload["events"]) == 4


def test_lineage_surfaces_rejection_reason(isolated_stores):
    from optimizer.gates import RejectionReason
    from optimizer.improvement_lineage import ImprovementLineageStore
    _, lineage_db = isolated_stores
    s = ImprovementLineageStore(db_path=str(lineage_db))
    s.record_attempt(
        attempt_id="rej00001", status="rejected_regression",
        score_before=0.80, score_after=0.75,
    )
    s.record_rejection(
        attempt_id="rej00001",
        reason=RejectionReason.REGRESSION_DETECTED.value,
        detail="composite dropped 0.05",
    )
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("rej00001", status="rejected_regression")],
    ):
        r = CliRunner().invoke(cli, ["improve", "lineage", "rej00001"])
    assert r.exit_code == 0
    assert "regression_detected" in r.output
    assert "composite dropped 0.05" in r.output
