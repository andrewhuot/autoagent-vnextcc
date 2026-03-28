"""Langfuse observability platform integration."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LangfuseExporter:
    """Exports traces and eval results to Langfuse, and imports eval results from it.

    Langfuse is an open-source LLM observability platform. This exporter
    serialises AutoAgent trace dicts into Langfuse's trace/observation schema
    and pushes them via its REST API (or the langfuse Python SDK when available).
    """

    def __init__(
        self,
        public_key: str = "",
        secret_key: str = "",
        host: str = "",
    ) -> None:
        """Initialise the exporter.

        Args:
            public_key: Langfuse public (client) key.
            secret_key: Langfuse secret key.
            host: Langfuse host URL (defaults to https://cloud.langfuse.com).
        """
        self.public_key = public_key
        self.secret_key = secret_key
        self.host = host or "https://cloud.langfuse.com"
        self._client: Any = None
        self._init_client()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_client(self) -> None:
        """Attempt to initialise the official Langfuse SDK client if available."""
        if not self.public_key or not self.secret_key:
            return
        try:
            import langfuse  # type: ignore[import]

            self._client = langfuse.Langfuse(
                public_key=self.public_key,
                secret_key=self.secret_key,
                host=self.host,
            )
        except ImportError:
            logger.debug("langfuse SDK not installed; using HTTP fallback")

    def _format_for_langfuse(self, trace: dict) -> dict:
        """Convert an AutoAgent trace dict into Langfuse's trace schema.

        Args:
            trace: AutoAgent trace dictionary.

        Returns:
            Dictionary conforming to the Langfuse Trace object schema.
        """
        return {
            "id": trace.get("trace_id") or trace.get("id", ""),
            "name": trace.get("name") or trace.get("agent_name", "autoagent"),
            "input": trace.get("input") or trace.get("messages", []),
            "output": trace.get("output") or trace.get("response", ""),
            "metadata": {
                "agent_id": trace.get("agent_id", ""),
                "model": trace.get("model", ""),
                "tags": trace.get("tags", []),
                **trace.get("metadata", {}),
            },
            "user_id": trace.get("user_id", ""),
            "session_id": trace.get("session_id", ""),
            "tags": trace.get("tags", []),
            "timestamp": trace.get("timestamp") or trace.get("created_at", ""),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export_trace(self, trace: dict) -> bool:
        """Export a single trace to Langfuse.

        Args:
            trace: AutoAgent trace dictionary.

        Returns:
            True on success, False on failure.
        """
        formatted = self._format_for_langfuse(trace)

        # Use official SDK when available
        if self._client is not None:
            try:
                self._client.trace(**formatted)
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Langfuse SDK trace export failed: %s", exc)
                return False

        # HTTP fallback using urllib (no extra deps)
        try:
            import base64
            import json
            import urllib.request

            credentials = base64.b64encode(
                f"{self.public_key}:{self.secret_key}".encode()
            ).decode()
            payload = json.dumps({"batch": [{"type": "trace-create", "body": formatted}]}).encode()
            req = urllib.request.Request(
                f"{self.host}/api/public/ingestion",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Basic {credentials}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 300
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse HTTP trace export failed: %s", exc)
            return False

    def export_eval_result(self, result: dict) -> bool:
        """Export an evaluation result (score) to Langfuse.

        Args:
            result: Eval result dict containing at minimum ``trace_id``, ``name``,
                and ``value``.

        Returns:
            True on success, False on failure.
        """
        if self._client is not None:
            try:
                self._client.score(
                    trace_id=result.get("trace_id", ""),
                    name=result.get("name", "score"),
                    value=result.get("value", 0.0),
                    comment=result.get("comment", ""),
                )
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Langfuse SDK score export failed: %s", exc)
                return False

        try:
            import base64
            import json
            import urllib.request

            credentials = base64.b64encode(
                f"{self.public_key}:{self.secret_key}".encode()
            ).decode()
            payload = json.dumps({
                "traceId": result.get("trace_id", ""),
                "name": result.get("name", "score"),
                "value": result.get("value", 0.0),
                "comment": result.get("comment", ""),
            }).encode()
            req = urllib.request.Request(
                f"{self.host}/api/public/scores",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Basic {credentials}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 300
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse HTTP score export failed: %s", exc)
            return False

    def import_eval_results(self, dataset_name: str) -> list[dict]:
        """Import eval results from a Langfuse dataset.

        Args:
            dataset_name: Name of the Langfuse dataset to import from.

        Returns:
            List of score/result dicts, each containing ``trace_id``, ``name``,
            ``value``, and ``comment``.
        """
        if self._client is not None:
            try:
                dataset = self._client.get_dataset(dataset_name)
                results: list[dict] = []
                for item in dataset.items:
                    for run in getattr(item, "runs", []):
                        for score in getattr(run, "scores", []):
                            results.append({
                                "trace_id": getattr(score, "trace_id", ""),
                                "name": getattr(score, "name", ""),
                                "value": getattr(score, "value", 0.0),
                                "comment": getattr(score, "comment", ""),
                                "dataset_name": dataset_name,
                            })
                return results
            except Exception as exc:  # noqa: BLE001
                logger.warning("Langfuse SDK import failed: %s", exc)
                return []

        try:
            import base64
            import json
            import urllib.request

            credentials = base64.b64encode(
                f"{self.public_key}:{self.secret_key}".encode()
            ).decode()
            url = f"{self.host}/api/public/datasets/{dataset_name}/items"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Basic {credentials}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return data.get("data", [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Langfuse HTTP import failed: %s", exc)
            return []
