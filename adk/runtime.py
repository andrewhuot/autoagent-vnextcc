"""ADK Runtime Adapter for executing agents with AutoAgent tracing."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from .types import AdkSessionConfig
from .template_vars import resolve_template_vars


@dataclass
class AdkExecutionResult:
    """Result of a single ADK agent execution."""

    success: bool
    output: str
    trace_events: list[dict] = field(default_factory=list)
    tokens_used: int = 0
    latency_ms: float = 0.0
    state_snapshot: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class AdkRuntimeAdapter:
    """Adapter that executes ADK agents and produces AutoAgent-compatible trace events.

    This class wraps the ADK execution loop with AutoAgent instrumentation so
    that every invocation produces structured trace events, token counts, and a
    final state snapshot. The implementation is intentionally dependency-light:
    the actual ADK SDK is imported lazily so that the module can be imported in
    environments that do not have the SDK installed (tests, CI, etc.).
    """

    def __init__(
        self,
        agent_config: dict,
        session_config: AdkSessionConfig | None = None,
    ) -> None:
        """Initialise the runtime adapter.

        Args:
            agent_config: Raw agent configuration dict (as produced by AdkMapper
                or loaded from config.json).
            session_config: Optional session-level configuration. When omitted a
                default AdkSessionConfig is used.
        """
        self._agent_config = agent_config
        self._session_config = session_config or AdkSessionConfig()

    # ------------------------------------------------------------------
    # Public execution methods
    # ------------------------------------------------------------------

    def execute(
        self,
        user_message: str,
        session_state: dict | None = None,
    ) -> AdkExecutionResult:
        """Execute the agent synchronously and return a full result.

        If the Google ADK SDK is available the agent is run via the SDK runner.
        Otherwise a lightweight stub execution is performed so that the rest of
        the AutoAgent pipeline can function in offline / test mode.

        Args:
            user_message: The human turn message to send to the agent.
            session_state: Optional initial session state dict.

        Returns:
            An AdkExecutionResult with output, trace events and metrics.
        """
        state = dict(session_state or {})
        start = time.monotonic()
        errors: list[str] = []
        output = ""
        trace_events: list[dict] = []
        tokens_used = 0

        # Resolve template variables in the instruction before execution.
        instruction = self._agent_config.get("instruction", "")
        resolved_instruction = resolve_template_vars(instruction, state)

        try:
            sdk_result = self._try_adk_sdk_execute(
                user_message=user_message,
                resolved_instruction=resolved_instruction,
                state=state,
            )
            output = sdk_result.get("output", "")
            tokens_used = sdk_result.get("tokens_used", 0)
            raw_events = sdk_result.get("raw_events", [])
            state.update(sdk_result.get("state_delta", {}))
            trace_events = self._build_trace_events(
                user_message=user_message,
                output=output,
                raw_events=raw_events,
                state=state,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            output = ""

        latency_ms = (time.monotonic() - start) * 1000.0

        return AdkExecutionResult(
            success=len(errors) == 0,
            output=output,
            trace_events=trace_events,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            state_snapshot=dict(state),
            errors=errors,
        )

    def execute_streaming(
        self,
        user_message: str,
        session_state: dict | None = None,
    ) -> Iterator[dict]:
        """Stream agent execution events as they are produced.

        Each yielded dict has at minimum a ``type`` key and a ``data`` key.
        Possible event types:

        - ``"token"``: a streaming output token
        - ``"trace"``: a structured trace event
        - ``"state"``: a state update
        - ``"error"``: an error event
        - ``"done"``: final event with the full AdkExecutionResult serialised

        Args:
            user_message: The human turn message to send to the agent.
            session_state: Optional initial session state dict.

        Yields:
            Structured event dicts suitable for SSE encoding.
        """
        state = dict(session_state or {})
        start = time.monotonic()
        errors: list[str] = []
        tokens_used = 0
        output_parts: list[str] = []
        trace_events: list[dict] = []

        instruction = self._agent_config.get("instruction", "")
        resolved_instruction = resolve_template_vars(instruction, state)

        try:
            for chunk in self._try_adk_sdk_stream(
                user_message=user_message,
                resolved_instruction=resolved_instruction,
                state=state,
            ):
                chunk_type = chunk.get("type", "token")
                if chunk_type == "token":
                    token_text = chunk.get("text", "")
                    output_parts.append(token_text)
                    yield {"type": "token", "data": {"text": token_text}}
                elif chunk_type == "trace":
                    trace_events.append(chunk.get("event", {}))
                    yield {"type": "trace", "data": chunk.get("event", {})}
                elif chunk_type == "state_delta":
                    delta = chunk.get("delta", {})
                    state.update(delta)
                    yield {"type": "state", "data": {"delta": delta}}
                elif chunk_type == "usage":
                    tokens_used = chunk.get("tokens", 0)
                else:
                    yield {"type": chunk_type, "data": chunk}
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            yield {"type": "error", "data": {"message": str(exc)}}

        output = "".join(output_parts)
        latency_ms = (time.monotonic() - start) * 1000.0
        final_result = AdkExecutionResult(
            success=len(errors) == 0,
            output=output,
            trace_events=trace_events,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            state_snapshot=dict(state),
            errors=errors,
        )
        yield {
            "type": "done",
            "data": {
                "success": final_result.success,
                "output": final_result.output,
                "tokens_used": final_result.tokens_used,
                "latency_ms": final_result.latency_ms,
                "errors": final_result.errors,
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_trace_events(
        self,
        user_message: str,
        output: str,
        raw_events: list[Any],
        state: dict,
    ) -> list[dict]:
        """Convert raw ADK execution events into AutoAgent trace event dicts.

        The resulting list is ordered chronologically. Each event has:
        - ``event_id``: monotonically increasing integer string
        - ``event_type``: one of ``user_turn``, ``model_turn``, ``tool_call``,
          ``tool_result``, ``state_update``
        - ``data``: event-specific payload dict

        Args:
            user_message: The original user message.
            output: The final agent output text.
            raw_events: Raw events from the ADK SDK runner (may be empty).
            state: Final state snapshot.

        Returns:
            Ordered list of AutoAgent-format trace event dicts.
        """
        events: list[dict] = []
        counter = 0

        def _next_id() -> str:
            nonlocal counter
            counter += 1
            return str(counter)

        # Always emit the user turn.
        events.append(
            {
                "event_id": _next_id(),
                "event_type": "user_turn",
                "data": {"message": user_message},
            }
        )

        # Translate raw SDK events when available.
        for raw in raw_events:
            raw_type = raw.get("type", "")
            if raw_type == "model_response":
                events.append(
                    {
                        "event_id": _next_id(),
                        "event_type": "model_turn",
                        "data": {
                            "text": raw.get("text", ""),
                            "model": raw.get("model", self._agent_config.get("model", "")),
                        },
                    }
                )
            elif raw_type == "function_call":
                events.append(
                    {
                        "event_id": _next_id(),
                        "event_type": "tool_call",
                        "data": {
                            "tool_name": raw.get("name", ""),
                            "arguments": raw.get("args", {}),
                        },
                    }
                )
            elif raw_type == "function_response":
                events.append(
                    {
                        "event_id": _next_id(),
                        "event_type": "tool_result",
                        "data": {
                            "tool_name": raw.get("name", ""),
                            "result": raw.get("response", {}),
                        },
                    }
                )
            elif raw_type == "state_delta":
                events.append(
                    {
                        "event_id": _next_id(),
                        "event_type": "state_update",
                        "data": {"delta": raw.get("delta", {})},
                    }
                )

        # Always emit the final model turn if not already captured from raw events.
        model_turns = [e for e in events if e["event_type"] == "model_turn"]
        if not model_turns and output:
            events.append(
                {
                    "event_id": _next_id(),
                    "event_type": "model_turn",
                    "data": {
                        "text": output,
                        "model": self._agent_config.get("model", ""),
                    },
                }
            )

        return events

    def _resolve_template_vars(self, instruction: str, state: dict) -> str:
        """Resolve ``{key}`` template variables in *instruction* from *state*.

        This is a thin wrapper around the standalone ``resolve_template_vars``
        function that allows subclasses to override resolution logic.

        Args:
            instruction: Raw instruction string possibly containing ``{key}``
                placeholders.
            state: State dict used to resolve the placeholders.

        Returns:
            The instruction with all resolvable placeholders substituted.
        """
        return resolve_template_vars(instruction, state)

    # ------------------------------------------------------------------
    # ADK SDK integration (lazy / optional)
    # ------------------------------------------------------------------

    def _try_adk_sdk_execute(
        self,
        user_message: str,
        resolved_instruction: str,
        state: dict,
    ) -> dict:
        """Attempt to run the agent via the Google ADK SDK.

        Falls back to a stub response when the SDK is not installed.

        Returns:
            Dict with keys: ``output``, ``tokens_used``, ``raw_events``,
            ``state_delta``.
        """
        try:
            return self._adk_sdk_execute(user_message, resolved_instruction, state)
        except ImportError:
            return self._stub_execute(user_message, resolved_instruction)

    def _try_adk_sdk_stream(
        self,
        user_message: str,
        resolved_instruction: str,
        state: dict,
    ) -> Iterator[dict]:
        """Attempt to stream via the Google ADK SDK; fall back to stub."""
        try:
            yield from self._adk_sdk_stream(user_message, resolved_instruction, state)
        except ImportError:
            stub = self._stub_execute(user_message, resolved_instruction)
            for word in stub["output"].split():
                yield {"type": "token", "text": word + " "}
            yield {"type": "usage", "tokens": stub["tokens_used"]}

    def _adk_sdk_execute(
        self,
        user_message: str,
        resolved_instruction: str,
        state: dict,
    ) -> dict:
        """Execute via the google-adk SDK (requires google-adk to be installed)."""
        # Import lazily so the module can load without the SDK.
        from google.adk.runners import InMemoryRunner  # type: ignore[import]
        from google.adk.agents import LlmAgent  # type: ignore[import]
        from google.genai import types as genai_types  # type: ignore[import]

        agent_name = self._agent_config.get("name", "agent")
        model = self._agent_config.get("model", "gemini-2.0-flash")

        agent = LlmAgent(
            name=agent_name,
            model=model,
            instruction=resolved_instruction,
        )
        runner = InMemoryRunner(agent=agent, app_name=agent_name)
        session = runner.session_service.create_session(
            app_name=agent_name,
            user_id="autoagent",
        )

        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=user_message)],
        )

        raw_events: list[dict] = []
        output_parts: list[str] = []
        tokens_used = 0

        for event in runner.run(
            user_id="autoagent",
            session_id=session.id,
            new_message=content,
        ):
            if event.is_final_response():
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            output_parts.append(part.text)
                raw_events.append(
                    {"type": "model_response", "text": "".join(output_parts)}
                )
            elif hasattr(event, "get_function_calls") and event.get_function_calls():
                for fc in event.get_function_calls():
                    raw_events.append(
                        {"type": "function_call", "name": fc.name, "args": dict(fc.args)}
                    )
            elif hasattr(event, "get_function_responses") and event.get_function_responses():
                for fr in event.get_function_responses():
                    raw_events.append(
                        {"type": "function_response", "name": fr.name, "response": fr.response}
                    )

        return {
            "output": "".join(output_parts),
            "tokens_used": tokens_used,
            "raw_events": raw_events,
            "state_delta": {},
        }

    def _adk_sdk_stream(
        self,
        user_message: str,
        resolved_instruction: str,
        state: dict,
    ) -> Iterator[dict]:
        """Stream via the google-adk SDK (requires google-adk to be installed)."""
        from google.adk.runners import InMemoryRunner  # type: ignore[import]
        from google.adk.agents import LlmAgent  # type: ignore[import]
        from google.genai import types as genai_types  # type: ignore[import]

        agent_name = self._agent_config.get("name", "agent")
        model = self._agent_config.get("model", "gemini-2.0-flash")

        agent = LlmAgent(
            name=agent_name,
            model=model,
            instruction=resolved_instruction,
        )
        runner = InMemoryRunner(agent=agent, app_name=agent_name)
        session = runner.session_service.create_session(
            app_name=agent_name,
            user_id="autoagent",
        )
        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=user_message)],
        )

        for event in runner.run(
            user_id="autoagent",
            session_id=session.id,
            new_message=content,
        ):
            if event.is_final_response():
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            yield {"type": "token", "text": part.text}
            elif hasattr(event, "get_function_calls") and event.get_function_calls():
                for fc in event.get_function_calls():
                    yield {
                        "type": "trace",
                        "event": {
                            "event_type": "tool_call",
                            "data": {"tool_name": fc.name, "arguments": dict(fc.args)},
                        },
                    }

    @staticmethod
    def _stub_execute(user_message: str, resolved_instruction: str) -> dict:
        """Minimal stub used when the ADK SDK is not installed."""
        output = (
            f"[ADK SDK not installed] Stub response to: {user_message[:80]}"
        )
        return {
            "output": output,
            "tokens_used": 0,
            "raw_events": [],
            "state_delta": {},
        }
