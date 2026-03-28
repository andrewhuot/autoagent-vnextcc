"""Secret store — SQLite persistence with basic base64+XOR encryption."""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

def _encode(value: str, key: str) -> str:
    """Encode value using base64, optionally XOR'd with a repeating key."""
    raw = value.encode("utf-8")
    if key:
        key_bytes = key.encode("utf-8")
        raw = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(raw))
    return base64.b64encode(raw).decode("ascii")


def _decode(encoded: str, key: str) -> str:
    """Reverse of _encode."""
    raw = base64.b64decode(encoded.encode("ascii"))
    if key:
        key_bytes = key.encode("utf-8")
        raw = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(raw))
    return raw.decode("utf-8")


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class SecretStore:
    """SQLite-backed secret store with simple encryption."""

    def __init__(
        self,
        db_path: str = ".autoagent/secrets.db",
        encryption_key: str = "",
    ) -> None:
        self.db_path = db_path
        self.encryption_key = encryption_key
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
                CREATE TABLE IF NOT EXISTS secrets (
                    key         TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    value_enc   TEXT NOT NULL,
                    PRIMARY KEY (key, environment)
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, key: str, value: str, environment: str) -> None:
        """Encrypt and persist a secret."""
        encoded = _encode(value, self.encryption_key)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO secrets (key, environment, value_enc)
                VALUES (?, ?, ?)
                ON CONFLICT(key, environment) DO UPDATE SET value_enc = excluded.value_enc
                """,
                (key, environment, encoded),
            )
            conn.commit()

    def retrieve(self, key: str, environment: str) -> Optional[str]:
        """Decrypt and return a secret, or None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_enc FROM secrets WHERE key = ? AND environment = ?",
                (key, environment),
            ).fetchone()
        if row is None:
            return None
        return _decode(row["value_enc"], self.encryption_key)

    def list_keys(self, environment: str) -> list[str]:
        """List all secret keys for an environment."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key FROM secrets WHERE environment = ?", (environment,)
            ).fetchall()
        return [r["key"] for r in rows]

    def delete(self, key: str, environment: str) -> None:
        """Remove a secret."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM secrets WHERE key = ? AND environment = ?",
                (key, environment),
            )
            conn.commit()
