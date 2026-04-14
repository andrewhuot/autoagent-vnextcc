"""Shared publish logic for HTTP and coordinator-worker deploy paths.

The HTTP route in ``api/routes/deploy.py`` and the coordinator
``PlatformPublisherWorker`` both need to turn a deploy request (strategy +
either an existing version or a new config dict) into a ``version``,
``status``, and a human-readable message. Keeping the logic in one place
prevents the two paths from drifting.

The callers remain responsible for their own cross-cutting concerns —
lineage recording, HTTP error shaping, or coordinator artifact emission.
This module only owns the core publish decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class PublishError(ValueError):
    """Raised when a publish request cannot be executed (bad input)."""


@dataclass(frozen=True)
class PublishResult:
    """Return value from :func:`publish_config`.

    ``version`` is the config version that was promoted or deployed; it may
    be ``None`` when the caller asked to promote a canary that does not
    exist. ``strategy`` is ``"canary"``, ``"immediate"``, or ``"promote"``.
    """

    message: str
    version: int | None
    strategy: str
    status: str
    source: str


def publish_config(
    deployer: Any,
    version_manager: Any,
    *,
    strategy: str = "canary",
    version: int | None = None,
    config: dict[str, Any] | None = None,
    scores: dict[str, Any] | None = None,
) -> PublishResult:
    """Publish a config according to ``strategy``.

    The two valid combinations are:

    - ``version`` is provided — promote or canary the saved version.
    - ``config`` is provided — save a new version and publish it.

    When neither is provided the helper tries to promote the current canary
    (``strategy="immediate"``), which mirrors the HTTP fallback behavior.
    """

    normalized_scores: dict[str, Any] = dict(scores or {})
    normalized_strategy = str(strategy or "canary")

    if version is not None:
        if normalized_strategy == "immediate":
            version_manager.promote(version)
            return PublishResult(
                message=f"Promoted v{version:03d} to active (immediate)",
                version=int(version),
                strategy="immediate",
                status="active",
                source="deploy_existing_version",
            )
        version_manager.mark_canary(version)
        return PublishResult(
            message=f"Deployed v{version:03d} as canary",
            version=int(version),
            strategy="canary",
            status="canary",
            source="deploy_existing_version",
        )

    if config is not None:
        if normalized_strategy == "immediate":
            cv = version_manager.save_version(config, normalized_scores, status="active")
            return PublishResult(
                message=f"Deployed v{cv.version:03d} as active (immediate)",
                version=int(cv.version),
                strategy="immediate",
                status="active",
                source="deploy_new_config",
            )
        message = deployer.deploy(config, normalized_scores)
        canary_ver = version_manager.manifest.get("canary_version")
        return PublishResult(
            message=str(message),
            version=int(canary_ver) if canary_ver is not None else None,
            strategy="canary",
            status="canary",
            source="deploy_new_config",
        )

    canary_ver = version_manager.manifest.get("canary_version")
    if canary_ver is None:
        raise PublishError("No config, version, or active canary to deploy")
    if normalized_strategy != "immediate":
        raise PublishError("Provide config or version to deploy")
    version_manager.promote(canary_ver)
    return PublishResult(
        message=f"Promoted canary v{canary_ver:03d} to active",
        version=int(canary_ver),
        strategy="immediate",
        status="active",
        source="promote_current_canary",
    )


__all__ = ["PublishError", "PublishResult", "publish_config"]
