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
            # Tool-call surface: plan mode forbids anything that mutates the
            # workspace. Read-only tools are allow-listed individually below so
            # the pattern order (``deny`` before ``allow``) still works.
            "tool:FileEdit:*",
            "tool:FileWrite:*",
            "tool:Bash:*",
            "tool:ConfigEdit:*",
        ],
        "allow": [
            "tool:FileRead:*",
            "tool:Glob",
            "tool:Grep",
            "tool:ConfigRead:*",
            "*",
        ],
    },
    "default": {
        "ask": [
            "config.write",
            "deploy.*",
            "review.apply",
            "mcp.*",
            "model.write",
            "full_auto.run",
            # Any tool that mutates the workspace prompts in default mode.
            # Read-only tools fall through to the ``allow`` rule below so they
            # never interrupt the user.
            "tool:FileEdit:*",
            "tool:FileWrite:*",
            "tool:Bash:*",
            "tool:ConfigEdit:*",
        ],
        "allow": ["*"],
    },
    "acceptEdits": {
        "allow": [
            "config.write",
            "memory.write",
            "model.write",
            "tool:FileEdit:*",
            "tool:FileWrite:*",
            "tool:ConfigEdit:*",
        ],
        "ask": ["deploy.*", "review.apply", "mcp.*", "full_auto.run", "tool:Bash:*"],
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
        # In-memory session overrides populated by the permission dialog when
        # the user selects "Approve always (this session)". They take
        # precedence over both explicit rules and mode defaults but are not
        # persisted to disk — the user's reload clears them.
        self._session_allow: list[str] = []
        self._session_deny: list[str] = []
        # Patterns added by ``ask_for_session`` (e.g. AgentLab's permission
        # preset) — they force a prompt even when ``explicit_rules`` or the
        # mode defaults would otherwise ``allow``. They sit BELOW
        # ``explicit_rules`` so a user who deliberately allowlists a tool in
        # ``settings.json`` still wins.
        self._session_ask: list[str] = []
        # Optional plan-mode workflow injected by the workbench loop. When
        # present, drafting plans restrict the tool surface ahead of the
        # normal mode lookup — see ``decision_for_tool`` below.
        self._plan_workflow: Any | None = None

    def bind_plan_workflow(self, workflow: Any | None) -> None:
        """Attach (or clear) a :class:`cli.workbench_app.plan_mode.PlanWorkflow`.

        Kept as a plain setter rather than a constructor argument because the
        workflow depends on the workspace root that ``__post_init__`` has
        already resolved — the REPL builds the manager first, then the
        workflow, then binds them."""
        self._plan_workflow = workflow

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
        """Return `allow`, `ask`, or `deny` for the requested action.

        Precedence (highest to lowest):

        1. ``_session_deny`` — in-memory hard-block from the permission
           dialog.
        2. ``_session_allow`` — in-memory "always-yes" from the dialog.
        3. Explicit ``deny``/``ask``/``allow`` rules from
           ``settings.json::permissions.rules``.
        4. ``_session_ask`` — in-memory "force-prompt" patterns added via
           :meth:`ask_for_session` (AgentLab's permission preset). Sits
           below explicit rules so a user who deliberately allowlists a
           tool in their workspace settings keeps that decision.
        5. Mode defaults from :data:`_MODE_RULES`.

        Rationale for the session-allow / session-deny layers at top: a
        user who chose "Approve always (this session)" expects the decision
        to stick even if the mode rules would otherwise ``ask`` — and a
        session-level ``deny`` should hard-block even when an explicit
        allow exists. ``_session_ask`` is one tier weaker: it upgrades a
        mode-default ``allow`` to ``ask`` but never overrides an explicit
        user choice in ``settings.json``.
        """
        if self._matches(action, self._session_deny):
            return "deny"
        if self._matches(action, self._session_allow):
            return "allow"

        for decision in ("deny", "ask", "allow"):
            if self._matches(action, self.explicit_rules.get(decision, [])):
                return decision

        if self._matches(action, self._session_ask):
            return "ask"

        defaults = _MODE_RULES.get(self.mode, _MODE_RULES[DEFAULT_PERMISSION_MODE])
        for decision in ("deny", "ask", "allow"):
            if self._matches(action, defaults.get(decision, [])):
                return decision
        return "allow"

    def decision_for_tool(self, tool: Any, tool_input: Any) -> str:
        """Resolve the decision for a tool invocation.

        Precedence:

        1. A bound :class:`PlanWorkflow` in ``drafting`` state restricts the
           tool surface to :data:`~cli.workbench_app.plan_mode.DRAFTING_ALLOWED_TOOLS`.
           Read-only tools still pass through to the normal check.
        2. Read-only tools (``tool.read_only is True``) short-circuit to
           ``allow`` — they never mutate the workspace, so prompting would
           only train the user to auto-approve every prompt.
        3. Everything else flows through :meth:`decision_for` with the
           action string produced by ``tool.permission_action(tool_input)``.
        """
        read_only = bool(getattr(tool, "read_only", False))
        action = tool.permission_action(tool_input) if not read_only else ""

        # Skill overlays (see cli.user_skills.allowlist) take precedence so
        # an in-flight skill never executes a tool outside its declared
        # allow-list. Read-only tools on the overlay are still subject to
        # the overlay — the skill may be intentionally narrowing reads too.
        from cli.user_skills.allowlist import skill_overlay_allows

        overlay_verdict = skill_overlay_allows(self, tool.name)
        if overlay_verdict is False:
            return "deny"

        base_decision = "allow" if read_only else self.decision_for(action)

        workflow = self._plan_workflow
        if workflow is not None and getattr(workflow, "active_restriction", None):
            # Local import keeps the plan module optional; cli.permissions
            # must still load cleanly if a caller never uses plan mode.
            from cli.workbench_app.plan_mode import decision_for_tool_with_workflow

            return decision_for_tool_with_workflow(
                tool.name,
                read_only,
                workflow,
                base_decision,
            )
        return base_decision

    def allow_for_session(self, pattern: str) -> None:
        """Register an allow pattern for the lifetime of this manager."""
        if pattern and pattern not in self._session_allow:
            self._session_allow.append(pattern)

    def deny_for_session(self, pattern: str) -> None:
        """Register a deny pattern for the lifetime of this manager."""
        if pattern and pattern not in self._session_deny:
            self._session_deny.append(pattern)

    def ask_for_session(self, pattern: str) -> None:
        """Register a force-ask pattern for the lifetime of this manager.

        Used by the AgentLab permission preset (:mod:`cli.workbench_app.permission_preset`)
        to route risky tools through a prompt even when the mode defaults
        would fall through to ``allow``. Sits BELOW
        ``explicit_rules`` in :meth:`decision_for` so a user's
        ``settings.json`` allow/ask/deny choice still wins — and BELOW
        ``_session_allow`` so an explicit dialog "always-yes" is never
        silently downgraded by a programmatic preset."""
        if pattern and pattern not in self._session_ask:
            self._session_ask.append(pattern)

    def persist_allow_rule(self, pattern: str) -> Path:
        """Append an allow rule to ``settings.json`` and reload the cache."""
        rules = self.explicit_rules
        existing = list(rules.get("allow", []))
        if pattern in existing:
            return settings_path(self.root)
        existing.append(pattern)
        path = update_workspace_settings(
            {"permissions": {"rules": {**rules, "allow": existing}}}, root=self.root
        )
        self.settings = load_workspace_settings(self.root)
        return path

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
