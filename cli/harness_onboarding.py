"""First-run wizard that writes ``harness.models.{coordinator,worker}``.

Without these keys, :func:`builder.model_resolver.resolve_harness_model`
returns ``source="missing"`` and the coordinator-worker runtime falls
back to :class:`builder.worker_mode.WorkerMode.DETERMINISTIC`. Operators
who ran ``agentlab init`` with a live provider key but never declared
harness models would silently get canned worker outputs — exactly the
failure mode :class:`builder.worker_mode.WorkerModeConfigurationError`
was designed to surface.

This module provides a minimal prompt flow the onboarding code path
can call after the workspace + API key step. It:

1. Detects missing / invalid harness-model entries.
2. Prompts for provider + model per role (coordinator, worker).
3. Writes the new keys to ``agentlab.yaml`` while preserving all
   other top-level sections verbatim.

The public API takes injected ``prompt_fn`` / ``echo_fn`` callables so
tests can script answers without touching ``click.prompt``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import yaml

from builder.model_resolver import resolve_harness_model


# ---------------------------------------------------------------------------
# Provider + model catalogue
# ---------------------------------------------------------------------------

# The catalogue is intentionally small and opinionated. We pick one
# flagship coordinator model and one fast worker model per provider so
# users don't face a 40-way choice on first run. Operators who want
# something bespoke can hand-edit ``agentlab.yaml`` after the fact.
_PROVIDER_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "key": "anthropic",
        "label": "Anthropic",
        "api_key_env": "ANTHROPIC_API_KEY",
        "coordinator_models": ("claude-opus-4-6", "claude-sonnet-4-6"),
        "worker_models": ("claude-sonnet-4-6", "claude-haiku-4"),
    },
    {
        "key": "openai",
        "label": "OpenAI",
        "api_key_env": "OPENAI_API_KEY",
        "coordinator_models": ("gpt-5", "gpt-4.1"),
        "worker_models": ("gpt-4.1-mini", "gpt-4.1"),
    },
    {
        "key": "google",
        "label": "Google / Gemini",
        "api_key_env": "GOOGLE_API_KEY",
        "coordinator_models": ("gemini-2.5-pro", "gemini-2.5-flash"),
        "worker_models": ("gemini-2.5-flash", "gemini-2.5-pro"),
    },
)


PromptFn = Callable[[str, Sequence[str], str], str]
"""(label, choices, default) -> selected choice. Must return one of ``choices``."""

EchoFn = Callable[[str], None]


@dataclass(frozen=True)
class RoleModel:
    """Concrete harness model selection for one role."""

    provider: str
    model: str
    api_key_env: str


@dataclass(frozen=True)
class HarnessChoice:
    """Structured outcome of :func:`run_harness_wizard`."""

    coordinator: RoleModel
    worker: RoleModel


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def needs_harness_config(config_path: str | Path) -> bool:
    """Return True when ``agentlab.yaml`` lacks valid harness models.

    A workspace needs the wizard when *either* role resolves to
    ``source="missing"`` or the ``.invalid`` sentinel emitted for
    partial declarations (e.g. provider without model). We ignore the
    ``optimizer.models[0]`` fallback intentionally — it was never a
    harness declaration, just a legacy inheritance we want operators
    to make explicit.
    """
    path = Path(config_path)
    for role in ("coordinator", "worker"):
        resolution = resolve_harness_model(role, config_path=path)  # type: ignore[arg-type]
        source = resolution.source
        if source == "missing" or source.endswith(".invalid"):
            return True
        if not source.startswith("harness.models."):
            # Only accept an explicit harness-scoped source. The
            # optimizer.models[0] fallback means the operator has not
            # actually declared harness roles yet.
            return True
    return False


def run_harness_wizard(
    config_path: str | Path,
    *,
    prompt_fn: PromptFn,
    echo_fn: EchoFn,
) -> HarnessChoice:
    """Run the interactive flow and return the operator's choices.

    ``prompt_fn`` receives (label, choices, default) and must return a
    value from ``choices``. Returning an out-of-list value would bypass
    our validation, so we defensively fall back to ``default`` in that
    case rather than letting a typo leak into YAML.
    """
    del config_path  # accepted for symmetry; wizard is pure prompting
    echo_fn("")
    echo_fn("  Configure harness models")
    echo_fn("  ------------------------")
    echo_fn("  AgentLab runs a coordinator (planning) and workers (execution).")
    echo_fn("  Pick a provider + model for each so live workers can run.")
    echo_fn("")

    provider_keys = [entry["key"] for entry in _PROVIDER_CATALOG]
    provider_choice = _safe_choice(
        prompt_fn(
            "  Provider ("
            + ", ".join(f"{entry['key']}={entry['label']}" for entry in _PROVIDER_CATALOG)
            + ")",
            provider_keys,
            provider_keys[0],
        ),
        provider_keys,
        provider_keys[0],
    )
    provider_entry = next(entry for entry in _PROVIDER_CATALOG if entry["key"] == provider_choice)
    api_key_env = str(provider_entry["api_key_env"])

    coordinator_models = list(provider_entry["coordinator_models"])
    coordinator_model = _safe_choice(
        prompt_fn(
            f"  Coordinator model [{'/'.join(coordinator_models)}]",
            coordinator_models,
            coordinator_models[0],
        ),
        coordinator_models,
        coordinator_models[0],
    )

    worker_models = list(provider_entry["worker_models"])
    worker_model = _safe_choice(
        prompt_fn(
            f"  Worker model [{'/'.join(worker_models)}]",
            worker_models,
            worker_models[0],
        ),
        worker_models,
        worker_models[0],
    )

    return HarnessChoice(
        coordinator=RoleModel(
            provider=provider_entry["key"],
            model=coordinator_model,
            api_key_env=api_key_env,
        ),
        worker=RoleModel(
            provider=provider_entry["key"],
            model=worker_model,
            api_key_env=api_key_env,
        ),
    )


def write_harness_models(config_path: str | Path, choice: HarnessChoice) -> None:
    """Persist ``choice`` into ``agentlab.yaml`` without touching other keys.

    Loads the existing YAML with :func:`yaml.safe_load`, merges the new
    ``harness.models`` subtree, and dumps the result. Unrelated keys
    (``optimizer``, ``deployer``, ``evals``, …) are preserved verbatim.
    """
    path = Path(config_path)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except yaml.YAMLError:
            # Rather than silently wiping a malformed file, refuse to
            # write. The caller should surface this via doctor; first-run
            # onboarding will almost always start from empty or freshly
            # scaffolded YAML so this path is rare.
            raise

    harness_section = existing.get("harness")
    if not isinstance(harness_section, dict):
        harness_section = {}
    models_section = harness_section.get("models")
    if not isinstance(models_section, dict):
        models_section = {}

    models_section["coordinator"] = _role_to_mapping(choice.coordinator, role="coordinator")
    models_section["worker"] = _role_to_mapping(choice.worker, role="worker")
    harness_section["models"] = models_section
    existing["harness"] = harness_section

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(existing, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_choice(raw: str, choices: Sequence[str], default: str) -> str:
    value = str(raw or "").strip()
    if value in choices:
        return value
    return default


def _role_to_mapping(role_model: RoleModel, *, role: str) -> dict[str, Any]:
    return {
        "provider": role_model.provider,
        "model": role_model.model,
        "role": role,
        "api_key_env": role_model.api_key_env,
    }


__all__ = [
    "EchoFn",
    "HarnessChoice",
    "PromptFn",
    "RoleModel",
    "needs_harness_config",
    "run_harness_wizard",
    "write_harness_models",
]
