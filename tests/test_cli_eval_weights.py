"""Tests for `agentlab eval weights {show|set|validate}` subcommand (R3.10)."""

from pathlib import Path

import yaml
from click.testing import CliRunner


def _cli():
    import runner
    return runner.cli


def test_eval_weights_show_reads_yaml(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agentlab.yaml").write_text(
        "eval:\n"
        "  composite:\n"
        "    weights:\n"
        "      quality: 0.45\n"
        "      safety: 0.25\n"
        "      latency: 0.15\n"
        "      cost: 0.15\n"
    )
    result = CliRunner().invoke(_cli(), ["eval", "weights", "show"])
    assert result.exit_code == 0, result.output
    assert "quality" in result.output and "0.45" in result.output
    assert "safety" in result.output and "0.25" in result.output
    assert "latency" in result.output and "0.15" in result.output
    assert "cost" in result.output and "0.15" in result.output


def test_eval_weights_show_defaults_when_no_yaml(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # No agentlab.yaml in cwd
    result = CliRunner().invoke(_cli(), ["eval", "weights", "show"])
    assert result.exit_code == 0, result.output
    assert "0.4" in result.output  # default quality


def test_eval_weights_set_creates_section_in_existing_yaml(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    yml = tmp_path / "agentlab.yaml"
    yml.write_text("harness:\n  models: {}\n")
    result = CliRunner().invoke(_cli(), [
        "eval", "weights", "set",
        "--quality", "0.5",
        "--safety", "0.2",
        "--latency", "0.15",
        "--cost", "0.15",
    ])
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(yml.read_text())
    assert data["eval"]["composite"]["weights"]["quality"] == 0.5
    assert data["eval"]["composite"]["weights"]["safety"] == 0.2
    assert data["eval"]["composite"]["weights"]["latency"] == 0.15
    assert data["eval"]["composite"]["weights"]["cost"] == 0.15
    # Existing keys preserved
    assert "harness" in data


def test_eval_weights_set_preserves_sibling_eval_keys(tmp_path, monkeypatch) -> None:
    """The eval.* section may already contain other keys (history_db_path,
    cache_enabled, etc.). `set` must not clobber them."""
    monkeypatch.chdir(tmp_path)
    yml = tmp_path / "agentlab.yaml"
    yml.write_text(
        "eval:\n"
        "  history_db_path: eval_history.db\n"
        "  cache_enabled: true\n"
    )
    result = CliRunner().invoke(_cli(), [
        "eval", "weights", "set",
        "--quality", "0.4", "--safety", "0.3",
        "--latency", "0.2", "--cost", "0.1",
    ])
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(yml.read_text())
    assert data["eval"]["history_db_path"] == "eval_history.db"
    assert data["eval"]["cache_enabled"] is True
    assert data["eval"]["composite"]["weights"]["quality"] == 0.4


def test_eval_weights_set_rejects_bad_sum(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agentlab.yaml").write_text("harness: {}\n")
    result = CliRunner().invoke(_cli(), [
        "eval", "weights", "set",
        "--quality", "0.9",  # sum = 0.9+0.25+0.2+0.15 = 1.5 → reject
        "--safety", "0.25",
        "--latency", "0.2",
        "--cost", "0.15",
    ])
    assert result.exit_code != 0
    assert "sum" in result.output.lower() or "1.0" in result.output


def test_eval_weights_validate_ok(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agentlab.yaml").write_text(
        "eval:\n  composite:\n    weights:\n"
        "      quality: 0.4\n      safety: 0.25\n"
        "      latency: 0.2\n      cost: 0.15\n"
    )
    result = CliRunner().invoke(_cli(), ["eval", "weights", "validate"])
    assert result.exit_code == 0, result.output
    assert "ok" in result.output.lower() or "valid" in result.output.lower()


def test_eval_weights_validate_rejects_bad_sum(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agentlab.yaml").write_text(
        "eval:\n  composite:\n    weights:\n"
        "      quality: 0.9\n      safety: 0.25\n"
        "      latency: 0.2\n      cost: 0.15\n"
    )
    result = CliRunner().invoke(_cli(), ["eval", "weights", "validate"])
    assert result.exit_code != 0
    assert "sum" in result.output.lower() or "1.0" in result.output
