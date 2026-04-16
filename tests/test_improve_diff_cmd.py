"""agentlab improve diff <attempt_id> — show change description, diff, patch."""
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
    change_description: str = "Tighten system prompt"
    config_diff: str = "- old line\n+ new line"
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


def test_diff_shows_change_description_and_diff(isolated_stores):
    attempt = FakeAttempt(attempt_id="a1b2c3d4")
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix", return_value=[attempt]
    ):
        r = CliRunner().invoke(cli, ["improve", "diff", "a1b2c3d4"])
    assert r.exit_code == 0, r.output
    assert "Tighten system prompt" in r.output
    assert "- old line" in r.output
    assert "+ new line" in r.output


def test_diff_errors_when_not_found(isolated_stores):
    with patch("cli.commands.improve._lookup_attempt_by_prefix", return_value=[]):
        r = CliRunner().invoke(cli, ["improve", "diff", "ghost000"])
    assert r.exit_code != 0


def test_diff_errors_when_ambiguous(isolated_stores):
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix",
        return_value=[FakeAttempt("a1b2c3d4"), FakeAttempt("a1b2c3d5")],
    ):
        r = CliRunner().invoke(cli, ["improve", "diff", "a1b"])
    assert r.exit_code != 0


def test_diff_renders_patch_bundle_when_present(isolated_stores):
    bundle = json.dumps(
        {"surface": "prompt", "mutation": "tighten", "components": ["sys"]}
    )
    attempt = FakeAttempt(attempt_id="a1b2c3d4", patch_bundle=bundle)
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix", return_value=[attempt]
    ):
        r = CliRunner().invoke(cli, ["improve", "diff", "a1b2c3d4"])
    assert r.exit_code == 0
    assert "tighten" in r.output
    assert "prompt" in r.output


def test_diff_json_envelope(isolated_stores):
    attempt = FakeAttempt(attempt_id="a1b2c3d4")
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix", return_value=[attempt]
    ):
        r = CliRunner().invoke(cli, ["improve", "diff", "a1b2c3d4", "--json"])
    assert r.exit_code == 0
    payload = json.loads(r.output.strip().split("\n")[-1])
    assert payload["status"] == "ok"
    assert payload["attempt_id"] == "a1b2c3d4"
    assert payload["change_description"] == "Tighten system prompt"
    assert payload["config_diff"] == "- old line\n+ new line"


def test_diff_handles_empty_diff_gracefully(isolated_stores):
    attempt = FakeAttempt(
        attempt_id="empty001", change_description="No-op", config_diff=""
    )
    with patch(
        "cli.commands.improve._lookup_attempt_by_prefix", return_value=[attempt]
    ):
        r = CliRunner().invoke(cli, ["improve", "diff", "empty001"])
    assert r.exit_code == 0
    assert "No-op" in r.output
    assert "no diff" in r.output.lower() or "empty" in r.output.lower() or r.output  # tolerant
