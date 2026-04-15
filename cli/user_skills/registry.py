"""Skill registry singleton.

Thin wrapper around a :class:`SkillStore` that the workbench initialises
once and hands to :class:`SlashContext` via ``meta['skill_registry']``. The
wrapper exists so the slash layer doesn't need to know whether skills came
from disk, a bundled list, or a future MCP source — it calls
:meth:`SkillRegistry.list` / :meth:`SkillRegistry.get` and gets a uniform
:class:`Skill` back.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cli.user_skills.store import SkillStore
from cli.user_skills.types import Skill


@dataclass
class SkillRegistry:
    """In-memory skill catalogue indexed by slug.

    The registry owns one :class:`SkillStore` by default. Multiple stores
    can be stacked via :meth:`extend` so bundled skills layer cleanly on
    top of disk-loaded ones — later additions win slug collisions, so the
    REPL can register overrides without touching the store."""

    store: SkillStore
    _extras: dict[str, Skill]

    def __init__(
        self,
        store: SkillStore,
        *,
        extras: Iterable[Skill] = (),
    ) -> None:
        self.store = store
        self._extras = {skill.slug: skill for skill in extras}

    # ------------------------------------------------------------------ API

    def list(self) -> list[Skill]:
        """Return merged skills sorted by slug, extras overriding disk."""
        merged: dict[str, Skill] = {skill.slug: skill for skill in self.store.list()}
        merged.update(self._extras)
        return [merged[slug] for slug in sorted(merged)]

    def get(self, slug: str) -> Skill | None:
        if slug in self._extras:
            return self._extras[slug]
        return self.store.get(slug)

    def has(self, slug: str) -> bool:
        return slug in self._extras or self.store.has(slug)

    def extend(self, skills: Iterable[Skill]) -> None:
        """Add programmatic skills that override any disk-loaded copy."""
        for skill in skills:
            self._extras[skill.slug] = skill

    def reload(self) -> None:
        """Rescan the backing :class:`SkillStore`. Extras are unaffected."""
        self.store.reload()

    @property
    def warnings(self) -> list[str]:
        return list(self.store.warnings)


# ---------------------------------------------------------------------------
# Default construction
# ---------------------------------------------------------------------------


def default_skill_store(
    *,
    workspace_root: Path | None,
    user_home: Path | None = None,
) -> SkillStore:
    """Build the standard :class:`SkillStore` for the workbench.

    ``user_home`` defaults to :meth:`Path.home` but tests can inject a
    tmp path so per-home fixtures don't require monkey-patching ``HOME``."""
    home = user_home if user_home is not None else Path.home()
    return SkillStore(workspace_root=workspace_root, user_home=home)


__all__ = ["SkillRegistry", "default_skill_store"]
