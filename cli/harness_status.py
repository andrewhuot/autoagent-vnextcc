"""Harness lifecycle and readiness surfaces for long-running CLI work."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from agent.config.runtime import RuntimeConfig
from cli.workspace import AgentLabWorkspace
from optimizer.reliability import LoopCheckpoint


@dataclass
class HarnessStatusSnapshot:
    """Structured harness state so every CLI surface reports the same operator truth."""

    health: str
    loop: dict[str, Any]
    checkpoint: dict[str, Any]
    dead_letters: dict[str, Any]
    control: dict[str, Any]
    evidence: dict[str, Any]
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recovery_actions: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    @property
    def loop_label(self) -> str:
        status = str(self.loop.get("status") or "idle")
        next_cycle = self.loop.get("next_cycle")
        completed = self.loop.get("completed_cycles")
        if next_cycle is not None:
            return f"{status} (next cycle {next_cycle}, completed {completed})"
        return status

    @property
    def summary_label(self) -> str:
        parts = [self.health, self.loop_label]
        if self.control.get("paused"):
            parts.append("paused")
        dead_letter_count = int(self.dead_letters.get("count") or 0)
        if dead_letter_count:
            parts.append(f"{dead_letter_count} dead letter(s)")
        return "; ".join(parts)

    @property
    def recovery_label(self) -> str:
        return str(self.recovery_actions[0]) if self.recovery_actions else "none"

    @property
    def evidence_label(self) -> str:
        checkpoint = self.evidence.get("checkpoint_path") or "n/a"
        dead_letters = self.evidence.get("dead_letter_db") or "n/a"
        return f"checkpoint={checkpoint} dead_letters={dead_letters}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "health": self.health,
            "loop": self.loop,
            "checkpoint": self.checkpoint,
            "dead_letters": self.dead_letters,
            "control": self.control,
            "evidence": self.evidence,
            "issues": self.issues,
            "warnings": self.warnings,
            "recovery_actions": self.recovery_actions,
            "next_actions": self.next_actions,
        }


def collect_harness_status(
    workspace: AgentLabWorkspace,
    *,
    runtime: RuntimeConfig,
) -> HarnessStatusSnapshot:
    """Collect read-only harness state for steering, recovery, and readiness checks."""
    root = workspace.root
    checkpoint_path = _resolve_workspace_path(root, runtime.loop.checkpoint_path)
    dead_letter_path = _resolve_workspace_path(root, runtime.loop.dead_letter_db)
    structured_log_path = _resolve_workspace_path(root, runtime.loop.structured_log_path)
    control_path = root / ".agentlab" / "human_control.json"
    trace_path = workspace.trace_db

    issues: list[str] = []
    warnings: list[str] = []

    checkpoint, checkpoint_snapshot = _read_checkpoint(checkpoint_path, issues=issues, warnings=warnings)
    dead_letters = _read_dead_letters(dead_letter_path, issues=issues)
    control = _read_control_state(control_path, issues=issues)

    loop_status = _derive_loop_status(
        checkpoint_snapshot,
        watchdog_timeout_seconds=runtime.loop.watchdog_timeout_seconds,
        now=time.time(),
    )
    health = _derive_health(
        issues=issues,
        paused=bool(control.get("paused")),
        dead_letter_count=int(dead_letters.get("count") or 0),
        loop_status=loop_status,
    )
    recovery_actions = _derive_recovery_actions(
        paused=bool(control.get("paused")),
        dead_letter_count=int(dead_letters.get("count") or 0),
        loop_status=loop_status,
    )
    next_actions = _derive_next_actions(recovery_actions)

    loop = {
        "status": loop_status,
        "last_status": checkpoint_snapshot.get("last_status"),
        "next_cycle": checkpoint_snapshot.get("next_cycle"),
        "completed_cycles": checkpoint_snapshot.get("completed_cycles"),
        "plateau_count": checkpoint_snapshot.get("plateau_count"),
        "last_cycle_started_at": checkpoint_snapshot.get("last_cycle_started_at"),
        "last_cycle_finished_at": checkpoint_snapshot.get("last_cycle_finished_at"),
        "last_cycle_finished_at_label": _format_epoch(checkpoint_snapshot.get("last_cycle_finished_at")),
    }

    evidence = {
        "checkpoint_path": str(checkpoint_path),
        "dead_letter_db": str(dead_letter_path),
        "control_path": str(control_path),
        "structured_log_path": str(structured_log_path),
        "trace_db": str(trace_path),
        "checkpoint_exists": checkpoint_path.exists(),
        "dead_letter_db_exists": dead_letter_path.exists(),
        "control_exists": control_path.exists(),
        "structured_log_exists": structured_log_path.exists(),
        "trace_db_exists": trace_path.exists(),
    }

    checkpoint_payload = {
        "path": str(checkpoint_path),
        "exists": checkpoint_path.exists(),
        "backup_path": str(checkpoint_path.with_suffix(checkpoint_path.suffix + ".bak")),
        "readable": checkpoint is not None or not checkpoint_path.exists(),
        "source": checkpoint_snapshot.get("source"),
        "data": checkpoint_snapshot,
    }

    return HarnessStatusSnapshot(
        health=health,
        loop=loop,
        checkpoint=checkpoint_payload,
        dead_letters=dead_letters,
        control=control,
        evidence=evidence,
        issues=issues,
        warnings=warnings,
        recovery_actions=recovery_actions,
        next_actions=next_actions,
    )


def render_harness_status(snapshot: HarnessStatusSnapshot) -> None:
    """Render harness state as operator guidance rather than raw files."""
    click.echo(click.style("\nHarness Status", bold=True))
    click.echo("--------------")
    click.echo(f"  Health:     {snapshot.health}")
    click.echo(f"  Loop:       {snapshot.loop_label}")
    click.echo(f"  Checkpoint: {snapshot.checkpoint['path']}")
    click.echo(f"  Dead letters: {snapshot.dead_letters['count']} pending")
    click.echo(f"  Controls:   {snapshot.control['status_label']}")
    click.echo(f"  Evidence:   {snapshot.evidence_label}")

    if snapshot.issues:
        click.echo("\n  Issues:")
        for issue in snapshot.issues:
            click.echo(f"    - {issue}")

    if snapshot.warnings:
        click.echo("\n  Warnings:")
        for warning in snapshot.warnings:
            click.echo(f"    - {warning}")

    click.echo("\n  Recovery:")
    printed_recovery = False
    if snapshot.loop.get("status") == "recoverable":
        click.echo("    Resume:     agentlab loop --resume")
        printed_recovery = True
    if snapshot.loop.get("status") == "running_or_recoverable":
        click.echo("    Inspect:    agentlab harness status --json")
        printed_recovery = True
    if snapshot.control.get("paused"):
        click.echo("    Unpause:    agentlab loop resume")
        printed_recovery = True
    should_print_dead_letter_inspect = (
        int(snapshot.dead_letters.get("count") or 0) > 0
        and snapshot.loop.get("status") != "running_or_recoverable"
    )
    if should_print_dead_letter_inspect:
        click.echo("    Inspect:    agentlab harness status --json")
        printed_recovery = True
    if not printed_recovery:
        click.echo("    None needed")

    next_step = snapshot.next_actions[0] if snapshot.next_actions else "agentlab optimize --continuous"
    click.echo(click.style(f"\n  Next step:  {next_step}", fg="green"))


def _resolve_workspace_path(root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return root / path


def _read_checkpoint(
    checkpoint_path: Path,
    *,
    issues: list[str],
    warnings: list[str],
) -> tuple[LoopCheckpoint | None, dict[str, Any]]:
    backup_path = checkpoint_path.with_suffix(checkpoint_path.suffix + ".bak")
    primary_error: str | None = None
    for source, candidate in (("primary", checkpoint_path), ("backup", backup_path)):
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            checkpoint = LoopCheckpoint(**payload)
            data = {
                "source": source,
                "next_cycle": checkpoint.next_cycle,
                "completed_cycles": checkpoint.completed_cycles,
                "plateau_count": checkpoint.plateau_count,
                "last_status": checkpoint.last_status,
                "last_cycle_started_at": checkpoint.last_cycle_started_at,
                "last_cycle_finished_at": checkpoint.last_cycle_finished_at,
                "metadata": checkpoint.metadata,
            }
            if primary_error is not None:
                warnings.append(f"Primary checkpoint was unreadable; recovered from backup: {primary_error}")
            return checkpoint, data
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            if source == "primary":
                primary_error = str(exc)
            else:
                issues.append(f"Loop checkpoint is unreadable: {exc}")
    if primary_error is not None:
        issues.append(f"Loop checkpoint is unreadable: {primary_error}")
    return None, {}


def _read_dead_letters(dead_letter_path: Path, *, issues: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": str(dead_letter_path),
        "exists": dead_letter_path.exists(),
        "readable": True,
        "count": 0,
        "latest": None,
    }
    if not dead_letter_path.exists():
        return payload
    try:
        with sqlite3.connect(str(dead_letter_path)) as conn:
            row = conn.execute("SELECT COUNT(*) FROM dead_letters").fetchone()
            payload["count"] = int(row[0] if row else 0)
            latest = conn.execute(
                """
                SELECT id, created_at, kind, error
                FROM dead_letters
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        if latest is not None:
            payload["latest"] = {
                "id": latest[0],
                "created_at": latest[1],
                "kind": latest[2],
                "error": latest[3],
            }
    except sqlite3.DatabaseError as exc:
        payload["readable"] = False
        issues.append(f"Dead-letter DB is unreadable: {exc}")
    return payload


