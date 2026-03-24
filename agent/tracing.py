"""Tracing middleware for the demo agent.

Wraps agent invocations with TraceCollector instrumentation to produce
real trace data for the observe → optimize pipeline.
"""

from __future__ import annotations

import functools
import time
import uuid
from collections.abc import Callable
from typing import Any

from observer.traces import TraceCollector, TraceStore


def _short_id() -> str:
    """Generate a 12-character UUID prefix."""
    return str(uuid.uuid4())[:12]


class TracingMiddleware:
    """Instruments agent invocations and individual tools with TraceCollector.

    Usage::

        middleware = TracingMiddleware(trace_store)
        instrumented_fn = middleware.wrap_agent_fn(original_fn, session_id="sess-abc")

    The middleware records the following event sequence per invocation:

    1. ``state_delta`` — trace start (via ``collector.start_trace``)
    2. ``model_call``  — before the agent fn executes
    3. ``model_response`` — after the agent fn returns (or ``error`` on exception)

    Individual tools wrapped with ``instrument_tool`` emit:

    1. ``tool_call``     — before the tool executes
    2. ``tool_response`` — after the tool returns (or ``error`` on exception)

    Agent transfers are recorded by inspecting the response object for an
    ``agent_transfer`` attribute, or can be triggered explicitly via
    ``record_transfer``.
    """

    # Default agent-path / branch for the root invocation context.
    ROOT_AGENT_PATH = "root"
    DEFAULT_BRANCH = "v001"

    def __init__(self, trace_store: TraceStore) -> None:
        self.store = trace_store
        self.collector = TraceCollector(store=trace_store)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def wrap_agent_fn(
        self,
        agent_fn: Callable,
        *,
        session_id: str | None = None,
        agent_path: str = ROOT_AGENT_PATH,
        branch: str = DEFAULT_BRANCH,
    ) -> Callable:
        """Return a wrapped version of *agent_fn* that emits trace events.

        The wrapper:
        - Starts a new trace before each call.
        - Records a ``model_call`` event before invoking *agent_fn*.
        - Records a ``model_response`` event on success.
        - Records an ``error`` event (and re-raises) on exception.
        - Ends the trace span on completion.

        Args:
            agent_fn: The agent callable to wrap.
            session_id: Session ID to attach to trace events. If *None* a new
                UUID is generated per call.
            agent_path: Dot-or-slash-delimited agent path (e.g. ``"root"``).
            branch: Config-version label used for A/B attribution.

        Returns:
            A callable with the same signature as *agent_fn*.
        """

        @functools.wraps(agent_fn)
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            _session_id = session_id or str(uuid.uuid4())
            _invocation_id = _short_id()

            trace_id = self.collector.start_trace(
                session_id=_session_id,
                invocation_id=_invocation_id,
                agent_path=agent_path,
                branch=branch,
            )

            # Estimate input tokens from the first positional arg if it's a
            # string (user message), otherwise use a placeholder count.
            user_message: str = args[0] if args and isinstance(args[0], str) else ""
            tokens_in = max(1, int(len(user_message.split()) * 1.3))

            self.collector.record_model_call(
                trace_id=trace_id,
                tokens_in=tokens_in,
                agent_path=agent_path,
                session_id=_session_id,
                invocation_id=_invocation_id,
                branch=branch,
            )

            start = time.monotonic()
            try:
                result = agent_fn(*args, **kwargs)
            except Exception as exc:
                latency_ms = (time.monotonic() - start) * 1000
                self.collector.record_error(
                    trace_id=trace_id,
                    error_message=str(exc),
                    agent_path=agent_path,
                    session_id=_session_id,
                    invocation_id=_invocation_id,
                    branch=branch,
                )
                # Record a partial model_response so timing is always captured.
                self.collector.record_model_response(
                    trace_id=trace_id,
                    tokens_out=0,
                    latency_ms=latency_ms,
                    agent_path=agent_path,
                    session_id=_session_id,
                    invocation_id=_invocation_id,
                    branch=branch,
                )
                raise

            latency_ms = (time.monotonic() - start) * 1000

            # Estimate output tokens from the result if it's a string.
            response_text: str = result if isinstance(result, str) else ""
            tokens_out = max(1, int(len(response_text.split()) * 1.3))

            # Check for agent-transfer hints in the result dict.
            if isinstance(result, dict):
                to_agent = result.get("agent_transfer") or result.get("specialist")
                if to_agent:
                    self.collector.record_agent_transfer(
                        trace_id=trace_id,
                        from_agent=agent_path,
                        to_agent=str(to_agent),
                        session_id=_session_id,
                        invocation_id=_invocation_id,
                        branch=branch,
                    )

            self.collector.record_model_response(
                trace_id=trace_id,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                agent_path=agent_path,
                session_id=_session_id,
                invocation_id=_invocation_id,
                branch=branch,
            )

            return result

        return _wrapped

    def instrument_tool(
        self,
        tool_fn: Callable,
        tool_name: str,
        *,
        session_id: str | None = None,
        agent_path: str = ROOT_AGENT_PATH,
        branch: str = DEFAULT_BRANCH,
        trace_id_provider: Callable[[], str | None] | None = None,
    ) -> Callable:
        """Wrap *tool_fn* with tool_call / tool_response trace recording.

        Each call to the wrapped function emits a ``tool_call`` event before
        execution and a ``tool_response`` (or ``error``) event after.

        Args:
            tool_fn: The tool callable to wrap.
            tool_name: Human-readable name stored in trace events.
            session_id: Session ID. Generated per call if *None*.
            agent_path: Agent path attributed to the tool events.
            branch: Config-version label.
            trace_id_provider: Optional zero-argument callable that returns the
                active trace ID. When provided, tool events are correlated to
                the parent trace; otherwise a new trace is started per call.

        Returns:
            A callable with the same signature as *tool_fn*.
        """

        @functools.wraps(tool_fn)
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            _session_id = session_id or str(uuid.uuid4())
            _invocation_id = _short_id()

            # Resolve or create a trace ID for this tool call.
            if trace_id_provider is not None:
                _trace_id = trace_id_provider() or self.collector.start_trace(
                    session_id=_session_id,
                    invocation_id=_invocation_id,
                    agent_path=agent_path,
                    branch=branch,
                )
            else:
                _trace_id = self.collector.start_trace(
                    session_id=_session_id,
                    invocation_id=_invocation_id,
                    agent_path=agent_path,
                    branch=branch,
                )

            # Build tool_input from args/kwargs.
            tool_input: dict[str, Any] = dict(kwargs)
            if args:
                tool_input["_args"] = list(args)

            self.collector.record_tool_call(
                trace_id=_trace_id,
                tool_name=tool_name,
                tool_input=tool_input,
                agent_path=agent_path,
                session_id=_session_id,
                invocation_id=_invocation_id,
                branch=branch,
            )

            start = time.monotonic()
            try:
                result = tool_fn(*args, **kwargs)
            except Exception as exc:
                latency_ms = (time.monotonic() - start) * 1000
                self.collector.record_tool_response(
                    trace_id=_trace_id,
                    tool_name=tool_name,
                    tool_output={},
                    latency_ms=latency_ms,
                    agent_path=agent_path,
                    session_id=_session_id,
                    invocation_id=_invocation_id,
                    branch=branch,
                    error=str(exc),
                )
                raise

            latency_ms = (time.monotonic() - start) * 1000

            # Normalise result to a JSON-serialisable dict.
            if isinstance(result, dict):
                tool_output: dict[str, Any] = result
            elif isinstance(result, list):
                tool_output = {"results": result}
            elif result is None:
                tool_output = {}
            else:
                tool_output = {"result": result}

            self.collector.record_tool_response(
                trace_id=_trace_id,
                tool_name=tool_name,
                tool_output=tool_output,
                latency_ms=latency_ms,
                agent_path=agent_path,
                session_id=_session_id,
                invocation_id=_invocation_id,
                branch=branch,
            )

            return result

        return _wrapped

    def record_transfer(
        self,
        trace_id: str,
        from_agent: str,
        to_agent: str,
        session_id: str,
        invocation_id: str,
        branch: str = DEFAULT_BRANCH,
    ) -> str:
        """Explicitly record an agent-transfer event.

        Delegates directly to ``TraceCollector.record_agent_transfer`` for
        callers that control their own trace IDs (e.g. the ADK event loop).

        Returns:
            The event_id of the recorded transfer event.
        """
        return self.collector.record_agent_transfer(
            trace_id=trace_id,
            from_agent=from_agent,
            to_agent=to_agent,
            session_id=session_id,
            invocation_id=invocation_id,
            branch=branch,
        )
