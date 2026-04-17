"""Tests for cost-aware Pareto archive and ``optimize --show-tradeoffs`` (R6.11/R6.12).

These tests pin three things:

1.  ``ObjectiveName`` exposes quality/safety/cost as first-class names and the
    archive accepts them with direction-aware dominance (cost MINIMIZE).
2.  Legacy archives built without cost keep their pre-R6 2D behavior intact.
3.  The ``agentlab optimize`` command grew a ``--show-tradeoffs`` flag and its
    CLI renderer prints a fixed-width table of the top-K non-dominated
    candidates with quality / safety / cost columns plus dominance info.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 1. Cost-aware domination on ConstrainedParetoArchive (the direction-aware
#    archive that backs the optimize loop). We use the canonical objective
#    names from :class:`optimizer.pareto.ObjectiveName`.
# ---------------------------------------------------------------------------


def test_objective_name_enum_exposes_quality_safety_cost() -> None:
    """`ObjectiveName` must name the three first-class objectives."""
    from optimizer.pareto import ObjectiveName

    assert ObjectiveName.QUALITY.value == "quality"
    assert ObjectiveName.SAFETY.value == "safety"
    assert ObjectiveName.COST.value == "cost"


def test_cost_aware_pareto_dominance_three_way() -> None:
    """The 5-candidate scenario from the task spec:

    A (0.9, 0.9, 0.10)  — dominated by B (cheaper, same q/s)
    B (0.9, 0.9, 0.05)  — non-dominated
    C (0.95, 0.8, 0.05) — non-dominated (better quality)
    D (0.7, 0.7, 0.01)  — non-dominated (cheapest)
    E (0.5, 0.5, 0.20)  — dominated by B, C, D
    """
    from optimizer.pareto import (
        ConstrainedParetoArchive,
        ObjectiveDirection,
        ObjectiveName,
    )

    archive = ConstrainedParetoArchive(
        objective_directions={
            ObjectiveName.QUALITY.value: ObjectiveDirection.MAXIMIZE,
            ObjectiveName.SAFETY.value: ObjectiveDirection.MAXIMIZE,
            ObjectiveName.COST.value: ObjectiveDirection.MINIMIZE,
        }
    )
    scenarios = {
        "cand_A": {"quality": 0.9, "safety": 0.9, "cost": 0.10},
        "cand_B": {"quality": 0.9, "safety": 0.9, "cost": 0.05},
        "cand_C": {"quality": 0.95, "safety": 0.8, "cost": 0.05},
        "cand_D": {"quality": 0.7, "safety": 0.7, "cost": 0.01},
        "cand_E": {"quality": 0.5, "safety": 0.5, "cost": 0.20},
    }
    for cid, objectives in scenarios.items():
        archive.add_candidate(
            candidate_id=cid,
            objectives=objectives,
            constraints_passed=True,
        )

    front_ids = {c["candidate_id"] for c in archive.frontier()}
    assert front_ids == {"cand_B", "cand_C", "cand_D"}

    # Dominance spot-checks: B dominates A on cost; A is dominated, B is not.
    cand_a = next(c for c in archive.feasible_candidates if c["candidate_id"] == "cand_A")
    cand_b = next(c for c in archive.feasible_candidates if c["candidate_id"] == "cand_B")
    cand_e = next(c for c in archive.feasible_candidates if c["candidate_id"] == "cand_E")
    assert archive.dominates(cand_b, cand_a) is True
    assert archive.dominates(cand_a, cand_b) is False
    assert archive.dominates(cand_b, cand_e) is True


# ---------------------------------------------------------------------------
# 2. Backward compatibility: legacy positional-vector ParetoArchive still works
# ---------------------------------------------------------------------------


def test_legacy_pareto_archive_two_dim_unchanged() -> None:
    """The positional ``ParetoArchive`` (2D vectors) must still work exactly
    as it did before R6.11 — no cost dimension, no named objectives."""
    from optimizer.pareto import ParetoArchive, ParetoCandidate

    archive = ParetoArchive()
    a = ParetoCandidate(
        candidate_id="a",
        objective_vector=[0.5, 0.5],
        constraints_passed=True,
        constraint_violations=[],
        config_hash="h1",
    )
    b = ParetoCandidate(
        candidate_id="b",
        objective_vector=[0.9, 0.9],  # dominates a
        constraints_passed=True,
        constraint_violations=[],
        config_hash="h2",
    )
    archive.add(a)
    archive.add(b)
    front = archive.get_frontier()
    assert len(front) == 1
    assert front[0].candidate_id == "b"


# ---------------------------------------------------------------------------
# 3. CLI: ``--show-tradeoffs`` renders the top-K tradeoff table
# ---------------------------------------------------------------------------


def test_render_tradeoffs_table_formats_columns() -> None:
    """The CLI renderer emits a fixed-width ASCII table with the expected
    columns and dominance info."""
    from cli.commands.optimize import render_tradeoffs_table
    from optimizer.pareto import (
        ConstrainedParetoArchive,
        ObjectiveDirection,
        ObjectiveName,
    )

    archive = ConstrainedParetoArchive(
        objective_directions={
            ObjectiveName.QUALITY.value: ObjectiveDirection.MAXIMIZE,
            ObjectiveName.SAFETY.value: ObjectiveDirection.MAXIMIZE,
            ObjectiveName.COST.value: ObjectiveDirection.MINIMIZE,
        }
    )
    for cid, objectives in [
        ("cand_A", {"quality": 0.9, "safety": 0.9, "cost": 0.10}),
        ("cand_B", {"quality": 0.9, "safety": 0.9, "cost": 0.05}),
        ("cand_C", {"quality": 0.95, "safety": 0.8, "cost": 0.05}),
        ("cand_D", {"quality": 0.7, "safety": 0.7, "cost": 0.01}),
        ("cand_E", {"quality": 0.5, "safety": 0.5, "cost": 0.20}),
    ]:
        archive.add_candidate(
            candidate_id=cid,
            objectives=objectives,
            constraints_passed=True,
        )

    out = render_tradeoffs_table(archive, k=3)

    # Header
    assert "candidate" in out
    assert "quality" in out
    assert "safety" in out
    assert "cost" in out
    assert "dominates" in out
    assert "dominated_by" in out

    # Non-dominated candidates listed
    assert "cand_B" in out
    assert "cand_C" in out
    assert "cand_D" in out

    # Each listed candidate shows its quality value
    assert "0.9000" in out or "0.90" in out
    # Cost column visible
    assert "0.05" in out
    assert "0.01" in out


def test_render_tradeoffs_table_respects_k_limit() -> None:
    """When K < |frontier|, only K candidates appear in the body rows."""
    from cli.commands.optimize import render_tradeoffs_table
    from optimizer.pareto import (
        ConstrainedParetoArchive,
        ObjectiveDirection,
        ObjectiveName,
    )

    archive = ConstrainedParetoArchive(
        objective_directions={
            ObjectiveName.QUALITY.value: ObjectiveDirection.MAXIMIZE,
            ObjectiveName.SAFETY.value: ObjectiveDirection.MAXIMIZE,
            ObjectiveName.COST.value: ObjectiveDirection.MINIMIZE,
        }
    )
    # All four are pairwise non-dominated (strict tradeoffs on cost vs quality).
    for cid, q, s, c in [
        ("cand_A", 0.9, 0.7, 0.10),
        ("cand_B", 0.8, 0.7, 0.05),
        ("cand_C", 0.7, 0.7, 0.02),
        ("cand_D", 0.6, 0.7, 0.01),
    ]:
        archive.add_candidate(
            candidate_id=cid,
            objectives={"quality": q, "safety": s, "cost": c},
            constraints_passed=True,
        )
    out = render_tradeoffs_table(archive, k=2)
    # Exactly 2 body rows (and no fifth candidate line).
    cand_lines = [ln for ln in out.splitlines() if ln.startswith("cand_")]
    assert len(cand_lines) == 2


def test_render_tradeoffs_table_empty_archive() -> None:
    """An archive with no feasible candidates should not crash."""
    from cli.commands.optimize import render_tradeoffs_table
    from optimizer.pareto import (
        ConstrainedParetoArchive,
        ObjectiveDirection,
        ObjectiveName,
    )

    archive = ConstrainedParetoArchive(
        objective_directions={
            ObjectiveName.QUALITY.value: ObjectiveDirection.MAXIMIZE,
            ObjectiveName.SAFETY.value: ObjectiveDirection.MAXIMIZE,
            ObjectiveName.COST.value: ObjectiveDirection.MINIMIZE,
        }
    )
    out = render_tradeoffs_table(archive, k=5)
    assert "No Pareto candidates" in out or "no tradeoff" in out.lower()


# ---------------------------------------------------------------------------
# 4. Golden help text — ``optimize --help`` must advertise --show-tradeoffs
# ---------------------------------------------------------------------------


def _clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTLAB_")}
    env.setdefault("NO_COLOR", "1")
    env.setdefault("TERM", "dumb")
    env.setdefault("COLUMNS", "80")
    return env


def test_optimize_help_lists_show_tradeoffs_flag() -> None:
    """Smoke-test the CLI: ``--show-tradeoffs`` must appear in help."""
    result = subprocess.run(
        ["uv", "run", "--quiet", "agentlab", "optimize", "--help"],
        capture_output=True,
        text=True,
        env=_clean_env(),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--show-tradeoffs" in result.stdout


def test_optimize_help_matches_updated_golden() -> None:
    """The optimize --help golden must be regenerated to include the new flag."""
    golden = Path(__file__).parent / "golden" / "optimize_help.txt"
    assert golden.exists()
    content = golden.read_text()
    assert "--show-tradeoffs" in content, (
        "Golden tests/golden/optimize_help.txt must advertise --show-tradeoffs."
    )
