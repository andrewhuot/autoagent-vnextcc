"""Unit tests for agent.config.runtime — OptimizationConfig and RuntimeConfig."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agent.config.runtime import (
    OptimizationConfig,
    RuntimeConfig,
    load_runtime_config,
)


class TestOptimizationConfigDefaults:
    def test_default_optimization_config(self):
        cfg = OptimizationConfig()
        assert cfg.mode == "standard"
        assert cfg.objective == ""
        assert cfg.guardrails == []
        assert cfg.budget_per_cycle == 1.0
        assert cfg.budget_daily == 10.0
        assert cfg.autonomy == "supervised"
        assert "instructions" in cfg.allowed_surfaces


class TestRuntimeConfigIntegration:
    def test_optimization_config_in_runtime(self):
        rc = RuntimeConfig()
        assert rc.optimization is not None
        assert rc.optimization.mode == "standard"

    def test_load_runtime_config_with_optimization(self, tmp_path: Path):
        data = {
            "optimization": {
                "mode": "advanced",
                "objective": "Maximize task success",
                "guardrails": ["No safety regressions"],
                "budget_per_cycle": 2.0,
                "budget_daily": 20.0,
                "autonomy": "semi-auto",
            }
        }
        cfg_file = tmp_path / "autoagent.yaml"
        cfg_file.write_text(yaml.dump(data), encoding="utf-8")

        rc = load_runtime_config(str(cfg_file))
        assert rc.optimization.mode == "advanced"
        assert rc.optimization.objective == "Maximize task success"
        assert rc.optimization.budget_per_cycle == 2.0
        assert rc.optimization.autonomy == "semi-auto"

    def test_load_runtime_config_without_optimization(self, tmp_path: Path):
        data = {"optimizer": {"use_mock": True}}
        cfg_file = tmp_path / "autoagent.yaml"
        cfg_file.write_text(yaml.dump(data), encoding="utf-8")

        rc = load_runtime_config(str(cfg_file))
        # Falls back to defaults
        assert rc.optimization.mode == "standard"
        assert rc.optimization.budget_per_cycle == 1.0

    def test_optimization_config_validation(self):
        with pytest.raises(ValidationError):
            OptimizationConfig(mode="turbo")  # type: ignore[arg-type]

    def test_legacy_strategy_migration(self, tmp_path: Path):
        """Legacy search_strategy in optimizer block auto-migrates to optimization.mode."""
        data = {"optimizer": {"search_strategy": "adaptive", "use_mock": True}}
        cfg_file = tmp_path / "autoagent.yaml"
        cfg_file.write_text(yaml.dump(data), encoding="utf-8")

        rc = load_runtime_config(str(cfg_file))
        assert rc.optimization.mode == "advanced"

    def test_legacy_full_strategy_migration(self, tmp_path: Path):
        data = {"optimizer": {"search_strategy": "full", "use_mock": True}}
        cfg_file = tmp_path / "autoagent.yaml"
        cfg_file.write_text(yaml.dump(data), encoding="utf-8")

        rc = load_runtime_config(str(cfg_file))
        assert rc.optimization.mode == "research"

    def test_explicit_mode_overrides_legacy(self, tmp_path: Path):
        data = {
            "optimizer": {"search_strategy": "full"},
            "optimization": {"mode": "standard"},
        }
        cfg_file = tmp_path / "autoagent.yaml"
        cfg_file.write_text(yaml.dump(data), encoding="utf-8")

        rc = load_runtime_config(str(cfg_file))
        assert rc.optimization.mode == "standard"
