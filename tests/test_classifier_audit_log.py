"""Tests for the classifier audit log.

The audit log is a JSONL sink in ``<root>/.agentlab/classifier_audit.jsonl``
with size-based rotation. Each line records a classifier decision so
operators can see — after the fact — which tool calls auto-approved,
auto-denied, or fell through to a prompt.

Failure-mode tests lean on the fact that the log must never corrupt
(concurrent writes, malformed pre-existing lines, aggressive rotation).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from cli.permissions.audit_log import ClassifierAuditLog, default_audit_log
from cli.permissions.classifier import ClassifierDecision


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        out.append(json.loads(raw))
    return out


def test_empty_log_iter_recent_yields_nothing(tmp_path: Path) -> None:
    log = ClassifierAuditLog(tmp_path / "audit.jsonl")
    assert list(log.iter_recent()) == []


def test_record_one_emits_entry_with_correct_shape(tmp_path: Path) -> None:
    log = ClassifierAuditLog(tmp_path / "audit.jsonl")
    log.record(
        tool_name="Bash",
        decision=ClassifierDecision.AUTO_APPROVE,
        tool_input_digest="sha256:abcdef0123456789",
        reason="bash_safe_allowlist",
    )
    entries = list(log.iter_recent())
    assert len(entries) == 1
    entry = entries[0]
    assert entry["tool"] == "Bash"
    assert entry["decision"] == "auto_approve"
    assert entry["input_digest"] == "sha256:abcdef0123456789"
    assert entry["reason"] == "bash_safe_allowlist"
    # ISO-8601 timestamp. We don't assert the exact value — just that it's
    # there and parseable as a string with a ``T`` separator.
    assert isinstance(entry["ts"], str)
    assert "T" in entry["ts"]


def test_input_digest_helper_is_short_hex_and_deterministic(tmp_path: Path) -> None:
    from cli.permissions.audit_log import compute_input_digest

    payload_a = {"command": "ls -la", "cwd": "/tmp"}
    payload_b = {"cwd": "/tmp", "command": "ls -la"}  # same content, different order
    digest_a = compute_input_digest(payload_a)
    digest_b = compute_input_digest(payload_b)
    assert digest_a == digest_b, "digest should be key-order-insensitive"
    # sha256: prefix + 16 hex chars
    assert digest_a.startswith("sha256:")
    hex_part = digest_a.split(":", 1)[1]
    assert len(hex_part) == 16
    int(hex_part, 16)  # parses as hex


def test_rotation_triggers_when_size_exceeded(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = ClassifierAuditLog(path, max_bytes=200, keep=3)
    # Each record line is ~130-150 bytes, so two should push past 200.
    for i in range(5):
        log.record(
            tool_name=f"ToolX{i}",
            decision=ClassifierDecision.PROMPT,
            tool_input_digest="sha256:0123456789abcdef",
            reason=f"iter-{i}",
        )
    # .1 must exist, holding the older content.
    assert path.exists()
    rotated_1 = path.with_suffix(".jsonl.1")
    assert rotated_1.exists(), "expected rotated file .jsonl.1"
    # Current file size should be <= max_bytes after rotation (fresh write).
    assert path.stat().st_size <= 200 + 200  # room for the fresh line


def test_rotation_respects_keep_limit(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = ClassifierAuditLog(path, max_bytes=120, keep=3)
    for i in range(20):
        log.record(
            tool_name=f"Tool{i}",
            decision=ClassifierDecision.AUTO_DENY,
            tool_input_digest="sha256:0123456789abcdef",
            reason=f"iter-{i}",
        )
    # keep=3 means .1, .2, .3 may exist; .4 must not.
    assert not path.with_suffix(".jsonl.4").exists()
    # At least one rotation must have happened.
    assert path.with_suffix(".jsonl.1").exists()


def test_concurrent_writes_do_not_corrupt_the_file(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = ClassifierAuditLog(path, max_bytes=10 * 1024 * 1024)

    def writer(thread_id: int) -> None:
        for i in range(25):
            log.record(
                tool_name=f"T{thread_id}",
                decision=ClassifierDecision.PROMPT,
                tool_input_digest=f"sha256:{thread_id:016d}",
                reason=f"t{thread_id}-i{i}",
            )

    threads = [threading.Thread(target=writer, args=(tid,)) for tid in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every line must parse — a torn write would raise here.
    entries = _read_lines(path)
    assert len(entries) == 4 * 25
    for entry in entries:
        assert set(entry).issuperset({"ts", "tool", "decision", "input_digest"})


def test_default_audit_log_creates_under_dot_agentlab(tmp_path: Path) -> None:
    log = default_audit_log(tmp_path)
    log.record(
        tool_name="Glob",
        decision=ClassifierDecision.AUTO_APPROVE,
        tool_input_digest="sha256:0000000000000000",
    )
    expected = tmp_path / ".agentlab" / "classifier_audit.jsonl"
    assert expected.exists()
    assert expected.read_text(encoding="utf-8").strip() != ""


def test_iter_recent_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text(
        "this-is-not-json\n"
        '{"ts": "2026-01-01T00:00:00+00:00", "tool": "Bash", "decision": "auto_approve", "input_digest": "sha256:0000000000000000"}\n'
        "\n"
        "{broken\n",
        encoding="utf-8",
    )
    log = ClassifierAuditLog(path)
    entries = list(log.iter_recent())
    assert len(entries) == 1
    assert entries[0]["tool"] == "Bash"
