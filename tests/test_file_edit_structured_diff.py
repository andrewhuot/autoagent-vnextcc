"""Tests for structured diff payloads on file-editing tools."""

from __future__ import annotations

from pathlib import Path

from cli.tools.base import ToolContext
from cli.tools.file_edit import FileEditTool
from cli.tools.file_write import FileWriteTool
from cli.tools.rendering import (
    STRUCTURED_DIFF_KIND,
    structured_diff_from_metadata,
)


def _context(workspace: Path) -> ToolContext:
    return ToolContext(workspace_root=workspace)


def test_file_edit_returns_unified_diff_display_and_renderable(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo.py"
    target.write_text("def add(x, y):\n    return x + y\n", encoding="utf-8")

    result = FileEditTool().run(
        {
            "path": "demo.py",
            "old_string": "x + y",
            "new_string": "x - y",
        },
        _context(workspace),
    )

    assert result.ok is True
    assert result.display is not None
    assert "--- a/demo.py" in result.display
    assert "+++ b/demo.py" in result.display
    assert "-    return x + y" in result.display
    assert "+    return x - y" in result.display

    renderable = structured_diff_from_metadata(result.metadata)
    assert renderable is not None
    assert renderable.kind == STRUCTURED_DIFF_KIND
    assert renderable.file_path == "demo.py"
    assert renderable.language == "python"
    assert renderable.old == "def add(x, y):\n    return x + y\n"
    assert renderable.new == "def add(x, y):\n    return x - y\n"


def test_file_write_for_new_file_returns_renderable_with_empty_left_side(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = FileWriteTool().run(
        {
            "path": "notes.md",
            "content": "# Title\n\nHello\n",
        },
        _context(workspace),
    )

    assert result.ok is True
    assert result.display is not None
    assert "--- a/notes.md" in result.display
    assert "+++ b/notes.md" in result.display
    assert "+# Title" in result.display

    renderable = structured_diff_from_metadata(result.metadata)
    assert renderable is not None
    assert renderable.file_path == "notes.md"
    assert renderable.language == "markdown"
    assert renderable.old == ""
    assert renderable.new == "# Title\n\nHello\n"


def test_file_write_truncates_large_new_content_in_renderable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lines = "\n".join(f"line {index}" for index in range(1005)) + "\n"

    result = FileWriteTool().run(
        {
            "path": "big.txt",
            "content": lines,
        },
        _context(workspace),
    )

    renderable = structured_diff_from_metadata(result.metadata)
    assert renderable is not None
    assert len(renderable.new.splitlines()) == 1000
    assert result.display is not None
    assert "truncated" in result.display


def test_file_write_overwrites_non_utf8_existing_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "binary.txt"
    target.write_bytes(b"\xff\xfe\x00\x01")

    result = FileWriteTool().run(
        {
            "path": "binary.txt",
            "content": "replacement\n",
        },
        _context(workspace),
    )

    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "replacement\n"
    renderable = structured_diff_from_metadata(result.metadata)
    assert renderable is not None
    assert "non-UTF-8" in renderable.old
