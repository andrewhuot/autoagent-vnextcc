"""Project memory helpers for shared, local, rules, and generated context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUTOAGENT_MD_FILENAME = "AUTOAGENT.md"
AUTOAGENT_LOCAL_MD_FILENAME = "AUTOAGENT.local.md"
RULES_DIRNAME = ".autoagent/rules"
MEMORY_DIRNAME = ".autoagent/memory"

INTEL_BEGIN = "<!-- BEGIN AUTOAGENT INTELLIGENCE — auto-updated, do not edit -->"
INTEL_END = "<!-- END AUTOAGENT INTELLIGENCE -->"

AUTOAGENT_MD_TEMPLATE = '''# AUTOAGENT.md — Project Memory

## Agent Identity
- Name: {agent_name}
- Platform: {platform}
- Primary use case: {use_case}

## Business Constraints
- Response latency must stay under 3 seconds (SLA)
- Safety violations are zero-tolerance
- Cost per conversation budget: $0.05

## Known Good Patterns
- (Add patterns that work well for your agent here)

## Known Bad Patterns
- (Add patterns to avoid here)

## Team Preferences
- Prefer instruction edits over model swaps
- Always run canary before promotion

## Optimization History
'''


@dataclass(frozen=True)
class MemorySource:
    """One physical context source participating in the merged memory view."""

    kind: str
    path: Path
    label: str
    exists: bool = True


@dataclass
class LayeredProjectContext:
    """Merged view across shared, local, rules, and generated memory sources."""

    root: Path
    shared_path: Path
    local_path: Path
    rules_dir: Path
    memory_dir: Path
    sources: list[MemorySource]
    merged_content: str

    @property
    def active_sources(self) -> list[MemorySource]:
        """Return only sources that currently exist on disk."""
        return [source for source in self.sources if source.exists]

    def summary(self) -> dict[str, Any]:
        """Return a compact summary suitable for status/doctor surfaces."""
        return {
            "active_count": len(self.active_sources),
            "shared_present": self.shared_path.exists(),
            "local_present": self.local_path.exists(),
            "rule_count": sum(1 for source in self.active_sources if source.kind == "rule"),
            "generated_count": sum(1 for source in self.active_sources if source.kind == "generated"),
            "paths": [str(source.path) for source in self.active_sources],
        }


def _paths(root: str | Path = ".") -> dict[str, Path]:
    base = Path(root)
    return {
        "root": base,
        "shared": base / AUTOAGENT_MD_FILENAME,
        "local": base / AUTOAGENT_LOCAL_MD_FILENAME,
        "rules_dir": base / RULES_DIRNAME,
        "memory_dir": base / MEMORY_DIRNAME,
    }


def ensure_layered_memory_dirs(root: str | Path = ".") -> tuple[Path, Path]:
    """Create the `.autoagent/rules` and `.autoagent/memory` directories."""
    resolved = _paths(root)
    resolved["rules_dir"].mkdir(parents=True, exist_ok=True)
    resolved["memory_dir"].mkdir(parents=True, exist_ok=True)
    return resolved["rules_dir"], resolved["memory_dir"]


def list_memory_sources(root: str | Path = ".") -> list[MemorySource]:
    """Return all layered memory sources in deterministic order."""
    resolved = _paths(root)
    ensure_layered_memory_dirs(root)

    sources: list[MemorySource] = [
        MemorySource(kind="shared", path=resolved["shared"], label=AUTOAGENT_MD_FILENAME, exists=resolved["shared"].exists()),
        MemorySource(kind="local", path=resolved["local"], label=AUTOAGENT_LOCAL_MD_FILENAME, exists=resolved["local"].exists()),
    ]

    for path in sorted(resolved["rules_dir"].glob("*.md")):
        sources.append(MemorySource(kind="rule", path=path, label=path.name, exists=True))
    for path in sorted(resolved["memory_dir"].glob("*.md")):
        sources.append(MemorySource(kind="generated", path=path, label=path.name, exists=True))
    return sources


def load_layered_project_context(root: str | Path = ".") -> LayeredProjectContext:
    """Load and merge layered project memory content."""
    resolved = _paths(root)
    sources = list_memory_sources(root)
    sections: list[str] = []
    for source in sources:
        if not source.exists:
            continue
        body = source.path.read_text(encoding="utf-8").strip()
        if not body:
            continue
        sections.append(f"<!-- {source.kind}:{source.path.name} -->\n{body}")
    merged = "\n\n".join(sections)
    return LayeredProjectContext(
        root=resolved["root"],
        shared_path=resolved["shared"],
        local_path=resolved["local"],
        rules_dir=resolved["rules_dir"],
        memory_dir=resolved["memory_dir"],
        sources=sources,
        merged_content=merged,
    )


def resolve_memory_target(root: str | Path, target: str) -> Path:
    """Resolve a logical memory target name to a concrete file path."""
    resolved = _paths(root)
    ensure_layered_memory_dirs(root)
    normalized = target.strip().lower()
    if normalized in {"shared", "project"}:
        return resolved["shared"]
    if normalized in {"local", "personal"}:
        return resolved["local"]
    if normalized.startswith("rules/"):
        return resolved["rules_dir"] / f"{normalized.split('/', 1)[1]}.md".removesuffix(".md.md")
    if normalized.startswith("memory/"):
        return resolved["memory_dir"] / f"{normalized.split('/', 1)[1]}.md".removesuffix(".md.md")
    if normalized.endswith(".md"):
        return resolved["root"] / normalized
    return resolved["rules_dir"] / f"{normalized}.md"


def append_memory_text(root: str | Path, target: str, text: str) -> Path:
    """Append markdown text to a target memory file."""
    path = resolve_memory_target(root, target)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").rstrip() if path.exists() else ""
    addition = text.strip()
    combined = f"{existing}\n\n{addition}\n" if existing else f"{addition}\n"
    path.write_text(combined, encoding="utf-8")
    return path


def write_session_summary(root: str | Path, *, title: str, summary: str) -> Path:
    """Write a generated session summary into `.autoagent/memory/`."""
    _, memory_dir = ensure_layered_memory_dirs(root)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    path = memory_dir / f"{timestamp}_session.md"
    body = "\n".join(
        [
            f"# {title}",
            "",
            f"_Generated {datetime.now(timezone.utc).isoformat()}_",
            "",
            summary.strip(),
            "",
        ]
    )
    path.write_text(body, encoding="utf-8")
    return path


@dataclass
class ProjectMemory:
    """Structured representation of `AUTOAGENT.md` project memory."""

    agent_name: str = ""
    platform: str = ""
    use_case: str = ""
    business_constraints: list[str] = field(default_factory=list)
    known_good_patterns: list[str] = field(default_factory=list)
    known_bad_patterns: list[str] = field(default_factory=list)
    team_preferences: list[str] = field(default_factory=list)
    optimization_history: list[str] = field(default_factory=list)
    raw_content: str = ""
    file_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "platform": self.platform,
            "use_case": self.use_case,
            "business_constraints": self.business_constraints,
            "known_good_patterns": self.known_good_patterns,
            "known_bad_patterns": self.known_bad_patterns,
            "team_preferences": self.team_preferences,
            "optimization_history": self.optimization_history,
        }

    def get_optimizer_context(self) -> dict[str, Any]:
        """Return the context most relevant to the optimizer loop."""
        return {
            "agent_identity": f"{self.agent_name} ({self.platform}) — {self.use_case}",
            "constraints": self.business_constraints,
            "avoid_patterns": self.known_bad_patterns,
            "preferences": self.team_preferences,
            "good_patterns": self.known_good_patterns,
        }

    def get_immutable_surfaces(self) -> set[str]:
        """Extract immutable optimization surfaces from written preferences."""
        immutable: set[str] = set()
        for pref in self.team_preferences + self.known_bad_patterns:
            lower = pref.lower()
            if "immutable" in lower or "don't optimize" in lower or "don't change" in lower:
                for keyword in ["greeting", "safety", "routing", "model"]:
                    if keyword in lower:
                        immutable.add(keyword)
        return immutable

    def _build_intelligence_section(
        self,
        report: dict | None,
        eval_score: float | None,
        recent_changes: list[dict] | None,
        skill_gaps: list[dict] | None,
    ) -> str:
        """Build the auto-generated intelligence section."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        safety = "n/a"
        routing = "n/a"
        latency = "n/a"
        issues: list[str] = []
        if report:
            svr = report.get("safety_violation_rate")
            safety = f"{svr:.2f}" if svr is not None else "n/a"
            sr = report.get("success_rate")
            routing = f"{sr * 100:.0f}" if sr is not None else "n/a"
            lat = report.get("avg_latency_ms")
            latency = f"{lat / 1000:.1f}" if lat is not None else "n/a"
            for key, val in report.items():
                if key.endswith("_issues") and isinstance(val, list):
                    issues.extend(val)
                elif key == "issues" and isinstance(val, list):
                    issues.extend(val)

        score_str = f"{eval_score:.2f}" if eval_score is not None else "n/a"

        lines: list[str] = [INTEL_BEGIN]
        lines.append("## Current Health")
        lines.append(
            f"Score: {score_str} | Safety: {safety} | Routing: {routing}% | Latency: {latency}s"
        )
        lines.append(f"Last updated: {ts} UTC")
        lines.append("")

        lines.append("## Active Issues")
        if issues:
            for index, issue in enumerate(issues, 1):
                lines.append(f"{index}. {issue}")
        else:
            lines.append("No active issues")
        lines.append("")

        lines.append("## Recent Changes")
        if recent_changes:
            for change in recent_changes:
                version = change.get("version", "?")
                delta = change.get("delta", 0.0)
                description = change.get("description", "")
                sign = "+" if delta >= 0 else ""
                lines.append(f"- v{version} ({sign}{delta:.2f}): {description}")
        else:
            lines.append("No recent changes")
        lines.append("")

        lines.append("## Skill Gaps")
        if skill_gaps:
            for gap in skill_gaps:
                description = gap.get("description", "")
                count = gap.get("count", 0)
                handled = gap.get("handled", 0)
                lines.append(f"- {description} ({count} user requests, {handled} handled)")
        else:
            lines.append("No skill gaps identified")
        lines.append(INTEL_END)
        return "\n".join(lines)

    def update_with_intelligence(
        self,
        report: dict | None = None,
        eval_score: float | None = None,
        recent_changes: list[dict] | None = None,
        skill_gaps: list[dict] | None = None,
    ) -> None:
        """Update `AUTOAGENT.md` with current agent intelligence."""
        if not self.file_path:
            self.save()

        path = Path(self.file_path)
        current_content = path.read_text(encoding="utf-8") if path.exists() else self.raw_content
        intel_section = self._build_intelligence_section(
            report,
            eval_score,
            recent_changes,
            skill_gaps,
        )

        if INTEL_BEGIN in current_content and INTEL_END in current_content:
            before = current_content[: current_content.index(INTEL_BEGIN)]
            after = current_content[current_content.index(INTEL_END) + len(INTEL_END):]
            new_content = before + intel_section + after
        else:
            separator = "" if current_content.endswith("\n") else "\n"
            new_content = current_content + separator + intel_section + "\n"

        path.write_text(new_content, encoding="utf-8")
        self.raw_content = new_content

    @classmethod
    def load(cls, directory: str = ".") -> ProjectMemory | None:
        """Load `AUTOAGENT.md` from disk, returning `None` when absent."""
        path = Path(directory) / AUTOAGENT_MD_FILENAME
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        memory = cls._parse(content)
        memory.file_path = str(path)
        memory.raw_content = content
        return memory

    def save(self, directory: str = ".") -> str:
        """Save `AUTOAGENT.md` and return the file path."""
        path = Path(directory) / AUTOAGENT_MD_FILENAME
        content = self._render()
        path.write_text(content, encoding="utf-8")
        self.file_path = str(path)
        self.raw_content = content
        return str(path)

    def add_history_entry(self, entry: str) -> None:
        """Add a dated optimization history entry."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.optimization_history.append(f"- {ts}: {entry}")

    def add_note(self, section: str, note: str) -> None:
        """Add a note to a supported memory section."""
        section_lower = section.lower()
        if "good" in section_lower:
            self.known_good_patterns.append(f"- {note}")
        elif "bad" in section_lower:
            self.known_bad_patterns.append(f"- {note}")
        elif "preference" in section_lower or "team" in section_lower:
            self.team_preferences.append(f"- {note}")
        elif "constraint" in section_lower or "business" in section_lower:
            self.business_constraints.append(f"- {note}")

    @classmethod
    def generate_template(
        cls,
        agent_name: str = "My Agent",
        platform: str = "Google ADK",
        use_case: str = "General purpose assistant",
    ) -> str:
        """Generate a fresh starter template for `AUTOAGENT.md`."""
        return AUTOAGENT_MD_TEMPLATE.format(
            agent_name=agent_name,
            platform=platform,
            use_case=use_case,
        )

    @classmethod
    def _parse(cls, content: str) -> ProjectMemory:
        """Parse markdown content into a `ProjectMemory` object."""
        memory = cls()
        sections = _split_sections(content)

        identity = sections.get("agent identity", "")
        for line in identity.strip().splitlines():
            stripped = line.strip().lstrip("- ")
            if stripped.lower().startswith("name:"):
                memory.agent_name = stripped.split(":", 1)[1].strip()
            elif stripped.lower().startswith("platform:"):
                memory.platform = stripped.split(":", 1)[1].strip()
            elif stripped.lower().startswith("primary use case:"):
                memory.use_case = stripped.split(":", 1)[1].strip()

        memory.business_constraints = _parse_list_section(sections.get("business constraints", ""))
        memory.known_good_patterns = _parse_list_section(sections.get("known good patterns", ""))
        memory.known_bad_patterns = _parse_list_section(sections.get("known bad patterns", ""))
        memory.team_preferences = _parse_list_section(sections.get("team preferences", ""))
        memory.optimization_history = _parse_list_section(sections.get("optimization history", ""))
        return memory

    def _render(self) -> str:
        """Render the object back into `AUTOAGENT.md` format."""
        lines = ["# AUTOAGENT.md — Project Memory", ""]
        lines.append("## Agent Identity")
        lines.append(f"- Name: {self.agent_name}")
        lines.append(f"- Platform: {self.platform}")
        lines.append(f"- Primary use case: {self.use_case}")
        lines.append("")

        lines.append("## Business Constraints")
        for item in self.business_constraints:
            lines.append(item if item.startswith("- ") else f"- {item}")
        lines.append("")

        lines.append("## Known Good Patterns")
        for item in self.known_good_patterns:
            lines.append(item if item.startswith("- ") else f"- {item}")
        lines.append("")

        lines.append("## Known Bad Patterns")
        for item in self.known_bad_patterns:
            lines.append(item if item.startswith("- ") else f"- {item}")
        lines.append("")

        lines.append("## Team Preferences")
        for item in self.team_preferences:
            lines.append(item if item.startswith("- ") else f"- {item}")
        lines.append("")

        lines.append("## Optimization History")
        for item in self.optimization_history:
            lines.append(item if item.startswith("- ") else f"- {item}")
        lines.append("")
        return "\n".join(lines)


def _split_sections(content: str) -> dict[str, str]:
    """Split markdown content by `##` section headings."""
    sections: dict[str, str] = {}
    current_header = ""
    current_lines: list[str] = []

    for line in content.splitlines():
        if line.startswith("## "):
            if current_header:
                sections[current_header] = "\n".join(current_lines)
            current_header = line[3:].strip().lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_header:
        sections[current_header] = "\n".join(current_lines)
    return sections


def _parse_list_section(text: str) -> list[str]:
    """Parse a markdown bullet section into plain string entries."""
    items: list[str] = []
    for line in text.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
        elif stripped.startswith("* "):
            items.append(stripped[2:].strip())
        elif stripped and not stripped.startswith("#") and not stripped.startswith("("):
            items.append(stripped)
    return items
