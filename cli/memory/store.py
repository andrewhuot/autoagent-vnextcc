"""Disk-backed memory store with YAML frontmatter.

Layout
------
``<memory_dir>/MEMORY.md``
    Human-editable index. One bullet per memory:
    ``- [<name>](<name>.md) — <description>``. Kept under 200 lines;
    overflow spills into ``MEMORY-archive-YYYYMMDD.md`` (oldest first).

``<memory_dir>/<name>.md``
    One file per memory. YAML frontmatter fenced by ``---`` followed
    by the markdown body.

Mirrors the convention used at ``~/.claude/projects/<slug>/memory/``.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .types import Memory, MemoryType

logger = logging.getLogger(__name__)

_INDEX_FILENAME = "MEMORY.md"
_INDEX_MAX_LINES = 200
_FRONTMATTER_FENCE = "---"


# --------------------------------------------------------------------------- #
# name validation                                                             #
# --------------------------------------------------------------------------- #

_FORBIDDEN_CHARS = ("/", "\\", "\0")


def _validate_name(name: str) -> None:
    """Reject names that are not safe to use as a filename stem.

    Raises :class:`ValueError` with a descriptive message if the name
    is empty, contains a path separator or NUL, or starts with a dot.
    """
    if not name:
        raise ValueError("memory name must be non-empty")
    for ch in _FORBIDDEN_CHARS:
        if ch in name:
            raise ValueError(f"memory name contains forbidden character {ch!r}: {name!r}")
    if name.startswith("."):
        raise ValueError(f"memory name must not start with a dot: {name!r}")


# --------------------------------------------------------------------------- #
# frontmatter (de)serialisation                                               #
# --------------------------------------------------------------------------- #

def _format_datetime(dt: datetime) -> str:
    """ISO-8601 UTC; naive datetimes treated as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Use Z suffix for UTC for readability + parity with user's files.
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        # pyyaml may deliver as string if the timestamp has a trailing Z
        # that it didn't recognise. datetime.fromisoformat in 3.11 handles
        # most shapes; normalise "Z" → "+00:00".
        s = value.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    raise ValueError(f"unrecognised datetime value: {value!r}")


def _serialise_memory(memory: Memory) -> str:
    """Render a :class:`Memory` to a string (frontmatter + body)."""
    frontmatter: dict[str, Any] = {
        "name": memory.name,
        "type": memory.type.value,
        "description": memory.description,
        "created_at": _format_datetime(memory.created_at),
        "source_session_id": memory.source_session_id,
        "tags": list(memory.tags),
    }
    fm_text = yaml.safe_dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    body = memory.body
    if body and not body.endswith("\n"):
        body += "\n"
    return f"{_FRONTMATTER_FENCE}\n{fm_text}{_FRONTMATTER_FENCE}\n{body}"


def _deserialise_memory(text: str) -> Memory:
    """Parse a frontmatter+body document into a :class:`Memory`.

    Raises :class:`ValueError` on any parse error or missing required
    field. Callers above (:meth:`MemoryStore.read`, :meth:`list`)
    catch this and log instead of propagating.
    """
    if not text.startswith(_FRONTMATTER_FENCE):
        raise ValueError("missing opening frontmatter fence")
    # Split on the closing fence. The frontmatter ends at the first "---"
    # on its own line after the opener.
    # text starts with "---\n"; search for "\n---\n" or "\n---" at EOL.
    rest = text[len(_FRONTMATTER_FENCE):].lstrip("\n")
    end_match = re.search(r"(?:^|\n)---(?:\n|$)", rest)
    if end_match is None:
        raise ValueError("missing closing frontmatter fence")
    fm_text = rest[: end_match.start()]
    body = rest[end_match.end():]
    try:
        data = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"frontmatter must be a mapping, got {type(data).__name__}")

    # Required fields.
    for required in ("name", "type", "description", "created_at"):
        if required not in data:
            raise ValueError(f"missing required frontmatter field: {required}")

    name = data["name"]
    if not isinstance(name, str):
        raise ValueError(f"name must be a string, got {type(name).__name__}")

    type_raw = data["type"]
    try:
        mem_type = MemoryType(type_raw)
    except ValueError as exc:
        raise ValueError(f"invalid memory type: {type_raw!r}") from exc

    description = data["description"]
    if not isinstance(description, str):
        raise ValueError("description must be a string")

    created_at = _parse_datetime(data["created_at"])

    source_session_id = data.get("source_session_id")
    if source_session_id is not None and not isinstance(source_session_id, str):
        raise ValueError("source_session_id must be a string or null")

    tags_raw = data.get("tags") or []
    if not isinstance(tags_raw, list):
        raise ValueError("tags must be a list")
    tags = tuple(str(t) for t in tags_raw)

    # Strip trailing newline on body for a cleaner round-trip.
    if body.endswith("\n"):
        body = body[:-1]

    return Memory(
        name=name,
        type=mem_type,
        description=description,
        body=body,
        created_at=created_at,
        source_session_id=source_session_id,
        tags=tags,
    )


