"""Skill supply chain — package verification, installation, and trust management."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from registry.signing import SkillSigner
from registry.static_analysis import SkillStaticAnalyzer
from registry.trust_tiers import TrustEvaluator, TrustTier


# ---------------------------------------------------------------------------
# SkillPackage dataclass
# ---------------------------------------------------------------------------

@dataclass
class SkillPackage:
    name: str
    version: int
    author: str
    signature: Optional[str]
    trust_tier: str
    compatibility: dict
    benchmark_badges: list[str]
    provenance_chain: list[dict]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "signature": self.signature,
            "trust_tier": self.trust_tier,
            "compatibility": self.compatibility,
            "benchmark_badges": self.benchmark_badges,
            "provenance_chain": self.provenance_chain,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SkillPackage":
        return cls(
            name=d["name"],
            version=d.get("version", 1),
            author=d.get("author", ""),
            signature=d.get("signature"),
            trust_tier=d.get("trust_tier", TrustTier.UNVERIFIED.value),
            compatibility=d.get("compatibility", {}),
            benchmark_badges=d.get("benchmark_badges", []),
            provenance_chain=d.get("provenance_chain", []),
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class SupplyChainManager:
    """Manages skill package verification, installation and trust tracking."""

    def __init__(
        self,
        install_dir: str = ".autoagent/skills",
        author_key: str = "",
    ) -> None:
        self._install_dir = Path(install_dir)
        self._install_dir.mkdir(parents=True, exist_ok=True)
        self._author_key = author_key
        self._signer = SkillSigner()
        self._analyzer = SkillStaticAnalyzer()
        self._trust_evaluator = TrustEvaluator()
        # name -> SkillPackage
        self._installed: dict[str, SkillPackage] = {}
        self._load_installed()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _index_path(self) -> Path:
        return self._install_dir / "_index.json"

    def _load_installed(self) -> None:
        path = self._index_path()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                for entry in data:
                    pkg = SkillPackage.from_dict(entry)
                    self._installed[pkg.name] = pkg
            except Exception:
                pass

    def _save_installed(self) -> None:
        path = self._index_path()
        data = [pkg.to_dict() for pkg in self._installed.values()]
        path.write_text(json.dumps(data, indent=2))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify_signature(self, package: SkillPackage) -> bool:
        """Return True if the package carries a valid HMAC signature.

        Verification uses the package name + version as the canonical content
        string when no richer content is available.  If no signature is
        present, returns False.
        """
        if not package.signature:
            return False
        canonical = f"{package.name}:{package.version}:{package.author}"
        return self._signer.verify(canonical, package.signature, self._author_key)

    def check_compatibility(
        self, package: SkillPackage, target_config: dict
    ) -> list[str]:
        """Return a list of incompatibility strings (empty = fully compatible).

        Checks keys present in package.compatibility against target_config.
        """
        issues: list[str] = []
        compat = package.compatibility

        min_version = compat.get("min_python")
        if min_version:
            import sys
            current = f"{sys.version_info.major}.{sys.version_info.minor}"
            if current < min_version:
                issues.append(
                    f"Requires Python >= {min_version}, running {current}"
                )

        required_keys = compat.get("requires_config_keys", [])
        for key in required_keys:
            if key not in target_config:
                issues.append(f"Missing required config key: {key}")

        incompatible_targets = compat.get("incompatible_with", [])
        target_name = target_config.get("deployment_target", "")
        if target_name in incompatible_targets:
            issues.append(
                f"Package is incompatible with deployment target: {target_name}"
            )

        return issues

    def install(self, package: SkillPackage) -> bool:
        """Verify, statically analyse, and register a skill package.

        Returns True on success, False if any check fails.
        """
        # 1. Static analysis — requires content stored in provenance_chain or name
        content = ""
        if package.provenance_chain:
            last = package.provenance_chain[-1]
            content = last.get("content", package.name)
        else:
            content = package.name

        result = self._analyzer.analyze(content)
        if not result.safe:
            return False

        # 2. Signature check (warn but do not block if key not configured)
        if self._author_key and package.signature:
            if not self.verify_signature(package):
                return False

        # 3. Evaluate and assign trust tier
        pkg_dict = package.to_dict()
        tier = self._trust_evaluator.evaluate(pkg_dict)
        package.trust_tier = tier.value

        # 4. Register
        self._installed[package.name] = package
        self._save_installed()
        return True

    def get_trust_tier(self, package: SkillPackage) -> str:
        """Return the trust tier string for the given package."""
        pkg_dict = package.to_dict()
        tier = self._trust_evaluator.evaluate(pkg_dict)
        return tier.value

    def list_installed(self) -> list[SkillPackage]:
        """Return all installed packages."""
        return list(self._installed.values())
