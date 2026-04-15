"""User-invocable skills for the workbench REPL.

Claude Code's skills are prompt+tool bundles the user invokes via ``/name``
and the model can call via :class:`SkillTool`. They live on disk as markdown
files with YAML frontmatter and carry an allow-list of tool names that
restricts the tool surface while the skill runs.

This is *distinct* from :mod:`agent_skills` which analyses agent gaps and
emits suggested runtime capabilities — the two systems share the word
"skill" but mean different things. Keeping them in separate packages keeps
the naming honest; a future refactor can merge if the concepts converge.

Public surface:

* :class:`Skill`               — dataclass for one loaded skill.
* :class:`SkillStore`          — walks workspace + user-home skill dirs.
* :class:`SkillRegistry`       — in-memory lookup keyed by slug.
* :func:`default_skill_store`  — singleton factory the REPL calls at start.
"""

from __future__ import annotations

from cli.user_skills.types import Skill, SkillSource
from cli.user_skills.store import SkillStore
from cli.user_skills.registry import SkillRegistry, default_skill_store

__all__ = [
    "Skill",
    "SkillSource",
    "SkillStore",
    "SkillRegistry",
    "default_skill_store",
]
