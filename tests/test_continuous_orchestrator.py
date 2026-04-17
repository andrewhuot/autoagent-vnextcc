"""Tests for the R6.2/R6.3 ContinuousOrchestrator.

Covers the per-cycle ingest → score → regression-check → queue-improvement
→ lineage-record pipeline plus the watermark invariant that prevents
re-ingesting the same trace twice.

No real eval / LLM is invoked — every LLM-touching collaborator is faked.
The ``ImprovementLineageStore`` runs against a real temp SQLite file so we
exercise the actual persistence path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from cli.workspace import AgentLabWorkspace, WorkspaceMetadata
from optimizer.improvement_lineage import (
    EVENT_ATTEMPT,
    EVENT_DEPLOYMENT,
    EVENT_EVAL_RUN,
    ImprovementLineageStore,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> AgentLabWorkspace:
    """Seeded workspace with .agentlab/ and a minimal v001 config."""
    ws = AgentLabWorkspace.create(
        root=tmp_path / "wk",
        name="cont-test",
        template="blank",
        agent_name="Cont",
        platform="mock",
    )
    ws.ensure_structure()
    cfg = ws.configs_dir / "v001.yaml"
    cfg.write_text("model: mock\nprompts:\n  root: hello\n", encoding="utf-8")
    ws.metadata.active_config_version = 1
    ws.metadata.active_config_file = "v001.yaml"
    ws.save_metadata()
    return ws


@pytest.fixture
def trace_source(tmp_path: Path) -> Path:
    """A dir holding two JSONL trace files."""
    src = tmp_path / "traces"
    src.mkdir()
    (src / "trace_a.jsonl").write_text(
        json.dumps({"trace_id": "t1", "input": "hi a"}) + "\n",
        encoding="utf-8",
    )
    (src / "trace_b.jsonl").write_text(
        json.dumps({"trace_id": "t2", "input": "hi b"}) + "\n",
        encoding="utf-8",
    )
    return src


@dataclass
class _FakeEvalResult:
    run_id: str
    composite_score: float
    case_count: int


class _FakeEvalRunner:
    """Swappable EvalRunner — returns a scripted sequence of scores."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = list(scores)
        self._i = 0
        self.calls: list[int] = []

    def score_cases(self, cases: list[dict[str, Any]], *, config: Any = None) -> _FakeEvalResult:
        self.calls.append(len(cases))
        score = self._scores[self._i]
        self._i += 1
        return _FakeEvalResult(
            run_id=f"run_{self._i}",
            composite_score=score,
            case_count=len(cases),
        )


@dataclass
class _FakeImproveRunResult:
    attempt_id: str | None
    config_path: str | None
    eval_run_id: str | None
    status: str


# ---------------------------------------------------------------------------
# run_once — first cycle: ingest, no baseline, no regression, no improvement
# ---------------------------------------------------------------------------


def test_run_once_ingests_traces_and_records_eval_run(
    workspace: AgentLabWorkspace, trace_source: Path, tmp_path: Path
) -> None:
    from optimizer.continuous import ContinuousOrchestrator

    lineage = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))
    fake_eval = _FakeEvalRunner(scores=[0.9])

    def fake_convert(paths: list[Path], **_: Any) -> list[dict[str, Any]]:
        return [{"case_id": p.stem, "task": "x"} for p in paths]

    with patch("optimizer.continuous._convert_trace_files_to_cases", side_effect=fake_convert), \
         patch("optimizer.continuous._build_eval_runner", return_value=fake_eval), \
         patch("optimizer.continuous._run_improve_run_in_process") as improve_mock:
        orch = ContinuousOrchestrator(
            workspace,
            trace_source=trace_source,
            lineage_store=lineage,
        )
        result = orch.run_once()

    assert result.ingested_trace_count == 2
    assert result.median_score == pytest.approx(0.9)
    assert result.baseline_median is None  # no prior history
    assert result.regressed is False
    assert result.improvement_queued is False
    assert result.attempt_id is None
    improve_mock.assert_not_called()

    # Watermark file written.
    watermark = workspace.agentlab_dir / "continuous_watermark.json"
    assert watermark.exists()
    wm = json.loads(watermark.read_text())
    assert isinstance(wm.get("files"), dict)
    assert len(wm["files"]) == 2


# ---------------------------------------------------------------------------
# second cycle: regression fires → improvement queued → no deploy
# ---------------------------------------------------------------------------


