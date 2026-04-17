"""Tests for optimizer.calibration.CalibrationStore."""

from __future__ import annotations

import sqlite3
import time

import pytest

from optimizer.calibration import CalibrationStore


def test_calibration_factor_sparse_returns_none(tmp_path) -> None:
    db_path = str(tmp_path / "cal.db")
    store = CalibrationStore(db_path=db_path)

    for i in range(5):
        store.record(
            attempt_id=f"a{i}",
            surface="planner",
            strategy="tighten",
            predicted_effectiveness=0.1,
            actual_delta=0.05,
            recorded_at=1000.0 + i,
        )

    assert store.factor(surface="planner", strategy="tighten", n=20) is None


def test_calibration_factor_last_n_mean(tmp_path) -> None:
    db_path = str(tmp_path / "cal.db")
    store = CalibrationStore(db_path=db_path)

    # 25 rows. Deltas-minus-predictions span [-0.1, +0.1].
    # Make predicted=0 so actual_delta IS the diff, for clarity.
    values = [round(-0.1 + (0.2 * i / 24), 6) for i in range(25)]
    for i, v in enumerate(values):
        store.record(
            attempt_id=f"a{i}",
            surface="planner",
            strategy="tighten",
            predicted_effectiveness=0.0,
            actual_delta=v,
            recorded_at=1000.0 + i,  # monotonic, so newest = highest i
        )

    # The most recent 20 are the last 20 in insertion order.
    last20 = values[-20:]
    expected = sum(last20) / len(last20)

    factor = store.factor(surface="planner", strategy="tighten", n=20)
    assert factor is not None
    assert factor == pytest.approx(expected, abs=1e-9)


def test_calibration_record_persists(tmp_path) -> None:
    db_path = str(tmp_path / "cal.db")
    store = CalibrationStore(db_path=db_path)

    row_id = store.record(
        attempt_id="attempt-xyz",
        surface="router",
        strategy="rewrite",
        predicted_effectiveness=0.37,
        actual_delta=-0.12,
        recorded_at=1234567.5,
    )
    assert isinstance(row_id, int) and row_id > 0

    # Reopen — should hit the same file.
    store2 = CalibrationStore(db_path=db_path)
    assert store2 is not None

    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT attempt_id, surface, strategy, predicted_effectiveness, "
            "actual_delta, recorded_at FROM predicted_vs_actual WHERE id = ?",
            (row_id,),
        )
        row = cur.fetchone()

    assert row == ("attempt-xyz", "router", "rewrite", 0.37, -0.12, 1234567.5)


def test_calibration_keys_by_surface_strategy(tmp_path) -> None:
    db_path = str(tmp_path / "cal.db")
    store = CalibrationStore(db_path=db_path)

    # 25 rows on (planner, tighten) — all diff = +0.5
    for i in range(25):
        store.record(
            attempt_id=f"p{i}",
            surface="planner",
            strategy="tighten",
            predicted_effectiveness=0.0,
            actual_delta=0.5,
            recorded_at=1000.0 + i,
        )

    # 25 rows on (router, rewrite) — all diff = -0.3
    for i in range(25):
        store.record(
            attempt_id=f"r{i}",
            surface="router",
            strategy="rewrite",
            predicted_effectiveness=0.0,
            actual_delta=-0.3,
            recorded_at=2000.0 + i,
        )

    # A handful of noise across other keys
    for i in range(3):
        store.record(
            attempt_id=f"x{i}",
            surface="other",
            strategy="noop",
            predicted_effectiveness=0.0,
            actual_delta=99.0,
            recorded_at=3000.0 + i,
        )

    planner = store.factor(surface="planner", strategy="tighten", n=20)
    router = store.factor(surface="router", strategy="rewrite", n=20)

    assert planner == pytest.approx(0.5, abs=1e-9)
    assert router == pytest.approx(-0.3, abs=1e-9)


def test_calibration_record_default_recorded_at(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "cal.db")
    store = CalibrationStore(db_path=db_path)

    fixed = 424242.125
    monkeypatch.setattr(
        "optimizer.calibration.time.time", lambda: fixed, raising=True
    )

    row_id = store.record(
        attempt_id="a1",
        surface="planner",
        strategy="tighten",
        predicted_effectiveness=0.1,
        actual_delta=0.2,
    )

    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "SELECT recorded_at FROM predicted_vs_actual WHERE id = ?", (row_id,)
        )
        (recorded_at,) = cur.fetchone()

    assert recorded_at == pytest.approx(fixed, abs=1e-9)


def test_calibration_creates_parent_dir(tmp_path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "cal.db"
    assert not nested.parent.exists()

    store = CalibrationStore(db_path=str(nested))
    assert nested.parent.exists() and nested.parent.is_dir()

    # Smoke-test: the store is functional.
    row_id = store.record(
        attempt_id="a1",
        surface="planner",
        strategy="tighten",
        predicted_effectiveness=0.1,
        actual_delta=0.2,
        recorded_at=1.0,
    )
    assert row_id > 0
