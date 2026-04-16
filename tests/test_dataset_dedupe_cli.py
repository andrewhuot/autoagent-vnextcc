"""Tests for `agentlab eval dataset dedupe` (R5 Slice B.3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from runner import cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _base_case(case_id: str, user_message: str, reference_answer: str = "") -> dict:
    return {
        "id": case_id,
        "category": "support",
        "user_message": user_message,
        "expected_specialist": "support",
        "expected_behavior": "answer",
        "reference_answer": reference_answer,
    }


def _write_yaml(path: Path, cases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"cases": cases}), encoding="utf-8")


@pytest.fixture(autouse=True)
def _force_fake_embedder(monkeypatch):
    """Force AGENTLAB_EMBEDDER=fake for every CLI test below."""
    monkeypatch.setenv("AGENTLAB_EMBEDDER", "fake")
    # Ensure nothing accidentally tries to use a real key during tests.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_cli_dedupe_dry_run_does_not_modify_files(tmp_path):
    src_dir = tmp_path / "cases"
    yaml_path = src_dir / "suite.yaml"
    cases = [
        _base_case("cs_001", "same text", reference_answer="longer ref here"),
        _base_case("cs_002", "unique one about refunds"),
        _base_case("cs_003", "same text", reference_answer="short"),
    ]
    _write_yaml(yaml_path, cases)
    original = yaml_path.read_text()

    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "dedupe", "--source", str(src_dir), "--dry-run"],
    )
    assert r.exit_code == 0, r.output
    # Files unchanged.
    assert yaml_path.read_text() == original
    # Output reports the drop.
    assert "Kept: 2" in r.output
    assert "Dropped: 1" in r.output


def test_cli_dedupe_applies_and_rewrites_source(tmp_path):
    src_dir = tmp_path / "cases"
    yaml_path = src_dir / "suite.yaml"
    cases = [
        _base_case("cs_001", "same text", reference_answer="longer ref here"),
        _base_case("cs_002", "unique one about refunds"),
        _base_case("cs_003", "same text", reference_answer="short"),
    ]
    _write_yaml(yaml_path, cases)

    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "dedupe", "--source", str(src_dir)],
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load(yaml_path.read_text())
    kept_ids = {c["id"] for c in data["cases"]}
    assert kept_ids == {"cs_001", "cs_002"}
    assert "Dropped: 1" in r.output


def test_cli_dedupe_output_path_writes_single_yaml(tmp_path):
    src_dir = tmp_path / "cases"
    yaml_path = src_dir / "suite.yaml"
    cases = [
        _base_case("cs_001", "same text", reference_answer="longer"),
        _base_case("cs_002", "unique thing"),
        _base_case("cs_003", "same text", reference_answer="s"),
    ]
    _write_yaml(yaml_path, cases)
    original = yaml_path.read_text()

    out_path = tmp_path / "deduped.yaml"
    r = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "dedupe",
            "--source", str(src_dir),
            "--output", str(out_path),
        ],
    )
    assert r.exit_code == 0, r.output
    # Source dir unchanged.
    assert yaml_path.read_text() == original
    assert out_path.exists()
    data = yaml.safe_load(out_path.read_text())
    kept_ids = {c["id"] for c in data["cases"]}
    assert kept_ids == {"cs_001", "cs_002"}


def test_cli_dedupe_uses_fake_embedder_via_env(tmp_path):
    # Env var set by the autouse fixture. Assert no OPENAI_API_KEY is present.
    assert "OPENAI_API_KEY" not in os.environ
    src_dir = tmp_path / "cases"
    _write_yaml(
        src_dir / "a.yaml",
        [_base_case("c1", "hi there")],
    )
    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "dedupe", "--source", str(src_dir), "--dry-run"],
    )
    assert r.exit_code == 0, r.output


def test_cli_dedupe_prints_sim_values(tmp_path):
    src_dir = tmp_path / "cases"
    cases = [
        _base_case("cs_001", "identical text", reference_answer="longer"),
        _base_case("cs_002", "identical text", reference_answer="s"),
    ]
    _write_yaml(src_dir / "suite.yaml", cases)
    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "dedupe", "--source", str(src_dir), "--dry-run"],
    )
    assert r.exit_code == 0, r.output
    assert "sim=" in r.output


def test_cli_dedupe_threshold_flag_respected(tmp_path):
    # Same fixture, two thresholds → more drops at lower threshold.
    # We synthesize FakeEmbedder-sensitive inputs: identical messages hash
    # to the exact same vector (sim=1.0), while differing messages hash to
    # effectively random vectors (sim in ~[-0.5, 0.5]). So threshold=0.99
    # still drops the exact duplicates, but threshold=-1.0 treats every
    # pair as a duplicate and collapses them all.
    src_dir_a = tmp_path / "cases_a"
    src_dir_b = tmp_path / "cases_b"
    cases = [
        _base_case("c1", "same text", reference_answer="ref1"),
        _base_case("c2", "same text", reference_answer="ref2"),
        _base_case("c3", "totally different subject matter"),
        _base_case("c4", "yet another unrelated question"),
    ]
    _write_yaml(src_dir_a / "x.yaml", cases)
    _write_yaml(src_dir_b / "x.yaml", cases)

    low = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "dedupe",
            "--source", str(src_dir_a),
            "--threshold", "-1.0",
            "--dry-run",
        ],
    )
    high = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "dedupe",
            "--source", str(src_dir_b),
            "--threshold", "0.99",
            "--dry-run",
        ],
    )
    assert low.exit_code == 0, low.output
    assert high.exit_code == 0, high.output

    def _drops(text: str) -> int:
        for line in text.splitlines():
            if line.startswith("Dropped:"):
                return int(line.split(":", 1)[1].strip())
        return -1

    assert _drops(low.output) > _drops(high.output)


def test_cli_dedupe_removes_empty_yaml_file_after_full_drop(tmp_path):
    src_dir = tmp_path / "cases"
    keeper_path = src_dir / "keep.yaml"
    dupe_path = src_dir / "dupes.yaml"
    # The keeper file contains the longer-ref case → the entire dupes.yaml
    # is duplicates of it and should be removed after the rewrite.
    _write_yaml(
        keeper_path,
        [_base_case("keep_1", "duplicate text", reference_answer="a much longer reference")],
    )
    _write_yaml(
        dupe_path,
        [
            _base_case("dup_1", "duplicate text", reference_answer="s"),
            _base_case("dup_2", "duplicate text", reference_answer="t"),
        ],
    )

    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "dedupe", "--source", str(src_dir)],
    )
    assert r.exit_code == 0, r.output
    assert keeper_path.exists()
    # Fully-emptied YAML must be deleted.
    assert not dupe_path.exists()
    data = yaml.safe_load(keeper_path.read_text())
    assert [c["id"] for c in data["cases"]] == ["keep_1"]
