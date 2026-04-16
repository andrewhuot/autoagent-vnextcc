"""Unit tests for the post-experiment reflection engine."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from optimizer.reflection import Reflection, ReflectionEngine, SurfaceEffectiveness


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_attempt(
    *,
    attempt_id: str = "att-001",
    status: str = "accepted",
    change_description: str = "Rewrite root prompt for clarity",
    config_section: str = "prompts",
    score_before: float = 0.70,
    score_after: float = 0.80,
) -> dict:
    """Build a minimal attempt dict matching OptimizationAttempt fields."""
    return {
        "attempt_id": attempt_id,
        "timestamp": time.time(),
        "change_description": change_description,
        "config_diff": "{}",
        "config_section": config_section,
        "status": status,
        "score_before": score_before,
        "score_after": score_after,
    }


def _make_engine(tmp_path: Path, llm_router: MagicMock | None = None) -> ReflectionEngine:
    """Build a ReflectionEngine backed by a temp database."""
    db_path = str(tmp_path / "reflections.db")
    return ReflectionEngine(llm_router=llm_router, db_path=db_path)


# ---------------------------------------------------------------------------
# Deterministic reflection tests
# ---------------------------------------------------------------------------


class TestDeterministicReflectionAccepted:
    """Deterministic reflection on an accepted attempt with positive delta."""

    def test_what_worked_populated(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        attempt = _make_attempt(status="accepted", score_before=0.70, score_after=0.80)
        result = engine.reflect(attempt)

        assert result.outcome == "accepted"
        assert result.score_delta == pytest.approx(0.10)
        assert len(result.what_worked) == 1
        assert "Rewrite root prompt" in result.what_worked[0]
        assert result.what_didnt == []

    def test_surface_learnings_positive(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        attempt = _make_attempt(status="accepted", score_before=0.70, score_after=0.80)
        result = engine.reflect(attempt)

        assert "prompts" in result.surface_learnings
        assert result.surface_learnings["prompts"] > 0.0

    def test_next_suggestions_deepen(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        attempt = _make_attempt(status="accepted", score_before=0.70, score_after=0.80)
        result = engine.reflect(attempt)

        assert len(result.next_suggestions) >= 1
        assert any("prompts" in s for s in result.next_suggestions)

    def test_confidence_and_reasoning(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        attempt = _make_attempt(status="accepted", score_before=0.70, score_after=0.80)
        result = engine.reflect(attempt)

        assert result.confidence > 0.0
        assert result.reasoning != ""


class TestDeterministicReflectionRejected:
    """Deterministic reflection on rejected attempts."""

    def test_regression_populates_what_didnt(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        attempt = _make_attempt(
            status="rejected_regression",
            score_before=0.80,
            score_after=0.65,
        )
        result = engine.reflect(attempt)

        assert result.outcome == "rejected_regression"
        assert result.score_delta == pytest.approx(-0.15)
        assert result.what_worked == []
        assert len(result.what_didnt) == 1
        assert "counterproductive" in result.root_cause_update.lower()

    def test_no_change_populates_what_didnt(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        attempt = _make_attempt(
            status="rejected_no_improvement",
            score_before=0.75,
            score_after=0.75,
        )
        result = engine.reflect(attempt)

        assert result.score_delta == pytest.approx(0.0)
        assert result.what_worked == []
        assert len(result.what_didnt) == 1
        assert "no measurable effect" in result.root_cause_update.lower()

    def test_regression_surface_learnings_zero(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        attempt = _make_attempt(
            status="rejected_regression",
            score_before=0.80,
            score_after=0.65,
        )
        result = engine.reflect(attempt)

        assert result.surface_learnings.get("prompts") == 0.0

    def test_rejected_suggests_different_surface(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        attempt = _make_attempt(
            status="rejected_regression",
            score_before=0.80,
            score_after=0.65,
        )
        result = engine.reflect(attempt)

        assert any("different" in s.lower() for s in result.next_suggestions)


# ---------------------------------------------------------------------------
# LLM reflection tests
# ---------------------------------------------------------------------------


def _mock_llm_response(payload: dict) -> MagicMock:
    """Create a mock LLMResponse with the given JSON payload."""
    resp = MagicMock()
    resp.text = json.dumps(payload)
    return resp


class TestLLMReflection:
    """Reflection using a mocked LLM router."""

    def test_llm_reflection_parses_response(self, tmp_path: Path) -> None:
        router = MagicMock()
        router.generate.return_value = _mock_llm_response(
            {
                "what_worked": ["Prompt rewrite improved clarity"],
                "what_didnt": [],
                "root_cause_update": "Root prompt was too vague",
                "next_suggestions": ["Try adding examples to the prompt"],
                "surface_learnings": {"prompts": 0.85},
                "confidence": 0.9,
                "reasoning": "The rewrite directly addressed the vagueness issue.",
            }
        )
        engine = _make_engine(tmp_path, llm_router=router)
        attempt = _make_attempt(status="accepted", score_before=0.70, score_after=0.80)
        result = engine.reflect(attempt)

        assert result.what_worked == ["Prompt rewrite improved clarity"]
        assert result.what_didnt == []
        assert result.root_cause_update == "Root prompt was too vague"
        assert result.confidence == pytest.approx(0.9)
        assert result.surface_learnings == {"prompts": 0.85}
        router.generate.assert_called_once()

    def test_llm_reflection_with_wrapped_json(self, tmp_path: Path) -> None:
        """LLM wraps JSON in markdown fences — should still parse."""
        router = MagicMock()
        wrapped = (
            "Here is my analysis:\n```json\n"
            + json.dumps(
                {
                    "what_worked": ["Better routing"],
                    "what_didnt": [],
                    "root_cause_update": "Routing was the bottleneck",
                    "next_suggestions": ["Expand keywords"],
                    "surface_learnings": {"routing": 0.7},
                    "confidence": 0.8,
                    "reasoning": "Routing fix resolved misrouted queries.",
                }
            )
            + "\n```"
        )
        resp = MagicMock()
        resp.text = wrapped
        router.generate.return_value = resp
        engine = _make_engine(tmp_path, llm_router=router)
        attempt = _make_attempt(status="accepted", score_before=0.60, score_after=0.72)
        result = engine.reflect(attempt)

        assert result.what_worked == ["Better routing"]
        assert result.surface_learnings == {"routing": 0.7}

    def test_llm_fallback_on_error(self, tmp_path: Path) -> None:
        """When LLM raises, engine falls back to deterministic reflection."""
        router = MagicMock()
        router.generate.side_effect = RuntimeError("LLM unavailable")
        engine = _make_engine(tmp_path, llm_router=router)
        attempt = _make_attempt(status="accepted", score_before=0.70, score_after=0.80)
        result = engine.reflect(attempt)

        # Should still get a valid reflection from deterministic path.
        assert result.attempt_id == "att-001"
        assert result.score_delta == pytest.approx(0.10)
        assert len(result.what_worked) >= 1

    def test_llm_fallback_on_unparseable_json(self, tmp_path: Path) -> None:
        """When LLM returns garbage, engine falls back to deterministic."""
        router = MagicMock()
        resp = MagicMock()
        resp.text = "I don't know how to respond as JSON!"
        router.generate.return_value = resp
        engine = _make_engine(tmp_path, llm_router=router)
        attempt = _make_attempt(status="accepted", score_before=0.70, score_after=0.80)
        result = engine.reflect(attempt)

        assert result.attempt_id == "att-001"
        assert len(result.what_worked) >= 1


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


class TestPersistence:
    """Reflect then verify data is retrievable."""

    def test_reflect_then_get_context(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        attempt = _make_attempt(status="accepted", score_before=0.70, score_after=0.80)
        engine.reflect(attempt)

        ctx = engine.get_context_for_next_cycle(limit=5)
        assert len(ctx["recent_reflections"]) == 1
        ref = ctx["recent_reflections"][0]
        assert ref["attempt_id"] == "att-001"
        assert ref["outcome"] == "accepted"
        assert ref["score_delta"] == pytest.approx(0.10)

    def test_multiple_reflections_ordered(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        for i in range(3):
            attempt = _make_attempt(
                attempt_id=f"att-{i:03d}",
                status="accepted",
                score_before=0.60 + i * 0.05,
                score_after=0.65 + i * 0.05,
            )
            engine.reflect(attempt)

        ctx = engine.get_context_for_next_cycle(limit=10)
        ids = [r["attempt_id"] for r in ctx["recent_reflections"]]
        # Most recent first.
        assert ids[0] == "att-002"

    def test_limit_respected(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        for i in range(10):
            attempt = _make_attempt(
                attempt_id=f"att-{i:03d}",
                status="accepted",
                score_before=0.50,
                score_after=0.55,
            )
            engine.reflect(attempt)

        ctx = engine.get_context_for_next_cycle(limit=3)
        assert len(ctx["recent_reflections"]) == 3


# ---------------------------------------------------------------------------
# Surface effectiveness tests
# ---------------------------------------------------------------------------


class TestSurfaceEffectiveness:
    """Cumulative surface effectiveness scoring."""

    def test_single_success(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        attempt = _make_attempt(
            status="accepted",
            config_section="prompts",
            score_before=0.70,
            score_after=0.80,
        )
        engine.reflect(attempt)

        eff = engine.get_surface_effectiveness()
        assert "prompts" in eff
        assert eff["prompts"].attempts == 1
        assert eff["prompts"].successes == 1
        assert eff["prompts"].success_rate == pytest.approx(1.0)
        assert eff["prompts"].avg_improvement > 0.0

    def test_accumulation_across_attempts(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        # First: accepted improvement.
        engine.reflect(
            _make_attempt(
                attempt_id="att-a",
                status="accepted",
                config_section="prompts",
                score_before=0.70,
                score_after=0.80,
            )
        )
        # Second: rejected regression on same surface.
        engine.reflect(
            _make_attempt(
                attempt_id="att-b",
                status="rejected_regression",
                config_section="prompts",
                score_before=0.80,
                score_after=0.75,
            )
        )
        # Third: accepted on a different surface.
        engine.reflect(
            _make_attempt(
                attempt_id="att-c",
                status="accepted",
                config_section="routing",
                score_before=0.60,
                score_after=0.72,
            )
        )

        eff = engine.get_surface_effectiveness()
        assert eff["prompts"].attempts == 2
        assert eff["prompts"].successes == 1
        assert eff["prompts"].success_rate == pytest.approx(0.5)

        assert eff["routing"].attempts == 1
        assert eff["routing"].successes == 1
        assert eff["routing"].success_rate == pytest.approx(1.0)

    def test_success_rate_property(self) -> None:
        eff = SurfaceEffectiveness(surface="test", attempts=0, successes=0)
        assert eff.success_rate == 0.0

        eff = SurfaceEffectiveness(surface="test", attempts=4, successes=3)
        assert eff.success_rate == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# get_context_for_next_cycle format tests
# ---------------------------------------------------------------------------


class TestContextFormat:
    """Verify the shape of get_context_for_next_cycle output."""

    def test_context_keys(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        ctx = engine.get_context_for_next_cycle()

        assert "recent_reflections" in ctx
        assert "surface_effectiveness" in ctx
        assert "patterns" in ctx
        assert isinstance(ctx["recent_reflections"], list)
        assert isinstance(ctx["surface_effectiveness"], dict)
        assert isinstance(ctx["patterns"], list)

    def test_context_with_data(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        engine.reflect(
            _make_attempt(status="accepted", score_before=0.70, score_after=0.80)
        )
        ctx = engine.get_context_for_next_cycle()

        ref = ctx["recent_reflections"][0]
        assert "attempt_id" in ref
        assert "outcome" in ref
        assert "what_worked" in ref
        assert "what_didnt" in ref
        assert "next_suggestions" in ref
        assert "confidence" in ref

        # Surface effectiveness should be serialized as dicts.
        for surface_data in ctx["surface_effectiveness"].values():
            assert "surface" in surface_data
            assert "attempts" in surface_data
            assert "success_rate" in surface_data

    def test_patterns_generated_for_effective_surface(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        # Two successes on same surface => effective pattern.
        for i in range(2):
            engine.reflect(
                _make_attempt(
                    attempt_id=f"att-{i}",
                    status="accepted",
                    config_section="prompts",
                    score_before=0.70,
                    score_after=0.80,
                )
            )
        ctx = engine.get_context_for_next_cycle()
        assert any("effective" in p.lower() for p in ctx["patterns"])

    def test_patterns_generated_for_ineffective_surface(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        # Two failures on same surface => ineffective pattern.
        for i in range(2):
            engine.reflect(
                _make_attempt(
                    attempt_id=f"att-{i}",
                    status="rejected_regression",
                    config_section="prompts",
                    score_before=0.80,
                    score_after=0.70,
                )
            )
        ctx = engine.get_context_for_next_cycle()
        assert any("ineffective" in p.lower() for p in ctx["patterns"])


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


class TestEmptyState:
    """Engine behavior with no prior reflections."""

    def test_empty_context(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        ctx = engine.get_context_for_next_cycle()

        assert ctx["recent_reflections"] == []
        assert ctx["surface_effectiveness"] == {}
        assert ctx["patterns"] == []

    def test_empty_surface_effectiveness(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        eff = engine.get_surface_effectiveness()
        assert eff == {}
