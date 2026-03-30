"""Guided onboarding flow for bare ``autoagent`` outside a workspace.

When a user runs ``autoagent`` with no subcommand and no workspace is
detected, this module presents a friendly guided choice:

1. Create demo workspace (scaffolds with synthetic data + demo traces)
2. Create empty workspace (minimal scaffold)
"""

from __future__ import annotations

import click


def run_onboarding() -> str | None:
    """Return the onboarding action the user selected."""
    click.echo(click.style("\n  Welcome to AutoAgent", fg="cyan", bold=True))
    click.echo("  No workspace detected in the current directory.\n")
    click.echo("  What would you like to do?\n")
    click.echo("    1) Create demo workspace   (starter data + review cards)")
    click.echo("    2) Create empty workspace   (minimal scaffold)")
    click.echo("    3) Exit\n")

    choice = click.prompt(
        "  Choose",
        type=click.Choice(["1", "2", "3"]),
        default="1",
        show_choices=False,
    )

    if choice == "1":
        return "demo"
    if choice == "2":
        return "empty"
    return None
