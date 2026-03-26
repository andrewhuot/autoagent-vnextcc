"""Team and role management."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TeamMember:
    """A team member."""

    user_id: str
    name: str
    role: str  # admin, operator, reviewer, viewer
    email: str | None = None


class TeamManager:
    """Simple file-based team management."""

    def __init__(self, config_path: str = ".autoagent/team.json"):
        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_config()

    def _ensure_config(self) -> None:
        """Ensure config file exists."""
        if not self.config_path.exists():
            self.config_path.write_text(json.dumps({"members": []}, indent=2))

    def add_member(self, member: TeamMember) -> None:
        """Add a team member."""
        config = self._load_config()
        config["members"].append(
            {
                "user_id": member.user_id,
                "name": member.name,
                "role": member.role,
                "email": member.email,
            }
        )
        self._save_config(config)

    def remove_member(self, user_id: str) -> bool:
        """Remove a team member."""
        config = self._load_config()
        original_len = len(config["members"])
        config["members"] = [m for m in config["members"] if m["user_id"] != user_id]

        if len(config["members"]) < original_len:
            self._save_config(config)
            return True
        return False

    def get_member(self, user_id: str) -> TeamMember | None:
        """Get a team member."""
        config = self._load_config()
        for member_data in config["members"]:
            if member_data["user_id"] == user_id:
                return TeamMember(**member_data)
        return None

    def list_members(self) -> list[TeamMember]:
        """List all team members."""
        config = self._load_config()
        return [TeamMember(**m) for m in config["members"]]

    def has_role(self, user_id: str, required_role: str) -> bool:
        """Check if user has a role."""
        member = self.get_member(user_id)
        if not member:
            return False

        # Role hierarchy
        roles = ["admin", "operator", "reviewer", "viewer"]
        if member.role not in roles or required_role not in roles:
            return False

        return roles.index(member.role) <= roles.index(required_role)

    def _load_config(self) -> dict:
        """Load config."""
        return json.loads(self.config_path.read_text())

    def _save_config(self, config: dict) -> None:
        """Save config."""
        self.config_path.write_text(json.dumps(config, indent=2))
