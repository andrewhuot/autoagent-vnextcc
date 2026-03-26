"""Integration tests for skill-driven optimization in the optimizer loop."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from core.skills.store import SkillStore
from core.skills.types import (
    EvalCriterion,
    MutationOperator,
    Skill,
    SkillKind,
    TriggerCondition,
)
from evals.scorer import CompositeScore, EvalResult
from observer.metrics import HealthMetrics, HealthReport
from optimizer.loop import Optimizer
from optimizer.memory import OptimizationMemory
from optimizer.mutations import create_default_registry
from optimizer.skill_engine import SkillEngine


class DeterministicEvalRunner:
    """Return baseline_score first, then always candidate_score.

    Simpler approach: first call returns baseline, all subsequent calls return candidate.
    This works for the common pattern of: baseline eval, then candidate eval(s).
    """

    def __init__(self, baseline_config: dict, baseline_score: float, candidate_score: float):
        self.baseline_score = baseline_score
        self.candidate_score = candidate_score
        self.call_count = 0
        self.scores_returned = []

    def run(self, config: dict | None = None) -> CompositeScore:
        self.call_count += 1

        # First call gets baseline, all others get candidate
        score = self.baseline_score if self.call_count == 1 else self.candidate_score
        self.scores_returned.append(score)

        # Build realistic case results for significance testing
        case_quality = score
        results = [
            EvalResult(
                case_id=f"case_{i:02d}",
                category="regression",
                passed=True,
                quality_score=case_quality,
                safety_passed=True,
                latency_ms=100.0,
                token_count=150,
            )
            for i in range(10)
        ]

        return CompositeScore(
            quality=score,
            safety=1.0,
            latency=0.9,
            cost=0.85,
            composite=score,
            safety_failures=0,
            total_cases=10,
            passed_cases=10,
            results=results,
        )


@pytest.fixture
def base_config() -> dict:
    """Base agent configuration for testing."""
    return {
        "routing": {"rules": []},
        "prompts": {
            "root": "You are a helpful assistant.",
            "support": "You are a support specialist.",
        },
        "tools": {"catalog": {"enabled": True}},
        "thresholds": {"confidence_threshold": 0.6},
        "model": "gemini-2.0-flash",
    }


@pytest.fixture
def health_report() -> HealthReport:
    """Standard health report for testing."""
    return HealthReport(
        metrics=HealthMetrics(
            success_rate=0.65,
            avg_latency_ms=450.0,
            error_rate=0.20,
            safety_violation_rate=0.01,
            avg_cost=0.18,
            total_conversations=100,
        ),
        failure_buckets={"routing_error": 15, "tool_failure": 5},
        needs_optimization=True,
        reason="routing accuracy below threshold",
    )


@pytest.fixture
def skill_store(tmp_path: Path) -> SkillStore:
    """Create a skill store with a test build-time skill."""
    store = SkillStore(str(tmp_path / "skills.db"))

    # Create a routing improvement skill
    skill = Skill(
        id="skill-routing-001",
        name="routing_keyword_expansion",
        kind=SkillKind.BUILD,
        version="1.0.0",
        domain="routing",
        description="Expand routing keywords to improve accuracy",
        triggers=[
            TriggerCondition(
                failure_family="routing_error",
                metric_name=None,
                threshold=None,
            ),
        ],
        mutations=[
            MutationOperator(
                name="instruction_rewrite",
                description="Add routing clarification to root prompt",
                target_surface="instruction",
                operator_type="append",
                template=" Consider user intent carefully when routing.",
                parameters={"target": "root", "text": "You are a helpful assistant. Consider user intent carefully when routing."},
                risk_level="low",
            ),
        ],
        eval_criteria=[
            EvalCriterion(
                metric="composite",
                operator="gt",
                target=0.7,
            ),
        ],
        status="active",
        tags=["routing", "keywords", "accuracy"],
    )

    store.create(skill)
    return store


def test_skill_engine_integration_disabled_by_default(
    tmp_path: Path,
    base_config: dict,
    health_report: HealthReport,
    skill_store: SkillStore,
) -> None:
    """Skill engine should NOT be used when use_skills=False (default)."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = DeterministicEvalRunner(base_config, baseline_score=0.75, candidate_score=0.80)

    skill_engine = SkillEngine(skill_store, create_default_registry())

    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        skill_engine=skill_engine,
        use_skills=False,  # Explicitly disabled
        require_statistical_significance=False,
    )

    # Should fall back to standard proposer (which will use mock mode and propose a routing change)
    config, status = optimizer.optimize(health_report, base_config)

    # Should get a proposal from the mock proposer, not from skills
    assert config is not None
    assert "ACCEPTED" in status

    # Skills should NOT be recorded in the attempt
    attempts = memory.recent(limit=1)
    assert len(attempts) == 1
    skills_applied = json.loads(attempts[0].skills_applied)
    assert len(skills_applied) == 0  # No skills used

    # Config section should be from mock proposer, not "skill_optimization"
    assert attempts[0].config_section == "routing"  # Mock proposer's default for routing_error


