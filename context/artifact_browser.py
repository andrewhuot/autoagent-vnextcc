"""Artifact browser — versioned artifact storage and diff support."""

from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_hash(content: Any) -> str:
    """Compute a stable SHA-256 hash of the content."""
    if isinstance(content, (dict, list)):
        raw = json.dumps(content, sort_keys=True, ensure_ascii=False)
    else:
        raw = str(content)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ArtifactVersion:
    artifact_id: str
    version: int
    content_hash: str
    created_at: str
    metadata: dict

    # Actual content stored separately (not always serialised)
    _content: Any = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "version": self.version,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ArtifactVersion":
        return cls(
            artifact_id=d["artifact_id"],
            version=d.get("version", 1),
            content_hash=d.get("content_hash", ""),
            created_at=d.get("created_at", _now_iso()),
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------

class ArtifactBrowser:
    """In-memory store for versioned artifacts with diff support."""

    def __init__(self) -> None:
        # artifact_id -> list[ArtifactVersion] (ordered by version ascending)
        self._store: dict[str, list[ArtifactVersion]] = {}

    # ------------------------------------------------------------------
    # Mutation helpers (not part of the public spec but needed for testing)
    # ------------------------------------------------------------------

    def add_version(
        self,
        artifact_id: str,
        content: Any,
        metadata: Optional[dict] = None,
        agent_id: Optional[str] = None,
    ) -> ArtifactVersion:
        """Add a new version of an artifact and return it."""
        versions = self._store.setdefault(artifact_id, [])
        version_num = len(versions) + 1
        meta = dict(metadata or {})
        if agent_id is not None:
            meta["agent_id"] = agent_id

        av = ArtifactVersion(
            artifact_id=artifact_id,
            version=version_num,
            content_hash=_content_hash(content),
            created_at=_now_iso(),
            metadata=meta,
        )
        av._content = content
        versions.append(av)
        return av

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_artifacts(
        self, agent_id: Optional[str] = None
    ) -> list[ArtifactVersion]:
        """Return the latest version of each artifact.

        If agent_id is given, only include artifacts whose metadata contains
        a matching agent_id.
        """
        result: list[ArtifactVersion] = []
        for versions in self._store.values():
            if not versions:
                continue
            latest = versions[-1]
            if agent_id is not None:
                if latest.metadata.get("agent_id") != agent_id:
                    continue
            result.append(latest)
        return result

    def get_version(
        self,
        artifact_id: str,
        version: Optional[int] = None,
    ) -> Optional[ArtifactVersion]:
        """Return a specific version (or the latest if version is None)."""
        versions = self._store.get(artifact_id)
        if not versions:
            return None
        if version is None:
            return versions[-1]
        for av in versions:
            if av.version == version:
                return av
        return None

    def diff_versions(self, artifact_id: str, v1: int, v2: int) -> dict:
        """Return a diff summary between two versions of an artifact.

        Returns a dict with:
          - artifact_id: str
          - v1, v2: int
          - content_hash_v1, content_hash_v2: str
          - unchanged: bool
          - diff_lines: list[str]  (unified diff, text artifacts only)
        """
        av1 = self.get_version(artifact_id, v1)
        av2 = self.get_version(artifact_id, v2)

        if av1 is None or av2 is None:
            return {
                "artifact_id": artifact_id,
                "v1": v1,
                "v2": v2,
                "error": "One or both versions not found",
            }

        unchanged = av1.content_hash == av2.content_hash

        diff_lines: list[str] = []
        if not unchanged:
            c1 = av1._content
            c2 = av2._content

            # Render both sides as text for the diff
            if isinstance(c1, (dict, list)):
                text1 = json.dumps(c1, indent=2, sort_keys=True).splitlines(keepends=True)
            else:
                text1 = str(c1).splitlines(keepends=True)

            if isinstance(c2, (dict, list)):
                text2 = json.dumps(c2, indent=2, sort_keys=True).splitlines(keepends=True)
            else:
                text2 = str(c2).splitlines(keepends=True)

            diff_lines = list(
                difflib.unified_diff(
                    text1,
                    text2,
                    fromfile=f"{artifact_id}@v{v1}",
                    tofile=f"{artifact_id}@v{v2}",
                )
            )

        return {
            "artifact_id": artifact_id,
            "v1": v1,
            "v2": v2,
            "content_hash_v1": av1.content_hash,
            "content_hash_v2": av2.content_hash,
            "unchanged": unchanged,
            "diff_lines": diff_lines,
        }
