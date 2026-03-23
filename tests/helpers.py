"""Reusable test helpers."""

from __future__ import annotations

import time
import uuid

from logger.store import ConversationRecord


def build_record(
    *,
    session_id: str = "session-1",
    user_message: str = "hello",
    agent_response: str = "Thanks for reaching out. I can help with that.",
    outcome: str = "success",
    latency_ms: float = 120.0,
    token_count: int = 200,
    safety_flags: list[str] | None = None,
    tool_calls: list[dict] | None = None,
    specialist_used: str = "support",
    config_version: str = "v001",
    error_message: str = "",
) -> ConversationRecord:
    """Build a ConversationRecord with defaults suitable for tests."""
    return ConversationRecord(
        conversation_id=str(uuid.uuid4()),
        session_id=session_id,
        user_message=user_message,
        agent_response=agent_response,
        tool_calls=tool_calls or [],
        latency_ms=latency_ms,
        token_count=token_count,
        outcome=outcome,
        safety_flags=safety_flags or [],
        error_message=error_message,
        specialist_used=specialist_used,
        config_version=config_version,
        timestamp=time.time(),
    )
