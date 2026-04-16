"""Tests for evals.dataset.importers.load_csv (A.3).

CSV row contract: thin free-function importer that turns CSV rows into
TestCase objects. Pipe-delimited lists for expected_keywords and tags.
Honors the tags-inherit-from-category contract from A.1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.dataset.importers import load_csv
from evals.runner import TestCase


def _write_csv(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_load_csv_returns_list_of_testcase(tmp_path: Path) -> None:
    path = tmp_path / "two.csv"
    _write_csv(
        path,
        "id,category,user_message\n"
        "a,safety,hello\n"
        "b,billing,charge me\n",
    )

    cases = load_csv(path)
    assert isinstance(cases, list)
    assert len(cases) == 2
    assert all(isinstance(c, TestCase) for c in cases)
    assert cases[0].id == "a"
    assert cases[1].id == "b"


def test_load_csv_all_fields_populated(tmp_path: Path) -> None:
    path = tmp_path / "full.csv"
    _write_csv(
        path,
        "id,category,user_message,expected_specialist,expected_behavior,safety_probe,"
        "expected_keywords,expected_tool,split,reference_answer,tags\n"
        "c1,billing,where is my order,orders,answer,true,"
        "order|tracking,lookup_order,train,Your order is en route,billing|urgent\n",
    )

    cases = load_csv(path)
    assert len(cases) == 1
    case = cases[0]
    assert case.id == "c1"
    assert case.category == "billing"
    assert case.user_message == "where is my order"
    assert case.expected_specialist == "orders"
    assert case.expected_behavior == "answer"
    assert case.safety_probe is True
    assert case.expected_keywords == ["order", "tracking"]
    assert case.expected_tool == "lookup_order"
    assert case.split == "train"
    assert case.reference_answer == "Your order is en route"
    assert case.tags == ["billing", "urgent"]


def test_load_csv_defaults_applied(tmp_path: Path) -> None:
    path = tmp_path / "defaults.csv"
    _write_csv(
        path,
        "id,category,user_message\n"
        "d1,safety,stay safe\n",
    )

    cases = load_csv(path)
    assert len(cases) == 1
    case = cases[0]
    assert case.expected_specialist == "support"
    assert case.expected_behavior == "answer"
    assert case.safety_probe is False
    assert case.expected_keywords == []
    assert case.expected_tool is None
    assert case.split is None
    assert case.reference_answer == ""
    # tags falls back to [category]
    assert case.tags == ["safety"]


def test_load_csv_explicit_tags_win(tmp_path: Path) -> None:
    path = tmp_path / "tags.csv"
    _write_csv(
        path,
        "id,category,user_message,tags\n"
        "t1,safety,hi,custom|override\n",
    )

    cases = load_csv(path)
    assert cases[0].tags == ["custom", "override"]


def test_load_csv_missing_required_header_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad_header.csv"
    _write_csv(
        path,
        "id,category\n"
        "x,safety\n",
    )

    with pytest.raises(ValueError) as excinfo:
        load_csv(path)
    assert "user_message" in str(excinfo.value)


def test_load_csv_missing_required_value_raises(tmp_path: Path) -> None:
    path = tmp_path / "missing_val.csv"
    _write_csv(
        path,
        "id,category,user_message\n"
        "ok,safety,hi\n"
        ",billing,hello\n",
    )

    with pytest.raises(ValueError) as excinfo:
        load_csv(path)
    msg = str(excinfo.value)
    assert "id" in msg
    # second data row is data-row 2
    assert "2" in msg


def test_load_csv_invalid_bool_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad_bool.csv"
    _write_csv(
        path,
        "id,category,user_message,safety_probe\n"
        "x,safety,hi,maybe\n",
    )

    with pytest.raises(ValueError) as excinfo:
        load_csv(path)
    # first data row is data-row 1
    assert "1" in str(excinfo.value)


def test_load_csv_no_header_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    _write_csv(path, "")

    with pytest.raises(ValueError) as excinfo:
        load_csv(path)
    assert "no header" in str(excinfo.value).lower()


def test_load_csv_header_only_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "header_only.csv"
    _write_csv(path, "id,category,user_message\n")

    cases = load_csv(path)
    assert cases == []


def test_load_csv_pipe_delimited_keywords(tmp_path: Path) -> None:
    path = tmp_path / "kw.csv"
    _write_csv(
        path,
        "id,category,user_message,expected_keywords\n"
        "k1,safety,hi,alpha|beta|gamma\n"
        "k2,safety,hey,\n",
    )

    cases = load_csv(path)
    assert cases[0].expected_keywords == ["alpha", "beta", "gamma"]
    assert cases[1].expected_keywords == []


def test_load_csv_accepts_path_or_str(tmp_path: Path) -> None:
    path = tmp_path / "p.csv"
    _write_csv(
        path,
        "id,category,user_message\n"
        "p1,safety,hi\n",
    )

    from_path = load_csv(path)
    from_str = load_csv(str(path))
    assert len(from_path) == 1
    assert len(from_str) == 1
    assert from_path[0].id == from_str[0].id == "p1"
