"""Compact archive store: JSONL-backed retention of compacted turns.

When the orchestrator compacts a range of transcript messages
``[start, end)`` it replaces them in the live context with a boundary
sentinel system message (see :func:`build_boundary_message`) and
writes the original messages to a JSONL archive on disk. If the user
later asks to replay or audit what was elided, the orchestrator can
reconstruct the slice via :meth:`CompactArchive.load`.

Layout
------
``<root>/<session_id>/<start>-<end>.jsonl``
    One :class:`cli.llm.types.TurnMessage` per line, serialised via
    :func:`dataclasses.asdict`. Filenames are derived from the
    ``(start, end)`` range — callers are expected to hand in the exact
    bounds they compacted. ``start`` is inclusive, ``end`` is exclusive,
    matching every other ``[start, end)`` convention in this package.

Retention
---------
Archived ranges are considered expired 30 days after their file's
``mtime`` — :meth:`is_expired` is a predicate; eviction is the caller's
job. We keep the policy as a simple predicate so ``/doctor`` can
enumerate expired archives without mutating anything.

Boundary sentinel
-----------------
The live transcript needs *some* placeholder in place of the removed
turns so the model sees continuity. We use a ``role="system"``
:class:`TurnMessage` whose ``content`` is a dict tagged with
:data:`COMPACT_BOUNDARY_SENTINEL`. Callers identify boundaries with
:func:`is_boundary` and recover the archived range with
:func:`boundary_range`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cli.llm.types import TurnMessage


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


COMPACT_BOUNDARY_SENTINEL = "__compact_boundary__"
"""Marker string stored under ``content["kind"]`` on a boundary system
message. Chosen as a double-underscored literal so a user message that
happens to contain the string in prose cannot be mistaken for a real
boundary — :func:`is_boundary` additionally requires the message role
to be ``"system"`` and ``content`` to be a dict with a ``range`` field.
"""


_RETENTION_DAYS = 30
"""Archived ranges expire 30 days after their file's mtime."""


# ---------------------------------------------------------------------------
# CompactArchive
# ---------------------------------------------------------------------------


@dataclass
class CompactArchive:
    """JSONL archive of compacted transcript slices for one session.

    ``root`` is conventionally ``<workspace>/.agentlab/compact_archive``;
    each session gets its own subdirectory so multiple concurrent
    sessions don't collide on range filenames. The directory is created
    lazily on first :meth:`write`.
    """

    root: Path
    session_id: str

    # -- path helpers -------------------------------------------------------

    def _session_dir(self) -> Path:
        return Path(self.root) / self.session_id

    def _path_for(self, start: int, end: int) -> Path:
        return self._session_dir() / f"{start}-{end}.jsonl"

    # -- write / load -------------------------------------------------------

    def write(self, start: int, end: int, messages: list[TurnMessage]) -> Path:
        """Persist ``messages`` under the ``(start, end)`` key.

        Overwrites any existing archive for the same range — compaction
        is idempotent on a given slice, and a second write with the
        same bounds should reflect the latest truth.
        """
        path = self._path_for(start, end)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for message in messages:
                fh.write(json.dumps(asdict(message), ensure_ascii=False))
                fh.write("\n")
        return path

    def load(self, start: int, end: int) -> list[TurnMessage]:
        """Return the messages previously written for this range.

        Raises :class:`FileNotFoundError` if no archive exists for the
        range — we deliberately don't swallow that into an empty list so
        callers see the difference between "archived empty" (possible
        but pathological) and "nothing archived".

        Partial / truncated lines are skipped: if the last line of a
        JSONL file is non-empty but not valid JSON, we ignore it. This
        mirrors the append-only nature of the store — a crash mid-write
        should lose at most the tail record, not corrupt the whole
        archive.
        """
        path = self._path_for(start, end)
        if not path.exists():
            raise FileNotFoundError(
                f"no compact archive for range {start}-{end} in {self._session_dir()}"
            )
        out: list[TurnMessage] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError:
                    # Tail-of-file corruption: drop this record and stop.
                    # We stop rather than continue so we don't silently
                    # reorder messages if a middle record gets mangled.
                    break
                out.append(_message_from_dict(data))
        return out

    # -- enumeration --------------------------------------------------------

    def ranges(self) -> list[tuple[int, int]]:
        """Return all archived ``(start, end)`` pairs, sorted ascending.

        Ordering is by ``start`` then ``end`` — ascending start covers
        the common case of "replay archives in transcript order"; the
        secondary sort on ``end`` is defensive in case a caller ever
        writes two ranges sharing a start (the API doesn't forbid it,
        though production never does).

        An empty / missing directory returns ``[]``.
        """
        directory = self._session_dir()
        if not directory.is_dir():
            return []
        out: list[tuple[int, int]] = []
        for child in directory.iterdir():
            if not child.is_file():
                continue
            if child.suffix != ".jsonl":
                continue
            stem = child.stem
            # Expected form "<int>-<int>". Anything else — partials,
            # dotfiles, editor swaps — is ignored rather than raising.
            parts = stem.split("-")
            if len(parts) != 2:
                continue
            try:
                start = int(parts[0])
                end = int(parts[1])
            except ValueError:
                continue
            out.append((start, end))
        out.sort()
        return out

    # -- retention ----------------------------------------------------------

    def written_at(self, path: Path) -> datetime:
        """Return the UTC datetime of ``path``'s last modification.

        We use mtime rather than recording a timestamp in the file so
        ``touch``-based manual retention extensions keep working (the
        user edits the archive file, mtime bumps, retention window
        renews). Returned as timezone-aware UTC for unambiguous
        comparison with ``datetime.now(tz=timezone.utc)``.
        """
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc)

    def is_expired(self, path: Path, *, now: datetime) -> bool:
        """True iff ``now - written_at(path) >= 30 days``.

        The ``>=`` (not ``>``) means an archive written exactly 30 days
        ago is considered expired — matches the "30-day retention"
        promise verbatim.

        A naive ``now`` is treated as UTC. This is lenient rather than
        strict because ``datetime.now()`` without ``tz`` is the common
        ad-hoc form in scripts and we'd rather not surprise callers
        with a ``TypeError``.
        """
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return (now - self.written_at(path)) >= timedelta(days=_RETENTION_DAYS)


