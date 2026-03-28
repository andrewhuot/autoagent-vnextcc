"""OTel span exporters for various backends."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from observer.otel_types import OtelTrace


class OtelExporter(ABC):
    """Abstract base class for all OTel span exporters."""

    @abstractmethod
    def export(self, trace: OtelTrace) -> bool:
        """Export a trace.  Returns True on success, False on failure."""

    def shutdown(self) -> None:
        """Flush and release any held resources.  Default is a no-op."""


# ---------------------------------------------------------------------------
# Console exporter
# ---------------------------------------------------------------------------

class OtelConsoleExporter(OtelExporter):
    """Prints spans to stdout in a human-readable format (useful for development)."""

    def export(self, trace: OtelTrace) -> bool:
        """Write a formatted trace summary to stdout."""
        print(f"[OTel] Trace {trace.trace_id}  service={trace.resource.service_name}")
        for span in trace.spans:
            status_label = span.status.code.value
            print(
                f"  span={span.context.span_id}"
                f"  name={span.name}"
                f"  kind={span.kind.value}"
                f"  duration_ms={span.duration_ms:.2f}"
                f"  status={status_label}"
            )
            if span.attributes:
                for k, v in span.attributes.items():
                    print(f"    {k}={v}")
            if span.events:
                for evt in span.events:
                    print(f"    event: {evt.name}  attrs={evt.attributes}")
        return True

    def shutdown(self) -> None:
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# JSON file exporter
# ---------------------------------------------------------------------------

class OtelJsonFileExporter(OtelExporter):
    """Appends one OTLP JSON object per line to a file.

    The output is NDJSON (newline-delimited JSON) where every line is a
    complete OTLP ``ExportTraceServiceRequest`` payload.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

    def export(self, trace: OtelTrace) -> bool:
        """Append the trace as a single OTLP JSON line to the configured file."""
        try:
            otlp = trace.to_otlp_json()
            line = json.dumps(otlp, separators=(",", ":"))
            with open(self.file_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            return True
        except OSError as exc:
            print(f"[OtelJsonFileExporter] export failed: {exc}", file=sys.stderr)
            return False

    def shutdown(self) -> None:
        pass  # Nothing to flush for file-based export.


# ---------------------------------------------------------------------------
# OTLP HTTP exporter
# ---------------------------------------------------------------------------

class OtelOtlpHttpExporter(OtelExporter):
    """POSTs traces to an OTLP/HTTP endpoint.

    Uses only stdlib ``urllib`` — no external dependencies required.
    """

    def __init__(
        self,
        endpoint: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        # Normalise the endpoint to always point at the traces resource.
        if not endpoint.endswith("/v1/traces"):
            endpoint = endpoint.rstrip("/") + "/v1/traces"
        self.endpoint = endpoint
        self.headers: dict[str, str] = headers or {}
        self.timeout_seconds = timeout_seconds

    def export(self, trace: OtelTrace) -> bool:
        """POST a trace to the configured OTLP/HTTP endpoint.

        Returns True if the server responds with a 2xx status code.
        """
        try:
            payload = json.dumps(trace.to_otlp_json()).encode("utf-8")
            req = urllib.request.Request(
                url=self.endpoint,
                data=payload,
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            for key, value in self.headers.items():
                req.add_header(key, value)

            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as exc:
            print(
                f"[OtelOtlpHttpExporter] HTTP {exc.code} from {self.endpoint}",
                file=sys.stderr,
            )
            return False
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            print(
                f"[OtelOtlpHttpExporter] export failed: {exc}",
                file=sys.stderr,
            )
            return False

    def shutdown(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Cloud Trace exporter (Google Cloud)
# ---------------------------------------------------------------------------

class OtelCloudTraceExporter(OtelExporter):
    """Formats traces for the Google Cloud Trace API.

    Builds a ``BatchWriteSpans`` request body and POSTs it to
    ``https://cloudtrace.googleapis.com/v2/projects/{project}/traces:batchWrite``.

    Authentication must be handled externally (e.g. via the
    ``GOOGLE_APPLICATION_CREDENTIALS`` environment variable and the GCP
    metadata server); this exporter does not manage auth tokens.
    """

    _CLOUD_TRACE_URL = (
        "https://cloudtrace.googleapis.com/v2/projects/{project}/traces:batchWrite"
    )

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id

    def export(self, trace: OtelTrace) -> bool:
        """Convert the trace to Cloud Trace format and POST it to the API."""
        if not self.project_id:
            print("[OtelCloudTraceExporter] project_id is not set — skipping.", file=sys.stderr)
            return False

        spans = self._convert_spans(trace)
        if not spans:
            return True

        url = self._CLOUD_TRACE_URL.format(project=self.project_id)
        payload = json.dumps({"spans": spans}).encode("utf-8")
        req = urllib.request.Request(url=url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.URLError, OSError) as exc:
            print(f"[OtelCloudTraceExporter] export failed: {exc}", file=sys.stderr)
            return False

    def _convert_spans(self, trace: OtelTrace) -> list[dict[str, Any]]:
        """Convert OtelSpans to Cloud Trace v2 Span objects."""
        project = self.project_id
        result: list[dict[str, Any]] = []

        for span in trace.spans:
            ct_span: dict[str, Any] = {
                "name": f"projects/{project}/traces/{span.context.trace_id}/spans/{span.context.span_id}",
                "spanId": span.context.span_id,
                "displayName": {"value": span.name, "truncatedByteCount": 0},
                "startTime": _nano_to_rfc3339(span.start_time_unix_nano),
                "endTime": _nano_to_rfc3339(span.end_time_unix_nano),
                "attributes": {
                    "attributeMap": {
                        k: {"stringValue": {"value": str(v), "truncatedByteCount": 0}}
                        for k, v in span.attributes.items()
                    }
                },
            }
            if span.parent_span_id:
                ct_span["parentSpanId"] = span.parent_span_id
            if span.status.code.value == "ERROR":
                ct_span["status"] = {"code": 2, "message": span.status.message}
            result.append(ct_span)

        return result

    def shutdown(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class ExporterFactory:
    """Creates OtelExporter instances from configuration."""

    @staticmethod
    def create(config: dict[str, Any]) -> OtelExporter:
        """Instantiate an exporter from a config dict.

        Expected keys:
          ``exporter_type``: one of ``console``, ``json_file``, ``otlp_http``,
          ``cloud_trace``.

        Additional keys depend on the exporter type:
          - ``json_file``:   ``file_path`` (str)
          - ``otlp_http``:   ``endpoint`` (str), ``headers`` (dict), ``timeout_seconds`` (int)
          - ``cloud_trace``: ``project_id`` (str)
        """
        exporter_type = config.get("exporter_type", "console")

        if exporter_type == "console":
            return OtelConsoleExporter()

        if exporter_type == "json_file":
            file_path = config.get("file_path", "otel_traces.jsonl")
            return OtelJsonFileExporter(file_path=file_path)

        if exporter_type == "otlp_http":
            return OtelOtlpHttpExporter(
                endpoint=config.get("endpoint", "http://localhost:4318"),
                headers=config.get("headers"),
                timeout_seconds=int(config.get("timeout_seconds", 10)),
            )

        if exporter_type == "cloud_trace":
            return OtelCloudTraceExporter(project_id=config.get("project_id", ""))

        raise ValueError(f"Unknown exporter_type: {exporter_type!r}")

    @staticmethod
    def create_from_env() -> OtelExporter | None:
        """Create an exporter from the ``OTEL_EXPORTER_OTLP_ENDPOINT`` environment variable.

        Returns ``None`` if the variable is not set.
        Additional headers may be supplied via ``OTEL_EXPORTER_OTLP_HEADERS``
        as a comma-separated list of ``key=value`` pairs.
        """
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        if not endpoint:
            return None

        raw_headers = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
        headers: dict[str, str] = {}
        for pair in raw_headers.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, _, v = pair.partition("=")
                headers[k.strip()] = v.strip()

        return OtelOtlpHttpExporter(
            endpoint=endpoint,
            headers=headers or None,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _nano_to_rfc3339(unix_nano: int) -> str:
    """Convert a Unix nanosecond timestamp to an RFC 3339 / ISO-8601 string."""
    import datetime

    if unix_nano == 0:
        return "1970-01-01T00:00:00Z"
    dt = datetime.datetime.fromtimestamp(unix_nano / 1_000_000_000, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