def _read_control_state(control_path: Path, *, issues: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": str(control_path),
        "exists": control_path.exists(),
        "readable": True,
        "paused": False,
        "immutable_surfaces": [],
        "rejected_experiments_count": 0,
        "last_injected_mutation": None,
        "updated_at": None,
        "status_label": "active",
    }
    if not control_path.exists():
        return payload
    try:
        raw = json.loads(control_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        payload["readable"] = False
        issues.append(f"Human-control state is unreadable: {exc}")
        return payload

    immutable_surfaces = list(raw.get("immutable_surfaces", []))
    payload.update(
        {
            "paused": bool(raw.get("paused", False)),
            "immutable_surfaces": immutable_surfaces,
            "rejected_experiments_count": len(list(raw.get("rejected_experiments", []))),
            "last_injected_mutation": raw.get("last_injected_mutation"),
            "updated_at": raw.get("updated_at"),
        }
    )
    label = "paused" if payload["paused"] else "active"
    if immutable_surfaces:
        label = f"{label}, {len(immutable_surfaces)} pinned surface(s)"
    payload["status_label"] = label
    return payload


def _derive_loop_status(
    checkpoint_snapshot: dict[str, Any],
    *,
    watchdog_timeout_seconds: int,
    now: float,
) -> str:
    last_status = str(checkpoint_snapshot.get("last_status") or "").strip().lower()
    if not checkpoint_snapshot:
        return "idle"
    if last_status == "running":
        last_activity = checkpoint_snapshot.get("last_cycle_finished_at") or checkpoint_snapshot.get(
            "last_cycle_started_at"
        )
        if isinstance(last_activity, (int, float)) and now - float(last_activity) > watchdog_timeout_seconds:
            return "recoverable"
        return "running_or_recoverable"
    if last_status in {"stopped", "stopped_plateau"}:
        return "recoverable"
    if last_status == "completed":
        return "completed"
    return last_status or "unknown"


def _derive_health(
    *,
    issues: list[str],
    paused: bool,
    dead_letter_count: int,
    loop_status: str,
) -> str:
    if issues:
        return "blocked"
    if paused or dead_letter_count > 0 or loop_status in {"recoverable", "running_or_recoverable"}:
        return "attention"
    return "ready"


def _derive_recovery_actions(*, paused: bool, dead_letter_count: int, loop_status: str) -> list[str]:
    actions: list[str] = []
    if paused:
        actions.append("agentlab loop resume")
    if loop_status == "recoverable":
        actions.append("agentlab loop --resume")
    if loop_status == "running_or_recoverable":
        actions.append("agentlab harness status --json")
    if dead_letter_count > 0:
        actions.append("agentlab harness status --json")
    return list(dict.fromkeys(actions))


def _derive_next_actions(recovery_actions: list[str]) -> list[str]:
    if recovery_actions:
        return list(recovery_actions)
    return ["agentlab optimize --continuous"]


def _format_epoch(value: object) -> str | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
