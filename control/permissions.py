"""Permission engine for evaluating action requests against grants and profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from control.types import (
    ActionDecision,
    ActionRequest,
    EnvironmentScope,
    PermissionGrant,
    PermissionProfile,
    PermissionTier,
    ResourceScope,
)

# Tier ordering — higher index = more permissive
_TIER_ORDER = [PermissionTier.INSPECT, PermissionTier.MUTATE, PermissionTier.PROMOTE]

# Risk classes that are never considered side-effect-safe for eval replay
_UNSAFE_REPLAY_RISK_CLASSES = {"high", "critical"}

# Action types that are inherently unsafe for eval replay (live side effects)
_UNSAFE_REPLAY_ACTION_TYPES = {"deploy", "apply_mutation", "tool_call"}


class PermissionEngine:
    """Evaluates ActionRequests against a PermissionProfile and explicit grants.

    Decision priority:
    1. Profile-level checks (tier, environment, scope, skill/tool deny/allow).
    2. Explicit per-resource grants (may elevate or narrow access).
    3. Auto-approve / require-human-approval based on risk class.

    An explicit grant for the exact resource + tier combination is sufficient
    to allow an action *only if* the profile max_tier allows that tier.
    """

    def __init__(self, profile: PermissionProfile | None = None) -> None:
        self._profile: PermissionProfile | None = profile
        self._grants: list[PermissionGrant] = []

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_profile(self, profile: PermissionProfile) -> None:
        """Replace the active permission profile."""
        self._profile = profile

    def add_grant(self, grant: PermissionGrant) -> None:
        """Register an explicit permission grant."""
        self._grants.append(grant)

    def remove_grant(self, resource: str, tier: PermissionTier) -> None:
        """Remove all grants for the given resource + tier combination."""
        self._grants = [
            g for g in self._grants
            if not (g.resource == resource and g.tier == tier)
        ]

    def get_active_grants(self) -> list[PermissionGrant]:
        """Return all non-expired grants."""
        return [g for g in self._grants if not g.is_expired()]

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    def evaluate(self, request: ActionRequest) -> ActionDecision:
        """Evaluate an ActionRequest and return an ActionDecision.

        Checks are applied in order; the first failure short-circuits.
        """
        now = datetime.now(timezone.utc).isoformat()

        if self._profile is None:
            return ActionDecision(
                allowed=False,
                reason="No permission profile is configured.",
                request=request,
                timestamp=now,
            )

        # 1. Tier check
        if not self.check_tier(request):
            return ActionDecision(
                allowed=False,
                reason=(
                    f"Tier '{request.tier_required.value}' exceeds profile max tier "
                    f"'{self._profile.max_tier.value}'."
                ),
                request=request,
                timestamp=now,
            )

        # 2. Environment check
        if not self.check_environment(request):
            allowed_envs = [e.value for e in self._profile.allowed_environments]
            return ActionDecision(
                allowed=False,
                reason=(
                    f"Environment '{request.environment.value}' is not in the "
                    f"allowed list: {allowed_envs}."
                ),
                request=request,
                timestamp=now,
            )

        # 3. Resource scope check
        if not self.check_resource_scope(request):
            allowed_scopes = [s.value for s in self._profile.allowed_scopes]
            requested_scope = request.metadata.get("scope")
            return ActionDecision(
                allowed=False,
                reason=(
                    f"Resource scope '{requested_scope}' is not in the allowed "
                    f"scopes: {allowed_scopes}."
                ),
                request=request,
                timestamp=now,
            )

        # 4. Skill / tool allow/deny lists
        if request.action_type == "tool_call":
            if not self.check_tool_allowed(request.resource):
                return ActionDecision(
                    allowed=False,
                    reason=(
                        f"Tool '{request.resource}' is not permitted by the current "
                        "profile (deny list or not in allow list)."
                    ),
                    request=request,
                    timestamp=now,
                )
        else:
            # Treat resource as a skill name for non-tool actions
            if not self.check_skill_allowed(request.resource):
                return ActionDecision(
                    allowed=False,
                    reason=(
                        f"Skill '{request.resource}' is not permitted by the current "
                        "profile (deny list or not in allow list)."
                    ),
                    request=request,
                    timestamp=now,
                )

        # 5. Risk class gating — require human approval
        if request.risk_class in self._profile.require_human_approval_for:
            # Check whether an explicit grant bypasses the requirement
            grant = self._find_matching_grant(request)
            if grant is None:
                return ActionDecision(
                    allowed=False,
                    reason=(
                        f"Risk class '{request.risk_class}' requires explicit human "
                        "approval. No matching grant found."
                    ),
                    request=request,
                    timestamp=now,
                )
            return ActionDecision(
                allowed=True,
                reason=(
                    f"Risk class '{request.risk_class}' approved via explicit grant "
                    f"granted by '{grant.granted_by}'."
                ),
                request=request,
                grant_used=grant,
                timestamp=now,
            )

        # 6. Auto-approve for low-risk classes
        if request.risk_class in self._profile.auto_approve_risk_classes:
            grant = self._find_matching_grant(request)
            return ActionDecision(
                allowed=True,
                reason=(
                    f"Auto-approved: risk class '{request.risk_class}' is in "
                    "auto_approve_risk_classes."
                ),
                request=request,
                grant_used=grant,
                timestamp=now,
            )

        # 7. For all other risk classes, an explicit grant is required
        grant = self._find_matching_grant(request)
        if grant is not None:
            return ActionDecision(
                allowed=True,
                reason=(
                    f"Explicit grant found for resource '{request.resource}' "
                    f"at tier '{request.tier_required.value}'."
                ),
                request=request,
                grant_used=grant,
                timestamp=now,
            )

        return ActionDecision(
            allowed=False,
            reason=(
                f"No explicit grant for resource '{request.resource}' at tier "
                f"'{request.tier_required.value}' with risk class "
                f"'{request.risk_class}'."
            ),
            request=request,
            timestamp=now,
        )

    # ------------------------------------------------------------------
    # Individual checks (also usable standalone)
    # ------------------------------------------------------------------

    def check_tier(self, request: ActionRequest) -> bool:
        """Return True if the required tier is within the profile's max tier."""
        if self._profile is None:
            return False
        required_idx = _TIER_ORDER.index(request.tier_required)
        max_idx = _TIER_ORDER.index(self._profile.max_tier)
        return required_idx <= max_idx

    def check_environment(self, request: ActionRequest) -> bool:
        """Return True if the target environment is allowed by the profile."""
        if self._profile is None:
            return False
        return request.environment in self._profile.allowed_environments

    def check_resource_scope(self, request: ActionRequest) -> bool:
        """Return True if the resource scope (if specified) is allowed by the profile.

        If no scope is specified in request metadata the check passes.
        """
        if self._profile is None:
            return False
        scope_value = request.metadata.get("scope")
        if scope_value is None:
            return True
        try:
            scope = ResourceScope(scope_value)
        except ValueError:
            return False
        return scope in self._profile.allowed_scopes

    def check_skill_allowed(self, skill_name: str) -> bool:
        """Return True if the skill is permitted by the profile.

        Deny list takes precedence over allow list.
        """
        if self._profile is None:
            return False
        if skill_name in self._profile.skill_denylist:
            return False
        if self._profile.skill_allowlist is None:
            return True
        return skill_name in self._profile.skill_allowlist

    def check_tool_allowed(self, tool_name: str) -> bool:
        """Return True if the tool is permitted by the profile.

        Deny list takes precedence over allow list.
        """
        if self._profile is None:
            return False
        if tool_name in self._profile.tool_denylist:
            return False
        if self._profile.tool_allowlist is None:
            return True
        return tool_name in self._profile.tool_allowlist

    def is_side_effect_safe(self, request: ActionRequest) -> bool:
        """Return True if this action is safe to replay in an eval context.

        Production environment actions, high/critical risk classes, and
        inherently side-effectful action types are considered unsafe.
        """
        if request.environment == EnvironmentScope.PRODUCTION:
            return False
        if request.risk_class in _UNSAFE_REPLAY_RISK_CLASSES:
            return False
        if request.action_type in _UNSAFE_REPLAY_ACTION_TYPES:
            scope_value = request.metadata.get("scope")
            if scope_value in (
                ResourceScope.SECRET.value,
                ResourceScope.DEPLOYMENT.value,
                ResourceScope.HIGH_RISK_BUSINESS.value,
            ):
                return False
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_matching_grant(
        self, request: ActionRequest
    ) -> PermissionGrant | None:
        """Return the first active, non-expired grant that matches the request."""
        for grant in self.get_active_grants():
            if grant.resource != request.resource:
                continue
            required_idx = _TIER_ORDER.index(request.tier_required)
            grant_idx = _TIER_ORDER.index(grant.tier)
            if grant_idx < required_idx:
                continue
            if grant.environment != request.environment:
                continue
            return grant
        return None
