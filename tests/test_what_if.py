"""Tests for what-if replay engine."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.what_if import router as what_if_router
from evals.what_if import (
    ReplayOutcome,
    WhatIfEngine,
    WhatIfResult,
    WhatIfStore,
)
from logger.store import ConversationStore
from tests.helpers import build_record


def _tmp_db() -> str:
    """Return a path to a fresh temp SQLite database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


@pytest.fixture
def what_if_app(conversation_store: ConversationStore) -> FastAPI:
    """Minimal FastAPI app with the what-if router mounted."""
    app = FastAPI()
    app.include_router(what_if_router)
    app.state.conversation_store = conversation_store
    return app


@pytest.fixture
def what_if_client(what_if_app: FastAPI) -> TestClient:
    """Test client for the what-if router app."""
    return TestClient(what_if_app)


# ---------------------------------------------------------------------------
# WhatIfStore tests
# ---------------------------------------------------------------------------


def test_what_if_store_save_and_get_result() -> None:
    """WhatIfStore should persist and retrieve results."""
    db = _tmp_db()
    store = WhatIfStore(db_path=db)

    outcome1 = ReplayOutcome(
        conversation_id="conv1",
        original_outcome="success",
        replay_outcome="success",
        original_score=0.9,
        replay_score=0.95,
        original_latency_ms=100.0,
        replay_latency_ms=80.0,
        original_cost=0.01,
        replay_cost=0.008,
        tool_calls_matched=True,
        delta_score=0.05,
        improved=True,
    )

    outcome2 = ReplayOutcome(
        conversation_id="conv2",
        original_outcome="fail",
        replay_outcome="success",
        original_score=0.3,
        replay_score=0.85,
        original_latency_ms=200.0,
        replay_latency_ms=150.0,
        original_cost=0.02,
        replay_cost=0.015,
        tool_calls_matched=True,
        delta_score=0.55,
        improved=True,
    )

    result = WhatIfResult(
        job_id="job1",
        candidate_config_label="candidate_v2",
        conversation_ids=["conv1", "conv2"],
        outcomes=[outcome1, outcome2],
        total_conversations=2,
        improved_count=2,
        degraded_count=0,
        unchanged_count=0,
        avg_delta_score=0.30,
    )

    store.save_result(result)

    loaded = store.get_result("job1")
    assert loaded is not None
    assert loaded.job_id == "job1"
    assert loaded.candidate_config_label == "candidate_v2"
    assert loaded.total_conversations == 2
    assert loaded.improved_count == 2
    assert len(loaded.outcomes) == 2
    assert loaded.outcomes[0].conversation_id == "conv1"
    assert loaded.outcomes[0].improved is True
    assert loaded.outcomes[1].delta_score == 0.55


def test_what_if_store_get_nonexistent_result() -> None:
    """Getting a non-existent result should return None."""
    db = _tmp_db()
    store = WhatIfStore(db_path=db)

    result = store.get_result("nonexistent")
    assert result is None


def test_what_if_store_list_recent() -> None:
    """WhatIfStore should list recent jobs."""
    db = _tmp_db()
    store = WhatIfStore(db_path=db)

    for i in range(3):
        result = WhatIfResult(
            job_id=f"job{i}",
            candidate_config_label=f"v{i}",
            conversation_ids=[f"conv{i}"],
            outcomes=[],
            total_conversations=1,
            improved_count=0,
            degraded_count=0,
            unchanged_count=1,
            avg_delta_score=0.0,
        )
        store.save_result(result)

    jobs = store.list_recent(limit=2)
    assert len(jobs) == 2
    # Most recent first
    assert jobs[0]["job_id"] == "job2"
    assert jobs[1]["job_id"] == "job1"


def test_what_if_jobs_route_initializes_engine(what_if_client: TestClient) -> None:
    """Listing jobs should not fail when the app omitted explicit what-if wiring."""
    response = what_if_client.get("/api/what-if/jobs")

    assert response.status_code == 200
    assert response.json() == {"jobs": []}


