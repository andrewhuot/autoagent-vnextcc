"""Tests for XML instruction parsing, building, validation, and migration."""

from __future__ import annotations

from agent.instruction_builder import (
    build_xml_instruction,
    merge_xml_sections,
    parse_xml_instruction,
    validate_xml_instruction,
)
from agent.migrate_to_xml import infer_instruction_sections, migrate_instruction_text


SAMPLE_XML = """
CURRENT CUSTOMER: {username}

<role>Weather support specialist.</role>
<persona>
  <primary_goal>Provide accurate weather answers.</primary_goal>
  Stay calm and concise.
  Follow the constraints and taskflow exactly.
</persona>
<constraints>
  1. Use {@TOOL: get_weather} only for specific weather requests.
  2. If the user's name is known, greet them by name.
</constraints>
<taskflow>
  <subtask name="Intent Routing">
    <step name="Detect Greeting">
      <trigger>User says hello.</trigger>
      <action>Call {@AGENT: Greeting Agent}.</action>
    </step>
    <step name="Handle Weather">
      <trigger>User asks for weather in a location.</trigger>
      <action>Use {@TOOL: get_weather} and summarize the result.</action>
    </step>
  </subtask>
</taskflow>
<examples>
EXAMPLE 1:
Begin example
[user]
What's the weather in London?
[model]
The weather in London is 15 C and Cloudy.
End example
</examples>
""".strip()


def test_parse_xml_instruction_extracts_google_recommended_sections() -> None:
    """Valid XML instructions should parse into a structured section payload."""
    parsed = parse_xml_instruction(SAMPLE_XML)

    assert parsed["preamble"] == "CURRENT CUSTOMER: {username}"
    assert parsed["role"] == "Weather support specialist."
    assert parsed["persona"]["primary_goal"] == "Provide accurate weather answers."
    assert "Stay calm and concise." in parsed["persona"]["guidelines"]
    assert parsed["constraints"] == [
        "Use {@TOOL: get_weather} only for specific weather requests.",
        "If the user's name is known, greet them by name.",
    ]
    assert parsed["taskflow"][0]["name"] == "Intent Routing"
    assert parsed["taskflow"][0]["steps"][0]["name"] == "Detect Greeting"
    assert parsed["taskflow"][0]["steps"][1]["action"] == "Use {@TOOL: get_weather} and summarize the result."
    assert parsed["examples"] == [
        "EXAMPLE 1:\nBegin example\n[user]\nWhat's the weather in London?\n[model]\nThe weather in London is 15 C and Cloudy.\nEnd example"
    ]


def test_build_xml_instruction_round_trips_parsed_sections() -> None:
    """Structured sections should build back into XML that validates cleanly."""
    sections = parse_xml_instruction(SAMPLE_XML)

    rebuilt = build_xml_instruction(sections)
    validation = validate_xml_instruction(rebuilt)

    assert "<role>Weather support specialist.</role>" in rebuilt
    assert '<subtask name="Intent Routing">' in rebuilt
    assert validation["valid"] is True
    assert validation["errors"] == []


def test_validate_xml_instruction_reports_missing_required_sections() -> None:
    """Validation should fail when required recommended XML sections are missing."""
    validation = validate_xml_instruction("<role>Only a role.</role>")

    assert validation["valid"] is False
    assert "persona.primary_goal" in validation["errors"]
    assert "constraints" in validation["errors"]
    assert "taskflow" in validation["errors"]


def test_validate_xml_instruction_rejects_malformed_xml() -> None:
    """Malformed XML should be rejected with a parse error."""
    validation = validate_xml_instruction("<role>Broken</role><persona>")

    assert validation["valid"] is False
    assert any("xml" in error.lower() for error in validation["errors"])


def test_merge_xml_sections_replaces_override_lists_and_nested_fields() -> None:
    """Section overrides should replace targeted XML sections without dropping untouched content."""
    base = parse_xml_instruction(SAMPLE_XML)
    override = {
        "persona": {
            "primary_goal": "Handle refunds safely.",
            "guidelines": ["Be empathetic and direct."],
        },
        "constraints": ["Always verify the order number before account changes."],
    }

    merged = merge_xml_sections(base, override)

    assert merged["role"] == "Weather support specialist."
    assert merged["persona"]["primary_goal"] == "Handle refunds safely."
    assert merged["persona"]["guidelines"] == ["Be empathetic and direct."]
    assert merged["constraints"] == ["Always verify the order number before account changes."]
    assert merged["taskflow"][0]["name"] == "Intent Routing"


def test_migrate_instruction_text_infers_google_xml_sections_from_plain_text() -> None:
    """Plain-text instructions should migrate into the recommended XML structure."""
    plain_text = (
        "You are a customer support assistant. "
        "Help with refunds and order tracking. "
        "Always verify account details before making changes. "
        "If the request is unsafe, refuse politely."
    )

    sections = infer_instruction_sections(plain_text, agent_name="Customer Support Agent")
    migrated = migrate_instruction_text(plain_text, agent_name="Customer Support Agent")
    validation = validate_xml_instruction(migrated)

    assert sections["role"]
    assert sections["persona"]["primary_goal"]
    assert sections["constraints"]
    assert "<taskflow>" in migrated
    assert "<examples>" in migrated
    assert validation["valid"] is True
