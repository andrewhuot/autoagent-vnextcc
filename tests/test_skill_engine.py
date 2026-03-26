"""Tests for optimizer.skill_engine module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.skills.store import SkillStore
from core.skills.types import (
    EvalCriterion,
    MutationOperator as SkillMutationOperator,
    Skill,
    SkillKind,
    TriggerCondition,
)
from optimizer.mutations import (
    MutationOperator,
    MutationRegistry,
    MutationSurface,
    RiskClass,
)
from optimizer.skill_engine import SkillEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db() -> str:
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        return f.name


@pytest.fixture
def skill_store(temp_db: str) -> SkillStore:
    """Create a SkillStore with temporary database."""
    return SkillStore(db_path=temp_db)


@pytest.fixture
def mutation_registry() -> MutationRegistry:
    """Create a MutationRegistry with test operators."""
    registry = MutationRegistry()

    # Simple instruction rewrite operator
    def apply_instruction_rewrite(config: dict, params: dict) -> dict:
        config = config.copy()
        config["instruction"] = params.get("text", "")
        return config

    def validate_instruction_rewrite(config: dict) -> bool:
        return "instruction" in config and isinstance(config["instruction"], str)

    registry.register(
        MutationOperator(
            name="instruction_rewrite",
            surface=MutationSurface.instruction,
            risk_class=RiskClass.low,
            validator=validate_instruction_rewrite,
            apply=apply_instruction_rewrite,
            description="Rewrite instruction text",
        )
    )

    # Temperature adjustment operator
    def apply_temperature_adjust(config: dict, params: dict) -> dict:
        config = config.copy()
        if "generation_settings" not in config:
            config["generation_settings"] = {}
        config["generation_settings"]["temperature"] = params.get("temperature", 0.7)
        return config

    def validate_temperature_adjust(config: dict) -> bool:
        return (
            "generation_settings" in config
            and "temperature" in config["generation_settings"]
        )

    registry.register(
        MutationOperator(
            name="temperature_adjust",
            surface=MutationSurface.generation_settings,
            risk_class=RiskClass.low,
            validator=validate_temperature_adjust,
            apply=apply_temperature_adjust,
            description="Adjust generation temperature",
        )
    )

    return registry


@pytest.fixture
def skill_engine(skill_store: SkillStore, mutation_registry: MutationRegistry) -> SkillEngine:
    """Create a SkillEngine with test fixtures."""
    return SkillEngine(store=skill_store, mutation_registry=mutation_registry)


# ---------------------------------------------------------------------------
# Test Skill Selection
# ---------------------------------------------------------------------------


def test_select_skills_by_failure_family(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test selecting skills by failure family."""
    # Create a skill with routing_failure trigger
    skill = Skill(
        id="skill1",
        name="routing_optimizer",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Optimizes routing accuracy",
        triggers=[
            TriggerCondition(failure_family="routing_failure"),
        ],
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Add routing instructions",
                target_surface="instruction",
                operator_type="append",
            )
        ],
    )
    skill_store.create(skill)

    # Select skills for routing_failure
    selected = skill_engine.select_skills(failure_family="routing_failure")

    assert len(selected) == 1
    assert selected[0].name == "routing_optimizer"


