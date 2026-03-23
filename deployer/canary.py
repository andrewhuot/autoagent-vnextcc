"""Canary deployment orchestration and verdict execution."""

import random
import time
from dataclasses import dataclass

from logger.store import ConversationStore

from .versioning import ConfigVersionManager


@dataclass
class CanaryStatus:
    is_active: bool
    canary_version: int | None
    baseline_version: int | None
    canary_conversations: int
    canary_success_rate: float
    baseline_success_rate: float
    started_at: float
    verdict: str  # "no_canary", "pending", "promote", "rollback"


class CanaryManager:
    def __init__(
        self,
        version_manager: ConfigVersionManager,
        store: ConversationStore | None = None,
        canary_percentage: float = 0.10,
        min_canary_conversations: int = 10,
        max_canary_duration_s: float = 3600.0,  # 1 hour
    ):
        self.version_manager = version_manager
        self.store = store
        self.canary_percentage = canary_percentage
        self.min_canary_conversations = min_canary_conversations
        self.max_canary_duration_s = max_canary_duration_s

    def should_use_canary(self) -> bool:
        """Decide if this request should use canary config."""
        if self.version_manager.get_canary_config() is None:
            return False
        if not 0 < self.canary_percentage <= 1:
            return False
        return random.random() < self.canary_percentage

    def get_config(self) -> tuple[dict, str]:
        """Get config for this request. Returns (config, version_label)."""
        if self.should_use_canary():
            config = self.version_manager.get_canary_config()
            if config:
                return config, f"v{self.version_manager.manifest['canary_version']:03d}"
        config = self.version_manager.get_active_config()
        if config:
            return config, f"v{self.version_manager.manifest['active_version']:03d}"
        # Fallback: no configs yet
        return {}, "v000"

    def deploy_canary(self, config: dict, scores: dict) -> int:
        """Deploy a new canary config. Returns version number."""
        cv = self.version_manager.save_version(config, scores, status="canary")
        return cv.version

    def check_canary(self) -> CanaryStatus:
        """Check canary health and decide promote/rollback."""
        canary_ver = self.version_manager.manifest.get("canary_version")
        active_ver = self.version_manager.manifest.get("active_version")

        if canary_ver is None:
            return CanaryStatus(
                is_active=False, canary_version=None, baseline_version=active_ver,
                canary_conversations=0, canary_success_rate=0, baseline_success_rate=0,
                started_at=0, verdict="no_canary",
            )

        # Get canary version info for timing
        canary_info = None
        for v in self.version_manager.manifest["versions"]:
            if v["version"] == canary_ver:
                canary_info = v
                break
        started_at = canary_info["timestamp"] if canary_info else time.time()

        # Get conversations for canary and baseline versions
        canary_label = f"v{canary_ver:03d}"
        baseline_label = f"v{active_ver:03d}" if active_ver else None

        canary_convos = []
        baseline_convos = []
        if self.store:
            canary_convos = self.store.get_by_config_version(canary_label)
            if baseline_label:
                baseline_convos = self.store.get_by_config_version(baseline_label, limit=100)

        canary_success = sum(1 for c in canary_convos if c.outcome == "success") / max(len(canary_convos), 1)
        baseline_success = sum(1 for c in baseline_convos if c.outcome == "success") / max(len(baseline_convos), 1)

        # Decide verdict
        verdict = "pending"
        elapsed = time.time() - started_at

        if len(canary_convos) >= self.min_canary_conversations:
            if baseline_convos:
                if canary_success >= baseline_success * 0.95:  # canary at least 95% as good
                    verdict = "promote"
                else:
                    verdict = "rollback"
            else:
                # With no baseline data, require an absolute quality bar.
                verdict = "promote" if canary_success >= 0.7 else "rollback"
        elif elapsed > self.max_canary_duration_s:
            # Timed out -- promote if we have any data and it's decent, else rollback
            if len(canary_convos) > 0 and canary_success >= 0.7:
                verdict = "promote"
            else:
                verdict = "rollback"

        return CanaryStatus(
            is_active=True,
            canary_version=canary_ver,
            baseline_version=active_ver,
            canary_conversations=len(canary_convos),
            canary_success_rate=canary_success,
            baseline_success_rate=baseline_success,
            started_at=started_at,
            verdict=verdict,
        )

    def execute_verdict(self, status: CanaryStatus) -> str:
        """Execute the canary verdict (promote or rollback)."""
        if status.verdict == "promote" and status.canary_version:
            self.version_manager.promote(status.canary_version)
            return f"Promoted v{status.canary_version:03d} to active"
        elif status.verdict == "rollback" and status.canary_version:
            self.version_manager.rollback(status.canary_version)
            return f"Rolled back v{status.canary_version:03d}"
        return f"No action: {status.verdict}"


class Deployer:
    """High-level deployer that manages config versions and canary deploys."""

    def __init__(self, configs_dir: str = "configs", store: ConversationStore | None = None):
        self.version_manager = ConfigVersionManager(configs_dir)
        self.canary_manager = CanaryManager(self.version_manager, store)

    def deploy(self, config: dict, scores: dict) -> str:
        """Deploy a new config as canary."""
        version = self.canary_manager.deploy_canary(config, scores)
        return f"Deployed v{version:03d} as canary (10% traffic)"

    def check_and_act(self) -> str:
        """Check canary status and promote/rollback if ready."""
        status = self.canary_manager.check_canary()
        if status.verdict in ("promote", "rollback"):
            return self.canary_manager.execute_verdict(status)
        return f"Canary pending: {status.canary_conversations} conversations so far"

    def get_active_config(self) -> dict | None:
        return self.version_manager.get_active_config()

    def status(self) -> dict:
        return {
            "active_version": self.version_manager.manifest.get("active_version"),
            "canary_version": self.version_manager.manifest.get("canary_version"),
            "total_versions": len(self.version_manager.manifest["versions"]),
            "history": self.version_manager.get_version_history()[-5:],
        }
