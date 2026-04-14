"""Harness model resolution for the coordinator and its workers.

The user may declare which models back the coordinator planning layer and
the worker execution layer via two keys in ``agentlab.yaml``::

    harness:
      models:
        coordinator:
          provider: anthropic
          model: claude-opus-4-6
          api_key_env: ANTHROPIC_API_KEY
        worker:
          provider: anthropic
          model: claude-sonnet-4-6
          api_key_env: ANTHROPIC_API_KEY

Both keys are optional. When absent, the resolver falls back to the first
``optimizer.models`` entry so existing single-provider workspaces keep
working, then finally to ``None`` so callers can decide whether to degrade
to deterministic mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from optimizer.providers import ModelConfig


HarnessRole = Literal["coordinator", "worker"]


@dataclass(frozen=True)
class ModelResolution:
    """Outcome of resolving a harness role to a concrete model configuration."""

    role: HarnessRole
    config: ModelConfig | None
    source: str
    """Where the configuration came from: ``"harness.models.*"`` |
    ``"optimizer.models[0]"`` | ``"missing"``."""


def resolve_harness_model(
    role: HarnessRole,
    *,
    config: dict[str, Any] | None = None,
    config_path: str | Path | None = None,
) -> ModelResolution:
    """Return the :class:`ModelConfig` backing ``role`` for the harness.

    Prefers ``harness.models.<role>`` when set. Falls back to the first
    ``optimizer.models`` entry so users who haven't yet declared harness
    keys still get a working worker. Returns ``ModelResolution.config=None``
    when nothing is configured — the runtime should then degrade to
    :class:`builder.worker_mode.WorkerMode.DETERMINISTIC`.
    """
    data = _load_config(config=config, config_path=config_path)
    harness_section = _maybe_mapping(data.get("harness"))
    models_section = _maybe_mapping(harness_section.get("models"))
    role_section = _maybe_mapping(models_section.get(role))
    if role_section:
        return ModelResolution(
            role=role,
            config=_to_model_config(role_section, default_role=role),
            source=f"harness.models.{role}",
        )

    optimizer_section = _maybe_mapping(data.get("optimizer"))
    optimizer_models = optimizer_section.get("models")
    if isinstance(optimizer_models, list) and optimizer_models:
        first = _maybe_mapping(optimizer_models[0])
        if first:
            return ModelResolution(
                role=role,
                config=_to_model_config(first, default_role=role),
                source="optimizer.models[0]",
            )

    return ModelResolution(role=role, config=None, source="missing")


def _load_config(
    *,
    config: dict[str, Any] | None,
    config_path: str | Path | None,
) -> dict[str, Any]:
    """Return the agentlab config dict, tolerating absent files."""
    if config is not None:
        return config
    path = Path(config_path) if config_path else Path("agentlab.yaml")
    if not path.exists():
        return {}
    try:
        import yaml

        with path.open("r", encoding="utf-8") as stream:
            loaded = yaml.safe_load(stream) or {}
        return loaded if isinstance(loaded, dict) else {}
    except Exception:  # pragma: no cover - defensive: bad YAML should not crash startup
        return {}


def _maybe_mapping(value: Any) -> dict[str, Any]:
    """Coerce arbitrary config values to a dict for safe attribute access."""
    return value if isinstance(value, dict) else {}


def _to_model_config(raw: dict[str, Any], *, default_role: str) -> ModelConfig:
    """Build a :class:`ModelConfig` from a raw YAML mapping with defaults."""
    return ModelConfig(
        provider=str(raw.get("provider") or "google"),
        model=str(raw.get("model") or "gemini-2.5-flash"),
        role=str(raw.get("role") or default_role),
        api_key_env=raw.get("api_key_env"),
        base_url=raw.get("base_url"),
        timeout_seconds=float(raw.get("timeout_seconds", 30.0)),
        requests_per_minute=int(raw.get("requests_per_minute", 60)),
        input_cost_per_1k_tokens=float(raw.get("input_cost_per_1k_tokens", 0.0)),
        output_cost_per_1k_tokens=float(raw.get("output_cost_per_1k_tokens", 0.0)),
    )


__all__ = [
    "HarnessRole",
    "ModelResolution",
    "resolve_harness_model",
]
