"""Builder contract loader — parses BUILDER_CONTRACT.md for machine use.

WHY: The builder contract defines operating behavior in a human-readable
markdown file.  This module extracts structured metadata so the harness can
surface contract information in events and the UI without coupling to the
raw markdown format.

The loader is intentionally lightweight: it reads section headings and
extracts key metadata, but does NOT enforce the contract.  Enforcement is
a future concern; today's goal is visibility and truthfulness.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Contract data model
# ---------------------------------------------------------------------------

@dataclass
class SkillLayerDefinition:
    """Describes one skill layer (build or runtime) from the contract."""

    kind: str  # "build" or "runtime"
    description: str = ""


@dataclass
class BuilderContract:
    """Structured representation of the builder behavior contract.

    Extracted from ``BUILDER_CONTRACT.md`` at harness startup.
    """

    version: str = "1.0"
    phases: list[str] = field(default_factory=list)
    skill_layers: list[SkillLayerDefinition] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    source_path: str = ""
    loaded: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize for inclusion in events / API responses."""
        return {
            "version": self.version,
            "phases": self.phases,
            "skill_layers": [
                {"kind": sl.kind, "description": sl.description}
                for sl in self.skill_layers
            ],
            "sections": self.sections,
            "source_path": self.source_path,
            "loaded": self.loaded,
        }


# ---------------------------------------------------------------------------
# Section heading regex: ## N. Title
# ---------------------------------------------------------------------------
_SECTION_RE = re.compile(r"^##\s+\d+\.\s+(.+)$", re.MULTILINE)

# Phase list regex: ### Phase N: Name
_PHASE_RE = re.compile(r"^###\s+Phase\s+\d+:\s+(.+)$", re.MULTILINE)


def _locate_contract(search_dirs: list[str] | None = None) -> str | None:
    """Find ``BUILDER_CONTRACT.md`` by searching upward from the working directory.

    Also checks any explicit ``search_dirs`` paths.
    """
    candidates: list[str] = []

    # Explicit search paths
    if search_dirs:
        for d in search_dirs:
            candidates.append(os.path.join(d, "BUILDER_CONTRACT.md"))

    # Walk up from cwd
    cwd = os.getcwd()
    while True:
        candidates.append(os.path.join(cwd, "BUILDER_CONTRACT.md"))
        parent = os.path.dirname(cwd)
        if parent == cwd:
            break
        cwd = parent

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def load_builder_contract(
    path: str | None = None,
    search_dirs: list[str] | None = None,
) -> BuilderContract:
    """Load and parse ``BUILDER_CONTRACT.md``.

    Args:
        path: Explicit path to the contract file.  When ``None``, the loader
            searches upward from the current working directory.
        search_dirs: Additional directories to search.

    Returns:
        A ``BuilderContract`` with ``loaded=True`` if the file was found and
        parsed successfully.  Returns a default (``loaded=False``) contract
        if the file is missing or unparseable — the harness must degrade
        gracefully, never crash on a missing contract.
    """
    contract = BuilderContract()

    resolved = path or _locate_contract(search_dirs)
    if resolved is None or not os.path.isfile(resolved):
        return contract

    try:
        text = Path(resolved).read_text(encoding="utf-8")
    except OSError:
        return contract

    contract.source_path = resolved
    contract.loaded = True

    # Extract top-level sections (## N. Title)
    contract.sections = _SECTION_RE.findall(text)

    # Extract phases (### Phase N: Name)
    contract.phases = _PHASE_RE.findall(text)

    # Extract skill layers
    if "Build-time skills" in text:
        contract.skill_layers.append(
            SkillLayerDefinition(
                kind="build",
                description="Optimization strategies that modify agent configurations during development.",
            )
        )
    if "Runtime skills" in text:
        contract.skill_layers.append(
            SkillLayerDefinition(
                kind="runtime",
                description="Agent capabilities deployed at runtime.",
            )
        )

    return contract
