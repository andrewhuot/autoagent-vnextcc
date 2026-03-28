"""OTel observability configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OtelConfig:
    """Configuration for OpenTelemetry-based observability.

    All fields have safe defaults so the system works out of the box with
    OTel disabled.  Set ``enabled=True`` (or ``OTEL_ENABLED=true`` in the
    environment) to activate tracing.
    """

    # Master switch — no spans are exported when False.
    enabled: bool = False

    # Exporter backend: console | json_file | otlp_http | cloud_trace
    exporter_type: str = "otlp_http"

    # OTLP/HTTP endpoint (used when exporter_type == "otlp_http").
    endpoint: str = ""

    # Extra HTTP headers forwarded to the OTLP endpoint (e.g. auth tokens).
    headers: dict[str, str] = field(default_factory=dict)

    # Service identity stamped on every resource.
    service_name: str = "autoagent"
    service_version: str = "1.0.0"

    # Google Cloud Trace project ID (used when exporter_type == "cloud_trace").
    cloud_trace_project_id: str = ""

    # Batching settings.
    export_interval_seconds: int = 30
    max_batch_size: int = 100

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the config to a plain dict."""
        return {
            "enabled": self.enabled,
            "exporter_type": self.exporter_type,
            "endpoint": self.endpoint,
            "headers": dict(self.headers),
            "service_name": self.service_name,
            "service_version": self.service_version,
            "cloud_trace_project_id": self.cloud_trace_project_id,
            "export_interval_seconds": self.export_interval_seconds,
            "max_batch_size": self.max_batch_size,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OtelConfig":
        """Deserialize from a plain dict.  Unknown keys are silently ignored."""
        return cls(
            enabled=bool(data.get("enabled", False)),
            exporter_type=str(data.get("exporter_type", "otlp_http")),
            endpoint=str(data.get("endpoint", "")),
            headers=dict(data.get("headers", {})),
            service_name=str(data.get("service_name", "autoagent")),
            service_version=str(data.get("service_version", "1.0.0")),
            cloud_trace_project_id=str(data.get("cloud_trace_project_id", "")),
            export_interval_seconds=int(data.get("export_interval_seconds", 30)),
            max_batch_size=int(data.get("max_batch_size", 100)),
        )

    # ------------------------------------------------------------------
    # Environment variable loader
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "OtelConfig":
        """Build an OtelConfig by reading well-known environment variables.

        Variable names follow the OTel specification where possible:

        ========================= =======================================
        Variable                  Field
        ========================= =======================================
        ``OTEL_ENABLED``          ``enabled`` (any truthy string)
        ``OTEL_EXPORTER_TYPE``    ``exporter_type``
        ``OTEL_EXPORTER_OTLP_ENDPOINT`` ``endpoint``
        ``OTEL_EXPORTER_OTLP_HEADERS``  ``headers`` (``k=v,k2=v2``)
        ``OTEL_SERVICE_NAME``     ``service_name``
        ``OTEL_SERVICE_VERSION``  ``service_version``
        ``CLOUD_TRACE_PROJECT_ID``  ``cloud_trace_project_id``
        ``OTEL_EXPORT_INTERVAL_SECONDS`` ``export_interval_seconds``
        ``OTEL_MAX_BATCH_SIZE``   ``max_batch_size``
        ========================= =======================================
        """
        raw_enabled = os.environ.get("OTEL_ENABLED", "false").lower()
        enabled = raw_enabled in {"1", "true", "yes", "on"}

        raw_headers = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
        headers: dict[str, str] = {}
        for pair in raw_headers.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, _, v = pair.partition("=")
                headers[k.strip()] = v.strip()

        return cls(
            enabled=enabled,
            exporter_type=os.environ.get("OTEL_EXPORTER_TYPE", "otlp_http"),
            endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            headers=headers,
            service_name=os.environ.get("OTEL_SERVICE_NAME", "autoagent"),
            service_version=os.environ.get("OTEL_SERVICE_VERSION", "1.0.0"),
            cloud_trace_project_id=os.environ.get("CLOUD_TRACE_PROJECT_ID", ""),
            export_interval_seconds=int(
                os.environ.get("OTEL_EXPORT_INTERVAL_SECONDS", "30")
            ),
            max_batch_size=int(os.environ.get("OTEL_MAX_BATCH_SIZE", "100")),
        )


# ---------------------------------------------------------------------------
# YAML config loader
# ---------------------------------------------------------------------------

def load_otel_config(yaml_config: dict[str, Any]) -> OtelConfig:
    """Build an OtelConfig from the ``observability`` section of ``autoagent.yaml``.

    The expected structure is::

        observability:
          otel_enabled: false
          otel_exporter: otlp_http
          otel_endpoint: ""
          otel_service_name: autoagent
          cloud_trace_project_id: ""

    Any keys not present fall back to :class:`OtelConfig` defaults.
    """
    obs: dict[str, Any] = yaml_config.get("observability", {}) if yaml_config else {}

    return OtelConfig(
        enabled=bool(obs.get("otel_enabled", False)),
        exporter_type=str(obs.get("otel_exporter", "otlp_http")),
        endpoint=str(obs.get("otel_endpoint", "")),
        headers=dict(obs.get("otel_headers", {})),
        service_name=str(obs.get("otel_service_name", "autoagent")),
        service_version=str(obs.get("otel_service_version", "1.0.0")),
        cloud_trace_project_id=str(obs.get("cloud_trace_project_id", "")),
        export_interval_seconds=int(obs.get("export_interval_seconds", 30)),
        max_batch_size=int(obs.get("max_batch_size", 100)),
    )
