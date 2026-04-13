"""Deploy endpoints — deploy configs, check status, rollback."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from pydantic import BaseModel

from api.models import (
    DeployRequest,
    DeployResponse,
    DeployStatusResponse,
    DeployStrategy,
)


class PromoteRequest(BaseModel):
    """Optional body for the promote endpoint."""
    version: int | None = None
    attempt_id: str | None = None


class RollbackRequest(BaseModel):
    """Optional body for the rollback endpoint."""
    attempt_id: str | None = None


router = APIRouter(prefix="/api/deploy", tags=["deploy"])


def _deploy_context(request: Request) -> tuple[Any, Any]:
    """Return deployer/version manager after refreshing disk-backed versions.

    WHY: Build and Workbench can materialize candidate configs through a
    separate version manager. Deploy must see those fresh versions before
    status, canary, promote, or rollback actions.
    """
    deployer = request.app.state.deployer
    vm = request.app.state.version_manager
    if hasattr(vm, "reload"):
        vm.reload()
    deployer.version_manager = vm
    if hasattr(deployer, "canary_manager"):
        deployer.canary_manager.version_manager = vm
    return deployer, vm


def _record_lineage(
    request: Request,
    event_type: str,
    *,
    attempt_id: str | None,
    version: int | None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append a lineage event if the store is wired and we know the attempt."""
    lineage = getattr(request.app.state, "improvement_lineage", None)
    if lineage is None or not attempt_id:
        return
    try:
        lineage.record(
            attempt_id,
            event_type,
            version=version,
            payload=payload or {},
        )
    except Exception:
        pass


def _resolve_attempt_id(request: Request, explicit: str | None) -> str | None:
    """Fall back to the most recent optimizer attempt when the caller omits one.

    This keeps existing CLI and UI flows (which don't yet pass ``attempt_id``)
    still produce lineage rows automatically.
    """
    if explicit:
        return explicit
    memory = getattr(request.app.state, "optimization_memory", None)
    if memory is None:
        return None
    try:
        recent = memory.recent(limit=1)
    except Exception:
        return None
    return recent[0].attempt_id if recent else None


@router.post("", response_model=DeployResponse, status_code=201)
async def deploy_config(body: DeployRequest, request: Request) -> DeployResponse:
    """Deploy a config version using the specified strategy."""
    deployer, vm = _deploy_context(request)
    attempt_id = _resolve_attempt_id(request, body.attempt_id)

    if body.version is not None:
        # Deploy an existing saved version instead of duplicating it.
        try:
            if body.strategy == DeployStrategy.immediate:
                vm.promote(body.version)
            else:
                vm.mark_canary(body.version)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        event_type = "promote" if body.strategy == DeployStrategy.immediate else "deploy_canary"
        _record_lineage(
            request,
            event_type,
            attempt_id=attempt_id,
            version=body.version,
            payload={"source": "deploy_existing_version"},
        )
        if body.strategy == DeployStrategy.immediate:
            return DeployResponse(
                message=f"Promoted v{body.version:03d} to active (immediate)",
                version=body.version,
                strategy="immediate",
            )
        return DeployResponse(
            message=f"Deployed v{body.version:03d} as canary",
            version=body.version,
            strategy="canary",
        )

    if body.config is not None:
        # Deploy a new config dict
        scores = body.scores or {}
        if body.strategy == DeployStrategy.immediate:
            cv = vm.save_version(body.config, scores, status="active")
            _record_lineage(
                request,
                "promote",
                attempt_id=attempt_id,
                version=cv.version,
                payload={"source": "deploy_new_config", "scores": scores},
            )
            return DeployResponse(
                message=f"Deployed v{cv.version:03d} as active (immediate)",
                version=cv.version,
                strategy="immediate",
            )
        else:
            msg = deployer.deploy(body.config, scores)
            canary_ver = vm.manifest.get("canary_version")
            _record_lineage(
                request,
                "deploy_canary",
                attempt_id=attempt_id,
                version=canary_ver,
                payload={"source": "deploy_new_config", "scores": scores},
            )
            return DeployResponse(
                message=msg,
                version=canary_ver,
                strategy="canary",
            )

    # No config and no version — try to promote current canary
    canary_ver = vm.manifest.get("canary_version")
    if canary_ver is None:
        raise HTTPException(status_code=400, detail="No config, version, or active canary to deploy")

    if body.strategy == DeployStrategy.immediate:
        vm.promote(canary_ver)
        _record_lineage(
            request,
            "promote",
            attempt_id=attempt_id,
            version=canary_ver,
            payload={"source": "promote_current_canary"},
        )
        return DeployResponse(
            message=f"Promoted canary v{canary_ver:03d} to active",
            version=canary_ver,
            strategy="immediate",
        )

    raise HTTPException(status_code=400, detail="Provide config or version to deploy")


@router.get("/status", response_model=DeployStatusResponse)
async def get_deploy_status(request: Request) -> DeployStatusResponse:
    """Get current deployment status including canary info."""
    deployer, _vm = _deploy_context(request)
    status = deployer.status()

    canary_status: dict[str, Any] | None = None
    canary_ver = status.get("canary_version")
    if canary_ver is not None:
        cs = deployer.canary_manager.check_canary()
        canary_status = {
            "is_active": cs.is_active,
            "canary_version": cs.canary_version,
            "baseline_version": cs.baseline_version,
            "canary_conversations": cs.canary_conversations,
            "canary_success_rate": cs.canary_success_rate,
            "baseline_success_rate": cs.baseline_success_rate,
            "started_at": cs.started_at,
            "verdict": cs.verdict,
        }

    return DeployStatusResponse(
        active_version=status.get("active_version"),
        canary_version=status.get("canary_version"),
        total_versions=status.get("total_versions", 0),
        canary_status=canary_status,
        history=status.get("history", []),
    )


@router.post("/promote", response_model=DeployResponse)
async def promote_canary(request: Request, body: PromoteRequest | None = None) -> DeployResponse:
    """Promote the current canary (or a specific version) to active."""
    _deployer, vm = _deploy_context(request)

    target = body.version if body else None
    if target is None:
        target = vm.manifest.get("canary_version")
    if target is None:
        raise HTTPException(status_code=400, detail="No active canary to promote and no version specified")

    try:
        vm.promote(target)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    _record_lineage(
        request,
        "promote",
        attempt_id=_resolve_attempt_id(request, body.attempt_id if body else None),
        version=target,
        payload={"source": "promote_endpoint"},
    )
    return DeployResponse(
        message=f"Promoted v{target:03d} to active",
        version=target,
        strategy="promote",
    )


@router.post("/rollback", response_model=DeployResponse)
async def rollback_canary(request: Request, body: RollbackRequest | None = None) -> DeployResponse:
    """Rollback the current canary deployment."""
    _deployer, vm = _deploy_context(request)
    canary_ver = vm.manifest.get("canary_version")
    if canary_ver is None:
        raise HTTPException(status_code=400, detail="No active canary to rollback")

    try:
        vm.rollback(canary_ver)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    _record_lineage(
        request,
        "rollback",
        attempt_id=_resolve_attempt_id(request, body.attempt_id if body else None),
        version=canary_ver,
        payload={"source": "rollback_endpoint"},
    )
    return DeployResponse(
        message=f"Rolled back canary v{canary_ver:03d}",
        version=canary_ver,
        strategy="rollback",
    )
