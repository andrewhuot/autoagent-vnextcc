"""Regression tests for Worker C's optimize/eval evidence backlog slice."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner

import runner as runner_module
from cli.commands.optimize import run_optimize_in_process


def _write_eval_payload(path: Path, payload: dict[str, Any], *, mtime: int) -> None:
    """Persist one eval payload with a deterministic modification time."""
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_health_report_from_eval_triggers_optimization_for_low_composite_all_pass() -> None:
    """All-pass evals should still optimize when the composite is meaningfully weak."""
    report = runner_module._health_report_from_eval(
        {
            "scores": {
                "quality": 0.90,
                "safety": 1.0,
                "latency": 0.96,
                "cost": 0.95,
                "composite": 0.8818,
            },
            "passed": 3,
            "total": 3,
            "results": [
                {"case_id": "case-1", "passed": True},
                {"case_id": "case-2", "passed": True},
                {"case_id": "case-3", "passed": True},
            ],
        }
    )

    assert report.needs_optimization is True
    assert "composite" in report.reason.lower()
    assert "0.8818" in report.reason


def test_health_report_from_eval_skips_high_composite_all_pass() -> None:
    """Healthy all-pass evals should still skip optimization."""
    report = runner_module._health_report_from_eval(
        {
            "scores": {
                "quality": 0.98,
                "safety": 1.0,
                "latency": 0.97,
                "cost": 0.96,
                "composite": 0.9625,
            },
            "passed": 3,
            "total": 3,
            "results": [
                {"case_id": "case-1", "passed": True},
                {"case_id": "case-2", "passed": True},
                {"case_id": "case-3", "passed": True},
            ],
        }
    )

    assert report.needs_optimization is False
    assert report.reason == "All latest eval cases passed."


def test_latest_eval_payload_for_active_config_prefers_latest_matching_bound_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The active-config lookup should ignore newer payloads for other configs."""
    monkeypatch.chdir(tmp_path)
    config_a = tmp_path / "configs" / "a.yaml"
    config_b = tmp_path / "configs" / "b.yaml"
    config_a.parent.mkdir(parents=True)
    config_a.write_text("a: 1\n", encoding="utf-8")
    config_b.write_text("b: 1\n", encoding="utf-8")

    older_matching = tmp_path / "eval_results_a.json"
    newer_other = tmp_path / "eval_results_b.json"
    _write_eval_payload(
        older_matching,
        {"run_id": "run-a", "config_path": str(config_a.resolve()), "scores": {"composite": 0.82}},
        mtime=100,
    )
    _write_eval_payload(
        newer_other,
        {"run_id": "run-b", "config_path": str(config_b.resolve()), "scores": {"composite": 0.91}},
        mtime=200,
    )

    path, payload = runner_module._latest_eval_payload_for_active_config(config_a)

    assert path == older_matching
    assert payload is not None
    assert runner_module._eval_payload_run_id(payload) == "run-a"


