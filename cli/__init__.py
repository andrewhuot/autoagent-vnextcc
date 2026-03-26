"""CLI command modules for AutoAgent.

This package contains modular CLI commands that can be imported
and registered to the main CLI group.
"""

from cli.skills import register_skill_commands

__all__ = ["register_skill_commands"]
