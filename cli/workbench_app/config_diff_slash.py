"""Slash commands for inspecting and promoting candidate agent configs.

``/build`` writes candidate versions via
:func:`cli.workbench_app.coordinator_slash._apply_build_synthesis` using
:meth:`deployer.versioning.ConfigVersionManager.save_version` with
``status="candidate"``. Operators need a way to review those candidates and
promote/reject them without editing ``configs/manifest.json`` by hand.

Commands:

- ``/diff [<version>]`` — show a unified diff of the active config against the
  target version (defaulting to the newest candidate).
- ``/accept <version>`` — promote the target version to active
  (``ConfigVersionManager.promote``).
- ``/reject <version>`` — mark the target version ``rolled_back``
  (``ConfigVersionManager.rollback``) without touching the current active.

Slash context ``meta`` keys honoured (mirroring ``checkpoint_slash``):

- ``version_manager`` — caller-supplied :class:`ConfigVersionManager`.
- ``configs_dir`` — override directory when no manager is supplied.
"""

from __future__ import annotations

import difflib
import shlex
from pathlib import Path
from typing import Any

import yaml

from cli.workbench_app import theme
from cli.workbench_app.checkpoint import CheckpointManager
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.slash import SlashContext
from deployer.versioning import ConfigVersionManager


def build_diff_command() -> LocalCommand:
    return LocalCommand(
        name="diff",
        description="Show unified diff of active config vs a candidate version",
        handler=_handle_diff,
        source="builtin",
        argument_hint="[version]",
        when_to_use="Use after /build to review the proposed candidate config.",
        sensitive=False,
    )


def build_accept_command() -> LocalCommand:
    return LocalCommand(
        name="accept",
        description="Promote a candidate config version to active",
        handler=_handle_accept,
        source="builtin",
        argument_hint="<version>",
        when_to_use="Use after /diff confirms the candidate is good to ship.",
        sensitive=True,
    )


def build_reject_command() -> LocalCommand:
    return LocalCommand(
        name="reject",
        description="Mark a candidate config version rolled back",
        handler=_handle_reject,
        source="builtin",
        argument_hint="<version>",
        when_to_use="Use to discard an unwanted /build candidate.",
        sensitive=True,
    )


# ---------------------------------------------------------------------------
# Handlers.
# ---------------------------------------------------------------------------


def _handle_diff(ctx: SlashContext, *args: str) -> OnDoneResult:
    manager = _resolve_version_manager(ctx)
    if manager is None:
        return on_done(
            "  No configs/ directory found. Run from a workspace with a saved config.",
            display="system",
        )

    raw = " ".join(args).strip()
    if raw:
        try:
            target_version = _parse_version(raw)
        except ValueError as exc:
            return on_done(f"  {exc}", display="system")
    else:
        target_version = _latest_candidate_version(manager)
        if target_version is None:
            return on_done(
                "  No candidate version found. Run /build to produce one.",
                display="system",
            )

    target_entry = _find_entry(manager, target_version)
    if target_entry is None:
        return on_done(
            f"  Unknown version: v{target_version:03d}.",
            display="system",
        )

    active_version = manager.manifest.get("active_version")
    if active_version is None:
        return on_done(
            "  No active config to diff against.",
            display="system",
        )

    try:
        active_config = manager.get_active_config() or {}
        target_config = _load_config(manager, target_entry) or {}
    except OSError as exc:
        return on_done(f"  Failed to load config: {exc}", display="system")

    active_text = yaml.safe_dump(active_config, sort_keys=False).splitlines()
    target_text = yaml.safe_dump(target_config, sort_keys=False).splitlines()

    diff_lines = list(
        difflib.unified_diff(
            active_text,
            target_text,
            fromfile=f"v{active_version:03d}",
            tofile=f"v{target_version:03d}",
            lineterm="",
        )
    )
    if not diff_lines:
        return on_done(
            f"  No differences between v{active_version:03d} and v{target_version:03d}.",
            display="system",
        )

    header = (
        f"  Diff v{active_version:03d} (active) → v{target_version:03d} "
        f"({target_entry.get('status', 'unknown')}):"
    )
    body = [_style_diff_line(line) for line in diff_lines]
    return on_done("\n".join([header, *body]), display="user")