def test_second_cycle_regression_queues_improvement(
    workspace: AgentLabWorkspace, trace_source: Path, tmp_path: Path
) -> None:
    from optimizer.continuous import ContinuousOrchestrator

    lineage = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))
    # Seed prior run medians into the lineage store so baseline_median = 0.9.
    for i in range(3):
        lineage.record_eval_run(
            eval_run_id=f"prior_{i}",
            attempt_id="",
            composite_score=0.9,
            case_count=2,
        )

    fake_eval = _FakeEvalRunner(scores=[0.7])

    def fake_convert(paths: list[Path], **_: Any) -> list[dict[str, Any]]:
        return [{"case_id": p.stem, "task": "x"} for p in paths]

    fake_result = _FakeImproveRunResult(
        attempt_id="att_xyz",
        config_path=None,
        eval_run_id="eval_1",
        status="ok",
    )

    with patch("optimizer.continuous._convert_trace_files_to_cases", side_effect=fake_convert), \
         patch("optimizer.continuous._build_eval_runner", return_value=fake_eval), \
         patch(
             "optimizer.continuous._run_improve_run_in_process",
             return_value=fake_result,
         ) as improve_mock:
        orch = ContinuousOrchestrator(
            workspace,
            trace_source=trace_source,
            lineage_store=lineage,
            regression_threshold=0.05,
            lookback_runs=5,
        )
        result = orch.run_once()

    assert result.ingested_trace_count == 2
    assert result.median_score == pytest.approx(0.7)
    assert result.baseline_median == pytest.approx(0.9)
    assert result.regressed is True
    assert result.improvement_queued is True
    assert result.attempt_id == "att_xyz"
    assert result.lineage_event_id is not None

    # run_improve_run_in_process called with analyze_and_propose, no auto-deploy.
    improve_mock.assert_called_once()
    call_kwargs = improve_mock.call_args.kwargs
    assert call_kwargs["mode"] == "analyze_and_propose"
    assert call_kwargs["cycles"] == 1
    assert call_kwargs["strict_live"] is True
    assert call_kwargs["auto"] is False

    # No deployment events recorded.
    all_events = lineage.recent(limit=100)
    assert not any(e.event_type == EVENT_DEPLOYMENT for e in all_events)

    # A continuous_cycle marker exists.
    cycle_events = [e for e in all_events if e.event_type == "continuous_cycle"]
    assert len(cycle_events) == 1
    assert cycle_events[0].payload.get("regressed") is True
    assert cycle_events[0].payload.get("attempt_id") == "att_xyz"


# ---------------------------------------------------------------------------
# watermark prevents re-ingestion
# ---------------------------------------------------------------------------


def test_watermark_prevents_reingestion(
    workspace: AgentLabWorkspace, trace_source: Path, tmp_path: Path
) -> None:
    from optimizer.continuous import ContinuousOrchestrator

    lineage = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))
    fake_eval = _FakeEvalRunner(scores=[0.9, 0.9, 0.9])

    def fake_convert(paths: list[Path], **_: Any) -> list[dict[str, Any]]:
        return [{"case_id": p.stem, "task": "x"} for p in paths]

    with patch("optimizer.continuous._convert_trace_files_to_cases", side_effect=fake_convert), \
         patch("optimizer.continuous._build_eval_runner", return_value=fake_eval), \
         patch("optimizer.continuous._run_improve_run_in_process"):
        orch = ContinuousOrchestrator(
            workspace,
            trace_source=trace_source,
            lineage_store=lineage,
        )
        first = orch.run_once()
        second = orch.run_once()

    assert first.ingested_trace_count == 2
    # No new traces → watermark skips both files.
    assert second.ingested_trace_count == 0
    assert second.median_score is None
    assert second.regressed is False


# ---------------------------------------------------------------------------
# notification_manager=None does not crash
# ---------------------------------------------------------------------------


def test_notification_manager_none_does_not_crash(
    workspace: AgentLabWorkspace, trace_source: Path, tmp_path: Path
) -> None:
    from optimizer.continuous import ContinuousOrchestrator

    lineage = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))
    fake_eval = _FakeEvalRunner(scores=[0.9])

    def fake_convert(paths: list[Path], **_: Any) -> list[dict[str, Any]]:
        return [{"case_id": p.stem} for p in paths]

    with patch("optimizer.continuous._convert_trace_files_to_cases", side_effect=fake_convert), \
         patch("optimizer.continuous._build_eval_runner", return_value=fake_eval), \
         patch("optimizer.continuous._run_improve_run_in_process"):
        orch = ContinuousOrchestrator(
            workspace,
            trace_source=trace_source,
            lineage_store=lineage,
            notification_manager=None,
        )
        result = orch.run_once()

    assert result.error is None


# ---------------------------------------------------------------------------
# no deploy invocation anywhere
# ---------------------------------------------------------------------------


def test_no_deploy_ever_invoked(
    workspace: AgentLabWorkspace, trace_source: Path, tmp_path: Path
) -> None:
    from optimizer.continuous import ContinuousOrchestrator

    lineage = ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))
    for i in range(3):
        lineage.record_eval_run(
            eval_run_id=f"prior_{i}",
            attempt_id="",
            composite_score=0.95,
            case_count=2,
        )

    fake_eval = _FakeEvalRunner(scores=[0.5])

    def fake_convert(paths: list[Path], **_: Any) -> list[dict[str, Any]]:
        return [{"case_id": p.stem} for p in paths]

    fake_result = _FakeImproveRunResult(
        attempt_id="att_no_deploy",
        config_path=None,
        eval_run_id=None,
        status="ok",
    )

    with patch("optimizer.continuous._convert_trace_files_to_cases", side_effect=fake_convert), \
         patch("optimizer.continuous._build_eval_runner", return_value=fake_eval), \
         patch(
             "optimizer.continuous._run_improve_run_in_process",
             return_value=fake_result,
         ):
        # Catch any accidental deploy call.
        with patch("deployer.Deployer") as deployer_cls:
            orch = ContinuousOrchestrator(
                workspace,
                trace_source=trace_source,
                lineage_store=lineage,
            )
            orch.run_once()
        deployer_cls.assert_not_called()
