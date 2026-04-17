"""Config version persistence and promotion state management."""

from __future__ import annotations

import difflib
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ConfigVersion:
    version: int
    config_hash: str
    filename: str
    timestamp: float
    scores: dict  # composite score dict at time of deployment
    status: str  # "active", "canary", "retired", "rolled_back"


class ConfigVersionManager:
    def __init__(self, configs_dir: str = "configs"):
        self.configs_dir = Path(configs_dir)
        self.configs_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.configs_dir / "manifest.json"
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        """Load or create manifest tracking all versions."""
        if self.manifest_path.exists():
            with self.manifest_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        return {"versions": [], "active_version": None, "canary_version": None}

    def _save_manifest(self):
        with self.manifest_path.open("w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2)

    def _config_hash(self, config: dict) -> str:
        canonical = yaml.safe_dump(config, sort_keys=True).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()[:12]

    def _find_version(self, version: int) -> dict | None:
        """Return manifest entry for a version number, if present."""
        for item in self.manifest["versions"]:
            if item["version"] == version:
                return item
        return None

    def _retire_version_if(self, version: int | None, *, expected_status: str) -> None:
        """Retire a tracked version when it currently owns a specific manifest role."""
        if version is None:
            return

        entry = self._find_version(version)
        if entry is not None and entry["status"] == expected_status:
            entry["status"] = "retired"

    def get_next_version(self) -> int:
        if not self.manifest["versions"]:
            return 1
        return max(v["version"] for v in self.manifest["versions"]) + 1

    def save_version(self, config: dict, scores: dict, status: str = "canary") -> ConfigVersion:
        """Save a new config version."""
        version_num = self.get_next_version()
        filename = f"v{version_num:03d}.yaml"
        filepath = self.configs_dir / filename

        with filepath.open("w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)

        cv = ConfigVersion(
            version=version_num,
            config_hash=self._config_hash(config),
            filename=filename,
            timestamp=time.time(),
            scores=scores,
            status=status,
        )
        self.manifest["versions"].append({
            "version": cv.version,
            "config_hash": cv.config_hash,
            "filename": cv.filename,
            "timestamp": cv.timestamp,
            "scores": cv.scores,
            "status": cv.status,
        })
        if status == "canary":
            previous_canary = self.manifest.get("canary_version")
            self._retire_version_if(previous_canary, expected_status="canary")
            self.manifest["canary_version"] = version_num
        elif status == "active":
            previous_active = self.manifest.get("active_version")
            previous_canary = self.manifest.get("canary_version")
            self._retire_version_if(previous_active, expected_status="active")
            self._retire_version_if(previous_canary, expected_status="canary")
            self.manifest["active_version"] = version_num
            self.manifest["canary_version"] = None
        self._save_manifest()
        return cv

    def promote(self, version: int):
        """Promote a version to active, retire the old active."""
        promoted = self._find_version(version)
        if promoted is None:
            raise ValueError(f"Unknown version: {version}")

        previous_active = self.manifest.get("active_version")
        previous_canary = self.manifest.get("canary_version")
        for v in self.manifest["versions"]:
            if v["version"] == previous_active and v["version"] != version:
                v["status"] = "retired"
            if v["version"] == previous_canary and v["version"] != version and v["status"] == "canary":
                v["status"] = "retired"
            if v["version"] == version:
                v["status"] = "active"
        self.manifest["active_version"] = version
        self.manifest["canary_version"] = None
        self._save_manifest()

    def mark_canary(self, version: int) -> None:
        """Mark an existing version as the active canary target."""
        candidate = self._find_version(version)
        if candidate is None:
            raise ValueError(f"Unknown version: {version}")
        if version == self.manifest.get("active_version") or candidate["status"] == "active":
            raise ValueError(f"Cannot mark active version {version} as canary")

        previous_canary = self.manifest.get("canary_version")
        if previous_canary is not None and previous_canary != version:
            self._retire_version_if(previous_canary, expected_status="canary")

        candidate["status"] = "canary"
        self.manifest["canary_version"] = version
        self._save_manifest()

    def rollback(self, version: int):
        """Rollback a canary version."""
        rolled_back = self._find_version(version)
        if rolled_back is None:
            raise ValueError(f"Unknown version: {version}")
        if version == self.manifest.get("active_version"):
            raise ValueError(f"Cannot roll back active version {version}")

        for v in self.manifest["versions"]:
            if v["version"] == version:
                v["status"] = "rolled_back"
        if self.manifest.get("canary_version") == version:
            self.manifest["canary_version"] = None
        self._save_manifest()

    def get_active_config(self) -> dict | None:
        """Load the active config."""
        active = self.manifest.get("active_version")
        if active is None:
            return None
        for v in self.manifest["versions"]:
            if v["version"] == active:
                filepath = self.configs_dir / v["filename"]
                with filepath.open("r", encoding="utf-8") as f:
                    return yaml.safe_load(f)
        return None

    def get_canary_config(self) -> dict | None:
        """Load the canary config if one exists."""
        canary = self.manifest.get("canary_version")
        if canary is None:
            return None
        for v in self.manifest["versions"]:
            if v["version"] == canary:
                filepath = self.configs_dir / v["filename"]
                with filepath.open("r", encoding="utf-8") as f:
                    return yaml.safe_load(f)
        return None

    def reload(self) -> None:
        """Refresh the in-memory manifest from disk."""
        self.manifest = self._load_manifest()

    def get_version_history(self) -> list[dict]:
        return list(self.manifest["versions"])

    # ------------------------------------------------------------------
    # Enhanced inspection helpers
    # ------------------------------------------------------------------

    def diff_versions(self, version_a: int, version_b: int) -> str:
        """Produce a human-readable diff between two config versions.

        Returns a unified diff string, or a descriptive error message.
        """
        entry_a = self._find_version(version_a)
        entry_b = self._find_version(version_b)

        if entry_a is None:
            return f"Error: version {version_a} not found"
        if entry_b is None:
            return f"Error: version {version_b} not found"

        path_a = self.configs_dir / entry_a["filename"]
        path_b = self.configs_dir / entry_b["filename"]

        if not path_a.exists():
            return f"Error: config file {entry_a['filename']} missing from disk"
        if not path_b.exists():
            return f"Error: config file {entry_b['filename']} missing from disk"

        text_a = path_a.read_text(encoding="utf-8").splitlines(keepends=True)
        text_b = path_b.read_text(encoding="utf-8").splitlines(keepends=True)

        diff_lines = list(
            difflib.unified_diff(
                text_a,
                text_b,
                fromfile=entry_a["filename"],
                tofile=entry_b["filename"],
            )
        )

        if not diff_lines:
            return "No changes"

        return "".join(diff_lines)

    def get_version_summary(self, version: int) -> dict:
        """Return a summary dict for a version (scores, status, timestamp, etc)."""
        entry = self._find_version(version)
        if entry is None:
            return {"error": f"version {version} not found"}
        return {
            "version": entry["version"],
            "config_hash": entry["config_hash"],
            "filename": entry["filename"],
            "timestamp": entry["timestamp"],
            "scores": entry.get("scores", {}),
            "status": entry["status"],
        }

    def list_versions(self, limit: int = 20) -> list[dict]:
        """Return recent versions with metadata, newest first."""
        versions = sorted(
            self.manifest["versions"],
            key=lambda v: v["version"],
            reverse=True,
        )
        return versions[:limit]
