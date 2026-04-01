"""CLI helpers and commands for explicit mock/live mode control."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import click

from agent.config.runtime import RuntimeConfig, load_runtime_config
from cli.errors import with_doctor_hint
from cli.workspace_env import load_workspace_env
from optimizer.providers import has_real_provider_credentials


WORKSPACE_STATE_PATH = Path(".agentlab") / "workspace.json"
VALID_MODES = {"auto", "mock", "live"}


def _read_workspace_state(path: Path = WORKSPACE_STATE_PATH) -> dict[str, Any]:
    """Return persisted CLI workspace state, defaulting to an empty payload."""
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def _write_workspace_state(payload: dict[str, Any], path: Path = WORKSPACE_STATE_PATH) -> None:
    """Persist CLI workspace state for subsequent invocations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def get_mode_preference(path: Path = WORKSPACE_STATE_PATH) -> str | None:
    """Return the workspace mode preference when one has been set."""
    mode = str(_read_workspace_state(path).get("mode", "")).strip().lower()
    return mode if mode in VALID_MODES else None


def set_mode_preference(mode: str, path: Path = WORKSPACE_STATE_PATH) -> None:
    """Persist the requested workspace mode preference for the CLI."""
    normalized = mode.strip().lower()
    if normalized not in VALID_MODES:  # pragma: no cover - guarded by Click
        raise ValueError(f"Unsupported mode: {mode}")
    payload = _read_workspace_state(path)
    payload["mode"] = normalized
    payload["updated_at"] = time.time()
    payload["updated_by"] = "agentlab mode set"
    _write_workspace_state(payload, path)


def describe_providers(runtime: RuntimeConfig) -> list[dict[str, Any]]:
    """Return configured providers and whether their required credentials exist."""
    providers: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for model in runtime.optimizer.models:
        key = (model.provider, model.model, model.api_key_env)
        if key in seen:
            continue
        seen.add(key)
        env_name = model.api_key_env
        configured = bool(env_name and os.environ.get(env_name))
        providers.append(
            {
                "provider": model.provider,
                "model": model.model,
                "api_key_env": env_name,
                "credential_set": configured,
                "configured": configured,
            }
        )
    return providers


def summarize_mode_state(config_path: str = "agentlab.yaml") -> dict[str, Any]:
    """Return preferred/effective mode details plus provider configuration."""
    load_workspace_env()
    runtime = load_runtime_config(config_path)
    workspace_mode = get_mode_preference()
    config_mode = "mock" if runtime.optimizer.use_mock else "live"
    preferred_mode = workspace_mode or config_mode
    real_provider_configured = has_real_provider_credentials(runtime.optimizer)
    if preferred_mode == "mock":
        effective_mode = "mock"
    else:
        effective_mode = "live" if real_provider_configured else "mock"

    if preferred_mode == "mock":
        message = (
            "Running in MOCK mode — results use deterministic responses. "
            "Run agentlab mode set live to use real providers."
        )
    elif preferred_mode == "auto":
        if effective_mode == "live":
            message = (
                "Running in AUTO mode — configured provider credentials are available, "
                "so the CLI will use LIVE providers."
            )
        else:
            message = (
                "Running in AUTO mode — no configured provider credentials are available, "
                "so the CLI is falling back to MOCK execution."
            )
    elif effective_mode == "live":
        message = "Running in LIVE mode — CLI will use configured real providers."
    else:
        message = (
            "LIVE mode is preferred, but no configured provider credentials are available right now. "
            "The CLI will fall back to MOCK execution until credentials are restored."
        )

    return {
        "runtime": runtime,
        "workspace_mode": workspace_mode,
        "config_mode": config_mode,
        "preferred_mode": preferred_mode,
        "effective_mode": effective_mode,
        "mode_source": "workspace preference (.agentlab/workspace.json)" if workspace_mode else f"runtime config ({config_path})",
        "providers": describe_providers(runtime),
        "real_provider_configured": real_provider_configured,
        "message": message,
    }


def load_runtime_with_mode_preference(config_path: str = "agentlab.yaml") -> RuntimeConfig:
    """Load runtime config and apply the CLI workspace mode preference."""
    summary = summarize_mode_state(config_path)
    runtime = summary["runtime"].model_copy(deep=True)
    runtime.optimizer.use_mock = summary["effective_mode"] == "mock"
    return runtime


def load_runtime_with_builder_live_preference(config_path: str = "agentlab.yaml") -> RuntimeConfig:
    """Load runtime config for Build flows, preferring live providers when available.

    WHY: Build/config generation becomes misleading when it silently stays in
    mock mode even though the operator has already configured real provider
    credentials. The builder should use live providers unless the workspace has
    been explicitly pinned to mock mode.
    """
    summary = summarize_mode_state(config_path)
    runtime = summary["runtime"].model_copy(deep=True)
    workspace_mode = summary["workspace_mode"]

    if workspace_mode == "mock":
        runtime.optimizer.use_mock = True
    else:
        runtime.optimizer.use_mock = not summary["real_provider_configured"]

    return runtime


def ensure_live_mode_ready(config_path: str = "agentlab.yaml") -> dict[str, Any]:
    """Validate that live mode has at least one configured real provider credential."""
    summary = summarize_mode_state(config_path)
    if not summary["real_provider_configured"]:
        raise click.ClickException(
            with_doctor_hint(
                "Cannot enable live mode because no configured provider API keys are available. "
                "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY first."
            )
        )
    return summary


def _render_provider_lines(providers: list[dict[str, Any]]) -> list[str]:
    """Render provider configuration lines for terminal output."""
    lines: list[str] = []
    for provider in providers:
        env_name = provider.get("api_key_env") or "n/a"
        status = "set" if provider.get("credential_set") else "missing"
        lines.append(
            f"  - {provider.get('provider')}:{provider.get('model')} "
            f"[{env_name}: {status}]"
        )
    return lines or ["  - No providers configured in runtime config."]


@click.group("mode", invoke_without_command=True)
@click.pass_context
def mode_group(ctx: click.Context) -> None:
    """Show or set explicit CLI execution mode.

    Examples:
      agentlab mode show
      agentlab mode set auto
      agentlab mode set mock
      agentlab mode set live
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(show_mode)


@mode_group.command("show")
@click.option("--config", "config_path", default="agentlab.yaml", show_default=True,
              help="Path to runtime config YAML.")
def show_mode(config_path: str) -> None:
    """Show the current CLI mode and configured providers."""
    summary = summarize_mode_state(config_path)
    click.echo(f"Current mode: {summary['effective_mode'].upper()}")
    click.echo(f"Preferred mode: {summary['preferred_mode'].upper()}")
    click.echo(f"Mode source: {summary['mode_source']}")
    click.echo(summary["message"])
    click.echo("Configured providers:")
    for line in _render_provider_lines(summary["providers"]):
        click.echo(line)


@mode_group.command("set")
@click.argument("mode", type=click.Choice(sorted(VALID_MODES), case_sensitive=False))
@click.option("--config", "config_path", default="agentlab.yaml", show_default=True,
              help="Path to runtime config YAML.")
def set_mode(mode: str, config_path: str) -> None:
    """Persist the requested CLI mode preference for this workspace."""
    normalized = mode.lower()
    if normalized == "live":
        ensure_live_mode_ready(config_path)
    set_mode_preference(normalized)
    summary = summarize_mode_state(config_path)
    click.echo(summary["message"])
    click.echo(f"Saved workspace preference: {normalized.upper()} ({WORKSPACE_STATE_PATH})")
    click.echo("Configured providers:")
    for line in _render_provider_lines(summary["providers"]):
        click.echo(line)
