"""Tests for OffPolicyEvaluator in policy_opt/ope.py."""

from __future__ import annotations

import pytest

from data.episode_types import Episode, EpisodeStep
from policy_opt.ope import OffPolicyEvaluator
from policy_opt.types import OPEReport, PolicyArtifact, PolicyType, TrainingMode


def _make_episode(
    total_reward: dict | None = None,
    hard_gates: bool = True,
    action_type: str = "tool_call",
    n_steps: int = 1,
    eval_run_id: str = "ev1",
) -> Episode:
    steps = [
        EpisodeStep(
            step_index=i,
            action_type=action_type,
            action={"text": f"act_{i}"},
        )
        for i in range(n_steps)
    ]
    return Episode(
        eval_run_id=eval_run_id,
        agent_version="v1",
        steps=steps,
        total_reward=total_reward or {"r1": 0.7},
        hard_gates_passed=hard_gates,
    )


def _make_policy(training_dataset_version: str = "ds-v1") -> PolicyArtifact:
    return PolicyArtifact(
        name="test_policy",
        policy_type=PolicyType.mutation_policy,
        training_mode=TrainingMode.control,
        training_dataset_version=training_dataset_version,
    )


# ---------------------------------------------------------------------------
# evaluate — empty episodes
# ---------------------------------------------------------------------------

def test_evaluate_empty_episodes_returns_report():
    evaluator = OffPolicyEvaluator(n_bootstrap=10)
    policy = _make_policy()
    report = evaluator.evaluate(policy, [])

    assert isinstance(report, OPEReport)
    assert report.policy_id == policy.policy_id
    assert report.baseline_replay_score == pytest.approx(0.0)
    assert report.candidate_estimated_uplift == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# evaluate — happy path with episodes
# ---------------------------------------------------------------------------

def test_evaluate_returns_ope_report():
    evaluator = OffPolicyEvaluator(n_bootstrap=20)
    policy = _make_policy()
    episodes = [_make_episode(total_reward={"r1": 0.8}) for _ in range(5)]
    report = evaluator.evaluate(policy, episodes)

    assert isinstance(report, OPEReport)
    assert report.policy_id == policy.policy_id


def test_evaluate_baseline_score_positive_for_good_episodes():
    evaluator = OffPolicyEvaluator(n_bootstrap=20)
    policy = _make_policy()
    episodes = [_make_episode(total_reward={"r1": 1.0}, hard_gates=True) for _ in range(4)]
    report = evaluator.evaluate(policy, episodes)

    assert report.baseline_replay_score > 0.0


def test_evaluate_gate_failed_episodes_get_zero_baseline():
    evaluator = OffPolicyEvaluator(n_bootstrap=10)
    policy = _make_policy()
    # All episodes fail hard gates
    episodes = [_make_episode(total_reward={"r1": 0.9}, hard_gates=False) for _ in range(3)]
    report = evaluator.evaluate(policy, episodes)

    assert report.baseline_replay_score == pytest.approx(0.0)


def test_evaluate_diagnostics_populated():
    evaluator = OffPolicyEvaluator(n_bootstrap=20)
    policy = _make_policy()
    episodes = [_make_episode() for _ in range(5)]
    report = evaluator.evaluate(policy, episodes)

    assert "n_episodes" in report.diagnostics
    assert report.diagnostics["n_episodes"] == 5
    assert "baseline_mean" in report.diagnostics


def test_evaluate_support_coverage_between_zero_and_one():
    evaluator = OffPolicyEvaluator(n_bootstrap=10)
    policy = _make_policy()
    episodes = [_make_episode(action_type="tool_call") for _ in range(3)]
    report = evaluator.evaluate(policy, episodes)

    assert 0.0 <= report.support_coverage <= 1.0


def test_evaluate_uncertainty_interval_ordered():
    evaluator = OffPolicyEvaluator(n_bootstrap=50)
    policy = _make_policy()
    episodes = [_make_episode(total_reward={"r1": float(i) / 5}) for i in range(5)]
    report = evaluator.evaluate(policy, episodes)

    assert report.uncertainty_lower <= report.uncertainty_upper
