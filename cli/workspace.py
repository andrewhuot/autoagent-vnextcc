"""Workspace discovery and metadata helpers for the AutoAgent CLI."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


WORKSPACE_DIRNAME = ".autoagent"
WORKSPACE_METADATA_FILENAME = "workspace.json"
DEFAULT_LIFECYCLE_SKILL_DB = Path(WORKSPACE_DIRNAME) / "core_skills.db"
SETTINGS_FILENAME = "settings.json"
_CONFIG_VERSION_RE = re.compile(r"^v(?P<version>\d{3})(?:$|_.*$)")


@dataclass
class WorkspaceMetadata:
    """Persisted workspace metadata used by CLI commands."""

    name: str
    active_config_version: int | None = None
    active_config_file: str | None = None
    schema_version: int = 1
    created_at: float = 0.0
    template: str = "customer-support"
    agent_name: str = "My Agent"
    platform: str = "Google ADK"
    demo_seeded: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceMetadata:
        """Build metadata from a plain dict."""
        return cls(
            name=str(data.get("name") or "autoagent-workspace"),
            active_config_version=data.get("active_config_version"),
            active_config_file=data.get("active_config_file"),
            schema_version=int(data.get("schema_version", 1)),
            created_at=float(data.get("created_at", 0.0) or 0.0),
            template=str(data.get("template") or "customer-support"),
            agent_name=str(data.get("agent_name") or "My Agent"),
            platform=str(data.get("platform") or "Google ADK"),
            demo_seeded=bool(data.get("demo_seeded", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize metadata for storage in `.autoagent/workspace.json`."""
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "active_config_version": self.active_config_version,
            "active_config_file": self.active_config_file,
            "created_at": self.created_at,
            "template": self.template,
            "agent_name": self.agent_name,
            "platform": self.platform,
            "demo_seeded": self.demo_seeded,
        }


@dataclass
class ResolvedConfig:
    """A config resolved from the workspace metadata or config directory."""

    version: int
    path: Path
    config: dict[str, Any]


