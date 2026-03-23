import sqlite3
import json
import time
from dataclasses import dataclass, field


@dataclass
class ConversationRecord:
    conversation_id: str
    session_id: str
    user_message: str
    agent_response: str
    tool_calls: list[dict] = field(default_factory=list)
    latency_ms: float = 0.0
    token_count: int = 0
    outcome: str = "unknown"  # success, fail, abandon, error
    safety_flags: list[str] = field(default_factory=list)
    error_message: str = ""
    specialist_used: str = ""
    config_version: str = ""
    timestamp: float = field(default_factory=time.time)


class ConversationStore:
    def __init__(self, db_path: str = "conversations.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create table if not exists with all ConversationRecord fields."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    agent_response TEXT NOT NULL,
                    tool_calls TEXT NOT NULL DEFAULT '[]',
                    latency_ms REAL NOT NULL DEFAULT 0.0,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    outcome TEXT NOT NULL DEFAULT 'unknown',
                    safety_flags TEXT NOT NULL DEFAULT '[]',
                    error_message TEXT NOT NULL DEFAULT '',
                    specialist_used TEXT NOT NULL DEFAULT '',
                    config_version TEXT NOT NULL DEFAULT '',
                    timestamp REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_session ON conversations(session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outcome ON conversations(outcome)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON conversations(timestamp DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_config_version ON conversations(config_version)"
            )
            conn.commit()

    def log(self, record: ConversationRecord):
        """Insert record into SQLite."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO conversations (
                    conversation_id, session_id, user_message, agent_response,
                    tool_calls, latency_ms, token_count, outcome,
                    safety_flags, error_message, specialist_used,
                    config_version, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.conversation_id,
                    record.session_id,
                    record.user_message,
                    record.agent_response,
                    json.dumps(record.tool_calls),
                    record.latency_ms,
                    record.token_count,
                    record.outcome,
                    json.dumps(record.safety_flags),
                    record.error_message,
                    record.specialist_used,
                    record.config_version,
                    record.timestamp,
                ),
            )
            conn.commit()

    def _row_to_record(self, row: tuple) -> ConversationRecord:
        """Convert a database row to a ConversationRecord."""
        return ConversationRecord(
            conversation_id=row[0],
            session_id=row[1],
            user_message=row[2],
            agent_response=row[3],
            tool_calls=json.loads(row[4]),
            latency_ms=row[5],
            token_count=row[6],
            outcome=row[7],
            safety_flags=json.loads(row[8]),
            error_message=row[9],
            specialist_used=row[10],
            config_version=row[11],
            timestamp=row[12],
        )

    def get_recent(self, limit: int = 100) -> list[ConversationRecord]:
        """Get most recent N conversations ordered by timestamp DESC."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def get_by_outcome(self, outcome: str, limit: int = 50) -> list[ConversationRecord]:
        """Get conversations filtered by outcome."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE outcome = ? ORDER BY timestamp DESC LIMIT ?",
                (outcome, limit),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def get_failures(self, limit: int = 50) -> list[ConversationRecord]:
        """Get conversations where outcome in ('fail', 'error', 'abandon')."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE outcome IN ('fail', 'error', 'abandon') "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def get_by_session(self, session_id: str) -> list[ConversationRecord]:
        """Get all conversations in a session."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE session_id = ? ORDER BY timestamp ASC",
                (session_id,),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def get_by_config_version(self, version: str, limit: int = 100) -> list[ConversationRecord]:
        """Get conversations for a specific config version."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE config_version = ? ORDER BY timestamp DESC LIMIT ?",
                (version, limit),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def count(self) -> int:
        """Return total count of conversation records."""
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()
            return result[0]

    def clear(self):
        """Delete all records (for testing)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM conversations")
            conn.commit()