def test_latest_eval_payload_for_active_config_ignores_unbound_latest_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing config_path must not be treated as valid evidence for the active config."""
    monkeypatch.chdir(tmp_path)
    config_a = tmp_path / "configs" / "a.yaml"
    config_a.parent.mkdir(parents=True)
    config_a.write_text("a: 1\n", encoding="utf-8")

    older_matching = tmp_path / "eval_results_bound.json"
    newer_unbound = tmp_path / "eval_results_unbound.json"
    _write_eval_payload(
        older_matching,
        {"run_id": "run-bound", "config_path": str(config_a.resolve()), "scores": {"composite": 0.83}},
        mtime=100,
    )
    _write_eval_payload(
        newer_unbound,
        {"run_id": "run-unbound", "scores": {"composite": 0.99}},
        mtime=200,
    )

    path, payload = runner_module._latest_eval_payload_for_active_config(config_a)

    assert path == older_matching
    assert payload is not None
    assert runner_module._eval_payload_run_id(payload) == "run-bound"


@pytest.mark.parametrize(
    ("payload_config", "expected_found"),
    [
        (None, False),
        ("other", False),
        ("match", True),
    ],
)
def test_eval_payload_for_run_id_requires_matching_bound_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload_config: str | None,
    expected_found: bool,
) -> None:
    """Explicit run-id lookup must still respect config binding when scoped."""
    monkeypatch.chdir(tmp_path)
    active_config = tmp_path / "configs" / "active.yaml"
    other_config = tmp_path / "configs" / "other.yaml"
    active_config.parent.mkdir(parents=True)
    active_config.write_text("active: true\n", encoding="utf-8")
    other_config.write_text("other: true\n", encoding="utf-8")

    payload: dict[str, Any] = {"run_id": "run-target", "scores": {"composite": 0.8}}
    if payload_config == "match":
        payload["config_path"] = str(active_config.resolve())
    elif payload_config == "other":
        payload["config_path"] = str(other_config.resolve())

    _write_eval_payload(tmp_path / "eval_results_target.json", payload, mtime=100)

    path, data = runner_module._eval_payload_for_run_id(
        "run-target",
        config_path=active_config,
    )

    if expected_found:
        assert path is not None
        assert data is not None
        assert runner_module._eval_payload_run_id(data) == "run-target"
    else:
        assert path is None
        assert data is None


def test_run_optimize_in_process_reports_attempt_from_current_cycle_not_latest_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Result plumbing should surface the attempt created by this optimize run."""
    monkeypatch.chdir(tmp_path)

    class FakeConversationStore:
        def __init__(self, db_path: str) -> None:
            self.db_path = db_path

    class FakeObserver:
        def __init__(self, store: FakeConversationStore) -> None:
            self.store = store

        def observe(self) -> object:
            return SimpleNamespace()

    class FakeMemory:
        def __init__(self, db_path: str) -> None:
            self.db_path = db_path

        def recent(self, limit: int = 1) -> list[object]:
            del limit
            return [
                SimpleNamespace(
                    attempt_id="alien-attempt",
                    change_description="Alien row",
                    score_before=0.10,
                    score_after=0.11,
                    significance_p_value=1.0,
                )
            ]

    class FakeOptimizer:
        def __init__(self, eval_runner, memory: FakeMemory, **_: object) -> None:
            del eval_runner, memory
            self.last_attempt = None

        def optimize(
            self,
            report: object,
            current_config: dict[str, object],
            failure_samples: list[dict[str, object]] | None = None,
        ) -> tuple[dict[str, object] | None, str]:
            del report, current_config, failure_samples
            self.last_attempt = SimpleNamespace(
                attempt_id="current-attempt",
                change_description="Current cycle attempt",
                score_before=0.70,
                score_after=0.73,
                significance_p_value=0.04,
            )
            return None, "REJECTED (rejected_no_improvement): no gain"

    class FakeDeployer:
        def __init__(self, configs_dir: str, store: FakeConversationStore) -> None:
            self.configs_dir = configs_dir
            self.store = store

    class FakeEvalRunner:
        pass

    runtime = SimpleNamespace(
        eval=SimpleNamespace(
            significance_alpha=0.05,
            significance_min_effect_size=0.0,
            significance_iterations=32,
            significance_min_pairs=0,
        ),
        optimizer=SimpleNamespace(skill_autolearn_enabled=False),
    )
    baseline_eval_payload = {
        "config_path": str((tmp_path / "configs" / "active.yaml").resolve()),
        "scores": {"quality": 0.7, "safety": 1.0, "latency": 0.9, "cost": 0.9, "composite": 0.7},
        "passed": 0,
        "total": 1,
        "results": [
            {
                "case_id": "case-1",
                "category": "routing",
                "passed": False,
                "quality_score": 0.3,
                "safety_passed": True,
                "details": "routing: failed",
            }
        ],
    }

    monkeypatch.setattr(runner_module, "ConversationStore", FakeConversationStore)
    monkeypatch.setattr(runner_module, "Observer", FakeObserver)
    monkeypatch.setattr(runner_module, "OptimizationMemory", FakeMemory)
    monkeypatch.setattr(runner_module, "Optimizer", FakeOptimizer)
    monkeypatch.setattr(runner_module, "Deployer", FakeDeployer)
    monkeypatch.setattr(
        runner_module,
        "_build_runtime_components",
        lambda: (
            runtime,
            FakeEvalRunner(),
            SimpleNamespace(use_mock=False, llm_router=None),
            None,
            None,
            None,
        ),
    )
    monkeypatch.setattr(runner_module, "_runtime_budget_config", lambda _runtime: (str(tmp_path / "budget.db"), 1.0, 10.0, 5))
    monkeypatch.setattr(runner_module, "_warn_mock_modes", lambda **_: None)
    monkeypatch.setattr(runner_module, "_proposer_total_cost", lambda _proposer: 0.0)
    monkeypatch.setattr(runner_module, "_generate_recommendations", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner_module, "_print_cli_plan", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_module, "_print_next_actions", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner_module,
        "resolve_config_snapshot",
        lambda **_: SimpleNamespace(snapshot=None),
    )
    monkeypatch.setattr(runner_module, "persist_config_lockfile", lambda _resolution: None)
    monkeypatch.setattr(
        runner_module,
        "_latest_eval_payload_for_active_config",
        lambda *_args, **_kwargs: (tmp_path / "eval_results.json", baseline_eval_payload),
    )
    monkeypatch.setattr(
        runner_module,
        "_health_report_from_eval",
        lambda _data: SimpleNamespace(
            needs_optimization=True,
            failure_buckets={"routing_error": 1},
            metrics=SimpleNamespace(to_dict=lambda: {"success_rate": 0.0}),
            reason="failure present",
        ),
    )
    monkeypatch.setattr(runner_module, "_load_optimize_current_config", lambda **_: {"model": "baseline"})

    result = run_optimize_in_process(
        cycles=1,
        on_event=lambda _event: None,
    )

    assert result.attempt_id == "current-attempt"
