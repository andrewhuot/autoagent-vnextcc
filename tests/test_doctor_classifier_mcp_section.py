"""Tests for the P3.T4 classifier + MCP transport /doctor section.

These cover:

* ``classifier_section`` / ``render_classifier_section`` — inspects the
  persisted allowlist file and the audit log on disk without requiring
  an active session.
* ``mcp_transports_section`` / ``render_mcp_transports_section`` —
  reads ``.mcp.json`` and surfaces each server's transport type
  (stdio / sse / streamable-http) with a best-effort label when the
  config doesn't yet discriminate.

Both renderers must degrade gracefully on empty/missing workspaces —
``/doctor`` should never crash because a workspace is pre-init.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli.doctor_sections import (
    classifier_section,
    mcp_transports_section,
    render_classifier_section,
    render_mcp_transports_section,
)


# ---------------------------------------------------------------------------
# Classifier section
# ---------------------------------------------------------------------------


def test_classifier_section_empty_workspace(tmp_path: Path) -> None:
    """No .agentlab dir, no audit log — section must still return a
    well-formed dict without raising."""
    section = classifier_section(tmp_path)
    assert section["allowlist_count"] == 0
    assert section["audit_log_exists"] is False
    assert section["audit_log_path"].endswith("classifier_audit.jsonl")


def test_classifier_section_reports_allowlist_count(tmp_path: Path) -> None:
    (tmp_path / ".agentlab").mkdir()
    (tmp_path / ".agentlab" / "classifier_allowlist.json").write_text(
        json.dumps({"allow": ["tool:Bash:*", "tool:FileRead:*", "tool:Glob:*"]}),
        encoding="utf-8",
    )
    section = classifier_section(tmp_path)
    assert section["allowlist_count"] == 3


def test_classifier_section_reports_audit_log_metadata(tmp_path: Path) -> None:
    from cli.permissions.audit_log import default_audit_log
    from cli.permissions.classifier import ClassifierDecision

    log = default_audit_log(tmp_path)
    log.record(
        tool_name="Bash",
        decision=ClassifierDecision.AUTO_APPROVE,
        tool_input_digest="sha256:0000000000000000",
    )

    section = classifier_section(tmp_path)
    assert section["audit_log_exists"] is True
    assert section["audit_log_size_bytes"] > 0
    assert section["last_entry_ts"] is not None


def test_render_classifier_section_returns_plain_lines(tmp_path: Path) -> None:
    """Renderer must never raise and must produce human-readable lines."""
    lines = render_classifier_section(tmp_path)
    assert isinstance(lines, list)
    # All entries are strings.
    assert all(isinstance(line, str) for line in lines)
    # Section header is present somewhere in the first couple of lines.
    joined = "\n".join(lines)
    assert "Classifier" in joined


# ---------------------------------------------------------------------------
# MCP transports section
# ---------------------------------------------------------------------------


def test_mcp_transports_section_no_config(tmp_path: Path) -> None:
    """Missing .mcp.json → empty server list, no crash."""
    section = mcp_transports_section(tmp_path)
    assert section["servers"] == []
    assert section["configured"] is False


def test_mcp_transports_section_stdio_legacy(tmp_path: Path) -> None:
    """A server with command+args but no transport field must surface
    as 'stdio (legacy)' so T9 (typed config) is unambiguously flagged."""
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "alpha": {"command": "alpha-server", "args": ["--foo"]},
                }
            }
        ),
        encoding="utf-8",
    )
    section = mcp_transports_section(tmp_path)
    assert section["configured"] is True
    assert len(section["servers"]) == 1
    entry = section["servers"][0]
    assert entry["name"] == "alpha"
    assert entry["transport"] == "stdio (legacy)"
    assert entry["command"] == "alpha-server"


def test_mcp_transports_section_typed_transports(tmp_path: Path) -> None:
    """If the config (speculatively, from T9) has ``type`` or
    ``transport``, surface it verbatim."""
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "beta": {"type": "sse", "url": "https://example.com/sse"},
                    "gamma": {
                        "transport": "streamable-http",
                        "url": "https://example.com/mcp",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    section = mcp_transports_section(tmp_path)
    names = {e["name"]: e for e in section["servers"]}
    assert names["beta"]["transport"] == "sse"
    assert names["gamma"]["transport"] == "streamable-http"


def test_render_mcp_transports_section_no_crash_on_empty(tmp_path: Path) -> None:
    lines = render_mcp_transports_section(tmp_path)
    assert isinstance(lines, list)
    assert "MCP" in "\n".join(lines)


def test_render_mcp_transports_section_shows_each_server(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "alpha": {"command": "alpha-server", "args": []},
                    "beta": {"type": "sse", "url": "https://example.com/sse"},
                }
            }
        ),
        encoding="utf-8",
    )
    text = "\n".join(render_mcp_transports_section(tmp_path))
    assert "alpha" in text
    assert "beta" in text
    assert "stdio" in text  # the legacy label
    assert "sse" in text


# ---------------------------------------------------------------------------
# TUI doctor screen smoke test
# ---------------------------------------------------------------------------


def test_tui_doctor_screen_renders_classifier_and_mcp_without_crashing(
    tmp_path: Path,
) -> None:
    """The TUI doctor screen must include the P3.T4 sections on an empty
    workspace. We reach in through ``_run_diagnostics`` so we don't need
    a full Textual event loop — the sections are plain strings."""
    from cli.workbench_app.tui.screens.doctor import DoctorScreen

    class _FakeWorkspace:
        def __init__(self, root: Path) -> None:
            self.root = root

        def resolve_active_config(self) -> None:  # pragma: no cover - smoke
            return None

    screen = DoctorScreen(workspace=_FakeWorkspace(tmp_path))
    lines = screen._run_diagnostics()
    text = "\n".join(lines)
    assert "Classifier" in text
    assert "MCP transports" in text
