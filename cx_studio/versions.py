"""CX Agent Studio versions resource management."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CxVersion:
    """A point-in-time version snapshot of a CX agent configuration.

    Mirrors the CX Agent Studio versions resource (agent-level).  The
    ``agent_snapshot`` field stores the full config so that the version
    can be used to restore an agent to a previous state without re-fetching
    from the API.
    """

    version_id: str
    display_name: str
    description: str
    created_at: str
    agent_snapshot: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class CxVersionManager:
    """Manage CX Agent Studio versions (agent-level snapshots).

    Versions are stored in memory when no API client is provided, making the
    manager usable offline and in unit tests.  When a real ``CxClient`` is
    injected the ``create_version`` and ``list_versions`` calls are forwarded
    to the CX REST API.

    Args:
        client: Optional ``CxClient`` instance.  When ``None`` the manager
            operates in local-only mode, persisting versions in memory.
    """

    def __init__(self, client: Any = None) -> None:
        self._client = client
        # Local version store: agent_id → list[CxVersion]
        self._local_store: dict[str, list[CxVersion]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_version(
        self,
        agent_id: str,
        description: str,
        config_snapshot: dict[str, Any],
    ) -> CxVersion:
        """Create a new version snapshot for an agent.

        If a CX client is available the version is persisted via the CX REST
        API and the returned version ID is from the server.  Otherwise a
        locally-generated ID is used.

        Args:
            agent_id: Fully-qualified CX agent resource name or local ID.
            description: Human-readable description, e.g. ``"pre-optimization snapshot"``.
            config_snapshot: AutoAgent config dict to snapshot.

        Returns:
            A ``CxVersion`` instance representing the created version.
        """
        version_id = self._generate_version_id(agent_id)
        display_name = f"v{len(self._get_local(agent_id)) + 1}"

        if self._client is not None:
            try:
                api_result = self._client._request(
                    "POST",
                    f"https://ces.googleapis.com/v1/{agent_id}/versions",
                    json_body={
                        "displayName": display_name,
                        "description": description,
                        "agentSnapshot": config_snapshot,
                    },
                )
                if api_result and isinstance(api_result, dict):
                    version_id = api_result.get("name", version_id).split("/")[-1]
                    display_name = api_result.get("displayName", display_name)
            except Exception:
                # Fall back to local mode if API call fails
                pass

        version = CxVersion(
            version_id=version_id,
            display_name=display_name,
            description=description,
            created_at=_utcnow(),
            agent_snapshot=copy.deepcopy(config_snapshot),
            metadata={"agent_id": agent_id},
        )
        self._local_store.setdefault(agent_id, []).append(version)
        return version

    def list_versions(self, agent_id: str) -> list[CxVersion]:
        """List all known versions for an agent.

        When a CX client is available, fetches the version list from the API
        and merges it with any locally-held versions.  Without a client, only
        local versions are returned.

        Args:
            agent_id: Fully-qualified CX agent resource name or local ID.

        Returns:
            List of ``CxVersion`` instances, ordered from oldest to newest.
        """
        local = list(self._get_local(agent_id))

        if self._client is not None:
            try:
                data = self._client._request(
                    "GET",
                    f"https://ces.googleapis.com/v1/{agent_id}/versions",
                )
                if data and isinstance(data, dict):
                    for v in data.get("versions", []):
                        vid = v.get("name", "").split("/")[-1]
                        # Don't duplicate locally-known versions
                        if not any(lv.version_id == vid for lv in local):
                            local.append(
                                CxVersion(
                                    version_id=vid,
                                    display_name=v.get("displayName", vid),
                                    description=v.get("description", ""),
                                    created_at=v.get("createTime", ""),
                                    agent_snapshot={},
                                    metadata={"agent_id": agent_id, "source": "api"},
                                )
                            )
            except Exception:
                pass  # Return local-only list on error

        return local

    def get_version(self, agent_id: str, version_id: str) -> CxVersion | None:
        """Retrieve a specific version by ID.

        Args:
            agent_id: Fully-qualified CX agent resource name or local ID.
            version_id: The version identifier to look up.

        Returns:
            The matching ``CxVersion``, or ``None`` if not found.
        """
        for version in self._get_local(agent_id):
            if version.version_id == version_id:
                return version

        if self._client is not None:
            try:
                data = self._client._request(
                    "GET",
                    f"https://ces.googleapis.com/v1/{agent_id}/versions/{version_id}",
                )
                if data and isinstance(data, dict):
                    return CxVersion(
                        version_id=data.get("name", "").split("/")[-1],
                        display_name=data.get("displayName", version_id),
                        description=data.get("description", ""),
                        created_at=data.get("createTime", ""),
                        agent_snapshot=data.get("agentSnapshot", {}),
                        metadata={"agent_id": agent_id, "source": "api"},
                    )
            except Exception:
                pass

        return None

    def restore_version(self, agent_id: str, version_id: str) -> dict[str, Any]:
        """Restore an agent to a previously snapshotted version.

        When a client is present the CX ``restoreVersion`` long-running
        operation is triggered.  Without a client, the snapshot dict is
        returned directly so callers can apply it manually.

        Args:
            agent_id: Fully-qualified CX agent resource name or local ID.
            version_id: The version identifier to restore.

        Returns:
            Operation result dict with ``"status"`` and, if available,
            the restored ``"agent_snapshot"``.

        Raises:
            ValueError: if the version cannot be found.
        """
        version = self.get_version(agent_id, version_id)
        if version is None:
            raise ValueError(
                f"Version '{version_id}' not found for agent '{agent_id}'."
            )

        if self._client is not None:
            try:
                result = self._client._request(
                    "POST",
                    f"https://ces.googleapis.com/v1/{agent_id}/versions/{version_id}:restore",
                    json_body={},
                )
                return {
                    "status": "restoring",
                    "operation": result,
                    "version_id": version_id,
                    "agent_snapshot": version.agent_snapshot,
                }
            except Exception as exc:
                return {
                    "status": "error",
                    "error": str(exc),
                    "version_id": version_id,
                    "agent_snapshot": version.agent_snapshot,
                }

        # Offline mode — return snapshot for manual application
        return {
            "status": "local_restore",
            "version_id": version_id,
            "agent_snapshot": copy.deepcopy(version.agent_snapshot),
        }

    def create_pre_optimization_snapshot(
        self,
        agent_id: str,
        config: dict[str, Any],
    ) -> CxVersion:
        """Convenience method: snapshot config before an optimization run.

        Creates a version labelled ``"pre-optimization"`` so that the agent
        can be rolled back if the optimization degrades quality.

        Args:
            agent_id: Fully-qualified CX agent resource name or local ID.
            config: Current agent config dict.

        Returns:
            A ``CxVersion`` with the pre-optimization snapshot.
        """
        return self.create_version(
            agent_id=agent_id,
            description="Pre-optimization snapshot — created automatically before optimization.",
            config_snapshot=config,
        )

    def create_post_optimization_snapshot(
        self,
        agent_id: str,
        config: dict[str, Any],
        experiment_id: str,
    ) -> CxVersion:
        """Convenience method: snapshot config after a successful optimization run.

        Tags the version with the experiment ID for traceability.

        Args:
            agent_id: Fully-qualified CX agent resource name or local ID.
            config: Optimized agent config dict.
            experiment_id: Identifier of the optimization experiment.

        Returns:
            A ``CxVersion`` with the post-optimization snapshot.
        """
        version = self.create_version(
            agent_id=agent_id,
            description=(
                f"Post-optimization snapshot — experiment '{experiment_id}'."
            ),
            config_snapshot=config,
        )
        version.metadata["experiment_id"] = experiment_id
        return version

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_local(self, agent_id: str) -> list[CxVersion]:
        """Return the local version list for an agent (read-only view)."""
        return self._local_store.get(agent_id, [])

    @staticmethod
    def _generate_version_id(agent_id: str) -> str:
        """Generate a deterministic version ID from agent_id and current time."""
        import hashlib

        ts = _utcnow().replace(":", "").replace("-", "").replace("+", "").replace(".", "")
        raw = f"{agent_id}-{ts}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]
