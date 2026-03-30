"""Tests for the shared command taxonomy."""

from __future__ import annotations

from shared.taxonomy import COMMAND_GROUPS, COMMAND_TAXONOMY


def test_command_groups_are_in_cli_alignment_order() -> None:
    assert COMMAND_GROUPS == (
        "home",
        "build",
        "import",
        "eval",
        "optimize",
        "review",
        "deploy",
        "observe",
        "govern",
        "integrations",
        "settings",
    )


def test_command_taxonomy_exposes_expected_labels() -> None:
    assert COMMAND_TAXONOMY["build"]["label"] == "Build"
    assert COMMAND_TAXONOMY["optimize"]["label"] == "Optimize"
    assert COMMAND_TAXONOMY["settings"]["description"] == "Workspace configuration and diagnostics"


def test_build_subcommands_match_unified_build_surface() -> None:
    assert COMMAND_TAXONOMY["build"]["subcommands"] == (
        "prompt",
        "transcript",
        "builder_chat",
        "saved_artifacts",
    )
