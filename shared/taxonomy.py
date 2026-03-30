"""Canonical AutoAgent command taxonomy shared across CLI and UI shells."""

from __future__ import annotations

from dataclasses import dataclass


CommandGroup = str


@dataclass(frozen=True, slots=True)
class CommandGroupSpec:
    """Describe one top-level command group for navigation and help text."""

    label: str
    description: str
    subcommands: tuple[str, ...]

    def __getitem__(self, key: str) -> str | tuple[str, ...]:
        """Allow dict-style reads so Python and TypeScript callers stay aligned."""
        return getattr(self, key)


COMMAND_GROUPS: tuple[CommandGroup, ...] = (
    "home",
    "build",
    "import",
    "eval",
    "optimize",
    "review",
    "deploy",
    "observe",
    "govern",
    "integrations",
    "settings",
)

COMMAND_TAXONOMY: dict[CommandGroup, CommandGroupSpec] = {
    "home": CommandGroupSpec(
        label="Home",
        description="Workspace status and setup",
        subcommands=("dashboard", "setup"),
    ),
    "build": CommandGroupSpec(
        label="Build",
        description="Create and refine agent configurations",
        subcommands=("prompt", "transcript", "builder_chat", "saved_artifacts"),
    ),
    "import": CommandGroupSpec(
        label="Import",
        description="Import external agents and artifacts",
        subcommands=("cx", "adk", "config", "transcript"),
    ),
    "eval": CommandGroupSpec(
        label="Eval",
        description="Run and inspect evaluation suites",
        subcommands=("run", "results", "show", "list", "generate", "curriculum"),
    ),
    "optimize": CommandGroupSpec(
        label="Optimize",
        description="Improve agent performance through experimentation",
        subcommands=("run", "live", "experiments", "review", "opportunities"),
    ),
    "review": CommandGroupSpec(
        label="Review",
        description="Review and apply proposed changes",
        subcommands=("list", "show", "apply", "reject", "export"),
    ),
    "deploy": CommandGroupSpec(
        label="Deploy",
        description="Promote configurations to production",
        subcommands=("canary", "immediate", "status", "rollback", "release"),
    ),
    "observe": CommandGroupSpec(
        label="Observe",
        description="Monitor agent health and behavior",
        subcommands=("dashboard", "traces", "conversations", "events", "blame", "context", "loop"),
    ),
    "govern": CommandGroupSpec(
        label="Govern",
        description="Manage judges, configs, memory, runbooks, and policies",
        subcommands=(
            "judges",
            "configs",
            "memory",
            "runbooks",
            "scorers",
            "skills",
            "registry",
            "rewards",
            "preferences",
            "policies",
        ),
    ),
    "integrations": CommandGroupSpec(
        label="Integrations",
        description="External platform connections",
        subcommands=("cx-import", "cx-deploy", "adk-import", "adk-deploy", "agent-skills", "mcp"),
    ),
    "settings": CommandGroupSpec(
        label="Settings",
        description="Workspace configuration and diagnostics",
        subcommands=("setup", "mode", "doctor", "notifications"),
    ),
}
