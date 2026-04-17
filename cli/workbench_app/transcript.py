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
from typing import TYPE_CHECKING, Any, Callable, Iterable, Iterator, Literal, Mapping, Sequence

import click

from cli.workbench_app import theme
from cli.workbench_render import format_workbench_event

if TYPE_CHECKING:
    from cli.sessions import Session, SessionStore


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


_COMPACT_BOUNDARY_EVENT = "compact_boundary"
"""``event_name`` marker for a transcript entry that represents a compact
boundary. Kept as a module-level constant so callers (and tests) can
reference the same literal the renderer branches on."""


_BOUNDARY_RULE = "─" * 40
"""Horizontal rule rendered above and below a compact-boundary entry.

40 chars is wide enough to read as a divider in a narrow terminal while
still leaving room for the content line on a single row. The renderer
contract only requires ``≥ 10`` characters, so consumers may not rely on
the exact width."""


def _format_compact_boundary(entry: TranscriptEntry, *, color: bool) -> str:
    """Render a compact-boundary entry as ``rule / content / rule``.

    The three lines are joined with ``\n`` and returned as a single
    string so the existing ``echo(format_entry(...))`` path prints the
    whole block atomically. Colored output dims the rules (they're
    structural, not content) while leaving the content on the default
    role color so "Compacted N turns — /uncompact to restore" reads as
    a normal meta line.
    """
    rule = _BOUNDARY_RULE
    content = entry.content
    if color:
        rule = theme.meta(rule)
        content = theme.meta(content)
    return f"{rule}\n{content}\n{rule}"