def test_what_if_replay_route_uses_lazy_initialized_engine(
    what_if_client: TestClient,
    conversation_store: ConversationStore,
) -> None:
    """Replay route should initialize a what-if engine and return results."""
    record = build_record(
        user_message="Can I get a refund for the duplicate charge?",
        agent_response="Let me connect you with billing.",
        outcome="success",
        latency_ms=120.0,
        token_count=80,
    )
    conversation_store.log(record)

    response = what_if_client.post(
        "/api/what-if/replay",
        json={
            "conversation_ids": [record.conversation_id],
            "candidate_config_label": "candidate_v2",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["job_id"].startswith("whatif_")
    assert payload["total_conversations"] == 1


# ---------------------------------------------------------------------------
# WhatIfEngine tests
# ---------------------------------------------------------------------------


def test_what_if_engine_replay_with_config(conversation_store: ConversationStore) -> None:
    """WhatIfEngine should replay conversations and compute deltas."""
    # Add test conversations
    conv1 = build_record(
        user_message="Test 1",
        agent_response="Response 1",
        outcome="success",
        latency_ms=100.0,
        token_count=100,
    )
    conv2 = build_record(
        user_message="Test 2",
        agent_response="Response 2",
        outcome="fail",
        latency_ms=200.0,
        token_count=200,
    )

    conversation_store.log(conv1)
    conversation_store.log(conv2)

    engine = WhatIfEngine(
        conversation_store=conversation_store,
        what_if_store=WhatIfStore(db_path=_tmp_db()),
    )

    result = engine.replay_with_config(
        conversation_ids=[conv1.conversation_id, conv2.conversation_id],
        candidate_config_label="candidate_v1",
    )

    assert result.job_id.startswith("whatif_")
    assert result.candidate_config_label == "candidate_v1"
    assert result.total_conversations == 2
    assert len(result.outcomes) == 2
    assert result.improved_count >= 0
    assert result.degraded_count >= 0
    assert result.unchanged_count >= 0


def test_what_if_engine_replay_skips_missing_conversations() -> None:
    """WhatIfEngine should skip conversations that don't exist."""
    mock_store = MagicMock()
    mock_store.get = MagicMock(return_value=None)

    engine = WhatIfEngine(
        conversation_store=mock_store,
        what_if_store=WhatIfStore(db_path=_tmp_db()),
    )

    result = engine.replay_with_config(
        conversation_ids=["missing1", "missing2"],
        candidate_config_label="candidate_v1",
    )

    assert result.total_conversations == 0
    assert len(result.outcomes) == 0


def test_what_if_engine_compare_outcomes() -> None:
    """WhatIfEngine should compare original and replay outcomes."""
    engine = WhatIfEngine(
        conversation_store=MagicMock(),
        what_if_store=WhatIfStore(db_path=_tmp_db()),
    )

    original = [
        {"conversation_id": "c1", "score": 0.8},
        {"conversation_id": "c2", "score": 0.5},
        {"conversation_id": "c3", "score": 0.9},
    ]

    replay = [
        {"conversation_id": "c1", "score": 0.9},  # improved
        {"conversation_id": "c2", "score": 0.4},  # degraded
        {"conversation_id": "c3", "score": 0.9},  # unchanged
    ]

    comparison = engine.compare_outcomes(original, replay)

    assert comparison["total"] == 3
    assert comparison["improved"] == 1
    assert comparison["degraded"] == 1
    assert comparison["unchanged"] == 1
    # avg_delta should be 0.0 (improved +0.1, degraded -0.1, unchanged 0)
    assert abs(comparison["avg_delta"]) < 0.01


def test_what_if_engine_compare_outcomes_mismatched_lengths() -> None:
    """compare_outcomes should raise error on mismatched lengths."""
    engine = WhatIfEngine(
        conversation_store=MagicMock(),
        what_if_store=WhatIfStore(db_path=_tmp_db()),
    )

    original = [{"conversation_id": "c1", "score": 0.8}]
    replay = [
        {"conversation_id": "c1", "score": 0.9},
        {"conversation_id": "c2", "score": 0.9},
    ]

    try:
        engine.compare_outcomes(original, replay)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "must match" in str(e)


def test_what_if_engine_project_impact() -> None:
    """WhatIfEngine should project impact to full population."""
    db = _tmp_db()
    store = WhatIfStore(db_path=db)

    # Create a sample result with 10 conversations, 7 improved
    outcomes = []
    for i in range(10):
        outcomes.append(
            ReplayOutcome(
                conversation_id=f"conv{i}",
                original_outcome="fail",
                replay_outcome="success",
                original_score=0.5,
                replay_score=0.9,
                original_latency_ms=100.0,
                replay_latency_ms=80.0,
                original_cost=0.01,
                replay_cost=0.008,
                tool_calls_matched=True,
                delta_score=0.4,
                improved=(i < 7),  # 7 out of 10 improved
            )
        )

    result = WhatIfResult(
        job_id="proj_test",
        candidate_config_label="v1",
        conversation_ids=[f"conv{i}" for i in range(10)],
        outcomes=outcomes,
        total_conversations=10,
        improved_count=7,
        degraded_count=0,
        unchanged_count=3,
        avg_delta_score=0.28,
    )
    store.save_result(result)

    engine = WhatIfEngine(conversation_store=MagicMock(), what_if_store=store)

    projection = engine.project_impact(job_id="proj_test", total_population=1000)

    assert projection.job_id == "proj_test"
    assert projection.sample_size == 10
    assert projection.total_population == 1000
    assert projection.improved_count == 7
    assert projection.projected_improvement_rate == 0.7
    assert projection.projected_improvement_absolute == 700
    assert projection.confidence_interval_95[0] > 0
    assert projection.confidence_interval_95[1] <= 1.0
    assert projection.recommendation == "RECOMMEND_DEPLOY"


def test_what_if_engine_project_impact_negative() -> None:
    """project_impact should recommend against deployment for negative results."""
    db = _tmp_db()
    store = WhatIfStore(db_path=db)

    # Create result with degraded performance
    outcomes = []
    for i in range(10):
        outcomes.append(
            ReplayOutcome(
                conversation_id=f"conv{i}",
                original_outcome="success",
                replay_outcome="fail",
                original_score=0.9,
                replay_score=0.3,
                original_latency_ms=100.0,
                replay_latency_ms=200.0,
                original_cost=0.01,
                replay_cost=0.02,
                tool_calls_matched=True,
                delta_score=-0.6,
                improved=False,
            )
        )

    result = WhatIfResult(
        job_id="neg_test",
        candidate_config_label="v1",
        conversation_ids=[f"conv{i}" for i in range(10)],
        outcomes=outcomes,
        total_conversations=10,
        improved_count=0,
        degraded_count=10,
        unchanged_count=0,
        avg_delta_score=-0.6,
    )
    store.save_result(result)

    engine = WhatIfEngine(conversation_store=MagicMock(), what_if_store=store)
    projection = engine.project_impact(job_id="neg_test", total_population=1000)

    assert projection.recommendation == "DO_NOT_DEPLOY"


def test_what_if_engine_project_impact_nonexistent_job() -> None:
    """project_impact should raise error for non-existent job."""
    engine = WhatIfEngine(
        conversation_store=MagicMock(),
        what_if_store=WhatIfStore(db_path=_tmp_db()),
    )

    try:
        engine.project_impact(job_id="nonexistent", total_population=1000)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "not found" in str(e)


def test_what_if_engine_project_impact_empty_sample() -> None:
    """project_impact should raise error for empty sample."""
    db = _tmp_db()
    store = WhatIfStore(db_path=db)

    result = WhatIfResult(
        job_id="empty",
        candidate_config_label="v1",
        conversation_ids=[],
        outcomes=[],
        total_conversations=0,
        improved_count=0,
        degraded_count=0,
        unchanged_count=0,
        avg_delta_score=0.0,
    )
    store.save_result(result)

    engine = WhatIfEngine(conversation_store=MagicMock(), what_if_store=store)

    try:
        engine.project_impact(job_id="empty", total_population=1000)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "empty sample" in str(e)


def test_replay_outcome_defaults() -> None:
    """ReplayOutcome should have correct defaults."""
    outcome = ReplayOutcome(
        conversation_id="test",
        original_outcome="success",
        replay_outcome="success",
        original_score=0.9,
        replay_score=0.95,
        original_latency_ms=100.0,
        replay_latency_ms=80.0,
        original_cost=0.01,
        replay_cost=0.008,
        tool_calls_matched=True,
    )

    assert outcome.delta_score == 0.0
    assert outcome.improved is False
