"""Disk-based skill store.

Walks two directories — ``<workspace>/.agentlab/skills`` (project-local)
and ``~/.agentlab/skills`` (user-global) — and parses every ``*.md`` file
it finds into a :class:`Skill`. Precedence: workspace wins ties against
user-global, matching Claude Code's project-over-home behaviour.

The store is deliberately synchronous and cache-free: skills load once at
workbench start and a ``/reload-skills`` command (added in a later phase)
can call :meth:`SkillStore.reload`. Cache invalidation would add a
filesystem watcher we don't otherwise need.

Parsing is intentionally permissive. A file without frontmatter is treated
as a body-only skill (slug = filename stem, description empty); a broken
frontmatter block logs a warning via :attr:`SkillStore.warnings` so the
REPL can surface load problems without aborting startup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from cli.user_skills.types import Skill, SkillSource


SKILL_DIR_RELATIVE = ".agentlab/skills"
"""Sub-path appended to each search root."""


@dataclass
class SkillStore:
    """Skill collection loaded from disk.

    The store records load warnings on :attr:`warnings` rather than
    raising; the workbench is expected to keep running with partial skill
    coverage if one file is malformed."""

    workspace_root: Path | None = None
    user_home: Path | None = None

    skills: dict[str, Skill] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.reload()

    # ------------------------------------------------------------------ public

    def reload(self) -> None:
        """Rescan configured roots. Safe to call repeatedly."""
        self.skills.clear()
        self.warnings.clear()
        # Load user-global first so workspace skills overwrite conflicting
        # slugs — mirrors Claude Code's project-local-wins rule.
        if self.user_home is not None:
            self._load_dir(self.user_home / SKILL_DIR_RELATIVE, SkillSource.USER)
        if self.workspace_root is not None:
            self._load_dir(self.workspace_root / SKILL_DIR_RELATIVE, SkillSource.WORKSPACE)

    def list(self) -> list[Skill]:
        """Return skills sorted by slug for stable display."""
        return [self.skills[slug] for slug in sorted(self.skills)]

    def get(self, slug: str) -> Skill | None:
        return self.skills.get(slug)

    def has(self, slug: str) -> bool:
        return slug in self.skills

    # ------------------------------------------------------------------ internal

    def _load_dir(self, directory: Path, source: SkillSource) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*.md")):
            try:
                skill = parse_skill_file(path, source=source)
            except ValueError as exc:
                self.warnings.append(f"{path}: {exc}")
                continue
            self.skills[skill.slug] = skill


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_skill_file(path: Path, *, source: SkillSource) -> Skill:
    """Parse a markdown file into a :class:`Skill`.

    Raises :class:`ValueError` when frontmatter is malformed *and* the body
    cannot be safely used as a fallback — i.e. the file is fundamentally
    unreadable. Callers (SkillStore) convert that into a load warning."""
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)
    slug_default = path.stem

    if frontmatter is None:
        return Skill(
            slug=slug_default,
            name=slug_default,
            description="",
            body=body.strip() + ("\n" if body else ""),
            source=source,
            path=path,
        )

    headers = _parse_frontmatter(frontmatter)
    if "error" in headers:
        raise ValueError(headers["error"])

    allowed_raw = headers.get("allowed-tools") or headers.get("tools") or ""
    allowed_tools = _parse_tool_list(allowed_raw)

    slug = _slugify(str(headers.get("slug") or headers.get("name") or slug_default))
    name = str(headers.get("name") or slug)
    description = str(headers.get("description") or "")

    known_keys = {"name", "slug", "description", "allowed-tools", "tools"}
    extra = {
        key: value
        for key, value in headers.items()
        if key not in known_keys
    }

    return Skill(
        slug=slug,
        name=name,
        description=description,
        body=body.strip() + ("\n" if body else ""),
        allowed_tools=tuple(allowed_tools),
        source=source,
        path=path,
        extra=extra,
    )


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return ``(frontmatter, body)``. ``frontmatter`` is ``None`` when the
    file doesn't open with a ``---`` delimiter."""
    if not text.startswith("---"):
        return None, text
    # Require the opening delimiter to be on its own line. A file that
    # happens to start with three dashes in prose (unlikely but possible)
    # should not be mistaken for frontmatter.
    first_line_end = text.find("\n")
    if first_line_end == -1 or text[:first_line_end].strip() != "---":
        return None, text
    remainder = text[first_line_end + 1 :]
    closer_index = remainder.find("\n---")
    if closer_index == -1:
        # Opening delimiter without a close — treat the whole file as body
        # and let the body tell the user what went wrong.
        return None, text
    frontmatter = remainder[:closer_index]
    body_start = closer_index + len("\n---")
    # Consume the newline that follows the closing ``---`` if present.
    if remainder[body_start : body_start + 1] == "\n":
        body_start += 1
    body = remainder[body_start:]
    return frontmatter, body


def _parse_frontmatter(block: str) -> dict[str, object]:
    """Parse ``key: value`` lines into a mapping.

    We accept a tiny YAML subset rather than importing PyYAML because the
    skills format is tight (flat keys, scalar or list values) and keeping
    the parser in-repo lets us give skill-specific error messages. YAML
    support can land later if authors start using anchors and blocks."""
    result: dict[str, object] = {}
    current_list_key: str | None = None
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if current_list_key is not None and line.lstrip().startswith("- "):
            value = line.lstrip()[2:].strip()
            existing = result.get(current_list_key)
            if isinstance(existing, list):
                existing.append(value)
            else:
                result[current_list_key] = [value]
            continue
        if ":" not in line:
            return {"error": f"Malformed frontmatter line: {raw_line!r}"}
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            # Possible list follow-up on subsequent lines.
            current_list_key = key
            result[key] = []
            continue
        current_list_key = None
        if value.startswith("[") and value.endswith("]"):
            items = [
                item.strip().strip("'\"")
                for item in value[1:-1].split(",")
                if item.strip()
            ]
            result[key] = items
            continue
        result[key] = value.strip("'\"")
    return result


def _parse_tool_list(raw: object) -> list[str]:
    """Normalise the frontmatter value into a list of trimmed tool names."""
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        cleaned = raw.strip()
        if not cleaned:
            return []
        if cleaned.startswith("[") and cleaned.endswith("]"):
            inner = cleaned[1:-1]
            return [
                token.strip().strip("'\"")
                for token in inner.split(",")
                if token.strip()
            ]
        return [token.strip() for token in cleaned.split(",") if token.strip()]
    return []


def _slugify(raw: str) -> str:
    """Convert ``"Deploy Helper"`` → ``"deploy-helper"``.

    Slugs are the slash-command name, so we aim for URL-safe characters.
    Non-ASCII letters survive as-is (after lowercasing) so a Japanese-
    named skill remains invocable — the restriction is whitespace and
    path separators."""
    cleaned = raw.strip().lower()
    result: list[str] = []
    prev_dash = False
    for char in cleaned:
        if char.isalnum() or char in {"_", "-"}:
            result.append(char)
            prev_dash = False
        elif char.isspace() or char in {"/", "\\"}:
            if not prev_dash:
                result.append("-")
                prev_dash = True
    slug = "".join(result).strip("-")
    return slug or "skill"


__all__ = ["SkillStore", "parse_skill_file"]
