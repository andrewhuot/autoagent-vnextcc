"""Tests for Episode and EpisodeStep types in data/episode_types.py."""

from __future__ import annotations

import pytest

from data.episode_types import Episode, EpisodeStep


def _make_step(index: int = 0, action_type: str = "tool_call", terminal: bool = False) -> EpisodeStep:
    return EpisodeStep(
        step_index=index,
        observation={"text": f"obs_{index}"},
        action={"text": f"act_{index}", "selected": "op_a"},
        action_type=action_type,
        reward_vector={"r1": float(index) * 0.1},
        discount=1.0,
        terminal=terminal,
        metadata={"step_meta": index},
    )


def _make_episode(n_steps: int = 2, hard_gates: bool = True) -> Episode:
    steps = [_make_step(i, terminal=(i == n_steps - 1)) for i in range(n_steps)]
    return Episode(
        trace_id="trace-001",
        eval_run_id="eval-run-001",
        experiment_id="exp-001",
        agent_version="v1.0",
        adk_project="proj",
        steps=steps,
        total_reward={"r1": 0.75},
        hard_gates_passed=hard_gates,
        business_outcomes=[{"metric": "conversion", "value": 1}],
        preference_labels=[],
        tool_calls=[{"tool": "search", "result": "ok"}],
        metadata={"env": "test"},
    )


# ---------------------------------------------------------------------------
# EpisodeStep round-trip
# ---------------------------------------------------------------------------

def test_episode_step_round_trip():
    step = _make_step(index=3, action_type="routing_decision")
    restored = EpisodeStep.from_dict(step.to_dict())

    assert restored.step_id == step.step_id
    assert restored.step_index == 3
    assert restored.action_type == "routing_decision"
    assert restored.observation == step.observation
    assert restored.action == step.action
    assert restored.reward_vector == step.reward_vector
    assert restored.terminal == step.terminal
    assert restored.metadata == step.metadata


def test_episode_step_defaults():
    step = EpisodeStep()
    assert step.step_index == 0
    assert step.discount == 1.0
    assert step.terminal is False
    assert step.reward_vector == {}


def test_episode_step_from_dict_missing_fields():
    step = EpisodeStep.from_dict({"step_index": 5})
    assert step.step_index == 5
    assert step.action_type == ""


# ---------------------------------------------------------------------------
# Episode round-trip with nested steps
# ---------------------------------------------------------------------------

def test_episode_round_trip_with_steps():
    ep = _make_episode(n_steps=3)
    d = ep.to_dict()
    restored = Episode.from_dict(d)

    assert restored.episode_id == ep.episode_id
    assert restored.trace_id == ep.trace_id
    assert restored.eval_run_id == ep.eval_run_id
    assert restored.experiment_id == ep.experiment_id
    assert restored.agent_version == ep.agent_version
    assert restored.hard_gates_passed == ep.hard_gates_passed
    assert restored.total_reward == ep.total_reward
    assert len(restored.steps) == 3
    assert restored.steps[2].terminal is True


def test_episode_steps_serialized_correctly():
    ep = _make_episode(n_steps=2)
    d = ep.to_dict()
    assert len(d["steps"]) == 2
    assert d["steps"][0]["step_index"] == 0
    assert d["steps"][1]["step_index"] == 1


def test_episode_defaults():
    ep = Episode()
    assert ep.hard_gates_passed is True
    assert ep.steps == []
    assert ep.total_reward == {}
    assert ep.business_outcomes == []


def test_episode_from_dict_handles_missing_fields():
    ep = Episode.from_dict({"trace_id": "t1"})
    assert ep.trace_id == "t1"
    assert ep.steps == []
    assert ep.hard_gates_passed is True
