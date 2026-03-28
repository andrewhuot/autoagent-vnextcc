"""Abstract training backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from policy_opt.types import TrainingJob, TrainingMode, TrainingStatus


class TrainingBackend(ABC):
    """Abstract interface for provider-specific training backends.

    Each backend handles dataset validation, training job lifecycle,
    and result retrieval for its provider's API.
    """

    name: str = ""
    supported_modes: list[TrainingMode] = []

    @abstractmethod
    def validate_dataset(self, path: str, mode: TrainingMode) -> list[str]:
        """Validate dataset format for this backend. Returns list of errors (empty = valid)."""

    @abstractmethod
    def start_training(self, job: TrainingJob) -> str:
        """Start a training job. Returns provider job ID."""

    @abstractmethod
    def check_status(self, provider_job_id: str) -> TrainingStatus:
        """Check current status of a provider training job."""

    @abstractmethod
    def get_result(self, provider_job_id: str) -> dict[str, Any]:
        """Get result/artifact from a completed job."""

    @abstractmethod
    def cancel(self, provider_job_id: str) -> bool:
        """Cancel a running job. Returns True if cancelled."""

    def supports_mode(self, mode: TrainingMode) -> bool:
        return mode in self.supported_modes


_BACKENDS: dict[str, type[TrainingBackend]] = {}


def register_backend(name: str):
    """Decorator to register a backend class."""
    def wrapper(cls):
        _BACKENDS[name] = cls
        return cls
    return wrapper


def get_backend(name: str) -> TrainingBackend:
    """Get a backend instance by name. Raises KeyError if unknown."""
    if name not in _BACKENDS:
        raise KeyError(f"Unknown training backend: {name}. Available: {list(_BACKENDS.keys())}")
    return _BACKENDS[name]()


def list_backends() -> list[str]:
    return list(_BACKENDS.keys())
