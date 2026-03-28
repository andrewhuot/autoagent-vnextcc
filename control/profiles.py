"""Built-in permission profiles for common deployment scenarios."""

from __future__ import annotations

from control.types import (
    EnvironmentScope,
    PermissionProfile,
    PermissionTier,
    ResourceScope,
)

# ---------------------------------------------------------------------------
# READONLY — Inspection only, no mutations or deployments
# ---------------------------------------------------------------------------

READONLY_PROFILE = PermissionProfile(
    name="readonly",
    description=(
        "Read-only inspection profile. The agent may observe metrics, "
        "read configs, and report findings but cannot propose or apply "
        "any changes."
    ),
    max_tier=PermissionTier.INSPECT,
    allowed_environments=[
        EnvironmentScope.DEV,
        EnvironmentScope.STAGING,
        EnvironmentScope.PRODUCTION,
    ],
    allowed_scopes=[],  # No resource scopes permitted
    auto_approve_risk_classes=["low"],
    require_human_approval_for=["medium", "high", "critical"],
)

# ---------------------------------------------------------------------------
# DEV — Mutations in dev only, auto-approve low-risk
# ---------------------------------------------------------------------------

DEV_PROFILE = PermissionProfile(
    name="dev",
    description=(
        "Development profile. The agent can propose and test mutations "
        "in the dev environment only. Low-risk actions are auto-approved; "
        "medium/high/critical require explicit human grants."
    ),
    max_tier=PermissionTier.MUTATE,
    allowed_environments=[EnvironmentScope.DEV],
    allowed_scopes=[
        ResourceScope.FILE_WRITE,
        ResourceScope.NETWORK,
    ],
    auto_approve_risk_classes=["low"],
    require_human_approval_for=["critical"],
)

# ---------------------------------------------------------------------------
# STAGING — Mutations in dev + staging, manual approve medium+
# ---------------------------------------------------------------------------

STAGING_PROFILE = PermissionProfile(
    name="staging",
    description=(
        "Staging profile. The agent can propose and test mutations in "
        "dev and staging environments. Medium and above risk classes "
        "require explicit human approval."
    ),
    max_tier=PermissionTier.MUTATE,
    allowed_environments=[EnvironmentScope.DEV, EnvironmentScope.STAGING],
    allowed_scopes=[
        ResourceScope.FILE_WRITE,
        ResourceScope.NETWORK,
        ResourceScope.DEPLOYMENT,
    ],
    auto_approve_risk_classes=["low"],
    require_human_approval_for=["high", "critical"],
)

# ---------------------------------------------------------------------------
# PRODUCTION — Full access, manual approve high+critical
# ---------------------------------------------------------------------------

PRODUCTION_PROFILE = PermissionProfile(
    name="production",
    description=(
        "Production profile. Full access to all environments and resource "
        "scopes. High and critical risk actions require explicit human "
        "approval; low and medium are auto-approved."
    ),
    max_tier=PermissionTier.PROMOTE,
    allowed_environments=[
        EnvironmentScope.DEV,
        EnvironmentScope.STAGING,
        EnvironmentScope.PRODUCTION,
    ],
    allowed_scopes=[
        ResourceScope.FILE_WRITE,
        ResourceScope.NETWORK,
        ResourceScope.SECRET,
        ResourceScope.DEPLOYMENT,
        ResourceScope.HIGH_RISK_BUSINESS,
    ],
    auto_approve_risk_classes=["low", "medium"],
    require_human_approval_for=["high", "critical"],
)

# ---------------------------------------------------------------------------
# AUTONOMOUS — Auto-approve up to medium risk in dev + staging
# ---------------------------------------------------------------------------

AUTONOMOUS_PROFILE = PermissionProfile(
    name="autonomous",
    description=(
        "Autonomous profile. The agent can self-approve up to medium-risk "
        "mutations in dev and staging. High and critical always require "
        "an explicit human grant. Production promotions are not permitted."
    ),
    max_tier=PermissionTier.MUTATE,
    allowed_environments=[EnvironmentScope.DEV, EnvironmentScope.STAGING],
    allowed_scopes=[
        ResourceScope.FILE_WRITE,
        ResourceScope.NETWORK,
        ResourceScope.DEPLOYMENT,
    ],
    auto_approve_risk_classes=["low", "medium"],
    require_human_approval_for=["high", "critical"],
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_PROFILES: dict[str, PermissionProfile] = {
    p.name: p
    for p in [
        READONLY_PROFILE,
        DEV_PROFILE,
        STAGING_PROFILE,
        PRODUCTION_PROFILE,
        AUTONOMOUS_PROFILE,
    ]
}


def get_profile(name: str) -> PermissionProfile:
    """Return a built-in profile by name.

    Raises KeyError if the name is not recognised.
    """
    try:
        return _PROFILES[name]
    except KeyError:
        available = sorted(_PROFILES.keys())
        raise KeyError(
            f"Unknown permission profile '{name}'. "
            f"Available profiles: {available}"
        ) from None


def list_profiles() -> list[PermissionProfile]:
    """Return all built-in permission profiles."""
    return list(_PROFILES.values())
