"""Connect routes for importing external runtimes into AgentLab workspaces."""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from adapters import (
    AnthropicClaudeAdapter,
    HttpWebhookAdapter,
    OpenAIAgentsAdapter,
    TranscriptAdapter,
    create_connected_workspace,
)

router = APIRouter(prefix="/api/connect", tags=["connect"])


class ConnectImportRequest(BaseModel):
    """Request payload for guided runtime connection."""

    adapter: str = Field(..., pattern="^(openai-agents|anthropic|http|transcript)$")
    path: str | None = None
    url: str | None = None
    file: str | None = None
    output_dir: str = "."
    workspace_name: str | None = None
    runtime_mode: str = Field("mock", pattern="^(mock|live|auto)$")


class ConnectImportResponse(BaseModel):
    """Response payload after creating a connected workspace."""

    adapter: str
    agent_name: str
    workspace_path: str
    config_path: str
    eval_path: str
    adapter_config_path: str
    spec_path: str
    traces_path: str | None = None
    tool_count: int
    guardrail_count: int
    trace_count: int
    eval_case_count: int
    registered_version: int | None = None


@router.get("")
async def connect_catalog() -> dict[str, object]:
    """Return the supported connect adapters for UI and API discovery."""
    return {
        "adapters": [
            {"id": "openai-agents", "label": "OpenAI Agents", "source_field": "path"},
            {"id": "anthropic", "label": "Anthropic", "source_field": "path"},
            {"id": "http", "label": "HTTP", "source_field": "url"},
            {"id": "transcript", "label": "Transcript", "source_field": "file"},
        ],
        "count": 4,
    }


@router.post("/import", response_model=ConnectImportResponse, status_code=201)
async def connect_import(body: ConnectImportRequest, request: Request) -> ConnectImportResponse:
    """Create a workspace from an imported runtime or transcript export."""

    try:
        if body.adapter == "openai-agents":
            if not body.path:
                raise HTTPException(status_code=400, detail="path is required for openai-agents")
            spec = OpenAIAgentsAdapter(body.path).discover()
        elif body.adapter == "anthropic":
            if not body.path:
                raise HTTPException(status_code=400, detail="path is required for anthropic")
            spec = AnthropicClaudeAdapter(body.path).discover()
        elif body.adapter == "http":
            if not body.url:
                raise HTTPException(status_code=400, detail="url is required for http")
            spec = HttpWebhookAdapter(body.url).discover()
        else:
            if not body.file:
                raise HTTPException(status_code=400, detail="file is required for transcript")
            spec = TranscriptAdapter(body.file).discover()

        result = create_connected_workspace(
            spec,
            output_dir=body.output_dir,
            workspace_name=body.workspace_name,
            runtime_mode=body.runtime_mode,
        )

        # Register the imported config with the running server's version manager
        # so it appears immediately in /api/agents and the agent library UI.
        registered_version: int | None = None
        version_manager = getattr(request.app.state, "version_manager", None)
        if version_manager is not None:
            config_path = Path(result.config_path)
            if config_path.exists():
                config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                cv = version_manager.save_version(
                    config,
                    scores={},
                    status="candidate",
                )
                registered_version = cv.version

        response = ConnectImportResponse(**result.to_dict())
        response.registered_version = registered_version
        return response
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
