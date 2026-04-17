"""Cross-provider tool-schema translator.

Every bundled tool declares a JSON Schema under ``Tool.input_schema`` and
packs it into the canonical Anthropic tool-use shape via
:meth:`Tool.to_schema_entry`:

    {
        "name": "FileRead",
        "description": "...",
        "input_schema": {"type": "object", "properties": {...}, ...},
    }

This module converts that canonical shape to the three provider-specific
shapes we support:

* ``to_anthropic`` — passthrough. Anthropic's tool-use API consumes the
  canonical shape verbatim. We still normalise it (deep-copy + required
  keys validation) so callers can treat the return value as owned.
* ``to_openai`` — OpenAI function-calling shape:
  ``{"type": "function", "function": {"name", "description", "parameters"}}``.
  OpenAI accepts the full JSON Schema surface under ``parameters`` so no
  stripping is needed.
* ``to_gemini`` — Gemini ``Tool(function_declarations=[...])`` shape. The
  Gemini SDK takes an OpenAPI-subset JSON Schema, which **does not**
  accept several JSON Schema keywords that the other providers tolerate.
  We strip them recursively rather than raise, because our goal is
  best-effort round-trip across providers for the same registry.

Gemini-specific rules
---------------------
**Stripped** (dropped without error, nested recursively into children):

* ``$schema``, ``$id``, ``$ref``, ``$defs``, ``definitions`` — schema
  metadata the Gemini SDK rejects.
* ``additionalProperties`` — Gemini has no notion of an additional-property
  switch on ``object`` schemas. Dropping is safe because the function
  executor validates inputs against the canonical Anthropic shape, not
  against the SDK-emitted Gemini shape.
* ``pattern`` — JSON Schema regexes aren't part of OpenAPI 3.0 on the
  Gemini side.
* ``format`` values outside the OpenAPI-accepted set — we preserve
  ``date-time``, ``date``, ``time``, ``enum``, and drop the rest
  (``uri``, ``email``, ``regex`` etc.). Unknown formats would cause the
  SDK to reject the whole function declaration.
* ``const`` — OpenAPI 3.0 uses ``enum: [value]`` instead.

**Flattened with a warning** (logged at WARNING level, deduped):

* ``oneOf`` / ``anyOf`` — we use the first branch. Gemini's function
  schema is closed; there is no discriminated union. Callers who rely on
  disjunctions at the tool boundary should redesign the tool (or fall
  back to a string + runtime parse).
* ``allOf`` — we shallow-merge the branches. If keys collide, later
  entries win; this matches ``dict.update`` semantics.
* ``not`` — dropped; Gemini cannot express negation.

**Preserved** across all three providers: ``type``, ``description``,
``properties``, ``items``, ``required``, ``enum``, ``default``,
``minimum``, ``maximum``, ``minLength``, ``maxLength``, ``minItems``,
``maxItems``, ``nullable``.

Unknown JSON Schema keywords are stripped from the Gemini output rather
than raised — every adapter must survive a canonical schema that uses a
keyword its SDK doesn't understand. The translator **never raises** on
unknown input shape except for missing top-level keys (``name``,
``input_schema``), which are programmer errors.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)

_WARNED_KEYWORDS: set[str] = set()

# Keywords Gemini accepts on a property / schema node (OpenAPI 3.0 subset).
_GEMINI_ALLOWED_KEYWORDS: frozenset[str] = frozenset(
    {
        "type",
        "description",
        "properties",
        "items",
        "required",
        "enum",
        "default",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "nullable",
        "title",
        "example",
    }
)

# Formats Gemini's OpenAPI subset accepts. Others (``uri``, ``email``,
# ``regex``, ``uuid``) are dropped to avoid SDK rejection.
_GEMINI_ALLOWED_FORMATS: frozenset[str] = frozenset(
    {"date-time", "date", "time", "enum", "int32", "int64", "float", "double"}
)

# Keywords that are silently stripped from Gemini (no warning — they are
# expected to appear and are benign when dropped).
_GEMINI_SILENT_STRIP: frozenset[str] = frozenset(
    {
        "$schema",
        "$id",
        "$ref",
        "$defs",
        "definitions",
        "additionalProperties",
        "pattern",
        "patternProperties",
        "const",
        "not",
    }
)

# Keywords that are flattened with a warning the first time we see them.
_GEMINI_FLATTEN_WARN: frozenset[str] = frozenset({"oneOf", "anyOf", "allOf"})


class ToolSchemaError(ValueError):
    """Raised when a canonical schema is missing required top-level keys."""


# ---------------------------------------------------------------------------
# Canonical-shape validation
# ---------------------------------------------------------------------------


def _validate_canonical(schema: dict[str, Any]) -> None:
    """Check that the canonical Anthropic shape is present.

    ``name`` and ``input_schema`` are mandatory; ``description`` is
    optional (some MCP tools omit it).
    """
    if not isinstance(schema, dict):
        raise ToolSchemaError(
            f"Canonical tool schema must be a dict, got {type(schema).__name__}."
        )
    if "name" not in schema or not isinstance(schema["name"], str):
        raise ToolSchemaError("Canonical tool schema missing string 'name'.")
    if "input_schema" not in schema:
        raise ToolSchemaError(
            f"Canonical tool schema {schema['name']!r} missing 'input_schema'."
        )
    if not isinstance(schema["input_schema"], dict):
        raise ToolSchemaError(
            f"Canonical tool schema {schema['name']!r} has non-dict 'input_schema'."
        )


# ---------------------------------------------------------------------------
# Anthropic — passthrough (normalised copy)
# ---------------------------------------------------------------------------


def to_anthropic(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical Anthropic tool-use shape.

    Anthropic consumes the canonical shape verbatim. We deep-copy so
    callers can mutate the return value without affecting the input, and
    we normalise missing optional fields (``description``).
    """
    _validate_canonical(schema)
    out: dict[str, Any] = {
        "name": schema["name"],
        "description": schema.get("description", ""),
        "input_schema": copy.deepcopy(schema["input_schema"]),
    }
    return out


