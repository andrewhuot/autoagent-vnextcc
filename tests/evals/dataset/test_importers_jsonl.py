"""Tests for evals.dataset.importers.load_jsonl (A.2).

JSONL row contract: thin free-function importer that turns JSONL lines into
TestCase objects, honoring the tags-inherit-from-category contract from A.1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.dataset.importers import load_jsonl
from evals.runner import TestCase


def _write_jsonl(path: Path, rows: list[dict | str]) -> None:
    lines: list[str] = []
    for row in rows:
        if isinstance(row, str):
            lines.append(row)
        else:
            lines.append(json.dumps(row))
    path.write_text("\n".join(lines) + "\n")


def test_load_jsonl_returns_list_of_testcase(tmp_path: Path) -> None:
    path = tmp_path / "two.jsonl"
    _write_jsonl(
        path,
        [
            {"id": "a", "category": "safety", "user_message": "hello"},
            {"id": "b", "category": "billing", "user_message": "charge me"},
        ],
    )

    cases = load_jsonl(path)
    assert isinstance(cases, list)
    assert len(cases) == 2
    assert all(isinstance(c, TestCase) for c in cases)
    assert cases[0].id == "a"
    assert cases[1].id == "b"


def test_load_jsonl_all_fields_populated(tmp_path: Path) -> None:
    path = tmp_path / "full.jsonl"
    row = {
        "id": "c1",
        "category": "safety",
        "user_message": "probe",
        "expected_specialist": "ops",
        "expected_behavior": "refuse",
        "safety_probe": True,
        "expected_keywords": ["k1", "k2"],
        "expected_tool": "search",
        "split": "test",
        "reference_answer": "the answer",
        "tags": ["safety", "slow"],
    }
    _write_jsonl(path, [row])

    cases = load_jsonl(path)
    assert len(cases) == 1
    c = cases[0]
    assert c.id == "c1"
    assert c.category == "safety"
    assert c.user_message == "probe"
    assert c.expected_specialist == "ops"
    assert c.expected_behavior == "refuse"
    assert c.safety_probe is True
    assert c.expected_keywords == ["k1", "k2"]
    assert c.expected_tool == "search"
    assert c.split == "test"
    assert c.reference_answer == "the answer"
    assert c.tags == ["safety", "slow"]


def test_load_jsonl_defaults_applied(tmp_path: Path) -> None:
    path = tmp_path / "min.jsonl"
    _write_jsonl(
        path,
        [{"id": "m1", "category": "billing", "user_message": "hi"}],
    )

    cases = load_jsonl(path)
    assert len(cases) == 1
    c = cases[0]
    assert c.expected_specialist == "support"
    assert c.expected_behavior == "answer"
    assert c.safety_probe is False
    assert c.expected_keywords == []
    assert c.expected_tool is None
    assert c.split is None
    assert c.reference_answer == ""
    # tags inherits [category] when missing
    assert c.tags == ["billing"]


def test_load_jsonl_explicit_tags_win(tmp_path: Path) -> None:
    path = tmp_path / "tagged.jsonl"
    _write_jsonl(
        path,
        [
            {
                "id": "t1",
                "category": "billing",
                "user_message": "hi",
                "tags": ["a", "b"],
            }
        ],
    )

    cases = load_jsonl(path)
    assert cases[0].tags == ["a", "b"]


def test_load_jsonl_missing_required_field_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    _write_jsonl(
        path,
        [
            {"id": "ok", "category": "x", "user_message": "hello"},
            {"id": "nope", "category": "x"},  # missing user_message
        ],
    )

    with pytest.raises(ValueError) as exc:
        load_jsonl(path)
    msg = str(exc.value)
    assert "user_message" in msg
    # line 2 is the offending one (1-indexed)
    assert "2" in msg


def test_load_jsonl_malformed_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "malformed.jsonl"
    path.write_text(
        json.dumps({"id": "a", "category": "c", "user_message": "m"}) + "\n"
        + "{not json\n"
    )

    with pytest.raises(ValueError) as exc:
        load_jsonl(path)
    msg = str(exc.value)
    assert "2" in msg  # line number


def test_load_jsonl_skips_blank_and_comment_lines(tmp_path: Path) -> None:
    path = tmp_path / "comments.jsonl"
    path.write_text(
        "\n"
        "# this is a comment\n"
        + json.dumps({"id": "a", "category": "c", "user_message": "m"}) + "\n"
        "\n"
        "   \n"
        "# another comment\n"
        + json.dumps({"id": "b", "category": "c", "user_message": "m2"}) + "\n"
    )

    cases = load_jsonl(path)
    assert [c.id for c in cases] == ["a", "b"]


def test_load_jsonl_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert load_jsonl(empty) == []

    whitespace = tmp_path / "ws.jsonl"
    whitespace.write_text("\n   \n\t\n")
    assert load_jsonl(whitespace) == []


def test_load_jsonl_accepts_path_or_str(tmp_path: Path) -> None:
    path = tmp_path / "p.jsonl"
    _write_jsonl(
        path,
        [{"id": "a", "category": "c", "user_message": "m"}],
    )

    from_path = load_jsonl(path)
    from_str = load_jsonl(str(path))
    assert len(from_path) == 1
    assert len(from_str) == 1
    assert from_path[0].id == from_str[0].id == "a"


def test_load_jsonl_empty_tags_list_inherits_category(tmp_path: Path) -> None:
    """Explicit empty tags list should fall back to [category]."""
    path = tmp_path / "empty_tags.jsonl"
    _write_jsonl(
        path,
        [
            {
                "id": "e1",
                "category": "safety",
                "user_message": "hi",
                "tags": [],
            }
        ],
    )

    cases = load_jsonl(path)
    assert cases[0].tags == ["safety"]
