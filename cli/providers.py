"""Workspace-local provider configuration helpers for the CLI."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import yaml

from agent.config.runtime import RuntimeConfig, RuntimeModelConfig, load_runtime_config
from cli.workspace import AgentLabWorkspace
from cli.workspace_env import load_workspace_env


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


def normalize_model_name(provider: str, model: str) -> str:
    """Accept either bare model names or `provider:model` strings for one provider."""
    normalized_provider = provider.strip().lower()
    cleaned = model.strip()
    if ":" not in cleaned:
        return cleaned

    prefix, remainder = cleaned.split(":", 1)
    if prefix.strip().lower() == normalized_provider and remainder.strip():
        return remainder.strip()
    return cleaned


def providers_file_path(workspace: AgentLabWorkspace | None) -> Path:
    """Return the provider registry path for the current CLI scope."""
    if workspace is not None:
        return workspace.agentlab_dir / "providers.json"
    return Path(".agentlab") / "providers.json"


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
    normalized_model = normalize_model_name(normalized_provider, model)
    registry = load_provider_registry(path)
    providers = [
        item
        for item in registry.get("providers", [])
        if str(item.get("provider", "")).strip().lower() != normalized_provider
    ]
    providers.append(
        {
            "provider": normalized_provider,
            "model": normalized_model,
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


def runtime_configured_providers(runtime_config_path: Path | str = "agentlab.yaml") -> list[dict[str, Any]]:
    """Return provider entries declared in the workspace runtime config.

    WHY: `agentlab.yaml` is the provider source used by doctor, mode, Build,
    Eval, and Optimize. Provider CLI commands should still be useful before the
    optional `.agentlab/providers.json` registry has been explicitly created.
    """
    runtime = load_runtime_config(str(runtime_config_path))
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for model in runtime.optimizer.models:
        key = (model.provider, model.model, model.api_key_env)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "provider": model.provider,
                "model": model.model,
                "api_key_env": model.api_key_env or "",
                "base_url": model.base_url,
            }
        )
    return result


def configured_or_runtime_providers(
    path: Path,
    *,
    runtime_config_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return registry providers, falling back to runtime-config providers."""
    registry_providers = configured_providers(path)
    if registry_providers:
        return [{**provider, "source": "registry"} for provider in registry_providers]

    resolved_runtime_path = runtime_config_path or path.parent.parent / "agentlab.yaml"
    return [
        {**provider, "source": "runtime config"}
        for provider in runtime_configured_providers(resolved_runtime_path)
    ]


def sync_runtime_config(
    runtime_config_path: Path,
    *,
    provider: str,
    model: str,
    api_key_env: str,
    base_url: str | None = None,
) -> RuntimeConfig:
    """Update `agentlab.yaml` so CLI live-mode setup matches provider registry state."""
    runtime = load_runtime_config(str(runtime_config_path))
    runtime.optimizer.use_mock = False
    normalized_provider = provider.strip().lower()
    normalized_model = normalize_model_name(normalized_provider, model)
    runtime.optimizer.models = [
        RuntimeModelConfig(
            provider=normalized_provider,
            model=normalized_model,
            api_key_env=api_key_env.strip(),
            base_url=base_url.strip() if base_url else None,
        )
    ]
    runtime_config_path.write_text(
        yaml.safe_dump(runtime.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    return runtime


def provider_health_checks(
    path: Path,
    env: dict[str, str] | None = None,
    *,
    runtime_config_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return lightweight readiness checks for configured providers."""
    environment = env if env is not None else os.environ
    resolved_runtime_path = Path(runtime_config_path) if runtime_config_path is not None else path.parent.parent / "agentlab.yaml"
    load_workspace_env(resolved_runtime_path.parent, override=False, environ=environment)
    checks: list[dict[str, Any]] = []
    for provider in configured_or_runtime_providers(path, runtime_config_path=resolved_runtime_path):
        env_name = provider.get("api_key_env")
        credential_present = bool(env_name and environment.get(env_name))
        checks.append(
            {
                **provider,
                "credential_present": credential_present,
                "message": (
                    f"{provider['provider']}:{provider['model']} has credentials configured (live probe not run)"
                    if credential_present
                    else f"Missing {env_name} for {provider['provider']}:{provider['model']}"
                ),
            }
        )
    return checks


def redact_provider_secrets(message: str, environment: dict[str, str]) -> str:
    """Remove credential values from provider error text before it reaches users."""
    redacted = message
    for env_name in DEFAULT_PROVIDER_ENV_VARS.values():
        value = environment.get(env_name)
        if value and len(value) >= 8:
            redacted = redacted.replace(value, "[redacted]")
    return redacted


def provider_live_error_hint(provider: str, env_name: str | None, detail: str) -> str:
    """Return a next-step hint because live provider failures are usually fixable setup issues."""
    provider_name = provider.strip().lower()
    detail_lower = detail.lower()
    key_label = env_name or "the provider API key"
    if "401" in detail_lower or "403" in detail_lower or "permission" in detail_lower:
        if provider_name == "google":
            return (
                f"Check that {key_label} is valid, the Gemini API is enabled for the key's project, "
                "and the selected Gemini model is allowed."
            )
        return f"Check that {key_label} is valid and has access to the selected model."
    if "404" in detail_lower or "not found" in detail_lower:
        return "Check the model name and base URL in agentlab.yaml or .agentlab/providers.json."
    if "timeout" in detail_lower or "timed out" in detail_lower:
        return "The provider request timed out; retry or check local network access."
    return "Check provider credentials, model access, and network connectivity."


def provider_live_health_checks(
    path: Path,
    env: dict[str, str] | None = None,
    *,
    runtime_config_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Make tiny provider API calls so `provider test --live` validates real connectivity."""
    from optimizer.providers import LLMRequest, LLMRouter, ModelConfig

    environment = env if env is not None else os.environ
    resolved_runtime_path = Path(runtime_config_path) if runtime_config_path is not None else path.parent.parent / "agentlab.yaml"
    load_workspace_env(resolved_runtime_path.parent, override=False, environ=environment)

    checks: list[dict[str, Any]] = []
    for provider in configured_or_runtime_providers(path, runtime_config_path=resolved_runtime_path):
        env_name = str(provider.get("api_key_env") or "").strip()
        if not (env_name and environment.get(env_name)):
            continue

        provider_name = str(provider.get("provider") or "").strip().lower()
        model_name = str(provider.get("model") or "").strip()
        try:
            router = LLMRouter(
                strategy="single",
                models=[
                    ModelConfig(
                        provider=provider_name,
                        model=model_name,
                        api_key_env=env_name,
                        base_url=provider.get("base_url"),
                        timeout_seconds=15.0,
                    )
                ],
            )
            response = router.generate(
                LLMRequest(
                    prompt="Reply with exactly: AgentLab provider check ok",
                    temperature=0,
                    max_tokens=16,
                )
            )
            checks.append(
                {
                    **provider,
                    "live_ok": True,
                    "message": f"{response.provider}:{response.model} accepted a live provider probe",
                }
            )
        except Exception as exc:  # noqa: BLE001 - provider SDK/HTTP failures vary by backend.
            raw_detail = str(exc) or exc.__class__.__name__
            detail = redact_provider_secrets(raw_detail, environment)
            hint = provider_live_error_hint(provider_name, env_name, detail)
            checks.append(
                {
                    **provider,
                    "live_ok": False,
                    "message": f"{provider_name}:{model_name} rejected the live probe ({detail}). {hint}",
                }
            )
    return checks
