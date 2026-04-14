"""Guided onboarding flow for bare ``agentlab`` outside a workspace.

When a user runs ``agentlab`` with no subcommand and no workspace is
detected, this module presents a friendly guided choice:

1. Create demo workspace (scaffolds with synthetic data + demo traces)
2. Create empty workspace (minimal scaffold)

If no provider API key is detected on the system after the workspace
selection, the user must paste one before workspace creation continues.
Live mode is the default when any provider key is already available in
the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
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
    """Prompt until the user provides a provider key.

    Returns (mode, saved_env_name) where mode is "live" or "mock".
    """
    click.echo("")
    click.echo(click.style("  Add a provider API key to continue.", bold=True))
    click.echo("  AgentLab uses live model calls for the workbench. Your key is saved")
    click.echo("  to .agentlab/.env and is not printed back to the terminal.\n")
    for number, label, env_name in PROVIDER_CHOICES:
        click.echo(f"    {number}) Paste {label} key ({env_name})")
    click.echo("")

    choice = click.prompt(
        "  Choose",
        type=click.Choice(["1", "2", "3"]),
        default="1",
        show_choices=False,
    )

    env_name = next(
        (
            env
            for number, _label, env in PROVIDER_CHOICES
            if number == choice
        ),
        "OPENAI_API_KEY",
    )
    key_value = ""
    while not key_value:
        key_value = click.prompt(
            f"  Paste your {env_name}",
            hide_input=True,
            confirmation_prompt=False,
            default="",
            show_default=False,
        ).strip()
        if not key_value:
            click.echo(click.style("  API key is required to continue.", fg="yellow"))

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
    _maybe_run_harness_wizard()
    return OnboardingResult(workspace=workspace, mode=mode, saved_key_env=saved)


def _maybe_run_harness_wizard(config_path: Optional[Path] = None) -> None:
    """Offer to write ``harness.models.{coordinator,worker}`` on first run.

    We run this after the workspace/API-key step so the wizard inherits
    the same prompt loop. Failures are soft-logged — a broken wizard
    must never block workspace creation because doctor can always be
    used later to finish the configuration.
    """
    try:
        from cli.harness_onboarding import (
            needs_harness_config,
            run_harness_wizard,
            write_harness_models,
        )
    except Exception:  # pragma: no cover — defensive import guard
        return

    target = Path(config_path) if config_path is not None else Path("agentlab.yaml")
    try:
        if not needs_harness_config(target):
            return
    except Exception:  # pragma: no cover — never block onboarding on doctor errors
        return

    def _prompt(label: str, choices, default: str) -> str:
        return click.prompt(
            label,
            type=click.Choice(list(choices)),
            default=default,
            show_choices=False,
        )

    try:
        choice = run_harness_wizard(target, prompt_fn=_prompt, echo_fn=click.echo)
        write_harness_models(target, choice)
        click.echo(
            click.style(
                f"  ✓ Wrote harness.models to {target} "
                f"(coordinator={choice.coordinator.model}, worker={choice.worker.model})\n",
                fg="green",
            )
        )
    except Exception as exc:  # pragma: no cover — surfaced via doctor instead
        click.echo(
            click.style(
                f"  ⚠ Could not configure harness models automatically: {exc}. "
                "Run `agentlab doctor` to finish setup.\n",
                fg="yellow",
            )
        )
