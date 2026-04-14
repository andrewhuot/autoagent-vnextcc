"""Tests for the ``@`` file-reference completer in
:mod:`cli.workbench_app.completer`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.workbench_app.commands import CommandRegistry, LocalCommand
from cli.workbench_app.completer import (
    MAX_FILE_COMPLETIONS,
    extract_file_ref_token,
    iter_completions,
    iter_file_completions,
)


def _noop(_ctx, *_args):  # type: ignore[no-untyped-def]
    return None


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("# app")
    (tmp_path / "src" / "app_utils.py").write_text("# utils")
    (tmp_path / "src" / "nested").mkdir()
    (tmp_path / "src" / "nested" / "deep.py").write_text("# deep")
    (tmp_path / "tests").mkdir()
    (tmp_path / "README.md").write_text("readme")
    (tmp_path / ".hidden").write_text("hidden")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "noise.js").write_text("noise")
    return tmp_path


def test_extract_file_ref_token_handles_prefixes() -> None:
    assert extract_file_ref_token("") is None
    assert extract_file_ref_token("hello") is None
    assert extract_file_ref_token("@") == ""
    assert extract_file_ref_token("  @src/") == "src/"
    assert extract_file_ref_token("please look at @sr") == "sr"
    assert extract_file_ref_token("/build @foo") == "foo"


def test_iter_file_completions_lists_root_entries(workspace: Path) -> None:
    records = list(iter_file_completions(workspace, "@"))
    names = [record.path.rstrip("/") for record in records]
    assert "README.md" in names
    assert "src" in names
    assert ".hidden" not in names  # hidden files suppressed by default
    assert "node_modules" not in names  # ignored dir list


def test_iter_file_completions_filters_by_prefix(workspace: Path) -> None:
    records = list(iter_file_completions(workspace, "@src/app"))
    paths = [record.path for record in records]
    assert "src/app.py" in paths
    assert "src/app_utils.py" in paths
    assert "src/nested" not in paths


def test_iter_file_completions_descends_directories(workspace: Path) -> None:
    records = list(iter_file_completions(workspace, "@src/"))
    paths = [record.path for record in records]
    assert "src/app.py" in paths
    assert "src/nested/" in paths


def test_iter_file_completions_caps_results(tmp_path: Path) -> None:
    for idx in range(MAX_FILE_COMPLETIONS + 10):
        (tmp_path / f"file_{idx:03}.txt").write_text("x")
    records = list(iter_file_completions(tmp_path, "@file_"))
    assert len(records) == MAX_FILE_COMPLETIONS


def test_iter_file_completions_exposes_hidden_when_queried(workspace: Path) -> None:
    records = list(iter_file_completions(workspace, "@.hid"))
    paths = [record.path for record in records]
    assert ".hidden" in paths


def test_slash_command_completion_still_fires_without_at_token() -> None:
    registry = CommandRegistry()
    registry.register(LocalCommand(name="build", description="d", source="builtin", handler=_noop))
    names = [record.name for record in iter_completions(registry, "/bu")]
    assert names == ["build"]


def test_iter_file_completions_ignores_when_no_at_token(workspace: Path) -> None:
    assert list(iter_file_completions(workspace, "")) == []
    assert list(iter_file_completions(workspace, "hello world")) == []


def test_iter_file_completions_tolerates_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "does" / "not" / "exist"
    assert list(iter_file_completions(missing, "@foo")) == []