@dataclass
class AutoAgentWorkspace:
    """Resolved workspace paths and metadata."""

    root: Path
    metadata: WorkspaceMetadata

    @property
    def autoagent_dir(self) -> Path:
        return self.root / WORKSPACE_DIRNAME

    @property
    def metadata_path(self) -> Path:
        return self.autoagent_dir / WORKSPACE_METADATA_FILENAME

    @property
    def configs_dir(self) -> Path:
        return self.root / "configs"

    @property
    def evals_dir(self) -> Path:
        return self.root / "evals"

    @property
    def cases_dir(self) -> Path:
        return self.evals_dir / "cases"

    @property
    def runtime_config_path(self) -> Path:
        return self.root / "autoagent.yaml"

    @property
    def settings_path(self) -> Path:
        return self.autoagent_dir / SETTINGS_FILENAME

    @property
    def conversation_db(self) -> Path:
        return self.root / "conversations.db"

    @property
    def memory_db(self) -> Path:
        return self.root / "optimizer_memory.db"

    @property
    def registry_db(self) -> Path:
        return self.root / "registry.db"

    @property
    def eval_history_db(self) -> Path:
        return self.root / "eval_history.db"

    @property
    def trace_db(self) -> Path:
        return self.autoagent_dir / "traces.db"

    @property
    def eval_cache_db(self) -> Path:
        return self.autoagent_dir / "eval_cache.db"

    @property
    def skill_db(self) -> Path:
        return self.root / DEFAULT_LIFECYCLE_SKILL_DB

    @property
    def rules_dir(self) -> Path:
        return self.autoagent_dir / "rules"

    @property
    def memory_dir(self) -> Path:
        return self.autoagent_dir / "memory"

    @property
    def local_memory_path(self) -> Path:
        return self.root / "AUTOAGENT.local.md"

    @property
    def mcp_config_path(self) -> Path:
        return self.root / ".mcp.json"

    @property
    def best_score_file(self) -> Path:
        return self.autoagent_dir / "best_score.txt"

    @property
    def scorer_specs_dir(self) -> Path:
        return self.autoagent_dir / "scorers"

    @property
    def change_cards_db(self) -> Path:
        return self.autoagent_dir / "change_cards.db"

    @property
    def autofix_db(self) -> Path:
        return self.autoagent_dir / "autofix.db"

    @property
    def grader_versions_db(self) -> Path:
        return self.autoagent_dir / "grader_versions.db"

    @property
    def human_feedback_db(self) -> Path:
        return self.autoagent_dir / "human_feedback.db"

    @property
    def workspace_label(self) -> str:
        """Return the display label for the workspace."""
        return self.metadata.name or self.root.name

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        name: str,
        template: str,
        agent_name: str,
        platform: str,
        demo_seeded: bool = False,
    ) -> AutoAgentWorkspace:
        """Create a new workspace model with default metadata."""
        metadata = WorkspaceMetadata(
            name=name,
            created_at=time.time(),
            template=template,
            agent_name=agent_name,
            platform=platform,
            demo_seeded=demo_seeded,
        )
        return cls(root=root.resolve(), metadata=metadata)

    def ensure_structure(self) -> None:
        """Create the on-disk directory structure required for a workspace."""
        self.autoagent_dir.mkdir(parents=True, exist_ok=True)
        self.configs_dir.mkdir(parents=True, exist_ok=True)
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        (self.root / "agent" / "config").mkdir(parents=True, exist_ok=True)
        self.scorer_specs_dir.mkdir(parents=True, exist_ok=True)
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        (self.autoagent_dir / "logs").mkdir(parents=True, exist_ok=True)
        self.best_score_file.touch(exist_ok=True)

    def save_metadata(self) -> None:
        """Persist workspace metadata to disk."""
        self.ensure_structure()
        self.metadata_path.write_text(
            json.dumps(self.metadata.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def list_config_versions(self) -> dict[int, list[Path]]:
        """Return discovered config files grouped by semantic version number."""
        versions: dict[int, list[Path]] = {}
        if not self.configs_dir.exists():
            return versions
        for path in sorted(self.configs_dir.glob("*.yaml")):
            match = _CONFIG_VERSION_RE.match(path.stem)
            if match is None:
                continue
            version = int(match.group("version"))
            versions.setdefault(version, []).append(path)
        return versions

    def manifest(self) -> dict[str, Any]:
        """Return the config manifest when available."""
        manifest_path = self.configs_dir / "manifest.json"
        if not manifest_path.exists():
            return {}
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def resolve_config_path(self, version: int) -> Path | None:
        """Resolve the best file path for a given config version."""
        manifest = self.manifest()
        for entry in manifest.get("versions", []):
            if entry.get("version") == version:
                manifest_path = self.configs_dir / str(entry["filename"])
                if manifest_path.exists():
                    return manifest_path

        candidates = self.list_config_versions().get(version, [])
        if not candidates:
            return None

        exact_name = f"v{version:03d}.yaml"
        for candidate in candidates:
            if candidate.name == exact_name:
                return candidate
        for candidate in candidates:
            if candidate.name.endswith("_base.yaml"):
                return candidate
        return sorted(candidates, key=lambda item: (len(item.name), item.name))[0]

    def resolve_active_config(self) -> ResolvedConfig | None:
        """Resolve the workspace active config from metadata or inferred state."""
        manifest = self.manifest()
        selected_version = self.metadata.active_config_version
        selected_path: Path | None = None

        if selected_version is not None:
            selected_path = self.resolve_config_path(selected_version)

        if selected_path is None:
            manifest_active = manifest.get("active_version")
            if manifest_active is not None:
                selected_version = int(manifest_active)
                selected_path = self.resolve_config_path(selected_version)

        if selected_path is None:
            versions = self.list_config_versions()
            if not versions:
                return None
            selected_version = max(versions.keys())
            selected_path = self.resolve_config_path(selected_version)

        if selected_path is None or selected_version is None:
            return None

        config = yaml.safe_load(selected_path.read_text(encoding="utf-8")) or {}
        return ResolvedConfig(version=selected_version, path=selected_path, config=config)

    def set_active_config(self, version: int, *, filename: str | None = None) -> None:
        """Update workspace metadata to point to the requested active config."""
        self.metadata.active_config_version = version
        self.metadata.active_config_file = filename or f"v{version:03d}.yaml"
        self.save_metadata()

    @staticmethod
    def summarize_config(config: dict[str, Any] | None) -> str:
        """Return a short human-readable config summary for status surfaces."""
        if not config:
            return "No config summary available"
        model = str(config.get("model") or "unknown-model")
        prompt = str((config.get("prompts") or {}).get("root") or "").strip()
        compact_prompt = " ".join(prompt.split())
        if compact_prompt:
            snippet = compact_prompt[:72].rstrip()
            if len(compact_prompt) > 72:
                snippet += "..."
            return f"{model} | {snippet}"
        return model


def infer_workspace_metadata(root: Path) -> WorkspaceMetadata:
    """Infer workspace metadata for legacy directories that predate `workspace.json`."""
    metadata_path = root / WORKSPACE_DIRNAME / WORKSPACE_METADATA_FILENAME
    if metadata_path.exists():
        return WorkspaceMetadata.from_dict(
            json.loads(metadata_path.read_text(encoding="utf-8"))
        )

    workspace = AutoAgentWorkspace(root=root.resolve(), metadata=WorkspaceMetadata(name=root.name))
    manifest = workspace.manifest()
    active_version = manifest.get("active_version")
    if active_version is None:
        versions = workspace.list_config_versions()
        active_version = max(versions.keys()) if versions else None

    return WorkspaceMetadata(
        name=root.name,
        active_config_version=active_version,
        active_config_file=(f"v{active_version:03d}.yaml" if active_version is not None else None),
    )


def discover_workspace(start: Path | None = None) -> AutoAgentWorkspace | None:
    """Walk up from `start` and return the nearest AutoAgent workspace, if any."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        autoagent_dir = candidate / WORKSPACE_DIRNAME
        if not autoagent_dir.exists():
            continue
        metadata = infer_workspace_metadata(candidate)
        return AutoAgentWorkspace(root=candidate, metadata=metadata)
    return None
