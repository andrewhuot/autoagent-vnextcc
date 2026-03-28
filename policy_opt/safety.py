"""No-online-exploration enforcement guard."""


class OnlineExplorationGuard:
    """Prevents any online exploration on production traffic.

    All training must be offline (from logged data only).
    All policy application must be deterministic (no epsilon-greedy in prod).
    """

    BLOCKED_CONFIGS = {"online_exploration", "epsilon_greedy_prod", "live_sampling", "on_policy"}

    @staticmethod
    def validate_training_config(config: dict) -> list[str]:
        """Check training config for online exploration settings. Returns list of violations."""
        violations = []
        if config.get("online", False):
            violations.append("Training mode 'online' is not allowed. Use offline data only.")
        if config.get("exploration_strategy") in ("epsilon_greedy", "boltzmann", "ucb_online"):
            violations.append(
                f"Exploration strategy '{config['exploration_strategy']}' is not allowed in production."
            )
        if config.get("on_policy", False):
            violations.append("On-policy training is not allowed. Use off-policy/offline methods only.")
        for key in OnlineExplorationGuard.BLOCKED_CONFIGS:
            if config.get(key):
                violations.append(f"Config key '{key}' is blocked by safety guard.")
        return violations

    @staticmethod
    def validate_policy_application(context: dict) -> list[str]:
        """Validate that policy application is deterministic (no live exploration)."""
        violations = []
        if context.get("explore", False):
            violations.append("Exploration is not allowed during policy application.")
        if context.get("epsilon", 0.0) > 0.0:
            violations.append("Epsilon-greedy exploration is not allowed in production.")
        return violations

    @staticmethod
    def enforce(config: dict) -> None:
        """Raise ValueError if any online exploration is detected."""
        violations = OnlineExplorationGuard.validate_training_config(config)
        if violations:
            raise ValueError(f"Online exploration guard violations: {'; '.join(violations)}")
