"""Shared boundary types and taxonomy for CLI, API, and UI surfaces."""

from __future__ import annotations

from .taxonomy import COMMAND_GROUPS, COMMAND_TAXONOMY, CommandGroup, CommandGroupSpec

__all__ = [
    "COMMAND_GROUPS",
    "COMMAND_TAXONOMY",
    "CommandGroup",
    "CommandGroupSpec",
]
