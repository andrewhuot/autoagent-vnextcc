"""Unit tests for candidate sandbox isolation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from optimizer.sandbox import (
    CandidateSandbox,
    SandboxConfig,
    _deep_merge,
    _format_value,
    yaml_diff,
)


# ---------------------------------------------------------------------------
# CandidateSandbox tests
# ---------------------------------------------------------------------------


class TestCandidateSandbox:
    def test_creates_work_dir(self) -> None:
        with CandidateSandbox({"model": "gpt-4"}) as sb:
            assert Path(sb.work_dir).is_dir()
            assert sb.sandbox_id != ""

    def test_baseline_saved_to_yaml(self) -> None:
        with CandidateSandbox({"model": "gpt-4", "temp": 0.7}) as sb:
            baseline_path = Path(sb.work_dir) / "baseline.yaml"
            assert baseline_path.exists()
            loaded = yaml.safe_load(baseline_path.read_text())
            assert loaded["model"] == "gpt-4"
            assert loaded["temp"] == 0.7

    def test_baseline_config_is_deep_copy(self) -> None:
        original = {"model": "gpt-4", "nested": {"key": "val"}}
        with CandidateSandbox(original) as sb:
            baseline = sb.baseline_config
            baseline["nested"]["key"] = "changed"
            # Original should be unchanged
            assert sb.baseline_config["nested"]["key"] == "val"

    def test_candidate_none_before_mutation(self) -> None:
        with CandidateSandbox({"model": "gpt-4"}) as sb:
            assert sb.candidate_config is None

    def test_apply_mutation(self) -> None:
        with CandidateSandbox({"model": "gpt-4", "temp": 0.7}) as sb:
            result = sb.apply_mutation({"temp": 0.3, "top_k": 40})
            assert result["model"] == "gpt-4"
            assert result["temp"] == 0.3
            assert result["top_k"] == 40

            # Candidate saved to disk
            candidate_path = Path(sb.work_dir) / "candidate.yaml"
            assert candidate_path.exists()
            loaded = yaml.safe_load(candidate_path.read_text())
            assert loaded["temp"] == 0.3

    def test_apply_mutation_deep_merge(self) -> None:
        baseline = {"gen": {"temp": 0.7, "max_tokens": 1000}}
        with CandidateSandbox(baseline) as sb:
            result = sb.apply_mutation({"gen": {"temp": 0.3}})
            assert result["gen"]["temp"] == 0.3
            assert result["gen"]["max_tokens"] == 1000

    def test_set_candidate(self) -> None:
        with CandidateSandbox({"model": "gpt-4"}) as sb:
            sb.set_candidate({"model": "gpt-4o", "extra": True})
            candidate = sb.candidate_config
            assert candidate is not None
            assert candidate["model"] == "gpt-4o"
            assert candidate["extra"] is True

    def test_compute_diff_empty_without_candidate(self) -> None:
        with CandidateSandbox({"model": "gpt-4"}) as sb:
            assert sb.compute_diff() == []

    def test_compute_diff_detects_changes(self) -> None:
        with CandidateSandbox({"model": "gpt-4", "temp": 0.7}) as sb:
            sb.apply_mutation({"temp": 0.3})
            diffs = sb.compute_diff()
            assert len(diffs) == 1
            assert diffs[0]["surface"] == "temp"
            assert diffs[0]["old_value"] == "0.7"
            assert diffs[0]["new_value"] == "0.3"

    def test_cleanup_removes_directory(self) -> None:
        sb = CandidateSandbox({"model": "gpt-4"})
        work_dir = sb.work_dir
        assert Path(work_dir).is_dir()
        sb.cleanup()
        assert not Path(work_dir).exists()

    def test_context_manager_cleans_up(self) -> None:
        with CandidateSandbox({"model": "gpt-4"}) as sb:
            work_dir = sb.work_dir
        assert not Path(work_dir).exists()


# ---------------------------------------------------------------------------
# yaml_diff tests
# ---------------------------------------------------------------------------


class TestYamlDiff:
    def test_no_changes(self) -> None:
        assert yaml_diff({"a": 1}, {"a": 1}) == []

    def test_simple_change(self) -> None:
        diffs = yaml_diff({"a": 1}, {"a": 2})
        assert len(diffs) == 1
        assert diffs[0]["surface"] == "a"
        assert diffs[0]["old_value"] == "1"
        assert diffs[0]["new_value"] == "2"

    def test_added_key(self) -> None:
        diffs = yaml_diff({"a": 1}, {"a": 1, "b": 2})
        assert len(diffs) == 1
        assert diffs[0]["surface"] == "b"
        assert diffs[0]["old_value"] == "(not set)"

    def test_removed_key(self) -> None:
        diffs = yaml_diff({"a": 1, "b": 2}, {"a": 1})
        assert len(diffs) == 1
        assert diffs[0]["surface"] == "b"
        assert diffs[0]["new_value"] == "(not set)"

    def test_nested_change(self) -> None:
        old = {"gen": {"temp": 0.7, "max_tokens": 1000}}
        new = {"gen": {"temp": 0.3, "max_tokens": 1000}}
        diffs = yaml_diff(old, new)
        assert len(diffs) == 1
        assert diffs[0]["surface"] == "gen.temp"

    def test_deeply_nested(self) -> None:
        old = {"a": {"b": {"c": 1}}}
        new = {"a": {"b": {"c": 2}}}
        diffs = yaml_diff(old, new)
        assert diffs[0]["surface"] == "a.b.c"


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_simple_override(self) -> None:
        base = {"a": 1, "b": 2}
        _deep_merge(base, {"b": 3})
        assert base == {"a": 1, "b": 3}

    def test_add_new_key(self) -> None:
        base = {"a": 1}
        _deep_merge(base, {"b": 2})
        assert base == {"a": 1, "b": 2}

    def test_nested_merge(self) -> None:
        base = {"x": {"a": 1, "b": 2}}
        _deep_merge(base, {"x": {"b": 3, "c": 4}})
        assert base == {"x": {"a": 1, "b": 3, "c": 4}}


class TestFormatValue:
    def test_none(self) -> None:
        assert _format_value(None) == "(not set)"

    def test_string(self) -> None:
        assert _format_value("hello") == "hello"

    def test_number(self) -> None:
        assert _format_value(42) == "42"

    def test_dict(self) -> None:
        result = _format_value({"a": 1})
        assert "a" in result


class TestSandboxConfig:
    def test_auto_generates_id(self) -> None:
        cfg = SandboxConfig()
        assert cfg.sandbox_id != ""
        assert len(cfg.sandbox_id) == 8

    def test_preserves_explicit_id(self) -> None:
        cfg = SandboxConfig(sandbox_id="my-id")
        assert cfg.sandbox_id == "my-id"