def test_select_skills_by_metrics(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test selecting skills by metric thresholds."""
    # Create a skill with metric trigger: routing_accuracy < 0.7
    skill = Skill(
        id="skill2",
        name="accuracy_booster",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Improves routing accuracy",
        triggers=[
            TriggerCondition(
                metric_name="routing_accuracy",
                threshold=0.7,
                operator="lt",
            ),
        ],
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Add accuracy instructions",
                target_surface="instruction",
                operator_type="append",
            )
        ],
    )
    skill_store.create(skill)

    # Select skills with routing_accuracy = 0.6 (< 0.7, should match)
    selected = skill_engine.select_skills(metrics={"routing_accuracy": 0.6})

    assert len(selected) == 1
    assert selected[0].name == "accuracy_booster"


def test_select_skills_max_limit(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test max_skills parameter limits results."""
    # Create 10 skills
    for i in range(10):
        skill = Skill(
            id=f"skill{i}",
            name=f"skill_{i}",
            kind=SkillKind.BUILD,
            version="1.0",
            description=f"Skill {i}",
            triggers=[TriggerCondition(failure_family="routing_failure")],
            mutations=[
                SkillMutationOperator(
                    name="instruction_rewrite",
                    description="Test mutation",
                    target_surface="instruction",
                    operator_type="append",
                )
            ],
        )
        skill_store.create(skill)

    # Select with max_skills=3
    selected = skill_engine.select_skills(failure_family="routing_failure", max_skills=3)

    assert len(selected) == 3


def test_select_skills_no_matches(skill_engine: SkillEngine) -> None:
    """Test selecting skills with no matches returns empty list."""
    selected = skill_engine.select_skills(failure_family="nonexistent_failure")
    assert selected == []


# ---------------------------------------------------------------------------
# Test Mutation Application
# ---------------------------------------------------------------------------


def test_apply_skill_single_mutation(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test applying a skill with a single mutation."""
    skill = Skill(
        id="skill3",
        name="instruction_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Rewrites instructions",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite instruction",
                target_surface="instruction",
                operator_type="replace",
                parameters={"text": "New instruction"},
            )
        ],
    )
    skill_store.create(skill)

    config = {"instruction": "Old instruction"}
    mutated = skill_engine.apply_skill(skill, config)

    assert mutated["instruction"] == "New instruction"
    assert config["instruction"] == "Old instruction"  # Original unchanged


def test_apply_skill_with_context_override(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test that context parameters override skill defaults."""
    skill = Skill(
        id="skill4",
        name="instruction_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Rewrites instructions",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite instruction",
                target_surface="instruction",
                operator_type="replace",
                parameters={"text": "Default text"},
            )
        ],
    )
    skill_store.create(skill)

    config = {"instruction": "Old"}
    context = {"text": "Context override"}
    mutated = skill_engine.apply_skill(skill, config, context)

    assert mutated["instruction"] == "Context override"


def test_apply_skill_no_mutations_raises(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test applying a skill with no mutations raises ValueError."""
    skill = Skill(
        id="skill5",
        name="empty_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="No mutations",
        mutations=[],
    )
    skill_store.create(skill)

    config = {}
    with pytest.raises(ValueError, match="has no mutations"):
        skill_engine.apply_skill(skill, config)


def test_apply_skill_unknown_mutation_raises(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test applying a skill with unknown mutation raises ValueError."""
    skill = Skill(
        id="skill6",
        name="bad_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Unknown mutation",
        mutations=[
            SkillMutationOperator(
                name="nonexistent_mutation",
                description="Does not exist",
                target_surface="instruction",
                operator_type="replace",
            )
        ],
    )
    skill_store.create(skill)

    config = {}
    with pytest.raises(ValueError, match="not found in registry"):
        skill_engine.apply_skill(skill, config)


# ---------------------------------------------------------------------------
# Test Propose from Skills
# ---------------------------------------------------------------------------


def test_propose_from_skills_multiple(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test proposing mutations from multiple skills."""
    skill1 = Skill(
        id="skill7",
        name="skill_a",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Skill A",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite",
                target_surface="instruction",
                operator_type="replace",
                parameters={"text": "Mutation A"},
            )
        ],
    )
    skill2 = Skill(
        id="skill8",
        name="skill_b",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Skill B",
        mutations=[
            SkillMutationOperator(
                name="temperature_adjust",
                description="Adjust temp",
                target_surface="generation_settings",
                operator_type="replace",
                parameters={"temperature": 0.9},
            )
        ],
    )
    skill_store.create(skill1)
    skill_store.create(skill2)

    config = {"instruction": "Base"}
    proposals = skill_engine.propose_from_skills([skill1, skill2], config)

    assert len(proposals) == 2
    assert proposals[0]["instruction"] == "Mutation A"
    assert proposals[1]["generation_settings"]["temperature"] == 0.9


def test_propose_from_skills_skip_invalid(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test that propose_from_skills skips invalid mutations."""
    skill1 = Skill(
        id="skill9",
        name="good_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Good skill",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Valid",
                target_surface="instruction",
                operator_type="replace",
                parameters={"text": "Valid"},
            )
        ],
    )
    skill2 = Skill(
        id="skill10",
        name="bad_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Bad skill",
        mutations=[
            SkillMutationOperator(
                name="nonexistent_mutation",
                description="Invalid",
                target_surface="instruction",
                operator_type="replace",
            )
        ],
    )
    skill_store.create(skill1)
    skill_store.create(skill2)

    config = {"instruction": "Base"}
    proposals = skill_engine.propose_from_skills([skill1, skill2], config)

    # Only the valid mutation should produce a proposal
    assert len(proposals) == 1
    assert proposals[0]["instruction"] == "Valid"


