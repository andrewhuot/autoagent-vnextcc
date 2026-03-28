"""Control-plane governance engine wrappers."""

from __future__ import annotations

from dataclasses import dataclass, field

from deployer.release_manager import PromotionRecord, ReleaseManager

from control.permissions import PermissionEngine
from control.profiles import DEV_PROFILE, get_profile
from control.types import ActionDecision, ActionRequest, PermissionProfile


@dataclass
class GovernanceEngine:
    """Governance-as-code control-plane policy evaluator.

    Wraps the ReleaseManager for promotion decisions and the PermissionEngine
    for autonomy boundary enforcement.  The two concerns are kept separate:
    ``evaluate_candidate`` drives the release pipeline; ``check_permission``
    enforces the permission model before any action is attempted.
    """

    release_manager: ReleaseManager
    permission_engine: PermissionEngine = field(
        default_factory=lambda: PermissionEngine(profile=DEV_PROFILE)
    )

    def __post_init__(self) -> None:
        # Ensure permission_engine always has at least the default profile loaded.
        if self.permission_engine._profile is None:
            self.permission_engine.set_profile(DEV_PROFILE)

    # ------------------------------------------------------------------
    # Release pipeline
    # ------------------------------------------------------------------

    def evaluate_candidate(
        self,
        candidate_version: str,
        gate_results: dict[str, bool],
        holdout_score: float,
        slice_results: dict[str, float],
        canary_verdict: str | None = None,
    ) -> PromotionRecord:
        """Evaluate promotion readiness for a release candidate.

        Delegates to ReleaseManager's full pipeline.
        """
        return self.release_manager.run_full_pipeline(
            candidate_version=candidate_version,
            gate_results=gate_results,
            holdout_score=holdout_score,
            slice_results=slice_results,
            canary_verdict=canary_verdict,
        )

    # ------------------------------------------------------------------
    # Permission model
    # ------------------------------------------------------------------

    def check_permission(self, action_request: ActionRequest) -> ActionDecision:
        """Evaluate an ActionRequest against the active permission profile.

        This is the primary entry point for permission checks throughout the
        control plane.  Callers should inspect ``decision.allowed`` before
        proceeding with any side-effectful operation.

        Args:
            action_request: The action that the optimizer (or another
                component) wants to perform.

        Returns:
            An ActionDecision describing whether the action is permitted and
            the reason for that decision.
        """
        return self.permission_engine.evaluate(action_request)

    def set_permission_profile(self, profile_name: str) -> None:
        """Switch the active permission profile by name.

        Looks up the profile from the built-in registry and applies it to the
        internal PermissionEngine.

        Args:
            profile_name: One of "readonly", "dev", "staging", "production",
                or "autonomous".

        Raises:
            KeyError: If the profile name is not recognised.
        """
        profile = get_profile(profile_name)
        self.permission_engine.set_profile(profile)

    def load_permission_profile(self, profile: PermissionProfile) -> None:
        """Apply a custom PermissionProfile to the permission engine.

        Use this when you need a profile that is not in the built-in registry
        (e.g. constructed from YAML configuration).

        Args:
            profile: A fully constructed PermissionProfile instance.
        """
        self.permission_engine.set_profile(profile)
