"""Deploy endpoints — deploy configs, check status, rollback."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from api.models import (
    DeployRequest,
    DeployResponse,
    DeployStatusResponse,
    DeployStrategy,
)

router = APIRouter(prefix="/api/deploy", tags=["deploy"])


@router.post("", response_model=DeployResponse, status_code=201)
async def deploy_config(body: DeployRequest, request: Request) -> DeployResponse:
    """Deploy a config version using the specified strategy."""
    deployer = request.app.state.deployer
    vm = request.app.state.version_manager

    if body.strategy == DeployStrategy.immediate and body.version is not None:
        # Promote an existing version directly to active
        try:
            vm.promote(body.version)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return DeployResponse(
            message=f"Promoted v{body.version:03d} to active (immediate)",
            version=body.version,
            strategy="immediate",
        )

    if body.config is not None:
        # Deploy a new config dict
        scores = body.scores or {}
        if body.strategy == DeployStrategy.immediate:
            cv = vm.save_version(body.config, scores, status="active")
            return DeployResponse(
                message=f"Deployed v{cv.version:03d} as active (immediate)",
                version=cv.version,
                strategy="immediate",
            )
        else:
            msg = deployer.deploy(body.config, scores)
            canary_ver = vm.manifest.get("canary_version")
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
        return DeployResponse(
            message=f"Promoted canary v{canary_ver:03d} to active",
            version=canary_ver,
            strategy="immediate",
        )

    raise HTTPException(status_code=400, detail="Provide config or version to deploy")


@router.get("/status", response_model=DeployStatusResponse)
async def get_deploy_status(request: Request) -> DeployStatusResponse:
    """Get current deployment status including canary info."""
    deployer = request.app.state.deployer
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


@router.post("/rollback", response_model=DeployResponse)
async def rollback_canary(request: Request) -> DeployResponse:
    """Rollback the current canary deployment."""
    vm = request.app.state.version_manager
    canary_ver = vm.manifest.get("canary_version")
    if canary_ver is None:
        raise HTTPException(status_code=400, detail="No active canary to rollback")

    try:
        vm.rollback(canary_ver)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return DeployResponse(
        message=f"Rolled back canary v{canary_ver:03d}",
        version=canary_ver,
        strategy="rollback",
    )
