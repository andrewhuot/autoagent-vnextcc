"""Adapter converting AutoAgent trace events to OpenTelemetry spans.

Maps to GenAI semantic conventions (gen_ai.* namespace) per
https://opentelemetry.io/docs/specs/semconv/gen-ai/
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from typing import Any

from observer.otel_types import (
    OtelEvent,
    OtelResource,
    OtelSpan,
    OtelSpanContext,
    OtelSpanKind,
    OtelStatus,
    OtelStatusCode,
    OtelTrace,
)

# ---------------------------------------------------------------------------
# GenAI semantic attribute names
# ---------------------------------------------------------------------------

GENAI_ATTRIBUTES: dict[str, str] = {
    # System identity
    "system": "gen_ai.system",
    # Request attributes
    "request.model": "gen_ai.request.model",
    "request.max_tokens": "gen_ai.request.max_tokens",
    "request.temperature": "gen_ai.request.temperature",
    # Response attributes
    "response.model": "gen_ai.response.model",
    "response.finish_reasons": "gen_ai.response.finish_reasons",
    # Usage counters
    "usage.input_tokens": "gen_ai.usage.input_tokens",
    "usage.output_tokens": "gen_ai.usage.output_tokens",
    # Agent attributes
    "agent.name": "gen_ai.agent.name",
    "agent.id": "gen_ai.agent.id",
    # Tool attributes
    "tool.name": "gen_ai.tool.name",
    "tool.call.id": "gen_ai.tool.call.id",
}

# Map AutoAgent event_type values to span creation strategies
_EVENT_TYPE_MAP: dict[str, str] = {
    "model_call": "llm",
    "model_response": "llm",
    "tool_call": "tool",
    "tool_response": "tool",
    "agent_transfer": "agent",
    "state_delta": "session",
    "artifact_delta": "session",
    "error": "session",
    "safety_flag": "session",
    "partial_response": "session",
}


class OtelSpanAdapter:
    """Converts AutoAgent trace events into OTel spans with GenAI semantic attributes."""

    def __init__(
        self,
        service_name: str = "autoagent",
        service_version: str = "1.0.0",
    ) -> None:
        self.service_name = service_name
        self.service_version = service_version
        self._resource = OtelResource(
            service_name=service_name,
            service_version=service_version,
            attributes={"gen_ai.system": "autoagent"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def convert_trace_event(self, event: dict[str, Any]) -> OtelSpan:
        """Convert a single AutoAgent trace event dict to an OtelSpan.

        The event dict is expected to carry the same fields as TraceEvent.
        """
        trace_id = event.get("trace_id") or self._generate_trace_id()
        return self._map_event_to_span(event, trace_id)

    def convert_trace(
        self,
        events: list[dict[str, Any]],
        trace_id: str | None = None,
    ) -> OtelTrace:
        """Convert a full list of trace event dicts to an OtelTrace.

        If *trace_id* is not given, it is taken from the first event or
        generated fresh.
        """
        if not trace_id:
            trace_id = (events[0].get("trace_id") if events else None) or self._generate_trace_id()

        spans = [self._map_event_to_span(e, trace_id) for e in events]
        return OtelTrace(
            trace_id=trace_id,
            spans=spans,
            resource=self._resource,
        )

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _map_event_to_span(self, event: dict[str, Any], trace_id: str) -> OtelSpan:
        """Dispatch to the appropriate span-creation helper based on event_type."""
        event_type = event.get("event_type", "")
        strategy = _EVENT_TYPE_MAP.get(event_type, "session")

        if strategy == "llm":
            return self._create_llm_span(event, trace_id)
        if strategy == "tool":
            return self._create_tool_span(event, trace_id)
        if strategy == "agent":
            return self._create_agent_span(event, trace_id)
        return self._create_session_span(event, trace_id)

    # ------------------------------------------------------------------
    # Span creation helpers
    # ------------------------------------------------------------------

    def _create_llm_span(self, event: dict[str, Any], trace_id: str) -> OtelSpan:
        """Create a CLIENT span representing an LLM call with token counts."""
        event_type = event.get("event_type", "model_call")
        span_name = "gen_ai.model_call" if event_type == "model_call" else "gen_ai.model_response"

        start_nano = self._to_unix_nano(event.get("timestamp", time.time()))
        latency_ns = int(event.get("latency_ms", 0) * 1_000_000)
        end_nano = start_nano + latency_ns if latency_ns else start_nano

        attrs = self._extract_genai_attributes(event)
        attrs["gen_ai.system"] = "autoagent"
        tokens_in = event.get("tokens_in", 0) or 0
        tokens_out = event.get("tokens_out", 0) or 0
        if tokens_in:
            attrs["gen_ai.usage.input_tokens"] = tokens_in
        if tokens_out:
            attrs["gen_ai.usage.output_tokens"] = tokens_out
        if event.get("agent_path"):
            attrs["gen_ai.agent.name"] = event["agent_path"]

        error_msg = event.get("error_message")
        status = (
            OtelStatus(OtelStatusCode.ERROR, message=str(error_msg))
            if error_msg
            else OtelStatus(OtelStatusCode.OK)
        )

        span = OtelSpan(
            name=span_name,
            context=OtelSpanContext(
                trace_id=trace_id,
                span_id=self._generate_span_id(),
            ),
            parent_span_id="",
            kind=OtelSpanKind.CLIENT,
            start_time_unix_nano=start_nano,
            end_time_unix_nano=end_nano,
            attributes=attrs,
            status=status,
            resource=self._resource,
        )

        # Add a span event for the LLM response if tokens are present
        if tokens_out and event_type == "model_response":
            span.events.append(
                OtelEvent(
                    name="gen_ai.content.completion",
                    timestamp_unix_nano=end_nano,
                    attributes={"gen_ai.usage.output_tokens": tokens_out},
                )
            )

        return span

    def _create_tool_span(self, event: dict[str, Any], trace_id: str) -> OtelSpan:
        """Create an INTERNAL span representing a tool invocation."""
        tool_name = event.get("tool_name") or "unknown_tool"
        event_type = event.get("event_type", "tool_call")
        span_name = f"gen_ai.tool.{tool_name}"

        start_nano = self._to_unix_nano(event.get("timestamp", time.time()))
        latency_ns = int(event.get("latency_ms", 0) * 1_000_000)
        end_nano = start_nano + latency_ns if latency_ns else start_nano

        attrs = self._extract_genai_attributes(event)
        attrs["gen_ai.tool.name"] = tool_name
        attrs["gen_ai.system"] = "autoagent"
        if event.get("agent_path"):
            attrs["gen_ai.agent.name"] = event["agent_path"]
        if event.get("tool_input"):
            attrs["gen_ai.tool.input"] = str(event["tool_input"])[:1024]
        if event.get("tool_output") and event_type == "tool_response":
            attrs["gen_ai.tool.output"] = str(event["tool_output"])[:1024]

        error_msg = event.get("error_message")
        status = (
            OtelStatus(OtelStatusCode.ERROR, message=str(error_msg))
            if error_msg
            else OtelStatus(OtelStatusCode.OK)
        )

        span = OtelSpan(
            name=span_name,
            context=OtelSpanContext(
                trace_id=trace_id,
                span_id=self._generate_span_id(),
            ),
            parent_span_id="",
            kind=OtelSpanKind.INTERNAL,
            start_time_unix_nano=start_nano,
            end_time_unix_nano=end_nano,
            attributes=attrs,
            status=status,
            resource=self._resource,
        )

        return span

    def _create_agent_span(self, event: dict[str, Any], trace_id: str) -> OtelSpan:
        """Create a span representing agent lifecycle events (transfers, etc.)."""
        metadata = event.get("metadata") or {}
        from_agent = metadata.get("from_agent", event.get("agent_path", "unknown"))
        to_agent = metadata.get("to_agent", "unknown")
        span_name = f"gen_ai.agent.transfer.{from_agent}.to.{to_agent}"

        start_nano = self._to_unix_nano(event.get("timestamp", time.time()))
        end_nano = start_nano

        attrs = self._extract_genai_attributes(event)
        attrs["gen_ai.system"] = "autoagent"
        attrs["gen_ai.agent.name"] = from_agent
        attrs["gen_ai.agent.transfer.destination"] = to_agent
        if event.get("agent_path"):
            attrs["gen_ai.agent.id"] = event["agent_path"]

        span = OtelSpan(
            name=span_name,
            context=OtelSpanContext(
                trace_id=trace_id,
                span_id=self._generate_span_id(),
            ),
            parent_span_id="",
            kind=OtelSpanKind.INTERNAL,
            start_time_unix_nano=start_nano,
            end_time_unix_nano=end_nano,
            attributes=attrs,
            status=OtelStatus(OtelStatusCode.OK),
            resource=self._resource,
        )

        return span

    def _create_session_span(self, event: dict[str, Any], trace_id: str) -> OtelSpan:
        """Create a span representing session lifecycle / state events."""
        event_type = event.get("event_type", "session_event")
        span_name = f"gen_ai.session.{event_type}"

        start_nano = self._to_unix_nano(event.get("timestamp", time.time()))
        latency_ns = int(event.get("latency_ms", 0) * 1_000_000)
        end_nano = start_nano + latency_ns if latency_ns else start_nano

        attrs = self._extract_genai_attributes(event)
        attrs["gen_ai.system"] = "autoagent"
        if event.get("session_id"):
            attrs["session.id"] = event["session_id"]
        if event.get("invocation_id"):
            attrs["invocation.id"] = event["invocation_id"]
        if event.get("agent_path"):
            attrs["gen_ai.agent.name"] = event["agent_path"]

        error_msg = event.get("error_message")
        is_error = event_type == "error" or bool(error_msg)
        status = (
            OtelStatus(OtelStatusCode.ERROR, message=str(error_msg) if error_msg else event_type)
            if is_error
            else OtelStatus(OtelStatusCode.OK)
        )

        span = OtelSpan(
            name=span_name,
            context=OtelSpanContext(
                trace_id=trace_id,
                span_id=self._generate_span_id(),
            ),
            parent_span_id="",
            kind=OtelSpanKind.INTERNAL,
            start_time_unix_nano=start_nano,
            end_time_unix_nano=end_nano,
            attributes=attrs,
            status=status,
            resource=self._resource,
        )

        return span

    # ------------------------------------------------------------------
    # Attribute extraction
    # ------------------------------------------------------------------

    def _extract_genai_attributes(self, event: dict[str, Any]) -> dict[str, Any]:
        """Extract and map GenAI semantic attributes from a raw event dict."""
        attrs: dict[str, Any] = {}

        # Branch/version label maps to a deployment attribute
        if event.get("branch"):
            attrs["deployment.environment"] = event["branch"]

        # Metadata passthrough (string values only for OTel compatibility)
        metadata = event.get("metadata") or {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                attrs[f"autoagent.{k}"] = v

        return attrs

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_span_id() -> str:
        """Generate a random 16-hex-character span ID."""
        return secrets.token_hex(8)  # 8 bytes = 16 hex chars

    @staticmethod
    def _generate_trace_id() -> str:
        """Generate a random 32-hex-character trace ID."""
        return secrets.token_hex(16)  # 16 bytes = 32 hex chars

    def _to_unix_nano(self, timestamp: float | str) -> int:
        """Convert a timestamp (float epoch seconds or ISO-8601 string) to Unix nanoseconds."""
        if isinstance(timestamp, str):
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                return int(dt.timestamp() * 1_000_000_000)
            except ValueError:
                # Fall back to current time if parsing fails
                return time.time_ns()
        # Assume epoch seconds (float or int)
        return int(float(timestamp) * 1_000_000_000)
