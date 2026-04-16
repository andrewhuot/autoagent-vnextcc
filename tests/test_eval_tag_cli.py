"""Tests for `agentlab eval run --tag/--exclude-tag` (R5 Slice C.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from runner import cli


def _write_yaml_cases(path: Path) -> None:
    """Write a 3-case YAML suite with mixed tags."""
    cases = [
        {
            "id": "c_safety",
            "category": "safety",
            "user_message": "refuse me",
            "expected_specialist": "support",
            "expected_behavior": "refuse",
            "tags": ["safety"],
        },
        {
            "id": "c_billing",
            "category": "billing",
            "user_message": "charge",
            "expected_specialist": "support",
            "expected_behavior": "answer",
            "tags": ["billing"],
        },
        {
            "id": "c_edge",
            "category": "edge",
            "user_message": "weird",
            "expected_specialist": "support",
            "expected_behavior": "answer",
            "tags": ["edge", "slow"],
        },
    ]
    path.write_text(yaml.safe_dump({"cases": cases}), encoding="utf-8")


def _write_jsonl_dataset(path: Path) -> None:
    rows = [
        {
            "id": "r_safety",
            "category": "safety",
            "user_message": "a",
            "expected_specialist": "support",
            "expected_behavior": "refuse",
            "split": "train",
            "tags": ["safety"],
        },
        {
            "id": "r_billing",
            "category": "billing",
            "user_message": "b",
            "expected_specialist": "support",
            "expected_behavior": "answer",
            "split": "train",
            "tags": ["billing"],
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Help text — flag presence
# ---------------------------------------------------------------------------


def test_cli_eval_run_accepts_tag_flag() -> None:
    """`agentlab eval run --help` advertises --tag and --exclude-tag."""
    result = CliRunner().invoke(cli, ["eval", "run", "--help"])
    assert result.exit_code == 0, result.output
    assert "--tag" in result.output
    assert "--exclude-tag" in result.output


# ---------------------------------------------------------------------------
# Plumbing via monkeypatch on EvalRunner.load_cases
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_kwargs(monkeypatch):
    """Patch EvalRunner.load_cases / load_dataset_cases to record filter kwargs."""
    captured: dict[str, dict] = {}

    from evals import runner as evals_runner

    original_load_cases = evals_runner.EvalRunner.load_cases
    original_load_dataset = evals_runner.EvalRunner.load_dataset_cases

    def spy_load_cases(self, *, tags=None, exclude_tags=None):
        captured["load_cases"] = {"tags": tags, "exclude_tags": exclude_tags}
        return original_load_cases(self, tags=tags, exclude_tags=exclude_tags)

    def spy_load_dataset(self, dataset_path, *, split="all", train_ratio=0.8, tags=None, exclude_tags=None):
        captured["load_dataset_cases"] = {
            "tags": tags,
            "exclude_tags": exclude_tags,
            "split": split,
        }
        return original_load_dataset(
            self,
            dataset_path,
            split=split,
            train_ratio=train_ratio,
            tags=tags,
            exclude_tags=exclude_tags,
        )

    monkeypatch.setattr(evals_runner.EvalRunner, "load_cases", spy_load_cases)
    monkeypatch.setattr(
        evals_runner.EvalRunner, "load_dataset_cases", spy_load_dataset
    )
    return captured


def _invoke_eval_run(args: list[str]) -> object:
    """Invoke `agentlab eval run` with --mock so we hit no network."""
    return CliRunner().invoke(cli, ["eval", "run", "--mock", *args])


def test_cli_eval_run_tag_filter_narrows_suite(tmp_path, captured_kwargs) -> None:
    suite_dir = tmp_path / "cases"
    suite_dir.mkdir()
    _write_yaml_cases(suite_dir / "cases.yaml")

    result = _invoke_eval_run(["--suite", str(suite_dir), "--tag", "safety"])
    assert result.exit_code == 0, result.output

    assert "load_cases" in captured_kwargs
    assert captured_kwargs["load_cases"]["tags"] == ["safety"]
    assert captured_kwargs["load_cases"]["exclude_tags"] is None


def test_cli_eval_run_exclude_tag_filter_drops_cases(tmp_path, captured_kwargs) -> None:
    suite_dir = tmp_path / "cases"
    suite_dir.mkdir()
    _write_yaml_cases(suite_dir / "cases.yaml")

    result = _invoke_eval_run(["--suite", str(suite_dir), "--exclude-tag", "slow"])
    assert result.exit_code == 0, result.output

    assert captured_kwargs["load_cases"]["tags"] is None
    assert captured_kwargs["load_cases"]["exclude_tags"] == ["slow"]


def test_cli_eval_run_multiple_tag_flags_or_together(tmp_path, captured_kwargs) -> None:
    suite_dir = tmp_path / "cases"
    suite_dir.mkdir()
    _write_yaml_cases(suite_dir / "cases.yaml")

    result = _invoke_eval_run(
        ["--suite", str(suite_dir), "--tag", "safety", "--tag", "billing"]
    )
    assert result.exit_code == 0, result.output

    assert captured_kwargs["load_cases"]["tags"] == ["safety", "billing"]


def test_cli_eval_run_tag_works_with_dataset_flag(tmp_path, captured_kwargs) -> None:
    dataset_path = tmp_path / "ds.jsonl"
    _write_jsonl_dataset(dataset_path)

    result = _invoke_eval_run(
        [
            "--dataset",
            str(dataset_path),
            "--tag",
            "safety",
            "--exclude-tag",
            "billing",
        ]
    )
    assert result.exit_code == 0, result.output

    assert "load_dataset_cases" in captured_kwargs
    assert captured_kwargs["load_dataset_cases"]["tags"] == ["safety"]
    assert captured_kwargs["load_dataset_cases"]["exclude_tags"] == ["billing"]
