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

from pathlib import Path
from typing import Any, Mapping

from cli.hooks import HookRegistry
from cli.hooks.types import HookEvent, HookType
from cli.llm.pricing import TokenPrice, resolve
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


# ---------------------------------------------------------------------------
# Cost section
# ---------------------------------------------------------------------------


def cost_section(
    settings: Settings | None,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Build the per-turn cost rate card for ``(provider, model)``.

    When the caller doesn't supply ``provider`` / ``model`` we fall back
    to ``settings.providers.default_provider`` / ``default_model`` so
    ``agentlab doctor`` with no arguments surfaces the active rate card.
    The section is JSON-safe and never raises — unknown pairs resolve to
    the :data:`cli.llm.pricing.DEFAULT_PRICE` fallback and show up as
    ``"source": "fallback"`` so the doctor output tells the user why the
    numbers might not match their invoice.
    """
    resolved_provider = provider or _safe_attr(
        settings, "providers.default_provider", default=None
    )
    resolved_model = model or _safe_attr(
        settings, "providers.default_model", default=None
    )
    overrides: dict[str, dict[str, float]] = {}
    if settings is not None:
        raw_overrides = _safe_attr(settings, "providers.pricing_overrides", default=None)
        if isinstance(raw_overrides, dict):
            overrides = raw_overrides

    if not resolved_provider or not resolved_model:
        return {
            "provider": resolved_provider,
            "model": resolved_model,
            "source": "unset",
            "price": None,
            "has_override": False,
        }

    price: TokenPrice = resolve(
        resolved_provider, resolved_model, overrides=overrides or None
    )
    override_key = f"{resolved_provider}:{resolved_model}"
    has_override = override_key in overrides

    # Tag the source so the renderer can say "using claude-sonnet-4-6
    # rates" without re-implementing the PRICING lookup.
    from cli.llm.pricing import PRICING, DEFAULT_PRICE

    if has_override:
        source = "override"
    elif (resolved_provider, resolved_model) in PRICING:
        source = "table"
    elif price is DEFAULT_PRICE:
        source = "fallback"
    else:  # pragma: no cover — resolve only returns table/override/DEFAULT
        source = "table"

    return {
        "provider": resolved_provider,
        "model": resolved_model,
        "source": source,
        "has_override": has_override,
        "price": {
            "input_per_m": price.input_per_m,
            "output_per_m": price.output_per_m,
            "cache_read_per_m": price.cache_read_per_m,
            "cache_write_per_m": price.cache_write_per_m,
            "thinking_per_m": price.thinking_per_m,
        },
    }


def render_cost_section(
    settings: Settings | None,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> list[str]:
    """Render the cost section as plain lines for the doctor command."""
    section = cost_section(settings, provider=provider, model=model)
    lines: list[str] = ["", "Cost"]

    resolved_provider = section["provider"]
    resolved_model = section["model"]
    if not resolved_provider or not resolved_model:
        lines.append("  Rate card:         (no default provider/model configured)")
        return lines

    source = section["source"]
    source_label = {
        "table": "built-in pricing table",
        "override": "settings override",
        "fallback": "DEFAULT_PRICE fallback (model not in pricing table)",
    }.get(source, source)

    lines.append(f"  Using:             {resolved_provider}/{resolved_model} rates")
    lines.append(f"  Source:            {source_label}")
    price = section["price"] or {}
    lines.append(
        f"  Input:             ${price.get('input_per_m', 0):.4f} / 1M tokens"
    )
    lines.append(
        f"  Output:            ${price.get('output_per_m', 0):.4f} / 1M tokens"
    )
    cache_read = price.get("cache_read_per_m")
    if cache_read is not None:
        lines.append(f"  Cache read:        ${cache_read:.4f} / 1M tokens")
    cache_write = price.get("cache_write_per_m")
    if cache_write is not None:
        lines.append(f"  Cache write:       ${cache_write:.4f} / 1M tokens")
    thinking = price.get("thinking_per_m")
    if thinking is not None:
        lines.append(f"  Thinking:          ${thinking:.4f} / 1M tokens")
    return lines


# ---------------------------------------------------------------------------
# Classifier section (P3.T4)
# ---------------------------------------------------------------------------


def classifier_section(root: str | Path | None) -> dict[str, Any]:
    """Build the transcript-classifier diagnostic block.

    Reports how many persisted-allow patterns are in scope and the
    audit-log metadata (path, size, most-recent timestamp). Per-session
    state like :class:`~cli.permissions.denial_tracking.DenialTracker`
    is explicitly NOT reported — ``/doctor`` runs out-of-band and has no
    session handle. Users who want the live denial state should use
    ``/perms`` inside the workbench.

    Accepts ``None`` for callers that have no workspace; the returned
    dict still has the expected keys so renderers don't special-case.
    """
    if root is None:
        return _empty_classifier_section()

    root_path = Path(root)
    allowlist_count = _classifier_allowlist_count(root_path)
    audit = _classifier_audit_metadata(root_path)

    return {
        "workspace_root": str(root_path),
        "allowlist_path": str(root_path / ".agentlab" / "classifier_allowlist.json"),
        "allowlist_count": allowlist_count,
        "audit_log_path": audit["path"],
        "audit_log_exists": audit["exists"],
        "audit_log_size_bytes": audit["size"],
        "last_entry_ts": audit["last_ts"],
    }


def render_classifier_section(root: str | Path | None) -> list[str]:
    """Render the classifier section as plain lines for the doctor command.

    Layout matches the existing :func:`render_settings_section`:
    two-space indent, colon-aligned labels, no ANSI colours (callers
    add colour).
    """
    section = classifier_section(root)
    lines: list[str] = ["", "Classifier"]

    count = section.get("allowlist_count", 0)
    allowlist_path = section.get("allowlist_path") or "(no workspace)"
    if count:
        lines.append(f"  Allowlist:         {count} pattern(s) at {allowlist_path}")
    else:
        lines.append(f"  Allowlist:         (empty) — file: {allowlist_path}")

    audit_path = section.get("audit_log_path") or "(no workspace)"
    if section.get("audit_log_exists"):
        size = section.get("audit_log_size_bytes") or 0
        last_ts = section.get("last_entry_ts") or "(none)"
        lines.append(f"  Audit log:         {audit_path}")
        lines.append(f"  Audit size:        {size} bytes")
        lines.append(f"  Last entry:        {last_ts}")
    else:
        lines.append(f"  Audit log:         (not yet written) — {audit_path}")

    # Denial tracker is session-scoped; documented here so users don't
    # assume the absence of the field means "no denials".
    lines.append(
        "  Denial tracker:    session-scoped — inspect via /perms inside the workbench"
    )

    return lines


def _empty_classifier_section() -> dict[str, Any]:
    return {
        "workspace_root": None,
        "allowlist_path": None,
        "allowlist_count": 0,
        "audit_log_path": None,
        "audit_log_exists": False,
        "audit_log_size_bytes": 0,
        "last_entry_ts": None,
    }


def _classifier_allowlist_count(root: Path) -> int:
    """Count persisted allow-patterns without importing the persistence
    module at top level (it pulls in logging config we don't want to
    reach for in the JSON path).

    We intentionally call through to the persistence helper so the
    count matches what the classifier actually sees at session start.
    """
    try:
        from cli.permissions.classifier_persistence import load_persisted_patterns

        return len(load_persisted_patterns(root))
    except Exception:  # pragma: no cover - defensive
        return 0


def _classifier_audit_metadata(root: Path) -> dict[str, Any]:
    """Return audit-log path/size/last-ts WITHOUT reading the whole file.

    We do tail up to 100 lines to find the most recent timestamp so the
    doctor display reflects reality; 100 lines is bounded by the log
    layout (one short JSON object per line) and the caller accepts
    O(reading) cost in exchange for freshness.
    """
    audit_path = root / ".agentlab" / "classifier_audit.jsonl"
    result: dict[str, Any] = {
        "path": str(audit_path),
        "exists": False,
        "size": 0,
        "last_ts": None,
    }
    if not audit_path.exists():
        return result
    try:
        result["size"] = audit_path.stat().st_size
    except OSError:
        return result
    result["exists"] = True

    try:
        from cli.permissions.audit_log import ClassifierAuditLog

        log = ClassifierAuditLog(audit_path)
        last_ts: str | None = None
        for entry in log.iter_recent(limit=100):
            # iter_recent yields in file order; the last one wins.
            ts = entry.get("ts")
            if isinstance(ts, str):
                last_ts = ts
        result["last_ts"] = last_ts
    except Exception:  # pragma: no cover - defensive
        pass
    return result


# ---------------------------------------------------------------------------
# MCP transports section (P3.T4)
# ---------------------------------------------------------------------------


def mcp_transports_section(root: str | Path | None) -> dict[str, Any]:
    """Build the MCP-transport diagnostic block.

    Parses ``<root>/.mcp.json`` and, for each server, labels its
    configured transport. Since T9 hasn't landed yet the config is
    loosely typed: we accept both ``type`` and ``transport`` keys, fall
    back to "stdio (legacy)" when only ``command``/``args`` are
    present, and never attempt a live connectivity probe (probes can
    hang the doctor render).
    """
    if root is None:
        return {"configured": False, "config_path": None, "servers": []}

    root_path = Path(root)
    config_path = root_path / ".mcp.json"
    if not config_path.exists():
        return {"configured": False, "config_path": str(config_path), "servers": []}

    try:
        import json as _json

        payload = _json.loads(config_path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        return {"configured": False, "config_path": str(config_path), "servers": []}

    servers_raw = payload.get("mcpServers") if isinstance(payload, dict) else None
    if not isinstance(servers_raw, dict):
        return {"configured": True, "config_path": str(config_path), "servers": []}

    servers: list[dict[str, Any]] = []
    for name in sorted(servers_raw):
        entry = servers_raw.get(name)
        if not isinstance(entry, dict):
            continue
        servers.append(
            {
                "name": name,
                "transport": _detect_transport_label(entry),
                "command": entry.get("command"),
                "args": list(entry.get("args") or []),
                "url": entry.get("url"),
            }
        )

    return {
        "configured": True,
        "config_path": str(config_path),
        "servers": servers,
    }


def render_mcp_transports_section(root: str | Path | None) -> list[str]:
    """Render the MCP-transport section as plain lines for the doctor.

    Each server gets one main line (``name: transport``) and, when
    relevant, a second indented line with the connection hint (command
    line or URL). We DO NOT probe — connectivity checks can hang on an
    unresponsive remote.
    """
    section = mcp_transports_section(root)
    lines: list[str] = ["", "MCP transports"]

    if not section.get("configured"):
        lines.append("  .mcp.json:         (not configured)")
        return lines

    servers = section.get("servers") or []
    if not servers:
        lines.append("  .mcp.json:         present, no servers configured")
        return lines

    lines.append(f"  .mcp.json:         {section.get('config_path', '(unknown)')}")
    lines.append(f"  Servers:           {len(servers)}")
    for entry in servers:
        name = entry.get("name", "?")
        transport = entry.get("transport", "?")
        lines.append(f"    - {name}: {transport}")
        detail = _render_server_detail(entry)
        if detail:
            lines.append(f"        {detail}")
    return lines


def _detect_transport_label(entry: Mapping[str, Any]) -> str:
    """Return a human-readable transport label.

    Preference order:

    1. Explicit ``transport`` key (T9's expected field).
    2. Explicit ``type`` key (some alternative configs).
    3. ``command`` present → ``stdio (legacy)`` — we know enough to say
       it's stdio but flag it as pre-T9 so the user knows the schema
       will tighten.
    4. ``url`` present but no type → ``http (legacy)`` as a best guess.
    5. Otherwise ``unknown``.
    """
    transport = entry.get("transport")
    if isinstance(transport, str) and transport.strip():
        return transport.strip()
    kind = entry.get("type")
    if isinstance(kind, str) and kind.strip():
        return kind.strip()
    if entry.get("command"):
        return "stdio (legacy)"
    if entry.get("url"):
        return "http (legacy)"
    return "unknown"


def _render_server_detail(entry: Mapping[str, Any]) -> str:
    """Single-line detail: command+args for stdio-ish transports, URL
    for HTTP-ish transports. No output when both are missing."""
    url = entry.get("url")
    if isinstance(url, str) and url:
        return f"url={url}"
    command = entry.get("command")
    if isinstance(command, str) and command:
        args = entry.get("args") or []
        if args:
            return f"command={command} args={' '.join(str(a) for a in args)}"
        return f"command={command}"
    return ""


__all__ = [
    "classifier_section",
    "cost_section",
    "hooks_section",
    "mcp_transports_section",
    "render_classifier_section",
    "render_cost_section",
    "render_hooks_section",
    "render_mcp_transports_section",
    "render_settings_section",
    "settings_section",
]
