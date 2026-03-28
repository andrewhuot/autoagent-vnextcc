"""Extended thinking support: per-component configuration and cost tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ThinkingConfig:
    enabled: bool = False
    budget_tokens: int = 10000
    components: list[str] = field(
        default_factory=lambda: ["proposer", "judge", "diagnose"]
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "budget_tokens": self.budget_tokens,
            "components": self.components,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThinkingConfig":
        return cls(
            enabled=data.get("enabled", False),
            budget_tokens=data.get("budget_tokens", 10000),
            components=data.get("components", ["proposer", "judge", "diagnose"]),
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ThinkingModeManager:
    """Configure and monitor extended thinking budgets per agent component."""

    def __init__(self) -> None:
        self._configs: dict[str, ThinkingConfig] = {}
        self._token_usage: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(self, component: str, enabled: bool, budget: int) -> None:
        """Set the thinking mode for *component*."""
        existing = self._configs.get(component, ThinkingConfig())
        self._configs[component] = ThinkingConfig(
            enabled=enabled,
            budget_tokens=budget,
            components=existing.components,
        )

    def get_config(self, component: str) -> ThinkingConfig:
        """Return the ThinkingConfig for *component*, creating a default if absent."""
        if component not in self._configs:
            self._configs[component] = ThinkingConfig()
        return self._configs[component]

    # ------------------------------------------------------------------
    # Tracking
    # ------------------------------------------------------------------

    def track_thinking_tokens(self, component: str, tokens_used: int) -> None:
        """Record that *component* consumed *tokens_used* thinking tokens."""
        self._token_usage[component] = self._token_usage.get(component, 0) + tokens_used

    def get_thinking_cost_report(self) -> dict[str, Any]:
        """Return a summary of thinking token usage and budget utilisation."""
        report: dict[str, Any] = {}
        all_components = set(self._configs) | set(self._token_usage)
        total_used = 0
        total_budget = 0
        for component in sorted(all_components):
            cfg = self._configs.get(component, ThinkingConfig())
            used = self._token_usage.get(component, 0)
            budget = cfg.budget_tokens if cfg.enabled else 0
            utilisation = (used / budget * 100) if budget else 0.0
            total_used += used
            total_budget += budget
            report[component] = {
                "enabled": cfg.enabled,
                "budget_tokens": cfg.budget_tokens,
                "tokens_used": used,
                "utilisation_pct": round(utilisation, 2),
            }
        report["_totals"] = {
            "total_tokens_used": total_used,
            "total_budget": total_budget,
            "overall_utilisation_pct": round(total_used / total_budget * 100, 2) if total_budget else 0.0,
        }
        return report
