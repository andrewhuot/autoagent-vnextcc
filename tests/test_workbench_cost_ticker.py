"""R4.9 / C3 — cost ticker surfaces in the Workbench status bar.

These tests pin three invariants:

1. ``WorkbenchSession.cost_ticker_usd`` is the single sink that accumulates
   every USD cost — conversation turns and slash-command LLM calls alike.
   ``session.increment_cost(...)`` is the only mutator the status bar reads.
2. ``StatusSnapshot.cost_usd`` mirrors the session's ticker so the bar can
   render it without re-computing pricing.
3. The rendered line includes a ``Cost: $X.XX`` segment formatted the way
   the rest of the bar formats numbers (two decimals for dollars >= $10,
   four decimals for fractional amounts so a 0.01 increment is legible).

The tests never touch the pricing table in ``cost_calculator.py`` — they
exercise the calculator through ``record_slash_cost`` only. If you change
the invariant, update this test and the commit message so the next reader
sees the provenance.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.workbench_app.cost_calculator import compute_turn_cost, record_slash_cost
from cli.workbench_app.session_state import WorkbenchSession
from cli.workbench_app.status_bar import (
    StatusBar,
    StatusSnapshot,
    render_snapshot,
    snapshot_from_workspace,
)


SONNET = "claude-sonnet-4-5"  # input 3.0 / output 15.0 per 1M — matches cost_calculator tests


# ---------------------------------------------------------------------------
# core invariant: three increments sum on the snapshot
# ---------------------------------------------------------------------------


def test_three_increments_reflected_in_snapshot() -> None:
    """Feeding three known costs into the single sink sums on the snapshot."""
    session = WorkbenchSession()
    session.increment_cost(0.01)
    session.increment_cost(0.03)
    session.increment_cost(0.05)

    assert session.cost_ticker_usd == pytest.approx(0.09, abs=1e-9)

    snap = snapshot_from_workspace(None, workbench_session=session)
    assert snap.cost_usd == pytest.approx(0.09, abs=1e-9)


def test_rendered_bar_contains_dollar_amount() -> None:
    """The rendered status line should expose the dollar amount to the user."""
    session = WorkbenchSession()
    session.increment_cost(0.01)
    session.increment_cost(0.03)
    session.increment_cost(0.05)

    snap = snapshot_from_workspace(None, workbench_session=session)
    rendered = render_snapshot(snap, color=False)
    assert "$0.09" in rendered or "$0.0900" in rendered


def test_status_bar_refresh_from_workspace_includes_cost(tmp_path: Path) -> None:
    """``StatusBar.refresh_from_workspace`` must propagate the ticker."""
    session = WorkbenchSession()
    session.increment_cost(0.42)

    bar = StatusBar()
    snap = bar.refresh_from_workspace(None, workbench_session=session)
    assert snap.cost_usd == pytest.approx(0.42, abs=1e-9)
    assert "$0.42" in bar.render(color=False)


def test_zero_cost_not_rendered() -> None:
    """A zero ticker should not clutter the bar — matches ``best_score=None``."""
    snap = StatusSnapshot(workspace_label="demo", cost_usd=0.0)
    rendered = render_snapshot(snap, color=False)
    assert "$" not in rendered
    assert "Cost" not in rendered


def test_large_cost_uses_two_decimals() -> None:
    """>= $10 renders with two decimals; fractions keep four for legibility."""
    snap = StatusSnapshot(workspace_label="demo", cost_usd=12.3456)
    rendered = render_snapshot(snap, color=False)
    assert "$12.35" in rendered  # rounded to 2 dp

    snap_small = StatusSnapshot(workspace_label="demo", cost_usd=0.0012)
    rendered_small = render_snapshot(snap_small, color=False)
    assert "$0.0012" in rendered_small


# ---------------------------------------------------------------------------
# single-sink invariant: compute_turn_cost -> increment_cost
# ---------------------------------------------------------------------------


def test_simulated_turn_costs_accumulate_through_single_sink() -> None:
    """Three simulated ``compute_turn_cost`` events flow through ``increment_cost``.

    This proves the sink invariant: a helper that records the calculator's
    output calls ``session.increment_cost`` (no shadow bookkeeping) and the
    running total matches the sum of the individual deltas.
    """
    session = WorkbenchSession()
    usages = [
        {"input_tokens": 1000, "output_tokens": 500},   # 0.0105
        {"input_tokens": 2000, "output_tokens": 0},     # 0.006
        {"input_tokens": 0, "output_tokens": 1000},     # 0.015
    ]
    expected_sum = sum(compute_turn_cost(u, SONNET) for u in usages)
    assert expected_sum == pytest.approx(0.0315, abs=1e-9)

    for usage in usages:
        record_slash_cost(session, usage=usage, model_id=SONNET)

    assert session.cost_ticker_usd == pytest.approx(expected_sum, abs=1e-9)


# ---------------------------------------------------------------------------
# record_slash_cost helper: behavior on edge inputs
# ---------------------------------------------------------------------------


def test_record_slash_cost_zero_cost_does_not_touch_ticker() -> None:
    """Unknown model => 0.0 delta => session untouched (and must not raise)."""
    session = WorkbenchSession()
    session.increment_cost(0.25)  # seed

    record_slash_cost(session, usage={"input_tokens": 1000}, model_id="no-such-model")
    record_slash_cost(session, usage=None, model_id=SONNET)
    record_slash_cost(session, usage={"input_tokens": 1000}, model_id=None)

    assert session.cost_ticker_usd == pytest.approx(0.25, abs=1e-9)


def test_record_slash_cost_returns_applied_delta() -> None:
    """Callers may want to log the delta; the helper returns it."""
    session = WorkbenchSession()
    delta = record_slash_cost(
        session,
        usage={"input_tokens": 1000, "output_tokens": 500},
        model_id=SONNET,
    )
    assert delta == pytest.approx(0.0105, abs=1e-9)
    assert session.cost_ticker_usd == pytest.approx(0.0105, abs=1e-9)
