"""Tests for ``/attempt-diff`` — multi-pane lineage-backed attempt viewer (R4.10).

Distinct from :mod:`cli.workbench_app.config_diff_slash`, which registers
``/diff`` for active-vs-candidate *version* diffs. This module covers the
attempt-id lineage inspection command that renders baseline / candidate YAML
plus an eval-delta summary sourced from :class:`ImprovementLineageStore`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.workbench_app.attempt_diff_slash import (
    _handle_attempt_diff,
    build_attempt_diff_command,
)
from cli.workbench_app.slash import SlashContext, build_builtin_registry
from optimizer.improvement_lineage import ImprovementLineageStore


ATTEMPT_ID = "att_123"
BASELINE_YAML = "model: gemini-2.5-flash\nrouting:\n  rules: []\n"
CANDIDATE_YAML = "model: gemini-2.5-pro\nrouting:\n  rules:\n    - fast-path\n"


@pytest.fixture
def baseline_path(tmp_path: Path) -> Path:
    p = tmp_path / "baseline.yaml"
    p.write_text(BASELINE_YAML, encoding="utf-8")
    return p


@pytest.fixture
def candidate_path(tmp_path: Path) -> Path:
    p = tmp_path / "candidate.yaml"
    p.write_text(CANDIDATE_YAML, encoding="utf-8")
    return p


@pytest.fixture
def store_with_measurement(
    tmp_path: Path, baseline_path: Path, candidate_path: Path
) -> ImprovementLineageStore:
    store = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))
    store.record_eval_run(
        eval_run_id="run-baseline",
        attempt_id=ATTEMPT_ID,
        config_path=str(baseline_path),
        composite_score=0.70,
    )
    store.record_attempt(
        attempt_id=ATTEMPT_ID,
        status="accepted",
        score_before=0.70,
        score_after=0.82,
        eval_run_id="run-baseline",
        baseline_config_path=str(baseline_path),
        candidate_config_path=str(candidate_path),
    )
    store.record_measurement(
        attempt_id=ATTEMPT_ID,
        measurement_id="m-1",
        composite_delta=0.12,
        eval_run_id="run-after",
    )
    return store


@pytest.fixture
def store_without_measurement(
    tmp_path: Path, baseline_path: Path, candidate_path: Path
) -> ImprovementLineageStore:
    store = ImprovementLineageStore(db_path=str(tmp_path / "lineage_no_m.db"))
    store.record_attempt(
        attempt_id=ATTEMPT_ID,
        status="proposed",
        baseline_config_path=str(baseline_path),
        candidate_config_path=str(candidate_path),
    )
    return store


def _ctx(store: ImprovementLineageStore) -> SlashContext:
    return SlashContext(meta={"lineage_store": store})


# ---------------------------------------------------------------------------
# Metadata.
# ---------------------------------------------------------------------------


def test_build_attempt_diff_command_metadata() -> None:
    cmd = build_attempt_diff_command()
    # Must NOT collide with existing `/diff` from config_diff_slash.
    assert cmd.name == "attempt-diff"
    assert cmd.sensitive is False
    assert cmd.source == "builtin"


# ---------------------------------------------------------------------------
# Happy path — three panes with eval delta.
# ---------------------------------------------------------------------------


def test_handler_renders_three_panes_with_delta(
    store_with_measurement: ImprovementLineageStore,
    baseline_path: Path,
    candidate_path: Path,
) -> None:
    ctx = _ctx(store_with_measurement)
    result = _handle_attempt_diff(ctx, ATTEMPT_ID)
    text = result.result or ""

    # Paths present.
    assert str(baseline_path) in text
    assert str(candidate_path) in text

    # YAML snippets surfaced.
    assert "gemini-2.5-flash" in text
    assert "gemini-2.5-pro" in text

    # Eval delta pane: before, after, signed delta.
    assert "0.700" in text
    assert "0.820" in text
    assert "+0.120" in text

    # Pane headers.
    assert "Baseline" in text
    assert "Candidate" in text
    assert "Eval Delta" in text


# ---------------------------------------------------------------------------
# No measurement recorded.
# ---------------------------------------------------------------------------


def test_handler_notes_missing_measurement(
    store_without_measurement: ImprovementLineageStore,
) -> None:
    ctx = _ctx(store_without_measurement)
    result = _handle_attempt_diff(ctx, ATTEMPT_ID)
    text = result.result or ""
    assert "no measurement recorded" in text


# ---------------------------------------------------------------------------
# Unknown attempt id — return error markup, do NOT raise.
# ---------------------------------------------------------------------------


def test_handler_reports_unknown_attempt(
    store_with_measurement: ImprovementLineageStore,
) -> None:
    ctx = _ctx(store_with_measurement)
    result = _handle_attempt_diff(ctx, "att_does_not_exist")
    text = result.result or ""
    assert "Unknown attempt" in text
    assert "att_does_not_exist" in text


# ---------------------------------------------------------------------------
# No arg supplied — usage error, no raise.
# ---------------------------------------------------------------------------


def test_handler_requires_attempt_id(
    store_with_measurement: ImprovementLineageStore,
) -> None:
    ctx = _ctx(store_with_measurement)
    result = _handle_attempt_diff(ctx)
    text = result.result or ""
    assert "Usage" in text or "attempt_id" in text


# ---------------------------------------------------------------------------
# Registry smoke test — name does not collide with `/diff`.
# ---------------------------------------------------------------------------


def test_registry_has_attempt_diff_without_colliding_with_diff() -> None:
    registry = build_builtin_registry()
    attempt_diff = registry.get("attempt-diff")
    config_diff = registry.get("diff")

    assert attempt_diff is not None, "/attempt-diff must be registered"
    assert config_diff is not None, "/diff (config_diff_slash) must stay registered"
    assert attempt_diff is not config_diff
    assert attempt_diff.name == "attempt-diff"
    assert config_diff.name == "diff"
