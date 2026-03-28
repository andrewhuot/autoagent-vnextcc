"""Platform authentication — users, tokens, and SQLite-backed persistence."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future_iso(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AuthUser:
    user_id: str
    username: str
    email: str
    roles: list[str]
    team_id: Optional[str]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "roles": self.roles,
            "team_id": self.team_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AuthUser":
        roles = d.get("roles", [])
        if isinstance(roles, str):
            import json
            roles = json.loads(roles)
        return cls(
            user_id=d["user_id"],
            username=d["username"],
            email=d["email"],
            roles=roles,
            team_id=d.get("team_id"),
            created_at=d["created_at"],
        )


@dataclass
class AuthToken:
    token: str
    user_id: str
    expires_at: str
    scopes: list[str]

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "user_id": self.user_id,
            "expires_at": self.expires_at,
            "scopes": self.scopes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AuthToken":
        scopes = d.get("scopes", [])
        if isinstance(scopes, str):
            import json
            scopes = json.loads(scopes)
        return cls(
            token=d["token"],
            user_id=d["user_id"],
            expires_at=d["expires_at"],
            scopes=scopes,
        )


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class AuthProvider:
    """SQLite-backed authentication provider."""

    def __init__(self, db_path: str = ".autoagent/auth.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id    TEXT PRIMARY KEY,
                    username   TEXT UNIQUE NOT NULL,
                    email      TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    roles      TEXT NOT NULL DEFAULT '[]',
                    team_id    TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tokens (
                    token      TEXT PRIMARY KEY,
                    user_id    TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    scopes     TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        email: str,
        password_hash: str,
        roles: list[str],
    ) -> AuthUser:
        import json

        user_id = str(uuid.uuid4())
        created_at = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, username, email, password_hash, roles, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, email, password_hash, json.dumps(roles), created_at),
            )
            conn.commit()
        return AuthUser(
            user_id=user_id,
            username=username,
            email=email,
            roles=roles,
            team_id=None,
            created_at=created_at,
        )

    def authenticate(self, username: str, password_hash: str) -> Optional[AuthToken]:
        import json

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? AND password_hash = ?",
                (username, password_hash),
            ).fetchone()
        if row is None:
            return None

        token_str = secrets.token_hex(32)
        expires_at = _future_iso(hours=24)
        scopes = ["read", "write"]

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO tokens (token, user_id, expires_at, scopes) VALUES (?, ?, ?, ?)",
                (token_str, row["user_id"], expires_at, json.dumps(scopes)),
            )
            conn.commit()

        return AuthToken(
            token=token_str,
            user_id=row["user_id"],
            expires_at=expires_at,
            scopes=scopes,
        )

    def validate_token(self, token: str) -> Optional[AuthUser]:
        import json

        now = _now_iso()
        with self._connect() as conn:
            tok_row = conn.execute(
                "SELECT * FROM tokens WHERE token = ? AND expires_at > ?",
                (token, now),
            ).fetchone()
            if tok_row is None:
                return None
            user_row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (tok_row["user_id"],)
            ).fetchone()
        if user_row is None:
            return None
        return AuthUser.from_dict(dict(user_row))

    def list_users(self) -> list[AuthUser]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM users").fetchall()
        return [AuthUser.from_dict(dict(r)) for r in rows]
