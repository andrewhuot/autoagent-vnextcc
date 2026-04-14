"""Agent-config checkpointing for the Workbench.

Claude Code snapshots files before edits so the operator can rewind with
``Esc+Esc``. For agent-building the equivalent artifact is the agent
configuration — persisted as ``configs/v{NNN}.yaml`` + ``manifest.json``.

:class:`CheckpointManager` wraps :class:`deployer.versioning.ConfigVersionManager`
and adds a ``reason`` annotation so operators can distinguish manual
snapshots (``/checkpoint <note>``), pre-execution auto-snapshots
(``reason="pre_execution:{run_id}"``), and optimizer-produced candidates.

Semantics:

- ``snapshot(reason)`` — copies the currently active config into a new
  version with status ``"checkpoint"`` and ``_reason`` recorded in its
  ``scores`` dict. Does nothing (returns ``None``) when no active config
  exists; the Workbench should never block on a missing config.
- ``rewind(version)`` — promotes ``version`` back to active and marks any
  intervening ``candidate``/``checkpoint`` entries as ``"rolled_back"`` so
  downstream callers know the history diverged. Raises ``ValueError`` for
  unknown versions so the ``/rewind`` slash can surface a friendly error.
- ``list_checkpoints()`` — returns the annotated checkpoint entries only,
  newest first, so ``/rewind`` completion and ``/tasks`` can render them
  without walking the full version list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deployer.versioning import ConfigVersionManager


CHECKPOINT_STATUS = "checkpoint"
_REASON_KEY = "_reason"


@dataclass(frozen=True)
class CheckpointRecord:
    """One persisted snapshot entry."""

    version: int
    filename: str
    reason: str
    timestamp: float
    status: str


class CheckpointManager:
    """Thin wrapper that records and restores agent-config snapshots."""

    def __init__(
        self,
        *,
        configs_dir: str | Path = "configs",
        versions: ConfigVersionManager | None = None,
    ) -> None:
        self._versions = versions or ConfigVersionManager(configs_dir=str(configs_dir))

    def snapshot(self, reason: str) -> CheckpointRecord | None:
        """Persist the current active config as a checkpoint.

        ``None`` when no active config exists — the caller should treat it
        as a best-effort operation so the REPL never aborts mid-turn.
        """
        active = self._versions.get_active_config()
        if active is None:
            return None
        scores = {_REASON_KEY: reason}
        cv = self._versions.save_version(
            config=active,
            scores=scores,
            status=CHECKPOINT_STATUS,
        )
        return CheckpointRecord(
            version=cv.version,
            filename=cv.filename,
            reason=reason,
            timestamp=cv.timestamp,
            status=cv.status,
        )

    def rewind(self, version: int) -> CheckpointRecord:
        """Promote a prior version back to active and retire newer entries."""
        self._versions.reload()
        target = self._find(version)
        if target is None:
            raise ValueError(f"Unknown checkpoint version: {version}")
        self._versions.promote(version)
        # Mark every version that came after the rewind target as rolled_back
        # so history readers can tell the timeline diverged. This intentionally
        # overrides whatever status ``promote`` left on the previously-active
        # version — rewinding IS a rollback of forward state.
        for entry in self._versions.manifest["versions"]:
            if entry["version"] > version and entry.get("status") != "rolled_back":
                entry["status"] = "rolled_back"
        self._versions._save_manifest()  # internal API — thin wrapper
        self._versions.reload()
        refreshed = self._find(version) or target
        return _record_from_entry(refreshed)

    def list_checkpoints(self) -> list[CheckpointRecord]:
        """Return checkpoint entries newest-first."""
        self._versions.reload()
        records = [
            _record_from_entry(entry)
            for entry in self._versions.manifest["versions"]
            if entry.get("status") == CHECKPOINT_STATUS
        ]
        records.sort(key=lambda item: item.timestamp, reverse=True)
        return records

    def active_version(self) -> int | None:
        """Return the current active version number, if any."""
        self._versions.reload()
        return self._versions.manifest.get("active_version")

    def _find(self, version: int) -> dict[str, Any] | None:
        for entry in self._versions.manifest["versions"]:
            if entry["version"] == version:
                return entry
        return None


def _record_from_entry(entry: dict[str, Any]) -> CheckpointRecord:
    """Convert a manifest entry into a typed :class:`CheckpointRecord`."""
    scores = entry.get("scores") or {}
    reason = str(scores.get(_REASON_KEY) or "") if isinstance(scores, dict) else ""
    return CheckpointRecord(
        version=int(entry["version"]),
        filename=str(entry["filename"]),
        reason=reason,
        timestamp=float(entry.get("timestamp") or 0.0),
        status=str(entry.get("status") or "unknown"),
    )


__all__ = [
    "CHECKPOINT_STATUS",
    "CheckpointManager",
    "CheckpointRecord",
]
