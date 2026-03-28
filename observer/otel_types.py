"""Pure-Python OpenTelemetry types for GenAI semantic conventions.

No dependency on opentelemetry-sdk — these are serializable dataclasses
that match the OTel data model for traces, spans, and events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass
class OtelResource:
    """Describes the entity producing telemetry (the service/process)."""

    service_name: str
    service_version: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "service_name": self.service_name,
            "service_version": self.service_version,
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OtelResource":
        """Deserialize from a plain dict."""
        return cls(
            service_name=data["service_name"],
            service_version=data["service_version"],
            attributes=dict(data.get("attributes", {})),
        )


@dataclass
class OtelSpanContext:
    """Immutable portion of a span that is propagated to child spans and across process boundaries."""

    trace_id: str
    span_id: str
    trace_flags: int = 1  # 1 = sampled

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "trace_flags": self.trace_flags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OtelSpanContext":
        return cls(
            trace_id=data["trace_id"],
            span_id=data["span_id"],
            trace_flags=data.get("trace_flags", 1),
        )


class OtelSpanKind(str, Enum):
    """The role a span plays in a distributed trace."""

    INTERNAL = "INTERNAL"
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


class OtelStatusCode(str, Enum):
    """The status code of a span's outcome."""

    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


@dataclass
class OtelStatus:
    """The status of a completed span."""

    code: OtelStatusCode
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OtelStatus":
        return cls(
            code=OtelStatusCode(data["code"]),
            message=data.get("message", ""),
        )


@dataclass
class OtelEvent:
    """A time-stamped annotation attached to a span."""

    name: str
    timestamp_unix_nano: int
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "timestamp_unix_nano": self.timestamp_unix_nano,
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OtelEvent":
        return cls(
            name=data["name"],
            timestamp_unix_nano=data["timestamp_unix_nano"],
            attributes=dict(data.get("attributes", {})),
        )


@dataclass
class OtelLink:
    """A pointer from a span to another span in the same or a different trace."""

    trace_id: str
    span_id: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OtelLink":
        return cls(
            trace_id=data["trace_id"],
            span_id=data["span_id"],
            attributes=dict(data.get("attributes", {})),
        )


