"""Trust tier definitions and evaluation for skill packages."""

from __future__ import annotations

from enum import Enum
from typing import Optional


class TrustTier(str, Enum):
    UNVERIFIED = "unverified"
    COMMUNITY_TESTED = "community_tested"
    BENCHMARK_VALIDATED = "benchmark_validated"
    ENTERPRISE_CERTIFIED = "enterprise_certified"


# Ordered list from lowest to highest trust
_TIER_ORDER = [
    TrustTier.UNVERIFIED,
    TrustTier.COMMUNITY_TESTED,
    TrustTier.BENCHMARK_VALIDATED,
    TrustTier.ENTERPRISE_CERTIFIED,
]


class TrustEvaluator:
    """Evaluates and manages trust tiers for skill packages."""

    def __init__(self) -> None:
        # package_name -> TrustTier
        self._tiers: dict[str, TrustTier] = {}
        # package_name -> list of evidence dicts
        self._evidence: dict[str, list[dict]] = {}

    def evaluate(self, package: dict) -> TrustTier:
        """Derive a TrustTier from package metadata.

        Heuristic rules (applied in order, most demanding first):
        - Has 'enterprise_cert' evidence key → ENTERPRISE_CERTIFIED
        - Has benchmark_badges list with entries → BENCHMARK_VALIDATED
        - Has signature AND community_reviews > 0 → COMMUNITY_TESTED
        - Everything else → UNVERIFIED
        """
        name = package.get("name", "")

        # Use stored override if present
        if name in self._tiers:
            return self._tiers[name]

        badges = package.get("benchmark_badges", [])
        signature = package.get("signature")
        community_reviews = package.get("community_reviews", 0)
        enterprise_cert = package.get("enterprise_cert", False)

        if enterprise_cert:
            return TrustTier.ENTERPRISE_CERTIFIED
        if badges:
            return TrustTier.BENCHMARK_VALIDATED
        if signature and community_reviews > 0:
            return TrustTier.COMMUNITY_TESTED
        return TrustTier.UNVERIFIED

    def promote(
        self, package_name: str, to_tier: TrustTier, evidence: dict
    ) -> bool:
        """Promote a package to a higher trust tier, recording evidence.

        Returns False if the target tier is not higher than the current tier.
        """
        current = self.get_tier(package_name)
        current_idx = _TIER_ORDER.index(current)
        target_idx = _TIER_ORDER.index(to_tier)

        if target_idx <= current_idx:
            return False

        self._tiers[package_name] = to_tier
        self._evidence.setdefault(package_name, []).append(evidence)
        return True

    def get_tier(self, package_name: str) -> TrustTier:
        """Return the stored tier for a package, defaulting to UNVERIFIED."""
        return self._tiers.get(package_name, TrustTier.UNVERIFIED)
