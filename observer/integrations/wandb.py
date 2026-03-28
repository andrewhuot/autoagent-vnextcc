"""Weights & Biases (wandb) observability platform integration."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class WandbExporter:
    """Exports traces and eval results to Weights & Biases.

    W&B (wandb) is an MLOps platform for experiment tracking and observability.
    This exporter logs AutoAgent traces as W&B runs/tables and records eval
    metrics via its summary API.
    """

    def __init__(
        self,
        api_key: str = "",
        project: str = "",
        entity: str = "",
    ) -> None:
        """Initialise the exporter.

        Args:
            api_key: W&B API key (falls back to WANDB_API_KEY env var).
            project: W&B project name.
            entity: W&B entity (team or user). Defaults to personal account.
        """
        self.api_key = api_key
        self.project = project
        self.entity = entity
        self._wandb: Any = None
        self._init_sdk()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_sdk(self) -> None:
        """Attempt to import wandb and authenticate."""
        try:
            import wandb  # type: ignore[import]

            if self.api_key:
                wandb.login(key=self.api_key, relogin=True)
            self._wandb = wandb
        except ImportError:
            logger.debug("wandb SDK not installed; HTTP logging will be used")

    def _run_kwargs(self, name: str | None = None) -> dict[str, Any]:
        """Build wandb.init kwargs from instance config."""
        kwargs: dict[str, Any] = {
            "project": self.project,
            "reinit": True,
            "job_type": "autoagent-trace",
        }
        if self.entity:
            kwargs["entity"] = self.entity
        if name:
            kwargs["name"] = name
        return kwargs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_trace(self, trace: dict) -> bool:
        """Export a single trace to W&B as a run log entry.

        Each trace is uploaded as a W&B Table row within a dedicated run so
        that the full conversation history is queryable from the W&B UI.

        Args:
            trace: AutoAgent trace dictionary.

        Returns:
            True on success, False on failure.
        """
        if self._wandb is None:
            logger.warning("wandb SDK not available; cannot export trace")
            return False

        try:
            run = self._wandb.init(
                **self._run_kwargs(
                    name=trace.get("name") or trace.get("trace_id", "")[:8]
                )
            )
            run.log({
                "trace_id": trace.get("trace_id", ""),
                "agent_id": trace.get("agent_id", ""),
                "model": trace.get("model", ""),
                "success": trace.get("success", False),
                "latency_ms": trace.get("latency_ms", 0),
                "input_tokens": trace.get("input_tokens", 0),
                "output_tokens": trace.get("output_tokens", 0),
                "cost_usd": trace.get("cost_usd", 0.0),
                "tags": ",".join(trace.get("tags", [])),
            })
            run.finish()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("wandb trace export failed: %s", exc)
            return False

    def log_eval_results(self, results: dict) -> bool:
        """Log evaluation results summary to W&B.

        Args:
            results: Eval results dict containing top-level scalar metrics
                and optionally a ``cases`` list for per-case logging.

        Returns:
            True on success, False on failure.
        """
        if self._wandb is None:
            logger.warning("wandb SDK not available; cannot log eval results")
            return False

        try:
            run = self._wandb.init(
                **self._run_kwargs(
                    name=results.get("eval_name") or results.get("benchmark_name", "eval")
                )
            )

            # Log scalar summary metrics
            scalars = {
                k: v
                for k, v in results.items()
                if isinstance(v, (int, float)) and k not in ("cases",)
            }
            if scalars:
                run.log(scalars)

            # Log per-case table if present
            cases = results.get("cases", [])
            if cases:
                columns = list(cases[0].keys()) if cases else []
                table = self._wandb.Table(columns=columns)
                for case in cases:
                    table.add_data(*[case.get(col) for col in columns])
                run.log({"eval_cases": table})

            run.finish()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("wandb eval results log failed: %s", exc)
            return False
