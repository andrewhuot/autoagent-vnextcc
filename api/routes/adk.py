"""ADK (Agent Development Kit) API routes — import, export, deploy."""
from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from adk import AdkImporter, AdkExporter, AdkDeployer
from adk.parser import parse_agent_directory
from api.models import AdkExportResponse, AdkImportResponse

router = APIRouter(prefix="/api/adk", tags=["adk"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AdkImportRequest(BaseModel):
    path: str
    output_dir: str = "."

class AdkExportRequest(BaseModel):
    config: dict
    snapshot_path: str
    output_dir: str
    dry_run: bool = False

class AdkDeployRequest(BaseModel):
    path: str
    target: str  # "cloud-run" or "vertex-ai"
    project: str
    region: str = "us-central1"

class AdkDeployResponse(BaseModel):
    target: str
    url: str
    status: str
    deployment_info: dict = Field(default_factory=dict)

class AdkStatusResponse(BaseModel):
    agent_name: str
    model: str
    tools_count: int
    sub_agents: list[str]
    has_config: bool

class AdkDiffResponse(BaseModel):
    changes: list[dict]
    diff: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/import", response_model=AdkImportResponse, status_code=201)
async def import_adk_agent(body: AdkImportRequest, request: Request) -> AdkImportResponse:
    """Import an ADK agent from local directory."""
    try:
        importer = AdkImporter()
        result = importer.import_agent(
            agent_path=body.path,
            output_dir=body.output_dir,
        )

        # Register the imported config with the running server's version manager
        version_manager = getattr(request.app.state, "version_manager", None)
        if version_manager is not None and result.config_path:
            config_path = Path(result.config_path)
            if config_path.exists():
                config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                version_manager.save_version(config, scores={}, status="candidate")

        return AdkImportResponse(
            config_path=result.config_path,
            snapshot_path=result.snapshot_path,
            agent_name=result.agent_name,
            surfaces_mapped=result.surfaces_mapped,
            tools_imported=result.tools_imported,
            portability_report=result.portability_report,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/export", response_model=AdkExportResponse)
async def export_adk_agent(body: AdkExportRequest) -> AdkExportResponse:
    """Export optimized config back to ADK source."""
    try:
        exporter = AdkExporter()
        result = exporter.export_agent(
            config=body.config,
            snapshot_path=body.snapshot_path,
            output_dir=body.output_dir,
            dry_run=body.dry_run,
        )
        return AdkExportResponse(
            output_path=result.output_path,
            changes=result.changes,
            files_modified=result.files_modified,
            export_matrix=result.export_matrix,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/deploy", response_model=AdkDeployResponse)
async def deploy_adk_agent(body: AdkDeployRequest) -> AdkDeployResponse:
    """Deploy ADK agent to Cloud Run or Vertex AI."""
    try:
        if body.target not in ["cloud-run", "vertex-ai"]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid target: {body.target}. Must be 'cloud-run' or 'vertex-ai'."
            )
        deployer = AdkDeployer(project=body.project, region=body.region)
        if body.target == "cloud-run":
            result = deployer.deploy_to_cloud_run(body.path)
        else:
            result = deployer.deploy_to_vertex_ai(body.path)
        return AdkDeployResponse(
            target=result.target,
            url=result.url,
            status=result.status,
            deployment_info=result.deployment_info,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/status", response_model=dict)
async def get_adk_status(path: str) -> dict:
    """Get agent structure summary."""
    from pathlib import Path
    try:
        if not path:
            raise HTTPException(status_code=400, detail="path is required")
        tree = parse_agent_directory(Path(path))
        return {
            "agent": {
                "name": tree.agent.name,
                "model": tree.agent.model or "gemini-2.0-flash",
                "tools": [{"name": t, "description": ""} for t in tree.agent.tools],
                "sub_agents": [{"name": sa.agent.name, "tools": sa.agent.tools} for sa in tree.sub_agents],
                "has_config": bool(tree.agent.generate_config),
            }
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/diff", response_model=AdkDiffResponse)
async def preview_adk_diff(config_path: str, snapshot_path: str) -> AdkDiffResponse:
    """Preview export changes."""
    import yaml
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid config: {exc}")

    try:
        exporter = AdkExporter()
        changes = exporter.preview_changes(config, snapshot_path)
        # Generate a simple diff string from changes
        diff_lines = []
        for change in changes:
            action = change.get("action", "modified")
            file = change.get("file", "unknown")
            field = change.get("field", "unknown")
            diff_lines.append(f"{action}: {file} -> {field}")
        diff = "\n".join(diff_lines) if diff_lines else None
        return AdkDiffResponse(changes=changes, diff=diff)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
