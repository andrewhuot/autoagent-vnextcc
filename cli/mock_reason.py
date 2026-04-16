"""Compute why mock mode is active, for R1.12 doctor UX."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


MockReason = Literal["disabled", "configured", "missing_provider_key"]


@dataclass(frozen=True)
class MockReasonResult:
    reason: MockReason
    detail: str

    @property
    def is_blocking(self) -> bool:
        return self.reason == "missing_provider_key"

    @property
    def is_warning(self) -> bool:
        return self.reason == "configured"


_PROVIDER_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENAI_API_KEY",
)


def _any_provider_key_present() -> bool:
    return any(str(os.environ.get(v, "")).strip() for v in _PROVIDER_ENV_VARS)


def _yaml_says_use_mock_true(config_path: str | Path) -> bool:
    """True if the raw YAML file explicitly sets optimizer.use_mock to true."""
    try:
        import yaml
    except ImportError:
        return False
    try:
        path = Path(config_path).expanduser()
        if not path.exists():
            return False
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return False
    optimizer = data.get("optimizer") if isinstance(data, dict) else None
    if not isinstance(optimizer, dict):
        return False
    return optimizer.get("use_mock") is True


def compute_mock_reason(
    *, runtime_use_mock: bool, config_path: str | Path | None
) -> MockReasonResult:
    """Given resolved runtime.optimizer.use_mock and the config path, explain why."""
    if not runtime_use_mock:
        return MockReasonResult("disabled", "Mock mode is off.")

    if config_path is not None and _yaml_says_use_mock_true(config_path):
        return MockReasonResult(
            "configured",
            "optimizer.use_mock is set to true in your agentlab.yaml.",
        )

    if not _any_provider_key_present():
        return MockReasonResult(
            "missing_provider_key",
            "No provider API key detected in the environment.",
        )

    # Runtime says mock, but YAML doesn't force it and a key is present —
    # usually means CLI flag / mode override. Treat as configured for UX.
    return MockReasonResult(
        "configured",
        "Mock mode is active (via CLI/mode override).",
    )
