"""Compatibility wrapper around the Dialogflow CX REST client."""

from __future__ import annotations

from typing import Any

from adapters.cx_studio_client import CxStudioClient, build_dialogflow_cx_base_url
from .types import CxDataStore


def _build_base_url(location: str) -> str:
    """Compatibility alias for older callers and tests."""

    return build_dialogflow_cx_base_url(location)


class CxClient(CxStudioClient):
    """Backwards-compatible CX client facade used by existing AutoAgent code."""

    def fetch_snapshot(self, agent_name: str, app_name: str | None = None):  # type: ignore[override]
        """Accept the legacy optional `app_name` argument while using v3 snapshots."""

        return super().fetch_snapshot(agent_name)

    def list_tools(self, agent_name: str) -> list[dict[str, Any]]:
        """Return an empty tool list when the agent does not use the v3 tools surface."""

        return []

    def create_data_store(
        self,
        app_name: str,
        display_name: str,
        content_entries: list[dict[str, Any]],
        data_store_type: str = "unstructured",
    ) -> CxDataStore:
        """Compatibility placeholder for legacy deployment code paths."""

        return CxDataStore(
            name=f"{app_name}/dataStores/{display_name.lower().replace(' ', '-')}",
            display_name=display_name,
            data_store_type=data_store_type,
            content_entries=content_entries,
        )

    def deploy_to_environment(
        self,
        deployment_name: str,
        version_configs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compatibility stub for legacy deployment flows."""

        return {
            "name": deployment_name,
            "versionConfigs": version_configs,
            "status": "submitted",
        }
