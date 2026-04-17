"""Tests for R6.B.2a: predicted_effectiveness / strategy_surface columns on
the optimizer ``attempts`` table.

Covers schema creation, idempotent migration of pre-R6 databases, legacy row
compatibility, and round-tripping the new fields through ``log`` / ``recent``
/ ``accepted`` / ``get_all``.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from optimizer.memory import OptimizationAttempt, OptimizationMemory


PRE_R6_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    change_description TEXT NOT NULL,
    config_diff TEXT NOT NULL,
    config_section TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    score_before REAL DEFAULT 0.0,
    score_after REAL DEFAULT 0.0,
    significance_p_value REAL DEFAULT 1.0,
    significance_delta REAL DEFAULT 0.0,
    significance_n INTEGER DEFAULT 0,
    health_context TEXT DEFAULT '',
    skills_applied TEXT DEFAULT '',
    patch_bundle TEXT DEFAULT ''
)
"""


def _column_info(db_path: str) -> dict[str, str]:
    """Return {column_name: declared_type} for the attempts table."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("PRAGMA table_info(attempts)").fetchall()
    return {row[1]: row[2] for row in rows}


def test_memory_schema_adds_calibration_columns(tmp_path) -> None:
    db_path = str(tmp_path / "mem.db")
    OptimizationMemory(db_path=db_path)

    cols = _column_info(db_path)
    assert "predicted_effectiveness" in cols
    assert "strategy_surface" in cols
    # Types should be the SQLite type affinities we declared.
    assert cols["predicted_effectiveness"].upper() == "REAL"
    assert cols["strategy_surface"].upper() == "TEXT"


def test_memory_migration_idempotent(tmp_path) -> None:
    db_path = str(tmp_path / "legacy.db")

    # Build an old-shape DB with only the pre-R6 columns.
    with sqlite3.connect(db_path) as conn:
        conn.execute(PRE_R6_CREATE_TABLE)
        conn.commit()

    # First open: migration should add the new columns.
    OptimizationMemory(db_path=db_path)
    cols_first = _column_info(db_path)
    assert "predicted_effectiveness" in cols_first
    assert "strategy_surface" in cols_first

    # Second open: must not raise and must not duplicate columns.
    OptimizationMemory(db_path=db_path)
    cols_second = _column_info(db_path)
    assert cols_first == cols_second
    # Sanity: no duplicated columns.
    assert len(cols_second) == len(set(cols_second.keys()))


def test_memory_legacy_row_loads_with_null_fields(tmp_path) -> None:
    db_path = str(tmp_path / "legacy_row.db")

    # Create the pre-R6 shape and insert a row that does NOT specify the new
    # R6 columns.
    with sqlite3.connect(db_path) as conn:
        conn.execute(PRE_R6_CREATE_TABLE)
        conn.execute(
            """
            INSERT INTO attempts (
                attempt_id, timestamp, change_description, config_diff,
                config_section, status, score_before, score_after,
                significance_p_value, significance_delta, significance_n,
                health_context, skills_applied, patch_bundle
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-1",
                time.time(),
                "legacy change",
                "{}",
                "system_prompt",
                "accepted",
                0.5,
                0.6,
                0.04,
                0.1,
                5,
                "{}",
                "[]",
                "{}",
            ),
        )
        conn.commit()

    mem = OptimizationMemory(db_path=db_path)
    latest = mem.recent(1)
    assert len(latest) == 1
    attempt = latest[0]
    assert attempt.attempt_id == "legacy-1"
    assert attempt.predicted_effectiveness is None
    assert attempt.strategy_surface is None


def test_memory_log_and_recent_roundtrips_new_fields(tmp_path) -> None:
    db_path = str(tmp_path / "roundtrip.db")
    mem = OptimizationMemory(db_path=db_path)

    attempt = OptimizationAttempt(
        attempt_id="rt-1",
        timestamp=time.time(),
        change_description="try new prompt",
        config_diff="{}",
        status="accepted",
        config_section="system_prompt",
        score_before=0.5,
        score_after=0.7,
        predicted_effectiveness=0.62,
        strategy_surface="system_prompt",
    )
    mem.log(attempt)

    latest = mem.recent(1)
    assert len(latest) == 1
    assert latest[0].predicted_effectiveness == pytest.approx(0.62)
    assert latest[0].strategy_surface == "system_prompt"


def test_memory_log_defaults_new_fields_to_none(tmp_path) -> None:
    db_path = str(tmp_path / "defaults.db")
    mem = OptimizationMemory(db_path=db_path)

    attempt = OptimizationAttempt(
        attempt_id="def-1",
        timestamp=time.time(),
        change_description="no new kwargs",
        config_diff="{}",
        status="rejected_no_improvement",
    )
    mem.log(attempt)

    latest = mem.recent(1)
    assert len(latest) == 1
    assert latest[0].predicted_effectiveness is None
    assert latest[0].strategy_surface is None


def test_memory_get_all_and_accepted_include_new_fields(tmp_path) -> None:
    db_path = str(tmp_path / "acc.db")
    mem = OptimizationMemory(db_path=db_path)

    attempt = OptimizationAttempt(
        attempt_id="acc-1",
        timestamp=time.time(),
        change_description="accepted one",
        config_diff="{}",
        status="accepted",
        config_section="tools",
        predicted_effectiveness=0.81,
        strategy_surface="tools",
    )
    mem.log(attempt)

    all_rows = mem.get_all()
    assert len(all_rows) == 1
    assert all_rows[0].predicted_effectiveness == pytest.approx(0.81)
    assert all_rows[0].strategy_surface == "tools"

    accepted = mem.accepted()
    assert len(accepted) == 1
    assert accepted[0].predicted_effectiveness == pytest.approx(0.81)
    assert accepted[0].strategy_surface == "tools"
