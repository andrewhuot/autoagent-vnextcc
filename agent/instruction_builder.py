"""Shared helpers for Google-style XML agent instructions.

WHY: XML instruction handling needs to be consistent across templates, evals,
CLI workflows, migrations, and the UI. Keeping the parsing and validation in
one module avoids each surface inventing slightly different rules.
"""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from typing import Any, Mapping


SECTION_TAGS = ("role", "persona", "constraints", "taskflow", "examples")


def is_xml_instruction(text: str) -> bool:
    """Return True when the instruction looks like the recommended XML format.

    WHY: Backward compatibility requires us to support plain text and XML side
    by side, so callers need a lightweight way to detect XML before parsing.
    """
    stripped = text.strip()
    if not stripped:
        return False
    return any(f"<{tag}" in stripped for tag in SECTION_TAGS)


def parse_xml_instruction(xml_text: str) -> dict[str, Any]:
    """Parse XML instruction text into a structured section dictionary.

    WHY: The CLI, eval harness, migrations, and UI need to reason about
    instruction sections independently instead of treating the prompt as one
    opaque string.
    """
    if not is_xml_instruction(xml_text):
        raise ValueError("Instruction does not appear to use the recommended XML structure.")

    try:
        root = ET.fromstring(f"<instruction>{xml_text}</instruction>")
    except ET.ParseError as exc:
        raise ValueError(f"XML parse error: {exc}") from exc

    sections: dict[str, Any] = {
        "preamble": (root.text or "").strip(),
        "role": "",
        "persona": {
            "primary_goal": "",
            "guidelines": [],
        },
        "constraints": [],
        "taskflow": [],
        "examples": [],
    }

    role_node = root.find("role")
    if role_node is not None and role_node.text:
        sections["role"] = role_node.text.strip()

    persona_node = root.find("persona")
    if persona_node is not None:
        primary_goal_node = persona_node.find("primary_goal")
        if primary_goal_node is not None and primary_goal_node.text:
            sections["persona"]["primary_goal"] = primary_goal_node.text.strip()

        guideline_chunks: list[str] = []
        if persona_node.text and persona_node.text.strip():
            guideline_chunks.extend(_split_text_chunks(persona_node.text))
        for child in list(persona_node):
            if child.tag == "primary_goal":
                if child.tail and child.tail.strip():
                    guideline_chunks.extend(_split_text_chunks(child.tail))
                continue
            if child.text and child.text.strip():
                guideline_chunks.extend(_split_text_chunks(child.text))
            if child.tail and child.tail.strip():
                guideline_chunks.extend(_split_text_chunks(child.tail))
        sections["persona"]["guidelines"] = guideline_chunks

    constraints_node = root.find("constraints")
    if constraints_node is not None:
        sections["constraints"] = _parse_text_list("".join(constraints_node.itertext()))

    taskflow_node = root.find("taskflow")
    if taskflow_node is not None:
        taskflow_sections: list[dict[str, Any]] = []
        for subtask_node in taskflow_node.findall("subtask"):
            subtask: dict[str, Any] = {
                "name": str(subtask_node.attrib.get("name", "")).strip(),
                "description": "",
                "steps": [],
            }
            if subtask_node.text and subtask_node.text.strip():
                subtask["description"] = " ".join(_split_text_chunks(subtask_node.text))

            for step_node in subtask_node.findall("step"):
                step = {
                    "name": str(step_node.attrib.get("name", "")).strip(),
                    "trigger": _node_text(step_node.find("trigger")),
                    "action": _node_text(step_node.find("action")),
                }
                subtask["steps"].append(step)
            taskflow_sections.append(subtask)
        sections["taskflow"] = taskflow_sections

    examples_node = root.find("examples")
    if examples_node is not None:
        examples_text = "".join(examples_node.itertext()).strip()
        sections["examples"] = _split_examples(examples_text)

    return sections


