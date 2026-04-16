"""agentlab improve accept <attempt_id> — deploy + schedule measurement."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from dataclasses import dataclass

import pytest
from click.testing import CliRunner

from runner import cli


@dataclass
class FakeAttempt:
    attempt_id: str
    status: str = "accepted"
    change_description: str = "tighten prompt"
    config_section: str = "prompt"
    score_before: float = 0.80
    score_after: float = 0.85
    timestamp: float = 0.0
    config_diff: str = ""
    health_context: str = "{}"


@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    """Point memory + lineage at tmp dirs so tests don't pollute the workspace."""
    memory_db = tmp_path / "optimizer_memory.db"
    lineage_db = tmp_path / "improvement_lineage.db"
    monkeypatch.setenv("AGENTLAB_MEMORY_DB", str(memory_db))
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(lineage_db))
    return memory_db, lineage_db


def test_accept_exits_error_when_attempt_not_found(isolated_stores):
    with patch("cli.commands.improve._lookup_attempt_by_prefix", return_value=[]):
        r = CliRunner().invoke(cli, ["improve", "accept", "nopematch"])
    assert r.exit_code != 0
    assert "no" in r.output.lower() or "not found" in r.output.lower()


def test_accept_exits_error_on_ambiguous_prefix(isolated_stores):
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4"), FakeAttempt("a1b2c3d5")],
    ):
        r = CliRunner().invoke(cli, ["improve", "accept", "a1b"])
    assert r.exit_code != 0
    assert "ambiguous" in r.output.lower() or "multiple" in r.output.lower()


def test_accept_idempotent_when_already_deployed(isolated_stores):
    from optimizer.improvement_lineage import ImprovementLineageStore
    memory_db, lineage_db = isolated_stores
    lineage = ImprovementLineageStore(db_path=str(lineage_db))
    lineage.record_deployment(attempt_id="a1b2c3d4", deployment_id="d1", version=3)

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4")],
    ), patch("cli.commands.improve._invoke_deploy") as deploy_mock:
        r = CliRunner().invoke(cli, ["improve", "accept", "a1b2c3d4"])
    assert r.exit_code == 0
    assert "already" in r.output.lower()
    deploy_mock.assert_not_called()


def test_accept_invokes_deploy_with_attempt_id(isolated_stores):
    captured = {}
    def fake_deploy(**kw):
        captured.update(kw)

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4")],
    ), patch("cli.commands.improve._invoke_deploy", side_effect=fake_deploy):
        r = CliRunner().invoke(cli, ["improve", "accept", "a1b2c3d4"])
    assert r.exit_code == 0, r.output
    assert captured.get("attempt_id") == "a1b2c3d4"
    assert captured.get("strategy") == "canary"


def test_accept_strategy_flag(isolated_stores):
    captured = {}
    def fake_deploy(**kw):
        captured.update(kw)
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4")],
    ), patch("cli.commands.improve._invoke_deploy", side_effect=fake_deploy):
        CliRunner().invoke(cli, ["improve", "accept", "a1b2c3d4", "--strategy", "immediate"])
    assert captured.get("strategy") == "immediate"


def test_accept_schedules_measurement_event(isolated_stores):
    from optimizer.improvement_lineage import EVENT_MEASUREMENT, ImprovementLineageStore
    memory_db, lineage_db = isolated_stores

    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4")],
    ), patch("cli.commands.improve._invoke_deploy"):
        r = CliRunner().invoke(cli, ["improve", "accept", "a1b2c3d4"])
    assert r.exit_code == 0, r.output
    lineage = ImprovementLineageStore(db_path=str(lineage_db))
    scheduled = [
        e for e in lineage.events_for("a1b2c3d4")
        if e.event_type == EVENT_MEASUREMENT and e.payload.get("scheduled") is True
    ]
    assert len(scheduled) == 1
    assert scheduled[0].payload["composite_delta"] is None


def test_accept_json_envelope(isolated_stores):
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4")],
    ), patch("cli.commands.improve._invoke_deploy"):
        r = CliRunner().invoke(cli, ["improve", "accept", "a1b2c3d4", "--json"])
    import json as _json
    payload = _json.loads(r.output.strip().split("\n")[-1])
    assert payload.get("status") == "ok"
    assert "a1b2c3d4" in _json.dumps(payload)