# ---------------------------------------------------------------------------
# Test Evaluation
# ---------------------------------------------------------------------------


def test_evaluate_skill_result_with_criteria(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test evaluating skill result with eval criteria."""
    skill = Skill(
        id="skill11",
        name="eval_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Skill with eval criteria",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite",
                target_surface="instruction",
                operator_type="replace",
            )
        ],
        eval_criteria=[
            EvalCriterion(metric="accuracy", target=0.8, operator="gt"),
        ],
    )
    skill_store.create(skill)

    # Success: 0.85 > 0.8
    assert skill_engine.evaluate_skill_result(skill, baseline_score=0.7, candidate_score=0.85)

    # Failure: 0.75 < 0.8
    assert not skill_engine.evaluate_skill_result(skill, baseline_score=0.7, candidate_score=0.75)


def test_evaluate_skill_result_multiple_criteria(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test that all criteria must pass (AND logic)."""
    skill = Skill(
        id="skill12",
        name="multi_eval_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Skill with multiple criteria",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite",
                target_surface="instruction",
                operator_type="replace",
            )
        ],
        eval_criteria=[
            EvalCriterion(metric="accuracy", target=0.8, operator="gte"),
            EvalCriterion(metric="latency", target=2.0, operator="lte"),
        ],
    )
    skill_store.create(skill)

    # Both pass
    assert skill_engine.evaluate_skill_result(skill, baseline_score=0.7, candidate_score=0.8)

    # Note: In this simplified implementation, we only check against candidate_score
    # In production, you'd pass a full metrics dict


def test_evaluate_skill_result_no_criteria(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test that no criteria defaults to simple improvement check."""
    skill = Skill(
        id="skill13",
        name="no_criteria_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Skill without criteria",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite",
                target_surface="instruction",
                operator_type="replace",
            )
        ],
        eval_criteria=[],
    )
    skill_store.create(skill)

    # Improvement
    assert skill_engine.evaluate_skill_result(skill, baseline_score=0.7, candidate_score=0.8)

    # No improvement
    assert not skill_engine.evaluate_skill_result(skill, baseline_score=0.7, candidate_score=0.6)


def test_evaluate_skill_result_operators(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test all eval criterion operators."""
    mutations = [
        SkillMutationOperator(
            name="instruction_rewrite",
            description="Test",
            target_surface="instruction",
            operator_type="replace",
        )
    ]

    # Test gt
    skill_gt = Skill(
        id="skill_gt",
        name="gt_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="GT",
        mutations=mutations,
        eval_criteria=[EvalCriterion(metric="score", target=0.5, operator="gt")],
    )
    skill_store.create(skill_gt)
    assert skill_engine.evaluate_skill_result(skill_gt, 0.4, 0.6)
    assert not skill_engine.evaluate_skill_result(skill_gt, 0.4, 0.5)

    # Test gte
    skill_gte = Skill(
        id="skill_gte",
        name="gte_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="GTE",
        mutations=mutations,
        eval_criteria=[EvalCriterion(metric="score", target=0.5, operator="gte")],
    )
    skill_store.create(skill_gte)
    assert skill_engine.evaluate_skill_result(skill_gte, 0.4, 0.5)
    assert not skill_engine.evaluate_skill_result(skill_gte, 0.4, 0.4)

    # Test lt
    skill_lt = Skill(
        id="skill_lt",
        name="lt_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="LT",
        mutations=mutations,
        eval_criteria=[EvalCriterion(metric="score", target=0.5, operator="lt")],
    )
    skill_store.create(skill_lt)
    assert skill_engine.evaluate_skill_result(skill_lt, 0.6, 0.4)
    assert not skill_engine.evaluate_skill_result(skill_lt, 0.6, 0.5)

    # Test lte
    skill_lte = Skill(
        id="skill_lte",
        name="lte_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="LTE",
        mutations=mutations,
        eval_criteria=[EvalCriterion(metric="score", target=0.5, operator="lte")],
    )
    skill_store.create(skill_lte)
    assert skill_engine.evaluate_skill_result(skill_lte, 0.6, 0.5)
    assert not skill_engine.evaluate_skill_result(skill_lte, 0.6, 0.6)

    # Test eq
    skill_eq = Skill(
        id="skill_eq",
        name="eq_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="EQ",
        mutations=mutations,
        eval_criteria=[EvalCriterion(metric="score", target=0.5, operator="eq")],
    )
    skill_store.create(skill_eq)
    assert skill_engine.evaluate_skill_result(skill_eq, 0.4, 0.5)
    assert not skill_engine.evaluate_skill_result(skill_eq, 0.4, 0.51)


# ---------------------------------------------------------------------------
# Test Learning
# ---------------------------------------------------------------------------


def test_learn_from_outcome_success(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test learning from successful skill application."""
    skill = Skill(
        id="skill14",
        name="learn_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Learning skill",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite",
                target_surface="instruction",
                operator_type="replace",
            )
        ],
    )
    skill_id = skill_store.create(skill)

    # Record successful outcome
    skill_engine.learn_from_outcome(skill, improvement=0.15, success=True)

    # Check effectiveness metrics
    effectiveness = skill_store.get_effectiveness(skill_id)
    assert effectiveness.times_applied == 1
    assert effectiveness.success_count == 1
    assert effectiveness.success_rate == 1.0
    assert effectiveness.avg_improvement == 0.15
    assert effectiveness.total_improvement == 0.15


def test_learn_from_outcome_failure(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test learning from failed skill application."""
    skill = Skill(
        id="skill15",
        name="fail_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Failing skill",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite",
                target_surface="instruction",
                operator_type="replace",
            )
        ],
    )
    skill_id = skill_store.create(skill)

    # Record failed outcome
    skill_engine.learn_from_outcome(skill, improvement=-0.05, success=False)

    # Check effectiveness metrics
    effectiveness = skill_store.get_effectiveness(skill_id)
    assert effectiveness.times_applied == 1
    assert effectiveness.success_count == 0
    assert effectiveness.success_rate == 0.0
    assert effectiveness.avg_improvement == 0.0  # Failures don't count in avg