def test_skill_engine_selects_relevant_skill(
    tmp_path: Path,
    base_config: dict,
    health_report: HealthReport,
    skill_store: SkillStore,
) -> None:
    """Skill engine should select skills matching failure family."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = DeterministicEvalRunner(base_config, baseline_score=0.65, candidate_score=0.75)

    skill_engine = SkillEngine(skill_store, create_default_registry())

    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        skill_engine=skill_engine,
        use_skills=True,
        skill_selection_strategy="auto",
        skill_max_candidates=5,
        require_statistical_significance=False,
    )

    config, status = optimizer.optimize(health_report, base_config)

    # Should succeed with skill-driven optimization
    assert config is not None
    assert "ACCEPTED" in status

    # Verify skills were used
    attempts = memory.recent(limit=1)
    assert len(attempts) == 1
    skills_applied = json.loads(attempts[0].skills_applied)
    assert len(skills_applied) > 0, "Expected skills to be applied"
    assert "skill-routing-001" in skills_applied
    assert attempts[0].config_section == "skill_optimization"

    # Verify skill was recorded in attempt
    attempts = memory.recent(limit=1)
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt.status == "accepted"
    assert attempt.config_section == "skill_optimization"

    # Check skills_applied field
    skills_applied = json.loads(attempt.skills_applied)
    assert len(skills_applied) > 0
    assert skills_applied[0] == "skill-routing-001"


def test_skill_engine_learns_from_outcome(
    tmp_path: Path,
    base_config: dict,
    health_report: HealthReport,
    skill_store: SkillStore,
) -> None:
    """Skill engine should update effectiveness metrics after application."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = DeterministicEvalRunner(base_config, baseline_score=0.65, candidate_score=0.75)

    skill_engine = SkillEngine(skill_store, create_default_registry())

    # Get initial skill state
    skill_before = skill_store.get("skill-routing-001")
    assert skill_before is not None
    assert skill_before.effectiveness.times_applied == 0
    assert skill_before.effectiveness.success_rate == 0.0

    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        skill_engine=skill_engine,
        use_skills=True,
        require_statistical_significance=False,
    )

    config, status = optimizer.optimize(health_report, base_config)
    assert config is not None
    assert "ACCEPTED" in status

    # Check updated skill metrics
    skill_after = skill_store.get("skill-routing-001")
    assert skill_after is not None
    assert skill_after.effectiveness.times_applied == 1
    assert skill_after.effectiveness.success_rate == 1.0  # 1/1 = 100%
    assert skill_after.effectiveness.avg_improvement > 0.0


def test_skill_engine_no_matching_skills(
    tmp_path: Path,
    base_config: dict,
    skill_store: SkillStore,
) -> None:
    """Should fall back to standard proposer when no skills match."""
    # Create health report with different failure family
    health_report = HealthReport(
        metrics=HealthMetrics(
            success_rate=0.65,
            avg_latency_ms=450.0,
            error_rate=0.20,
            safety_violation_rate=0.01,
            avg_cost=0.18,
            total_conversations=100,
        ),
        failure_buckets={"hallucination": 10},  # Different failure family
        needs_optimization=True,
        reason="hallucination rate high",
    )

    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = DeterministicEvalRunner(base_config, baseline_score=0.65, candidate_score=0.75)

    skill_engine = SkillEngine(skill_store, create_default_registry())

    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        skill_engine=skill_engine,
        use_skills=True,
        require_statistical_significance=False,
    )

    config, status = optimizer.optimize(health_report, base_config)

    # Should fall back to mock proposer which will propose a prompt change
    assert config is not None
    assert "ACCEPTED" in status

    # Should NOT have skills applied
    attempts = memory.recent(limit=1)
    skills_applied = json.loads(attempts[0].skills_applied)
    assert len(skills_applied) == 0


