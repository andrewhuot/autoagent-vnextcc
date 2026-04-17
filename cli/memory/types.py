"""Types for AgentLab's memory store.

Mirrors Claude Code's ``memoryTypes.ts`` taxonomy (user / feedback /
project / reference). Each :class:`Memory` is a single markdown file
with YAML frontmatter — see :mod:`cli.memory.store` for the on-disk
layout.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MemoryType(str, Enum):
    """Classification of a memory. Matches Claude Code's taxonomy."""

    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"


@dataclass(frozen=True)
class Memory:
    """A single memory entry.

    ``name`` doubles as the filename stem (``<name>.md``) and as the
    unique key within a store — writes with the same name replace
    in-place.

    Attributes:
        name: Slug / filename stem. Unique per store. Rejected at
            write time if it contains ``/``, ``\\``, NUL, or starts
            with ``.``.
        type: One of the :class:`MemoryType` enum values.
        description: One-line human summary shown in the MEMORY.md
            index.
        body: Full markdown body written below the frontmatter.
        created_at: Creation timestamp (tz-aware recommended).
        source_session_id: The AgentLab session that produced this
            memory, or ``None`` for hand-authored entries.
        tags: Optional tuple of short tags (empty by default).
    """

    name: str
    type: MemoryType
    description: str
    body: str
    created_at: datetime
    source_session_id: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