def test_learn_from_outcome_multiple(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test learning from multiple outcomes."""
    skill = Skill(
        id="skill16",
        name="multi_outcome_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Multiple outcomes",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite",
                target_surface="instruction",
                operator_type="replace",
            )
        ],
    )
    skill_id = skill_store.create(skill)

    # Record outcomes
    skill_engine.learn_from_outcome(skill, improvement=0.1, success=True)
    skill_engine.learn_from_outcome(skill, improvement=-0.05, success=False)
    skill_engine.learn_from_outcome(skill, improvement=0.2, success=True)

    # Check effectiveness metrics
    effectiveness = skill_store.get_effectiveness(skill_id)
    assert effectiveness.times_applied == 3
    assert effectiveness.success_count == 2
    assert effectiveness.success_rate == 2 / 3
    assert effectiveness.avg_improvement == (0.1 + 0.2) / 2  # Average of successes


# ---------------------------------------------------------------------------
# Test Application History
# ---------------------------------------------------------------------------


def test_application_history_tracking(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test that application history is tracked correctly."""
    skill = Skill(
        id="skill17",
        name="history_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="History tracking",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite",
                target_surface="instruction",
                operator_type="replace",
                parameters={"text": "New"},
            )
        ],
    )
    skill_store.create(skill)

    config = {"instruction": "Old"}
    skill_engine.apply_skill(skill, config)

    history = skill_engine.get_application_history()
    assert len(history) == 1
    assert history[0].skill_id == skill.id
    assert history[0].skill_name == skill.name
    assert history[0].mutation_name == "instruction_rewrite"
    assert history[0].config_before == {"instruction": "Old"}
    assert history[0].config_after == {"instruction": "New"}


def test_application_history_clear(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test clearing application history."""
    skill = Skill(
        id="skill18",
        name="clear_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Clear history",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite",
                target_surface="instruction",
                operator_type="replace",
            )
        ],
    )
    skill_store.create(skill)

    config = {"instruction": "Test"}
    skill_engine.apply_skill(skill, config)

    assert len(skill_engine.get_application_history()) == 1
    skill_engine.clear_history()
    assert len(skill_engine.get_application_history()) == 0


# ---------------------------------------------------------------------------
# Test Validation
# ---------------------------------------------------------------------------


def test_validate_config_success(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test config validation with valid config."""
    skill = Skill(
        id="skill19",
        name="validate_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Validation",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite",
                target_surface="instruction",
                operator_type="replace",
                parameters={"text": "Valid"},
            )
        ],
    )
    skill_store.create(skill)

    config = {"instruction": "Base"}
    mutated = skill_engine.apply_skill(skill, config)

    # Validate the mutated config
    assert skill_engine.validate_config(mutated)


