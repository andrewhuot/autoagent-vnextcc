"""Shared SSE framing primitives.

Both the plain SSE transport (long-lived GET + sibling POST) and the
newer Streamable-HTTP transport (single endpoint whose POST responses
may themselves be ``text/event-stream``) consume the same wire format:
blank-line-delimited frames with ``event:``, ``data:``, and comment
lines. Rather than duplicate the 40-line parser, we host it here as two
pure functions that neither transport needs to subclass or monkey-patch.

Keeping the framing dependency-free (no httpx, no queue) also means the
parser stays trivially unit-testable and works against any iterator of
byte chunks — real streams, MockTransport bodies, or fixture strings."""

from __future__ import annotations

from typing import Iterable, Iterator, Optional, Tuple


def parse_events(
    iterator: Iterable[bytes | str],
) -> Iterator[Tuple[str, str, Optional[str]]]:
    """Yield ``(event_name, data, event_id)`` tuples from a byte/str iter.

    Frames are delimited by a blank line. Multi-line ``data:`` values are
    joined with ``\\n`` per the SSE spec. Comment lines (starting with
    ``:``) are silently consumed. ``event_id`` is the last-seen ``id:``
    field value, passed through for resumption support (the Streamable-
    HTTP transport tracks it for ``Last-Event-ID`` reconnects); callers
    that do not care about resume can just ignore the third element.

    We swallow iterator exceptions because we are invariably driving
    this from a background reader thread — raising across that boundary
    would crash the thread silently; returning cleanly lets the owning
    transport's liveness signal (staleness timer, ``_closed`` flag)
    decide what the end-of-stream means."""
    buffer = ""
    try:
        for chunk in iterator:
            if not chunk:
                continue
            if isinstance(chunk, (bytes, bytearray)):
                buffer += chunk.decode("utf-8", errors="replace")
            else:
                buffer += chunk
            # SSE frames end on a blank line; split on the double
            # newline and keep the trailing partial for the next chunk.
            # We also tolerate \r\n framing by normalising first.
            buffer = buffer.replace("\r\n", "\n").replace("\r", "\n")
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                parsed = parse_one_frame(frame)
                if parsed is not None:
                    yield parsed
    except Exception:
        return


def parse_one_frame(frame: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """Return (event_name, data_joined, event_id) for one SSE frame.

    Missing ``event:`` defaults to ``"message"`` per the SSE spec.
    Comment-only or empty frames return None so the caller can skip
    cleanly. ``data:`` and ``event:`` values have their single optional
    leading space stripped. ``id:`` is captured verbatim (used for
    ``Last-Event-ID`` resumption). ``retry:`` and other unknown fields
    are ignored — reconnect timing is policy, not framing."""
    event_name = "message"
    data_lines: list[str] = []
    event_id: Optional[str] = None
    saw_field = False
    for line in frame.split("\n"):
        if not line:
            continue
        if line.startswith(":"):
            # Comment — consumed without effect on the frame payload.
            continue
        if ":" in line:
            field_name, _, value = line.partition(":")
            # The spec says a single space after ":" is the separator
            # and is stripped.
            if value.startswith(" "):
                value = value[1:]
        else:
            field_name, value = line, ""
        if field_name == "event":
            event_name = value
            saw_field = True
        elif field_name == "data":
            data_lines.append(value)
            saw_field = True
        elif field_name == "id":
            event_id = value
            saw_field = True
        # retry: and anything else — dropped.
    if not saw_field:
        return None
    return event_name, "\n".join(data_lines), event_id


__all__ = ["parse_events", "parse_one_frame"]
