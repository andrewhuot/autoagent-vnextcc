"""AgentLab memory store — markdown-with-frontmatter on disk.

Public surface:

- :class:`Memory` — frozen dataclass for a single memory.
- :class:`MemoryType` — ``user`` / ``feedback`` / ``project`` /
  ``reference``.
- :class:`MemoryStore` — CRUD over a directory of ``<name>.md`` files
  plus a ``MEMORY.md`` index.

Mirrors the on-disk convention used at
``~/.claude/projects/<slug>/memory/``.
"""
from __future__ import annotations

from .store import MemoryStore
from .types import Memory, MemoryType

__all__ = ["Memory", "MemoryStore", "MemoryType"]
