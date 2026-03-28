"""Browser confirmation policy — detect and gate destructive actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DestructiveAction(str, Enum):
    """Categories of browser actions that require human confirmation."""

    FORM_SUBMIT = "form_submit"
    PURCHASE = "purchase"
    ACCOUNT_CHANGE = "account_change"
    DATA_DELETE = "data_delete"
    PASSWORD_CHANGE = "password_change"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ConfirmationPolicy:
    """Policy controlling when human confirmation is required."""

    action_types: list[str] = field(default_factory=list)
    require_explicit: bool = True
    auto_approve_safe: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_types": self.action_types,
            "require_explicit": self.require_explicit,
            "auto_approve_safe": self.auto_approve_safe,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConfirmationPolicy":
        return cls(
            action_types=data.get("action_types", []),
            require_explicit=data.get("require_explicit", True),
            auto_approve_safe=data.get("auto_approve_safe", False),
        )


# ---------------------------------------------------------------------------
# Keyword signals for action classification
# ---------------------------------------------------------------------------

_DESTRUCTIVE_KEYWORDS: dict[str, list[str]] = {
    DestructiveAction.PURCHASE: ["buy", "purchase", "checkout", "pay", "order", "payment"],
    DestructiveAction.FORM_SUBMIT: ["submit", "send", "post", "confirm"],
    DestructiveAction.DATA_DELETE: ["delete", "remove", "erase", "destroy", "purge"],
    DestructiveAction.ACCOUNT_CHANGE: ["profile", "account", "settings", "email", "username"],
    DestructiveAction.PASSWORD_CHANGE: ["password", "passwd", "passphrase", "new password"],
}

_SAFE_ACTIONS = {"navigate", "scroll", "screenshot", "extract", "wait"}


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

class ConfirmationChecker:
    """Evaluate browser action dicts against a ConfirmationPolicy."""

    def __init__(self, policy: ConfirmationPolicy | None = None) -> None:
        self.policy = policy or ConfirmationPolicy(
            action_types=[d.value for d in DestructiveAction],
            require_explicit=True,
            auto_approve_safe=True,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def requires_confirmation(self, action: dict[str, Any]) -> bool:
        """Return True if *action* must be confirmed before execution."""
        action_type = action.get("action", "")
        target = (action.get("target", "") + " " + action.get("value", "")).lower()

        # Safe actions can be auto-approved
        if self.policy.auto_approve_safe and action_type in _SAFE_ACTIONS:
            return False

        # Check against explicit policy action_types list
        if action_type in self.policy.action_types:
            return self.policy.require_explicit

        # Keyword-based heuristic
        category = self._classify(target)
        if category and category.value in self.policy.action_types:
            return self.policy.require_explicit

        return False

    def get_confirmation_message(self, action: dict[str, Any]) -> str:
        """Return a human-readable confirmation prompt for *action*."""
        action_type = action.get("action", "unknown")
        target = action.get("target", "")
        value = action.get("value", "")
        category = self._classify(
            (target + " " + value).lower()
        )
        category_label = category.value if category else action_type

        parts = [f"Confirm {category_label.upper()} action:"]
        parts.append(f"  Action type : {action_type}")
        if target:
            parts.append(f"  Target      : {target}")
        if value:
            parts.append(f"  Value       : {value}")
        parts.append("Proceed? [yes/no]")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify(self, text: str) -> DestructiveAction | None:
        for category, keywords in _DESTRUCTIVE_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return DestructiveAction(category)
        return None
