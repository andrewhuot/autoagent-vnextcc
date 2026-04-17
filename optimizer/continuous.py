"""Continuous improvement orchestrator (R6.2 / R6.3).

On each ``run_once()`` cycle the orchestrator:

  1. Ingests any new JSONL trace files under ``trace_source`` — files whose
     mtime exceeds the per-workspace watermark stored at
     ``.agentlab/continuous_watermark.json``.
  2. Converts traces to eval-case dicts (via the R5 trace ingest helper)
     and scores them using :class:`evals.runner.EvalRunner`.
  3. Compares the per-cycle median against the median of the last N runs
     pulled from the lineage store's ``eval_run`` events. A drop of
     ``regression_threshold`` or more flips ``regressed=True``.
  4. On regression, queues an improvement attempt via
     :func:`cli.commands.improve.run_improve_run_in_process` using
     ``mode="analyze_and_propose"`` and ``auto=False`` — **never** auto-deploy.
  5. Records a ``continuous_cycle`` lineage event with the cycle outcome.

The orchestrator never calls ``deploy`` directly. Improvement acceptance
and deployment remain gated by the R2 accept/deploy path.

Strict-live invariant: LLM-invoking steps re-use the shared guards from
``cli.strict_live``; missing provider keys exit with ``EXIT_MISSING_PROVIDER``
(14) via the underlying ``run_improve_run_in_process`` path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from cli.workspace import AgentLabWorkspace
from optimizer.improvement_lineage import (
    EVENT_EVAL_RUN,
    ImprovementLineageStore,
    LineageEvent,
)

logger = logging.getLogger(__name__)

_WATERMARK_FILENAME = "continuous_watermark.json"
_CONTINUOUS_CYCLE_EVENT = "continuous_cycle"
_DEDUPE_DB_FILENAME = "notification_log.db"
_DEDUPE_WINDOW_SECONDS = 3600


def _stable_signature(*parts: Any) -> str:
    """Deterministic short hash used as a dedupe signature."""
    joined = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def _coerce_case_scores(raw: Any) -> list[float]:
    """Normalize an arbitrary iterable of per-case scores into floats.

    Entries that cannot be coerced to a finite float are dropped rather
    than exploding the drift check.
    """
    if not raw:
        return []
    out: list[float] = []
    try:
        iterable = list(raw)
    except TypeError:
        return []
    for item in iterable:
        try:
            val = float(item)
        except (TypeError, ValueError):
            continue
        if val != val:  # NaN guard without importing math.
            continue
        out.append(val)
    return out


def _score_bucket(score: float | None) -> str:
    """Round a composite score into a coarse bucket for signature stability.

    Two consecutive cycles with near-identical regressions should produce
    the same signature, so we bucket at 0.05 granularity — matching the
    default regression threshold.
    """
    if score is None:
        return "none"
    try:
        return f"{round(float(score) * 20) / 20:.3f}"
    except (TypeError, ValueError):
        return "none"


# ---------------------------------------------------------------------------
# Indirection shims — patched by tests, call into real modules in production.
# ---------------------------------------------------------------------------


def _convert_trace_files_to_cases(
    paths: list[Path],
    *,
    max_cases: int | None = None,
    expected_output: str | None = None,
) -> list[dict[str, Any]]:
    """Default ingest helper — forwards to cli.commands.ingest.

    Wrapped behind a module-level name so tests can monkeypatch
    ``optimizer.continuous._convert_trace_files_to_cases`` without having to
    reach into the Click command module.
    """
    from cli.commands.ingest import convert_trace_files_to_cases

    return convert_trace_files_to_cases(
        paths, max_cases=max_cases, expected_output=expected_output
    )


def _build_eval_runner(workspace: AgentLabWorkspace) -> Any:
    """Construct an EvalRunner mirroring the production wiring in eval.py.

    Tests monkeypatch this to inject a scripted scorer, so the production
    dependency chain (runtime config, providers, case loaders) is only
    pulled in when the orchestrator is exercised end-to-end.
    """
    # Import inside the function to keep module import cheap for tests.
    from agent.config.runtime import load_runtime_config
    from evals.runner import EvalRunner

    runtime = load_runtime_config()
    resolved = workspace.resolve_active_config()
    return EvalRunner(
        runtime=runtime,
        cases_dir=str(workspace.cases_dir),
        default_agent_config=resolved.config if resolved else None,
    )


def _run_improve_run_in_process(**kwargs: Any) -> Any:
    """Default improvement runner — forwards to cli.commands.improve."""
    from cli.commands.improve import run_improve_run_in_process

    return run_improve_run_in_process(**kwargs)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ContinuousCycleResult:
    """Outcome of one ``ContinuousOrchestrator.run_once()`` invocation."""

    ingested_trace_count: int
    median_score: float | None
    baseline_median: float | None
    regressed: bool
    improvement_queued: bool
    attempt_id: str | None
    lineage_event_id: str | None
    error: str | None
    # R6.9 / R6.10 — production-score distribution drift (C10).
    drift_kl: float | None = None
    drift_detected: bool = False


# ---------------------------------------------------------------------------
# Watermark persistence
# ---------------------------------------------------------------------------


@dataclass
class _Watermark:
    """Per-workspace cursor across ingested trace files."""

    files: dict[str, float] = field(default_factory=dict)  # path → mtime
    updated_at: float = 0.0

    @classmethod
    def load(cls, path: Path) -> "_Watermark":
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        files = raw.get("files") or {}
        if not isinstance(files, dict):
            files = {}
        # Normalize values to floats; drop non-numeric.
        clean: dict[str, float] = {}
        for key, val in files.items():
            try:
                clean[str(key)] = float(val)
            except (TypeError, ValueError):
                continue
        return cls(files=clean, updated_at=float(raw.get("updated_at") or 0.0))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"files": self.files, "updated_at": self.updated_at}
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ContinuousOrchestrator:
    """Drive one continuous-improvement cycle per ``run_once()`` call."""

    def __init__(
        self,
        workspace: AgentLabWorkspace,
        *,
        trace_source: Path,
        regression_threshold: float = 0.05,
        lookback_runs: int = 5,
        lineage_store: ImprovementLineageStore | None = None,
        notification_manager: Any | None = None,
        clock: Callable[[], datetime] = datetime.utcnow,
        drift_threshold: float = 0.2,
        min_baseline_size: int = 20,
    ) -> None:
        self.workspace = workspace
        self.trace_source = Path(trace_source)
        self.regression_threshold = float(regression_threshold)
        self.lookback_runs = int(lookback_runs)
        # R6.9 / R6.10 — production-score distribution drift (C10).
        self.drift_threshold = float(drift_threshold)
        self.min_baseline_size = int(min_baseline_size)
        # Exposed publicly so NotificationManager.send(..., clock=...) can
        # share the same clock for test-time mocking.
        self.clock = clock
        self.notification_manager = notification_manager

        # Attach a default dedupe store to the manager when one is wired but
        # the caller did not provide one — keeps C8 callers working while
        # guaranteeing dedupe for continuous-loop emissions.
        if self.notification_manager is not None and getattr(
            self.notification_manager, "dedupe_store", None
        ) is None:
            try:
                from optimizer.notification_dedupe import NotificationDedupeStore

                dedupe_db = workspace.agentlab_dir / _DEDUPE_DB_FILENAME
                self.notification_manager.dedupe_store = NotificationDedupeStore(
                    db_path=dedupe_db
                )
            except Exception:
                logger.exception("failed to attach default dedupe store")

        if lineage_store is None:
            lineage_db = workspace.agentlab_dir / "improvement_lineage.db"
            lineage_db.parent.mkdir(parents=True, exist_ok=True)
            lineage_store = ImprovementLineageStore(db_path=str(lineage_db))
        self.lineage_store = lineage_store

        self._watermark_path = workspace.agentlab_dir / _WATERMARK_FILENAME

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run_once(self) -> ContinuousCycleResult:
        """Execute one continuous cycle. Errors are captured in ``result.error``."""
        try:
            return self._run_once_inner()
        except Exception as exc:  # noqa: BLE001 — surfaced via result.error
            # Still record a lineage marker so operators can see the failure.
            try:
                ev = self.lineage_store.record(
                    attempt_id="",
                    event_type=_CONTINUOUS_CYCLE_EVENT,
                    payload={
                        "error": str(exc),
                        "regressed": False,
                    },
                )
                event_id: str | None = ev.event_id
            except Exception:  # pragma: no cover — do not mask original error
                event_id = None
            # Emit continuous_cycle_failed regardless of lineage success.
            self._emit_cycle_failed(exc)
            return ContinuousCycleResult(
                ingested_trace_count=0,
                median_score=None,
                baseline_median=None,
                regressed=False,
                improvement_queued=False,
                attempt_id=None,
                lineage_event_id=event_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Inner pipeline
    # ------------------------------------------------------------------

    def _run_once_inner(self) -> ContinuousCycleResult:
        watermark = _Watermark.load(self._watermark_path)

        # 1. Discover new trace files (mtime strictly greater than watermark).
        new_files = self._discover_new_traces(watermark)
        cases = _convert_trace_files_to_cases(new_files)
        ingested = len(cases)

        # Persist updated watermark immediately so even a later failure does
        # not cause re-ingestion. The watermark advances per-file.
        for path in new_files:
            try:
                watermark.files[str(path.resolve())] = path.stat().st_mtime
            except OSError:
                continue
        watermark.updated_at = self.clock().timestamp()
        watermark.save(self._watermark_path)

        # 2. Score (only when we actually have new cases).
        median_score: float | None = None
        run_id: str | None = None
        current_case_scores: list[float] = []
        if cases:
            eval_runner = _build_eval_runner(self.workspace)
            eval_result = eval_runner.score_cases(cases)
            median_score = float(getattr(eval_result, "composite_score", 0.0))
            run_id = str(getattr(eval_result, "run_id", "") or "")
            current_case_scores = _coerce_case_scores(
                getattr(eval_result, "case_scores", None)
            )
            if run_id:
                self.lineage_store.record_eval_run(
                    eval_run_id=run_id,
                    attempt_id="",
                    composite_score=median_score,
                    case_count=int(getattr(eval_result, "case_count", len(cases))),
                    source="continuous",
                    case_scores=current_case_scores,
                )

        # 3. Regression check — median-of-last-N prior eval_run composite scores.
        baseline_median = self._baseline_median(exclude_run_id=run_id)
        regressed = (
            median_score is not None
            and baseline_median is not None
            and (baseline_median - median_score) >= self.regression_threshold
        )

        # 3b. Distribution drift (R6.9 / R6.10). Pulls per-case scores from
        # the last N eval_run events and compares against the current run.
        drift_kl, drift_detected, drift_report = self._check_distribution_drift(
            current_case_scores=current_case_scores,
            exclude_run_id=run_id,
        )

        # 4. Queue improvement on regression. Never deploy.
        attempt_id: str | None = None
        improvement_queued = False
        if regressed:
            resolved = self.workspace.resolve_active_config()
            config_path = str(resolved.path) if resolved else None

            def _noop_event(_evt: dict[str, Any]) -> None:
                return None

            def _noop_text(_msg: str) -> None:
                return None

            improve_result = _run_improve_run_in_process(
                config_path=config_path,
                cycles=1,
                mode="analyze_and_propose",
                strict_live=True,
                auto=False,
                on_event=_noop_event,
                text_writer=_noop_text,
            )
            attempt_id = getattr(improve_result, "attempt_id", None)
            improvement_queued = True

        # 5. Record continuous_cycle lineage event.
        lineage_event = self._record_cycle(
            ingested=ingested,
            median_score=median_score,
            baseline_median=baseline_median,
            regressed=regressed,
            attempt_id=attempt_id,
            run_id=run_id,
        )

        # 6. Emit notifications (R6.4 / R6.5). Failures here must not break
        # the cycle — each helper swallows its own exceptions.
        if regressed:
            self._emit_regression_detected(
                median_score=median_score,
                baseline_median=baseline_median,
            )
        if improvement_queued and attempt_id:
            self._emit_improvement_queued(
                attempt_id=attempt_id,
                eval_run_id=run_id,
            )
        if drift_detected and drift_report is not None:
            self._emit_drift_detected(report=drift_report)

        return ContinuousCycleResult(
            ingested_trace_count=ingested,
            median_score=median_score,
            baseline_median=baseline_median,
            regressed=bool(regressed),
            improvement_queued=improvement_queued,
            attempt_id=attempt_id,
            lineage_event_id=lineage_event.event_id if lineage_event else None,
            error=None,
            drift_kl=drift_kl,
            drift_detected=bool(drift_detected),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _discover_new_traces(self, watermark: _Watermark) -> list[Path]:
        """Return JSONL files under ``trace_source`` with mtime > watermark."""
        if not self.trace_source.exists() or not self.trace_source.is_dir():
            return []
        new: list[Path] = []
        for path in sorted(self.trace_source.glob("*.jsonl")):
            key = str(path.resolve())
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            prior = watermark.files.get(key)
            if prior is not None and mtime <= prior:
                continue
            new.append(path)
        return new

    def _baseline_median(self, *, exclude_run_id: str | None) -> float | None:
        """Median composite score of the last N eval_run events in the lineage store.

        When ``exclude_run_id`` is non-None the current cycle's just-recorded
        run is skipped so the "baseline" remains genuinely prior history.
        """
        # Pull generously; keep only eval_run events and trim.
        recent = self.lineage_store.recent(limit=self.lookback_runs * 10 + 20)
        scores: list[float] = []
        for ev in recent:
            if ev.event_type != EVENT_EVAL_RUN:
                continue
            payload = ev.payload or {}
            if exclude_run_id and payload.get("eval_run_id") == exclude_run_id:
                continue
            raw = payload.get("composite_score")
            if raw is None:
                continue
            try:
                scores.append(float(raw))
            except (TypeError, ValueError):
                continue
            if len(scores) >= self.lookback_runs:
                break
        if not scores:
            return None
        return float(statistics.median(scores))

    def _collect_baseline_case_scores(
        self, *, exclude_run_id: str | None
    ) -> list[float]:
        """Concatenate per-case scores from the last N prior eval_run events.

        When ``exclude_run_id`` matches, that event is skipped so the
        baseline only reflects runs that preceded the current cycle.
        Runs emitted by the continuous loop itself (``source="continuous"``)
        are excluded so the baseline represents the curated eval set and
        stays stable across cycles — this also keeps the drift signature
        stable for C9 dedupe.
        """
        recent = self.lineage_store.recent(limit=self.lookback_runs * 10 + 20)
        scores: list[float] = []
        runs_seen = 0
        for ev in recent:
            if ev.event_type != EVENT_EVAL_RUN:
                continue
            payload = ev.payload or {}
            if exclude_run_id and payload.get("eval_run_id") == exclude_run_id:
                continue
            if payload.get("source") == "continuous":
                continue
            raw_case_scores = payload.get("case_scores")
            if not isinstance(raw_case_scores, list) or not raw_case_scores:
                continue
            scores.extend(_coerce_case_scores(raw_case_scores))
            runs_seen += 1
            if runs_seen >= self.lookback_runs:
                break
        return scores

    def _check_distribution_drift(
        self,
        *,
        current_case_scores: list[float],
        exclude_run_id: str | None,
    ) -> tuple[float | None, bool, Any]:
        """Pull baseline per-case scores and run the drift detector.

        Returns ``(kl, detected, report_or_None)``. When skipped (no
        current scores or baseline too small) returns ``(None, False, None)``.
        """
        if not current_case_scores:
            return None, False, None

        baseline = self._collect_baseline_case_scores(exclude_run_id=exclude_run_id)
        if len(baseline) < self.min_baseline_size:
            logger.debug(
                "drift check skipped: baseline=%d < min_baseline_size=%d",
                len(baseline),
                self.min_baseline_size,
            )
            return None, False, None

        # Import locally to keep orchestrator module import cheap.
        from evals.drift import detect_distribution_drift

        report = detect_distribution_drift(
            baseline,
            current_case_scores,
            threshold=self.drift_threshold,
        )
        return float(report.kl), bool(report.diverged), report

    def _record_cycle(
        self,
        *,
        ingested: int,
        median_score: float | None,
        baseline_median: float | None,
        regressed: bool,
        attempt_id: str | None,
        run_id: str | None,
    ) -> LineageEvent | None:
        payload = {
            "ingested_trace_count": ingested,
            "median_score": median_score,
            "baseline_median": baseline_median,
            "regressed": bool(regressed),
            "attempt_id": attempt_id,
            "eval_run_id": run_id,
            "cycle_id": uuid.uuid4().hex[:12],
            "timestamp": self.clock().isoformat(),
        }
        try:
            return self.lineage_store.record(
                attempt_id=attempt_id or "",
                event_type=_CONTINUOUS_CYCLE_EVENT,
                payload=payload,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Notification emission helpers (R6.4 / R6.5)
    # ------------------------------------------------------------------

    def _workspace_id(self) -> str:
        """Stable identifier used as the dedupe ``workspace`` key."""
        try:
            return str(self.workspace.metadata.name)
        except Exception:
            return str(self.workspace.root)

    def _config_version(self) -> str:
        try:
            return str(self.workspace.metadata.active_config_version or "")
        except Exception:
            return ""

    def _emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        signature: str,
    ) -> None:
        """Fire-and-forget emit; swallow any channel errors."""
        if self.notification_manager is None:
            return
        try:
            self.notification_manager.send(
                event_type,
                payload,
                workspace=self._workspace_id(),
                signature=signature,
                clock=self.clock,
            )
        except Exception:
            logger.exception("notification emit failed for %s", event_type)

    def _emit_regression_detected(
        self,
        *,
        median_score: float | None,
        baseline_median: float | None,
    ) -> None:
        workspace_id = self._workspace_id()
        signature = _stable_signature(
            workspace_id,
            _score_bucket(median_score),
            self._config_version(),
        )
        payload = {
            "workspace": workspace_id,
            "median_score": median_score,
            "baseline_median": baseline_median,
            "regression_threshold": self.regression_threshold,
            "timestamp": self.clock().isoformat(),
        }
        self._emit("regression_detected", payload, signature=signature)

    def _emit_improvement_queued(
        self,
        *,
        attempt_id: str,
        eval_run_id: str | None,
    ) -> None:
        workspace_id = self._workspace_id()
        payload = {
            "workspace": workspace_id,
            "attempt_id": attempt_id,
            "eval_run_id": eval_run_id,
            "timestamp": self.clock().isoformat(),
        }
        # Per spec: signature = attempt_id. Distinct attempts always fire.
        self._emit("improvement_queued", payload, signature=str(attempt_id))

    def _emit_drift_detected(self, *, report: Any) -> None:
        """Emit ``drift_detected`` with a KL-magnitude-bucketed signature."""
        workspace_id = self._workspace_id()
        # Bucket at 0.01 resolution — matches the 2-decimal signature spec.
        kl_bucket = round(float(report.kl), 2)
        signature = _stable_signature(workspace_id, f"{kl_bucket:.2f}")
        payload = {
            "workspace": workspace_id,
            "kl": float(report.kl),
            "baseline_size": int(report.baseline_size),
            "current_size": int(report.current_size),
            "recommendation": str(report.recommendation),
            "timestamp": self.clock().isoformat(),
        }
        self._emit("drift_detected", payload, signature=signature)

    def _emit_cycle_failed(self, exc: BaseException) -> None:
        workspace_id = self._workspace_id()
        error_class = type(exc).__name__
        error_message = str(exc)
        first_line = error_message.splitlines()[0] if error_message else ""
        signature = _stable_signature(workspace_id, error_class, first_line)
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        payload = {
            "workspace": workspace_id,
            "error": f"{error_class}: {error_message}",
            "traceback": tb,
            "timestamp": self.clock().isoformat(),
        }
        self._emit("continuous_cycle_failed", payload, signature=signature)