# --------------------------------------------------------------------------- #
# atomic write                                                                 #
# --------------------------------------------------------------------------- #

def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically via temp-file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # NamedTemporaryFile in same dir so os.replace is atomic on POSIX.
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup; re-raise.
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


# --------------------------------------------------------------------------- #
# store                                                                        #
# --------------------------------------------------------------------------- #

class MemoryStore:
    """Content-addressed markdown memory store with YAML frontmatter.

    See module docstring for the on-disk layout.
    """

    def __init__(self, memory_dir: Path) -> None:
        self._dir = Path(memory_dir)

    # -- path helpers -------------------------------------------------------

    @property
    def memory_dir(self) -> Path:
        return self._dir

    def _file_for(self, name: str) -> Path:
        return self._dir / f"{name}.md"

    # -- CRUD ---------------------------------------------------------------

    def write(self, memory: Memory) -> Path:
        """Persist ``memory`` to disk. Returns the file path.

        Replaces any existing memory with the same ``name``. Rewrites
        ``MEMORY.md`` after every write.
        """
        _validate_name(memory.name)
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._file_for(memory.name)
        _atomic_write_text(path, _serialise_memory(memory))
        self.rewrite_index()
        return path

    def read(self, name: str) -> Memory | None:
        """Return the memory with the given name, or ``None`` if not
        found or malformed. Warnings are logged for malformed files.
        """
        try:
            _validate_name(name)
        except ValueError:
            return None
        path = self._file_for(name)
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
            return _deserialise_memory(text)
        except (ValueError, OSError) as exc:
            logger.warning("malformed or unreadable memory %s: %s", path, exc)
            return None

    def list(self) -> list[Memory]:
        """Return all memories sorted by name. Corrupt files skipped."""
        if not self._dir.is_dir():
            return []
        out: list[Memory] = []
        for child in sorted(self._dir.iterdir()):
            if not child.is_file():
                continue
            if child.name == _INDEX_FILENAME:
                continue
            if child.name.startswith("MEMORY-archive-"):
                continue
            if child.suffix != ".md":
                continue
            if child.name.endswith(".tmp"):
                continue
            if child.name.startswith("."):
                continue
            try:
                mem = _deserialise_memory(child.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                logger.warning("skipping malformed memory file %s: %s", child, exc)
                continue
            out.append(mem)
        out.sort(key=lambda m: m.name)
        return out

    def delete(self, name: str) -> bool:
        """Delete a memory by name. Returns ``True`` if a file was
        removed, ``False`` if nothing to delete."""
        try:
            _validate_name(name)
        except ValueError:
            return False
        path = self._file_for(name)
        if not path.exists():
            return False
        path.unlink()
        self.rewrite_index()
        return True

    def exists(self, name: str) -> bool:
        try:
            _validate_name(name)
        except ValueError:
            return False
        return self._file_for(name).exists()

    # -- index --------------------------------------------------------------

    def rewrite_index(self) -> None:
        """Rewrite ``MEMORY.md`` so it reflects the current set of
        memories. Keeps the index under 200 lines — overflow spills
        oldest entries (by ``created_at``) into an archive file.
        """
        memories = self.list()
        # Sort by created_at ascending so that oldest entries are the
        # ones demoted to an archive when we overflow.
        memories_chrono = sorted(memories, key=lambda m: (m.created_at, m.name))
        lines = [
            f"- [{m.name}]({m.name}.md) — {m.description}"
            for m in memories_chrono
        ]
        if len(lines) > _INDEX_MAX_LINES:
            overflow = len(lines) - _INDEX_MAX_LINES
            to_archive = lines[:overflow]
            remaining = lines[overflow:]
            self._append_archive(to_archive)
            lines = remaining
        self._dir.mkdir(parents=True, exist_ok=True)
        index_path = self._dir / _INDEX_FILENAME
        _atomic_write_text(index_path, "\n".join(lines) + ("\n" if lines else ""))

    def _append_archive(self, lines: list[str]) -> None:
        """Append ``lines`` to a dated archive file. Uses UTC day."""
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        archive_path = self._dir / f"MEMORY-archive-{stamp}.md"
        existing = ""
        if archive_path.exists():
            existing = archive_path.read_text(encoding="utf-8")
            if existing and not existing.endswith("\n"):
                existing += "\n"
        new_text = existing + "\n".join(lines) + "\n"
        _atomic_write_text(archive_path, new_text)
