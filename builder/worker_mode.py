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
from enum import Enum


class WorkerMode(str, Enum):
    """Execution mode for coordinator-owned worker nodes."""

    DETERMINISTIC = "deterministic"
    LLM = "llm"
    HYBRID = "hybrid"


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


__all__ = [
    "DEFAULT_WORKER_MODE",
    "WorkerMode",
    "resolve_worker_mode",
]