def _handle_accept(ctx: SlashContext, *args: str) -> OnDoneResult:
    manager = _resolve_version_manager(ctx)
    if manager is None:
        return on_done(
            "  No configs/ directory found. Cannot accept.",
            display="system",
        )
    raw = " ".join(args).strip()
    if not raw:
        return on_done(
            "  Usage: /accept <version>. Use /diff to inspect the candidate first.",
            display="system",
        )
    try:
        version = _parse_version(raw)
    except ValueError as exc:
        return on_done(f"  {exc}", display="system")
    try:
        manager.promote(version)
    except ValueError as exc:
        return on_done(f"  {exc}", display="system")
    return on_done(
        f"  Promoted v{version:03d} to active. Previous active was retired.",
        display="user",
    )


def _handle_reject(ctx: SlashContext, *args: str) -> OnDoneResult:
    manager = _resolve_version_manager(ctx)
    if manager is None:
        return on_done(
            "  No configs/ directory found. Cannot reject.",
            display="system",
        )
    raw = " ".join(args).strip()
    if not raw:
        return on_done(
            "  Usage: /reject <version>.",
            display="system",
        )
    try:
        version = _parse_version(raw)
    except ValueError as exc:
        return on_done(f"  {exc}", display="system")
    try:
        manager.rollback(version)
    except ValueError as exc:
        return on_done(f"  {exc}", display="system")
    return on_done(
        f"  Marked v{version:03d} rolled_back. Active version unchanged.",
        display="user",
    )


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _resolve_version_manager(ctx: SlashContext) -> ConfigVersionManager | None:
    """Return a :class:`ConfigVersionManager` for the active workspace.

    Mirrors :func:`coordinator_slash._resolve_version_manager` so both command
    families share context-plumbing conventions without a cross-module import.
    """
    cached = ctx.meta.get("version_manager")
    if isinstance(cached, ConfigVersionManager):
        return cached
    checkpoint = ctx.meta.get("checkpoint_manager")
    if isinstance(checkpoint, CheckpointManager):
        versions = getattr(checkpoint, "_versions", None)
        if isinstance(versions, ConfigVersionManager):
            ctx.meta["version_manager"] = versions
            return versions
    configs_dir = _resolve_configs_dir(ctx)
    if configs_dir is None:
        return None
    versions = ConfigVersionManager(configs_dir=str(configs_dir))
    ctx.meta["version_manager"] = versions
    return versions


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
    tokens = shlex.split(raw)
    if not tokens:
        raise ValueError(f"Not a valid version: {raw!r}")
    token = tokens[0].lstrip("v").lstrip("V")
    try:
        return int(token)
    except ValueError as exc:
        raise ValueError(f"Not a valid version: {raw!r}") from exc


def _find_entry(manager: ConfigVersionManager, version: int) -> dict[str, Any] | None:
    for entry in manager.manifest.get("versions", []):
        if entry.get("version") == version:
            return entry
    return None


def _latest_candidate_version(manager: ConfigVersionManager) -> int | None:
    """Return the newest manifest entry with a candidate-like status.

    ``save_version`` persists build candidates with ``status="candidate"``; we
    also accept ``"canary"`` because older workflows used that name and the
    manager still exposes ``canary_version``.
    """
    canary = manager.manifest.get("canary_version")
    if isinstance(canary, int):
        return canary
    candidates = [
        entry
        for entry in manager.manifest.get("versions", [])
        if entry.get("status") in {"candidate", "canary"}
    ]
    if not candidates:
        return None
    return max(entry["version"] for entry in candidates)


def _load_config(
    manager: ConfigVersionManager, entry: dict[str, Any]
) -> dict[str, Any] | None:
    filename = entry.get("filename")
    if not filename:
        return None
    filepath = manager.configs_dir / filename
    with filepath.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _style_diff_line(line: str) -> str:
    """Colourise unified-diff output for the REPL."""
    if line.startswith("+++") or line.startswith("---"):
        return theme.meta(line)
    if line.startswith("@@"):
        return theme.meta(line)
    if line.startswith("+"):
        return theme.user(line, bold=False)
    if line.startswith("-"):
        return theme.warning(line)
    return line


__all__ = [
    "build_accept_command",
    "build_diff_command",
    "build_reject_command",
]
