"""Tests for the /doctor hook registry section."""

from __future__ import annotations

import pytest

from cli.doctor_sections import hooks_section, render_hooks_section
from cli.hooks import HookRegistry
from cli.hooks.types import HookDefinition, HookEvent, HookType
from cli.settings import Settings


def test_hooks_section_counts_per_lifecycle_event() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "beforeQuery": [{"hooks": [{"command": "echo before"}]}],
                "afterQuery": [{"hooks": [{"command": "echo after"}]}],
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"command": "echo pre"}]},
                    {"matcher": "FileEdit", "hooks": [{"command": "echo pre2"}]},
                ],
                "PostToolUse": [{"hooks": [{"command": "echo post"}]}],
                "SubagentStop": [{"hooks": [{"command": "echo sub-stop"}]}],
                "SessionEnd": [{"hooks": [{"command": "echo session-end"}]}],
            }
        }
    )
    registry = HookRegistry.load_from_settings(settings)

    section = hooks_section(registry)

    counts = section["counts"]
    assert counts["beforeQuery"] == 1
    assert counts["afterQuery"] == 1
    assert counts["PreToolUse"] == 2
    assert counts["PostToolUse"] == 1
    assert counts["SubagentStop"] == 1
    assert counts["SessionEnd"] == 1


def test_hooks_section_lists_source_per_hook() -> None:
    """Each registered hook should expose its command/prompt source."""
    settings = Settings.model_validate(
        {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"command": "/usr/local/bin/audit.sh"}]}
                ],
            }
        }
    )
    registry = HookRegistry.load_from_settings(settings)

    section = hooks_section(registry)
    pre_entries = section["entries"]["PreToolUse"]

    assert len(pre_entries) == 1
    entry = pre_entries[0]
    assert entry["matcher"] == "Bash"
    assert entry["source"] == "/usr/local/bin/audit.sh"
    assert entry["type"] == "command"


def test_hooks_section_includes_prompt_source_for_prompt_hooks() -> None:
    registry = HookRegistry()
    registry.add(
        HookDefinition(
            event=HookEvent.PRE_TOOL_USE,
            matcher="",
            prompt="be careful with rm",
            hook_type=HookType.PROMPT,
        )
    )

    section = hooks_section(registry)
    entry = section["entries"]["PreToolUse"][0]

    assert entry["type"] == "prompt"
    assert "be careful" in entry["source"]


def test_hooks_section_collects_load_errors_without_crashing() -> None:
    """Malformed hook config should surface as errors, not exceptions."""
    registry = HookRegistry()
    # Simulate a load error injected by the loader.
    registry.load_errors = ["malformed hook block: bad shape"]  # type: ignore[attr-defined]

    section = hooks_section(registry)

    assert "malformed hook block: bad shape" in section["errors"]


def test_hooks_section_handles_empty_registry() -> None:
    section = hooks_section(HookRegistry())

    assert section["counts"] == {}
    assert section["entries"] == {}
    assert section["errors"] == []


def test_render_hooks_section_yields_human_lines() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"command": "/usr/local/bin/audit.sh"}]}
                ],
            }
        }
    )
    registry = HookRegistry.load_from_settings(settings)

    lines = render_hooks_section(registry)

    text = "\n".join(lines)
    assert "Hooks" in text
    assert "PreToolUse" in text
    assert "/usr/local/bin/audit.sh" in text


def test_render_hooks_section_handles_no_hooks_gracefully() -> None:
    lines = render_hooks_section(HookRegistry())

    text = "\n".join(lines)
    assert "Hooks" in text
    # Empty registry should produce a friendly note rather than crashing.
    assert "no hooks" in text.lower() or "0 registered" in text.lower()
