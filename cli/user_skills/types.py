"""Data types for user-invocable skills.

Skills are parsed once at load time into plain dataclasses; the store and
registry operate on these immutable-ish records so callers never pass
around raw file paths. The dataclass mirrors the YAML frontmatter fields
we accept so a markdown file with extra keys still loads cleanly — extras
land in :attr:`Skill.extra` rather than forcing the schema to evolve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SkillSource(str, Enum):
    """Where a skill was loaded from — informs precedence and display."""

    BUNDLED = "bundled"
    """Shipped with the agentlab package. Always loaded."""

    USER = "user"
    """Lives under ``~/.agentlab/skills``. Available across workspaces."""

    WORKSPACE = "workspace"
    """Lives under ``<workspace>/.agentlab/skills``. Wins conflicts with
    user-global skills because the project voice beats the home voice."""


@dataclass
class Skill:
    """One user-invocable skill loaded from disk.

    Fields mirror Claude Code's skill frontmatter keys where meaningful,
    plus ``path`` and ``source`` so diagnostics can say where the skill
    came from without re-walking the filesystem.
    """

    slug: str
    """Filesystem-safe identifier used for ``/slug`` dispatch. Derived from
    the filename stem (``commit.md`` → ``commit``) when the frontmatter
    doesn't supply ``name``."""

    name: str
    """Human-readable title. Defaults to the slug when unset."""

    description: str
    """One-line description shown in ``/help`` / completer listings."""

    body: str
    """The prompt body — everything after the closing ``---`` delimiter.
    Whitespace is preserved so authors can embed code blocks verbatim."""

    allowed_tools: tuple[str, ...] = ()
    """Exact tool names the model may invoke while this skill runs. An
    empty tuple means "inherit the session's current allow-list" (i.e.
    no additional restriction). We store the tuple so callers can use it
    as a dict key or set member safely."""

    source: SkillSource = SkillSource.WORKSPACE
    path: Path | None = None
    """Absolute path of the markdown file, or ``None`` for programmatic
    skills the REPL registers at runtime."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Unknown frontmatter keys are preserved here so skill authors can
    add bespoke metadata without us rejecting the file."""

    def render_prompt(self, arguments: str = "") -> str:
        """Return the prompt to feed the model when this skill runs.

        ``arguments`` is the trailing text after the slash slug (``/commit
        wip``) so authors can include ``$ARGUMENTS`` in their body and have
        it substituted at dispatch time. We intentionally keep the
        template language minimal (one token); skills that want richer
        templating should do it in the body using regular markdown."""
        if "$ARGUMENTS" in self.body:
            return self.body.replace("$ARGUMENTS", arguments)
        if arguments:
            return f"{self.body.rstrip()}\n\nUser arguments: {arguments}".strip()
        return self.body

    def tool_allowlist(self) -> frozenset[str]:
        """Return the allow-list as a frozenset for fast membership checks."""
        return frozenset(self.allowed_tools)


__all__ = ["Skill", "SkillSource"]
