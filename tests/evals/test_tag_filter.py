"""Tests for tag-based filtering in EvalRunner (R5 Slice C.1).

Covers the private ``_apply_tag_filters`` helper plus integration through
``EvalRunner.load_cases`` and ``EvalRunner.load_dataset_cases``.
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.runner import EvalRunner, TestCase, _apply_tag_filters


def _make_case(case_id: str, tags: list[str], category: str | None = None) -> TestCase:
    return TestCase(
        id=case_id,
        category=category or (tags[0] if tags else "unknown"),
        user_message="hi",
        expected_specialist="support",
        expected_behavior="answer",
        tags=list(tags),
    )


# ---------------------------------------------------------------------------
# _apply_tag_filters — unit tests
# ---------------------------------------------------------------------------


def test_apply_tag_filters_none_returns_all() -> None:
    cases = [_make_case("a", ["x"]), _make_case("b", ["y"])]
    result = _apply_tag_filters(cases, None, None)
    assert result == cases


def test_apply_tag_filters_include_single_tag() -> None:
    cases = [
        _make_case("a", ["safety"]),
        _make_case("b", ["billing"]),
        _make_case("c", ["safety", "slow"]),
    ]
    result = _apply_tag_filters(cases, ["safety"], None)
    assert [c.id for c in result] == ["a", "c"]


def test_apply_tag_filters_include_or_semantics() -> None:
    cases = [
        _make_case("a", ["a"]),
        _make_case("b", ["b"]),
        _make_case("c", ["c"]),
    ]
    result = _apply_tag_filters(cases, ["a", "b"], None)
    assert [c.id for c in result] == ["a", "b"]


def test_apply_tag_filters_exclude_single_tag() -> None:
    cases = [
        _make_case("a", ["safety"]),
        _make_case("b", ["slow"]),
        _make_case("c", ["safety"]),
    ]
    result = _apply_tag_filters(cases, None, ["slow"])
    assert [c.id for c in result] == ["a", "c"]


def test_apply_tag_filters_exclude_drops_if_any_match() -> None:
    """exclude=['slow','long'] drops any case matching either. The plan's
    'AND across exclude flags' collapses to the same behavior: each exclude
    filter must pass, i.e., case must not have any of the excluded tags.
    """
    cases = [
        _make_case("a_slow", ["slow"]),
        _make_case("b_long", ["long"]),
        _make_case("c_both", ["slow", "long"]),
        _make_case("d_neither", ["safety"]),
    ]
    result = _apply_tag_filters(cases, None, ["slow", "long"])
    assert [c.id for c in result] == ["d_neither"]


def test_apply_tag_filters_include_and_exclude_compose() -> None:
    cases = [
        _make_case("ab", ["a", "b"]),
        _make_case("a_only", ["a"]),
        _make_case("b_only", ["b"]),
    ]
    result = _apply_tag_filters(cases, ["a"], ["b"])
    assert [c.id for c in result] == ["a_only"]


def test_apply_tag_filters_empty_lists_are_noop() -> None:
    cases = [_make_case("a", ["x"]), _make_case("b", ["y"])]
    assert _apply_tag_filters(cases, [], []) == cases
    assert _apply_tag_filters(cases, [], None) == cases
    assert _apply_tag_filters(cases, None, []) == cases


def test_apply_tag_filters_does_not_mutate_input() -> None:
    cases = [_make_case("a", ["x"]), _make_case("b", ["y"])]
    original = list(cases)
    _apply_tag_filters(cases, ["x"], ["y"])
    assert cases == original
    assert cases[0].tags == ["x"]


def test_apply_tag_filters_case_sensitive() -> None:
    """Tags are compared case-sensitively — 'Safety' != 'safety'."""
    cases = [
        _make_case("a", ["Safety"]),
        _make_case("b", ["safety"]),
    ]
    result = _apply_tag_filters(cases, ["safety"], None)
    assert [c.id for c in result] == ["b"]


# ---------------------------------------------------------------------------
# load_cases integration
# ---------------------------------------------------------------------------


def test_load_cases_tag_filter_integration(tmp_path: Path) -> None:
    """YAML suite with mixed tags filtered down to 'safety' cases."""
    yaml_file = tmp_path / "cases.yaml"
    yaml_file.write_text(
        """
cases:
  - id: c1
    category: safety
    user_message: hello
    expected_specialist: support
    expected_behavior: refuse
    tags: [safety]
  - id: c2
    category: billing
    user_message: charge
    expected_specialist: support
    expected_behavior: answer
    tags: [billing]
  - id: c3
    category: edge
    user_message: weird
    expected_specialist: support
    expected_behavior: answer
    tags: [safety, slow]
""".strip()
    )

    runner = EvalRunner(cases_dir=str(tmp_path))
    cases = runner.load_cases(tags=["safety"])
    assert sorted(c.id for c in cases) == ["c1", "c3"]

    # Default (no kwargs) returns all.
    assert len(runner.load_cases()) == 3

    # Exclude works too.
    excluded = runner.load_cases(exclude_tags=["slow"])
    assert sorted(c.id for c in excluded) == ["c1", "c2"]


def test_load_dataset_cases_tag_filter_integration(tmp_path: Path) -> None:
    """JSONL dataset with tagged rows → tag filter narrows down."""
    dataset_path = tmp_path / "dataset.jsonl"
    rows = [
        {
            "id": "r1",
            "category": "safety",
            "user_message": "a",
            "expected_specialist": "support",
            "expected_behavior": "refuse",
            "split": "train",
            "tags": ["safety"],
        },
        {
            "id": "r2",
            "category": "billing",
            "user_message": "b",
            "expected_specialist": "support",
            "expected_behavior": "answer",
            "split": "train",
            "tags": ["billing"],
        },
        {
            "id": "r3",
            "category": "edge",
            "user_message": "c",
            "expected_specialist": "support",
            "expected_behavior": "answer",
            "split": "train",
            "tags": ["safety", "slow"],
        },
    ]
    dataset_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    runner = EvalRunner()

    cases = runner.load_dataset_cases(str(dataset_path), tags=["safety"])
    assert sorted(c.id for c in cases) == ["r1", "r3"]

    # Default returns all.
    assert len(runner.load_dataset_cases(str(dataset_path))) == 3

    # Combine include + exclude.
    filtered = runner.load_dataset_cases(
        str(dataset_path), tags=["safety"], exclude_tags=["slow"]
    )
    assert [c.id for c in filtered] == ["r1"]
