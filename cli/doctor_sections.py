"""Pure data builders for ``agentlab doctor`` and the workbench doctor screen.

Two flavors per section:

* ``*_section()`` returns a serializable dict the JSON ``--json`` mode
  can dump verbatim and that tests can assert against,
* ``render_*_section()`` returns a list of human-readable lines (no
  click colors here — the runner wraps them with style on output).

These builders never raise on partial settings or hook-registry load
errors; the doctor surface should degrade gracefully and show what it
knows, not crash.
"""

from __future__ import annotations

from typing import Any, Mapping

from cli.hooks import HookRegistry
from cli.hooks.types import HookEvent, HookType
from cli.settings import Settings


# ---------------------------------------------------------------------------
# Constants — keep ordering stable for test assertions and human readability.
# ---------------------------------------------------------------------------

_HOOK_EVENT_NAMES: tuple[str, ...] = (
    "beforeQuery",
    "afterQuery",
    "PreToolUse",
    "PostToolUse",
    "OnPermissionRequest",
    "SubagentStop",
    "SessionEnd",
    "Stop",
)


# ---------------------------------------------------------------------------
# Settings section
# ---------------------------------------------------------------------------


def settings_section(settings: Settings | None) -> dict[str, Any]:
    """Build the settings cascade diagnostic block.

    Returns a JSON-safe dict; never includes API key values. Safe to call
    with ``None`` to support callers that catch a settings-load failure.
    """
    if settings is None:
        return _empty_settings_section()

    try:
        loaded_layers = list(getattr(settings, "_loaded_layers", []) or [])
    except Exception:
        loaded_layers = []

    try:
        env_overrides = list(getattr(settings, "_env_overrides", []) or [])
    except Exception:
        env_overrides = []

    permission_mode = _safe_attr(settings, "permissions.mode", default="default")
    sessions_root = _safe_attr(settings, "sessions.root", default=None)
    hook_counts = _hook_event_counts_from_settings(settings)

    providers = {
        "default_provider": _safe_attr(settings, "providers.default_provider", default=None),
        "default_model": _safe_attr(settings, "providers.default_model", default=None),
        # Surface only whether each key is present — never the value.
        "anthropic_api_key_set": bool(_safe_attr(settings, "providers.anthropic_api_key", default=None)),
        "openai_api_key_set": bool(_safe_attr(settings, "providers.openai_api_key", default=None)),
        "google_api_key_set": bool(_safe_attr(settings, "providers.google_api_key", default=None)),
        "gemini_api_key_set": bool(_safe_attr(settings, "providers.gemini_api_key", default=None)),
    }

    return {
        "loaded_layers": loaded_layers,
        "env_overrides": env_overrides,
        "permission_mode": permission_mode,
        "providers": providers,
        "sessions_root": sessions_root,
        "hooks": hook_counts,
    }


def render_settings_section(settings: Settings | None) -> list[str]:
    """Render the settings section as plain lines for the doctor command."""
    section = settings_section(settings)
    lines: list[str] = ["", "Settings"]

    layers = section["loaded_layers"]
    if layers:
        lines.append("  Cascade:")
        for layer in layers:
            label = layer.get("layer", "?")
            path = layer.get("path", "?")
            lines.append(f"    - {label}: {path}")
    else:
        lines.append("  Cascade:           (no layer info available)")

    overrides = section["env_overrides"]
    if overrides:
        lines.append(f"  Env overrides:     {', '.join(overrides)}")
    else:
        lines.append("  Env overrides:     (none)")

    lines.append(f"  Permission mode:   {section['permission_mode']}")
    sessions_root = section["sessions_root"] or "(default)"
    lines.append(f"  Sessions root:     {sessions_root}")

    providers = section["providers"]
    lines.append(
        f"  Provider:          {providers['default_provider'] or '(unset)'}"
    )
    lines.append(
        f"  Model:             {providers['default_model'] or '(unset)'}"
    )
    key_flags = [
        ("anthropic", providers["anthropic_api_key_set"]),
        ("openai", providers["openai_api_key_set"]),
        ("google", providers["google_api_key_set"]),
        ("gemini", providers["gemini_api_key_set"]),
    ]
    set_keys = [name for name, present in key_flags if present]
    if set_keys:
        lines.append(f"  Provider keys:     {', '.join(set_keys)} configured")
    else:
        lines.append("  Provider keys:     (none configured in settings)")

    hook_counts = section["hooks"]
    if hook_counts:
        summary = ", ".join(f"{name}={count}" for name, count in hook_counts.items())
        lines.append(f"  Hooks (settings):  {summary}")
    else:
        lines.append("  Hooks (settings):  (none registered)")

    return lines


