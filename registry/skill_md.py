"""SKILL.md portable skill format parser and serializer.

SKILL.md is the cross-platform skill standard used by OpenAI Codex, Anthropic Claude Code,
Google ADK, VS Code, and Cursor. Format:
- YAML frontmatter (between --- delimiters)
- Markdown body with structured sections
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

import yaml

from registry.skill_types import (
    EvalCriterion,
    MutationTemplate,
    Skill,
    SkillExample,
    TriggerCondition,
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class SkillMdParser:
    """Parses SKILL.md content into structured data and Skill objects."""

    def parse(self, content: str) -> dict:
        """Parse a SKILL.md string into a structured dict.

        Args:
            content: Full SKILL.md file content.

        Returns:
            Dict with keys ``frontmatter`` (dict) and section keys from the body.
        """
        frontmatter, body = self._parse_frontmatter(content)
        sections = self._parse_body_sections(body)
        result: dict[str, Any] = {"frontmatter": frontmatter}
        result.update(sections)
        return result

    def parse_file(self, path: str) -> dict:
        """Read and parse a SKILL.md file.

        Args:
            path: Absolute or relative path to a SKILL.md file.

        Returns:
            Parsed dict (same structure as :meth:`parse`).
        """
        content = Path(path).read_text(encoding="utf-8")
        return self.parse(content)

    def parse_directory(self, dir_path: str) -> dict:
        """Parse a SKILL.md directory (SKILL.md + optional assets/).

        Args:
            dir_path: Path to a directory that must contain SKILL.md.

        Returns:
            Parsed dict; also includes an ``assets`` key with a list of asset
            file paths found under an ``assets/`` subdirectory if it exists.
        """
        base = Path(dir_path)
        skill_md_path = base / "SKILL.md"
        if not skill_md_path.exists():
            raise FileNotFoundError(f"No SKILL.md found in directory: {dir_path}")

        result = self.parse_file(str(skill_md_path))

        assets_dir = base / "assets"
        if assets_dir.is_dir():
            result["assets"] = [str(p) for p in sorted(assets_dir.iterdir()) if p.is_file()]

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
        """Extract YAML frontmatter and return (frontmatter_dict, body_str).

        The frontmatter must be delimited by ``---`` on its own line at the
        start of the file.
        """
        content = content.lstrip("\ufeff")  # strip BOM if present
        if not content.startswith("---"):
            return {}, content

        # Work on the tail (everything after the opening ---)
        tail = content[3:]

        # Find the closing ---
        end_match = re.search(r"\n---\s*\n", tail)
        if end_match is None:
            # Try --- at end of file with no trailing newline
            end_match = re.search(r"\n---\s*$", tail)
            if end_match is None:
                return {}, content

        fm_text = tail[: end_match.start()]
        body = tail[end_match.end():]

        try:
            frontmatter = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError:
            frontmatter = {}

        return frontmatter, body

    def _parse_body_sections(self, body: str) -> dict:
        """Parse markdown body into a dict of section name -> content string.

        Top-level headings (``#``) become the skill title (key ``title``).
        Second-level headings (``##``) become section keys.
        """
        sections: dict[str, Any] = {}

        # Extract title from H1
        title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if title_match:
            sections["title"] = title_match.group(1).strip()

        # Split body on H2 headings
        parts = re.split(r"^##\s+", body, flags=re.MULTILINE)

        for part in parts[1:]:  # skip everything before first H2
            lines = part.split("\n", 1)
            heading = lines[0].strip()
            section_body = lines[1].strip() if len(lines) > 1 else ""
            key = heading.lower().replace(" ", "_")
            sections[key] = self._parse_section_content(heading, section_body)

        return sections

    def _parse_section_content(self, heading: str, content: str) -> Any:
        """Parse the content of a specific section.

        Known sections receive structured parsing; all others are returned as
        raw strings.
        """
        h = heading.lower()

        if h == "mutations":
            return self._parse_mutations_section(content)
        if h == "examples":
            return self._parse_examples_section(content)
        if h in ("eval criteria", "eval_criteria"):
            return self._parse_eval_criteria_section(content)
        if h == "guardrails":
            return self._parse_list_section(content)
        if h == "references":
            return content  # raw markdown

        return content

    def _parse_mutations_section(self, content: str) -> list[dict]:
        """Parse ## Mutations section into a list of mutation dicts."""
        mutations: list[dict] = []

        # Split on H3 headings
        parts = re.split(r"^###\s+", content, flags=re.MULTILINE)
        for part in parts[1:]:
            lines = part.split("\n", 1)
            name = lines[0].strip()
            body = lines[1] if len(lines) > 1 else ""
            mutation: dict[str, Any] = {"name": name}
            for key, val in self._parse_definition_list(body):
                if key == "type":
                    mutation["mutation_type"] = val
                elif key == "target":
                    mutation["target_surface"] = val
                elif key == "description":
                    mutation["description"] = val
                elif key == "template":
                    mutation["template"] = val
                else:
                    mutation[key] = val
            mutations.append(mutation)

        return mutations

    def _parse_examples_section(self, content: str) -> list[dict]:
        """Parse ## Examples section into a list of example dicts."""
        examples: list[dict] = []

        parts = re.split(r"^###\s+", content, flags=re.MULTILINE)
        for part in parts[1:]:
            lines = part.split("\n", 1)
            name = lines[0].strip()
            body = lines[1] if len(lines) > 1 else ""
            example: dict[str, Any] = {"name": name}
            for key, val in self._parse_definition_list(body):
                if key == "improvement":
                    try:
                        example["improvement"] = float(val)
                    except (TypeError, ValueError):
                        example["improvement"] = 0.0
                else:
                    example[key] = val
            examples.append(example)

        return examples

    def _parse_eval_criteria_section(self, content: str) -> list[dict]:
        """Parse ## Eval Criteria section (YAML list blocks) into dicts."""
        criteria: list[dict] = []

        # Try to parse as a YAML list directly
        try:
            parsed = yaml.safe_load(content)
            if isinstance(parsed, list):
                return parsed
        except yaml.YAMLError:
            pass

        # Fallback: parse bullet items as key: value pairs
        current: dict[str, Any] = {}
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") and ":" in stripped:
                if current:
                    criteria.append(current)
                    current = {}
                kv = stripped[2:]
                k, _, v = kv.partition(":")
                current[k.strip()] = v.strip()
            elif ":" in stripped and current:
                k, _, v = stripped.partition(":")
                current[k.strip()] = v.strip()

        if current:
            criteria.append(current)

        return criteria

    def _parse_list_section(self, content: str) -> list[str]:
        """Parse a simple bullet-list section into a list of strings."""
        items: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                items.append(stripped[2:].strip())
            elif stripped.startswith("* "):
                items.append(stripped[2:].strip())
        return items

    def _parse_definition_list(self, content: str) -> list[tuple[str, Any]]:
        """Parse markdown definition-list style items (``- **key**: value``).

        Also handles multi-line block values introduced with ``|``.
        """
        results: list[tuple[str, Any]] = []
        lines = content.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            m = re.match(r"-\s+\*\*(.+?)\*\*\s*:\s*(.*)", line)
            if m:
                key = m.group(1).lower()
                val: Any = m.group(2).strip()
                if val == "|":
                    # Collect indented block scalar
                    block_lines: list[str] = []
                    i += 1
                    while i < len(lines) and (lines[i].startswith("    ") or lines[i].strip() == ""):
                        block_lines.append(lines[i][4:] if lines[i].startswith("    ") else "")
                        i += 1
                    val = "\n".join(block_lines).strip()
                    results.append((key, val))
                    continue
                results.append((key, val))
            i += 1
        return results

    def _normalize_to_skill(self, parsed: dict) -> Skill:
        """Convert a parsed dict (from :meth:`parse`) to a registry :class:`Skill`.

        Args:
            parsed: Output of :meth:`parse`.

        Returns:
            A fully populated :class:`~registry.skill_types.Skill` instance.
        """
        fm = parsed.get("frontmatter", {})

        # Build mutations
        mutations: list[MutationTemplate] = []
        for m in parsed.get("mutations", []):
            mutations.append(
                MutationTemplate(
                    name=m.get("name", "unnamed"),
                    mutation_type=m.get("mutation_type", "instruction_rewrite"),
                    target_surface=m.get("target_surface", "system_prompt"),
                    description=m.get("description", ""),
                    template=m.get("template"),
                    parameters=m.get("parameters", {}),
                )
            )

        # Build examples
        examples: list[SkillExample] = []
        for ex in parsed.get("examples", []):
            examples.append(
                SkillExample(
                    name=ex.get("name", "example"),
                    surface=ex.get("surface", "system_prompt"),
                    before=ex.get("before", ""),
                    after=ex.get("after", ""),
                    improvement=float(ex.get("improvement", 0.0)),
                    context=ex.get("context", ""),
                )
            )

        # Build eval criteria
        eval_criteria: list[EvalCriterion] = []
        for ec in parsed.get("eval_criteria", []):
            if isinstance(ec, dict):
                eval_criteria.append(
                    EvalCriterion(
                        metric=ec.get("metric", ""),
                        target=float(ec.get("target", 0.0)),
                        operator=ec.get("operator", "gt"),
                        weight=float(ec.get("weight", 1.0)),
                    )
                )

        # Build triggers
        triggers: list[TriggerCondition] = []
        for t in fm.get("triggers", []):
            if isinstance(t, dict):
                triggers.append(
                    TriggerCondition(
                        failure_family=t.get("failure_family"),
                        metric_name=t.get("metric_name"),
                        threshold=t.get("threshold"),
                        operator=t.get("operator", "gt"),
                        blame_pattern=t.get("blame_pattern"),
                    )
                )

        description_section = parsed.get("description", "")
        description = fm.get("description", description_section or "")

        return Skill(
            name=fm.get("name", parsed.get("title", "unnamed-skill")),
            version=int(fm.get("version", 1)),
            description=description,
            category=fm.get("category", "quality"),
            platform=fm.get("platform", "universal"),
            target_surfaces=fm.get("target_surfaces", []),
            mutations=mutations,
            examples=examples,
            guardrails=parsed.get("guardrails", []),
            eval_criteria=eval_criteria,
            triggers=triggers,
            author=fm.get("author", "autoagent-builtin"),
            tags=fm.get("tags", []),
            created_at=time.time(),
            status="active",
            # New SKILL.md fields
            kind=fm.get("kind", "runtime"),
            dependencies=fm.get("dependencies", []),
            allowed_tools=fm.get("allowed_tools", []),
            supported_frameworks=fm.get("supported_frameworks", []),
            required_approvals=fm.get("required_approvals", []),
            eval_contract=fm.get("eval_contract", {}),
            rollout_policy=fm.get("rollout_policy", "gradual"),
            provenance=fm.get("provenance", ""),
            trust_level=fm.get("trust_level", "unverified"),
            instructions=parsed.get("instructions", ""),
            references=parsed.get("references", ""),
        )


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


class SkillMdSerializer:
    """Converts skill dicts (or :class:`Skill` objects) to SKILL.md format."""

    def serialize(self, skill: dict) -> str:
        """Convert a skill dict to a SKILL.md string.

        Also accepts a :class:`~registry.skill_types.Skill` instance (it will
        be converted via ``to_dict()`` first).

        Args:
            skill: Skill data dict.

        Returns:
            Full SKILL.md string.
        """
        if hasattr(skill, "to_dict"):
            skill = skill.to_dict()  # type: ignore[union-attr]

        frontmatter = self._generate_frontmatter(skill)
        body = self._generate_body(skill)
        return frontmatter + "\n" + body

    def serialize_to_file(self, skill: dict, path: str) -> None:
        """Write a SKILL.md file to ``path``.

        Args:
            skill: Skill data dict.
            path: Destination file path (will be created/overwritten).
        """
        content = self.serialize(skill)
        Path(path).write_text(content, encoding="utf-8")

    def serialize_to_directory(self, skill: dict, dir_path: str) -> None:
        """Create a SKILL.md directory layout (SKILL.md + assets/).

        Args:
            skill: Skill data dict.
            dir_path: Destination directory (created if it does not exist).
        """
        base = Path(dir_path)
        base.mkdir(parents=True, exist_ok=True)
        (base / "assets").mkdir(exist_ok=True)
        self.serialize_to_file(skill, str(base / "SKILL.md"))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_frontmatter(self, skill: dict) -> str:
        """Build the YAML frontmatter block.

        Args:
            skill: Skill data dict.

        Returns:
            String starting and ending with ``---\\n``.
        """
        fm: dict[str, Any] = {
            "name": skill.get("name", "unnamed-skill"),
            "version": skill.get("version", 1),
            "kind": skill.get("kind", "runtime"),
            "category": skill.get("category", "quality"),
            "platform": skill.get("platform", "universal"),
            "description": skill.get("description", ""),
            "author": skill.get("author", "autoagent-builtin"),
            "tags": skill.get("tags", []),
            "dependencies": skill.get("dependencies", []),
            "allowed_tools": skill.get("allowed_tools", []),
            "supported_frameworks": skill.get("supported_frameworks", []),
            "required_approvals": skill.get("required_approvals", []),
            "eval_contract": skill.get("eval_contract", {}),
            "rollout_policy": skill.get("rollout_policy", "gradual"),
            "provenance": skill.get("provenance", ""),
            "trust_level": skill.get("trust_level", "unverified"),
        }

        # Serialize triggers from TriggerCondition dicts
        raw_triggers = skill.get("triggers", [])
        if raw_triggers:
            triggers_out: list[dict] = []
            for t in raw_triggers:
                if isinstance(t, dict):
                    entry: dict[str, Any] = {}
                    if t.get("failure_family"):
                        entry["failure_family"] = t["failure_family"]
                    if t.get("metric_name"):
                        entry["metric_name"] = t["metric_name"]
                    if t.get("threshold") is not None:
                        entry["threshold"] = t["threshold"]
                    entry["operator"] = t.get("operator", "gt")
                    if t.get("blame_pattern"):
                        entry["blame_pattern"] = t["blame_pattern"]
                    triggers_out.append(entry)
            fm["triggers"] = triggers_out

        fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True)
        return f"---\n{fm_str}---\n"

    def _generate_body(self, skill: dict) -> str:
        """Build the markdown body.

        Args:
            skill: Skill data dict.

        Returns:
            Markdown string (without frontmatter).
        """
        name = skill.get("name", "unnamed-skill")
        title = name.replace("-", " ").title()
        lines: list[str] = [f"# {title}", ""]

        # Description
        description = skill.get("description", "")
        lines += ["## Description", "", description or "_No description provided._", ""]

        # Instructions (Layer 2)
        instructions = skill.get("instructions", "")
        if instructions:
            lines += ["## Instructions", "", instructions, ""]

        # Mutations
        mutations = skill.get("mutations", [])
        if mutations:
            lines.append("## Mutations")
            lines.append("")
            for m in mutations:
                mut_name = m.get("name", "unnamed")
                lines.append(f"### {mut_name}")
                lines.append(f"- **type**: {m.get('mutation_type', 'instruction_rewrite')}")
                lines.append(f"- **target**: {m.get('target_surface', 'system_prompt')}")
                if m.get("description"):
                    lines.append(f"- **description**: {m['description']}")
                template = m.get("template")
                if template:
                    lines.append("- **template**: |")
                    for tl in template.splitlines():
                        lines.append(f"    {tl}")
                lines.append("")

        # Examples
        examples = skill.get("examples", [])
        if examples:
            lines.append("## Examples")
            lines.append("")
            for ex in examples:
                ex_name = ex.get("name", "example")
                lines.append(f"### {ex_name}")
                lines.append(f"- **surface**: {ex.get('surface', 'system_prompt')}")
                lines.append(f"- **before**: {ex.get('before', '')}")
                lines.append(f"- **after**: {ex.get('after', '')}")
                lines.append(f"- **improvement**: {ex.get('improvement', 0.0)}")
                lines.append("")

        # Eval Criteria
        eval_criteria = skill.get("eval_criteria", [])
        if eval_criteria:
            lines.append("## Eval Criteria")
            lines.append("")
            for ec in eval_criteria:
                if isinstance(ec, dict):
                    lines.append(f"- metric: {ec.get('metric', '')}")
                    lines.append(f"  target: {ec.get('target', 0.0)}")
                    lines.append(f"  operator: {ec.get('operator', 'gt')}")
                    lines.append(f"  weight: {ec.get('weight', 1.0)}")
            lines.append("")

        # Guardrails
        guardrails = skill.get("guardrails", [])
        if guardrails:
            lines.append("## Guardrails")
            lines.append("")
            for g in guardrails:
                lines.append(f"- {g}")
            lines.append("")

        # References (Layer 3)
        references = skill.get("references", "")
        if references:
            lines += ["## References", "", references, ""]

        return "\n".join(lines) + "\n"
