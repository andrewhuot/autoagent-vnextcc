"""Types for the autonomy boundaries and permission model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class PermissionTier(str, Enum):
    """Autonomy tier controlling what actions are permitted."""

    INSPECT = "inspect"      # Read-only: observe and report
    MUTATE = "mutate"        # Propose and test changes in non-production
    PROMOTE = "promote"      # Deploy to production


class ResourceScope(str, Enum):
    """Categories of resource access that carry distinct risk profiles."""

    FILE_WRITE = "file_write"
    NETWORK = "network"
    SECRET = "secret"
    DEPLOYMENT = "deployment"
    HIGH_RISK_BUSINESS = "high_risk_business"


class EnvironmentScope(str, Enum):
    """Deployment environment tier."""

    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass
class PermissionGrant:
    """A single granted permission for a resource at a tier."""

    resource: str
    tier: PermissionTier
    scope: ResourceScope | None = None
    environment: EnvironmentScope = EnvironmentScope.DEV
    granted_by: str = "system"
    granted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    expires_at: str | None = None
    conditions: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Return True if this grant has passed its expiry timestamp."""
        if self.expires_at is None:
            return False
        now = datetime.now(timezone.utc).isoformat()
        return now > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "tier": self.tier.value,
            "scope": self.scope.value if self.scope is not None else None,
            "environment": self.environment.value,
            "granted_by": self.granted_by,
            "granted_at": self.granted_at,
            "expires_at": self.expires_at,
            "conditions": self.conditions,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PermissionGrant":
        return cls(
            resource=d["resource"],
            tier=PermissionTier(d["tier"]),
            scope=ResourceScope(d["scope"]) if d.get("scope") is not None else None,
            environment=EnvironmentScope(d.get("environment", EnvironmentScope.DEV.value)),
            granted_by=d.get("granted_by", "system"),
            granted_at=d.get("granted_at", ""),
            expires_at=d.get("expires_at"),
            conditions=d.get("conditions", {}),
        )


@dataclass
class ActionRequest:
    """A request to perform an action that requires permission evaluation."""

    action_type: str  # e.g. "apply_mutation", "deploy", "eval_replay", "tool_call"
    resource: str     # Target resource: skill name, tool name, env name, etc.
    tier_required: PermissionTier
    environment: EnvironmentScope = EnvironmentScope.DEV
    risk_class: str = "low"  # low, medium, high, critical
    metadata: dict[str, Any] = field(default_factory=dict)
    requestor: str = "optimizer"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "resource": self.resource,
            "tier_required": self.tier_required.value,
            "environment": self.environment.value,
            "risk_class": self.risk_class,
            "metadata": self.metadata,
            "requestor": self.requestor,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ActionRequest":
        return cls(
            action_type=d["action_type"],
            resource=d["resource"],
            tier_required=PermissionTier(d["tier_required"]),
            environment=EnvironmentScope(d.get("environment", EnvironmentScope.DEV.value)),
            risk_class=d.get("risk_class", "low"),
            metadata=d.get("metadata", {}),
            requestor=d.get("requestor", "optimizer"),
        )


@dataclass
class ActionDecision:
    """The outcome of evaluating an ActionRequest against the permission model."""

    allowed: bool
    reason: str
    request: ActionRequest
    grant_used: PermissionGrant | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "request": self.request.to_dict(),
            "grant_used": self.grant_used.to_dict() if self.grant_used is not None else None,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ActionDecision":
        return cls(
            allowed=d["allowed"],
            reason=d["reason"],
            request=ActionRequest.from_dict(d["request"]),
            grant_used=(
                PermissionGrant.from_dict(d["grant_used"])
                if d.get("grant_used") is not None
                else None
            ),
            timestamp=d.get("timestamp", ""),
        )


@dataclass
class PermissionProfile:
    """A named bundle of permission settings applied to the optimizer agent."""

    name: str         # readonly, dev, staging, production, autonomous
    description: str
    max_tier: PermissionTier
    allowed_environments: list[EnvironmentScope]
    allowed_scopes: list[ResourceScope]
    skill_allowlist: list[str] | None = None  # None = all allowed
    skill_denylist: list[str] = field(default_factory=list)
    tool_allowlist: list[str] | None = None   # None = all allowed
    tool_denylist: list[str] = field(default_factory=list)
    auto_approve_risk_classes: list[str] = field(default_factory=lambda: ["low"])
    require_human_approval_for: list[str] = field(default_factory=lambda: ["critical"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "max_tier": self.max_tier.value,
            "allowed_environments": [e.value for e in self.allowed_environments],
            "allowed_scopes": [s.value for s in self.allowed_scopes],
            "skill_allowlist": self.skill_allowlist,
            "skill_denylist": self.skill_denylist,
            "tool_allowlist": self.tool_allowlist,
            "tool_denylist": self.tool_denylist,
            "auto_approve_risk_classes": self.auto_approve_risk_classes,
            "require_human_approval_for": self.require_human_approval_for,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PermissionProfile":
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            max_tier=PermissionTier(d["max_tier"]),
            allowed_environments=[
                EnvironmentScope(e) for e in d.get("allowed_environments", [])
            ],
            allowed_scopes=[
                ResourceScope(s) for s in d.get("allowed_scopes", [])
            ],
            skill_allowlist=d.get("skill_allowlist"),
            skill_denylist=d.get("skill_denylist", []),
            tool_allowlist=d.get("tool_allowlist"),
            tool_denylist=d.get("tool_denylist", []),
            auto_approve_risk_classes=d.get("auto_approve_risk_classes", ["low"]),
            require_human_approval_for=d.get("require_human_approval_for", ["critical"]),
        )
