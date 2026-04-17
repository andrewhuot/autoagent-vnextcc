"""Bridge legacy environment variables into typed settings."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})

_ENV_BRIDGES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("AGENTLAB_NO_TUI", ("input", "no_tui"), "bool"),
    ("AGENTLAB_EXPOSE_SLASH_TO_MODEL", ("input", "expose_slash_to_model"), "bool"),
    ("ANTHROPIC_API_KEY", ("providers", "anthropic_api_key"), "string"),
    ("OPENAI_API_KEY", ("providers", "openai_api_key"), "string"),
    ("GOOGLE_API_KEY", ("providers", "google_api_key"), "string"),
    ("GEMINI_API_KEY", ("providers", "gemini_api_key"), "string"),
)


def env_overrides(environ: Mapping[str, str] | None = None) -> tuple[dict[str, object], list[str]]:
    """Return typed settings overrides for legacy env vars after file layers load."""
    source = os.environ if environ is None else environ
    overrides: dict[str, object] = {}
    applied: list[str] = []

    for env_name, path, value_kind in _ENV_BRIDGES:
        raw_value = source.get(env_name)
        if raw_value is None:
            continue

        if value_kind == "bool":
            value = _parse_bool(raw_value)
            if value is None:
                continue
        else:
            if raw_value == "":
                continue
            value = raw_value

        _set_nested(overrides, path, value)
        applied.append(env_name)

    return overrides, applied


def _parse_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return None


def _set_nested(target: dict[str, object], path: tuple[str, ...], value: object) -> None:
    node: dict[str, Any] = target
    for part in path[:-1]:
        child = node.setdefault(part, {})
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[path[-1]] = value
