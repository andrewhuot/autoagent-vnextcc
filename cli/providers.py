"""Workspace-local provider configuration helpers for the CLI."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import yaml

from agent.config.runtime import RuntimeConfig, RuntimeModelConfig, load_runtime_config
from cli.workspace import AutoAgentWorkspace


DEFAULT_PROVIDER_MODELS: dict[str, str] = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-5",
    "google": "gemini-2.5-pro",
}
DEFAULT_PROVIDER_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def providers_file_path(workspace: AutoAgentWorkspace | None) -> Path:
    """Return the provider registry path for the current CLI scope."""
    if workspace is not None:
        return workspace.autoagent_dir / "providers.json"
    return Path(".autoagent") / "providers.json"


def default_model_for(provider: str) -> str:
    """Return the default model name for a provider."""
    return DEFAULT_PROVIDER_MODELS.get(provider.strip().lower(), "gpt-4o")


def default_api_key_env_for(provider: str) -> str:
    """Return the default API key environment variable for a provider."""
    return DEFAULT_PROVIDER_ENV_VARS.get(provider.strip().lower(), "OPENAI_API_KEY")


def load_provider_registry(path: Path) -> dict[str, Any]:
    """Load or initialize a provider registry JSON document."""
    if not path.exists():
        return {"default_provider": None, "providers": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"default_provider": None, "providers": []}
    providers = payload.get("providers")
    if not isinstance(providers, list):
        payload["providers"] = []
    payload.setdefault("default_provider", None)
    return payload


def save_provider_registry(path: Path, registry: dict[str, Any]) -> None:
    """Persist a provider registry JSON document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def upsert_provider(
    path: Path,
    *,
    provider: str,
    model: str,
    api_key_env: str,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Insert or replace one configured provider entry."""
    normalized_provider = provider.strip().lower()
    registry = load_provider_registry(path)
    providers = [
        item
        for item in registry.get("providers", [])
        if str(item.get("provider", "")).strip().lower() != normalized_provider
    ]
    providers.append(
        {
            "provider": normalized_provider,
            "model": model.strip(),
            "api_key_env": api_key_env.strip(),
            "base_url": base_url.strip() if base_url else None,
            "configured_at": time.time(),
        }
    )
    providers.sort(key=lambda item: str(item.get("provider", "")))
    registry["providers"] = providers
    registry["default_provider"] = normalized_provider
    save_provider_registry(path, registry)
    return registry


def configured_providers(path: Path) -> list[dict[str, Any]]:
    """Return configured providers from disk."""
    registry = load_provider_registry(path)
    result: list[dict[str, Any]] = []
    for item in registry.get("providers", []):
        result.append(
            {
                "provider": str(item.get("provider") or "").strip().lower(),
                "model": str(item.get("model") or "").strip(),
                "api_key_env": str(item.get("api_key_env") or "").strip(),
                "base_url": str(item.get("base_url") or "").strip() or None,
            }
        )
    return result


def sync_runtime_config(
    runtime_config_path: Path,
    *,
    provider: str,
    model: str,
    api_key_env: str,
    base_url: str | None = None,
) -> RuntimeConfig:
    """Update `autoagent.yaml` so CLI live-mode setup matches provider registry state."""
    runtime = load_runtime_config(str(runtime_config_path))
    runtime.optimizer.use_mock = False
    runtime.optimizer.models = [
        RuntimeModelConfig(
            provider=provider.strip().lower(),
            model=model.strip(),
            api_key_env=api_key_env.strip(),
            base_url=base_url.strip() if base_url else None,
        )
    ]
    runtime_config_path.write_text(
        yaml.safe_dump(runtime.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    return runtime


def provider_health_checks(path: Path, env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Return lightweight readiness checks for configured providers."""
    environment = env or os.environ
    checks: list[dict[str, Any]] = []
    for provider in configured_providers(path):
        env_name = provider.get("api_key_env")
        credential_present = bool(env_name and environment.get(env_name))
        checks.append(
            {
                **provider,
                "credential_present": credential_present,
                "message": (
                    f"{provider['provider']}:{provider['model']} is ready"
                    if credential_present
                    else f"Missing {env_name} for {provider['provider']}:{provider['model']}"
                ),
            }
        )
    return checks
