"""Failure classification into diagnostic buckets."""

from logger.store import ConversationRecord

FAILURE_BUCKETS = [
    "routing_error",       # wrong specialist used
    "tool_failure",        # tool call failed
    "hallucination",       # response doesn't match available data
    "safety_violation",    # safety flag triggered
    "timeout",             # latency > threshold
    "unhelpful_response",  # low quality / too short response
]

# Mapping of message keywords to expected specialist types
_ROUTING_HINTS: dict[str, set[str]] = {
    "code": {"coder", "developer", "engineer", "code"},
    "debug": {"coder", "developer", "debugger", "code"},
    "write": {"writer", "content", "copywriter"},
    "search": {"researcher", "search", "web"},
    "math": {"math", "calculator", "analyst"},
    "data": {"analyst", "data", "researcher"},
    "image": {"vision", "image", "designer"},
    "translate": {"translator", "language"},
}


class FailureClassifier:
    def __init__(
        self,
        latency_threshold_ms: float = 3000.0,
        min_response_length: int = 20,
    ):
        self.latency_threshold_ms = latency_threshold_ms
        self.min_response_length = min_response_length

    def classify(self, record: ConversationRecord) -> list[str]:
        """Classify a single failed conversation into failure buckets."""
        buckets: list[str] = []

        # Safety violation: record has non-empty safety_flags
        if record.safety_flags:
            buckets.append("safety_violation")

        # Timeout: latency exceeds threshold
        if record.latency_ms > self.latency_threshold_ms:
            buckets.append("timeout")

        # Tool failure: any tool_call dict contains an error indicator
        for tool_call in record.tool_calls:
            if tool_call.get("error") or tool_call.get("status") == "error":
                buckets.append("tool_failure")
                break

        # Unhelpful response: response is too short
        if len(record.agent_response.strip()) < self.min_response_length:
            buckets.append("unhelpful_response")

        # Routing error: heuristic — check if specialist_used seems wrong for the message
        if record.specialist_used:
            specialist_lower = record.specialist_used.lower()
            message_lower = record.user_message.lower()
            for keyword, expected_specialists in _ROUTING_HINTS.items():
                if keyword in message_lower:
                    if not any(s in specialist_lower for s in expected_specialists):
                        buckets.append("routing_error")
                        break

        return buckets

    def classify_batch(self, records: list[ConversationRecord]) -> dict[str, int]:
        """Classify a batch of records and return bucket counts."""
        counts = {b: 0 for b in FAILURE_BUCKETS}
        for record in records:
            for bucket in self.classify(record):
                if bucket in counts:
                    counts[bucket] += 1
        return counts
