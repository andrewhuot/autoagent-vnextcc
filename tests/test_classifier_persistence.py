"""Tests for ``cli.permissions.classifier_persistence``.

The helper reads/writes a small JSON file
(``<root>/.agentlab/classifier_allowlist.json``) that seeds the transcript
classifier's ``persisted_allow_patterns`` across sessions. The dialog's
"save as rule" branch appends to this file when the user picks
``persist_scope=="settings"``.

Contract:

* Missing file or malformed JSON → empty frozenset, no exception.
* Appending a pattern dedups and preserves existing entries.
* The written JSON round-trips cleanly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli.permissions.classifier_persistence import (
    CLASSIFIER_ALLOWLIST_FILENAME,
    append_persisted_allow,
    load_persisted_patterns,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


def test_load_missing_file_returns_empty(workspace: Path) -> None:
    assert load_persisted_patterns(workspace) == frozenset()


def test_load_malformed_json_returns_empty(workspace: Path) -> None:
    path = workspace / ".agentlab" / CLASSIFIER_ALLOWLIST_FILENAME
    path.write_text("not-json{{", encoding="utf-8")
    assert load_persisted_patterns(workspace) == frozenset()


def test_load_existing_patterns(workspace: Path) -> None:
    path = workspace / ".agentlab" / CLASSIFIER_ALLOWLIST_FILENAME
    path.write_text(
        json.dumps({"allow": ["tool:Bash:*", "tool:FileEdit:docs/*"]}),
        encoding="utf-8",
    )
    patterns = load_persisted_patterns(workspace)
    assert patterns == frozenset({"tool:Bash:*", "tool:FileEdit:docs/*"})


def test_append_dedup(workspace: Path) -> None:
    append_persisted_allow(workspace, "tool:Bash:*")
    append_persisted_allow(workspace, "tool:Bash:*")
    append_persisted_allow(workspace, "tool:FileEdit:*")
    assert load_persisted_patterns(workspace) == frozenset(
        {"tool:Bash:*", "tool:FileEdit:*"}
    )


def test_append_roundtrip(workspace: Path) -> None:
    append_persisted_allow(workspace, "tool:FileRead:*")
    assert load_persisted_patterns(workspace) == frozenset({"tool:FileRead:*"})


def test_append_over_malformed_file_recovers(workspace: Path) -> None:
    path = workspace / ".agentlab" / CLASSIFIER_ALLOWLIST_FILENAME
    path.write_text("garbage", encoding="utf-8")
    append_persisted_allow(workspace, "tool:Glob")
    assert load_persisted_patterns(workspace) == frozenset({"tool:Glob"})
