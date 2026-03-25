"""Export optimized AutoAgent config back to CX Agent Studio."""
from __future__ import annotations

import json
from pathlib import Path

from .client import CxClient
from .mapper import CxMapper
from .types import CxAgentRef, CxAgentSnapshot, ExportResult
from .errors import CxExportError


class CxExporter:
    """Export optimized AutoAgent config back to CX Agent Studio."""

    def __init__(self, client: CxClient, mapper: CxMapper | None = None):
        self._client = client
        self._mapper = mapper or CxMapper()

    def export_agent(
        self,
        config: dict,
        ref: CxAgentRef,
        snapshot_path: str,
        dry_run: bool = False,
    ) -> ExportResult:
        """Export pipeline:

        1. Load base snapshot from disk.
        2. Map AutoAgent config → CX format overlay.
        3. Compute changes diff.
        4. If not dry_run, push changes via REST API.

        Args:
            config: AutoAgent config dict to export.
            ref: Reference identifying the target CX agent.
            snapshot_path: Path to the local snapshot JSON written during import.
            dry_run: When True, compute and return the diff without pushing anything.

        Returns:
            ExportResult with the list of changes and push status.

        Raises:
            CxExportError: On any failure during the export pipeline.
        """
        try:
            # 1. Load base snapshot from disk
            snap_data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
            base_snapshot = CxAgentSnapshot.model_validate(snap_data)

            # 2. Map AutoAgent config → CX snapshot overlay
            updated_snapshot = self._mapper.to_cx(config, base_snapshot)

            # 3. Compute changes diff
            changes = self._compute_changes(base_snapshot, updated_snapshot)

            if dry_run or not changes:
                return ExportResult(
                    changes=changes,
                    pushed=False,
                    resources_updated=0,
                )

            # 4. Push changes via REST API
            resources_updated = 0

            # Update agent resource if generative settings or description changed
            if any(c["resource"] == "agent" for c in changes):
                self._client.update_agent(ref, updated_snapshot.agent)
                resources_updated += 1

            # Update only playbooks whose instructions changed
            for playbook in updated_snapshot.playbooks:
                orig = next(
                    (p for p in base_snapshot.playbooks if p.name == playbook.name),
                    None,
                )
                if orig is not None and orig.instructions != playbook.instructions:
                    self._client.update_playbook(ref, playbook)
                    resources_updated += 1

            return ExportResult(
                changes=changes,
                pushed=True,
                resources_updated=resources_updated,
            )
        except CxExportError:
            raise
        except Exception as exc:
            raise CxExportError(f"Export failed: {exc}") from exc

    def preview_changes(self, config: dict, snapshot_path: str) -> list[dict]:
        """Preview what would change without pushing.

        Args:
            config: AutoAgent config dict to compare against the base snapshot.
            snapshot_path: Path to the local snapshot JSON written during import.

        Returns:
            List of change descriptors (resource, field, action).

        Raises:
            CxExportError: If the snapshot cannot be loaded or mapping fails.
        """
        try:
            snap_data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
            base_snapshot = CxAgentSnapshot.model_validate(snap_data)
            updated_snapshot = self._mapper.to_cx(config, base_snapshot)
            return self._compute_changes(base_snapshot, updated_snapshot)
        except CxExportError:
            raise
        except Exception as exc:
            raise CxExportError(f"Preview failed: {exc}") from exc

    def _compute_changes(
        self,
        base: CxAgentSnapshot,
        updated: CxAgentSnapshot,
    ) -> list[dict]:
        """Compute the list of changes between base and updated snapshots.

        Args:
            base: Original snapshot fetched during import.
            updated: Snapshot with AutoAgent config overlaid.

        Returns:
            List of change descriptors, each with at minimum ``resource`` and
            ``action`` keys.
        """
        changes: list[dict] = []

        # Agent-level changes
        if base.agent.generative_settings != updated.agent.generative_settings:
            changes.append({
                "resource": "agent",
                "field": "generative_settings",
                "action": "update",
            })
        if base.agent.description != updated.agent.description:
            changes.append({
                "resource": "agent",
                "field": "description",
                "action": "update",
            })

        # Playbook changes
        for updated_pb in updated.playbooks:
            orig = next(
                (p for p in base.playbooks if p.name == updated_pb.name),
                None,
            )
            if orig is None:
                changes.append({
                    "resource": "playbook",
                    "name": updated_pb.display_name,
                    "action": "add",
                })
            elif orig.instructions != updated_pb.instructions:
                changes.append({
                    "resource": "playbook",
                    "name": updated_pb.display_name,
                    "action": "update",
                    "field": "instructions",
                })

        return changes
