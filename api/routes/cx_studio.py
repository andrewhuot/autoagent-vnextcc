"""CX Agent Studio API routes — import, export, deploy, widget."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.models import CxExportResponse, CxImportResponse

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

class CxExportRequest(CxAgentRefPayload):
    config: dict
    snapshot_path: str
    dry_run: bool = False


class CxAuthRequest(BaseModel):
    credentials_path: str | None = None


class CxAuthResponse(BaseModel):
    project_id: str | None = None
    auth_type: str
    principal: str | None = None
    credentials_path: str | None = None


class CxDiffRequest(CxAgentRefPayload):
    config: dict
    snapshot_path: str


class CxSyncRequest(CxDiffRequest):
    conflict_strategy: str = "detect"

class CxPreflightRequest(BaseModel):
    config: dict
    export_matrix: dict | None = None


class CxPreflightResponse(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    safe_surfaces: list[str] = Field(default_factory=list)
    lossy_surfaces: list[str] = Field(default_factory=list)
    blocked_surfaces: list[str] = Field(default_factory=list)


class CxDeployRequest(CxAgentRefPayload):
    environment: str = "production"
    strategy: str = "immediate"
    traffic_pct: int = 100


class CxDeployResponse(BaseModel):
    environment: str
    status: str
    version_info: dict = Field(default_factory=dict)
    phase: str = ""
    canary: dict = Field(default_factory=dict)


class CxPromoteRequest(CxAgentRefPayload):
    canary: dict


class CxRollbackRequest(CxAgentRefPayload):
    canary: dict


class CxDeployStatusResponse(BaseModel):
    app: str = ""
    agent: str = ""
    deployments: list[dict] = Field(default_factory=list)
    canary: dict = Field(default_factory=dict)

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

@router.post("/auth", response_model=CxAuthResponse)
async def authenticate_cx(body: CxAuthRequest) -> CxAuthResponse:
    """Validate credentials and return basic auth metadata."""

    from cx_studio import CxAuth

    try:
        auth = CxAuth(credentials_path=body.credentials_path)
        details = auth.describe()
        return CxAuthResponse(**details)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

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
    """Import a CX agent into AgentLab format."""
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
            workspace_path=result.workspace_path,
            portability_report=result.portability_report,
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
            conflicts=result.conflicts,
            export_matrix=result.export_matrix,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/diff", response_model=CxExportResponse)
async def diff_cx_agent(body: CxDiffRequest) -> CxExportResponse:
    """Diff local config changes against the live CX agent."""

    from cx_studio import CxAuth, CxClient, CxExporter
    from cx_studio.types import CxAgentRef

    try:
        auth = CxAuth(credentials_path=body.credentials_path)
        client = CxClient(auth)
        exporter = CxExporter(client)
        ref = CxAgentRef(project=body.project, location=body.location, agent_id=body.agent_id)
        result = exporter.diff_agent(body.config, ref, body.snapshot_path)
        return CxExportResponse(
            changes=result.changes,
            pushed=result.pushed,
            resources_updated=result.resources_updated,
            conflicts=result.conflicts,
            export_matrix=result.export_matrix,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/sync", response_model=CxExportResponse)
async def sync_cx_agent(body: CxSyncRequest) -> CxExportResponse:
    """Synchronize local config changes with the live CX agent."""

    from cx_studio import CxAuth, CxClient, CxExporter
    from cx_studio.types import CxAgentRef

    try:
        auth = CxAuth(credentials_path=body.credentials_path)
        client = CxClient(auth)
        exporter = CxExporter(client)
        ref = CxAgentRef(project=body.project, location=body.location, agent_id=body.agent_id)
        result = exporter.sync_agent(
            body.config,
            ref,
            body.snapshot_path,
            conflict_strategy=body.conflict_strategy,
        )
        return CxExportResponse(
            changes=result.changes,
            pushed=result.pushed,
            resources_updated=result.resources_updated,
            conflicts=result.conflicts,
            export_matrix=result.export_matrix,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/preflight", response_model=CxPreflightResponse)
async def preflight_cx(body: CxPreflightRequest) -> CxPreflightResponse:
    """Run preflight validation before export or deploy."""
    from cx_studio import CxDeployer, CxAuth, CxClient

    auth = CxAuth.__new__(CxAuth)
    auth._token = None
    auth._token_expiry = 0.0
    auth._project_id = None
    auth._credentials_path = None
    client = CxClient.__new__(CxClient)
    client._auth = auth
    client._timeout = 30.0
    client._max_retries = 3
    deployer = CxDeployer(client)
    result = deployer.run_preflight(body.config, body.export_matrix)
    return CxPreflightResponse(
        passed=result.passed,
        errors=result.errors,
        warnings=result.warnings,
        safe_surfaces=result.safe_surfaces,
        lossy_surfaces=result.lossy_surfaces,
        blocked_surfaces=result.blocked_surfaces,
    )


@router.post("/deploy", response_model=CxDeployResponse)
async def deploy_cx_agent(body: CxDeployRequest) -> CxDeployResponse:
    """Deploy agent to a CX environment.

    Supports two strategies:
    - ``immediate``: full deploy to the environment (default)
    - ``canary``: deploy to a canary slice with ``traffic_pct`` traffic
    """
    from cx_studio import CxAuth, CxClient, CxDeployer
    from cx_studio.types import CxAgentRef
    try:
        auth = CxAuth(credentials_path=body.credentials_path)
        client = CxClient(auth)
        deployer = CxDeployer(client)
        ref = CxAgentRef(project=body.project, location=body.location, agent_id=body.agent_id)

        if body.strategy == "canary":
            result, canary = deployer.deploy_canary(
                ref, body.environment, body.traffic_pct,
            )
            return CxDeployResponse(
                environment=result.environment,
                status=result.status,
                version_info=result.version_info,
                phase=canary.phase.value,
                canary=canary.model_dump(),
            )

        result = deployer.deploy_to_environment(ref, body.environment)
        return CxDeployResponse(
            environment=result.environment,
            status=result.status,
            version_info=result.version_info,
            phase="promoted",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/promote", response_model=CxDeployResponse)
async def promote_cx_canary(body: CxPromoteRequest) -> CxDeployResponse:
    """Promote a canary deployment to full traffic."""
    from cx_studio import CxAuth, CxClient, CxDeployer
    from cx_studio.types import CanaryState, CxAgentRef
    try:
        auth = CxAuth(credentials_path=body.credentials_path)
        client = CxClient(auth)
        deployer = CxDeployer(client)
        ref = CxAgentRef(project=body.project, location=body.location, agent_id=body.agent_id)
        canary = CanaryState.model_validate(body.canary)
        result, updated_canary = deployer.promote_canary(ref, canary)
        return CxDeployResponse(
            environment=result.environment,
            status=result.status,
            version_info=result.version_info,
            phase=updated_canary.phase.value,
            canary=updated_canary.model_dump(),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/rollback", response_model=CxDeployResponse)
async def rollback_cx_deploy(body: CxRollbackRequest) -> CxDeployResponse:
    """Rollback a canary or promoted deployment."""
    from cx_studio import CxAuth, CxClient, CxDeployer
    from cx_studio.types import CanaryState, CxAgentRef
    try:
        auth = CxAuth(credentials_path=body.credentials_path)
        client = CxClient(auth)
        deployer = CxDeployer(client)
        ref = CxAgentRef(project=body.project, location=body.location, agent_id=body.agent_id)
        canary = CanaryState.model_validate(body.canary)
        result, updated_canary = deployer.rollback(ref, canary)
        return CxDeployResponse(
            environment=result.environment,
            status=result.status,
            version_info=result.version_info,
            phase=updated_canary.phase.value,
            canary=updated_canary.model_dump(),
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


@router.get("/status", response_model=CxDeployStatusResponse)
async def get_cx_status(
    project: str,
    location: str = "global",
    agent_id: str = "",
    credentials_path: str | None = None,
) -> CxDeployStatusResponse:
    """Get CX agent deployment status with environment versions."""
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    from cx_studio import CxAuth, CxClient, CxDeployer
    from cx_studio.types import CxAgentRef
    try:
        auth = CxAuth(credentials_path=credentials_path)
        client = CxClient(auth)
        deployer = CxDeployer(client)
        ref = CxAgentRef(project=project, location=location, agent_id=agent_id)
        status = deployer.get_deploy_status(ref)
        return CxDeployStatusResponse(
            app=status.get("app", ""),
            agent=status.get("agent", ""),
            deployments=status.get("deployments", []),
        )
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
