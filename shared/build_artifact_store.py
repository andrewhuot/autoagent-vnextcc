"""Shared durable store for build artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.contracts import BuildArtifact

DEFAULT_BUILD_ARTIFACT_STORE_PATH = Path(".agentlab") / "build_artifacts.json"
DEFAULT_LATEST_BUILD_ARTIFACT_PATH = Path(".agentlab") / "build_artifact_latest.json"


class StateStoreCorruptionError(RuntimeError):
    """Raised when a durable JSON store is unreadable or structurally invalid."""


class BuildArtifactStore:
    """Persist shared build artifacts while preserving CLI compatibility files."""

    def __init__(
        self,
        path: str | Path = DEFAULT_BUILD_ARTIFACT_STORE_PATH,
        latest_path: str | Path = DEFAULT_LATEST_BUILD_ARTIFACT_PATH,
    ) -> None:
        self.path = Path(path)
        self.latest_path = Path(latest_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.latest_path.parent.mkdir(parents=True, exist_ok=True)

    def save_latest(
        self,
        artifact: BuildArtifact | dict[str, Any],
        *,
        legacy_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Save an artifact as the newest record and update the compatibility snapshot."""
        payload = self._load()
        artifact_dict = self._normalize_artifact(artifact)

        previous_latest_id = payload.get("latest_id")
        if previous_latest_id and previous_latest_id in payload["artifacts"]:
            payload["artifacts"][previous_latest_id]["selector"] = ""

        artifact_dict["selector"] = "latest"
        payload["artifacts"][artifact_dict["id"]] = artifact_dict
        payload["latest_id"] = artifact_dict["id"]

        compatibility_payload = legacy_payload or self._build_legacy_payload(artifact_dict)
        payload["legacy_payloads"][artifact_dict["id"]] = compatibility_payload

        self._save(payload)
        self.latest_path.write_text(
            json.dumps(compatibility_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return artifact_dict

    def get_latest(self) -> dict[str, Any] | None:
        """Return the latest shared build artifact."""
        payload = self._load()
        latest_id = payload.get("latest_id")
        if not latest_id:
            return None
        artifact = payload["artifacts"].get(latest_id)
        if artifact is None:
            return None
        return dict(artifact)

    def get_latest_legacy(self) -> dict[str, Any] | None:
        """Return the latest compatibility payload for CLI build-show consumers."""
        payload = self._load()
        latest_id = payload.get("latest_id")
        if latest_id:
            legacy_payload = payload["legacy_payloads"].get(latest_id)
            if isinstance(legacy_payload, dict):
                return dict(legacy_payload)

        if not self.latest_path.exists():
            return None

        try:
            raw = json.loads(self.latest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return raw if isinstance(raw, dict) else None

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent shared artifacts ordered by `updated_at` descending."""
        payload = self._load()
        artifacts = list(payload["artifacts"].values())
        artifacts.sort(
            key=lambda artifact: (
                str(artifact.get("updated_at", "")),
                str(artifact.get("created_at", "")),
            ),
            reverse=True,
        )
        return [dict(artifact) for artifact in artifacts[:limit]]

    def get_by_id(self, artifact_id: str) -> dict[str, Any] | None:
        """Return one shared build artifact by ID."""
        payload = self._load()
        artifact = payload["artifacts"].get(artifact_id)
        if artifact is None:
            return None
        return dict(artifact)

    def _load(self) -> dict[str, Any]:
        """Load the JSON store, or initialize the empty structure."""
        if not self.path.exists():
            return {
                "latest_id": None,
                "artifacts": {},
                "legacy_payloads": {},
            }

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise StateStoreCorruptionError(
                f"Corrupt build artifact store at {self.path}"
            ) from exc

        if not isinstance(raw, dict):
            raise StateStoreCorruptionError(
                f"Corrupt build artifact store at {self.path}: expected a JSON object"
            )

        artifacts = raw.get("artifacts", {})
        legacy_payloads = raw.get("legacy_payloads", {})
        if not isinstance(artifacts, dict):
            raise StateStoreCorruptionError(
                f"Corrupt build artifact store at {self.path}: 'artifacts' must be an object"
            )
        if not isinstance(legacy_payloads, dict):
            raise StateStoreCorruptionError(
                f"Corrupt build artifact store at {self.path}: 'legacy_payloads' must be an object"
            )
        return {
            "latest_id": raw.get("latest_id"),
            "artifacts": artifacts,
            "legacy_payloads": legacy_payloads,
        }

    def _save(self, payload: dict[str, Any]) -> None:
        """Write the shared store payload to disk."""
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _normalize_artifact(self, artifact: BuildArtifact | dict[str, Any]) -> dict[str, Any]:
        """Convert an artifact-like value into the shared contract shape."""
        if isinstance(artifact, BuildArtifact):
            return artifact.to_dict()
        return BuildArtifact.from_dict(artifact).to_dict()

    @staticmethod
    def _build_legacy_payload(artifact: dict[str, Any]) -> dict[str, Any]:
        """Create the legacy CLI payload shape from a shared artifact record."""
        metadata = artifact.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}

        legacy_from_metadata = metadata.get("legacy_payload")
        if isinstance(legacy_from_metadata, dict):
            return dict(legacy_from_metadata)

        return {
            "artifact_id": artifact["id"],
            "source": artifact.get("source"),
            "status": artifact.get("status"),
            "source_prompt": artifact.get("prompt_used", ""),
            "connectors": list(metadata.get("connectors", [])),
            "intents": list(metadata.get("intents", [])),
            "tools": list(metadata.get("tools", [])),
            "guardrails": list(metadata.get("guardrails", [])),
            "skills": list(metadata.get("skills", [])),
            "config_yaml": artifact.get("config_yaml", ""),
        }
