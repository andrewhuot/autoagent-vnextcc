"""Tests for layered project memory and Stream B memory commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from runner import cli


@pytest.fixture
def runner() -> CliRunner:
    """Return a CLI runner."""
    return CliRunner()


def test_load_layered_project_context_merges_all_sources(tmp_path: Path) -> None:
    """Shared, local, rules, and generated summaries should all appear in the merged view."""
    from core.project_memory import load_layered_project_context

    (tmp_path / "AUTOAGENT.md").write_text("# Shared\nAlways keep the refund flow fast.\n", encoding="utf-8")
    (tmp_path / "AUTOAGENT.local.md").write_text("# Local\nPrefer concise debug output.\n", encoding="utf-8")
    rules_dir = tmp_path / ".autoagent" / "rules"
    memory_dir = tmp_path / ".autoagent" / "memory"
    rules_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "safety.md").write_text("# Safety Pack\nNever expose internal pricing.\n", encoding="utf-8")
    (memory_dir / "latest_session.md").write_text("# Session Summary\nBilling confusion spiked yesterday.\n", encoding="utf-8")

    snapshot = load_layered_project_context(tmp_path)

    assert snapshot.shared_path.name == "AUTOAGENT.md"
    assert snapshot.local_path.name == "AUTOAGENT.local.md"
    assert len(snapshot.active_sources) == 4
    assert "refund flow" in snapshot.merged_content
    assert "concise debug output" in snapshot.merged_content
    assert "internal pricing" in snapshot.merged_content
    assert "Billing confusion spiked" in snapshot.merged_content


def test_write_session_summary_creates_generated_memory_file(tmp_path: Path) -> None:
    """Summaries should be stored under `.autoagent/memory/`."""
    from core.project_memory import write_session_summary

    written = write_session_summary(
        tmp_path,
        title="March 30 session",
        summary="Investigated permissions and budget UX changes.",
    )

    assert written.parent == tmp_path / ".autoagent" / "memory"
    assert written.exists()
    body = written.read_text(encoding="utf-8")
    assert "March 30 session" in body
    assert "permissions and budget UX changes" in body


def test_memory_where_reports_active_sources(runner: CliRunner) -> None:
    """`memory where` should show the layered context file map."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        Path("AUTOAGENT.local.md").write_text("# Local\nPersonal notes.\n", encoding="utf-8")
        Path(".autoagent/rules").mkdir(parents=True, exist_ok=True)
        Path(".autoagent/rules/routing.md").write_text("# Routing\nPrefer billing specialist.\n", encoding="utf-8")

        result = runner.invoke(cli, ["memory", "where"])

        assert result.exit_code == 0, result.output
        assert "AUTOAGENT.md" in result.output
        assert "AUTOAGENT.local.md" in result.output
        assert ".autoagent/rules/routing.md" in result.output


def test_memory_edit_append_creates_target_file(runner: CliRunner) -> None:
    """`memory edit` should create the requested file when appending content."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        result = runner.invoke(
            cli,
            ["memory", "edit", "local", "--append", "## Local Notes\n- Prefer compact summaries"],
        )

        assert result.exit_code == 0, result.output
        body = Path("AUTOAGENT.local.md").read_text(encoding="utf-8")
        assert "Local Notes" in body
        assert "compact summaries" in body


def test_memory_summarize_session_writes_latest_session_note(runner: CliRunner) -> None:
    """`memory summarize-session` should persist a generated note in the memory directory."""
    with runner.isolated_filesystem():
        init_result = runner.invoke(cli, ["init", "--dir", "."])
        assert init_result.exit_code == 0, init_result.output

        result = runner.invoke(
            cli,
            [
                "memory",
                "summarize-session",
                "We resolved MCP runtime status visibility and clarified permission modes.",
            ],
        )

        assert result.exit_code == 0, result.output
        written_files = list((Path(".autoagent") / "memory").glob("*session*.md"))
        assert written_files
        assert "permission modes" in written_files[0].read_text(encoding="utf-8")
