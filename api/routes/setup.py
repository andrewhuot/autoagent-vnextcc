"""Setup and onboarding overview endpoints."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from cli.mcp_setup import _client_specs, _has_autoagent_entry
from cli.mode import summarize_mode_state
from cli.workspace import discover_workspace

router = APIRouter(prefix="/api/setup", tags=["setup"])


def _safe_sqlite_table_count(path: Path) -> int | None:
    """Return the total table row count for a SQLite database when readable."""
    if not path.exists():
        return None

    try:
        with sqlite3.connect(str(path)) as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            total = 0
            for table in tables:
                try:
                    total += int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
                except sqlite3.Error:
                    continue
            return total
    except sqlite3.Error:
        return None


@router.get("/overview")
async def get_setup_overview() -> dict[str, Any]:
    """Summarize workspace, doctor, mode, and MCP readiness for onboarding."""
    workspace = discover_workspace()
    mode_summary = summarize_mode_state("autoagent.yaml")

    workspace_path = workspace.root if workspace is not None else Path.cwd()
    data_store_paths = {
        "conversations": workspace_path / "conversations.db",
        "optimizer_memory": workspace_path / "optimizer_memory.db",
        "traces": workspace_path / ".autoagent" / "traces.db",
        "experiments": workspace_path / ".autoagent" / "experiments.db",
        "transcript_reports": workspace_path / ".autoagent" / "intelligence_reports.json",
    }

    data_stores = []
    for name, path in data_store_paths.items():
        table_count = _safe_sqlite_table_count(path) if path.suffix == ".db" else None
        data_stores.append(
            {
                "name": name,
                "path": str(path),
                "exists": path.exists(),
                "row_count": table_count,
            }
        )

    api_keys = []
    for env_var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        api_keys.append({"name": env_var, "configured": bool(os.environ.get(env_var))})

    mcp_clients = []
    for name, spec in sorted(_client_specs().items()):
        config_path = spec.path_factory()
        mcp_clients.append(
            {
                "name": name,
                "configured": _has_autoagent_entry(spec),
                "path": str(config_path),
            }
        )

    issues = []
    if workspace is None:
        issues.append("No AutoAgent workspace found yet.")
    if mode_summary["effective_mode"] == "mock":
        issues.append("CLI is currently running in mock mode.")
    if not any(item["configured"] for item in api_keys):
        issues.append("No provider API keys are configured.")
    if not any(item["configured"] for item in mcp_clients):
        issues.append("No MCP client is configured for AutoAgent.")

    return {
        "workspace": {
            "found": workspace is not None,
            "path": str(workspace.root) if workspace is not None else None,
            "label": workspace.workspace_label if workspace is not None else None,
            "runtime_config_path": (
                str(workspace.runtime_config_path)
                if workspace is not None
                else str((Path.cwd() / "autoagent.yaml").resolve())
            ),
            "active_config_version": (
                workspace.metadata.active_config_version if workspace is not None else None
            ),
        },
        "doctor": {
            "effective_mode": mode_summary["effective_mode"],
            "preferred_mode": mode_summary["preferred_mode"],
            "mode_source": mode_summary["mode_source"],
            "message": mode_summary["message"],
            "providers": mode_summary["providers"],
            "api_keys": api_keys,
            "data_stores": data_stores,
            "issues": issues,
        },
        "mcp_clients": mcp_clients,
        "recommended_commands": [
            "autoagent init",
            "autoagent doctor",
            "autoagent mode show",
            "autoagent mcp status",
        ],
    }
