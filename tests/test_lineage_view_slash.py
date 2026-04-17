"""Tests for ``/lineage <id>`` — ancestry visualizer (R4.11).

Renders the full ancestry chain for any node id in the R2 improvement
lineage (eval_run, attempt, deployment, measurement). Accepts any node id
and resolves both forward and backward via the lineage store.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.workbench_app.lineage_view_slash import (
    _handle_lineage_view,
    build_lineage_view_command,
)
from cli.workbench_app.slash import SlashContext, build_builtin_registry
from optimizer.improvement_lineage import ImprovementLineageStore


EVAL_RUN_ID = "ev_abc"
ATTEMPT_ID = "att_123"
DEPLOYMENT_ID = "dep_456"
MEASUREMENT_ID = "meas_789"


@pytest.fixture
def seeded_store(tmp_path: Path) -> ImprovementLineageStore:
    """Seed a lineage store with eval_run → attempt → deployment/measurement."""
    store = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))
    store.record_eval_run(
        eval_run_id=EVAL_RUN_ID,
        attempt_id=ATTEMPT_ID,
        config_path="/tmp/baseline.yaml",
        composite_score=0.82,
    )
    store.record_attempt(
        attempt_id=ATTEMPT_ID,
        status="candidate",
        score_before=0.82,
        score_after=0.89,
        eval_run_id=EVAL_RUN_ID,
    )
    store.record_deployment(
        attempt_id=ATTEMPT_ID,
        deployment_id=DEPLOYMENT_ID,
        version=7,
        env="staging",
    )
    store.record_measurement(
        attempt_id=ATTEMPT_ID,
        measurement_id=MEASUREMENT_ID,
        composite_delta=0.07,
        eval_run_id="run-after",
    )
    return store


def _ctx(store: ImprovementLineageStore) -> SlashContext:
    return SlashContext(meta={"lineage_store": store})


# ---------------------------------------------------------------------------
# Metadata.
# ---------------------------------------------------------------------------


def test_build_lineage_view_command_metadata() -> None:
    cmd = build_lineage_view_command()
    assert cmd.name == "lineage"
    assert cmd.sensitive is False
    assert cmd.source == "builtin"


# ---------------------------------------------------------------------------
# Happy path — attempt id resolves full chain.
# ---------------------------------------------------------------------------


def test_handler_renders_chain_from_attempt_id(
    seeded_store: ImprovementLineageStore,
) -> None:
    ctx = _ctx(seeded_store)
    result = _handle_lineage_view(ctx, ATTEMPT_ID)
    text = result.result or ""

    assert EVAL_RUN_ID in text
    assert ATTEMPT_ID in text
    assert DEPLOYMENT_ID in text
    assert MEASUREMENT_ID in text

    # Highlighted node is the attempt id.
    assert f"[bold yellow]" in text
    # The attempt id line should be bold yellow.
    assert f"[bold yellow]" in text and ATTEMPT_ID in text


def test_handler_highlights_attempt_when_attempt_id_given(
    seeded_store: ImprovementLineageStore,
) -> None:
    ctx = _ctx(seeded_store)
    result = _handle_lineage_view(ctx, ATTEMPT_ID)
    text = result.result or ""
    # Highlight marker must enclose the attempt id.
    assert f"[bold yellow]" in text
    # The line containing attempt id must also contain the highlight marker.
    hit = [ln for ln in text.splitlines() if ATTEMPT_ID in ln]
    assert any("[bold yellow]" in ln for ln in hit), (
        f"Expected attempt line to be highlighted in: {text}"
    )


# ---------------------------------------------------------------------------
# Resolve from eval_run id.
# ---------------------------------------------------------------------------


def test_handler_renders_chain_from_eval_run_id(
    seeded_store: ImprovementLineageStore,
) -> None:
    ctx = _ctx(seeded_store)
    result = _handle_lineage_view(ctx, EVAL_RUN_ID)
    text = result.result or ""

    assert EVAL_RUN_ID in text
    assert ATTEMPT_ID in text
    assert DEPLOYMENT_ID in text
    assert MEASUREMENT_ID in text

    # eval_run_id line should be highlighted.
    hit = [ln for ln in text.splitlines() if EVAL_RUN_ID in ln]
    assert any("[bold yellow]" in ln for ln in hit)


# ---------------------------------------------------------------------------
# Resolve from deployment id.
# ---------------------------------------------------------------------------


def test_handler_renders_chain_from_deployment_id(
    seeded_store: ImprovementLineageStore,
) -> None:
    ctx = _ctx(seeded_store)
    result = _handle_lineage_view(ctx, DEPLOYMENT_ID)
    text = result.result or ""

    assert EVAL_RUN_ID in text
    assert ATTEMPT_ID in text
    assert DEPLOYMENT_ID in text
    assert MEASUREMENT_ID in text

    hit = [ln for ln in text.splitlines() if DEPLOYMENT_ID in ln]
    assert any("[bold yellow]" in ln for ln in hit)


# ---------------------------------------------------------------------------
# Resolve from measurement id.
# ---------------------------------------------------------------------------


def test_handler_renders_chain_from_measurement_id(
    seeded_store: ImprovementLineageStore,
) -> None:
    ctx = _ctx(seeded_store)
    result = _handle_lineage_view(ctx, MEASUREMENT_ID)
    text = result.result or ""

    assert EVAL_RUN_ID in text
    assert ATTEMPT_ID in text
    assert DEPLOYMENT_ID in text
    assert MEASUREMENT_ID in text

    hit = [ln for ln in text.splitlines() if MEASUREMENT_ID in ln]
    assert any("[bold yellow]" in ln for ln in hit)


# ---------------------------------------------------------------------------
# Unknown id — return error markup, do NOT raise.
# ---------------------------------------------------------------------------


def test_handler_reports_unknown_id(
    seeded_store: ImprovementLineageStore,
) -> None:
    ctx = _ctx(seeded_store)
    result = _handle_lineage_view(ctx, "not_a_real_id")
    text = result.result or ""
    assert "Unknown lineage id" in text
    assert "not_a_real_id" in text


# ---------------------------------------------------------------------------
# No arg supplied — usage message.
# ---------------------------------------------------------------------------


def test_handler_requires_id(
    seeded_store: ImprovementLineageStore,
) -> None:
    ctx = _ctx(seeded_store)
    result = _handle_lineage_view(ctx)
    text = result.result or ""
    assert "Usage" in text or "id" in text


# ---------------------------------------------------------------------------
# Registry smoke test.
# ---------------------------------------------------------------------------


def test_registry_has_lineage_command() -> None:
    registry = build_builtin_registry()
    cmd = registry.get("lineage")
    assert cmd is not None, "/lineage must be registered"
    assert cmd.name == "lineage"
