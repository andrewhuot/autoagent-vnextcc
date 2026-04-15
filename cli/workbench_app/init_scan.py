"""Workspace scanner and ``AGENTLAB.md`` writer.

Claude Code's ``/init`` walks the repo, detects what it's looking at
(language, frameworks, tests), and writes a ``CLAUDE.md`` memory file
summarising the project for future sessions. We do the analogous thing
for agentlab: scan ``configs/``, ``agent/``, ``evals/`` and the user-
skill directories, then emit (or update) ``AGENTLAB.md`` with a structured
summary the next session can read back.

Design decisions:

* **Scan is a pure function**. :func:`scan_workspace` returns a
  :class:`WorkspaceSummary` dataclass; :func:`render_memory` serialises
  the summary to markdown. Separating the two lets tests assert
  structure without touching the filesystem and lets ``/init`` support a
  dry-run flag.
* **Preserve hand-written sections**. If ``AGENTLAB.md`` already exists
  we keep everything except the ``## Detected`` block which we rewrite
  fresh on every run. The memory file is a user-owned document — the
  scanner augments it, it doesn't own it.
* **Cheap scans only**. We avoid loading every YAML file (yaml parsing
  is non-trivial on huge configs); we just count file types and list the
  most-recently-touched entries. Authors who want richer summaries
  should wire custom scanners into the reader — we ship a sensible
  default.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


DETECTED_MARKER = "<!-- detected:start -->"
DETECTED_END_MARKER = "<!-- detected:end -->"
"""Sentinels that bracket the auto-managed ``## Detected`` block. We
preserve everything outside them so hand-written memory content survives
``/init`` re-runs."""


@dataclass
class WorkspaceFile:
    """Short-form record used by the summary renderer."""

    relative_path: str
    mtime: float


@dataclass
class WorkspaceSummary:
    """Aggregated inventory of the workspace.

    Each list is already ordered newest-first and capped — the memory
    file is meant to be human-readable, not a full manifest."""

    root: Path
    agent_configs: list[WorkspaceFile] = field(default_factory=list)
    agent_sources: list[WorkspaceFile] = field(default_factory=list)
    eval_cases: list[WorkspaceFile] = field(default_factory=list)
    user_skills: list[WorkspaceFile] = field(default_factory=list)
    plans: list[WorkspaceFile] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)

    def is_empty(self) -> bool:
        return not any(
            [
                self.agent_configs,
                self.agent_sources,
                self.eval_cases,
                self.user_skills,
                self.plans,
            ]
        )


def scan_workspace(
    root: Path,
    *,
    limit_per_section: int = 10,
) -> WorkspaceSummary:
    """Walk the workspace and collect headline files for the memory doc.

    The scan is purely IO-bound and read-only; it safely tolerates
    missing directories. ``limit_per_section`` caps each list so
    ``AGENTLAB.md`` stays a pleasant size even for large workspaces."""
    root = Path(root)
    summary = WorkspaceSummary(root=root)
    summary.agent_configs = _collect(root / "configs", ("*.yaml", "*.yml"), limit_per_section)
    summary.agent_sources = _collect(root / "agent", ("*.py",), limit_per_section)
    summary.eval_cases = _collect(root / "evals", ("*.yaml", "*.yml", "*.json"), limit_per_section)
    summary.user_skills = _collect(root / ".agentlab" / "skills", ("*.md",), limit_per_section)
    summary.plans = _collect(root / ".agentlab" / "plans", ("*.md",), limit_per_section)
    return summary


def render_memory(summary: WorkspaceSummary) -> str:
    """Return the ``AGENTLAB.md`` body that the current scan produces."""
    lines = ["# AGENTLAB.md — Project Memory", ""]
    lines.extend(_render_sections(summary))
    return "\n".join(lines) + "\n"


def write_memory(
    summary: WorkspaceSummary,
    *,
    path: Path | None = None,
    preserve_existing: bool = True,
) -> Path:
    """Emit or update ``AGENTLAB.md``.

    ``preserve_existing`` keeps hand-written content outside the
    auto-managed ``## Detected`` block. When the file is new we write the
    full scaffold so authors can see where their custom sections go."""
    memory_path = path or (summary.root / "AGENTLAB.md")
    new_detected = _render_detected_block(summary)

    if preserve_existing and memory_path.exists():
        existing = memory_path.read_text(encoding="utf-8")
        updated = _merge_detected_block(existing, new_detected)
        memory_path.write_text(updated, encoding="utf-8")
        return memory_path

    memory_path.write_text(_default_scaffold(new_detected), encoding="utf-8")
    return memory_path


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _collect(directory: Path, patterns: Iterable[str], limit: int) -> list[WorkspaceFile]:
    if not directory.is_dir():
        return []
    seen: dict[Path, float] = {}
    for pattern in patterns:
        for candidate in directory.rglob(pattern):
            if not candidate.is_file():
                continue
            if any(part.startswith(".") and part != ".agentlab" for part in candidate.parts):
                continue
            try:
                seen[candidate] = candidate.stat().st_mtime
            except OSError:
                continue
    ranked = sorted(seen.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [
        WorkspaceFile(
            relative_path=str(path.relative_to(directory.parent) if path.is_relative_to(directory.parent) else path),
            mtime=mtime,
        )
        for path, mtime in ranked
    ]


def _render_sections(summary: WorkspaceSummary) -> list[str]:
    lines: list[str] = []
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(summary.generated_at))
    lines.append(DETECTED_MARKER)
    lines.append("## Detected")
    lines.append(f"_Last scanned: {stamp}_")
    lines.append("")

    for heading, entries, hint in (
        ("Agent configs", summary.agent_configs, "from `configs/`"),
        ("Agent sources", summary.agent_sources, "from `agent/`"),
        ("Eval cases", summary.eval_cases, "from `evals/`"),
        ("User skills", summary.user_skills, "from `.agentlab/skills/`"),
        ("Plans", summary.plans, "from `.agentlab/plans/`"),
    ):
        lines.append(f"### {heading} ({hint})")
        if not entries:
            lines.append("- _none detected_")
        else:
            for entry in entries:
                lines.append(f"- `{entry.relative_path}`")
        lines.append("")
    lines.append(DETECTED_END_MARKER)
    return lines


def _render_detected_block(summary: WorkspaceSummary) -> str:
    return "\n".join(_render_sections(summary))


def _merge_detected_block(existing: str, new_block: str) -> str:
    """Splice ``new_block`` into ``existing`` between the sentinel markers.

    When the markers are missing we append the block to the end of the
    file — the authoritative location for the auto-managed summary is at
    the bottom, so adding once preserves the author's header."""
    start_idx = existing.find(DETECTED_MARKER)
    end_idx = existing.find(DETECTED_END_MARKER)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        suffix = "\n\n" if not existing.endswith("\n") else "\n"
        return existing.rstrip() + suffix + new_block + "\n"
    # Replace the block including the sentinels.
    end_of_block = end_idx + len(DETECTED_END_MARKER)
    return existing[:start_idx].rstrip() + "\n\n" + new_block + "\n" + existing[end_of_block:].lstrip("\n")


def _default_scaffold(detected_block: str) -> str:
    return "\n".join(
        [
            "# AGENTLAB.md — Project Memory",
            "",
            "## Agent Identity",
            "- Name:",
            "- Platform:",
            "- Primary use case:",
            "",
            "## Business Constraints",
            "",
            "## Known Good Patterns",
            "",
            "## Known Bad Patterns",
            "",
            "## Team Preferences",
            "",
            "## Optimization History",
            "",
            detected_block,
            "",
        ]
    )


__all__ = [
    "DETECTED_MARKER",
    "DETECTED_END_MARKER",
    "WorkspaceFile",
    "WorkspaceSummary",
    "render_memory",
    "scan_workspace",
    "write_memory",
]
