"""Config version persistence and promotion state management."""

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
            if previous_canary is not None:
                previous_entry = self._find_version(previous_canary)
                if previous_entry is not None and previous_entry["status"] == "canary":
                    previous_entry["status"] = "retired"
            self.manifest["canary_version"] = version_num
        elif status == "active":
            previous_active = self.manifest.get("active_version")
            if previous_active is not None:
                previous_entry = self._find_version(previous_active)
                if previous_entry is not None and previous_entry["status"] == "active":
                    previous_entry["status"] = "retired"
            self.manifest["active_version"] = version_num
        self._save_manifest()
        return cv

    def promote(self, version: int):
        """Promote a version to active, retire the old active."""
        promoted = self._find_version(version)
        if promoted is None:
            raise ValueError(f"Unknown version: {version}")

        for v in self.manifest["versions"]:
            if v["version"] == self.manifest.get("active_version") and v["version"] != version:
                v["status"] = "retired"
            if v["version"] == version:
                v["status"] = "active"
        self.manifest["active_version"] = version
        self.manifest["canary_version"] = None
        self._save_manifest()

    def rollback(self, version: int):
        """Rollback a canary version."""
        rolled_back = self._find_version(version)
        if rolled_back is None:
            raise ValueError(f"Unknown version: {version}")

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

    def get_version_history(self) -> list[dict]:
        return list(self.manifest["versions"])
