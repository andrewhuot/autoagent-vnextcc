"""Load skills from YAML packs and register them in the skill store."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from registry.skill_types import Skill


_PACKS_DIR = Path(__file__).parent / "packs"


def load_pack(path: str | Path) -> list[Skill]:
    """Load a YAML pack file and return a list of Skills."""
    path = Path(path)
    with open(path, "r") as f:
        data = yaml.safe_load(f)

    skills_data = data.get("skills", [])
    return [Skill.from_dict(s) for s in skills_data]


def install_pack(path: str | Path, store) -> int:
    """Load and register all skills from a pack. Returns count installed."""
    skills = load_pack(path)
    count = 0
    for skill in skills:
        existing = store.get(skill.name)
        if existing is None:
            store.register(skill)
            count += 1
    return count


def install_builtin_packs(store) -> int:
    """Install universal + cx_agent_studio packs. Returns total count."""
    total = 0
    for pack_file in ["universal.yaml", "cx_agent_studio.yaml"]:
        pack_path = _PACKS_DIR / pack_file
        if pack_path.exists():
            total += install_pack(pack_path, store)
    return total


def export_skill(skill: Skill, path: str | Path) -> None:
    """Export a skill to a YAML file."""
    path = Path(path)
    data = {"skills": [skill.to_dict()]}
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# SKILL.md loading
# ---------------------------------------------------------------------------


def load_from_skill_md(path: str | Path) -> Skill:
    """Load a :class:`~registry.skill_types.Skill` from a SKILL.md file or directory.

    Supports:
    - A plain ``.md`` file path.
    - A directory that contains a ``SKILL.md`` file (with optional ``assets/``
      subdirectory).

    Args:
        path: Path to a SKILL.md file or a directory containing one.

    Returns:
        A fully populated :class:`~registry.skill_types.Skill` instance.

    Raises:
        FileNotFoundError: If the path does not exist or no SKILL.md is found.
        ValueError: If the file cannot be parsed as valid SKILL.md.
    """
    # Import here to avoid circular imports at module load time
    from registry.skill_md import SkillMdParser  # noqa: PLC0415

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    parser = SkillMdParser()

    if path.is_dir():
        parsed = parser.parse_directory(str(path))
    else:
        parsed = parser.parse_file(str(path))

    return parser._normalize_to_skill(parsed)


def load(path: str | Path) -> list[Skill] | Skill:
    """Auto-detect format and load skill(s) from *path*.

    - If *path* is a directory containing ``SKILL.md`` → load one skill via
      :func:`load_from_skill_md`.
    - If *path* ends with ``.md`` → load one skill via :func:`load_from_skill_md`.
    - Otherwise → treat as a YAML pack and return a list of skills via
      :func:`load_pack`.

    Args:
        path: Path to a SKILL.md file/directory or a YAML pack file.

    Returns:
        A single :class:`~registry.skill_types.Skill` (SKILL.md) or a list of
        skills (YAML pack).
    """
    path = Path(path)

    # Directory with SKILL.md
    if path.is_dir() and (path / "SKILL.md").exists():
        return load_from_skill_md(path)

    # Markdown file
    if path.suffix.lower() == ".md":
        return load_from_skill_md(path)

    # Default: YAML pack
    return load_pack(path)
