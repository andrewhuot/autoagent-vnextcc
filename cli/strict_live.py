"""Strict-live policy: turn silent mock fallback into a hard failure.

When --strict-live is passed to build/eval/optimize/deploy, any mock fallback
(provider 403, rate limit, missing key handled silently, etc.) raises
MockFallbackError. The CLI catches this and exits with EXIT_MOCK_FALLBACK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


class MockFallbackError(RuntimeError):
    """Raised when --strict-live is enabled and a mock fallback was detected."""

    def __init__(self, warnings: list[str]) -> None:
        joined = "\n  - ".join(warnings) if warnings else "(no warnings recorded)"
        super().__init__(
            "strict-live: command fell back to mock execution.\n"
            f"  - {joined}\n"
            "Hint: configure a real provider with `agentlab provider configure` "
            "or remove --strict-live to allow mock fallback."
        )
        self.warnings = list(warnings)


@dataclass
class StrictLivePolicy:
    enabled: bool
    warnings: list[str] = field(default_factory=list)

    def record_mock_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.enabled:
            raise MockFallbackError([warning])

    def ingest_existing_warnings(self, warnings: Iterable[str]) -> None:
        """Absorb warnings produced by lower layers (eval runner, etc.)
        without raising immediately. Call check() after to enforce."""
        for w in warnings:
            self.warnings.append(w)

    def has_fallback(self) -> bool:
        return bool(self.warnings)

    def check(self) -> None:
        """Final gate. Raises if strict mode is enabled and any fallback occurred."""
        if self.enabled and self.warnings:
            raise MockFallbackError(self.warnings)
