"""Core types for the proactive guidance system.

Kept in a dedicated module so rules, engine, and adapters can share the
shape without importing one another. ``GuidanceContext`` is duck-typed to
keep tests cheap — callers pass whatever ``SimpleNamespace`` or dataclass
they can cheaply build from their environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


Severity = str  # "info" | "warn" | "blocker"

# Priority buckets. Lower number = surface first.
PRIORITY_BLOCKER = 0
PRIORITY_WARN = 50
PRIORITY_INFO = 100


@dataclass(frozen=True)
class Suggestion:
    """One grounded recommendation for the operator.

    ``id`` is stable across invocations so suppression/cooldown can key on
    it. ``command`` is an optional slash command the TUI or web UI may
    one-click execute; nothing auto-runs — this stays a *suggestion*.
    """

    id: str
    title: str
    body: str
    severity: Severity = "info"
    priority: int = PRIORITY_INFO
    command: str | None = None
    href: str | None = None
    cooldown_seconds: float = 300.0
    """How long after a dismissal before this id may fire again.

    ``300`` (five minutes) keeps the bar from nagging on every refresh but
    still lets a user re-surface a suggestion by waiting out a short pause.
    Individual rules override this via ``replace(..., cooldown_seconds=…)``.
    """


@dataclass
class GuidanceContext:
    """Inputs available to rule predicates.

    Fields are optional so callers can populate only what they know cheaply.
    A rule that needs a field it doesn't have should short-circuit rather
    than crash — see :func:`_has` helpers in :mod:`cli.guidance.rules`.
    """

    workspace: Any | None = None
    workspace_path: str | None = None
    workspace_valid: bool = True

    provider_name: str | None = None
    provider_key_present: bool = True
    mock_mode: bool = False
    mock_reason: str | None = None

    best_score: str | None = None
    last_eval_at: float | None = None
    last_eval_score: float | None = None
    last_optimize_at: float | None = None

    pending_review_cards: int = 0
    pending_autofix: int = 0

    deployment_blocked_reason: str | None = None

    active_session_id: str | None = None
    latest_session_id: str | None = None
    session_count: int = 0

    doctor_failing: bool = False
    doctor_summary: str | None = None

    now: float = 0.0
    """Unix timestamp used for cooldown comparisons. Defaulted by the engine
    when the caller leaves it 0.0."""

    extras: dict[str, Any] = field(default_factory=dict)
    """Free-form overrides for rule tests — avoids ballooning this dataclass
    with flags that only one rule inspects."""


class SuggestionRule(Protocol):
    """A pure function mapping context → zero or more suggestions.

    Rules must not mutate the context or perform I/O — they are called on
    every refresh and must stay cheap. When a rule needs expensive data
    (disk reads, DB queries), the caller stamps that data onto the context
    before evaluation.
    """

    id: str

    def __call__(self, ctx: GuidanceContext) -> list[Suggestion]:  # pragma: no cover
        ...


# Concrete form used by the engine: a rule identifier + a predicate. Keeping
# both structural (Protocol) and dataclass forms means callers who don't want
# to write a class can just register a function via ``make_rule``.
@dataclass(frozen=True)
class Rule:
    id: str
    predicate: Callable[[GuidanceContext], list[Suggestion]]

    def __call__(self, ctx: GuidanceContext) -> list[Suggestion]:
        return self.predicate(ctx)
