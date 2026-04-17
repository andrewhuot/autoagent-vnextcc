"""Tests for :mod:`cli.llm.tool_schema_translator`.

Covers:
1. Passthrough behaviour for Anthropic.
2. OpenAI wrapping under ``function`` key.
3. Gemini stripping of JSON Schema keywords not in its OpenAPI subset.
4. Round-trip across all 14 bundled tools via golden snapshots.
5. Edge cases — nested objects, enums, defaults, unicode, union flattening.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from cli.llm.tool_schema_translator import (
    ToolSchemaError,
    to_anthropic,
    to_gemini,
    to_openai,
)
from cli.tools.registry import default_registry


BUNDLED_TOOL_NAMES = [
    "AgentSpawn",
    "Bash",
    "ConfigEdit",
    "ConfigRead",
    "ExitPlanMode",
    "FileEdit",
    "FileRead",
    "FileWrite",
    "Glob",
    "Grep",
    "SkillTool",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
]


GOLDEN_ROOT = Path(__file__).parent / "golden" / "tool_schemas"


# ---------------------------------------------------------------------------
# Anthropic passthrough
# ---------------------------------------------------------------------------


def test_to_anthropic_preserves_name_description_input_schema():
    schema = {
        "name": "FileRead",
        "description": "Read a file from disk.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    }
    out = to_anthropic(schema)
    assert out["name"] == "FileRead"
    assert out["description"] == "Read a file from disk."
    assert out["input_schema"]["properties"]["path"] == {"type": "string"}
    assert out["input_schema"]["required"] == ["path"]


def test_to_anthropic_deep_copies_input_schema():
    """Mutating the return value must not affect the input."""
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {"type": "object", "properties": {"a": {"type": "string"}}},
    }
    out = to_anthropic(schema)
    out["input_schema"]["properties"]["a"]["type"] = "integer"
    assert schema["input_schema"]["properties"]["a"]["type"] == "string"


def test_to_anthropic_normalises_missing_description():
    schema = {"name": "X", "input_schema": {"type": "object"}}
    out = to_anthropic(schema)
    assert out["description"] == ""


def test_to_anthropic_raises_on_missing_name():
    with pytest.raises(ToolSchemaError, match="name"):
        to_anthropic({"input_schema": {"type": "object"}})


def test_to_anthropic_raises_on_missing_input_schema():
    with pytest.raises(ToolSchemaError, match="input_schema"):
        to_anthropic({"name": "X"})


# ---------------------------------------------------------------------------
# OpenAI shape
# ---------------------------------------------------------------------------


def test_to_openai_wraps_under_function_key():
    schema = {
        "name": "FileRead",
        "description": "Read a file",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
    }
    out = to_openai(schema)
    assert out["type"] == "function"
    assert out["function"]["name"] == "FileRead"
    assert out["function"]["description"] == "Read a file"
    assert out["function"]["parameters"]["properties"]["path"]["type"] == "string"


def test_to_openai_preserves_required_fields():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        },
    }
    out = to_openai(schema)
    assert out["function"]["parameters"]["required"] == ["a"]


def test_to_openai_preserves_enums():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["plan", "act"]}},
        },
    }
    out = to_openai(schema)
    assert out["function"]["parameters"]["properties"]["mode"]["enum"] == ["plan", "act"]


def test_to_openai_preserves_defaults():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10}},
        },
    }
    out = to_openai(schema)
    assert out["function"]["parameters"]["properties"]["limit"]["default"] == 10


def test_to_openai_preserves_additional_properties():
    """OpenAI accepts additionalProperties; we must not strip it."""
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "additionalProperties": False,
        },
    }
    out = to_openai(schema)
    assert out["function"]["parameters"]["additionalProperties"] is False


def test_to_openai_deep_copies_parameters():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {"type": "object", "properties": {"a": {"type": "string"}}},
    }
    out = to_openai(schema)
    out["function"]["parameters"]["properties"]["a"]["type"] = "integer"
    assert schema["input_schema"]["properties"]["a"]["type"] == "string"


def test_to_openai_fills_missing_parameters_type():
    schema = {"name": "X", "description": "", "input_schema": {"properties": {}}}
    out = to_openai(schema)
    assert out["function"]["parameters"]["type"] == "object"


def test_to_openai_raises_on_missing_name():
    with pytest.raises(ToolSchemaError):
        to_openai({"input_schema": {"type": "object"}})


# ---------------------------------------------------------------------------
# Gemini shape
# ---------------------------------------------------------------------------


def test_to_gemini_emits_function_declaration_shape():
    schema = {
        "name": "FileRead",
        "description": "Read a file",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    }
    out = to_gemini(schema)
    assert set(out.keys()) == {"name", "description", "parameters"}
    assert out["name"] == "FileRead"
    assert out["parameters"]["properties"]["path"]["type"] == "string"
    assert out["parameters"]["required"] == ["path"]


def test_to_gemini_strips_additional_properties():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "additionalProperties": False,
        },
    }
    out = to_gemini(schema)
    assert "additionalProperties" not in out["parameters"]
    assert out["parameters"]["properties"]["a"]["type"] == "string"


def test_to_gemini_strips_nested_additional_properties():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"x": {"type": "string"}},
                    },
                },
            },
        },
    }
    out = to_gemini(schema)
    inner = out["parameters"]["properties"]["items"]["items"]
    assert "additionalProperties" not in inner
    assert inner["properties"]["x"]["type"] == "string"


def test_to_gemini_strips_dollar_schema_and_ref():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "$schema": "http://json-schema.org/draft-07/schema",
            "$id": "foo",
            "properties": {"a": {"type": "string", "$ref": "#/defs/x"}},
        },
    }
    out = to_gemini(schema)
    assert "$schema" not in out["parameters"]
    assert "$id" not in out["parameters"]
    assert "$ref" not in out["parameters"]["properties"]["a"]


def test_to_gemini_strips_unknown_format():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string", "format": "regex"}},
        },
    }
    out = to_gemini(schema)
    assert "format" not in out["parameters"]["properties"]["pattern"]


def test_to_gemini_preserves_allowed_format_date_time():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {"when": {"type": "string", "format": "date-time"}},
        },
    }
    out = to_gemini(schema)
    assert out["parameters"]["properties"]["when"]["format"] == "date-time"


def test_to_gemini_strips_pattern_and_const():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "string", "pattern": "^foo"},
                "b": {"const": "bar"},
            },
        },
    }
    out = to_gemini(schema)
    assert "pattern" not in out["parameters"]["properties"]["a"]
    assert "const" not in out["parameters"]["properties"]["b"]


def test_to_gemini_preserves_enum():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["plan", "act"]}},
        },
    }
    out = to_gemini(schema)
    assert out["parameters"]["properties"]["mode"]["enum"] == ["plan", "act"]


def test_to_gemini_preserves_required():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
        },
    }
    out = to_gemini(schema)
    assert out["parameters"]["required"] == ["a"]


def test_to_gemini_flattens_oneof_with_warning(caplog):
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "integer"},
                    ],
                },
            },
        },
    }
    caplog.set_level(logging.WARNING, logger="cli.llm.tool_schema_translator")
    # Reset the dedupe cache so warnings fire for this test.
    import cli.llm.tool_schema_translator as mod

    mod._WARNED_KEYWORDS.discard("oneOf")
    out = to_gemini(schema)
    # First branch wins.
    assert out["parameters"]["properties"]["value"]["type"] == "string"
    # No oneOf leaks through.
    assert "oneOf" not in out["parameters"]["properties"]["value"]
    assert any("oneOf" in r.message for r in caplog.records)


def test_to_gemini_flattens_anyof_first_branch():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
            },
        },
    }
    out = to_gemini(schema)
    assert out["parameters"]["properties"]["value"]["type"] == "integer"
    assert "anyOf" not in out["parameters"]["properties"]["value"]


def test_to_gemini_flattens_allof_merge():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "allOf": [
                {"properties": {"a": {"type": "string"}}},
                {"required": ["a"]},
            ],
        },
    }
    out = to_gemini(schema)
    # Both branches merged into the parameters node.
    assert out["parameters"]["properties"]["a"]["type"] == "string"
    assert out["parameters"]["required"] == ["a"]
    assert "allOf" not in out["parameters"]


def test_to_gemini_strips_not():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {"a": {"type": "string", "not": {"enum": ["forbidden"]}}},
        },
    }
    out = to_gemini(schema)
    assert "not" not in out["parameters"]["properties"]["a"]


def test_to_gemini_fills_missing_parameters_type():
    schema = {"name": "X", "description": "", "input_schema": {"properties": {}}}
    out = to_gemini(schema)
    assert out["parameters"]["type"] == "object"


def test_to_gemini_unknown_keyword_stripped_and_warned(caplog):
    import cli.llm.tool_schema_translator as mod

    mod._WARNED_KEYWORDS.discard("experimentalFoo")
    caplog.set_level(logging.WARNING, logger="cli.llm.tool_schema_translator")
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "experimentalFoo": True,
            "properties": {"a": {"type": "string"}},
        },
    }
    out = to_gemini(schema)
    assert "experimentalFoo" not in out["parameters"]
    assert any("experimentalFoo" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Cross-cutting edge cases
# ---------------------------------------------------------------------------


def test_nested_object_schema_round_trips_across_all_three():
    """TodoWrite-style: array of objects with nested enum + required."""
    schema = default_registry().get("TodoWrite").to_schema_entry()
    assert schema["input_schema"]["properties"]["items"]["type"] == "array"

    anth = to_anthropic(schema)
    oai = to_openai(schema)
    gem = to_gemini(schema)

    # Anthropic + OpenAI preserve the full nested shape.
    anth_item = anth["input_schema"]["properties"]["items"]["items"]
    assert anth_item["type"] == "object"
    assert "status" in anth_item["properties"]
    assert set(anth_item["properties"]["status"]["enum"]) == {
        "completed",
        "in_progress",
        "pending",
    }

    oai_item = oai["function"]["parameters"]["properties"]["items"]["items"]
    assert oai_item["type"] == "object"
    assert oai_item["properties"]["status"]["enum"] == sorted(
        ["completed", "in_progress", "pending"]
    )

    # Gemini preserves the structure but strips additionalProperties.
    gem_item = gem["parameters"]["properties"]["items"]["items"]
    assert gem_item["type"] == "object"
    assert "additionalProperties" not in gem_item
    assert set(gem_item["properties"]["status"]["enum"]) == {
        "completed",
        "in_progress",
        "pending",
    }


def test_deeply_nested_objects_recurse_correctly():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {
                "a": {
                    "type": "object",
                    "properties": {
                        "b": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {"c": {"type": "string"}},
                        },
                    },
                },
            },
        },
    }
    gem = to_gemini(schema)
    deep = gem["parameters"]["properties"]["a"]["properties"]["b"]
    assert "additionalProperties" not in deep
    assert deep["properties"]["c"]["type"] == "string"


def test_empty_input_schema_no_properties():
    schema = {"name": "X", "description": "", "input_schema": {"type": "object"}}
    assert to_anthropic(schema)["input_schema"] == {"type": "object"}
    assert to_openai(schema)["function"]["parameters"] == {"type": "object"}
    assert to_gemini(schema)["parameters"] == {"type": "object"}


def test_unicode_descriptions_round_trip():
    schema = {
        "name": "X",
        "description": "Résumé — with emojis naïvely",
        "input_schema": {
            "type": "object",
            "properties": {
                "msg": {"type": "string", "description": "日本語 message"},
            },
        },
    }
    for fn in (to_anthropic, to_openai, to_gemini):
        out = fn(schema)
        blob = json.dumps(out, ensure_ascii=False)
        assert "Résumé" in blob
        assert "日本語" in blob


def test_arrays_recurse_into_items():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["a", "b"],
                        "pattern": "^[ab]$",
                    },
                },
            },
        },
    }
    gem = to_gemini(schema)
    items_schema = gem["parameters"]["properties"]["tags"]["items"]
    assert items_schema["enum"] == ["a", "b"]
    assert "pattern" not in items_schema  # stripped for Gemini
    oai = to_openai(schema)
    oai_items = oai["function"]["parameters"]["properties"]["tags"]["items"]
    # OpenAI keeps pattern (JSON Schema permissive).
    assert oai_items["pattern"] == "^[ab]$"


def test_property_descriptions_preserved_in_all_three():
    schema = {
        "name": "X",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Where the file lives."},
            },
        },
    }
    for fn, accessor in (
        (to_anthropic, lambda o: o["input_schema"]),
        (to_openai, lambda o: o["function"]["parameters"]),
        (to_gemini, lambda o: o["parameters"]),
    ):
        out = fn(schema)
        assert accessor(out)["properties"]["path"]["description"] == "Where the file lives."


# ---------------------------------------------------------------------------
# Golden-snapshot per bundled tool × provider
# ---------------------------------------------------------------------------


def _translate(provider: str, schema: dict) -> dict:
    return {
        "anthropic": to_anthropic,
        "openai": to_openai,
        "gemini": to_gemini,
    }[provider](schema)


@pytest.mark.parametrize("tool_name", BUNDLED_TOOL_NAMES)
@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini"])
def test_bundled_tool_golden_snapshot(tool_name: str, provider: str) -> None:
    """Every bundled tool round-trips against a committed golden file.

    Regenerate with ``AGENTLAB_REGEN_TOOL_SCHEMAS=1 pytest tests/test_tool_schema_translator.py``.
    """
    schema = default_registry().get(tool_name).to_schema_entry()
    translated = _translate(provider, schema)

    golden_dir = GOLDEN_ROOT / provider
    golden_dir.mkdir(parents=True, exist_ok=True)
    golden_path = golden_dir / f"{tool_name}.json"

    if os.environ.get("AGENTLAB_REGEN_TOOL_SCHEMAS"):
        golden_path.write_text(
            json.dumps(translated, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    assert golden_path.exists(), f"Missing golden: {golden_path}"
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    assert translated == expected, (
        f"Translated schema for {provider}/{tool_name} drifted from golden. "
        f"Regenerate with AGENTLAB_REGEN_TOOL_SCHEMAS=1."
    )


def test_all_14_bundled_tools_discoverable():
    """Fail loud if someone adds/removes a bundled tool without updating the parametrize list.

    Other tests in the suite can register extra tools on the shared default
    registry; assert that every parametrized name is present (subset check)
    rather than exact equality.
    """
    from cli.tools.registry import ToolRegistry, _register_builtins

    fresh = ToolRegistry()
    _register_builtins(fresh)
    registry_names = {t.name for t in fresh.list()}
    assert registry_names == set(BUNDLED_TOOL_NAMES)
    assert len(registry_names) == 14
