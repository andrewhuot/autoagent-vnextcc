"""Tests for `agentlab eval dataset balance` (R5 Slice B.5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from runner import cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _base_case(
    case_id: str,
    *,
    category: str = "support",
    tags: list[str] | None = None,
) -> dict:
    entry: dict = {
        "id": case_id,
        "category": category,
        "user_message": f"msg {case_id}",
        "expected_specialist": "support",
        "expected_behavior": "answer",
    }
    if tags is not None:
        entry["tags"] = tags
    return entry


def _write_yaml(path: Path, cases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"cases": cases}), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_cli_balance_prints_histogram_and_median(tmp_path):
    src_dir = tmp_path / "cases"
    cases = [
        _base_case("c1", category="happy_path"),
        _base_case("c2", category="happy_path"),
        _base_case("c3", category="happy_path"),
        _base_case("c4", category="edge"),
    ]
    _write_yaml(src_dir / "suite.yaml", cases)

    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "balance", "--source", str(src_dir)],
    )
    assert r.exit_code == 0, r.output
    assert "happy_path" in r.output
    assert "edge" in r.output
    # Counts present.
    assert "3" in r.output
    assert "1" in r.output
    # Median line present.
    assert "median" in r.output.lower()


def test_cli_balance_default_by_category(tmp_path):
    src_dir = tmp_path / "cases"
    cases = [
        _base_case("c1", category="a", tags=["x", "y"]),
        _base_case("c2", category="b", tags=["y"]),
    ]
    _write_yaml(src_dir / "suite.yaml", cases)

    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "balance", "--source", str(src_dir)],
    )
    assert r.exit_code == 0, r.output
    # Default is category → category names appear, per-tag names do not.
    assert "'a'" in r.output or " a" in r.output or "a:" in r.output
    # 'x' is a tag, shouldn't appear in a category-default run.
    # (Use the form "'x'" to avoid false matches on the letter 'x' in words.)
    assert "'x'" not in r.output
    # Header indicates by category.
    assert "by category" in r.output.lower()


def test_cli_balance_by_tag(tmp_path):
    src_dir = tmp_path / "cases"
    cases = [
        _base_case("c1", category="a", tags=["x", "y"]),
        _base_case("c2", category="a", tags=["x"]),
        _base_case("c3", category="a", tags=["z"]),
    ]
    _write_yaml(src_dir / "suite.yaml", cases)

    r = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "balance",
            "--source", str(src_dir),
            "--by", "tag",
            "--json",
        ],
    )
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload["by"] == "tag"
    assert payload["histogram"] == {"x": 2, "y": 1, "z": 1}
    # Sum exceeds case count because c1 has two tags.
    assert sum(payload["histogram"].values()) > 3


def test_cli_balance_json_flag_emits_parseable_json(tmp_path):
    src_dir = tmp_path / "cases"
    cases = [
        _base_case("c1", category="a"),
        _base_case("c2", category="b"),
        _base_case("c3", category="b"),
    ]
    _write_yaml(src_dir / "suite.yaml", cases)

    r = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "balance",
            "--source", str(src_dir),
            "--json",
        ],
    )
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert isinstance(payload, dict)
    assert set(payload.keys()) >= {"by", "histogram", "median", "recommendations"}
    assert payload["by"] == "category"
    assert payload["histogram"] == {"a": 1, "b": 2}
    assert isinstance(payload["median"], int)
    assert isinstance(payload["recommendations"], list)


def test_cli_balance_prints_recommendations_section(tmp_path):
    src_dir = tmp_path / "cases"
    # Strongly uneven so at least one bucket is off-median.
    cases = (
        [_base_case(f"a{i}", category="a") for i in range(1)]
        + [_base_case(f"b{i}", category="b") for i in range(5)]
        + [_base_case(f"c{i}", category="c") for i in range(10)]
    )
    _write_yaml(src_dir / "suite.yaml", cases)

    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "balance", "--source", str(src_dir)],
    )
    assert r.exit_code == 0, r.output
    assert "Recommendations:" in r.output
    # At least one rec line referencing a bucket name.
    assert "'a'" in r.output or "'c'" in r.output


def test_cli_balance_exits_nonzero_on_missing_source(tmp_path):
    missing = tmp_path / "nonexistent_dir"
    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "balance", "--source", str(missing)],
    )
    assert r.exit_code != 0
    # Click reports the error message in its combined output here.
    assert str(missing) in r.output


def test_cli_balance_reads_from_default_source_when_omitted():
    # Light integration test — evals/cases/ is tracked and has YAML files.
    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "balance", "--json"],
    )
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload["median"] > 0
    assert payload["histogram"]
