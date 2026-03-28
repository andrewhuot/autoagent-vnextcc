"""Tests for EpisodeStore CRUD in data/episodes.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.episode_types import Episode, EpisodeStep
from data.episodes import EpisodeStore


@pytest.fixture
def store(tmp_path: Path) -> EpisodeStore:
    db = tmp_path / "episodes_test.db"
    s = EpisodeStore(str(db))
    yield s
    s.close()


def _make_episode(
    trace_id: str = "t1",
    eval_run_id: str = "ev1",
    experiment_id: str = "exp1",
    agent_version: str = "v1",
    hard_gates: bool = True,
    n_steps: int = 1,
) -> Episode:
    steps = [
        EpisodeStep(
            step_index=i,
            action={"text": f"act_{i}"},
            action_type="tool_call",
            reward_vector={"r1": 0.5},
        )
        for i in range(n_steps)
    ]
    return Episode(
        trace_id=trace_id,
        eval_run_id=eval_run_id,
        experiment_id=experiment_id,
        agent_version=agent_version,
        total_reward={"r1": 0.5},
        hard_gates_passed=hard_gates,
        steps=steps,
    )


# ---------------------------------------------------------------------------
# store_episode / get_episode
# ---------------------------------------------------------------------------

def test_store_and_get_episode(store: EpisodeStore):
    ep = _make_episode(n_steps=2)
    ep_id = store.store_episode(ep)

    fetched = store.get_episode(ep_id)
    assert fetched is not None
    assert fetched.episode_id == ep.episode_id
    assert len(fetched.steps) == 2


def test_get_missing_returns_none(store: EpisodeStore):
    assert store.get_episode("nonexistent-id") is None


def test_store_replaces_existing_episode(store: EpisodeStore):
    ep = _make_episode()
    store.store_episode(ep)
    ep.agent_version = "v2"
    store.store_episode(ep)
    fetched = store.get_episode(ep.episode_id)
    assert fetched.agent_version == "v2"


# ---------------------------------------------------------------------------
# list_episodes with filters
# ---------------------------------------------------------------------------

def test_list_episodes_by_experiment_id(store: EpisodeStore):
    store.store_episode(_make_episode(experiment_id="exp_a"))
    store.store_episode(_make_episode(experiment_id="exp_b"))
    results = store.list_episodes(experiment_id="exp_a")
    assert len(results) == 1
    assert results[0].experiment_id == "exp_a"


def test_list_episodes_hard_gates_only(store: EpisodeStore):
    store.store_episode(_make_episode(hard_gates=True))
    store.store_episode(_make_episode(hard_gates=False))
    results = store.list_episodes(hard_gates_only=True)
    assert all(ep.hard_gates_passed for ep in results)
    assert len(results) == 1


def test_list_episodes_by_agent_version(store: EpisodeStore):
    store.store_episode(_make_episode(agent_version="v1"))
    store.store_episode(_make_episode(agent_version="v2"))
    results = store.list_episodes(agent_version="v1")
    assert len(results) == 1
    assert results[0].agent_version == "v1"


# ---------------------------------------------------------------------------
# get_episodes_for_trace / count_episodes
# ---------------------------------------------------------------------------

def test_get_episodes_for_trace(store: EpisodeStore):
    ep1 = _make_episode(trace_id="trace-x")
    ep2 = _make_episode(trace_id="trace-x")
    store.store_episode(ep1)
    store.store_episode(ep2)
    results = store.get_episodes_for_trace("trace-x")
    assert len(results) == 2


def test_count_episodes_total(store: EpisodeStore):
    store.store_episode(_make_episode())
    store.store_episode(_make_episode())
    assert store.count_episodes() == 2


def test_count_episodes_with_filter(store: EpisodeStore):
    store.store_episode(_make_episode(hard_gates=True))
    store.store_episode(_make_episode(hard_gates=False))
    assert store.count_episodes(hard_gates_only=True) == 1


# ---------------------------------------------------------------------------
# delete_episode
# ---------------------------------------------------------------------------

def test_delete_episode(store: EpisodeStore):
    ep = _make_episode()
    store.store_episode(ep)
    deleted = store.delete_episode(ep.episode_id)
    assert deleted is True
    assert store.get_episode(ep.episode_id) is None


def test_delete_nonexistent_returns_false(store: EpisodeStore):
    assert store.delete_episode("no-such-id") is False


# ---------------------------------------------------------------------------
# export_jsonl
# ---------------------------------------------------------------------------

def test_export_jsonl(store: EpisodeStore, tmp_path: Path):
    ep1 = _make_episode()
    ep2 = _make_episode()
    store.store_episode(ep1)
    store.store_episode(ep2)

    out = tmp_path / "export.jsonl"
    path = store.export_jsonl(output_path=str(out))
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["episode_id"] in {ep1.episode_id, ep2.episode_id}
