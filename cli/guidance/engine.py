"""Rule evaluation + dedupe/cooldown/suppression for guidance suggestions.

Separated from the rule definitions so tests can register synthetic rules
without depending on the built-in set, and so the adapter code (CLI status,
web API) imports only what it needs.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from cli.guidance.rules import DEFAULT_RULES as _DEFAULT_RULES
from cli.guidance.types import (
    GuidanceContext,
    Rule,
    Suggestion,
    SuggestionRule,
)


DEFAULT_RULES: tuple[Rule, ...] = _DEFAULT_RULES
"""Registered rules used when a caller doesn't pass a custom set."""


def default_now() -> float:
    """Return the current wall-clock time; indirection simplifies tests."""
    return time.time()


@dataclass
class SuggestionHistory:
    """Cooldown + dismissal state, keyed by suggestion id.

    Persisted as a small JSON file under the workspace (``.agentlab/guidance_history.json``)
    so a dismissed suggestion stays dismissed across REPL restarts. The store
    is intentionally tiny — we never record the full suggestion, only the id
    and the timestamps needed for cooldown math.
    """

    path: Path | None = None
    shown_at: dict[str, float] = field(default_factory=dict)
    dismissed_at: dict[str, float] = field(default_factory=dict)
    accepted_at: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None) -> "SuggestionHistory":
        """Read a history file; return an empty history on any failure."""
        if path is None or not path.exists():
            return cls(path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(path=path)
        if not isinstance(raw, dict):
            return cls(path=path)
        return cls(
            path=path,
            shown_at=_coerce_timestamp_map(raw.get("shown_at")),
            dismissed_at=_coerce_timestamp_map(raw.get("dismissed_at")),
            accepted_at=_coerce_timestamp_map(raw.get("accepted_at")),
        )

    def save(self) -> None:
        """Persist the history atomically; silent on failure.

        Status-line writes can't block the REPL loop — if the workspace is
        read-only or the path has rotated out from under us, we drop the
        update rather than raise.
        """
        if self.path is None:
            return
        payload = {
            "shown_at": self.shown_at,
            "dismissed_at": self.dismissed_at,
            "accepted_at": self.accepted_at,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            return

    # -- mutation ----------------------------------------------------------

    def mark_shown(self, suggestion_id: str, now: float) -> None:
        self.shown_at[suggestion_id] = now

    def mark_dismissed(self, suggestion_id: str, now: float) -> None:
        self.dismissed_at[suggestion_id] = now

    def mark_accepted(self, suggestion_id: str, now: float) -> None:
        self.accepted_at[suggestion_id] = now

    # -- query -------------------------------------------------------------

    def is_on_cooldown(self, suggestion: Suggestion, now: float) -> bool:
        """Return ``True`` if the suggestion should be suppressed right now.

        Accepted suggestions earn a long cooldown (``10×`` the rule's value)
        because the operator has clearly absorbed the recommendation. A
        dismissal applies the rule's own cooldown. A "shown but not acted
        on" state applies a shorter (``½×``) cooldown so repeat renders
        within the same session don't re-spam.
        """
        cooldown = max(0.0, suggestion.cooldown_seconds)
        accepted = self.accepted_at.get(suggestion.id)
        if accepted is not None and now - accepted < cooldown * 10.0:
            return True
        dismissed = self.dismissed_at.get(suggestion.id)
        if dismissed is not None and now - dismissed < cooldown:
            return True
        shown = self.shown_at.get(suggestion.id)
        if shown is not None and now - shown < cooldown * 0.5:
            return True
        return False


def _coerce_timestamp_map(raw: object) -> dict[str, float]:
    """Best-effort parse of ``{id: timestamp}`` from persisted JSON."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def evaluate_rules(
    ctx: GuidanceContext,
    *,
    rules: Sequence[SuggestionRule] | None = None,
) -> list[Suggestion]:
    """Run every rule and return dedup'd suggestions sorted by priority.

    Rules that raise are swallowed — a buggy rule must never take down the
    status bar. Duplicates (same ``id``) keep the first occurrence; rules
    earlier in the list win, which gives the built-in rule order precedence
    over plugin-registered rules.
    """
    active_rules = rules if rules is not None else DEFAULT_RULES
    seen: set[str] = set()
    results: list[Suggestion] = []
    for rule in active_rules:
        try:
            produced = rule(ctx)
        except Exception:
            continue
        if not produced:
            continue
        for suggestion in produced:
            if suggestion.id in seen:
                continue
            seen.add(suggestion.id)
            results.append(suggestion)
    results.sort(key=lambda s: (s.priority, s.id))
    return results


def select_suggestions(
    ctx: GuidanceContext,
    *,
    history: SuggestionHistory | None = None,
    rules: Sequence[SuggestionRule] | None = None,
    limit: int = 3,
    mark_shown: bool = True,
) -> list[Suggestion]:
    """Evaluate rules, drop suppressed/cooldown'd items, return up to ``limit``.

    ``mark_shown=True`` stamps the returned suggestions as shown in the
    history so the next call applies the "just shown" half-cooldown. Pass
    ``False`` for idempotent reads (e.g. previewing without committing).
    """
    now = ctx.now if ctx.now else default_now()
    if ctx.now == 0.0:
        ctx = _with_now(ctx, now)

    candidates = evaluate_rules(ctx, rules=rules)
    if not candidates:
        return []

    hist = history or SuggestionHistory()
    selected: list[Suggestion] = []
    for suggestion in candidates:
        if hist.is_on_cooldown(suggestion, now):
            continue
        selected.append(suggestion)
        if len(selected) >= limit:
            break

    if mark_shown:
        for suggestion in selected:
            hist.mark_shown(suggestion.id, now)
        hist.save()

    return selected


def _with_now(ctx: GuidanceContext, now: float) -> GuidanceContext:
    """Return a copy of ``ctx`` with ``now`` populated. Avoids mutating the
    caller's object — callers frequently reuse a single context across
    multiple evaluations in tests."""
    return GuidanceContext(
        workspace=ctx.workspace,
        workspace_path=ctx.workspace_path,
        workspace_valid=ctx.workspace_valid,
        provider_name=ctx.provider_name,
        provider_key_present=ctx.provider_key_present,
        mock_mode=ctx.mock_mode,
        mock_reason=ctx.mock_reason,
        best_score=ctx.best_score,
        last_eval_at=ctx.last_eval_at,
        last_eval_score=ctx.last_eval_score,
        last_optimize_at=ctx.last_optimize_at,
        pending_review_cards=ctx.pending_review_cards,
        pending_autofix=ctx.pending_autofix,
        deployment_blocked_reason=ctx.deployment_blocked_reason,
        active_session_id=ctx.active_session_id,
        latest_session_id=ctx.latest_session_id,
        session_count=ctx.session_count,
        doctor_failing=ctx.doctor_failing,
        doctor_summary=ctx.doctor_summary,
        now=now,
        extras=dict(ctx.extras),
    )


__all__ = [
    "DEFAULT_RULES",
    "SuggestionHistory",
    "evaluate_rules",
    "select_suggestions",
]
