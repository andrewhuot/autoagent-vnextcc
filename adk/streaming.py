"""SSE-based streaming for ADK agent execution.

Wraps ``AdkRuntimeAdapter.execute_streaming`` and converts the raw event
dicts into typed ``StreamEvent`` objects.  The ``format_sse`` helper produces
the wire format expected by browsers and HTTP clients that consume
Server-Sent Events.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from .runtime import AdkRuntimeAdapter


@dataclass
class StreamEvent:
    """A single event emitted during streamed ADK agent execution.

    Attributes:
        event_type: One of ``token``, ``trace``, ``state``, ``error``,
            ``done``.
        data: Arbitrary payload dict specific to the event type.
        timestamp: Unix epoch seconds at the moment the event was created.
    """

    event_type: str
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class AdkStreamHandler:
    """Converts ``AdkRuntimeAdapter`` streaming output into ``StreamEvent`` objects.

    Example::

        runtime = AdkRuntimeAdapter(agent_config)
        handler = AdkStreamHandler(runtime)
        for event in handler.stream("Hello"):
            print(handler.format_sse(event))
    """

    def __init__(self, runtime: "AdkRuntimeAdapter") -> None:
        """Initialise the stream handler.

        Args:
            runtime: An ``AdkRuntimeAdapter`` instance whose
                ``execute_streaming`` method will be called.
        """
        self._runtime = runtime

    # ------------------------------------------------------------------
    # Public streaming interface
    # ------------------------------------------------------------------

    def stream(
        self,
        user_message: str,
        session_state: dict | None = None,
    ) -> Iterator[StreamEvent]:
        """Yield ``StreamEvent`` objects for a full agent execution.

        Delegates to ``AdkRuntimeAdapter.execute_streaming`` and wraps each
        raw event dict in a ``StreamEvent``.

        Args:
            user_message: The user's input message.
            session_state: Optional initial session state.

        Yields:
            One ``StreamEvent`` per raw event emitted by the runtime.
        """
        for raw in self._runtime.execute_streaming(
            user_message=user_message,
            session_state=session_state,
        ):
            event_type = raw.get("type", "unknown")
            data = raw.get("data", {})
            # Some raw events store payload directly rather than under "data".
            # Normalise them so StreamEvent.data is always a dict.
            if not isinstance(data, dict):
                data = {"value": data}
            yield StreamEvent(event_type=event_type, data=data)

    # ------------------------------------------------------------------
    # SSE formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_sse(event: StreamEvent) -> str:
        """Format a ``StreamEvent`` as an SSE-compliant string.

        The output follows the `text/event-stream` wire format::

            event: <event_type>\\n
            data: <json-encoded data>\\n
            \\n

        Args:
            event: The ``StreamEvent`` to format.

        Returns:
            A string ready to be sent over an HTTP SSE connection.
        """
        lines = [
            f"event: {event.event_type}",
            f"data: {json.dumps(event.data, default=str)}",
            "",  # Trailing blank line terminates the event.
        ]
        return "\n".join(lines) + "\n"
