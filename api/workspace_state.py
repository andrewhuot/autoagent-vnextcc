"""Workspace-state detection for API startup and health surfaces."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from cli.workspace import AgentLabWorkspace, discover_workspace


WORKSPACE_ENV_VAR = "AGENTLAB_WORKSPACE"
WORKSPACE_PLACEHOLDER = "/path/to/agentlab-workspace"


@dataclass(frozen=True)
class WorkspaceState:
    """Resolved runtime workspace state for server startup and recovery UI."""

    valid: bool
    current_path: str
    workspace_root: str | None
    workspace_label: str | None
    active_config_path: str | None
    active_config_version: int | None
    source: str
    message: str
    recovery_commands: list[str]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation for API responses."""
        return asdict(self)


def _recovery_commands_for_missing_workspace() -> list[str]:
    """Return concrete commands that help users recover from a bad startup path."""
    return [
        f"cd {WORKSPACE_PLACEHOLDER} && agentlab server",
        f"agentlab server --workspace {WORKSPACE_PLACEHOLDER}",
        "agentlab init --dir /path/to/new-workspace",
    ]


def _recovery_commands_for_invalid_workspace(workspace_root: Path) -> list[str]:
    """Return recovery commands for a discovered workspace with missing runtime state."""
    root = str(workspace_root)
    return [
        f"cd {root} && agentlab config list",
        f"agentlab server --workspace {root}",
        f"agentlab init --dir {root}",
    ]


def _invalid_state(
    *,
    current_path: Path,
    source: str,
    message: str,
    workspace: AgentLabWorkspace | None = None,
    recovery_commands: list[str] | None = None,
) -> WorkspaceState:
    """Build an invalid state payload without leaking exceptions to callers."""
    workspace_root = str(workspace.root) if workspace is not None else None
    workspace_label = workspace.workspace_label if workspace is not None else None
    return WorkspaceState(
        valid=False,
        current_path=str(current_path),
        workspace_root=workspace_root,
        workspace_label=workspace_label,
        active_config_path=None,
        active_config_version=None,
        source=source,
        message=message,
        recovery_commands=recovery_commands or _recovery_commands_for_missing_workspace(),
    )


def _discover_from_explicit_path(path: Path) -> AgentLabWorkspace | None:
    """Discover a workspace from an explicit server path argument or env var."""
    if not path.exists() or not path.is_dir():
        return None
    return discover_workspace(path)


def resolve_workspace_state(start: Path | None = None) -> WorkspaceState:
    """Resolve current API workspace validity from env override or process CWD.

    The API server has historically used relative store paths, so this resolver
    makes the implicit startup dependency visible before those stores initialize.
    """
    current_path = (start or Path.cwd()).expanduser().resolve()
    explicit_workspace = os.environ.get(WORKSPACE_ENV_VAR)
    source = "env" if explicit_workspace else "cwd"

    if explicit_workspace:
        explicit_path = Path(explicit_workspace).expanduser().resolve()
        workspace = _discover_from_explicit_path(explicit_path)
        if workspace is None:
            return _invalid_state(
                current_path=current_path,
                source=source,
                message=f"Workspace path does not exist or is not an AgentLab workspace: {explicit_path}",
                recovery_commands=[
                    f"agentlab init --dir {explicit_path}",
                    f"agentlab server --workspace {WORKSPACE_PLACEHOLDER}",
                ],
            )
    else:
        workspace = discover_workspace(current_path)
        if workspace is None:
            return _invalid_state(
                current_path=current_path,
                source=source,
                message=(
                    f"No AgentLab workspace found from startup path {current_path}. "
                    "Start the server from a workspace or pass --workspace."
                ),
            )

    try:
        active_config = workspace.resolve_active_config()
    except Exception as exc:  # noqa: BLE001 - file contents are user-controlled.
        return _invalid_state(
            current_path=current_path,
            source=source,
            workspace=workspace,
            message=f"Could not read the active config for workspace {workspace.root}: {exc}",
            recovery_commands=_recovery_commands_for_invalid_workspace(workspace.root),
        )

    if active_config is None:
        return _invalid_state(
            current_path=current_path,
            source=source,
            workspace=workspace,
            message=f"No active config found in AgentLab workspace {workspace.root}.",
            recovery_commands=_recovery_commands_for_invalid_workspace(workspace.root),
        )

    return WorkspaceState(
        valid=True,
        current_path=str(current_path),
        workspace_root=str(workspace.root),
        workspace_label=workspace.workspace_label,
        active_config_path=str(active_config.path.resolve()),
        active_config_version=active_config.version,
        source=source,
        message="AgentLab workspace is ready.",
        recovery_commands=[],
    )
