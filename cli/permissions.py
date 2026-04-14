"""Workspace settings and permission-mode helpers for risky CLI actions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import click

from cli.errors import click_error
from cli.json_envelope import render_json_envelope


SETTINGS_FILENAME = "settings.json"
PERMISSION_MODES = ("plan", "default", "acceptEdits", "dontAsk", "bypass")
DEFAULT_PERMISSION_MODE = "default"

MODE_DISPLAY: dict[str, tuple[str, str, str]] = {
    "plan": ("⏸", "Plan Mode", "plan"),
    "default": ("", "Default", "default"),
    "acceptEdits": ("⏵⏵", "Accept edits", "accept"),
    "dontAsk": ("⏵⏵", "Don't Ask", "danger"),
    "bypass": ("⏵⏵", "Bypass", "danger"),
}
"""Maps each permission mode to ``(symbol, display_title, color_role)``."""

_MODE_RULES: dict[str, dict[str, list[str]]] = {
    "plan": {
        "deny": [
            "config.write",
            "memory.write",
            "deploy.*",
            "review.apply",
            "mcp.*",
            "full_auto.run",
            "model.write",
        ],
        "allow": ["*"],
    },
    "default": {
        "ask": [
            "config.write",
            "deploy.*",
            "review.apply",
            "mcp.*",
            "model.write",
            "full_auto.run",
        ],
        "allow": ["*"],
    },
    "acceptEdits": {
        "allow": ["config.write", "memory.write", "model.write"],
        "ask": ["deploy.*", "review.apply", "mcp.*", "full_auto.run"],
    },
    "dontAsk": {
        "allow": ["*"],
    },
    "bypass": {
        "allow": ["*"],
    },
}


def settings_path(root: str | Path | None = None) -> Path:
    """Return the workspace settings path."""
    base = Path(root or ".")
    return base / ".agentlab" / SETTINGS_FILENAME


def load_workspace_settings(root: str | Path | None = None) -> dict[str, Any]:
    """Load `.agentlab/settings.json`, defaulting to an empty object."""
    path = settings_path(root)
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def save_workspace_settings(settings: dict[str, Any], root: str | Path | None = None) -> Path:
    """Persist workspace settings."""
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def update_workspace_settings(
    updates: dict[str, Any],
    *,
    root: str | Path | None = None,
) -> Path:
    """Merge top-level settings keys and persist the result."""
    settings = load_workspace_settings(root)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(settings.get(key), dict):
            merged = dict(settings[key])
            merged.update(value)
            settings[key] = merged
        else:
            settings[key] = value
    return save_workspace_settings(settings, root)


@dataclass
class PermissionManager:
    """Resolve and enforce workspace permission rules."""

    root: str | Path | None = None

    def __post_init__(self) -> None:
        self.root = Path(self.root or ".")
        self.settings = load_workspace_settings(self.root)

    @property
    def mode(self) -> str:
        """Return the active permission mode."""
        raw_mode = (
            self.settings.get("permissions", {}).get("mode")
            if isinstance(self.settings.get("permissions"), dict)
            else None
        )
        normalized = str(raw_mode or DEFAULT_PERMISSION_MODE).strip()
        return normalized if normalized in PERMISSION_MODES else DEFAULT_PERMISSION_MODE

    @property
    def explicit_rules(self) -> dict[str, list[str]]:
        """Return explicit allow/ask/deny rules from settings."""
        permissions = self.settings.get("permissions", {})
        rules = permissions.get("rules", {}) if isinstance(permissions, dict) else {}
        if not isinstance(rules, dict):
            return {}
        normalized: dict[str, list[str]] = {}
        for key in ("allow", "ask", "deny"):
            raw_values = rules.get(key, [])
            if isinstance(raw_values, list):
                normalized[key] = [str(value) for value in raw_values]
        return normalized

    def decision_for(self, action: str) -> str:
        """Return `allow`, `ask`, or `deny` for the requested action."""
        for decision in ("deny", "ask", "allow"):
            if self._matches(action, self.explicit_rules.get(decision, [])):
                return decision

        defaults = _MODE_RULES.get(self.mode, _MODE_RULES[DEFAULT_PERMISSION_MODE])
        for decision in ("deny", "ask", "allow"):
            if self._matches(action, defaults.get(decision, [])):
                return decision
        return "allow"

    def require(
        self,
        action: str,
        *,
        prompt: str,
        assume_yes: bool = False,
        default: bool = False,
    ) -> str:
        """Enforce the rule for `action`, prompting when needed."""
        decision = self.decision_for(action)
        if decision == "deny":
            raise click_error(
                f"Permission mode '{self.mode}' blocks action '{action}'. "
                f"Update .agentlab/settings.json if this workspace should allow it."
            )
        if decision == "allow" or assume_yes:
            return "allow"
        if click.confirm(prompt, abort=True, default=default):
            return "ask"
        return "ask"

    @staticmethod
    def _matches(action: str, patterns: list[str]) -> bool:
        return any(fnmatch(action, pattern) for pattern in patterns)


def _require_workspace_root(root: str | Path = ".") -> Path:
    """Return the workspace root path or raise when `.agentlab` is missing."""
    workspace_root = Path(root)
    if not (workspace_root / ".agentlab").exists():
        raise click_error("No AgentLab workspace found.")
    return workspace_root


@click.group("permissions")
def permissions_group() -> None:
    """Inspect or change the workspace permission mode."""


@permissions_group.command("show")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def show_permissions(json_output: bool = False) -> None:
    """Show the active permission mode plus the effective defaults."""
    workspace_root = _require_workspace_root()
    manager = PermissionManager(root=workspace_root)
    data = {
        "mode": manager.mode,
        "path": str(settings_path(workspace_root)),
        "rules": manager.explicit_rules,
        "examples": {
            "config.write": manager.decision_for("config.write"),
            "review.apply": manager.decision_for("review.apply"),
            "deploy.canary": manager.decision_for("deploy.canary"),
            "model.write": manager.decision_for("model.write"),
        },
    }
    if json_output:
        click.echo(render_json_envelope("ok", data, next_command="agentlab permissions set <mode>"))
        return

    click.echo("Workspace permissions")
    click.echo(f"  Mode: {data['mode']}")
    click.echo(f"  Path: {data['path']}")
    click.echo("  Effective decisions:")
    for action, decision in data["examples"].items():
        click.echo(f"    {action:<14} {decision}")
    if data["rules"]:
        click.echo("  Explicit rules:")
        for decision in ("allow", "ask", "deny"):
            values = data["rules"].get(decision, [])
            if values:
                click.echo(f"    {decision}: {', '.join(values)}")


@permissions_group.command("set")
@click.argument("mode", type=click.Choice(PERMISSION_MODES, case_sensitive=False))
def set_permissions(mode: str) -> None:
    """Persist a workspace permission mode such as `acceptEdits` or `dontAsk`."""
    workspace_root = _require_workspace_root()
    normalized_mode = next(
        candidate for candidate in PERMISSION_MODES if candidate.lower() == mode.lower()
    )
    path = update_workspace_settings({"permissions": {"mode": normalized_mode}}, root=workspace_root)
    click.echo(f"Saved permission mode: {normalized_mode}")
    click.echo(f"  Path: {path}")
