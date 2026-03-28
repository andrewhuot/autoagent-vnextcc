"""Template variable resolution for ADK instruction strings.

Supports ``{key}`` style placeholders that are resolved from a state dict.
"""
from __future__ import annotations

import re

# Matches {key} placeholders where key is a non-empty sequence of word chars,
# dots, dashes, colons or slashes (to support state-prefixed keys like
# "user:name" or "app:config.value").
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_.:\-/]+)\}")


def resolve_template_vars(
    instruction: str,
    state: dict,
    default: str = "",
) -> str:
    """Resolve ``{key}`` placeholders in *instruction* from *state*.

    Keys that are present in *state* are substituted with their string value.
    Keys that are absent are replaced with *default* (empty string by default).

    Args:
        instruction: Raw instruction string possibly containing ``{key}``
            placeholders.
        state: Flat dict used to resolve the placeholders.
        default: Value to use when a key is not found in *state*.

    Returns:
        The instruction string with all recognised placeholders substituted.

    Examples::

        >>> resolve_template_vars("Hello {user:name}!", {"user:name": "Alice"})
        'Hello Alice!'
        >>> resolve_template_vars("Val: {missing}", {}, default="N/A")
        'Val: N/A'
    """

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        value = state.get(key)
        if value is None:
            return default
        return str(value)

    return _PLACEHOLDER_RE.sub(_replace, instruction)


def extract_template_vars(instruction: str) -> list[str]:
    """Return all unique placeholder names found in *instruction*.

    Args:
        instruction: Raw instruction string possibly containing ``{key}``
            placeholders.

    Returns:
        Deduplicated list of placeholder names in order of first appearance.

    Examples::

        >>> extract_template_vars("Hi {user:name}, your role is {role}.")
        ['user:name', 'role']
    """
    seen: set[str] = set()
    result: list[str] = []
    for match in _PLACEHOLDER_RE.finditer(instruction):
        key = match.group(1)
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def validate_template_vars(
    instruction: str,
    available_keys: set[str],
) -> list[str]:
    """Return the names of placeholders in *instruction* that cannot be resolved.

    Args:
        instruction: Raw instruction string.
        available_keys: Set of keys that are available for resolution.

    Returns:
        List of placeholder names that are *not* in *available_keys*.

    Examples::

        >>> validate_template_vars("{a} {b}", {"a"})
        ['b']
    """
    return [k for k in extract_template_vars(instruction) if k not in available_keys]