# ---------------------------------------------------------------------------
# Boundary sentinel helpers
# ---------------------------------------------------------------------------


def build_boundary_message(*, start: int, end: int, digest_text: str) -> TurnMessage:
    """Construct the system message that replaces a compacted slice.

    The shape is deliberately a dict (not a string) so the renderer can
    distinguish a boundary from a real system instruction without
    parsing prose. ``range`` is a two-element list (not a tuple)
    because JSON has no tuple and this content round-trips through
    wire serialisation downstream.
    """
    return TurnMessage(
        role="system",
        content={
            "kind": COMPACT_BOUNDARY_SENTINEL,
            "range": [start, end],
            "digest": digest_text,
        },
    )


def is_boundary(msg: TurnMessage) -> bool:
    """True iff ``msg`` is a boundary sentinel.

    Checks three invariants:

    * ``role == "system"`` — a user-authored message with the same
      sentinel string in prose shouldn't false-positive.
    * ``content`` is a mapping (dict).
    * ``content["kind"] == COMPACT_BOUNDARY_SENTINEL``.

    Returns ``False`` on any non-match and on any attribute access
    failure — callers invoke this inside hot rendering loops and must
    not crash on a malformed turn.
    """
    role = getattr(msg, "role", None)
    if role != "system":
        return False
    content = getattr(msg, "content", None)
    if not isinstance(content, dict):
        return False
    return content.get("kind") == COMPACT_BOUNDARY_SENTINEL


def boundary_range(msg: TurnMessage) -> tuple[int, int]:
    """Return ``(start, end)`` from a boundary message.

    Raises :class:`ValueError` if ``msg`` is not a boundary or if the
    ``range`` field is malformed. Callers that aren't sure should
    guard with :func:`is_boundary` first; the ``ValueError`` here is
    the loud failure mode for "I asserted this was a boundary and it
    wasn't".
    """
    if not is_boundary(msg):
        raise ValueError("message is not a compact-boundary sentinel")
    content = msg.content
    # is_boundary already verified content is a dict with the right kind;
    # validate the range field shape explicitly so a corrupt archive
    # doesn't produce a surprising IndexError two call stacks away.
    raw = content.get("range") if isinstance(content, dict) else None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValueError(f"boundary message has malformed range: {raw!r}")
    try:
        start = int(raw[0])
        end = int(raw[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"boundary range entries must be ints: {raw!r}") from exc
    return start, end


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _message_from_dict(data: dict[str, Any]) -> TurnMessage:
    """Rebuild a :class:`TurnMessage` from its ``asdict`` form.

    :class:`TurnMessage` is an ordinary (non-frozen) dataclass with
    ``role`` and ``content`` fields; ``asdict`` round-trips trivially
    via kwargs. We do *not* re-hydrate nested content blocks into
    their dataclass types — the orchestrator consumes content as
    opaque JSON-shaped data, so keeping it as plain dicts/lists/strs
    after a load is correct and slightly cheaper.
    """
    return TurnMessage(role=data["role"], content=data.get("content"))


__all__ = [
    "COMPACT_BOUNDARY_SENTINEL",
    "CompactArchive",
    "build_boundary_message",
    "boundary_range",
    "is_boundary",
]
