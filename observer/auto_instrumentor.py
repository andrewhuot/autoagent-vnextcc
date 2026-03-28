"""Auto-instrumentation for LLM calls, tool invocations, and agent lifecycle."""

from __future__ import annotations

import secrets
import time
from typing import Any

from observer.exporters import OtelExporter
from observer.otel import OtelSpanAdapter
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


class AutoInstrumentor:
    """High-level API for recording OTel spans around LLM calls, tool invocations,
    agent lifecycle events, session transitions, and callback decisions.

    Spans are buffered in memory and exported in batches.  Call :meth:`flush`
    to force export of any pending spans, or configure ``max_batch_size`` on
    the underlying adapter to tune the automatic flush threshold.
    """

    def __init__(
        self,
        adapter: OtelSpanAdapter,
        exporter: OtelExporter | None = None,
        max_batch_size: int = 100,
    ) -> None:
        self._adapter = adapter
        self._exporter = exporter
        self._max_batch_size = max_batch_size
        self._pending: list[OtelSpan] = []
        self._resource = OtelResource(
            service_name=adapter.service_name,
            service_version=adapter.service_version,
            attributes={"gen_ai.system": "autoagent"},
        )

    # ------------------------------------------------------------------
    # Public instrumentation methods
    # ------------------------------------------------------------------

    def instrument_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        cost: float,
        response_status: str = "ok",
    ) -> OtelSpan:
        """Record a completed LLM call as a CLIENT span.

        Parameters
        ----------
        model:
            The model identifier (e.g. ``gpt-4o``).
        input_tokens:
            Number of prompt/input tokens consumed.
        output_tokens:
            Number of completion/output tokens generated.
        latency_ms:
            End-to-end latency of the LLM call in milliseconds.
        cost:
            Estimated monetary cost in USD.
        response_status:
            ``"ok"`` or ``"error"``; determines the span status code.
        """
        now_ns = time.time_ns()
        start_ns = now_ns - int(latency_ms * 1_000_000)
        end_ns = now_ns

        is_error = response_status.lower() not in {"ok", "success"}
        status = (
            OtelStatus(OtelStatusCode.ERROR, message=response_status)
            if is_error
            else OtelStatus(OtelStatusCode.OK)
        )

        attrs: dict[str, Any] = {
            "gen_ai.system": "autoagent",
            "gen_ai.request.model": model,
            "gen_ai.response.model": model,
            "gen_ai.usage.input_tokens": input_tokens,
            "gen_ai.usage.output_tokens": output_tokens,
            "gen_ai.cost.usd": cost,
        }

        span = OtelSpan(
            name="gen_ai.llm_call",
            context=OtelSpanContext(
                trace_id=self._new_trace_id(),
                span_id=self._new_span_id(),
            ),
            kind=OtelSpanKind.CLIENT,
            start_time_unix_nano=start_ns,
            end_time_unix_nano=end_ns,
            attributes=attrs,
            status=status,
            resource=self._resource,
        )

        # Emit a span event capturing the completion token count.
        span.events.append(
            OtelEvent(
                name="gen_ai.content.completion",
                timestamp_unix_nano=end_ns,
                attributes={
                    "gen_ai.usage.output_tokens": output_tokens,
                    "gen_ai.response.finish_reasons": [response_status],
                },
            )
        )

        self._buffer(span)
        return span

    def instrument_tool_call(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        result: Any,
        latency_ms: float,
        error: str | None = None,
    ) -> OtelSpan:
        """Record a tool invocation as an INTERNAL span.

        Parameters
        ----------
        tool_name:
            Name of the tool being invoked.
        parameters:
            Input parameters passed to the tool (stored as a truncated string).
        result:
            Return value of the tool (stored as a truncated string).
        latency_ms:
            Duration of the tool call in milliseconds.
        error:
            Optional error message; if set the span is marked as ERROR.
        """
        now_ns = time.time_ns()
        start_ns = now_ns - int(latency_ms * 1_000_000)
        end_ns = now_ns

        status = (
            OtelStatus(OtelStatusCode.ERROR, message=error)
            if error
            else OtelStatus(OtelStatusCode.OK)
        )

        attrs: dict[str, Any] = {
            "gen_ai.system": "autoagent",
            "gen_ai.tool.name": tool_name,
            "gen_ai.tool.input": str(parameters)[:2048],
        }
        if result is not None:
            attrs["gen_ai.tool.output"] = str(result)[:2048]
        if error:
            attrs["error.message"] = error

        span = OtelSpan(
            name=f"gen_ai.tool.{tool_name}",
            context=OtelSpanContext(
                trace_id=self._new_trace_id(),
                span_id=self._new_span_id(),
            ),
            kind=OtelSpanKind.INTERNAL,
            start_time_unix_nano=start_ns,
            end_time_unix_nano=end_ns,
            attributes=attrs,
            status=status,
            resource=self._resource,
        )

        self._buffer(span)
        return span

    def instrument_agent_lifecycle(
        self,
        agent_name: str,
        agent_id: str,
        event: str,
        metadata: dict[str, Any] | None = None,
    ) -> OtelSpan:
        """Record an agent lifecycle event as an INTERNAL span.

        Parameters
        ----------
        agent_name:
            Human-readable name of the agent.
        agent_id:
            Unique identifier / path of the agent.
        event:
            Lifecycle event label (e.g. ``"start"``, ``"transfer"``, ``"stop"``).
        metadata:
            Optional extra key/value pairs added to the span attributes.
        """
        now_ns = time.time_ns()

        attrs: dict[str, Any] = {
            "gen_ai.system": "autoagent",
            "gen_ai.agent.name": agent_name,
            "gen_ai.agent.id": agent_id,
            "gen_ai.agent.event": event,
        }
        if metadata:
            for k, v in metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    attrs[f"autoagent.agent.{k}"] = v

        span = OtelSpan(
            name=f"gen_ai.agent.{event}",
            context=OtelSpanContext(
                trace_id=self._new_trace_id(),
                span_id=self._new_span_id(),
            ),
            kind=OtelSpanKind.INTERNAL,
            start_time_unix_nano=now_ns,
            end_time_unix_nano=now_ns,
            attributes=attrs,
            status=OtelStatus(OtelStatusCode.OK),
            resource=self._resource,
        )

        self._buffer(span)
        return span

    def instrument_session_event(
        self,
        session_id: str,
        event: str,
        state_delta: dict[str, Any] | None = None,
    ) -> OtelSpan:
        """Record a session lifecycle event as an INTERNAL span.

        Parameters
        ----------
        session_id:
            The session identifier.
        event:
            Event label (e.g. ``"start"``, ``"end"``, ``"state_delta"``).
        state_delta:
            Optional state changes associated with this event.
        """
        now_ns = time.time_ns()

        attrs: dict[str, Any] = {
            "gen_ai.system": "autoagent",
            "session.id": session_id,
            "session.event": event,
        }
        if state_delta:
            for k, v in state_delta.items():
                if isinstance(v, (str, int, float, bool)):
                    attrs[f"session.delta.{k}"] = v

        span = OtelSpan(
            name=f"gen_ai.session.{event}",
            context=OtelSpanContext(
                trace_id=self._new_trace_id(),
                span_id=self._new_span_id(),
            ),
            kind=OtelSpanKind.INTERNAL,
            start_time_unix_nano=now_ns,
            end_time_unix_nano=now_ns,
            attributes=attrs,
            status=OtelStatus(OtelStatusCode.OK),
            resource=self._resource,
        )

        self._buffer(span)
        return span

    def instrument_callback(
        self,
        callback_type: str,
        callback_name: str,
        decision: str,
        metadata: dict[str, Any] | None = None,
    ) -> OtelSpan:
        """Record a callback (guardrail, before/after hook) as an INTERNAL span.

        Parameters
        ----------
        callback_type:
            Category of callback (e.g. ``"guardrail"``, ``"before_call"``,
            ``"after_call"``).
        callback_name:
            Specific callback identifier.
        decision:
            Outcome of the callback (e.g. ``"allow"``, ``"block"``, ``"modify"``).
        metadata:
            Optional extra key/value pairs.
        """
        now_ns = time.time_ns()

        attrs: dict[str, Any] = {
            "gen_ai.system": "autoagent",
            "callback.type": callback_type,
            "callback.name": callback_name,
            "callback.decision": decision,
        }
        if metadata:
            for k, v in metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    attrs[f"callback.{k}"] = v

        span = OtelSpan(
            name=f"gen_ai.callback.{callback_type}.{callback_name}",
            context=OtelSpanContext(
                trace_id=self._new_trace_id(),
                span_id=self._new_span_id(),
            ),
            kind=OtelSpanKind.INTERNAL,
            start_time_unix_nano=now_ns,
            end_time_unix_nano=now_ns,
            attributes=attrs,
            status=OtelStatus(OtelStatusCode.OK),
            resource=self._resource,
        )

        self._buffer(span)
        return span

    # ------------------------------------------------------------------
    # Flush / export
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Export all buffered spans immediately.

        Spans are grouped by trace_id so each :class:`~observer.otel_types.OtelTrace`
        carries only the spans that share a trace.  If no exporter is
        configured the buffer is simply cleared.
        """
        if not self._pending:
            return

        spans_to_export = list(self._pending)
        self._pending.clear()

        if self._exporter is None:
            return

        # Group spans by trace_id.
        groups: dict[str, list[OtelSpan]] = {}
        for span in spans_to_export:
            groups.setdefault(span.context.trace_id, []).append(span)

        for trace_id, group in groups.items():
            trace = OtelTrace(
                trace_id=trace_id,
                spans=group,
                resource=self._resource,
            )
            self._exporter.export(trace)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _buffer(self, span: OtelSpan) -> None:
        """Add a span to the pending buffer and auto-flush if necessary."""
        self._pending.append(span)
        if len(self._pending) >= self._max_batch_size:
            self.flush()

    @staticmethod
    def _new_span_id() -> str:
        """Generate a random 16-hex-character span ID."""
        return secrets.token_hex(8)

    @staticmethod
    def _new_trace_id() -> str:
        """Generate a random 32-hex-character trace ID."""
        return secrets.token_hex(16)
