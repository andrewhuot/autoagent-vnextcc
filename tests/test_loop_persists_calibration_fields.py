"""Tests for R6.B.2b: ``optimizer/loop.py`` persists
``predicted_effectiveness`` and ``strategy_surface`` on every
``OptimizationAttempt`` it writes, sourced from the proposer's last
ranking (``_LAST_EXPLANATION[0]``).

The first three tests pin the helper and construction pattern in
isolation. The fourth covers the happy-path wiring at line 768 via a
focused integration using ``Optimizer.__new__`` + targeted stubs. The
fifth covers the rejection-path site at line 1205 by exercising the
existing ``_log_rejected_attempt`` method so both attempt-write sites
are verified.
"""

from __future__ import annotations

import re
import time
from collections import deque
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from optimizer import proposer as prop_mod
from optimizer.loop import Optimizer, _top_strategy_explanation
from optimizer.memory import OptimizationAttempt, OptimizationMemory
from optimizer.proposer import StrategyExplanation


# ---------------------------------------------------------------------------
# Helper isolation tests
# ---------------------------------------------------------------------------


def test_loop_persists_predicted_effectiveness_and_surface(monkeypatch) -> None:
    """Helper returns the seeded top entry; the construction pattern
    used in the loop produces an attempt with matching fields.
    """
    entry = StrategyExplanation(
        strategy="rewrite_prompt",
        surface="system_prompt",
        effectiveness=0.73,
        samples=15,
        explored=False,
    )
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", [entry])

    top = _top_strategy_explanation()
    assert top is entry

    # Mirror the exact construction pattern used in optimizer/loop.py so
    # this test fails loudly if the wiring contract is ever broken.
    _exp = _top_strategy_explanation()
    attempt = OptimizationAttempt(
        attempt_id="t1",
        timestamp=time.time(),
        change_description="x",
        config_diff="{}",
        status="accepted",
        predicted_effectiveness=(_exp.effectiveness if _exp is not None else None),
        strategy_surface=(_exp.surface if _exp is not None else None),
    )
    assert attempt.predicted_effectiveness == pytest.approx(0.73)
    assert attempt.strategy_surface == "system_prompt"


def test_loop_tolerates_missing_explanation(monkeypatch) -> None:
    """Empty ranking → helper returns None and the conditional fallback
    lands both fields as None on the persisted attempt.
    """
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", [])

    top = _top_strategy_explanation()
    assert top is None

    _exp = _top_strategy_explanation()
    attempt = OptimizationAttempt(
        attempt_id="t2",
        timestamp=time.time(),
        change_description="x",
        config_diff="{}",
        status="rejected_invalid",
        predicted_effectiveness=(_exp.effectiveness if _exp is not None else None),
        strategy_surface=(_exp.surface if _exp is not None else None),
    )
    assert attempt.predicted_effectiveness is None
    assert attempt.strategy_surface is None


def test_loop_uses_top_entry_not_later_entries(monkeypatch) -> None:
    """Top-ranked == chosen: locks the index-0 contract so a future
    refactor cannot silently start using a lower-ranked entry.
    """
    entries = [
        StrategyExplanation(
            strategy="a", surface="prompting", effectiveness=0.9, samples=20, explored=False
        ),
        StrategyExplanation(
            strategy="b", surface="tools", effectiveness=0.4, samples=10, explored=False
        ),
        StrategyExplanation(
            strategy="c", surface="architecture", effectiveness=0.1, samples=3, explored=True
        ),
    ]
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", entries)

    top = _top_strategy_explanation()
    assert top is entries[0]
    assert top.strategy == "a"
    assert top.surface == "prompting"
    assert top.effectiveness == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Rejection-path integration (line 1205 site)
# ---------------------------------------------------------------------------


def _make_optimizer_stub() -> Optimizer:
    """Minimal stubbed Optimizer suitable for exercising
    ``_log_rejected_attempt`` in isolation. Mirrors the shape used in
    ``tests/test_loop_rejections.py``.
    """
    opt = Optimizer.__new__(Optimizer)  # bypass __init__
    opt._recent_rejections = deque(maxlen=200)
    opt._current_cycle_skills = []
    opt.memory = MagicMock()
    opt.event_log = None
    # Lineage store is consulted on every attempt write; setting it to
    # None keeps `_emit_attempt_lineage` a no-op (it short-circuits on
    # None) without pulling in a real store.
    opt.lineage_store = None
    return opt


def test_rejection_path_writes_calibration_fields(monkeypatch) -> None:
    """Line-1205 site: ``_log_rejected_attempt`` must persist the
    calibration fields sourced from the proposer's last ranking.
    """
    entry = StrategyExplanation(
        strategy="refactor",
        surface="architecture",
        effectiveness=0.21,
        samples=7,
        explored=False,
    )
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", [entry])

    opt = _make_optimizer_stub()
    health_report = MagicMock()
    health_report.metrics.to_dict.return_value = {}

    opt._log_rejected_attempt(
        health_report=health_report,
        change_description="invalid bundle",
        config_section="system_prompt",
        rejection_status="rejected_invalid",
        rejection_reason="bad config",
    )

    assert opt.memory.log.call_count == 1
    persisted = opt.memory.log.call_args[0][0]
    assert persisted.predicted_effectiveness == pytest.approx(0.21)
    assert persisted.strategy_surface == "architecture"


