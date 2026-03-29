"""CX Agent Studio API routes — import, export, deploy, widget."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/cx", tags=["cx-studio"])


def _get_workspace_root(request: Request) -> Path:
    """Return the allowed filesystem root for CX preview assets."""
    configured_root = getattr(request.app.state, "cx_workspace_root", None)
    return Path(configured_root or Path.cwd()).resolve()


def _resolve_workspace_file(request: Request, raw_path: str) -> Path:
    """Resolve a file path and ensure it stays within the configured workspace root."""
    workspace_root = _get_workspace_root(request)
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (workspace_root / candidate).resolve()

    if not resolved.is_relative_to(workspace_root):
        raise HTTPException(status_code=400, detail=f"Path escapes workspace root: {raw_path}")

    return resolved


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CxAgentRefPayload(BaseModel):
    project: str
    location: str = "global"
    agent_id: str
    credentials_path: str | None = None

class CxImportRequest(CxAgentRefPayload):
    output_dir: str = "."
    include_test_cases: bool = True

class CxImportResponse(BaseModel):
    config_path: str
    eval_path: str | None = None
    snapshot_path: str
    agent_name: str
    surfaces_mapped: list[str]
    test_cases_imported: int

class CxExportRequest(CxAgentRefPayload):
    config: dict
    snapshot_path: str
    dry_run: bool = False

class CxExportResponse(BaseModel):
    changes: list[dict]
    pushed: bool
    resources_updated: int

class CxDeployRequest(CxAgentRefPayload):
    environment: str = "production"

class CxDeployResponse(BaseModel):
    environment: str
    status: str
    version_info: dict = Field(default_factory=dict)

class CxWidgetRequest(BaseModel):
    project_id: str
    agent_id: str
    location: str = "global"
    language_code: str = "en"
    chat_title: str = "Agent"
    primary_color: str = "#1a73e8"

class CxWidgetResponse(BaseModel):
    html: str

class CxAgentSummary(BaseModel):
    name: str
    display_name: str
    default_language_code: str = "en"
    description: str = ""

class CxPreviewResponse(BaseModel):
    changes: list[dict]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/agents", response_model=list[CxAgentSummary])
async def list_cx_agents(
    project: str,
    location: str = "global",
    credentials_path: str | None = None,
) -> list[CxAgentSummary]:
    """List CX agents in a project."""
    from cx_studio import CxAuth, CxClient
    try:
        auth = CxAuth(credentials_path=credentials_path)
        client = CxClient(auth)
        agents = client.list_agents(project, location)
        return [
            CxAgentSummary(
                name=a.name,
                display_name=a.display_name,
                default_language_code=a.default_language_code,
                description=a.description,
            )
            for a in agents
        ]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/import", response_model=CxImportResponse, status_code=201)
async def import_cx_agent(body: CxImportRequest) -> CxImportResponse:
    """Import a CX agent into AutoAgent format."""
    from cx_studio import CxAuth, CxClient, CxImporter
    from cx_studio.types import CxAgentRef
    try:
        auth = CxAuth(credentials_path=body.credentials_path)
        client = CxClient(auth)
        importer = CxImporter(client)
        ref = CxAgentRef(project=body.project, location=body.location, agent_id=body.agent_id)
        result = importer.import_agent(
            ref,
            output_dir=body.output_dir,
            include_test_cases=body.include_test_cases,
        )
        return CxImportResponse(
            config_path=result.config_path,
            eval_path=result.eval_path,
            snapshot_path=result.snapshot_path,
            agent_name=result.agent_name,
            surfaces_mapped=result.surfaces_mapped,
            test_cases_imported=result.test_cases_imported,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/export", response_model=CxExportResponse)
async def export_cx_agent(body: CxExportRequest) -> CxExportResponse:
    """Export optimized config back to CX Agent Studio."""
    from cx_studio import CxAuth, CxClient, CxExporter
    from cx_studio.types import CxAgentRef
    try:
        auth = CxAuth(credentials_path=body.credentials_path)
        client = CxClient(auth)
        exporter = CxExporter(client)
        ref = CxAgentRef(project=body.project, location=body.location, agent_id=body.agent_id)
        result = exporter.export_agent(
            body.config, ref, body.snapshot_path, dry_run=body.dry_run,
        )
        return CxExportResponse(
            changes=result.changes,
            pushed=result.pushed,
            resources_updated=result.resources_updated,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/deploy", response_model=CxDeployResponse)
async def deploy_cx_agent(body: CxDeployRequest) -> CxDeployResponse:
    """Deploy agent to a CX environment."""
    from cx_studio import CxAuth, CxClient, CxDeployer
    from cx_studio.types import CxAgentRef
    try:
        auth = CxAuth(credentials_path=body.credentials_path)
        client = CxClient(auth)
        deployer = CxDeployer(client)
        ref = CxAgentRef(project=body.project, location=body.location, agent_id=body.agent_id)
        result = deployer.deploy_to_environment(ref, body.environment)
        return CxDeployResponse(
            environment=result.environment,
            status=result.status,
            version_info=result.version_info,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/widget", response_model=CxWidgetResponse)
async def generate_cx_widget(body: CxWidgetRequest) -> CxWidgetResponse:
    """Generate chat-messenger web widget HTML."""
    from cx_studio import CxDeployer, CxAuth, CxClient
    from cx_studio.types import CxWidgetConfig
    widget_config = CxWidgetConfig(
        project_id=body.project_id,
        agent_id=body.agent_id,
        location=body.location,
        language_code=body.language_code,
        chat_title=body.chat_title,
        primary_color=body.primary_color,
    )
    # Widget generation doesn't need real auth
    auth = CxAuth.__new__(CxAuth)
    auth._token = None
    auth._token_expiry = 0.0
    auth._project_id = body.project_id
    auth._credentials_path = None
    client = CxClient.__new__(CxClient)
    client._auth = auth
    client._timeout = 30.0
    client._max_retries = 3
    deployer = CxDeployer(client)
    html = deployer.generate_widget_html(widget_config)
    return CxWidgetResponse(html=html)


@router.get("/status")
async def get_cx_status(
    project: str,
    location: str = "global",
    agent_id: str = "",
    credentials_path: str | None = None,
) -> dict[str, Any]:
    """Get CX agent deployment status."""
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    from cx_studio import CxAuth, CxClient, CxDeployer
    from cx_studio.types import CxAgentRef
    try:
        auth = CxAuth(credentials_path=credentials_path)
        client = CxClient(auth)
        deployer = CxDeployer(client)
        ref = CxAgentRef(project=project, location=location, agent_id=agent_id)
        return deployer.get_deploy_status(ref)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/preview", response_model=CxPreviewResponse)
async def preview_cx_export(
    request: Request,
    config_path: str,
    snapshot_path: str,
) -> CxPreviewResponse:
    """Preview what changes an export would make."""
    import yaml
    from cx_studio import CxExporter, CxAuth, CxClient

    resolved_config_path = _resolve_workspace_file(request, config_path)
    resolved_snapshot_path = _resolve_workspace_file(request, snapshot_path)

    try:
        with resolved_config_path.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid config: {exc}")

    auth = CxAuth.__new__(CxAuth)
    auth._token = None
    auth._token_expiry = 0.0
    auth._project_id = None
    auth._credentials_path = None
    client = CxClient.__new__(CxClient)
    client._auth = auth
    client._timeout = 30.0
    client._max_retries = 3
    exporter = CxExporter(client)
    try:
        changes = exporter.preview_changes(config, str(resolved_snapshot_path))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid snapshot: {exc}")
    return CxPreviewResponse(changes=changes)