def build_xml_instruction(sections: Mapping[str, Any]) -> str:
    """Build XML instruction text from a structured section dictionary.

    WHY: Callers should be able to manipulate sections as data and serialize the
    final instruction only at the point where a model or file needs text.
    """
    lines: list[str] = []
    preamble = str(sections.get("preamble", "") or "").strip()
    if preamble:
        lines.append(preamble)
        lines.append("")

    role = str(sections.get("role", "") or "").strip()
    lines.append(f"<role>{_escape_xml_text(role)}</role>")

    persona = sections.get("persona") or {}
    primary_goal = str(persona.get("primary_goal", "") or "").strip()
    guidelines = _normalize_string_list(persona.get("guidelines"))
    lines.append("<persona>")
    lines.append(f"  <primary_goal>{_escape_xml_text(primary_goal)}</primary_goal>")
    for guideline in guidelines:
        lines.append(f"  {_escape_xml_text(guideline)}")
    lines.append("</persona>")

    constraints = _normalize_string_list(sections.get("constraints"))
    lines.append("<constraints>")
    if constraints:
        for index, item in enumerate(constraints, start=1):
            lines.append(f"  {index}. {_escape_xml_text(item)}")
    lines.append("</constraints>")

    taskflow = sections.get("taskflow") or []
    lines.append("<taskflow>")
    for subtask in taskflow:
        name = _escape_xml_attr(str(subtask.get("name", "") or "").strip())
        lines.append(f'  <subtask name="{name}">')
        description = str(subtask.get("description", "") or "").strip()
        if description:
            lines.append(f"    {_escape_xml_text(description)}")
        for step in subtask.get("steps", []):
            step_name = _escape_xml_attr(str(step.get("name", "") or "").strip())
            lines.append(f'    <step name="{step_name}">')
            lines.append(f"      <trigger>{_escape_xml_text(str(step.get('trigger', '') or '').strip())}</trigger>")
            lines.append(f"      <action>{_escape_xml_text(str(step.get('action', '') or '').strip())}</action>")
            lines.append("    </step>")
        lines.append("  </subtask>")
    lines.append("</taskflow>")

    examples = _normalize_string_list(sections.get("examples"))
    lines.append("<examples>")
    for example in examples:
        for line in example.splitlines():
            lines.append(f"  {line.rstrip()}")
    lines.append("</examples>")

    return "\n".join(lines).strip()


def validate_xml_instruction(xml_text: str) -> dict[str, Any]:
    """Validate XML structure and return errors, warnings, and parsed sections.

    WHY: Validation needs to explain exactly what is missing so users can fix
    instructions in the CLI, UI, and template flows without guessing.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not is_xml_instruction(xml_text):
        return {
            "valid": False,
            "errors": ["Instruction does not use the recommended XML tags."],
            "warnings": ["Plain-text instructions remain supported, but XML is now the default."],
            "sections": None,
        }

    try:
        sections = parse_xml_instruction(xml_text)
    except ValueError as exc:
        return {
            "valid": False,
            "errors": [str(exc)],
            "warnings": warnings,
            "sections": None,
        }

    if not sections.get("role"):
        errors.append("role")

    persona = sections.get("persona") or {}
    if not str(persona.get("primary_goal", "") or "").strip():
        errors.append("persona.primary_goal")

    if not _normalize_string_list(sections.get("constraints")):
        errors.append("constraints")

    taskflow = sections.get("taskflow") or []
    if not taskflow:
        errors.append("taskflow")
    else:
        if not any((subtask.get("steps") or []) for subtask in taskflow):
            errors.append("taskflow.steps")

    examples = _normalize_string_list(sections.get("examples"))
    if not examples:
        warnings.append("No examples provided. Add few-shot examples only when they solve a specific behavior gap.")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "sections": sections,
    }


def merge_xml_sections(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Merge XML section dictionaries using section-level override semantics.

    WHY: Eval variants and specialist overlays need predictable replacement at
    the section level instead of line-based string concatenation.
    """
    merged = copy.deepcopy(dict(base))
    override_dict = dict(override)

    for key, value in override_dict.items():
        if value in (None, "", [], {}):
            continue

        if key == "persona" and isinstance(value, Mapping):
            persona = copy.deepcopy(dict(merged.get("persona") or {}))
            for nested_key, nested_value in dict(value).items():
                if nested_value in (None, "", [], {}):
                    continue
                persona[nested_key] = copy.deepcopy(nested_value)
            merged["persona"] = persona
            continue

        merged[key] = copy.deepcopy(value)

    return merged


def _node_text(node: ET.Element | None) -> str:
    """Return normalized text from an XML node."""
    if node is None:
        return ""
    return " ".join(_split_text_chunks("".join(node.itertext())))


def _split_text_chunks(text: str) -> list[str]:
    """Split a block of text into clean non-empty lines."""
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lines.append(line)
    return lines


def _parse_text_list(text: str) -> list[str]:
    """Parse numbered or bulleted free text into a normalized string list."""
    normalized = text.strip()
    if not normalized:
        return []

    lines = _split_text_chunks(normalized)
    items: list[str] = []
    for line in lines:
        cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        if cleaned:
            items.append(cleaned)
    if items:
        return items
    return [" ".join(normalized.split())]


def _split_examples(text: str) -> list[str]:
    """Split `<examples>` content into discrete example blocks."""
    normalized = text.strip()
    if not normalized:
        return []

    parts = re.split(r"(?=EXAMPLE\s+\d+:)", normalized)
    examples = [part.strip() for part in parts if part.strip()]
    return examples or [normalized]


def _normalize_string_list(value: Any) -> list[str]:
    """Normalize user-provided string-like sections into a clean list."""
    if value is None:
        return []
    if isinstance(value, str):
        return _parse_text_list(value)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _escape_xml_text(value: str) -> str:
    """Escape text content for XML serialization."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_xml_attr(value: str) -> str:
    """Escape attribute content for XML serialization."""
    return _escape_xml_text(value).replace('"', "&quot;").replace("'", "&apos;")