# ---------------------------------------------------------------------------
# OpenAI — {"type": "function", "function": {...}}
# ---------------------------------------------------------------------------


def to_openai(schema: dict[str, Any]) -> dict[str, Any]:
    """Emit the OpenAI function-calling tool shape.

    OpenAI's JSON Schema surface is permissive — we pass the canonical
    ``input_schema`` through untouched (deep-copied).
    """
    _validate_canonical(schema)
    parameters = copy.deepcopy(schema["input_schema"])
    # OpenAI expects at minimum ``type: object`` on the parameters block.
    if "type" not in parameters:
        parameters["type"] = "object"
    return {
        "type": "function",
        "function": {
            "name": schema["name"],
            "description": schema.get("description", ""),
            "parameters": parameters,
        },
    }


# ---------------------------------------------------------------------------
# Gemini — function_declarations with OpenAPI-subset parameters
# ---------------------------------------------------------------------------


def to_gemini(schema: dict[str, Any]) -> dict[str, Any]:
    """Emit the Gemini function-declaration shape.

    Returns ``{"name", "description", "parameters"}`` where ``parameters``
    is an OpenAPI-subset JSON Schema — every keyword the Gemini SDK
    rejects has been stripped or flattened. See module docstring for the
    full rule list.
    """
    _validate_canonical(schema)
    parameters = _simplify_for_gemini(schema["input_schema"], path=schema["name"])
    if "type" not in parameters:
        parameters["type"] = "object"
    return {
        "name": schema["name"],
        "description": schema.get("description", ""),
        "parameters": parameters,
    }


def _simplify_for_gemini(node: Any, *, path: str) -> Any:
    """Recursive reducer producing the OpenAPI-subset form.

    ``path`` is a dotted breadcrumb used only in warning logs so an
    operator can locate the offending schema node.
    """
    if not isinstance(node, dict):
        # Arrays of strings (enum values, required list), primitives — pass through.
        return copy.deepcopy(node)

    out: dict[str, Any] = {}

    # First pass: flatten oneOf/anyOf/allOf/not BEFORE iterating keys so the
    # keys picked from a flattened branch are subject to the same strip rules.
    node = _flatten_unions(node, path=path)

    for key, value in node.items():
        if key in _GEMINI_SILENT_STRIP:
            continue
        if key in _GEMINI_FLATTEN_WARN:
            # _flatten_unions should have handled these; defensively skip.
            _warn_once(key, path)
            continue
        if key == "format":
            if isinstance(value, str) and value in _GEMINI_ALLOWED_FORMATS:
                out[key] = value
            # otherwise drop silently — non-OpenAPI format.
            continue
        if key == "properties" and isinstance(value, dict):
            out["properties"] = {
                prop_name: _simplify_for_gemini(prop_schema, path=f"{path}.{prop_name}")
                for prop_name, prop_schema in value.items()
            }
            continue
        if key == "items":
            out["items"] = _simplify_for_gemini(value, path=f"{path}[]")
            continue
        if key in _GEMINI_ALLOWED_KEYWORDS:
            out[key] = copy.deepcopy(value)
            continue
        # Unknown keyword — strip silently. Warn once per keyword so an
        # operator notices if a new schema feature appears in a tool.
        _warn_once(key, path)

    return out


def _flatten_unions(node: dict[str, Any], *, path: str) -> dict[str, Any]:
    """Collapse ``oneOf``/``anyOf``/``allOf``/``not`` into the surrounding node.

    * ``oneOf`` / ``anyOf`` — take the first branch. A tool that relied on
      a discriminated union at the schema boundary will not round-trip;
      we surface that via a one-time warning.
    * ``allOf`` — shallow-merge every branch into the surrounding node
      (``dict.update`` semantics; later branches win on key collision).
    * ``not`` — stripped silently (no direct equivalent in OpenAPI 3.0).
    """
    has_union = any(key in node for key in ("oneOf", "anyOf", "allOf"))
    if not has_union:
        return node

    # Work on a shallow copy so we can pop union keys.
    merged = {k: v for k, v in node.items() if k not in ("oneOf", "anyOf", "allOf", "not")}

    one_of = node.get("oneOf")
    any_of = node.get("anyOf")
    all_of = node.get("allOf")

    if isinstance(all_of, list):
        for branch in all_of:
            if isinstance(branch, dict):
                merged.update(branch)
        _warn_once("allOf", path)

    if isinstance(one_of, list) and one_of:
        first = one_of[0]
        if isinstance(first, dict):
            # Fields already in merged win — explicit sibling keys beat the
            # branch. This mirrors "allOf merges in, oneOf fills gaps".
            for k, v in first.items():
                merged.setdefault(k, v)
        _warn_once("oneOf", path)
    elif isinstance(any_of, list) and any_of:
        first = any_of[0]
        if isinstance(first, dict):
            for k, v in first.items():
                merged.setdefault(k, v)
        _warn_once("anyOf", path)

    return merged


def _warn_once(keyword: str, path: str) -> None:
    """Log a keyword-stripped warning once per keyword across the process."""
    if keyword in _WARNED_KEYWORDS:
        return
    _WARNED_KEYWORDS.add(keyword)
    logger.warning(
        "tool_schema_translator: dropping/flattening unsupported Gemini keyword "
        "%r (first seen at %s). See module docstring for the full rule list.",
        keyword,
        path,
    )


__all__ = ["to_anthropic", "to_openai", "to_gemini", "ToolSchemaError"]
