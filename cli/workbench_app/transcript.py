"""Streaming transcript pane for the workbench app.

T07 builds the transcript surface that T04's echo-only loop and T05's slash
dispatch write into, and that T08/T09+ stream live tool-call events into. The
module is deliberately small and synchronous — the full-screen prompt_toolkit
wiring arrives with T16, but every layer downstream of dispatch talks to this
``Transcript`` class today so the persistence + replay contract is fixed.

Responsibilities
----------------
- Hold an append-only list of :class:`TranscriptEntry` values tagged by role.
- Format each entry with role-based coloring (dim system lines, yellow warns,
  red errors, cyan user prompts) while leaving tool-event content intact — the
  renderers in :mod:`cli.workbench_render` already produce pre-styled strings.
- Consume raw workbench streaming events via :meth:`Transcript.append_event`,
  which delegates to :func:`cli.workbench_render.format_workbench_event` so the
  transcript never re-implements the 30+ event renderers.
- Emit each appended entry to an injectable ``echo`` callable so tests and
  later prompt_toolkit integrations can observe output without swapping stdout.

Design notes
------------
- ``TranscriptEntry`` is frozen — entries never mutate in place. ``replace_tail``
  is available for the narrow case of streaming ``task.progress`` updates that
  want to coalesce into a single rolling line.
- Role coloring is applied at format-time, not store-time, so the same entry
  history can be re-rendered with color on/off (e.g. for a ``--no-color``
  transcript dump from ``/resume``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Iterator, Literal, Mapping

import click

from cli.workbench_render import format_workbench_event


TranscriptRole = Literal[
    "user",
    "assistant",
    "system",
    "tool",
    "error",
    "warning",
    "meta",
]
"""Role tag driving color/prefix selection.

