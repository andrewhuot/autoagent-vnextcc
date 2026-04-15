"""Worker execution mode resolution for the coordinator runtime.

The coordinator-worker runtime has two execution paths:

- ``DETERMINISTIC`` — the default :class:`DeterministicWorkerAdapter`
  produces offline-safe, role-aware artifacts without any provider call.
  Used in CI, offline development, and fallback when LLM config is missing.
- ``LLM`` — the :class:`LLMWorkerAdapter` calls a real provider through
  :class:`optimizer.providers.LLMRouter` to generate worker outputs.
- ``HYBRID`` — reserved for mixed pipelines where some roles are LLM-backed
  and others run deterministically; resolved by per-role adapter registration
  rather than a runtime-wide mode.

Callers select a mode via the ``AGENTLAB_WORKER_MODE`` environment variable
or by passing a :class:`WorkerMode` directly into the runtime. The resolver
treats missing / unreadable environment as deterministic so tests and
sandbox launches remain safe by default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class WorkerMode(str, Enum):
    """Execution mode for coordinator-owned worker nodes."""

    DETERMINISTIC = "deterministic"
    LLM = "llm"
    HYBRID = "hybrid"


class WorkerModeConfigurationError(RuntimeError):
    """Raised when the requested :class:`WorkerMode` is not satisfiable.

    Explicit ``WorkerMode.LLM`` without a valid ``harness.models.worker``
    entry must not silently degrade to deterministic — operators would
    believe real workers were running. The runtime raises this error
    instead, with a message that points to ``/doctor`` for diagnosis.
    """


DEFAULT_WORKER_MODE = WorkerMode.DETERMINISTIC
"""Fallback mode when no override is configured."""


_WORKER_MODE_ENV = "AGENTLAB_WORKER_MODE"


def resolve_worker_mode(env: dict[str, str] | None = None) -> WorkerMode:
    """Return the configured :class:`WorkerMode` from the environment.

    Unknown values degrade to :attr:`DEFAULT_WORKER_MODE` rather than
    raising — startup should never be blocked by a typo in an env var.
    """
    source = env if env is not None else os.environ
    raw = str(source.get(_WORKER_MODE_ENV, "")).strip().lower()
    if not raw:
        return DEFAULT_WORKER_MODE
    try:
        return WorkerMode(raw)
    except ValueError:
        return DEFAULT_WORKER_MODE


@dataclass(frozen=True)
class EffectiveWorkerMode:
    """Resolved runtime mode plus the reason we landed there.

    ``mode`` is what the runtime will actually use. ``source`` names the
    decision path (``"env"``, ``"autoselect.llm"``, ``"autoselect.deterministic"``)
    and ``reason`` is a one-line human-readable explanation suitable for
    ``/doctor`` output and transcript annotations.
    """

    mode: WorkerMode
    source: str
    reason: str


def resolve_effective_worker_mode(
    *,
    env: dict[str, str] | None = None,
    config_path: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> EffectiveWorkerMode:
    """Return the mode the runtime should use plus why.

    Decision order:

    1. ``AGENTLAB_WORKER_MODE`` env var wins when set and recognized — CI
       and tests pin deterministic this way, and power users force LLM
       against non-standard configs.
    2. Otherwise, check ``harness.models.worker`` (and ``optimizer.models[0]``
       fallback). When a valid model config resolves AND its credential env
       var is present, auto-select :attr:`WorkerMode.LLM`.
    3. Otherwise, fall back to :attr:`WorkerMode.DETERMINISTIC` with a
       reason string that names the first missing precondition.

    We perform the harness-model import lazily so this module stays cheap
    to import from early startup paths (``agentlab doctor``, CLI banner).
    """
    source = env if env is not None else os.environ
    raw = str(source.get(_WORKER_MODE_ENV, "")).strip().lower()
    if raw:
        try:
            explicit = WorkerMode(raw)
        except ValueError:
            return EffectiveWorkerMode(
                mode=DEFAULT_WORKER_MODE,
                source="env.invalid",
                reason=(
                    f"{_WORKER_MODE_ENV}={raw!r} is not a recognized mode; "
                    "using deterministic default."
                ),
            )
        return EffectiveWorkerMode(
            mode=explicit,
            source="env",
            reason=f"{_WORKER_MODE_ENV}={explicit.value} set explicitly.",
        )

    try:
        from builder.model_resolver import missing_credential_env, resolve_harness_model

        resolution = resolve_harness_model("worker", config=config, config_path=config_path)
    except Exception as exc:  # pragma: no cover - defensive: import/config errors
        return EffectiveWorkerMode(
            mode=DEFAULT_WORKER_MODE,
            source="autoselect.deterministic",
            reason=f"worker model resolver failed ({exc}); staying deterministic.",
        )

    if resolution.config is None:
        return EffectiveWorkerMode(
            mode=DEFAULT_WORKER_MODE,
            source="autoselect.deterministic",
            reason=(
                "no worker model configured in harness.models.worker or "
                "optimizer.models[0] — add one to run live workers."
            ),
        )

    missing = missing_credential_env(resolution.config)
    if missing:
        return EffectiveWorkerMode(
            mode=DEFAULT_WORKER_MODE,
            source="autoselect.deterministic",
            reason=(
                f"{resolution.config.provider}/{resolution.config.model} requires "
                f"{missing} but it is not set; staying deterministic."
            ),
        )

    return EffectiveWorkerMode(
        mode=WorkerMode.LLM,
        source="autoselect.llm",
        reason=(
            f"auto-selected LLM: harness.models.worker resolved to "
            f"{resolution.config.provider}/{resolution.config.model} with credentials."
        ),
    )


__all__ = [
    "DEFAULT_WORKER_MODE",
    "EffectiveWorkerMode",
    "WorkerMode",
    "WorkerModeConfigurationError",
    "resolve_effective_worker_mode",
    "resolve_worker_mode",
]
