"""Tests for RewardDatasetBuilder in policy_opt/dataset_builder.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.episode_types import Episode, EpisodeStep
from policy_opt.dataset_builder import RewardDatasetBuilder
from rewards.types import RewardDefinition, RewardKind


def _make_step(index: int = 0) -> EpisodeStep:
    return EpisodeStep(
        step_index=index,
        observation={"text": f"What is step {index}?"},
        action={"text": f"Answer to step {index}."},
        action_type="tool_call",
        reward_vector={"r1": 0.9},
        terminal=(index == 1),
    )


def _make_episode(
    hard_gates: bool = True,
    n_steps: int = 2,
    preference_labels: list | None = None,
    total_reward: dict | None = None,
    experiment_id: str = "exp1",
    agent_version: str = "v1",
) -> Episode:
    steps = [_make_step(i) for i in range(n_steps)]
    return Episode(
        agent_version=agent_version,
        experiment_id=experiment_id,
        steps=steps,
        total_reward=total_reward or {"r1": 0.8},
        hard_gates_passed=hard_gates,
        preference_labels=preference_labels or [],
    )


def _make_reward_def(reward_id: str = "r1", weight: float = 1.0) -> RewardDefinition:
    return RewardDefinition(
        reward_id=reward_id,
        name=reward_id,
        kind=RewardKind.verifiable,
        weight=weight,
    )


@pytest.fixture
def builder(tmp_path: Path) -> RewardDatasetBuilder:
    return RewardDatasetBuilder(output_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# build_verifiable_dataset
# ---------------------------------------------------------------------------

def test_build_verifiable_dataset_creates_file(builder: RewardDatasetBuilder, tmp_path: Path):
    episodes = [_make_episode(hard_gates=True) for _ in range(3)]
    path = builder.build_verifiable_dataset(episodes)
    assert Path(path).exists()


def test_build_verifiable_dataset_excludes_failed_gates(builder: RewardDatasetBuilder):
    episodes = [
        _make_episode(hard_gates=True),
        _make_episode(hard_gates=False),
    ]
    path = builder.build_verifiable_dataset(episodes)
    lines = [l for l in Path(path).read_text().strip().splitlines() if l]
    assert len(lines) == 1  # only the gate-passing episode


def test_build_verifiable_dataset_record_fields(builder: RewardDatasetBuilder):
    episodes = [_make_episode(hard_gates=True)]
    path = builder.build_verifiable_dataset(episodes)
    record = json.loads(Path(path).read_text().strip())
    assert "episode_id" in record
    assert "messages" in record
    assert "reward" in record
    assert "hard_gates_passed" in record
    assert record["hard_gates_passed"] is True


def test_build_verifiable_dataset_with_reward_definitions(builder: RewardDatasetBuilder):
    episodes = [_make_episode(hard_gates=True, total_reward={"r1": 0.6})]
    defns = [_make_reward_def("r1", weight=2.0)]
    path = builder.build_verifiable_dataset(episodes, reward_definitions=defns)
    assert Path(path).exists()
    record = json.loads(Path(path).read_text().strip())
    assert isinstance(record["reward"], float)


# ---------------------------------------------------------------------------
# build_preference_pairs
# ---------------------------------------------------------------------------

def test_build_preference_pairs_creates_file(builder: RewardDatasetBuilder):
    labels = [{
        "input_text": "What is 2+2?",
        "chosen": "4",
        "rejected": "5",
        "source": "human",
    }]
    episodes = [_make_episode(preference_labels=labels)]
    path = builder.build_preference_pairs(episodes)
    assert Path(path).exists()


def test_build_preference_pairs_skips_episodes_without_labels(builder: RewardDatasetBuilder):
    episodes = [_make_episode(preference_labels=[])]
    path = builder.build_preference_pairs(episodes)
    lines = [l for l in Path(path).read_text().strip().splitlines() if l]
    assert lines == []


def test_build_preference_pairs_record_structure(builder: RewardDatasetBuilder):
    labels = [{
        "input_text": "prompt text",
        "chosen": "good response",
        "rejected": "bad response",
        "source": "annotation_tool",
        "confidence": 0.9,
    }]
    episodes = [_make_episode(preference_labels=labels)]
    path = builder.build_preference_pairs(episodes)
    lines = [l for l in Path(path).read_text().strip().splitlines() if l]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["input_text"] == "prompt text"
    assert record["chosen"] == "good response"
    assert record["rejected"] == "bad response"
    assert "metadata" in record


# ---------------------------------------------------------------------------
# build_episode_export
# ---------------------------------------------------------------------------

def test_build_episode_export_creates_file(builder: RewardDatasetBuilder):
    episodes = [_make_episode() for _ in range(2)]
    path = builder.build_episode_export(episodes)
    assert Path(path).exists()


def test_build_episode_export_one_line_per_episode(builder: RewardDatasetBuilder):
    episodes = [_make_episode() for _ in range(4)]
    path = builder.build_episode_export(episodes)
    lines = [l for l in Path(path).read_text().strip().splitlines() if l]
    assert len(lines) == 4


def test_build_episode_export_contains_steps(builder: RewardDatasetBuilder):
    ep = _make_episode(n_steps=3)
    path = builder.build_episode_export([ep])
    record = json.loads(Path(path).read_text().strip())
    assert len(record["steps"]) == 3


# ---------------------------------------------------------------------------
# build_audit_set
# ---------------------------------------------------------------------------

def test_build_audit_set_creates_file(builder: RewardDatasetBuilder):
    # Need variance to trigger outlier detection
    episodes = (
        [_make_episode(total_reward={"r1": 1.0}) for _ in range(3)]
        + [_make_episode(total_reward={"r1": 0.0}) for _ in range(3)]
    )
    path = builder.build_audit_set(episodes)
    assert Path(path).exists()


def test_build_audit_set_record_has_audit_reasons(builder: RewardDatasetBuilder):
    # Create episodes with extreme rewards to force outlier flagging
    episodes = (
        [_make_episode(total_reward={"r1": 1.0})] * 5
        + [_make_episode(total_reward={"r1": 0.0})] * 5
    )
    path = builder.build_audit_set(episodes)
    content = Path(path).read_text().strip()
    if content:
        record = json.loads(content.splitlines()[0])
        assert "audit_reasons" in record
        assert isinstance(record["audit_reasons"], list)


def test_build_audit_set_empty_episodes_creates_empty_file(builder: RewardDatasetBuilder):
    path = builder.build_audit_set([])
    lines = [l for l in Path(path).read_text().strip().splitlines() if l]
    assert lines == []