@dataclass
class OtelSpan:
    """A single unit of work within a distributed trace, matching the OTel data model."""

    name: str
    context: OtelSpanContext
    parent_span_id: str = ""
    kind: OtelSpanKind = OtelSpanKind.INTERNAL
    start_time_unix_nano: int = 0
    end_time_unix_nano: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[OtelEvent] = field(default_factory=list)
    links: list[OtelLink] = field(default_factory=list)
    status: OtelStatus = field(default_factory=lambda: OtelStatus(OtelStatusCode.UNSET))
    resource: OtelResource | None = None
    instrumentation_scope: str = "autoagent"

    @property
    def duration_ms(self) -> float:
        """Duration of the span in milliseconds."""
        if self.start_time_unix_nano == 0 or self.end_time_unix_nano == 0:
            return 0.0
        return (self.end_time_unix_nano - self.start_time_unix_nano) / 1_000_000.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (not OTLP wire format — use OtelTrace.to_otlp_json() for that)."""
        return {
            "name": self.name,
            "context": self.context.to_dict(),
            "parent_span_id": self.parent_span_id,
            "kind": self.kind.value,
            "start_time_unix_nano": self.start_time_unix_nano,
            "end_time_unix_nano": self.end_time_unix_nano,
            "duration_ms": self.duration_ms,
            "attributes": dict(self.attributes),
            "events": [e.to_dict() for e in self.events],
            "links": [lnk.to_dict() for lnk in self.links],
            "status": self.status.to_dict(),
            "resource": self.resource.to_dict() if self.resource else None,
            "instrumentation_scope": self.instrumentation_scope,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OtelSpan":
        """Deserialize from a plain dict."""
        resource_data = data.get("resource")
        return cls(
            name=data["name"],
            context=OtelSpanContext.from_dict(data["context"]),
            parent_span_id=data.get("parent_span_id", ""),
            kind=OtelSpanKind(data.get("kind", OtelSpanKind.INTERNAL.value)),
            start_time_unix_nano=data.get("start_time_unix_nano", 0),
            end_time_unix_nano=data.get("end_time_unix_nano", 0),
            attributes=dict(data.get("attributes", {})),
            events=[OtelEvent.from_dict(e) for e in data.get("events", [])],
            links=[OtelLink.from_dict(lnk) for lnk in data.get("links", [])],
            status=OtelStatus.from_dict(data["status"]) if "status" in data else OtelStatus(OtelStatusCode.UNSET),
            resource=OtelResource.from_dict(resource_data) if resource_data else None,
            instrumentation_scope=data.get("instrumentation_scope", "autoagent"),
        )


@dataclass
class OtelTrace:
    """A complete trace consisting of one or more spans sharing a trace_id."""

    trace_id: str
    spans: list[OtelSpan]
    resource: OtelResource

    def to_otlp_json(self) -> dict[str, Any]:
        """Serialize to OTLP JSON format suitable for export to an OTLP collector.

        Follows the OTLP/JSON encoding defined at:
        https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding
        """
        # Build resource attributes list in OTel key-value format
        resource_attrs = [
            {"key": "service.name", "value": {"stringValue": self.resource.service_name}},
            {"key": "service.version", "value": {"stringValue": self.resource.service_version}},
        ]
        for k, v in self.resource.attributes.items():
            resource_attrs.append({"key": k, "value": _to_otlp_any_value(v)})

        # Group spans by instrumentation scope
        scope_spans_map: dict[str, list[dict[str, Any]]] = {}
        for span in self.spans:
            scope = span.instrumentation_scope
            scope_spans_map.setdefault(scope, []).append(_span_to_otlp(span))

        scope_spans = [
            {
                "scope": {"name": scope_name, "version": "1.0.0"},
                "spans": spans,
            }
            for scope_name, spans in scope_spans_map.items()
        ]

        return {
            "resourceSpans": [
                {
                    "resource": {"attributes": resource_attrs},
                    "scopeSpans": scope_spans,
                }
            ]
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "trace_id": self.trace_id,
            "spans": [s.to_dict() for s in self.spans],
            "resource": self.resource.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OtelTrace":
        """Deserialize from a plain dict."""
        return cls(
            trace_id=data["trace_id"],
            spans=[OtelSpan.from_dict(s) for s in data.get("spans", [])],
            resource=OtelResource.from_dict(data["resource"]),
        )


# ---------------------------------------------------------------------------
# Internal OTLP serialisation helpers
# ---------------------------------------------------------------------------

def _to_otlp_any_value(value: Any) -> dict[str, Any]:
    """Convert a Python value to an OTLP AnyValue dict."""
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_to_otlp_any_value(v) for v in value]}}
    if isinstance(value, dict):
        return {
            "kvlistValue": {
                "values": [{"key": k, "value": _to_otlp_any_value(v)} for k, v in value.items()]
            }
        }
    # Fallback: stringify
    return {"stringValue": str(value)}


_SPAN_KIND_INT = {
    OtelSpanKind.INTERNAL: 1,
    OtelSpanKind.SERVER: 2,
    OtelSpanKind.CLIENT: 3,
    OtelSpanKind.PRODUCER: 4,
    OtelSpanKind.CONSUMER: 5,
}

_STATUS_CODE_INT = {
    OtelStatusCode.UNSET: 0,
    OtelStatusCode.OK: 1,
    OtelStatusCode.ERROR: 2,
}


def _span_to_otlp(span: OtelSpan) -> dict[str, Any]:
    """Convert an OtelSpan to the OTLP JSON span object format."""
    attrs = [{"key": k, "value": _to_otlp_any_value(v)} for k, v in span.attributes.items()]
    events = [
        {
            "name": e.name,
            "timeUnixNano": str(e.timestamp_unix_nano),
            "attributes": [{"key": k, "value": _to_otlp_any_value(v)} for k, v in e.attributes.items()],
        }
        for e in span.events
    ]
    links = [
        {
            "traceId": lnk.trace_id,
            "spanId": lnk.span_id,
            "attributes": [{"key": k, "value": _to_otlp_any_value(v)} for k, v in lnk.attributes.items()],
        }
        for lnk in span.links
    ]
    result: dict[str, Any] = {
        "traceId": span.context.trace_id,
        "spanId": span.context.span_id,
        "name": span.name,
        "kind": _SPAN_KIND_INT.get(span.kind, 1),
        "startTimeUnixNano": str(span.start_time_unix_nano),
        "endTimeUnixNano": str(span.end_time_unix_nano),
        "attributes": attrs,
        "events": events,
        "links": links,
        "status": {
            "code": _STATUS_CODE_INT.get(span.status.code, 0),
            "message": span.status.message,
        },
    }
    if span.parent_span_id:
        result["parentSpanId"] = span.parent_span_id
    return result
