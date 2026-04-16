"""Tests for ReflectionEngine.read_surface_effectiveness (R3.3)."""

from optimizer.reflection import ReflectionEngine, SurfaceEffectiveness


def _seed_accepted_attempt(engine: ReflectionEngine, attempt_id: str, surface: str,
                           score_before: float = 0.70, score_after: float = 0.80) -> None:
    """Seed an accepted attempt via the real reflect() deterministic path."""
    engine.reflect({
        "attempt_id": attempt_id,
        "status": "accepted",
        "score_before": score_before,
        "score_after": score_after,
        "change_description": f"change on {surface}",
        "config_section": surface,
    })


def test_read_surface_effectiveness_returns_record(tmp_path) -> None:
    engine = ReflectionEngine(db_path=str(tmp_path / "r.db"))
    _seed_accepted_attempt(engine, "a1", "api")
    eff = engine.read_surface_effectiveness("api")
    assert isinstance(eff, SurfaceEffectiveness)
    assert eff.surface == "api"
    assert eff.attempts == 1
    assert eff.successes == 1
    assert eff.avg_improvement > 0


def test_read_surface_effectiveness_unknown_surface_returns_none(tmp_path) -> None:
    engine = ReflectionEngine(db_path=str(tmp_path / "r.db"))
    assert engine.read_surface_effectiveness("nonexistent") is None


def test_read_surface_effectiveness_accumulates_across_attempts(tmp_path) -> None:
    engine = ReflectionEngine(db_path=str(tmp_path / "r.db"))
    _seed_accepted_attempt(engine, "a1", "api", 0.50, 0.60)
    _seed_accepted_attempt(engine, "a2", "api", 0.60, 0.65)
    eff = engine.read_surface_effectiveness("api")
    assert eff is not None
    assert eff.attempts == 2
    assert eff.successes == 2
    assert eff.success_rate == 1.0


def test_read_surface_effectiveness_independent_surfaces(tmp_path) -> None:
    engine = ReflectionEngine(db_path=str(tmp_path / "r.db"))
    _seed_accepted_attempt(engine, "a1", "api")
    _seed_accepted_attempt(engine, "a2", "cli")
    assert engine.read_surface_effectiveness("api") is not None
    assert engine.read_surface_effectiveness("cli") is not None
    assert engine.read_surface_effectiveness("db") is None
