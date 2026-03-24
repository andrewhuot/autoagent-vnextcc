"""Runtime configuration schema for backend orchestration settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


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


class RuntimeConfig(BaseModel):
    """Top-level runtime settings loaded from `autoagent.yaml`."""

    optimizer: OptimizerRuntimeConfig = Field(default_factory=OptimizerRuntimeConfig)
    loop: LoopRuntimeConfig = Field(default_factory=LoopRuntimeConfig)
    eval: EvalRuntimeConfig = Field(default_factory=EvalRuntimeConfig)


def load_runtime_config(path: str = "autoagent.yaml") -> RuntimeConfig:
    """Load runtime settings from YAML, returning defaults when file is absent."""
    config_path = Path(path)
    if not config_path.exists():
        return RuntimeConfig()

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    return RuntimeConfig.model_validate(data)
