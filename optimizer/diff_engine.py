"""YAML-aware diff engine with hunk-level operations.

Generates unified diffs between configs, supports hunk-level
accept/reject, and provides colored terminal output.
"""

from __future__ import annotations

import copy
import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any

import yaml

from .change_card import DiffHunk


@dataclass
class UnifiedDiff:
    """A complete unified diff between two configs."""

    hunks: list[DiffHunk] = field(default_factory=list)
    baseline_hash: str = ""
    candidate_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "hunks": [h.to_dict() for h in self.hunks],
            "baseline_hash": self.baseline_hash,
            "candidate_hash": self.candidate_hash,
            "total_hunks": len(self.hunks),
            "pending_hunks": sum(1 for h in self.hunks if h.status == "pending"),
            "accepted_hunks": sum(
                1 for h in self.hunks if h.status == "accepted"
            ),
            "rejected_hunks": sum(
                1 for h in self.hunks if h.status == "rejected"
            ),
        }


class DiffEngine:
    """YAML-aware diff engine for configuration changes."""

    def compute_diff(
        self,
        baseline: dict[str, Any],
        candidate: dict[str, Any],
    ) -> UnifiedDiff:
        """Compute a unified diff between baseline and candidate configs."""
        baseline_str = yaml.safe_dump(baseline, sort_keys=True)
        candidate_str = yaml.safe_dump(candidate, sort_keys=True)

        hunks = self._diff_dicts(baseline, candidate, prefix="")

        return UnifiedDiff(
            hunks=hunks,
            baseline_hash=hashlib.sha256(baseline_str.encode()).hexdigest()[:12],
            candidate_hash=hashlib.sha256(candidate_str.encode()).hexdigest()[
                :12
            ],
        )

    def apply_hunks(
        self,
        baseline: dict[str, Any],
        diff: UnifiedDiff,
    ) -> dict[str, Any]:
        """Apply accepted hunks from a diff to the baseline config.

        Only hunks with status 'accepted' are applied.
        Hunks with status 'rejected' or 'pending' are skipped.
        """
        result = copy.deepcopy(baseline)

        for hunk in diff.hunks:
            if hunk.status != "accepted":
                continue
            self._apply_hunk(result, hunk)

        return result

    def accept_hunk(self, diff: UnifiedDiff, hunk_id: str) -> bool:
        """Accept a specific hunk by ID."""
        for hunk in diff.hunks:
            if hunk.hunk_id == hunk_id:
                hunk.status = "accepted"
                return True
        return False

    def reject_hunk(self, diff: UnifiedDiff, hunk_id: str) -> bool:
        """Reject a specific hunk by ID."""
        for hunk in diff.hunks:
            if hunk.hunk_id == hunk_id:
                hunk.status = "rejected"
                return True
        return False

    def accept_all(self, diff: UnifiedDiff) -> int:
        """Accept all pending hunks. Returns count of accepted hunks."""
        count = 0
        for hunk in diff.hunks:
            if hunk.status == "pending":
                hunk.status = "accepted"
                count += 1
        return count

    def reject_all(self, diff: UnifiedDiff) -> int:
        """Reject all pending hunks. Returns count of rejected hunks."""
        count = 0
        for hunk in diff.hunks:
            if hunk.status == "pending":
                hunk.status = "rejected"
                count += 1
        return count

    def to_terminal(self, diff: UnifiedDiff) -> str:
        """Render diff for terminal display with color codes."""
        lines: list[str] = []
        lines.append(f"--- baseline ({diff.baseline_hash})")
        lines.append(f"+++ candidate ({diff.candidate_hash})")
        lines.append("")

        for i, hunk in enumerate(diff.hunks, 1):
            status_marker = {
                "pending": "?",
                "accepted": "\u2713",
                "rejected": "\u2717",
            }.get(hunk.status, "?")
            lines.append(f"[{status_marker}] Hunk {i}: {hunk.surface}")

            if hunk.old_value:
                for old_line in hunk.old_value.splitlines():
                    lines.append(f"\033[31m  - {old_line}\033[0m")
            if hunk.new_value:
                for new_line in hunk.new_value.splitlines():
                    lines.append(f"\033[32m  + {new_line}\033[0m")
            lines.append("")

        return "\n".join(lines)

    def to_plain(self, diff: UnifiedDiff) -> str:
        """Render diff for plain text (no ANSI codes)."""
        lines: list[str] = []
        lines.append(f"--- baseline ({diff.baseline_hash})")
        lines.append(f"+++ candidate ({diff.candidate_hash})")
        lines.append("")

        for i, hunk in enumerate(diff.hunks, 1):
            status_marker = {
                "pending": "?",
                "accepted": "\u2713",
                "rejected": "\u2717",
            }.get(hunk.status, "?")
            lines.append(f"[{status_marker}] Hunk {i}: {hunk.surface}")

            if hunk.old_value:
                for old_line in hunk.old_value.splitlines():
                    lines.append(f"  - {old_line}")
            if hunk.new_value:
                for new_line in hunk.new_value.splitlines():
                    lines.append(f"  + {new_line}")
            lines.append("")

        return "\n".join(lines)

    def _diff_dicts(
        self,
        old: dict[str, Any],
        new: dict[str, Any],
        prefix: str,
    ) -> list[DiffHunk]:
        """Recursively diff two dicts, producing DiffHunks."""
        hunks: list[DiffHunk] = []
        all_keys = sorted(set(old.keys()) | set(new.keys()))

        for key in all_keys:
            surface = f"{prefix}.{key}" if prefix else key
            old_val = old.get(key)
            new_val = new.get(key)

            if old_val == new_val:
                continue

            if isinstance(old_val, dict) and isinstance(new_val, dict):
                hunks.extend(self._diff_dicts(old_val, new_val, surface))
            else:
                hunks.append(
                    DiffHunk(
                        hunk_id=str(uuid.uuid4())[:8],
                        surface=surface,
                        old_value=_format_yaml_value(old_val),
                        new_value=_format_yaml_value(new_val),
                        status="pending",
                    )
                )

        return hunks

    def _apply_hunk(self, config: dict[str, Any], hunk: DiffHunk) -> None:
        """Apply a single hunk to a config dict."""
        parts = hunk.surface.split(".")
        target = config

        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]

        # Parse the new value back from string
        try:
            new_val = yaml.safe_load(hunk.new_value)
        except (yaml.YAMLError, ValueError):
            new_val = hunk.new_value

        if new_val == "(not set)" or new_val is None:
            target.pop(parts[-1], None)
        else:
            target[parts[-1]] = new_val


def _format_yaml_value(val: Any) -> str:
    """Format a value for diff display."""
    if val is None:
        return "(not set)"
    if isinstance(val, (dict, list)):
        return yaml.safe_dump(val, default_flow_style=False).strip()
    return str(val)