def format_entry(entry: TranscriptEntry, *, color: bool = True) -> str:
    """Render a single :class:`TranscriptEntry` to a terminal line.

    ``color=False`` emits a plain string (no ANSI escapes). Tool entries are
    passed through unchanged because the workbench event renderers already
    apply their own styling; the prefix table above reserves no prefix for
    them either, so round-tripping through ``format_entry`` is a no-op aside
    from optional color stripping.

    Compact-boundary system entries (``event_name == "compact_boundary"``)
    are rendered as a fenced block — a horizontal rule above and below the
    content — so the operator sees a clear visual break between the live
    tail and the archived prefix.
    """
    if entry.role == "system" and entry.event_name == _COMPACT_BOUNDARY_EVENT:
        return _format_compact_boundary(entry, color=color)

    prefix = _ROLE_PREFIX[entry.role]
    text = f"{prefix}{entry.content}"

    if not color:
        return click.unstyle(text)

    if entry.role == "user":
        return theme.user(text)
    if entry.role == "system" or entry.role == "meta":
        return theme.meta(text)
    if entry.role == "error":
        return theme.error(text)
    if entry.role == "warning":
        return theme.warning(text)
    # "assistant" and "tool" keep their own styling (tool lines are produced
    # by pre-styled renderers; assistant text is expected to already include
    # any formatting the caller wants).
    return theme.assistant(text) if entry.role == "assistant" else text


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
        self._session: "Session | None" = None
        self._session_store: "SessionStore | None" = None

    # --------------------------------------------------------- session binding

    def bind_session(
        self,
        session: "Session | None",
        store: "SessionStore | None",
    ) -> None:
        """Wire the transcript to a :class:`SessionStore` for persistence.

        After binding, each successful ``append_*`` / ``replace_tail`` call
        also writes a :class:`SessionEntry` to disk via
        :meth:`SessionStore.append_entry`. ``clear()`` still only wipes
        in-memory state — the on-disk session is preserved so ``/resume``
        can still reach it. Passing ``None`` for either argument detaches
        the binding.
        """
        if session is None or store is None:
            self._session = None
            self._session_store = None
            return
        self._session = session
        self._session_store = store

    @property
    def bound_session(self) -> "Session | None":
        return self._session

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
        self._persist(entry)
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

    def append_compact_boundary(
        self,
        *,
        start: int,
        end: int,
        summary: str,
        emit: bool = True,
    ) -> TranscriptEntry:
        """Append a compact-boundary marker for the range ``[start, end)``.

        ``start`` is inclusive and ``end`` is exclusive — matches
        :mod:`cli.llm.compact_archive` so ``end - start`` is the number
        of compacted turns. The ``summary`` is stashed on ``data`` so a
        later tooltip / detail pane can surface the digest without a
        second round-trip through the archive.
        """
        count = end - start
        content = f"Compacted {count} turns — /uncompact to restore"
        entry = TranscriptEntry(
            role="system",
            content=content,
            event_name=_COMPACT_BOUNDARY_EVENT,
            data={"range": (start, end), "summary": summary},
        )
        return self.append(entry, emit=emit)

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
        self._persist(entry)
        return entry

    def extend(self, entries: Iterable[TranscriptEntry], *, emit: bool = True) -> None:
        for entry in entries:
            self.append(entry, emit=emit)

    # ------------------------------------------------------------------ misc

    def clear(self) -> None:
        """Drop all entries. Does not echo — callers repaint if needed.

        Only affects in-memory state; a bound on-disk session's transcript
        is untouched so ``/clear`` can wipe the visible pane without
        destroying the conversation file.
        """
        self._entries.clear()

    def restore_from_session(
        self, session: "Session", *, emit: bool = False
    ) -> int:
        """Repopulate in-memory entries from a persisted :class:`Session`.

        Used by ``/resume`` to rehydrate the transcript when a prior session
        is loaded. Persistence is suppressed during restore (we'd otherwise
        double-write every entry back to the same session). Returns the
        number of restored entries. ``emit=True`` repaints as each line is
        restored, useful when the loop wants to show a quick recap.
        """
        restored = 0
        for persisted in session.transcript:
            role = _normalize_role(persisted.role)
            entry = TranscriptEntry(
                role=role,
                content=persisted.content,
                timestamp=persisted.timestamp or time.time(),
            )
            self._entries.append(entry)
            if emit:
                self._emit(entry)
            restored += 1
        return restored

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
        clone._session = self._session
        clone._session_store = self._session_store
        return clone

    # ---------------------------------------------------------- internal

    def _emit(self, entry: TranscriptEntry) -> None:
        self._echo(format_entry(entry, color=self._color))

    def _persist(self, entry: TranscriptEntry) -> None:
        """Best-effort persist via the bound :class:`SessionStore`.

        Failures are swallowed because a flaky filesystem shouldn't take
        down the live transcript. The rendered ``content`` is persisted
        verbatim — role/timestamp ride across unchanged. Tool entries
        store the pre-styled event line; stripping ANSI for a cleaner
        session file happens in :mod:`cli.sessions` if ever wanted.
        """
        store = self._session_store
        session = self._session
        if store is None or session is None:
            return
        try:
            store.append_entry(session, entry.role, entry.content)
        except Exception:  # pragma: no cover — defensive; persistence is best-effort
            pass


_VALID_ROLES: frozenset[str] = frozenset(
    ("user", "assistant", "system", "tool", "error", "warning", "meta")
)


def _normalize_role(role: str) -> TranscriptRole:
    """Map a persisted role string to a valid :data:`TranscriptRole`.

    Unknown roles fall back to ``"system"`` so corrupt or legacy sessions
    can still be resumed without blowing up the restore step.
    """
    if role in _VALID_ROLES:
        return role  # type: ignore[return-value]
    return "system"


def _redact(entry: TranscriptEntry) -> TranscriptEntry:
    """Return ``entry`` with its ``data`` payload dropped.

    Convenience for the session-compaction step (T17) that wants to keep the
    rendered content but shed the (potentially large) raw event body.
    """
    if entry.data is None:
        return entry
    return replace(entry, data=None)


def transcript_has_boundary(entries: Sequence[TranscriptEntry]) -> bool:
    """Return ``True`` iff any entry in ``entries`` is a compact boundary.

    Used by the status-bar renderer to show a "compacted" indicator when
    at least one range in the live transcript has been archived. Pure
    predicate: no side effects, no echo, safe to call in a hot loop.
    """
    for entry in entries:
        if entry.event_name == _COMPACT_BOUNDARY_EVENT:
            return True
    return False


__all__ = [
    "EchoFn",
    "Transcript",
    "TranscriptEntry",
    "TranscriptRole",
    "_redact",
    "format_entry",
    "transcript_has_boundary",
]