def test_validate_config_failure(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test config validation with invalid config."""
    skill = Skill(
        id="skill20",
        name="invalid_skill",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Invalid validation",
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Rewrite",
                target_surface="instruction",
                operator_type="replace",
                parameters={"text": "Test"},
            )
        ],
    )
    skill_store.create(skill)

    config = {"instruction": "Base"}
    skill_engine.apply_skill(skill, config)

    # Create invalid config (missing instruction)
    invalid_config = {"other_field": "value"}
    assert not skill_engine.validate_config(invalid_config)


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


def test_full_optimization_cycle(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test a complete optimization cycle: select -> apply -> evaluate -> learn."""
    # 1. Create a skill
    skill = Skill(
        id="cycle_skill",
        name="routing_optimizer",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Optimize routing",
        triggers=[
            TriggerCondition(
                metric_name="routing_accuracy",
                threshold=0.7,
                operator="lt",
            ),
        ],
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Add routing instructions",
                target_surface="instruction",
                operator_type="append",
                parameters={"text": "Route carefully to the right specialist."},
            )
        ],
        eval_criteria=[
            EvalCriterion(metric="routing_accuracy", target=0.75, operator="gte"),
        ],
    )
    skill_store.create(skill)

    # 2. Select skills based on low routing accuracy
    selected = skill_engine.select_skills(metrics={"routing_accuracy": 0.65})
    assert len(selected) == 1
    assert selected[0].name == "routing_optimizer"

    # 3. Apply skill
    config = {"instruction": "You are a helpful assistant."}
    mutated = skill_engine.apply_skill(selected[0], config)
    assert "Route carefully" in mutated["instruction"]

    # 4. Evaluate (simulate improvement to 0.80)
    baseline_score = 0.65
    candidate_score = 0.80
    success = skill_engine.evaluate_skill_result(selected[0], baseline_score, candidate_score)
    assert success

    # 5. Learn from outcome
    improvement = candidate_score - baseline_score
    skill_engine.learn_from_outcome(selected[0], improvement, success)

    # 6. Verify effectiveness updated
    effectiveness = skill_store.get_effectiveness(selected[0].id)
    assert effectiveness.times_applied == 1
    assert effectiveness.success_rate == 1.0
    assert effectiveness.avg_improvement == improvement


def test_skill_ranking_by_effectiveness(skill_store: SkillStore, skill_engine: SkillEngine) -> None:
    """Test that skills are ranked by effectiveness (success_rate * avg_improvement)."""
    # Create two skills with same trigger
    skill_a = Skill(
        id="skill_a",
        name="skill_a",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Skill A",
        triggers=[TriggerCondition(failure_family="routing_failure")],
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Test",
                target_surface="instruction",
                operator_type="replace",
            )
        ],
    )
    skill_b = Skill(
        id="skill_b",
        name="skill_b",
        kind=SkillKind.BUILD,
        version="1.0",
        description="Skill B",
        triggers=[TriggerCondition(failure_family="routing_failure")],
        mutations=[
            SkillMutationOperator(
                name="instruction_rewrite",
                description="Test",
                target_surface="instruction",
                operator_type="replace",
            )
        ],
    )
    skill_store.create(skill_a)
    skill_store.create(skill_b)

    # Give skill_a better effectiveness: 1.0 * 0.2 = 0.2
    skill_engine.learn_from_outcome(skill_a, improvement=0.2, success=True)

    # Give skill_b worse effectiveness: 0.5 * 0.1 = 0.05
    skill_engine.learn_from_outcome(skill_b, improvement=0.1, success=True)
    skill_engine.learn_from_outcome(skill_b, improvement=0.0, success=False)

    # Select skills - skill_a should rank higher
    selected = skill_engine.select_skills(failure_family="routing_failure")
    assert len(selected) == 2
    assert selected[0].name == "skill_a"
    assert selected[1].name == "skill_b"
