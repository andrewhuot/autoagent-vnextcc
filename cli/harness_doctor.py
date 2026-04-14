"""Coordinator/worker diagnostics surfaced from ``agentlab doctor``.

The goal: when a worker silently degrades to deterministic stubs —
because harness models are missing, invalid, or credentials aren't in
the env — the operator should see *exactly why* in ``/doctor`` without
grepping YAML and env vars themselves.

This module is a pure renderer. It reads the workspace's
``agentlab.yaml`` via :func:`builder.model_resolver.resolve_harness_model`
and consults the current process environment through
:func:`builder.model_resolver.missing_credential_env`. It never runs the
real runtime, never raises :class:`builder.worker_mode.WorkerModeConfigurationError`,
and never prompts — doctor must stay side-effect free.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from builder.model_resolver import missing_credential_env, resolve_harness_model
from builder.worker_mode import resolve_worker_mode


def render_coordinator_section(workspace: Any | None) -> str:
    """Return a ``/doctor``-style block describing the coordinator/worker runtime.

    Always returns a string (empty block when ``workspace`` is None) so
    callers can unconditionally append the result. Lines follow the
    existing doctor layout — two-space indent, colon-aligned labels,
    no ANSI colours (colour is applied by the caller when wanted).
    """
    lines: list[str] = []
    lines.append("Coordinator")
    lines.append("-----------")

    worker_mode = resolve_worker_mode()
    lines.append(f"  Worker mode:        {worker_mode.value}")

    if workspace is None:
        lines.append("  Coordinator model:  (no workspace)")
        lines.append("  Worker model:       (no workspace)")
        lines.append("  Credentials:        (no workspace)")
        return "\n".join(lines) + "\n"

    config_path = _resolve_config_path(workspace)

    coordinator = resolve_harness_model("coordinator", config_path=config_path)
    worker = resolve_harness_model("worker", config_path=config_path)

    lines.append(f"  Coordinator model:  {_format_role_line(coordinator)}")
    lines.append(f"  Worker model:       {_format_role_line(worker)}")
    lines.append(f"  Credentials:        {_format_credentials(coordinator, worker)}")

    return "\n".join(lines) + "\n"


def _resolve_config_path(workspace: Any) -> Path:
    """Best-effort resolution of the workspace's ``agentlab.yaml`` path."""
    candidate = getattr(workspace, "runtime_config_path", None)
    if isinstance(candidate, Path):
        return candidate
    root = getattr(workspace, "root", None)
    if isinstance(root, Path):
        return root / "agentlab.yaml"
    return Path("agentlab.yaml")


def _format_role_line(resolution: Any) -> str:
    """Render a single role's resolved config for display."""
    config = resolution.config
    source = resolution.source
    if config is None:
        if source.endswith(".invalid"):
            return f"invalid (source: {source}) — fix agentlab.yaml"
        return "not configured (source: missing) — workers will run deterministic stubs"
    return f"{config.provider}/{config.model} (source: {source})"


def _format_credentials(coordinator: Any, worker: Any) -> str:
    """Summarise credential state for both roles on one line."""
    missing: list[str] = []
    seen: set[str] = set()
    for resolution in (coordinator, worker):
        config = resolution.config
        if config is None:
            continue
        env_name = missing_credential_env(config)
        if env_name and env_name not in seen:
            missing.append(env_name)
            seen.add(env_name)
    if missing:
        return "missing " + ", ".join(missing) + " — live mode will fail"
    if coordinator.config is None and worker.config is None:
        return "not required (no harness models configured)"
    # Report which env var is satisfied so the operator knows *why* we
    # think live mode is reachable.
    provided = _provided_env_names(coordinator, worker)
    if provided:
        return "present (" + ", ".join(provided) + ")"
    return "not required (mock/local providers)"


def _provided_env_names(coordinator: Any, worker: Any) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for resolution in (coordinator, worker):
        config = resolution.config
        if config is None:
            continue
        env_name = getattr(config, "api_key_env", None) or _guess_env(config.provider)
        if env_name and env_name not in seen and os.environ.get(env_name):
            names.append(env_name)
            seen.add(env_name)
    return names


def _guess_env(provider: str) -> str | None:
    name = (provider or "").strip().lower()
    if name == "openai":
        return "OPENAI_API_KEY"
    if name == "anthropic":
        return "ANTHROPIC_API_KEY"
    if name == "google":
        return "GOOGLE_API_KEY"
    return None


__all__ = ["render_coordinator_section"]
