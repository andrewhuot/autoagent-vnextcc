"""Runtime configuration schema for backend orchestration settings."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


_LEGACY_TO_MODE = {
    "simple": "standard",
    "adaptive": "advanced",
    "full": "research",
    "pro": "research",
}


def _legacy_strategy_to_mode(strategy: str | None) -> str:
    normalized = (strategy or "").strip().lower()
    return _LEGACY_TO_MODE.get(normalized, "standard")


def _mode_to_legacy_strategy(mode: str | None) -> str:
    normalized = (mode or "").strip().lower()
    if normalized == "advanced":
        return "adaptive"
    if normalized == "research":
        return "full"
    return "simple"


class RetryConfig(BaseModel):
    """Retry/backoff controls for outbound provider calls."""

    max_attempts: int = Field(3, ge=1, le=10)
    base_delay_seconds: float = Field(0.5, ge=0.0, le=30.0)
    max_delay_seconds: float = Field(8.0, ge=0.0, le=120.0)
    jitter_seconds: float = Field(0.25, ge=0.0, le=5.0)


class RuntimeModelConfig(BaseModel):
    """Single optimizer model configuration."""

    provider: str
    model: str
    role: str = "default"
    api_key_env: str | None = None
    base_url: str | None = None
    timeout_seconds: float = Field(30.0, ge=1.0, le=300.0)
    requests_per_minute: int = Field(60, ge=1, le=10000)
    input_cost_per_1k_tokens: float = Field(0.0, ge=0.0)
    output_cost_per_1k_tokens: float = Field(0.0, ge=0.0)


class OptimizerRuntimeConfig(BaseModel):
    """Runtime settings for optimization proposer model orchestration."""

    use_mock: bool = True
    strategy: Literal["single", "round_robin", "ensemble", "mixture"] = "single"
    search_strategy: Literal["simple", "adaptive", "full"] = "simple"
    bandit_policy: Literal["ucb", "thompson"] = "thompson"
    search_max_candidates: int = Field(10, ge=1, le=200)
    search_max_eval_budget: int = Field(5, ge=1, le=200)
    search_max_cost_dollars: float = Field(1.0, ge=0.0, le=1000.0)
    search_time_budget_seconds: float = Field(300.0, ge=1.0, le=36000.0)
    holdout_tolerance: float = Field(0.0, ge=0.0, le=1.0)
    holdout_rotation_interval: int = Field(5, ge=1, le=1000)
    drift_threshold: float = Field(0.12, ge=0.0, le=1.0)
    max_judge_variance: float = Field(0.03, ge=0.0, le=1.0)
    models: list[RuntimeModelConfig] = Field(
        default_factory=lambda: [RuntimeModelConfig(provider="mock", model="mock-proposer")]
    )
    retry: RetryConfig = Field(default_factory=RetryConfig)


class LoopRuntimeConfig(BaseModel):
    """Runtime settings for long-running loop reliability behavior."""

    schedule_mode: Literal["continuous", "interval", "cron"] = "continuous"
    interval_minutes: float = Field(5.0, ge=0.0, le=1440.0)
    cron: str = "*/5 * * * *"
    checkpoint_path: str = ".autoagent/loop_checkpoint.json"
    dead_letter_db: str = ".autoagent/dead_letters.db"
    watchdog_timeout_seconds: float = Field(300.0, ge=1.0, le=86400.0)
    resource_warn_memory_mb: float = Field(2048.0, ge=1.0)
    resource_warn_cpu_percent: float = Field(90.0, ge=1.0, le=1000.0)
    structured_log_path: str = ".autoagent/logs/backend.jsonl"
    log_max_bytes: int = Field(5_000_000, ge=10_000)
    log_backup_count: int = Field(5, ge=1, le=100)


class EvalRuntimeConfig(BaseModel):
    """Runtime settings for eval pipeline and significance gating."""

    history_db_path: str = "eval_history.db"
    dataset_path: str | None = None
    dataset_split: Literal["train", "test", "all"] = "test"
    significance_alpha: float = Field(0.05, ge=0.0001, le=0.5)
    significance_min_effect_size: float = Field(0.005, ge=0.0, le=1.0)
    significance_iterations: int = Field(2000, ge=100, le=50000)


class BudgetRuntimeConfig(BaseModel):
    """Production cost controls (from R2 simplicity thesis)."""

    per_cycle_dollars: float = Field(1.0, ge=0.0, le=10000.0)
    daily_dollars: float = Field(10.0, ge=0.0, le=100000.0)
    stall_threshold_cycles: int = Field(5, ge=1, le=1000)
    tracker_db_path: str = ".autoagent/cost_tracker.db"


class OptimizationConfig(BaseModel):
    """New user-facing optimization config (objective-first).

    This replaces the algorithm-centric knobs (search_strategy, bandit_policy)
    with a goal-oriented surface: pick a mode, state your objective, set
    guardrails and budgets.  The ``ModeRouter`` translates these into the
    internal strategy parameters the optimizer needs.
    """

    mode: Literal["standard", "advanced", "research"] = "standard"
    objective: str = ""
    guardrails: list[str] = Field(default_factory=list)
    budget_per_cycle: float = Field(1.0, ge=0.0, le=10000.0)
    budget_daily: float = Field(10.0, ge=0.0, le=100000.0)
    autonomy: Literal["supervised", "semi-auto", "autonomous"] = "supervised"
    allowed_surfaces: list[str] = Field(
        default_factory=lambda: ["instructions", "examples", "tool_descriptions"]
    )


class RuntimeConfig(BaseModel):
    """Top-level runtime settings loaded from `autoagent.yaml`."""

    optimizer: OptimizerRuntimeConfig = Field(default_factory=OptimizerRuntimeConfig)
    loop: LoopRuntimeConfig = Field(default_factory=LoopRuntimeConfig)
    eval: EvalRuntimeConfig = Field(default_factory=EvalRuntimeConfig)
    budget: BudgetRuntimeConfig = Field(default_factory=BudgetRuntimeConfig)
    optimization: OptimizationConfig = Field(default_factory=OptimizationConfig)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy(cls, raw: object) -> object:
        """Migrate legacy strategy-centric config to optimization-first fields."""
        if isinstance(raw, dict):
            return migrate_legacy_runtime_config(raw)
        return raw


def migrate_legacy_runtime_config(data: dict) -> dict:
    """Convert legacy strategy-centric config keys into optimization-first fields."""
    migrated = copy.deepcopy(data)
    optimizer = migrated.get("optimizer")
    if not isinstance(optimizer, dict):
        optimizer = {}
        migrated["optimizer"] = optimizer

    optimization = migrated.get("optimization")
    if not isinstance(optimization, dict):
        optimization = {}
        migrated["optimization"] = optimization

    # Infer mode from legacy search_strategy if not explicitly set
    resolved_mode = optimization.get("mode")
    if not isinstance(resolved_mode, str) or not resolved_mode.strip():
        resolved_mode = _legacy_strategy_to_mode(
            str(optimizer.get("search_strategy", "simple"))
        )
    optimization["mode"] = resolved_mode

    # Default objective
    if not isinstance(optimization.get("objective"), str) or not optimization.get("objective", "").strip():
        optimization["objective"] = "Maximize task success while honoring guardrails."

    # Normalize guardrails
    guardrails = optimization.get("guardrails")
    if not isinstance(guardrails, list):
        optimization["guardrails"] = []

    # Normalize autonomy
    autonomy = str(optimization.get("autonomy", "supervised")).strip().lower()
    if autonomy not in {"supervised", "semi-auto", "autonomous"}:
        autonomy = "supervised"
    optimization["autonomy"] = autonomy

    # Back-fill legacy search_strategy from mode
    optimizer.setdefault("search_strategy", _mode_to_legacy_strategy(resolved_mode))
    optimizer.setdefault("bandit_policy", "thompson")
    return migrated


def load_runtime_config(path: str = "autoagent.yaml") -> RuntimeConfig:
    """Load runtime settings from YAML, returning defaults when file is absent."""
    config_path = Path(path)
    if not config_path.exists():
        return RuntimeConfig()

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    return RuntimeConfig.model_validate(data)
