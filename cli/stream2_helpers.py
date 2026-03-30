"""CLI Stream 2 helpers — config import, durable semantics, JSON output, selectors, inspect.

Provides reusable logic for FR-05 through FR-13 so runner.py stays manageable.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from cli.json_envelope import render_json_envelope
from cli.selectors import is_selector as shared_is_selector
from cli.selectors import resolve_selector as shared_resolve_selector


# ---------------------------------------------------------------------------
# FR-05: Config importer
# ---------------------------------------------------------------------------

class ConfigImporter:
    """Import plain YAML/JSON config files into the versioned config store."""

    def __init__(self, configs_dir: str = "configs") -> None:
        self.configs_dir = Path(configs_dir)
        self.configs_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.configs_dir / "manifest.json"

    def _load_manifest(self) -> dict:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return {"versions": [], "active_version": None, "canary_version": None}

    def _save_manifest(self, manifest: dict) -> None:
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def _config_hash(self, config: dict) -> str:
        canonical = yaml.safe_dump(config, sort_keys=True).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()[:12]

    def import_config(self, file_path: str) -> dict[str, Any]:
        """Import a config file, returning metadata about the imported version."""
        source = Path(file_path)
        if not source.exists():
            raise FileNotFoundError(f"Config file not found: {file_path}")

        raw = source.read_text(encoding="utf-8")
        if source.suffix in (".yaml", ".yml"):
            config = yaml.safe_load(raw)
        elif source.suffix == ".json":
            config = json.loads(raw)
        else:
            # Try YAML first, fall back to JSON
            try:
                config = yaml.safe_load(raw)
            except Exception:
                config = json.loads(raw)

        if not isinstance(config, dict):
            raise ValueError("Config file must contain a mapping/object at the top level.")

        manifest = self._load_manifest()
        versions = manifest.get("versions", [])
        next_version = max((v["version"] for v in versions), default=0) + 1

        filename = f"v{next_version:03d}_imported.yaml"
        dest = self.configs_dir / filename
        dest.write_text(yaml.safe_dump(config, default_flow_style=False, sort_keys=False), encoding="utf-8")

        entry = {
            "version": next_version,
            "config_hash": self._config_hash(config),
            "filename": filename,
            "timestamp": time.time(),
            "scores": {},
            "status": "imported",
            "source_file": source.name,
        }
        manifest["versions"].append(entry)
        self._save_manifest(manifest)

        return {
            "version": next_version,
            "filename": filename,
            "config_hash": entry["config_hash"],
            "source_file": source.name,
            "dest_path": str(dest),
        }


# ---------------------------------------------------------------------------
# FR-06: Durable semantics helpers
# ---------------------------------------------------------------------------

class ReleaseStore:
    """Persist release objects to .autoagent/releases/."""

    def __init__(self, store_dir: str = ".autoagent/releases") -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def create(self, experiment_id: str, config_version: int | None = None) -> dict[str, Any]:
        release_id = f"rel-{uuid.uuid4().hex[:8]}"
        release = {
            "release_id": release_id,
            "experiment_id": experiment_id,
            "config_version": config_version,
            "status": "DRAFT",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self.store_dir / f"{release_id}.json"
        path.write_text(json.dumps(release, indent=2), encoding="utf-8")
        return release

    def list_releases(self, limit: int = 20) -> list[dict]:
        releases = []
        for p in sorted(self.store_dir.glob("rel-*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                releases.append(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
            if len(releases) >= limit:
                break
        return releases

    def get(self, release_id: str) -> dict | None:
        path = self.store_dir / f"{release_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


def write_trace_eval_case(trace_id: str, eval_case: dict, eval_cases_dir: str = "evals/cases") -> str:
    """Write a promoted trace as an eval case file. Returns the file path."""
    cases_dir = Path(eval_cases_dir)
    cases_dir.mkdir(parents=True, exist_ok=True)
    filename = f"promoted_{trace_id}.yaml"
    path = cases_dir / filename
    path.write_text(yaml.safe_dump({"cases": [eval_case]}, sort_keys=False), encoding="utf-8")
    return str(path)


def apply_autofix_to_config(
    proposal_id: str,
    new_config: dict,
    configs_dir: str = "configs",
) -> dict[str, Any]:
    """Write a new config version from an autofix apply. Returns version metadata."""
    importer = ConfigImporter(configs_dir=configs_dir)
    manifest = importer._load_manifest()
    versions = manifest.get("versions", [])
    next_version = max((v["version"] for v in versions), default=0) + 1
    filename = f"v{next_version:03d}_autofix_{proposal_id[:8]}.yaml"
    dest = Path(configs_dir) / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump(new_config, default_flow_style=False, sort_keys=False), encoding="utf-8")

    entry = {
        "version": next_version,
        "config_hash": importer._config_hash(new_config),
        "filename": filename,
        "timestamp": time.time(),
        "scores": {},
        "status": "candidate",
        "source": f"autofix:{proposal_id}",
    }
    manifest["versions"].append(entry)
    importer._save_manifest(manifest)
    return {"version": next_version, "filename": filename, "path": str(dest)}


# ---------------------------------------------------------------------------
# FR-07: Standard JSON output helpers
# ---------------------------------------------------------------------------

def json_response(status: str, data: Any, next_cmd: str | None = None) -> str:
    """Build a standard JSON response string."""
    return render_json_envelope(status=status, data=data, next_command=next_cmd)


# ---------------------------------------------------------------------------
# FR-08: Selector resolution
# ---------------------------------------------------------------------------

STANDARD_SELECTORS = {"latest", "current", "active", "pending"}


def resolve_selector(selector: str, items: list[dict], status_key: str = "status") -> dict | None:
    """Resolve a standard selector against a list of items.

    Items should be sorted newest-first.
    """
    return shared_resolve_selector(selector, items, status_key=status_key)


def is_selector(value: str) -> bool:
    """Check if a value is a standard selector keyword."""
    return shared_is_selector(value)


# ---------------------------------------------------------------------------
# FR-13: Inspect helpers
# ---------------------------------------------------------------------------

def get_latest_build_artifact(autoagent_dir: str = ".autoagent") -> dict | None:
    """Load the latest build artifact."""
    from shared.build_artifact_store import BuildArtifactStore

    autoagent_path = Path(autoagent_dir)
    store = BuildArtifactStore(
        path=autoagent_path / "build_artifacts.json",
        latest_path=autoagent_path / "build_artifact_latest.json",
    )
    artifact = store.get_latest_legacy()
    if artifact is not None:
        return artifact
    return None


def get_latest_eval_result() -> dict | None:
    """Find the most recent eval results file."""
    results_files = sorted(Path(".").glob("*results*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not results_files:
        return None
    try:
        return json.loads(results_files[0].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_policies() -> list[dict]:
    """List policy artifacts from the policy_opt registry."""
    try:
        from policy_opt.registry import PolicyArtifactRegistry
        registry = PolicyArtifactRegistry()
        policies = registry.list_all()
        result = []
        for p in policies:
            result.append({
                "policy_id": p.policy_id,
                "name": p.name,
                "version": p.version,
                "status": p.status,
                "mode": p.mode.value if hasattr(p.mode, "value") else str(p.mode),
                "backend": p.backend,
            })
        registry.close()
        return result
    except Exception:
        return []


def get_policy(policy_id_or_name: str) -> dict | None:
    """Get a policy by ID or name."""
    try:
        from policy_opt.registry import PolicyArtifactRegistry
        registry = PolicyArtifactRegistry()
        policy = registry.get_by_id(policy_id_or_name)
        if policy is None:
            # Try by name
            all_policies = registry.list_all()
            for p in all_policies:
                if p.name == policy_id_or_name:
                    policy = p
                    break
        registry.close()
        if policy is None:
            return None
        return {
            "policy_id": policy.policy_id,
            "name": policy.name,
            "version": policy.version,
            "status": policy.status,
            "mode": policy.mode.value if hasattr(policy.mode, "value") else str(policy.mode),
            "backend": policy.backend,
            "created_at": getattr(policy, "created_at", ""),
            "metadata": getattr(policy, "metadata", {}),
        }
    except Exception:
        return None
