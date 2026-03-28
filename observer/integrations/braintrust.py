"""Braintrust observability platform integration."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BraintrustExporter:
    """Exports traces and eval results to Braintrust, and imports scores from experiments.

    Braintrust is an AI evaluation platform. This exporter pushes AutoAgent
    trace dicts as Braintrust spans/experiments and retrieves scored results.
    """

    def __init__(
        self,
        api_key: str = "",
        project: str = "",
    ) -> None:
        """Initialise the exporter.

        Args:
            api_key: Braintrust API key.
            project: Braintrust project name.
        """
        self.api_key = api_key
        self.project = project
        self._client: Any = None
        self._init_client()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_client(self) -> None:
        """Attempt to initialise the official Braintrust SDK client if available."""
        if not self.api_key:
            return
        try:
            import braintrust  # type: ignore[import]

            self._client = braintrust
            # Store credentials for later use
            braintrust.login(api_key=self.api_key)
        except ImportError:
            logger.debug("braintrust SDK not installed; using HTTP fallback")

    def _get_headers(self) -> dict[str, str]:
        """Return authorization headers for Braintrust REST calls."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_trace(self, trace: dict) -> bool:
        """Export a single trace to Braintrust as a logged span.

        Args:
            trace: AutoAgent trace dictionary.

        Returns:
            True on success, False on failure.
        """
        if self._client is not None:
            try:
                experiment = self._client.init(
                    project=self.project,
                    experiment=trace.get("session_id") or "autoagent-traces",
                    open=True,
                )
                with experiment.start_span(
                    name=trace.get("name") or trace.get("agent_name", "autoagent"),
                    input=trace.get("input") or trace.get("messages", []),
                    output=trace.get("output") or trace.get("response", ""),
                    metadata={
                        "trace_id": trace.get("trace_id", ""),
                        "model": trace.get("model", ""),
                        **trace.get("metadata", {}),
                    },
                ):
                    pass
                experiment.close()
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Braintrust SDK trace export failed: %s", exc)
                return False

        # HTTP fallback
        try:
            import json
            import urllib.request

            payload = json.dumps({
                "project_name": self.project,
                "input": trace.get("input") or trace.get("messages", []),
                "output": trace.get("output") or trace.get("response", ""),
                "metadata": {
                    "trace_id": trace.get("trace_id", ""),
                    "agent_id": trace.get("agent_id", ""),
                    **trace.get("metadata", {}),
                },
                "tags": trace.get("tags", []),
            }).encode()

            req = urllib.request.Request(
                "https://api.braintrust.dev/v1/logs",
                data=payload,
                headers=self._get_headers(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 300
        except Exception as exc:  # noqa: BLE001
            logger.warning("Braintrust HTTP trace export failed: %s", exc)
            return False

    def export_eval(self, result: dict) -> bool:
        """Export an evaluation result to a Braintrust experiment.

        Args:
            result: Eval result dict containing at minimum ``input``, ``output``,
                and ``scores``.

        Returns:
            True on success, False on failure.
        """
        if self._client is not None:
            try:
                experiment = self._client.init(
                    project=self.project,
                    experiment=result.get("experiment_name", "autoagent-evals"),
                )
                experiment.log(
                    input=result.get("input", ""),
                    output=result.get("output", ""),
                    expected=result.get("expected", ""),
                    scores=result.get("scores", {}),
                    metadata=result.get("metadata", {}),
                )
                experiment.close()
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Braintrust SDK eval export failed: %s", exc)
                return False

        try:
            import json
            import urllib.request

            experiment_name = result.get("experiment_name", "autoagent-evals")
            payload = json.dumps({
                "project_name": self.project,
                "experiment_name": experiment_name,
                "input": result.get("input", ""),
                "output": result.get("output", ""),
                "expected": result.get("expected", ""),
                "scores": result.get("scores", {}),
                "metadata": result.get("metadata", {}),
            }).encode()

            req = urllib.request.Request(
                "https://api.braintrust.dev/v1/experiment",
                data=payload,
                headers=self._get_headers(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 300
        except Exception as exc:  # noqa: BLE001
            logger.warning("Braintrust HTTP eval export failed: %s", exc)
            return False

    def import_scores(self, experiment_name: str) -> list[dict]:
        """Import scores from a Braintrust experiment.

        Args:
            experiment_name: Name of the experiment to import scores from.

        Returns:
            List of score dicts, each containing ``id``, ``input``, ``output``,
            ``scores``, and ``metadata``.
        """
        if self._client is not None:
            try:
                experiment = self._client.init(
                    project=self.project,
                    experiment=experiment_name,
                    open=True,
                )
                rows = list(experiment.fetch())
                experiment.close()
                return [
                    {
                        "id": row.get("id", ""),
                        "input": row.get("input", ""),
                        "output": row.get("output", ""),
                        "expected": row.get("expected", ""),
                        "scores": row.get("scores", {}),
                        "metadata": row.get("metadata", {}),
                        "experiment_name": experiment_name,
                    }
                    for row in rows
                ]
            except Exception as exc:  # noqa: BLE001
                logger.warning("Braintrust SDK import failed: %s", exc)
                return []

        try:
            import json
            import urllib.request

            url = (
                f"https://api.braintrust.dev/v1/experiment"
                f"?project_name={self.project}&experiment_name={experiment_name}"
            )
            req = urllib.request.Request(url, headers=self._get_headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return data.get("objects", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Braintrust HTTP import failed: %s", exc)
            return []
