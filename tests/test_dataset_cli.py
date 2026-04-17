"""Tests for `agentlab eval dataset import|export` (R5 Slice A.6)."""
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


def _write_jsonl(path: Path, n: int) -> None:
    lines = []
    for i in range(n):
        row = {
            "id": f"case_{i}",
            "category": "support",
            "user_message": f"message {i}",
        }
        lines.append(json.dumps(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_csv(path: Path, n: int) -> None:
    rows = ["id,category,user_message"]
    for i in range(n):
        rows.append(f"case_{i},support,message {i}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_yaml_cases(path: Path, n: int) -> None:
    cases = []
    for i in range(n):
        cases.append(
            {
                "id": f"case_{i}",
                "category": "support",
                "user_message": f"message {i}",
                "expected_specialist": "support",
                "expected_behavior": "answer",
            }
        )
    path.write_text(yaml.safe_dump({"cases": cases}), encoding="utf-8")


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


def test_cli_dataset_import_jsonl_writes_yaml(tmp_path):
    src = tmp_path / "input.jsonl"
    _write_jsonl(src, 3)
    out_dir = tmp_path / "cases"
    out_dir.mkdir()

    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "import", str(src), "--output", str(out_dir)],
    )
    assert r.exit_code == 0, r.output

    out_file = out_dir / "input.yaml"
    assert out_file.exists()
    data = yaml.safe_load(out_file.read_text())
    assert "cases" in data
    assert len(data["cases"]) == 3


def test_cli_dataset_import_csv_auto_format(tmp_path):
    src = tmp_path / "cases.csv"
    _write_csv(src, 2)
    out_dir = tmp_path / "cases"
    out_dir.mkdir()

    r = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "import",
            str(src),
            "--format", "auto",
            "--output", str(out_dir),
        ],
    )
    assert r.exit_code == 0, r.output
    out_file = out_dir / "cases.yaml"
    assert out_file.exists()
    data = yaml.safe_load(out_file.read_text())
    assert len(data["cases"]) == 2


def test_cli_dataset_import_refuses_overwrite_without_force(tmp_path):
    src = tmp_path / "input.jsonl"
    _write_jsonl(src, 1)
    out_dir = tmp_path / "cases"
    out_dir.mkdir()
    (out_dir / "input.yaml").write_text("cases: []\n")

    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "import", str(src), "--output", str(out_dir)],
    )
    assert r.exit_code != 0
    assert "--force" in r.output


def test_cli_dataset_import_force_overwrites(tmp_path):
    src = tmp_path / "input.jsonl"
    _write_jsonl(src, 2)
    out_dir = tmp_path / "cases"
    out_dir.mkdir()
    (out_dir / "input.yaml").write_text("cases: []\n")

    r = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "import",
            str(src),
            "--output", str(out_dir),
            "--force",
        ],
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load((out_dir / "input.yaml").read_text())
    assert len(data["cases"]) == 2


def test_cli_dataset_import_hf_requires_dataset_name(tmp_path):
    r = CliRunner().invoke(
        cli,
        [
            "eval", "dataset", "import",
            "some/hf-dataset",
            "--format", "hf",
            "--output", str(tmp_path),
        ],
    )
    assert r.exit_code != 0
    assert "--dataset-name" in r.output or "dataset-name" in r.output


def test_cli_dataset_import_prints_count_summary(tmp_path):
    src = tmp_path / "input.jsonl"
    _write_jsonl(src, 4)
    out_dir = tmp_path / "cases"
    out_dir.mkdir()

    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "import", str(src), "--output", str(out_dir)],
    )
    assert r.exit_code == 0, r.output
    assert "Imported 4 cases" in r.output


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_cli_dataset_export_jsonl(tmp_path):
    src_dir = tmp_path / "cases"
    src_dir.mkdir()
    _write_yaml_cases(src_dir / "suite.yaml", 3)

    out = tmp_path / "out.jsonl"
    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "export", str(out), "--source", str(src_dir)],
    )
    assert r.exit_code == 0, r.output
    assert out.exists()
    lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
    assert len(lines) == 3


def test_cli_dataset_export_csv(tmp_path):
    src_dir = tmp_path / "cases"
    src_dir.mkdir()
    _write_yaml_cases(src_dir / "suite.yaml", 3)

    out = tmp_path / "out.csv"
    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "export", str(out), "--source", str(src_dir)],
    )
    assert r.exit_code == 0, r.output
    assert out.exists()

    # Round-trip semantic equality via load_csv
    from evals.dataset.importers import load_csv
    reloaded = load_csv(out)
    assert len(reloaded) == 3
    assert {c.id for c in reloaded} == {"case_0", "case_1", "case_2"}


def test_cli_dataset_export_format_from_extension(tmp_path):
    src_dir = tmp_path / "cases"
    src_dir.mkdir()
    _write_yaml_cases(src_dir / "suite.yaml", 2)

    # .jsonl extension -> jsonl
    out_jsonl = tmp_path / "out.jsonl"
    r1 = CliRunner().invoke(
        cli,
        ["eval", "dataset", "export", str(out_jsonl), "--source", str(src_dir)],
    )
    assert r1.exit_code == 0, r1.output
    # Should be valid JSONL (each line parses as JSON)
    for line in [ln for ln in out_jsonl.read_text().splitlines() if ln.strip()]:
        json.loads(line)

    # .csv extension -> csv
    out_csv = tmp_path / "out.csv"
    r2 = CliRunner().invoke(
        cli,
        ["eval", "dataset", "export", str(out_csv), "--source", str(src_dir)],
    )
    assert r2.exit_code == 0, r2.output
    text = out_csv.read_text()
    assert text.startswith('"id","category","user_message"')


def test_cli_dataset_export_prints_count_summary(tmp_path):
    src_dir = tmp_path / "cases"
    src_dir.mkdir()
    _write_yaml_cases(src_dir / "suite.yaml", 5)

    out = tmp_path / "out.jsonl"
    r = CliRunner().invoke(
        cli,
        ["eval", "dataset", "export", str(out), "--source", str(src_dir)],
    )
    assert r.exit_code == 0, r.output
    assert "Exported 5 cases" in r.output
