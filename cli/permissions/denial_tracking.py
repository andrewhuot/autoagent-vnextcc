"""In-memory denial tracker for the permission classifier.

After a tool has been denied N times in a single session, the classifier
gate escalates that tool back to PROMPT regardless of whether the
heuristic layer considers the call safe. This lets a user's repeated
"no" answers override a borderline-safe allowlist until the session ends
or the tracker is explicitly reset.

The tracker is intentionally in-memory only: no file I/O, no persistence.
A new session starts with fresh counters.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DenialTracker:
    """In-memory per-session tracker. After N denials of a tool, the classifier
    gate escalates that tool back to PROMPT regardless of heuristic safety.

    Semantics
    ---------
    * ``record_denial`` increments an unbounded per-tool counter.
    * ``denial_count`` returns the counter value (0 for unseen tools).
    * ``should_escalate_to_prompt`` fires iff the count has reached the
      threshold AND the threshold is strictly positive. A threshold of 0
      disables the tracker entirely — nothing ever escalates, even though
      counters still advance (useful for diagnostics / logging).
    * ``reset`` clears every counter but leaves the configured threshold
      intact, so the tracker can be reused across sub-sessions.

    Tool names are used verbatim as dict keys. An empty-string tool name
    is accepted (stored under the ``""`` key) — this keeps the tracker
    honest about what the caller passed in rather than silently dropping
    data. The classifier gate is responsible for ensuring it never calls
    the tracker with a meaningless name.
    """

    max_per_session_per_tool: int = 3
    _counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_per_session_per_tool < 0:
            raise ValueError("max_per_session_per_tool must be >= 0")

    def record_denial(self, tool_name: str) -> None:
        """Increment the denial counter for ``tool_name``.

        The counter is unbounded — we rely on Python's arbitrary-precision
        ``int``. The empty string is accepted as a valid key; see the
        class docstring for rationale.
        """
        self._counts[tool_name] = self._counts.get(tool_name, 0) + 1

    def denial_count(self, tool_name: str) -> int:
        """Return the current denial count for ``tool_name`` (0 if unseen)."""
        return self._counts.get(tool_name, 0)

    def should_escalate_to_prompt(self, tool_name: str) -> bool:
        """Return True iff the threshold is positive AND has been met."""
        if self.max_per_session_per_tool <= 0:
            return False
        return self.denial_count(tool_name) >= self.max_per_session_per_tool

    def reset(self) -> None:
        """Clear every counter. Leaves ``max_per_session_per_tool`` untouched."""
        self._counts.clear()
