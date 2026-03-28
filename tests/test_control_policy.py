"""Tests for ControlPolicyLearner in policy_opt/control_policy.py."""

from __future__ import annotations

import pytest

from data.episode_types import Episode, EpisodeStep
from policy_opt.control_policy import ControlPolicyLearner
from policy_opt.types import PolicyArtifact, PolicyType, TrainingMode


def _make_step(
    index: int = 0,
    action_type: str = "mutation_selection",
    selected: str = "op_add_types",
    reward: float = 0.8,
) -> EpisodeStep:
    return EpisodeStep(
        step_index=index,
        observation={"text": f"obs_{index}"},
        action={"selected": selected, "text": f"act_{index}"},
        action_type=action_type,
        reward_vector={"r1": reward},
        terminal=(index == 1),
    )


def _make_episode(
    agent_version: str = "v1",
    hard_gates: bool = True,
    n_steps: int = 2,
    action_type: str = "mutation_selection",
    failure_family: str = "type_errors",
) -> Episode:
    steps = [_make_step(i, action_type=action_type) for i in range(n_steps)]
    return Episode(
        agent_version=agent_version,
        adk_project="proj",
        steps=steps,
        total_reward={"r1": 0.8},
        hard_gates_passed=hard_gates,
        metadata={"failure_family": failure_family, "complexity": "medium"},
    )


# ---------------------------------------------------------------------------
# build_training_data
# ---------------------------------------------------------------------------

def test_build_training_data_returns_records():
    learner = ControlPolicyLearner()
    episodes = [_make_episode(), _make_episode(agent_version="v2")]
    data = learner.build_training_data(episodes)
    assert len(data) > 0


def test_build_training_data_record_structure():
    learner = ControlPolicyLearner()
    episodes = [_make_episode()]
    data = learner.build_training_data(episodes)
    for record in data:
        assert "context" in record
        assert "action" in record
        assert "reward" in record
        assert "success" in record
        assert "episode_id" in record


def test_build_training_data_skips_irrelevant_action_types():
    learner = ControlPolicyLearner()
    ep = _make_episode(action_type="tool_call")  # not a learnable decision type
    data = learner.build_training_data([ep])
    assert data == []


def test_build_training_data_routing_decision_included():
    learner = ControlPolicyLearner()
    ep = _make_episode(action_type="routing_decision")
    data = learner.build_training_data([ep])
    assert len(data) > 0
    assert all(r["action_type"] == "routing_decision" for r in data)


# ---------------------------------------------------------------------------
# train
# ---------------------------------------------------------------------------

def test_train_returns_policy_artifact():
    learner = ControlPolicyLearner()
    episodes = [_make_episode() for _ in range(3)]
    data = learner.build_training_data(episodes)
    artifact = learner.train(data)
    assert isinstance(artifact, PolicyArtifact)
    assert artifact.policy_type == PolicyType.mutation_policy
    assert artifact.training_mode == TrainingMode.control


def test_train_populates_metadata():
    learner = ControlPolicyLearner()
    data = learner.build_training_data([_make_episode()])
    artifact = learner.train(data)
    assert "arm_stats" in artifact.metadata
    assert artifact.provenance.get("n_records") == len(data)


def test_train_on_empty_data_returns_empty_artifact():
    learner = ControlPolicyLearner()
    artifact = learner.train([])
    assert isinstance(artifact, PolicyArtifact)
    assert artifact.metadata.get("arm_stats") == {}


# ---------------------------------------------------------------------------
# predict / get_action_scores
# ---------------------------------------------------------------------------

def test_predict_returns_string():
    learner = ControlPolicyLearner()
    episodes = [_make_episode(action_type="mutation_selection")]
    data = learner.build_training_data(episodes)
    artifact = learner.train(data)
    context = {"agent_version": "v1", "failure_family": "type_errors", "complexity": "medium"}
    action = learner.predict(artifact, context)
    assert isinstance(action, str)


def test_predict_returns_empty_string_for_unknown_context():
    learner = ControlPolicyLearner()
    artifact = learner.train([])
    action = learner.predict(artifact, {"agent_version": "unknown"})
    assert action == ""


def test_get_action_scores_returns_dict():
    learner = ControlPolicyLearner()
    episodes = [_make_episode(action_type="mutation_selection")]
    data = learner.build_training_data(episodes)
    artifact = learner.train(data)
    context = {"agent_version": "v1", "failure_family": "type_errors", "complexity": "medium"}
    scores = learner.get_action_scores(artifact, context)
    # Should be a dict (may be empty if context doesn't exactly match)
    assert isinstance(scores, dict)
    for v in scores.values():
        assert isinstance(v, float)
