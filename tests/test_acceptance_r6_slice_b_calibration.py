"""R6 Slice B acceptance — calibration data round-trip.

Seam-check across B.1..B.6: every individual unit test passed, but does
the wiring between them actually carry data through the system? This
test exercises the **measure → calibration → explain** path with as
much real machinery as possible.

Real:
  * ``optimizer.memory.OptimizationMemory`` (write + read).
  * ``cli.commands.improve.run_improve_measure_in_process`` (whole
    function body, including ``_find_unique_attempt`` against a real
    memory DB and ``_maybe_record_calibration`` against a real
    CalibrationStore).
  * ``optimizer.calibration.CalibrationStore`` (write + factor compute).
  * ``cli.commands.optimize._explanation_with_calibration`` and the
    underlying ``optimizer.proposer.format_strategy_explanation``.
  * ``optimizer.canary_scoring.LocalCanaryRouter`` and
    ``CanaryScoringAggregator`` with the default heuristic-only judge
    (smoke test).

Stubbed (cheap, well-understood boundaries):
  * ``cli.commands.improve._run_post_deploy_eval`` — would otherwise
    spin up a real eval runner.
  * ``ImprovementLineageStore.view_attempt`` — returns a fake
    ``deployment_id`` so the measure path proceeds.
  * ``ImprovementLineageStore.record_measurement`` — no-op (we only
    care about what flows into CalibrationStore).
  * ``optimizer.proposer._LAST_EXPLANATION`` — seeded directly so we
    don't have to run the proposer.

Pre-existing failures (``agent_card``, ``fastapi``,
``test_loop_rejections.py`` lineage_store, ``test_cli_help_golden.py``)
are out of scope.
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from cli.commands.improve import run_improve_measure_in_process
from cli.commands.optimize import _explanation_with_calibration
from optimizer import proposer as prop_mod
from optimizer.calibration import CalibrationStore
from optimizer.canary_scoring import (
    CanaryScoringAggregator,
    CanaryVerdict,
    LocalCanaryRouter,
)
from optimizer.memory import OptimizationAttempt, OptimizationMemory
from optimizer.proposer import StrategyExplanation


# ---------------------------------------------------------------------------
# Test 1: calibration round-trip — the headline acceptance test.
# ---------------------------------------------------------------------------


def test_slice_b_calibration_roundtrip(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """End-to-end: 20 attempts → measure each → factor materializes →
    --explain-strategy shows it.

    The story:
      1. Workspace is wired to tmp_path-scoped DBs via env vars.
      2. 20 attempts are persisted via the real OptimizationMemory for a
         single (surface, strategy) pair.
      3. For each attempt, ``run_improve_measure_in_process`` is invoked.
         The lineage view is stubbed to return a deployed view; the
         post-deploy eval is stubbed to return a fixed composite. Every
         other piece of the measure code path is real, including the
         CalibrationStore write.
      4. After all 20 measurements, the CalibrationStore yields a real
         ``factor()`` for the (surface, strategy) pair.
      5. The read side — ``_explanation_with_calibration`` — picks up
         the same factor via the env var and renders the calibrated
         clause.

    Wiring bugs this catches (none expected at green; called out for
    failure-mode clarity):
      * Mismatched DB-path env-var name between writer and reader.
      * Mismatched key ordering in CalibrationStore.record vs. .factor.
      * Sign convention drift between residual storage and rendering.
    """
    # ---- Step 1: workspace setup ----
    memory_db = tmp_path / "optimizer_memory.db"
    lineage_db = tmp_path / "improvement_lineage.db"
    cal_db = tmp_path / "calibration.db"
    monkeypatch.setenv("AGENTLAB_MEMORY_DB", str(memory_db))
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(lineage_db))
    monkeypatch.setenv("AGENTLAB_CALIBRATION_DB", str(cal_db))

    # ---- Step 2: seed 20 attempts via the real OptimizationMemory ----
    surface = "system_prompt"
    strategy = "rewrite_prompt"
    predicted = 0.65
    score_before = 0.50

    memory = OptimizationMemory(db_path=str(memory_db))
    attempt_ids: list[str] = []
    base_ts = time.time()
    for i in range(20):
        # 8-hex-char prefix style mirrors how production attempt_ids look.
        aid = f"acc{i:05d}xyz"
        attempt_ids.append(aid)
        memory.log(OptimizationAttempt(
            attempt_id=aid,
            timestamp=base_ts + i,
            change_description=f"acceptance attempt {i}",
            config_diff="{}",
            status="accepted",
            config_section=surface,
            score_before=score_before,
            score_after=score_before + 0.08,
            predicted_effectiveness=predicted,
            strategy_surface=surface,
            strategy_name=strategy,
        ))

    # ---- Step 3a: stub the lineage view ----
    # The measure path requires a non-None deployment_id and calls
    # record_measurement after the eval — both are stubbed here so we
    # keep the focus on the calibration data path.
    from optimizer.improvement_lineage import ImprovementLineageStore

    monkeypatch.setattr(
        ImprovementLineageStore,
        "view_attempt",
        lambda self, aid: SimpleNamespace(deployment_id="dep-abc"),
    )
    monkeypatch.setattr(
        ImprovementLineageStore,
        "record_measurement",
        lambda self, **kw: None,
    )

    # ---- Step 3b: stub the post-deploy eval ----
    # Choice: 20 identical post-composites of 0.59 → composite_delta of
    # +0.09 → residual (actual - predicted) = 0.09 - 0.65 = -0.56.
    # Mean over 20 identical residuals is the same -0.56. Identical
    # values are the minimum-viable case; varied values would exercise
    # the same code path with a less-contrived factor but add no
    # additional coverage of the wiring under test.
    post_composite = 0.59
    monkeypatch.setattr(
        "cli.commands.improve._run_post_deploy_eval",
        lambda **kw: post_composite,
    )

    # ---- Step 4: invoke run_improve_measure_in_process for each attempt ----
    events: list[dict[str, Any]] = []
    for aid in attempt_ids:
        result = run_improve_measure_in_process(
            attempt_id=aid,
            on_event=events.append,
        )
        assert result.status == "ok", (
            f"measure failed for {aid}: result={result!r}"
        )

    # All 20 events should report calibration_recorded=True.
    completed = [e for e in events if e["event"] == "improve_measure_complete"]
    assert len(completed) == 20, (
        f"expected 20 measure_complete events; got {len(completed)}"
    )
    for e in completed:
        assert e.get("calibration_recorded") is True, (
            "measure should have written a CalibrationStore row but "
            f"reported {e.get('calibration_recorded')!r} for {e['attempt_id']}"
        )

    # ---- Step 5: open the calibration DB directly, assert factor ----
    # Real CalibrationStore reads what the real measure path wrote.
    expected_residual = (post_composite - score_before) - predicted  # -0.56
    store = CalibrationStore(db_path=str(cal_db))
    factor = store.factor(surface=surface, strategy=strategy, n=20)
    assert factor is not None, (
        "factor() returned None despite 20 rows being written — "
        "key ordering or env-var-honoring may be mismatched between "
        "writer and reader"
    )
    assert factor == pytest.approx(expected_residual, abs=1e-9), (
        f"calibration factor {factor!r} drift from expected "
        f"{expected_residual!r}; sign convention may be off between "
        f"writer and reader"
    )

    # ---- Step 6: exercise the read side ----
    # Seed the proposer's last-explanation slot directly so we don't
    # have to run the proposer; the calibrated rendering is what's
    # under test.
    entry = StrategyExplanation(
        strategy=strategy,
        surface=surface,
        effectiveness=predicted,
        samples=20,
        explored=False,
    )
    monkeypatch.setattr(prop_mod, "_LAST_EXPLANATION", [entry])

    rendered = _explanation_with_calibration(entry)
    print(rendered)  # the assert is the proof; this aids debug on failure.

    # The renderer must show the calibrated clause sourced from the
    # same CalibrationStore the writer populated.
    assert "calibrated effectiveness=" in rendered, (
        f"renderer did not include the calibrated clause: {rendered!r}"
    )
    # Negative residual (actual underperformed predicted) → "underperformed".
    assert "underperformed" in rendered, (
        f"sign convention mismatch — expected 'underperformed' for a "
        f"negative residual but got: {rendered!r}"
    )
    # Calibrated value: clamp(0.65 + (-0.56)) = 0.09; format is .2f.
    assert "calibrated effectiveness=0.09" in rendered, (
        f"calibrated effectiveness value drift: {rendered!r}"
    )
    # The magnitude clause uses abs(factor): 0.56.
    assert "by 0.56" in rendered, (
        f"magnitude clause drift: {rendered!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: canary arc smoke — record 12 pairs, score_recent returns a verdict.
# ---------------------------------------------------------------------------


def test_slice_b_canary_aggregator_smoke(tmp_path) -> None:
    """B.4 + B.5 wiring smoke: pairs flow through the real router into
    the real aggregator with the default heuristic judge, producing a
    CanaryVerdict with one of the three legal ``preferred`` values.

    No LLM, no mocks — the heuristic-only PairwiseLLMJudge path is
    exercised.
    """
    router = LocalCanaryRouter(db_path=str(tmp_path / "canary_pairs.db"))

    for i in range(12):
        router.record_pair(
            input_id=f"in-{i}",
            baseline_label="v1",
            candidate_label="v2",
            baseline_output=f"baseline answer {i}",
            candidate_output=f"candidate answer {i}",
            metadata={"user_message": f"prompt {i}"},
        )

    # Default judge → heuristic-only PairwiseLLMJudge (no LLM router).
    aggregator = CanaryScoringAggregator(router=router)
    verdict = aggregator.score_recent(
        baseline_label="v1",
        candidate_label="v2",
        min_pairs=10,
    )

    assert verdict is not None, (
        "aggregator returned None despite 12 pairs >= min_pairs=10"
    )
    assert isinstance(verdict, CanaryVerdict)
    assert verdict.baseline_label == "v1"
    assert verdict.candidate_label == "v2"
    assert verdict.n_pairs == 12
    assert verdict.preferred in {"baseline", "candidate", "tie"}, (
        f"preferred must be one of the three legal values; got "
        f"{verdict.preferred!r}"
    )
