"""Workspace-scoped model inspection and override commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from agent.config.runtime import RuntimeConfig, RuntimeModelConfig, load_runtime_config
from cli.errors import click_error
from cli.json_envelope import render_json_envelope
from cli.permissions import load_workspace_settings, save_workspace_settings


def _model_key(model: RuntimeModelConfig) -> str:
    return f"{model.provider}:{model.model}"


def list_available_models(root: str | Path = ".") -> list[dict[str, Any]]:
    """Return available runtime models for the current workspace."""
    runtime = load_runtime_config(str(Path(root) / "autoagent.yaml"))
    return [
        {
            "key": _model_key(model),
            "provider": model.provider,
            "model": model.model,
            "role": model.role,
            "api_key_env": model.api_key_env,
            "input_cost_per_1k_tokens": model.input_cost_per_1k_tokens,
            "output_cost_per_1k_tokens": model.output_cost_per_1k_tokens,
        }
        for model in runtime.optimizer.models
    ]


def _resolve_model_choice(
    runtime: RuntimeConfig,
    requested_key: str | None,
    *,
    fallback_index: int = 0,
) -> RuntimeModelConfig | None:
    if requested_key:
        normalized = requested_key.strip().lower()
        exact = [
            model for model in runtime.optimizer.models
            if _model_key(model).lower() == normalized or model.model.lower() == normalized
        ]
        if len(exact) == 1:
            return exact[0]
    if not runtime.optimizer.models:
        return None
    index = min(max(fallback_index, 0), len(runtime.optimizer.models) - 1)
    return runtime.optimizer.models[index]


def effective_model_surface(root: str | Path = ".") -> dict[str, Any]:
    """Return effective proposer/evaluator selections for the workspace."""
    workspace_root = Path(root)
    runtime = load_runtime_config(str(workspace_root / "autoagent.yaml"))
    settings = load_workspace_settings(workspace_root)
    model_settings = settings.get("models", {}) if isinstance(settings.get("models"), dict) else {}

    proposer = _resolve_model_choice(runtime, model_settings.get("proposer"), fallback_index=0)
    evaluator = _resolve_model_choice(runtime, model_settings.get("evaluator"), fallback_index=1 if len(runtime.optimizer.models) > 1 else 0)

    def _surface_entry(model: RuntimeModelConfig | None, selected_key: str | None) -> dict[str, Any] | None:
        if model is None:
            return None
        return {
            "key": _model_key(model),
            "provider": model.provider,
            "model": model.model,
            "override": selected_key,
        }

    return {
        "proposer": _surface_entry(proposer, model_settings.get("proposer")),
        "evaluator": _surface_entry(evaluator, model_settings.get("evaluator")),
    }


def apply_model_overrides(runtime: RuntimeConfig, root: str | Path = ".") -> RuntimeConfig:
    """Apply proposer/evaluator workspace overrides to a runtime config copy."""
    updated = runtime.model_copy(deep=True)
    surface = effective_model_surface(root)
    proposer_key = surface.get("proposer", {}).get("key") if isinstance(surface.get("proposer"), dict) else None
    if proposer_key:
        matching = [model for model in updated.optimizer.models if _model_key(model) == proposer_key]
        if matching:
            remaining = [model for model in updated.optimizer.models if _model_key(model) != proposer_key]
            updated.optimizer.models = [matching[0], *remaining]
            updated.optimizer.models[0].role = "proposer"
    evaluator_key = surface.get("evaluator", {}).get("key") if isinstance(surface.get("evaluator"), dict) else None
    for model in updated.optimizer.models:
        if _model_key(model) == evaluator_key and model.role != "proposer":
            model.role = "evaluator"
    return updated


@click.group("model", invoke_without_command=True)
@click.pass_context
def model_group(ctx: click.Context) -> None:
    """Inspect and override workspace model preferences."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(show_models)


@model_group.command("list")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def list_models(json_output: bool = False) -> None:
    """List available runtime models."""
    if not Path(".autoagent").exists():
        raise click_error("No AutoAgent workspace found.")
    data = list_available_models()
    if json_output:
        click.echo(render_json_envelope("ok", data, next_command="autoagent model show"))
        return
    click.echo("Available models")
    for item in data:
        click.echo(f"  {item['key']}  role={item['role']}")


@model_group.command("show")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def show_models(json_output: bool = False) -> None:
    """Show the effective proposer and evaluator models."""
    if not Path(".autoagent").exists():
        raise click_error("No AutoAgent workspace found.")
    data = effective_model_surface()
    if json_output:
        click.echo(render_json_envelope("ok", data, next_command="autoagent model list"))
        return
    click.echo("Effective models")
    click.echo(f"  Proposer:  {data.get('proposer', {}).get('key', 'n/a')}")
    click.echo(f"  Evaluator: {data.get('evaluator', {}).get('key', 'n/a')}")


@model_group.command("set")
@click.argument("target", type=click.Choice(["proposer", "evaluator"], case_sensitive=False))
@click.argument("model_key")
def set_model(target: str, model_key: str) -> None:
    """Persist a proposer or evaluator workspace model override."""
    workspace_root = Path(".")
    if not (workspace_root / ".autoagent").exists():
        raise click_error("No AutoAgent workspace found.")
    available = list_available_models(workspace_root)
    available_keys = {item["key"].lower(): item["key"] for item in available}
    matched_key = available_keys.get(model_key.lower())
    if matched_key is None:
        short_matches = [item["key"] for item in available if item["model"].lower() == model_key.lower()]
        if len(short_matches) == 1:
            matched_key = short_matches[0]
    if matched_key is None:
        raise click.ClickException(f"Unknown model: {model_key}")

    settings = load_workspace_settings(workspace_root)
    models = settings.get("models", {}) if isinstance(settings.get("models"), dict) else {}
    models[target.lower()] = matched_key
    settings["models"] = models
    save_workspace_settings(settings, workspace_root)
    click.echo(f"Saved {target.lower()} override: {matched_key}")
