"""Modular CLI command registrations.

Each subcommand group lives in its own module and registers itself on
the top-level `cli` click group via a `register_<name>_commands(cli)`
function. This keeps runner.py thin and lets us test each command group
in isolation.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import click


def register_all(cli: "click.Group") -> None:
    """Register every command group on *cli*. Called from runner.py."""
    from cli.commands.improve import register_improve_commands
    from cli.commands.build import register_build_commands
    from cli.commands.eval import register_eval_commands
    from cli.commands.optimize import register_optimize_commands
    register_improve_commands(cli)
    register_build_commands(cli)
    register_eval_commands(cli)
    register_optimize_commands(cli)