def test_skill_engine_rejects_insufficient_improvement(
    tmp_path: Path,
    base_config: dict,
    health_report: HealthReport,
    skill_store: SkillStore,
) -> None:
    """Should reject skill proposals with insufficient improvement and fall back to proposer."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    # Minimal improvement (0.001) below default threshold (0.005)
    eval_runner = DeterministicEvalRunner(base_config, baseline_score=0.65, candidate_score=0.651)

    skill_engine = SkillEngine(skill_store, create_default_registry())

    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        skill_engine=skill_engine,
        use_skills=True,
        require_statistical_significance=False,
        significance_min_effect_size=0.005,
    )

    config, status = optimizer.optimize(health_report, base_config)

    # Should reject skill but fall back to mock proposer
    assert config is not None
    assert "ACCEPTED" in status

    # Should NOT have skills recorded (fell back to proposer)
    attempts = memory.recent(limit=1)
    skills_applied = json.loads(attempts[0].skills_applied)
    assert len(skills_applied) == 0


def test_skill_engine_strategy_diagnostics_includes_skills(
    tmp_path: Path,
    base_config: dict,
    health_report: HealthReport,
    skill_store: SkillStore,
) -> None:
    """Strategy diagnostics should include applied skill IDs."""
    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = DeterministicEvalRunner(base_config, baseline_score=0.65, candidate_score=0.75)

    skill_engine = SkillEngine(skill_store, create_default_registry())

    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        skill_engine=skill_engine,
        use_skills=True,
        require_statistical_significance=False,
    )

    config, status = optimizer.optimize(health_report, base_config)
    assert config is not None

    # Check strategy diagnostics
    diagnostics = optimizer.get_strategy_diagnostics()
    assert diagnostics.skills_applied is not None
    assert len(diagnostics.skills_applied) > 0
    assert "skill-routing-001" in diagnostics.skills_applied


def test_skill_config_from_agent_config(
    tmp_path: Path,
    base_config: dict,
    health_report: HealthReport,
    skill_store: SkillStore,
) -> None:
    """Optimizer should respect skill config from agent config."""
    # Add optimizer config with skill settings
    config_with_skills = deepcopy(base_config)
    config_with_skills["optimizer"] = {
        "use_skills": True,
        "skill_selection_strategy": "auto",
        "skill_max_candidates": 3,
    }

    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = DeterministicEvalRunner(base_config, baseline_score=0.65, candidate_score=0.75)

    skill_engine = SkillEngine(skill_store, create_default_registry())

    # Pass skill config from agent config
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        skill_engine=skill_engine,
        use_skills=config_with_skills["optimizer"]["use_skills"],
        skill_selection_strategy=config_with_skills["optimizer"]["skill_selection_strategy"],
        skill_max_candidates=config_with_skills["optimizer"]["skill_max_candidates"],
        require_statistical_significance=False,
    )

    config, status = optimizer.optimize(health_report, base_config)

    # Should use skills
    assert config is not None
    assert "ACCEPTED" in status

    # Verify skills were used
    attempts = memory.recent(limit=1)
    skills_applied = json.loads(attempts[0].skills_applied)
    assert len(skills_applied) > 0
    assert attempts[0].config_section == "skill_optimization"


def test_multiple_skills_generate_multiple_proposals(
    tmp_path: Path,
    base_config: dict,
    health_report: HealthReport,
    skill_store: SkillStore,
) -> None:
    """Multiple matching skills should generate multiple proposals."""
    # Add a second skill with different mutation
    skill2 = Skill(
        id="skill-routing-002",
        name="routing_confidence_boost",
        kind=SkillKind.BUILD,
        version="1.0.0",
        domain="routing",
        description="Boost routing confidence threshold",
        triggers=[
            TriggerCondition(
                failure_family="routing_error",
            ),
        ],
        mutations=[
            MutationOperator(
                name="update_threshold",
                description="Increase confidence threshold",
                target_surface="threshold",
                operator_type="replace",
                parameters={"path": "thresholds.confidence_threshold", "value": 0.7},
                risk_level="low",
            ),
        ],
        status="active",
        tags=["routing", "threshold"],
    )
    skill_store.create(skill2)

    memory = OptimizationMemory(db_path=str(tmp_path / "optimizer.db"))
    eval_runner = DeterministicEvalRunner(base_config, baseline_score=0.65, candidate_score=0.75)

    skill_engine = SkillEngine(skill_store, create_default_registry())

    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        skill_engine=skill_engine,
        use_skills=True,
        skill_max_candidates=5,
        require_statistical_significance=False,
    )

    config, status = optimizer.optimize(health_report, base_config)

    # Should evaluate both skills and pick the best
    assert config is not None
    assert "ACCEPTED" in status

    # Check that eval_runner was called multiple times (baseline + N proposals)
    # At least: 1 baseline + 2 proposals = 3 calls
    assert eval_runner.call_count >= 3
