"""Guided onboarding flow for bare ``agentlab`` outside a workspace.

When a user runs ``agentlab`` with no subcommand and no workspace is
detected, this module presents a friendly guided choice:

1. Create demo workspace (scaffolds with synthetic data + demo traces)
2. Create empty workspace (minimal scaffold)

If no provider API key is detected on the system after the workspace
selection, the user is prompted to either paste one now (enabling live
mode) or explicitly opt into mock mode. Live mode is the default when
any provider key is already available in the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import click

from cli.workspace_env import (
    PROVIDER_API_KEY_ENV_VARS,
    hydrate_provider_key_aliases,
    write_workspace_env_values,
)


@dataclass
class OnboardingResult:
    """Structured outcome of the interactive first-run flow."""

    workspace: Optional[str]  # "demo" | "empty" | None (user exited)
    mode: str  # "live" | "mock"
    saved_key_env: Optional[str]  # env var name that was saved, if any


PROVIDER_CHOICES = (
    ("1", "OpenAI", "OPENAI_API_KEY"),
    ("2", "Anthropic", "ANTHROPIC_API_KEY"),
    ("3", "Google / Gemini", "GOOGLE_API_KEY"),
)


def _detect_existing_provider_key() -> Optional[str]:
    """Return the first already-configured provider env var, or None."""
    hydrate_provider_key_aliases()
    for name in PROVIDER_API_KEY_ENV_VARS:
        if str(os.environ.get(name) or "").strip():
            return name
    return None


def _prompt_for_provider_key() -> tuple[str, Optional[str]]:
    """Prompt the user to paste a provider key or choose mock.

    Returns (mode, saved_env_name) where mode is "live" or "mock".
    """
    click.echo("")
    click.echo(click.style("  AgentLab works best with a real LLM.", bold=True))
    click.echo("  Paste a provider API key to enable live mode, or choose mock for")
    click.echo("  canned responses while you explore.\n")
    for number, label, env_name in PROVIDER_CHOICES:
        click.echo(f"    {number}) Paste {label} key ({env_name})")
    click.echo("    4) Use mock mode for now (no key)\n")

    choice = click.prompt(
        "  Choose",
        type=click.Choice(["1", "2", "3", "4"]),
        default="4",
        show_choices=False,
    )

    if choice == "4":
        click.echo(
            "  Using mock mode. Run `agentlab mode set live` after saving a key via "
            "`agentlab provider configure`.\n"
        )
        return "mock", None

    env_name = next(env for number, _label, env in PROVIDER_CHOICES if number == choice)
    key_value = click.prompt(
        f"  Paste your {env_name}",
        hide_input=True,
        confirmation_prompt=False,
        default="",
        show_default=False,
    ).strip()

    if not key_value:
        click.echo("  No key provided — falling back to mock mode.\n")
        return "mock", None

    write_workspace_env_values({env_name: key_value})
    os.environ[env_name] = key_value
    hydrate_provider_key_aliases()
    click.echo(click.style(f"  ✓ Saved {env_name} to .agentlab/.env (mode: live)\n", fg="green"))
    return "live", env_name


def run_onboarding() -> OnboardingResult:
    """Return the onboarding action the user selected, plus resolved mode."""
    click.echo(click.style("\n  Welcome to AgentLab", fg="cyan", bold=True))
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

    if choice == "3":
        return OnboardingResult(workspace=None, mode="mock", saved_key_env=None)

    workspace = "demo" if choice == "1" else "empty"

    existing_key = _detect_existing_provider_key()
    if existing_key:
        click.echo(click.style(
            f"  ✓ Detected {existing_key} — defaulting to live mode.\n",
            fg="green",
        ))
        return OnboardingResult(workspace=workspace, mode="live", saved_key_env=None)

    mode, saved = _prompt_for_provider_key()
    return OnboardingResult(workspace=workspace, mode=mode, saved_key_env=saved)
