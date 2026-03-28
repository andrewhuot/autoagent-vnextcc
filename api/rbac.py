"""Role-Based Access Control engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.auth import AuthUser


# ---------------------------------------------------------------------------
# Enums & Dataclasses
# ---------------------------------------------------------------------------

class Role(str, Enum):
    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"
    OWNER = "owner"


@dataclass
class Permission:
    resource: str
    action: str
    allowed: bool

    def to_dict(self) -> dict:
        return {
            "resource": self.resource,
            "action": self.action,
            "allowed": self.allowed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Permission":
        return cls(
            resource=d["resource"],
            action=d["action"],
            allowed=d["allowed"],
        )


# ---------------------------------------------------------------------------
# Built-in role permission matrix
# ---------------------------------------------------------------------------

_ROLE_PERMISSIONS: dict[str, list[Permission]] = {
    Role.VIEWER: [
        Permission("task", "read", True),
        Permission("task", "write", False),
        Permission("task", "delete", False),
        Permission("agent", "read", True),
        Permission("agent", "write", False),
        Permission("agent", "delete", False),
        Permission("skill", "read", True),
        Permission("skill", "write", False),
        Permission("secret", "read", False),
        Permission("secret", "write", False),
        Permission("user", "read", False),
        Permission("user", "write", False),
        Permission("team", "read", True),
        Permission("team", "write", False),
        Permission("audit", "read", False),
    ],
    Role.EDITOR: [
        Permission("task", "read", True),
        Permission("task", "write", True),
        Permission("task", "delete", False),
        Permission("agent", "read", True),
        Permission("agent", "write", True),
        Permission("agent", "delete", False),
        Permission("skill", "read", True),
        Permission("skill", "write", True),
        Permission("secret", "read", True),
        Permission("secret", "write", True),
        Permission("user", "read", True),
        Permission("user", "write", False),
        Permission("team", "read", True),
        Permission("team", "write", False),
        Permission("audit", "read", True),
    ],
    Role.ADMIN: [
        Permission("task", "read", True),
        Permission("task", "write", True),
        Permission("task", "delete", True),
        Permission("agent", "read", True),
        Permission("agent", "write", True),
        Permission("agent", "delete", True),
        Permission("skill", "read", True),
        Permission("skill", "write", True),
        Permission("secret", "read", True),
        Permission("secret", "write", True),
        Permission("user", "read", True),
        Permission("user", "write", True),
        Permission("team", "read", True),
        Permission("team", "write", True),
        Permission("audit", "read", True),
    ],
    Role.OWNER: [
        Permission("task", "read", True),
        Permission("task", "write", True),
        Permission("task", "delete", True),
        Permission("agent", "read", True),
        Permission("agent", "write", True),
        Permission("agent", "delete", True),
        Permission("skill", "read", True),
        Permission("skill", "write", True),
        Permission("secret", "read", True),
        Permission("secret", "write", True),
        Permission("user", "read", True),
        Permission("user", "write", True),
        Permission("user", "delete", True),
        Permission("team", "read", True),
        Permission("team", "write", True),
        Permission("team", "delete", True),
        Permission("audit", "read", True),
        Permission("audit", "delete", True),
    ],
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RbacEngine:
    """Evaluates access-control decisions for a given user."""

    def check_permission(self, user: "AuthUser", resource: str, action: str) -> bool:
        """Return True if any of the user's roles allow the requested action."""
        for role_str in user.roles:
            perms = self.get_role_permissions(role_str)
            for perm in perms:
                if perm.resource == resource and perm.action == action:
                    if perm.allowed:
                        return True
        return False

    def get_role_permissions(self, role: str) -> list[Permission]:
        """Return the built-in permission list for a named role."""
        # Normalise to enum value string for lookup
        try:
            role_key = Role(role.lower())
        except ValueError:
            return []
        return list(_ROLE_PERMISSIONS.get(role_key, []))
