"""Tests for evals.dataset.exporters (A.5).

JSONL exporter must be byte-identity round-trip with the golden fixture.
CSV exporter round-trips semantically (tags sort-canonicalized).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.dataset import export_csv, export_jsonl, load_csv, load_jsonl
from evals.runner import TestCase

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "golden_cases.jsonl"


def _mk(**overrides) -> TestCase:
    base: dict = {
        "id": "x",
        "category": "general",
        "user_message": "msg",
        "expected_specialist": "support",
        "expected_behavior": "answer",
    }
    base.update(overrides)
    return TestCase(**base)


# ---------------------------------------------------------------- JSONL tests


def test_export_jsonl_writes_file(tmp_path: Path) -> None:
    cases = [_mk(id="a"), _mk(id="b"), _mk(id="c")]
    out = tmp_path / "out.jsonl"
    export_jsonl(cases, out)
    assert out.exists()
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert all(line.strip() for line in lines)


def test_export_jsonl_sorted_keys(tmp_path: Path) -> None:
    cases = [_mk(id="a", tags=["b", "a"])]
    out = tmp_path / "out.jsonl"
    export_jsonl(cases, out)
    line = out.read_text(encoding="utf-8").strip()
    # Extract keys in the order they appear in the serialized string
    decoded = json.loads(line)
    # The raw string should have keys alphabetical
    keys_in_output: list[str] = []
    for token in line.split('"'):
        if token and token.endswith(":") or token in decoded.keys():
            if token in decoded.keys() and token not in keys_in_output:
                keys_in_output.append(token)
    assert keys_in_output == sorted(decoded.keys())


def test_export_jsonl_sorted_tags(tmp_path: Path) -> None:
    cases = [_mk(id="a", tags=["zebra", "apple"])]
    out = tmp_path / "out.jsonl"
    export_jsonl(cases, out)
    line = out.read_text(encoding="utf-8").strip()
    # Match the exact substring (tags serialized alphabetically).
    assert '"tags": ["apple", "zebra"]' in line


def test_export_jsonl_preserves_keyword_order(tmp_path: Path) -> None:
    cases = [_mk(id="a", expected_keywords=["b", "a", "c"])]
    out = tmp_path / "out.jsonl"
    export_jsonl(cases, out)
    decoded = json.loads(out.read_text(encoding="utf-8").strip())
    assert decoded["expected_keywords"] == ["b", "a", "c"]


def test_export_jsonl_trailing_newline_exactly_one(tmp_path: Path) -> None:
    cases = [_mk(id="a"), _mk(id="b")]
    out = tmp_path / "out.jsonl"
    export_jsonl(cases, out)
    raw = out.read_bytes()
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")


def test_export_jsonl_non_ascii_roundtrip(tmp_path: Path) -> None:
    cases = [_mk(id="a", user_message="héllo 世界")]
    out = tmp_path / "out.jsonl"
    export_jsonl(cases, out)
    loaded = load_jsonl(out)
    assert loaded[0].user_message == "héllo 世界"


def test_export_jsonl_empty_cases_produces_empty_file(tmp_path: Path) -> None:
    out = tmp_path / "out.jsonl"
    export_jsonl([], out)
    assert out.exists()
    assert out.read_bytes() == b""


def test_export_jsonl_missing_parent_dir_raises(tmp_path: Path) -> None:
    cases = [_mk(id="a")]
    out = tmp_path / "nope" / "nested" / "out.jsonl"
    with pytest.raises(FileNotFoundError) as exc:
        export_jsonl(cases, out)
    assert "parent" in str(exc.value).lower() or "director" in str(exc.value).lower()


def test_export_jsonl_matches_golden_bytes(tmp_path: Path) -> None:
    golden = GOLDEN_PATH.read_bytes()
    cases = load_jsonl(GOLDEN_PATH)
    assert len(cases) == 20, f"Golden fixture must have 20 cases, got {len(cases)}"
    out = tmp_path / "out.jsonl"
    export_jsonl(cases, out)
    assert out.read_bytes() == golden


def test_export_jsonl_accepts_str_path(tmp_path: Path) -> None:
    cases = [_mk(id="a")]
    out = tmp_path / "out.jsonl"
    export_jsonl(cases, str(out))
    assert out.exists()


# ------------------------------------------------------------------ CSV tests


def test_export_csv_has_header_row(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    export_csv([_mk(id="a")], out)
    first_line = out.read_text(encoding="utf-8").splitlines()[0]
    expected_columns = {
        "id",
        "category",
        "user_message",
        "expected_specialist",
        "expected_behavior",
        "safety_probe",
        "expected_keywords",
        "expected_tool",
        "split",
        "reference_answer",
        "tags",
    }
    # header is quoted in quote-all dialect, strip quotes before comparing
    header_fields = [c.strip('"') for c in first_line.split(",")]
    assert set(header_fields) == expected_columns
    assert len(header_fields) == 11


def test_export_csv_round_trip_semantic(tmp_path: Path) -> None:
    cases = load_jsonl(GOLDEN_PATH)
    out = tmp_path / "out.csv"
    export_csv(cases, out)
    reloaded = load_csv(out)
    assert len(reloaded) == len(cases)

    for original, loaded in zip(cases, reloaded, strict=True):
        assert original.id == loaded.id
        assert original.category == loaded.category
        assert original.user_message == loaded.user_message
        assert original.expected_specialist == loaded.expected_specialist
        assert original.expected_behavior == loaded.expected_behavior
        assert original.safety_probe == loaded.safety_probe
        assert original.expected_keywords == loaded.expected_keywords
        assert original.expected_tool == loaded.expected_tool
        assert original.split == loaded.split
        assert original.reference_answer == loaded.reference_answer
        # tags may be re-ordered by the exporter's canonicalization.
        assert sorted(original.tags) == sorted(loaded.tags)


def test_export_csv_bool_and_null_encoding(tmp_path: Path) -> None:
    cases = [
        _mk(id="a", safety_probe=True, expected_tool="search", split="train"),
        _mk(id="b", safety_probe=False, expected_tool=None, split=None),
    ]
    out = tmp_path / "out.csv"
    export_csv(cases, out)
    text = out.read_text(encoding="utf-8")
    lines = text.splitlines()
    # Data rows start at index 1.
    assert '"true"' in lines[1]
    assert '"search"' in lines[1]
    assert '"train"' in lines[1]
    assert '"false"' in lines[2]
    # expected_tool and split for case b should be the empty quoted string.
    assert '""' in lines[2]


def test_export_csv_empty_cases_writes_header_only(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    export_csv([], out)
    text = out.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line]
    assert len(lines) == 1  # header only


def test_export_csv_accepts_str_path(tmp_path: Path) -> None:
    cases = [_mk(id="a")]
    out = tmp_path / "out.csv"
    export_csv(cases, str(out))
    assert out.exists()


def test_export_csv_missing_parent_dir_raises(tmp_path: Path) -> None:
    cases = [_mk(id="a")]
    out = tmp_path / "nope" / "out.csv"
    with pytest.raises(FileNotFoundError):
        export_csv(cases, out)
