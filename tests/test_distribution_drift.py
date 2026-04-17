"""Tests for C10 — production-score distribution drift detector (R6.9 / R6.10).

Covers:

1. ``detect_distribution_drift`` unit behavior (no-drift, drift, clipping,
   recommendation text, scipy cross-check).
2. ``ContinuousOrchestrator.run_once()`` emits ``drift_detected`` once when
   per-case scores diverge from baseline, and dedupes a second identical
   cycle via the C9 dedupe store.
3. Small-n guard: baseline smaller than ``min_baseline_size`` → no drift
   check, no emission.

No real LLM is invoked — the EvalRunner collaborator is faked via the
existing ``_build_eval_runner`` shim.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from cli.workspace import AgentLabWorkspace
from optimizer.improvement_lineage import ImprovementLineageStore


# ---------------------------------------------------------------------------
# detect_distribution_drift — unit tests
# ---------------------------------------------------------------------------


def test_no_drift_identical_distributions() -> None:
    from evals.drift import detect_distribution_drift

    baseline = [0.8] * 50
    current = [0.8] * 50
    report = detect_distribution_drift(baseline, current, threshold=0.2)

    assert report.diverged is False
    assert report.kl < 0.2
    assert report.baseline_size == 50
    assert report.current_size == 50
    assert report.threshold == 0.2
    assert "stable" in report.recommendation.lower()


def test_strong_drift_triggers_divergence() -> None:
    from evals.drift import detect_distribution_drift

    # Uniform baseline.
    baseline = [i / 50 for i in range(50)]
    # Current heavily concentrated in lower scores.
    current = [0.1] * 40 + [0.2] * 10
    report = detect_distribution_drift(baseline, current, threshold=0.2)

    assert report.diverged is True
    assert report.kl >= 0.2
    assert "diverged" in report.recommendation.lower()
    assert "agentlab eval ingest" in report.recommendation
    assert f"KL={report.kl:.3f}" in report.recommendation


def test_no_drift_recommendation_format() -> None:
    from evals.drift import detect_distribution_drift

    baseline = [0.8] * 50
    current = [0.8] * 50
    report = detect_distribution_drift(baseline, current, threshold=0.2)

    expected = f"Eval distribution stable (KL={report.kl:.3f} < 0.2)."
    assert report.recommendation == expected


def test_drift_recommendation_format() -> None:
    from evals.drift import detect_distribution_drift

    baseline = [i / 50 for i in range(50)]
    current = [0.1] * 40 + [0.2] * 10
    report = detect_distribution_drift(baseline, current, threshold=0.2)

    assert report.recommendation.startswith(
        f"Eval distribution diverged (KL={report.kl:.3f} >= 0.2)."
    )
    assert (
        "Your eval set covers a stale slice of current production distribution."
        in report.recommendation
    )
    assert (
        "agentlab eval ingest --from-traces <path> --since 7d"
        in report.recommendation
    )


def test_scores_outside_unit_interval_are_clipped() -> None:
    from evals.drift import detect_distribution_drift

    # Out-of-range scores must not explode log math.
    baseline = [-0.5, 0.0, 0.5, 1.0, 1.5] * 20
    current = [-0.1, 0.5, 0.5, 0.5, 1.2] * 20
    report = detect_distribution_drift(baseline, current, threshold=0.2)

    assert math.isfinite(report.kl)
    assert report.kl >= 0.0


def test_empty_inputs_return_zero_kl_no_divergence() -> None:
    from evals.drift import detect_distribution_drift

    report = detect_distribution_drift([], [], threshold=0.2)
    assert report.diverged is False
    assert report.kl == 0.0
    assert report.baseline_size == 0
    assert report.current_size == 0


def test_scipy_cross_check_kl() -> None:
    """Our KL(P||Q) must match scipy.stats.entropy(p, q) for the same bucketing."""
    scipy_stats = pytest.importorskip("scipy.stats")
    import numpy as np

    from evals.drift import detect_distribution_drift

    baseline = [i / 50 for i in range(50)]
    current = [0.1] * 40 + [0.2] * 10
    bins = 10
    eps = 1e-9

    # Replicate the module's bucketing so scipy gets the same distributions.
    def _hist(xs: list[float]) -> list[float]:
        counts = [0.0] * bins
        for x in xs:
            clipped = max(0.0, min(1.0, x))
            # Right-open bins, last bin closed on right.
            idx = int(clipped * bins)
            if idx >= bins:
                idx = bins - 1
            counts[idx] += 1.0
        total = sum(counts)
        if total == 0.0:
            return [1.0 / bins] * bins
        return [(c / total) + eps for c in counts]

    q = _hist(baseline)
    p = _hist(current)
    # Re-normalize after smoothing so scipy treats inputs as distributions.
    p_arr = np.array(p) / sum(p)
    q_arr = np.array(q) / sum(q)
    expected = float(scipy_stats.entropy(p_arr, q_arr))  # natural log

    report = detect_distribution_drift(baseline, current, threshold=0.2)
    # Our implementation smooths without renormalizing; tolerance 1e-3 reflects
    # the smoothing constant eps. Reimplement the same calculation here
    # without renormalizing for the strict 1e-6 assertion.
    raw_kl = 0.0
    for pi, qi in zip(p, q):
        raw_kl += pi * math.log(pi / qi)

    assert abs(report.kl - raw_kl) < 1e-6
    # Renormalized version (scipy-style) should be within eps*bins of ours.
    assert abs(report.kl - expected) < 1e-3


# ---------------------------------------------------------------------------
# Orchestrator integration fixtures (mirrors test_continuous_orchestrator).
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> AgentLabWorkspace:
    ws = AgentLabWorkspace.create(
        root=tmp_path / "wk",
        name="drift-test",
        template="blank",
        agent_name="Drift",
        platform="mock",
    )
    ws.ensure_structure()
    cfg = ws.configs_dir / "v001.yaml"
    cfg.write_text("model: mock\nprompts:\n  root: hi\n", encoding="utf-8")
    ws.metadata.active_config_version = 1
    ws.metadata.active_config_file = "v001.yaml"
    ws.save_metadata()
    return ws


@pytest.fixture
def trace_source(tmp_path: Path) -> Path:
    src = tmp_path / "traces"
    src.mkdir()
    (src / "trace_a.jsonl").write_text(
        json.dumps({"trace_id": "t1", "input": "hi"}) + "\n",
        encoding="utf-8",
    )
    return src


@dataclass
class _FakeEvalResult:
    run_id: str
    composite_score: float
    case_count: int
    case_scores: list[float]


class _FakeEvalRunner:
    """EvalRunner stand-in that returns scripted per-case scores."""

    def __init__(self, per_cycle_case_scores: list[list[float]]) -> None:
        self._cycles = list(per_cycle_case_scores)
        self._i = 0

    def score_cases(
        self, cases: list[dict[str, Any]], *, config: Any = None
    ) -> _FakeEvalResult:
        scores = self._cycles[self._i]
        self._i += 1
        composite = sum(scores) / len(scores) if scores else 0.0
        return _FakeEvalResult(
            run_id=f"run_{self._i}",
            composite_score=composite,
            case_count=len(scores),
            case_scores=list(scores),
        )


class _RecordingChannel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def send(
        self,
        config: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.calls.append((event_type, dict(payload)))


class _ClockStub:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def advance(self, seconds: int) -> None:
        self.now = self.now + timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


def _build_manager(
    tmp_path: Path,
    channel: _RecordingChannel,
    *,
    events: list[str] | None = None,
) -> Any:
    from notifications.manager import NotificationManager

    events = events or [
        "regression_detected",
        "improvement_queued",
        "continuous_cycle_failed",
        "drift_detected",
    ]
    mgr = NotificationManager(db_path=tmp_path / "notif.db")
    mgr.webhook_channel = channel  # type: ignore[assignment]
    mgr.register_webhook("https://example.com/hook", events=events)
    return mgr


def _seed_baseline_eval_runs(
    lineage: ImprovementLineageStore,
    per_run_case_scores: list[list[float]],
) -> None:
    for i, scores in enumerate(per_run_case_scores):
        composite = sum(scores) / len(scores) if scores else 0.0
        lineage.record_eval_run(
            eval_run_id=f"prior_{i}",
            attempt_id="",
            composite_score=composite,
            case_count=len(scores),
            case_scores=list(scores),
        )


# ---------------------------------------------------------------------------
# Orchestrator smoke — drift fires drift_detected exactly once.
# ---------------------------------------------------------------------------


def test_orchestrator_emits_drift_detected_on_distribution_drift(
    workspace: AgentLabWorkspace, trace_source: Path, tmp_path: Path
) -> None:
    from optimizer.continuous import ContinuousOrchestrator
    from optimizer.notification_dedupe import NotificationDedupeStore

    channel = _RecordingChannel()
    mgr = _build_manager(tmp_path, channel)
    mgr.dedupe_store = NotificationDedupeStore(db_path=tmp_path / "dedupe.db")

    lineage = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))
    # Baseline = uniform spread over 5 runs × 10 cases = 50 scores.
    _seed_baseline_eval_runs(
        lineage,
        [[i / 10 for i in range(10)] for _ in range(5)],
    )

    # Current = strongly skewed low.
    fake_eval = _FakeEvalRunner([[0.1] * 8 + [0.2] * 2])

    def fake_convert(paths: list[Path], **_: Any) -> list[dict[str, Any]]:
        return [{"case_id": p.stem} for p in paths]

    clock = _ClockStub(datetime(2026, 4, 17, 12, 0, 0))

    with patch(
        "optimizer.continuous._convert_trace_files_to_cases",
        side_effect=fake_convert,
    ), patch(
        "optimizer.continuous._build_eval_runner", return_value=fake_eval
    ), patch("optimizer.continuous._run_improve_run_in_process"):
        orch = ContinuousOrchestrator(
            workspace,
            trace_source=trace_source,
            lineage_store=lineage,
            notification_manager=mgr,
            clock=clock,
        )
        result = orch.run_once()

    assert result.drift_detected is True
    assert result.drift_kl is not None and result.drift_kl >= 0.2

    drift_calls = [c for c in channel.calls if c[0] == "drift_detected"]
    assert len(drift_calls) == 1
    payload = drift_calls[0][1]
    assert payload["kl"] == pytest.approx(result.drift_kl)
    assert payload["baseline_size"] == 50
    assert payload["current_size"] == 10
    assert "agentlab eval ingest" in payload["recommendation"]


def test_orchestrator_dedupes_drift_detected_across_two_cycles(
    workspace: AgentLabWorkspace, trace_source: Path, tmp_path: Path
) -> None:
    from optimizer.continuous import ContinuousOrchestrator
    from optimizer.notification_dedupe import NotificationDedupeStore

    channel = _RecordingChannel()
    mgr = _build_manager(tmp_path, channel)
    mgr.dedupe_store = NotificationDedupeStore(db_path=tmp_path / "dedupe.db")

    lineage = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))
    _seed_baseline_eval_runs(
        lineage,
        [[i / 10 for i in range(10)] for _ in range(5)],
    )

    # Two drifted cycles with identical per-case scores → same KL → dedupe.
    fake_eval = _FakeEvalRunner([[0.1] * 8 + [0.2] * 2, [0.1] * 8 + [0.2] * 2])

    def fake_convert(paths: list[Path], **_: Any) -> list[dict[str, Any]]:
        return [{"case_id": p.stem} for p in paths]

    clock = _ClockStub(datetime(2026, 4, 17, 12, 0, 0))

    def _touch() -> None:
        import os

        p = trace_source / "trace_a.jsonl"
        st = p.stat()
        os.utime(p, (st.st_atime, st.st_mtime + 60))

    with patch(
        "optimizer.continuous._convert_trace_files_to_cases",
        side_effect=fake_convert,
    ), patch(
        "optimizer.continuous._build_eval_runner", return_value=fake_eval
    ), patch("optimizer.continuous._run_improve_run_in_process"):
        orch = ContinuousOrchestrator(
            workspace,
            trace_source=trace_source,
            lineage_store=lineage,
            notification_manager=mgr,
            clock=clock,
        )
        orch.run_once()
        _touch()
        clock.advance(5 * 60)
        orch.run_once()

    drift_calls = [c for c in channel.calls if c[0] == "drift_detected"]
    assert len(drift_calls) == 1, (
        "drift_detected must dedupe across cycles at the same KL magnitude"
    )


def test_orchestrator_small_baseline_skips_drift_check(
    workspace: AgentLabWorkspace, trace_source: Path, tmp_path: Path
) -> None:
    """Baseline of only 10 scores → drift check is skipped entirely."""
    from optimizer.continuous import ContinuousOrchestrator
    from optimizer.notification_dedupe import NotificationDedupeStore

    channel = _RecordingChannel()
    mgr = _build_manager(tmp_path, channel)
    mgr.dedupe_store = NotificationDedupeStore(db_path=tmp_path / "dedupe.db")

    lineage = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))
    # Only 10 baseline scores → below default min_baseline_size=20.
    _seed_baseline_eval_runs(lineage, [[i / 10 for i in range(10)]])

    fake_eval = _FakeEvalRunner([[0.1] * 8 + [0.2] * 2])

    def fake_convert(paths: list[Path], **_: Any) -> list[dict[str, Any]]:
        return [{"case_id": p.stem} for p in paths]

    clock = _ClockStub(datetime(2026, 4, 17, 12, 0, 0))

    with patch(
        "optimizer.continuous._convert_trace_files_to_cases",
        side_effect=fake_convert,
    ), patch(
        "optimizer.continuous._build_eval_runner", return_value=fake_eval
    ), patch("optimizer.continuous._run_improve_run_in_process"):
        orch = ContinuousOrchestrator(
            workspace,
            trace_source=trace_source,
            lineage_store=lineage,
            notification_manager=mgr,
            clock=clock,
        )
        result = orch.run_once()

    assert result.drift_detected is False
    assert result.drift_kl is None
    drift_calls = [c for c in channel.calls if c[0] == "drift_detected"]
    assert drift_calls == []
