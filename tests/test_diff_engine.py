"""Unit tests for the YAML-aware diff engine."""

from __future__ import annotations

import pytest

from optimizer.change_card import DiffHunk
from optimizer.diff_engine import DiffEngine, UnifiedDiff, _format_yaml_value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _baseline() -> dict:
    return {
        "model": "gpt-4",
        "generation_settings": {"temperature": 0.7, "max_tokens": 1000},
        "prompts": {"root": "Be helpful."},
    }


def _candidate() -> dict:
    return {
        "model": "gpt-4o",
        "generation_settings": {"temperature": 0.3, "max_tokens": 1000},
        "prompts": {"root": "Be helpful and concise."},
    }


# ---------------------------------------------------------------------------
# DiffEngine.compute_diff tests
# ---------------------------------------------------------------------------


class TestComputeDiff:
    def test_detects_all_changes(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())

        surfaces = {h.surface for h in diff.hunks}
        assert "model" in surfaces
        assert "generation_settings.temperature" in surfaces
        assert "prompts.root" in surfaces
        # max_tokens is unchanged
        assert "generation_settings.max_tokens" not in surfaces

    def test_hunk_count(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        assert len(diff.hunks) == 3

    def test_hashes_differ(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        assert diff.baseline_hash != ""
        assert diff.candidate_hash != ""
        assert diff.baseline_hash != diff.candidate_hash

    def test_all_hunks_pending(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        assert all(h.status == "pending" for h in diff.hunks)

    def test_no_changes_yields_empty_diff(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _baseline())
        assert len(diff.hunks) == 0

    def test_added_key(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff({"a": 1}, {"a": 1, "b": 2})
        assert len(diff.hunks) == 1
        assert diff.hunks[0].surface == "b"
        assert diff.hunks[0].old_value == "(not set)"

    def test_removed_key(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff({"a": 1, "b": 2}, {"a": 1})
        assert len(diff.hunks) == 1
        assert diff.hunks[0].surface == "b"
        assert diff.hunks[0].new_value == "(not set)"


# ---------------------------------------------------------------------------
# Hunk accept/reject tests
# ---------------------------------------------------------------------------


class TestHunkOperations:
    def test_accept_hunk(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        hunk_id = diff.hunks[0].hunk_id

        assert engine.accept_hunk(diff, hunk_id) is True
        assert diff.hunks[0].status == "accepted"

    def test_reject_hunk(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        hunk_id = diff.hunks[0].hunk_id

        assert engine.reject_hunk(diff, hunk_id) is True
        assert diff.hunks[0].status == "rejected"

    def test_accept_nonexistent_hunk(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        assert engine.accept_hunk(diff, "nonexistent") is False

    def test_reject_nonexistent_hunk(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        assert engine.reject_hunk(diff, "nonexistent") is False

    def test_accept_all(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        count = engine.accept_all(diff)
        assert count == 3
        assert all(h.status == "accepted" for h in diff.hunks)

    def test_reject_all(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        count = engine.reject_all(diff)
        assert count == 3
        assert all(h.status == "rejected" for h in diff.hunks)

    def test_accept_all_skips_non_pending(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        diff.hunks[0].status = "rejected"
        count = engine.accept_all(diff)
        assert count == 2
        assert diff.hunks[0].status == "rejected"


# ---------------------------------------------------------------------------
# apply_hunks tests
# ---------------------------------------------------------------------------


class TestApplyHunks:
    def test_apply_accepted_hunks(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        engine.accept_all(diff)

        result = engine.apply_hunks(_baseline(), diff)
        assert result["model"] == "gpt-4o"
        assert result["generation_settings"]["temperature"] == 0.3
        assert result["prompts"]["root"] == "Be helpful and concise."

    def test_skip_rejected_hunks(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        # Accept model change, reject temperature change
        for h in diff.hunks:
            if h.surface == "model":
                h.status = "accepted"
            else:
                h.status = "rejected"

        result = engine.apply_hunks(_baseline(), diff)
        assert result["model"] == "gpt-4o"
        assert result["generation_settings"]["temperature"] == 0.7  # unchanged
        assert result["prompts"]["root"] == "Be helpful."  # unchanged

    def test_skip_pending_hunks(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        # All pending by default — nothing applied
        result = engine.apply_hunks(_baseline(), diff)
        assert result == _baseline()

    def test_apply_creates_nested_keys(self) -> None:
        engine = DiffEngine()
        diff = UnifiedDiff(hunks=[
            DiffHunk(
                hunk_id="h1",
                surface="new_section.key",
                old_value="(not set)",
                new_value="value",
                status="accepted",
            )
        ])
        result = engine.apply_hunks({}, diff)
        assert result["new_section"]["key"] == "value"

    def test_apply_removes_key_on_not_set(self) -> None:
        engine = DiffEngine()
        diff = UnifiedDiff(hunks=[
            DiffHunk(
                hunk_id="h1",
                surface="model",
                old_value="gpt-4",
                new_value="(not set)",
                status="accepted",
            )
        ])
        result = engine.apply_hunks({"model": "gpt-4", "temp": 0.7}, diff)
        assert "model" not in result
        assert result["temp"] == 0.7


# ---------------------------------------------------------------------------
# Rendering tests
# ---------------------------------------------------------------------------


class TestRendering:
    def test_to_terminal_contains_hunks(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        output = engine.to_terminal(diff)
        assert "baseline" in output
        assert "candidate" in output
        assert "Hunk 1" in output

    def test_to_plain_no_ansi(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        output = engine.to_plain(diff)
        assert "\033[" not in output
        assert "Hunk 1" in output

    def test_to_terminal_shows_status_markers(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff({"a": 1}, {"a": 2})
        diff.hunks[0].status = "accepted"
        output = engine.to_plain(diff)
        assert "\u2713" in output


# ---------------------------------------------------------------------------
# UnifiedDiff.to_dict tests
# ---------------------------------------------------------------------------


class TestUnifiedDiffToDict:
    def test_to_dict_counts(self) -> None:
        engine = DiffEngine()
        diff = engine.compute_diff(_baseline(), _candidate())
        diff.hunks[0].status = "accepted"
        diff.hunks[1].status = "rejected"

        data = diff.to_dict()
        assert data["total_hunks"] == 3
        assert data["accepted_hunks"] == 1
        assert data["rejected_hunks"] == 1
        assert data["pending_hunks"] == 1


# ---------------------------------------------------------------------------
# _format_yaml_value tests
# ---------------------------------------------------------------------------


class TestFormatYamlValue:
    def test_none(self) -> None:
        assert _format_yaml_value(None) == "(not set)"

    def test_string(self) -> None:
        assert _format_yaml_value("hello") == "hello"

    def test_number(self) -> None:
        assert _format_yaml_value(42) == "42"

    def test_dict(self) -> None:
        result = _format_yaml_value({"key": "val"})
        assert "key" in result
        assert "val" in result
