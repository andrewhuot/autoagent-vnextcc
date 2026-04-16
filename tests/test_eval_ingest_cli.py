"""Tests for `agentlab eval ingest --from-traces` (R5 Slice C.4).

The command converts production JSONL traces into eval cases with
mandatory PII redaction. Exit-code contract:

- 0  success
- 20 redaction consent refused, or non-interactive without --yes
- 1  IO / malformed input

TTY simulation: CliRunner.invoke() leaves ``sys.stdin.isatty()`` returning
False by default, so the CLI's "non-interactive without --yes" path is
exercised out of the box. CliRunner swaps ``sys.stdin`` for a ``StringIO``
at invoke time — patching ``sys.stdin.isatty`` in the test itself is lost
by the time the command runs. So the CLI exposes a module-level
``_is_interactive`` helper that tests can monkeypatch to True to exercise
the click.confirm branch (which then reads from the CliRunner-provided
``input=`` stdin).
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from runner import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_traces(path: Path, traces: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(t) for t in traces) + "\n",
        encoding="utf-8",
    )


def _clean_trace(i: int) -> dict:
    return {
        "trace_id": f"clean_{i}",
        "user_message": f"what is the status of order {i}",
        "response": f"order {i} shipped",
        "specialist_used": "support",
    }


def _pii_trace(i: int) -> dict:
    return {
        "trace_id": f"pii_{i}",
        "user_message": f"email me at user{i}@example.com about order",
        "response": f"server at 10.0.0.{i} processed it",
        "specialist_used": "support",
    }


# ---------------------------------------------------------------------------
# Happy path: no PII
# ---------------------------------------------------------------------------


def test_ingest_writes_yaml_when_no_pii(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "traces.jsonl"
    _write_traces(src, [_clean_trace(0), _clean_trace(1)])

    out = tmp_path / "out.yaml"
    r = CliRunner().invoke(
        cli,
        ["eval", "ingest", "--from-traces", str(src), "--output", str(out)],
    )
    assert r.exit_code == 0, r.output
    assert out.exists()
    data = yaml.safe_load(out.read_text())
    assert "cases" in data
    assert len(data["cases"]) == 2


# ---------------------------------------------------------------------------
# Redaction consent gate — the core invariant
# ---------------------------------------------------------------------------


def test_ingest_non_interactive_without_yes_exits_20(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "traces.jsonl"
    _write_traces(src, [_pii_trace(0)])
    out = tmp_path / "out.yaml"

    # CliRunner default: stdin is not a TTY; no --yes → must exit 20.
    r = CliRunner().invoke(
        cli,
        ["eval", "ingest", "--from-traces", str(src), "--output", str(out)],
    )
    assert r.exit_code == 20, r.output
    assert not out.exists(), "output file must not be created on refusal"
    assert "--yes" in r.output


def test_ingest_non_interactive_with_yes_proceeds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "traces.jsonl"
    _write_traces(src, [_pii_trace(0)])
    out = tmp_path / "out.yaml"

    r = CliRunner().invoke(
        cli,
        [
            "eval", "ingest", "--from-traces", str(src),
            "--output", str(out), "--yes",
        ],
    )
    assert r.exit_code == 0, r.output
    assert out.exists()
    body = out.read_text()
    assert "<REDACTED:EMAIL>" in body
    assert "@example.com" not in body


def test_ingest_tty_prompt_y_proceeds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cli.commands.ingest._is_interactive", lambda: True)
    src = tmp_path / "traces.jsonl"
    _write_traces(src, [_pii_trace(0)])
    out = tmp_path / "out.yaml"

    r = CliRunner().invoke(
        cli,
        ["eval", "ingest", "--from-traces", str(src), "--output", str(out)],
        input="y\n",
    )
    assert r.exit_code == 0, r.output
    assert out.exists()


def test_ingest_tty_prompt_n_aborts_exit_20(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cli.commands.ingest._is_interactive", lambda: True)
    src = tmp_path / "traces.jsonl"
    _write_traces(src, [_pii_trace(0)])
    out = tmp_path / "out.yaml"

    r = CliRunner().invoke(
        cli,
        ["eval", "ingest", "--from-traces", str(src), "--output", str(out)],
        input="n\n",
    )
    assert r.exit_code == 20, r.output
    assert not out.exists()


# ---------------------------------------------------------------------------
# Flags and edge cases
# ---------------------------------------------------------------------------


def test_ingest_max_cases_caps_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "traces.jsonl"
    _write_traces(src, [_clean_trace(i) for i in range(50)])
    out = tmp_path / "out.yaml"

    r = CliRunner().invoke(
        cli,
        [
            "eval", "ingest", "--from-traces", str(src),
            "--output", str(out), "--max-cases", "5",
        ],
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load(out.read_text())
    assert len(data["cases"]) == 5


def test_ingest_missing_input_exits_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out.yaml"
    r = CliRunner().invoke(
        cli,
        [
            "eval", "ingest", "--from-traces", str(tmp_path / "nope.jsonl"),
            "--output", str(out),
        ],
    )
    assert r.exit_code == 1, r.output
    assert not out.exists()


def test_ingest_malformed_jsonl_exits_1_with_line_number(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "bad.jsonl"
    src.write_text(
        json.dumps(_clean_trace(0)) + "\n" + "{not valid json\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.yaml"
    r = CliRunner().invoke(
        cli,
        ["eval", "ingest", "--from-traces", str(src), "--output", str(out)],
    )
    assert r.exit_code == 1, r.output
    # Line number should be referenced (1-indexed, the bad line is #2).
    assert "2" in r.output or "line" in r.output.lower()


def test_ingest_refuses_overwrite_without_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "traces.jsonl"
    _write_traces(src, [_clean_trace(0)])
    out = tmp_path / "out.yaml"
    out.write_text("existing\n", encoding="utf-8")

    r = CliRunner().invoke(
        cli,
        ["eval", "ingest", "--from-traces", str(src), "--output", str(out)],
    )
    assert r.exit_code != 0
    assert "force" in r.output.lower() or "overwrite" in r.output.lower()
    # File untouched.
    assert out.read_text() == "existing\n"


def test_ingest_force_overwrites(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "traces.jsonl"
    _write_traces(src, [_clean_trace(0)])
    out = tmp_path / "out.yaml"
    out.write_text("existing\n", encoding="utf-8")

    r = CliRunner().invoke(
        cli,
        [
            "eval", "ingest", "--from-traces", str(src),
            "--output", str(out), "--force",
        ],
    )
    assert r.exit_code == 0, r.output
    data = yaml.safe_load(out.read_text())
    assert "cases" in data
    assert len(data["cases"]) == 1


def test_ingest_redaction_summary_prints_counts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "traces.jsonl"
    _write_traces(src, [_pii_trace(0), _pii_trace(1)])
    out = tmp_path / "out.yaml"

    r = CliRunner().invoke(
        cli,
        [
            "eval", "ingest", "--from-traces", str(src),
            "--output", str(out), "--yes",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "EMAIL" in r.output
    assert "Redaction" in r.output or "redaction" in r.output


def test_ingest_redacts_all_string_fields_not_just_user_message(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "traces.jsonl"
    # PII only in the response (which becomes reference_answer).
    _write_traces(src, [{
        "trace_id": "t0",
        "user_message": "order status?",
        "response": "email us at help@example.com for details",
        "specialist_used": "support",
    }])
    out = tmp_path / "out.yaml"

    r = CliRunner().invoke(
        cli,
        [
            "eval", "ingest", "--from-traces", str(src),
            "--output", str(out), "--yes",
        ],
    )
    assert r.exit_code == 0, r.output
    body = out.read_text()
    assert "help@example.com" not in body
    assert "<REDACTED:EMAIL>" in body
