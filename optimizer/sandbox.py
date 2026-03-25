"""Sandbox isolation for candidate config evaluation.

Each candidate gets a temporary directory with a clean config copy.
Diffs are computed against the baseline. Cleanup after accept/reject.
"""

from __future__ import annotations

import copy
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SandboxConfig:
    """Configuration for a sandbox instance."""

    sandbox_id: str = ""
    work_dir: str = ""
    baseline_config: dict[str, Any] = field(default_factory=dict)
    candidate_config: dict[str, Any] = field(default_factory=dict)
    created: bool = False

    def __post_init__(self) -> None:
        if not self.sandbox_id:
            self.sandbox_id = str(uuid.uuid4())[:8]


class CandidateSandbox:
    """Isolated workspace for evaluating candidate configs."""

    def __init__(self, baseline_config: dict[str, Any]) -> None:
        self._sandbox_id = str(uuid.uuid4())[:8]
        self._work_dir = tempfile.mkdtemp(
            prefix=f"autoagent_sandbox_{self._sandbox_id}_"
        )
        self._baseline = copy.deepcopy(baseline_config)
        self._candidate: dict[str, Any] | None = None

        # Save baseline to sandbox
        baseline_path = Path(self._work_dir) / "baseline.yaml"
        with baseline_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                self._baseline, f, default_flow_style=False, sort_keys=False
            )

    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    @property
    def work_dir(self) -> str:
        return self._work_dir

    @property
    def baseline_config(self) -> dict[str, Any]:
        return copy.deepcopy(self._baseline)

    @property
    def candidate_config(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._candidate) if self._candidate else None

    def apply_mutation(self, mutation: dict[str, Any]) -> dict[str, Any]:
        """Apply a mutation dict to the baseline config in the sandbox.

        Returns the resulting candidate config.
        """
        self._candidate = copy.deepcopy(self._baseline)
        _deep_merge(self._candidate, mutation)

        # Save candidate to sandbox
        candidate_path = Path(self._work_dir) / "candidate.yaml"
        with candidate_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                self._candidate, f, default_flow_style=False, sort_keys=False
            )

        return copy.deepcopy(self._candidate)

    def set_candidate(self, candidate_config: dict[str, Any]) -> None:
        """Directly set the candidate config (when mutation is already applied)."""
        self._candidate = copy.deepcopy(candidate_config)

        candidate_path = Path(self._work_dir) / "candidate.yaml"
        with candidate_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                self._candidate, f, default_flow_style=False, sort_keys=False
            )

    def compute_diff(self) -> list[dict[str, Any]]:
        """Compute YAML-aware diff between baseline and candidate.

        Returns a list of diff entries, each with surface, old_value, new_value.
        """
        if self._candidate is None:
            return []
        return yaml_diff(self._baseline, self._candidate)

    def cleanup(self) -> None:
        """Remove sandbox directory."""
        try:
            shutil.rmtree(self._work_dir, ignore_errors=True)
        except (OSError, PermissionError):
            pass

    def __enter__(self) -> CandidateSandbox:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        self.cleanup()
        return False


def yaml_diff(
    old: dict[str, Any],
    new: dict[str, Any],
    prefix: str = "",
) -> list[dict[str, Any]]:
    """Compute structural diff between two YAML-like dicts.

    Returns list of {surface, old_value, new_value} entries.
    """
    diffs: list[dict[str, Any]] = []

    all_keys = set(old.keys()) | set(new.keys())

    for key in sorted(all_keys):
        surface = f"{prefix}.{key}" if prefix else key
        old_val = old.get(key)
        new_val = new.get(key)

        if old_val == new_val:
            continue

        if isinstance(old_val, dict) and isinstance(new_val, dict):
            # Recurse into nested dicts
            diffs.extend(yaml_diff(old_val, new_val, surface))
        else:
            diffs.append({
                "surface": surface,
                "old_value": _format_value(old_val),
                "new_value": _format_value(new_val),
            })

    return diffs


def _format_value(val: Any) -> str:
    """Format a value for diff display."""
    if val is None:
        return "(not set)"
    if isinstance(val, (dict, list)):
        return yaml.safe_dump(val, default_flow_style=True).strip()
    return str(val)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Deep merge override into base dict (in-place)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
