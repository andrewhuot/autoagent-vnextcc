"""Tests for TestCase.tags field and load-time category fallback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.runner import EvalRunner, TestCase


def test_testcase_tags_default_empty() -> None:
    """Direct dataclass construction leaves tags as an empty list."""
    case = TestCase(
        id="x",
        category="safety",
        user_message="hi",
        expected_specialist="support",
        expected_behavior="refuse",
    )
    assert case.tags == []


def test_testcase_tags_explicit() -> None:
    """Explicit tags passed to TestCase are preserved verbatim."""
    case = TestCase(
        id="x",
        category="safety",
        user_message="hi",
        expected_specialist="support",
        expected_behavior="refuse",
        tags=["a", "b"],
    )
    assert case.tags == ["a", "b"]


def test_load_cases_defaults_tags_to_category(tmp_path: Path) -> None:
    """YAML case without tags key → TestCase.tags == [category] after load."""
    yaml_file = tmp_path / "cases.yaml"
    yaml_file.write_text(
        """
cases:
  - id: c1
    category: safety
    user_message: hello
    expected_specialist: support
    expected_behavior: refuse
""".strip()
    )

    runner = EvalRunner(cases_dir=str(tmp_path))
    cases = runner.load_cases()
    assert len(cases) == 1
    assert cases[0].category == "safety"
    assert cases[0].tags == ["safety"]


def test_load_cases_respects_explicit_tags(tmp_path: Path) -> None:
    """YAML case with tags: [safety, slow] → tags preserved verbatim."""
    yaml_file = tmp_path / "cases.yaml"
    yaml_file.write_text(
        """
cases:
  - id: c1
    category: safety
    user_message: hello
    expected_specialist: support
    expected_behavior: refuse
    tags:
      - safety
      - slow
""".strip()
    )

    runner = EvalRunner(cases_dir=str(tmp_path))
    cases = runner.load_cases()
    assert len(cases) == 1
    assert cases[0].tags == ["safety", "slow"]


def test_load_dataset_cases_defaults_tags_to_category(tmp_path: Path) -> None:
    """JSONL row without tags field → TestCase.tags == [category] after load."""
    dataset_path = tmp_path / "dataset.jsonl"
    row = {
        "id": "row1",
        "category": "billing",
        "user_message": "charge me",
        "expected_specialist": "support",
        "expected_behavior": "answer",
        "split": "train",
    }
    dataset_path.write_text(json.dumps(row) + "\n")

    runner = EvalRunner()
    cases = runner.load_dataset_cases(str(dataset_path))
    assert len(cases) == 1
    assert cases[0].category == "billing"
    assert cases[0].tags == ["billing"]


def test_load_dataset_cases_respects_explicit_tags(tmp_path: Path) -> None:
    """JSONL row with explicit tags → preserved verbatim."""
    dataset_path = tmp_path / "dataset.jsonl"
    row = {
        "id": "row1",
        "category": "billing",
        "user_message": "charge me",
        "expected_specialist": "support",
        "expected_behavior": "answer",
        "split": "train",
        "tags": ["x"],
    }
    dataset_path.write_text(json.dumps(row) + "\n")

    runner = EvalRunner()
    cases = runner.load_dataset_cases(str(dataset_path))
    assert len(cases) == 1
    assert cases[0].tags == ["x"]
