"""Slash commands for agent-config checkpoint / rewind.

- ``/checkpoint [reason]`` → snapshots the currently active config version
  into ``configs/v{NNN}.yaml`` with a reason annotation.
- ``/rewind <version>`` → promotes a prior version back to active and
  marks any intervening candidate/checkpoint versions as rolled back.
- ``/checkpoints`` → lists known checkpoints newest-first.

The handlers build a :class:`CheckpointManager` rooted at the active
workspace's ``configs/`` directory. Slash context ``meta`` keys:

- ``checkpoint_manager`` — caller-supplied manager (tests / custom roots).
- ``configs_dir`` — override directory if no manager is supplied.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from cli.workbench_app.checkpoint import CheckpointManager, CheckpointRecord
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.slash import SlashContext


def build_checkpoint_command() -> LocalCommand:
    return LocalCommand(
        name="checkpoint",
        description="Snapshot the active agent config for later rewind",
        handler=_handle_checkpoint,
        source="builtin",
        argument_hint="[reason]",
        when_to_use="Use before a risky change to the agent config.",
        sensitive=False,
    )


def build_rewind_command() -> LocalCommand:
    return LocalCommand(
        name="rewind",
        description="Restore a prior agent-config version as active",
        handler=_handle_rewind,
        source="builtin",
        argument_hint="<version>",
        when_to_use="Use after a workbench turn that produced an unwanted change.",
        sensitive=True,
    )


def build_checkpoints_command() -> LocalCommand:
    return LocalCommand(
        name="checkpoints",
        description="List recorded agent-config checkpoints",
        handler=_handle_list,
        source="builtin",
        aliases=("snapshots",),
    )


def _handle_checkpoint(ctx: SlashContext, *args: str) -> OnDoneResult:
    manager = _resolve_manager(ctx)
    if manager is None:
        return on_done(
            "  No configs/ directory found. Run from a workspace with a saved config.",
            display="system",
        )
    reason = " ".join(args).strip() or "manual"
    record = manager.snapshot(reason=reason)
    if record is None:
        return on_done(
            "  No active config to snapshot — nothing was written.",
            display="system",
        )
    return on_done(
        _format_record("Snapshot saved", record),
        display="user",
    )


def _handle_rewind(ctx: SlashContext, *args: str) -> OnDoneResult:
    manager = _resolve_manager(ctx)
    if manager is None:
        return on_done(
            "  No configs/ directory found. Cannot rewind.",
            display="system",
        )
    raw = " ".join(args).strip()
    if not raw:
        return on_done(
            "  Usage: /rewind <version>. Use /checkpoints to list available snapshots.",
            display="system",
        )
    try:
        version = _parse_version(raw)
    except ValueError as exc:
        return on_done(f"  {exc}", display="system")
    try:
        record = manager.rewind(version)
    except ValueError as exc:
        return on_done(f"  {exc}", display="system")
    return on_done(
        _format_record("Rewound to version", record),
        display="user",
        meta_messages=(
            "Forward versions (if any) were marked rolled_back.",
        ),
    )


def _handle_list(ctx: SlashContext, *_: str) -> OnDoneResult:
    manager = _resolve_manager(ctx)
    if manager is None:
        return on_done(
            "  No configs/ directory found.",
            display="system",
        )
    records = manager.list_checkpoints()
    if not records:
        return on_done(
            "  No checkpoints recorded yet. Run /checkpoint to create one.",
            display="system",
        )
    lines = ["  Checkpoints (newest first):"]
    active = manager.active_version()
    for record in records:
        marker = " (active)" if record.version == active else ""
        reason = record.reason or "—"
        lines.append(f"    v{record.version:03d} {record.filename} · {reason}{marker}")
    return on_done("\n".join(lines), display="user")


def _resolve_manager(ctx: SlashContext) -> CheckpointManager | None:
    """Return a :class:`CheckpointManager` for the active workspace."""
    cached = ctx.meta.get("checkpoint_manager")
    if isinstance(cached, CheckpointManager):
        return cached
    configs_dir = _resolve_configs_dir(ctx)
    if configs_dir is None:
        return None
    manager = CheckpointManager(configs_dir=configs_dir)
    ctx.meta["checkpoint_manager"] = manager
    return manager


def _resolve_configs_dir(ctx: SlashContext) -> Path | None:
    """Find the ``configs/`` directory for the current workspace."""
    override = ctx.meta.get("configs_dir")
    if override:
        path = Path(override)
        return path if path.exists() else None
    workspace = ctx.workspace
    root = getattr(workspace, "root", None) if workspace is not None else None
    candidates: list[Path] = []
    if root is not None:
        candidates.append(Path(root) / "configs")
    candidates.append(Path.cwd() / "configs")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _parse_version(raw: str) -> int:
    """Parse ``v014`` / ``14`` / ``v14`` into an int."""
    token = shlex.split(raw)[0].lstrip("v").lstrip("V")
    try:
        return int(token)
    except ValueError as exc:
        raise ValueError(f"Not a valid version: {raw!r}") from exc


def _format_record(prefix: str, record: CheckpointRecord) -> str:
    return (
        f"  {prefix} v{record.version:03d} ({record.filename})"
        + (f" — {record.reason}" if record.reason else "")
    )


__all__ = [
    "build_checkpoint_command",
    "build_checkpoints_command",
    "build_rewind_command",
]