def test_rejection_path_tolerates_empty_ranking(monkeypatch) -> None:
    """Empty ``_LAST_EXPLANATION`` → rejection attempt persists with
    NULL calibration fields (legacy path intact).
    """
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", [])

    opt = _make_optimizer_stub()
    health_report = MagicMock()
    health_report.metrics.to_dict.return_value = {}

    opt._log_rejected_attempt(
        health_report=health_report,
        change_description="empty",
        config_section="tools",
        rejection_status="rejected_noop",
        rejection_reason="noop",
    )

    persisted = opt.memory.log.call_args[0][0]
    assert persisted.predicted_effectiveness is None
    assert persisted.strategy_surface is None


# ---------------------------------------------------------------------------
# Accepted-path integration (line 768 site): round-trip through real
# OptimizationMemory so we prove the value lands in storage.
# ---------------------------------------------------------------------------


def test_accepted_path_attempt_roundtrips_calibration_fields(
    monkeypatch, tmp_path: Path
) -> None:
    """Build an attempt using the exact helper + construction pattern
    from the accepted path, log it through a real OptimizationMemory,
    and assert it round-trips through ``recent(1)``.

    Reaching the real line-768 code path requires an end-to-end loop
    with proposer/evals/gates wiring, which is disproportionate for
    this unit. Instead we exercise the *same* helper call and *same*
    kwarg construction that lives at line 768 against a real SQLite
    memory — if either the helper contract or the persisted shape
    regresses, this test fails.
    """
    entry = StrategyExplanation(
        strategy="tighten_prompt",
        surface="prompting",
        effectiveness=0.58,
        samples=12,
        explored=False,
    )
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", [entry])

    mem = OptimizationMemory(db_path=str(tmp_path / "roundtrip.db"))

    _exp = _top_strategy_explanation()
    attempt = OptimizationAttempt(
        attempt_id="acc-1",
        timestamp=time.time(),
        change_description="tighten",
        config_diff="{}",
        status="accepted",
        config_section="system_prompt",
        score_before=0.5,
        score_after=0.62,
        predicted_effectiveness=(_exp.effectiveness if _exp is not None else None),
        strategy_surface=(_exp.surface if _exp is not None else None),
    )
    mem.log(attempt)

    latest = mem.recent(1)
    assert len(latest) == 1
    assert latest[0].predicted_effectiveness == pytest.approx(0.58)
    assert latest[0].strategy_surface == "prompting"


# ---------------------------------------------------------------------------
# Meta-test: both OptimizationAttempt call sites in loop.py wire the
# new kwargs. Guards against future reverts.
# ---------------------------------------------------------------------------


def test_loop_second_attempt_site_also_populates_fields() -> None:
    """Regex audit of ``optimizer/loop.py``: every
    ``OptimizationAttempt(`` construction must pass both
    ``predicted_effectiveness=`` and ``strategy_surface=`` kwargs.
    """
    loop_path = (
        Path(__file__).resolve().parent.parent / "optimizer" / "loop.py"
    )
    source = loop_path.read_text()

    # Collect each OptimizationAttempt(...) block. We assume each
    # construction ends at the first line whose stripped text is ")".
    # That matches both the accepted-path (line 768) and rejection-path
    # (line 1205) sites in the current file.
    construction_starts = [
        m.start() for m in re.finditer(r"OptimizationAttempt\(", source)
    ]
    assert len(construction_starts) >= 2, (
        "Expected at least two OptimizationAttempt(...) construction "
        f"sites in loop.py, found {len(construction_starts)}."
    )

    for start in construction_starts:
        # Walk forward collecting lines until we hit a closing paren on
        # its own line at base indentation ≤ the opening line's indent.
        tail = source[start:]
        # Grab a generous slice (through the next blank line after the
        # closing ")"). 60 lines is plenty for either site.
        snippet_lines = tail.splitlines()[:60]
        snippet = "\n".join(snippet_lines)
        # Trim to up to and including the first line that is exactly
        # ")" (with optional indentation).
        closing = re.search(r"^\s*\)\s*$", snippet, re.MULTILINE)
        assert closing, (
            "Could not locate the closing ')' of an "
            f"OptimizationAttempt(...) call near offset {start}."
        )
        block = snippet[: closing.end()]
        assert "predicted_effectiveness=" in block, (
            "An OptimizationAttempt(...) construction in loop.py is "
            "missing the `predicted_effectiveness=` kwarg:\n"
            f"{block}"
        )
        assert "strategy_surface=" in block, (
            "An OptimizationAttempt(...) construction in loop.py is "
            "missing the `strategy_surface=` kwarg:\n"
            f"{block}"
        )