def _empty_settings_section() -> dict[str, Any]:
    return {
        "loaded_layers": [],
        "env_overrides": [],
        "permission_mode": "default",
        "providers": {
            "default_provider": None,
            "default_model": None,
            "anthropic_api_key_set": False,
            "openai_api_key_set": False,
            "google_api_key_set": False,
            "gemini_api_key_set": False,
        },
        "sessions_root": None,
        "hooks": {},
    }


def _hook_event_counts_from_settings(settings: Settings) -> dict[str, int]:
    try:
        event_map = settings.hooks.event_map()
    except Exception:
        return {}
    counts: dict[str, int] = {}
    for name in _HOOK_EVENT_NAMES:
        entries = event_map.get(name)
        if not entries:
            continue
        # Each entry is a HookMatcher with nested hooks.
        total = 0
        for entry in entries:
            nested = getattr(entry, "hooks", None)
            if nested is None and isinstance(entry, Mapping):
                nested = entry.get("hooks")
            total += len(nested or [])
        if total > 0:
            counts[name] = total
    return counts


# ---------------------------------------------------------------------------
# Hooks section
# ---------------------------------------------------------------------------


def hooks_section(registry: HookRegistry | None) -> dict[str, Any]:
    """Build the hook-registry diagnostic block.

    Reports counts and per-event hook sources (command path or prompt
    excerpt) so users can audit what will run on each lifecycle event.
    Surfaces any ``registry.load_errors`` instead of crashing.
    """
    if registry is None:
        return {"counts": {}, "entries": {}, "errors": []}

    counts: dict[str, int] = {}
    entries: dict[str, list[dict[str, str]]] = {}

    definitions = getattr(registry, "definitions", {}) or {}
    for event, hooks in definitions.items():
        if not hooks:
            continue
        name = _event_name(event)
        counts[name] = len(hooks)
        entries[name] = [_hook_entry(hook) for hook in hooks]

    errors_attr = getattr(registry, "load_errors", None) or []
    try:
        errors = list(errors_attr)
    except Exception:
        errors = []

    return {"counts": counts, "entries": entries, "errors": errors}


def render_hooks_section(registry: HookRegistry | None) -> list[str]:
    """Render the hooks section as plain lines for the doctor command."""
    section = hooks_section(registry)
    lines: list[str] = ["", "Hooks"]

    counts = section["counts"]
    if not counts:
        lines.append("  (no hooks registered)")
        if section["errors"]:
            lines.append("  Load errors:")
            for err in section["errors"]:
                lines.append(f"    - {err}")
        return lines

    for name, count in counts.items():
        lines.append(f"  {name}: {count}")
        for entry in section["entries"].get(name, []):
            matcher = entry.get("matcher") or "(any)"
            source = entry.get("source", "")
            kind = entry.get("type", "command")
            lines.append(f"    - matcher={matcher} type={kind} source={source}")

    if section["errors"]:
        lines.append("  Load errors:")
        for err in section["errors"]:
            lines.append(f"    - {err}")

    return lines


def _hook_entry(hook: Any) -> dict[str, str]:
    hook_type = getattr(hook, "hook_type", HookType.COMMAND)
    if hook_type is HookType.PROMPT:
        prompt = (getattr(hook, "prompt", "") or "").strip()
        # Truncate to keep the doctor output readable.
        excerpt = prompt[:80] + ("..." if len(prompt) > 80 else "")
        return {
            "matcher": getattr(hook, "matcher", "") or "",
            "type": "prompt",
            "source": excerpt,
        }
    return {
        "matcher": getattr(hook, "matcher", "") or "",
        "type": "command",
        "source": getattr(hook, "command", "") or "",
    }


def _event_name(event: Any) -> str:
    if isinstance(event, HookEvent):
        return event.value
    return str(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_attr(node: Any, dotted: str, *, default: Any = None) -> Any:
    """Walk a dotted attribute path; return ``default`` on any failure."""
    current = node
    for part in dotted.split("."):
        try:
            current = getattr(current, part)
        except Exception:
            return default
        if current is None:
            return default
    return current


__all__ = [
    "hooks_section",
    "render_hooks_section",
    "render_settings_section",
    "settings_section",
]
