import uuid
from .store import ConversationStore, ConversationRecord

SAFETY_KEYWORDS = ["hack", "exploit", "bomb", "weapon", "illegal", "steal", "kill"]
ABANDON_PATTERNS = ["nevermind", "forget it", "whatever", "bye"]
SUCCESS_PATTERNS = ["thank", "thanks", "perfect", "great", "that helps", "got it"]
REFUSAL_PATTERNS = ["can't", "cannot", "won't", "not able", "sorry", "unable"]


def detect_outcome(
    user_message: str,
    agent_response: str,
    tool_calls: list[dict],
    error: str = "",
) -> str:
    """Heuristic outcome detection."""
    if error:
        return "error"

    response_lower = agent_response.lower()
    user_lower = user_message.lower()

    # Check for safety violations in response
    mentions_harmful = any(keyword in response_lower for keyword in SAFETY_KEYWORDS)
    refused = any(pattern in response_lower for pattern in REFUSAL_PATTERNS)
    if mentions_harmful and not refused:
        return "fail"

    # Tool errors indicate failed fulfillment unless a top-level exception already captured.
    if any(call.get("error") or call.get("status") == "error" for call in tool_calls):
        return "fail"

    # Check for abandon patterns in user message
    for pattern in ABANDON_PATTERNS:
        if pattern in user_lower:
            return "abandon"

    # Check for success patterns in user message
    for pattern in SUCCESS_PATTERNS:
        if pattern in user_lower:
            return "success"

    # Check if agent gave a substantive response
    if len(agent_response.strip()) > 20:
        return "success"

    return "unknown"


def detect_safety_flags(user_message: str, agent_response: str) -> list[str]:
    """Detect safety-related content."""
    flags: list[str] = []
    combined = (user_message + " " + agent_response).lower()
    for keyword in SAFETY_KEYWORDS:
        if keyword in combined:
            flags.append(keyword)
    return flags


def log_conversation(
    store: ConversationStore,
    session_id: str,
    user_message: str,
    agent_response: str,
    tool_calls: list[dict] | None = None,
    latency_ms: float = 0.0,
    token_count: int = 0,
    specialist_used: str = "",
    config_version: str = "",
    error: str = "",
) -> ConversationRecord:
    """Log a conversation turn with automatic outcome detection."""
    if tool_calls is None:
        tool_calls = []

    outcome = detect_outcome(user_message, agent_response, tool_calls, error=error)
    safety_flags = detect_safety_flags(user_message, agent_response)

    record = ConversationRecord(
        conversation_id=str(uuid.uuid4()),
        session_id=session_id,
        user_message=user_message,
        agent_response=agent_response,
        tool_calls=tool_calls,
        latency_ms=latency_ms,
        token_count=token_count,
        outcome=outcome,
        safety_flags=safety_flags,
        error_message=error,
        specialist_used=specialist_used,
        config_version=config_version,
    )

    store.log(record)
    return record
