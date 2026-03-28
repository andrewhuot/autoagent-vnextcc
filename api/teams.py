"""Team management — SQLite-backed store."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class Team:
    team_id: str
    name: str
    members: list[str]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "members": self.members,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Team":
        members = d.get("members", [])
        if isinstance(members, str):
            members = json.loads(members)
        return cls(
            team_id=d["team_id"],
            name=d["name"],
            members=members,
            created_at=d["created_at"],
        )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class TeamStore:
    """SQLite-backed team store."""

    def __init__(self, db_path: str = ".autoagent/teams.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS teams (
                    team_id    TEXT PRIMARY KEY,
                    name       TEXT UNIQUE NOT NULL,
                    members    TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_team(self, name: str) -> Team:
        team_id = str(uuid.uuid4())
        created_at = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO teams (team_id, name, members, created_at) VALUES (?, ?, ?, ?)",
                (team_id, name, json.dumps([]), created_at),
            )
            conn.commit()
        return Team(team_id=team_id, name=name, members=[], created_at=created_at)

    def add_member(self, team_id: str, user_id: str) -> Optional[Team]:
        team = self.get_team(team_id)
        if team is None:
            return None
        if user_id not in team.members:
            team.members.append(user_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE teams SET members = ? WHERE team_id = ?",
                (json.dumps(team.members), team_id),
            )
            conn.commit()
        return team

    def remove_member(self, team_id: str, user_id: str) -> Optional[Team]:
        team = self.get_team(team_id)
        if team is None:
            return None
        team.members = [m for m in team.members if m != user_id]
        with self._connect() as conn:
            conn.execute(
                "UPDATE teams SET members = ? WHERE team_id = ?",
                (json.dumps(team.members), team_id),
            )
            conn.commit()
        return team

    def list_teams(self) -> list[Team]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM teams").fetchall()
        return [Team.from_dict(dict(r)) for r in rows]

    def get_team(self, team_id: str) -> Optional[Team]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM teams WHERE team_id = ?", (team_id,)
            ).fetchone()
        if row is None:
            return None
        return Team.from_dict(dict(row))