- ``user``     — free text typed by the operator at the prompt.
- ``assistant``— agent/model output (no prefix, default color).
- ``system``   — dim meta line (slash result with ``display="system"``).
- ``tool``     — a streaming workbench event (already pre-styled).
- ``error``    — red, prefixed with ``!``.
- ``warning``  — yellow, prefixed with ``⚠``.
- ``meta``     — dim auxiliary line (``meta_messages`` from ``onDone``).
"""

EchoFn = Callable[[str], None]
"""Writes one line to the underlying transport — defaults to :func:`click.echo`."""


_ROLE_PREFIX: Mapping[TranscriptRole, str] = {
    "user": "> ",
    "assistant": "",
    "system": "",
    "tool": "",
    "error": "! ",
    "warning": "⚠ ",
    "meta": "",
}


@dataclass(frozen=True)
class TranscriptEntry:
    """Immutable record of one line in the transcript.

    ``event_name`` / ``data`` are populated only for ``role == "tool"`` entries
    produced by :meth:`Transcript.append_event` — they let a later replay or
    compaction step inspect the original event without re-parsing the string.
    """

    role: TranscriptRole
    content: str
    timestamp: float = field(default_factory=time.time)
    event_name: str | None = None
    data: Mapping[str, Any] | None = None


def format_entry(entry: TranscriptEntry, *, color: bool = True) -> str:
    """Render a single :class:`TranscriptEntry` to a terminal line.

    ``color=False`` emits a plain string (no ANSI escapes). Tool entries are
    passed through unchanged because the workbench event renderers already
    apply their own styling; the prefix table above reserves no prefix for
    them either, so round-tripping through ``format_entry`` is a no-op aside
    from optional color stripping.
    """
    prefix = _ROLE_PREFIX[entry.role]
    text = f"{prefix}{entry.content}"

    if not color:
        return click.unstyle(text)

    if entry.role == "user":
        return click.style(text, fg="cyan", bold=True)
    if entry.role == "system":
        return click.style(text, dim=True)
    if entry.role == "meta":
        return click.style(text, dim=True)
    if entry.role == "error":
        return click.style(text, fg="red", bold=True)
    if entry.role == "warning":
        return click.style(text, fg="yellow")
    # "assistant" and "tool" keep their own styling (tool lines are produced
    # by pre-styled renderers; assistant text is expected to already include
    # any formatting the caller wants).
    return text


class Transcript:
    """Append-only log of transcript entries with synchronous echo.

    The enclosing workbench loop owns a single instance. Slash dispatch, the
    streaming event consumer, and the prompt echo paths all call the
    ``append_*`` helpers rather than talking to ``click.echo`` directly so the
    session store (T17) can persist every line from one code path.
    """

    def __init__(
        self,
        *,
        echo: EchoFn | None = None,
        color: bool = True,
    ) -> None:
        self._entries: list[TranscriptEntry] = []
        self._echo: EchoFn = echo if echo is not None else click.echo
        self._color = color

    # ------------------------------------------------------------------ read

    @property
    def entries(self) -> tuple[TranscriptEntry, ...]:
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[TranscriptEntry]:
        return iter(self._entries)

    @property
    def color(self) -> bool:
        return self._color

    def set_color(self, color: bool) -> None:
        """Toggle color for future :meth:`_emit` calls. History is unaffected."""
        self._color = color

    # ------------------------------------------------------------------ write

    def append(
        self,
        entry: TranscriptEntry,
        *,
        emit: bool = True,
    ) -> TranscriptEntry:
        """Append an entry and optionally echo it. Returns the stored entry."""
        self._entries.append(entry)
        if emit:
            self._emit(entry)
        return entry

    def append_user(self, content: str, *, emit: bool = True) -> TranscriptEntry:
        return self.append(TranscriptEntry(role="user", content=content), emit=emit)

    def append_assistant(
        self, content: str, *, emit: bool = True
    ) -> TranscriptEntry:
        return self.append(
            TranscriptEntry(role="assistant", content=content), emit=emit
        )

    def append_system(self, content: str, *, emit: bool = True) -> TranscriptEntry:
        return self.append(
            TranscriptEntry(role="system", content=content), emit=emit
        )

    def append_error(self, content: str, *, emit: bool = True) -> TranscriptEntry:
        return self.append(
            TranscriptEntry(role="error", content=content), emit=emit
        )

    def append_warning(
        self, content: str, *, emit: bool = True
    ) -> TranscriptEntry:
        return self.append(
            TranscriptEntry(role="warning", content=content), emit=emit
        )

    def append_meta(self, content: str, *, emit: bool = True) -> TranscriptEntry:
        return self.append(TranscriptEntry(role="meta", content=content), emit=emit)

    def append_event(
        self,
        event_name: str,
        data: Mapping[str, Any] | None = None,
        *,
        emit: bool = True,
    ) -> TranscriptEntry | None:
        """Format a workbench streaming event and append it as a ``tool`` entry.

        Returns ``None`` when the event has no registered renderer or the
        renderer intentionally suppressed output (heartbeat, message delta).
        The caller does not need to care which — the branch is the same
        either way (no transcript line written).
        """
        payload = dict(data or {})
        line = format_workbench_event(event_name, payload)
        if line is None:
            return None
        entry = TranscriptEntry(
            role="tool",
            content=line,
            event_name=event_name,
            data=payload,
        )
        return self.append(entry, emit=emit)

    def replace_tail(
        self,
        entry: TranscriptEntry,
        *,
        emit: bool = True,
    ) -> TranscriptEntry:
        """Replace the last entry — used for rolling progress updates.

        Raises :class:`IndexError` on an empty transcript so a buggy caller
        doesn't silently drop the first progress line. The replacement is
        echoed in the same way an append would be; no cursor rewind is
        attempted here (that belongs to the prompt_toolkit layer in T16/T18b).
        """
        if not self._entries:
            raise IndexError("replace_tail called on empty transcript")
        self._entries[-1] = entry
        if emit:
            self._emit(entry)
        return entry

    def extend(self, entries: Iterable[TranscriptEntry], *, emit: bool = True) -> None:
        for entry in entries:
            self.append(entry, emit=emit)

    # ------------------------------------------------------------------ misc

    def clear(self) -> None:
        """Drop all entries. Does not echo — callers repaint if needed."""
        self._entries.clear()

    def render(self, *, color: bool | None = None) -> str:
        """Return the full transcript joined by newlines.

        ``color`` defaults to the instance setting. Used by ``/resume`` (T17)
        to redisplay a prior session when the loop starts up, and by tests
        that want one string to assert on.
        """
        use_color = self._color if color is None else color
        return "\n".join(
            format_entry(entry, color=use_color) for entry in self._entries
        )

    def copy_with(
        self,
        *,
        echo: EchoFn | None = None,
        color: bool | None = None,
    ) -> "Transcript":
        """Return a shallow copy sharing history but with different output wiring."""
        clone = Transcript(
            echo=echo if echo is not None else self._echo,
            color=self._color if color is None else color,
        )
        clone._entries = list(self._entries)
        return clone

    # ---------------------------------------------------------- internal

    def _emit(self, entry: TranscriptEntry) -> None:
        self._echo(format_entry(entry, color=self._color))


def _redact(entry: TranscriptEntry) -> TranscriptEntry:
    """Return ``entry`` with its ``data`` payload dropped.

    Convenience for the session-compaction step (T17) that wants to keep the
    rendered content but shed the (potentially large) raw event body.
    """
    if entry.data is None:
        return entry
    return replace(entry, data=None)


__all__ = [
    "EchoFn",
    "Transcript",
    "TranscriptEntry",
    "TranscriptRole",
    "_redact",
    "format_entry",
]
