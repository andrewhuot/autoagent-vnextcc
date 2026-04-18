"""Unit tests for the proactive guidance engine.

Focuses on rule selection + suppression logic — the stuff that decides
*which* recommendations show up in the status line and when.  Adapter
integration (workspace reads, API responses) lives in its own test files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli.guidance import (
    GuidanceContext,
    Suggestion,
    SuggestionHistory,
    evaluate_rules,
    select_suggestions,
)
from cli.guidance.engine import DEFAULT_RULES
from cli.guidance.rules import DEFAULT_RULES as RULES_REGISTRY
from cli.guidance.types import Rule


# ---------------------------------------------------------------------------
# Rule firing
# ---------------------------------------------------------------------------


def test_broken_workspace_rule_fires_when_invalid() -> None:
    ctx = GuidanceContext(workspace_valid=False, now=1000.0)
    ids = {s.id for s in evaluate_rules(ctx)}
    assert "broken-workspace" in ids


def test_broken_workspace_rule_silent_when_valid() -> None:
    ctx = GuidanceContext(workspace_valid=True, now=1000.0)
    ids = {s.id for s in evaluate_rules(ctx)}
    assert "broken-workspace" not in ids


def test_mock_mode_rule_fires_and_includes_reason() -> None:
    ctx = GuidanceContext(mock_mode=True, mock_reason="OPENAI_API_KEY unset", now=1000.0)
    suggestions = evaluate_rules(ctx)
    assert any("OPENAI_API_KEY" in s.body for s in suggestions if s.id == "provider-mock-mode")


def test_missing_provider_key_rule_suppressed_when_mock_mode_on() -> None:
    """Don't double-surface — the mock_mode rule already explains the problem."""
    ctx = GuidanceContext(
        mock_mode=True,
        provider_key_present=False,
        provider_name="openai",
        now=1000.0,
    )
    ids = {s.id for s in evaluate_rules(ctx)}
    assert "provider-key-missing" not in ids


def test_missing_provider_key_rule_fires_when_not_mock() -> None:
    ctx = GuidanceContext(
        mock_mode=False,
        provider_key_present=False,
        provider_name="openai",
        now=1000.0,
    )
    suggestions = evaluate_rules(ctx)
    assert any(s.id == "provider-key-missing" for s in suggestions)


def test_pending_review_rule_counts_match_body() -> None:
    ctx = GuidanceContext(pending_review_cards=3, now=1000.0)
    suggestion = next(
        s for s in evaluate_rules(ctx) if s.id == "pending-review-blocks-deploy"
    )
    assert "3" in suggestion.title
    assert suggestion.severity == "warn"


def test_run_eval_before_optimize_fires_when_no_baseline() -> None:
    ctx = GuidanceContext(last_optimize_at=500.0, last_eval_at=None, now=1000.0)
    ids = {s.id for s in evaluate_rules(ctx)}
    assert "run-eval-before-optimize" in ids


def test_run_eval_before_optimize_silent_when_eval_recent() -> None:
    ctx = GuidanceContext(last_optimize_at=500.0, last_eval_at=600.0, now=1000.0)
    ids = {s.id for s in evaluate_rules(ctx)}
    assert "run-eval-before-optimize" not in ids


def test_run_eval_before_optimize_silent_when_never_optimized() -> None:
    """No optimize yet = nothing to compare against = don't nag."""
    ctx = GuidanceContext(last_optimize_at=None, last_eval_at=None, now=1000.0)
    ids = {s.id for s in evaluate_rules(ctx)}
    assert "run-eval-before-optimize" not in ids


def test_resume_prior_session_silent_when_already_on_latest() -> None:
    ctx = GuidanceContext(
        latest_session_id="s-7",
        active_session_id="s-7",
        session_count=5,
        now=1000.0,
    )
    ids = {s.id for s in evaluate_rules(ctx)}
    assert "resume-prior-session" not in ids


def test_resume_prior_session_fires_when_no_active_session() -> None:
    ctx = GuidanceContext(
        latest_session_id="s-7",
        active_session_id=None,
        session_count=5,
        now=1000.0,
    )
    ids = {s.id for s in evaluate_rules(ctx)}
    assert "resume-prior-session" in ids


def test_doctor_failing_rule_fires_with_summary() -> None:
    ctx = GuidanceContext(
        doctor_failing=True,
        doctor_summary="workspace missing AGENTLAB.md",
        now=1000.0,
    )
    suggestion = next(s for s in evaluate_rules(ctx) if s.id == "doctor-failing")
    assert "AGENTLAB.md" in suggestion.body


def test_deployment_blocked_rule_fires_when_reason_present() -> None:
    ctx = GuidanceContext(deployment_blocked_reason="safety gate failed", now=1000.0)
    ids = {s.id for s in evaluate_rules(ctx)}
    assert "deployment-blocked" in ids


# ---------------------------------------------------------------------------
# Engine behaviour: priority, dedupe, error handling
# ---------------------------------------------------------------------------


def test_suggestions_sorted_by_priority() -> None:
    ctx = GuidanceContext(
        workspace_valid=False,  # blocker
        mock_mode=True,         # warn
        pending_review_cards=1, # warn
        last_optimize_at=500.0, # info
        now=1000.0,
    )
    suggestions = evaluate_rules(ctx)
    priorities = [s.priority for s in suggestions]
    assert priorities == sorted(priorities), priorities


def test_dedupe_by_id_keeps_first_occurrence() -> None:
    """Two rules emitting the same id → first wins."""
    twin_a = Rule(
        "first", lambda ctx: [Suggestion("dup", "A", "from A", priority=10)]
    )
    twin_b = Rule(
        "second", lambda ctx: [Suggestion("dup", "B", "from B", priority=10)]
    )
    ctx = GuidanceContext(now=1000.0)
    suggestions = evaluate_rules(ctx, rules=(twin_a, twin_b))
    assert [s.title for s in suggestions] == ["A"]


def test_buggy_rule_swallowed() -> None:
    """A rule that raises must not take down status-line rendering."""
    def explode(_ctx: GuidanceContext) -> list[Suggestion]:
        raise RuntimeError("boom")

    broken = Rule("broken", explode)
    ok = Rule("ok", lambda _c: [Suggestion("ok", "ok", "body")])
    ctx = GuidanceContext(now=1000.0)
    ids = [s.id for s in evaluate_rules(ctx, rules=(broken, ok))]
    assert ids == ["ok"]


# ---------------------------------------------------------------------------
# Cooldown + history
# ---------------------------------------------------------------------------


def _make_ctx_for_single_rule() -> GuidanceContext:
    """Return a context that triggers exactly the pending-review rule."""
    return GuidanceContext(pending_review_cards=1, now=1000.0)


def test_select_suggestions_returns_results_when_history_empty() -> None:
    ctx = _make_ctx_for_single_rule()
    history = SuggestionHistory()
    selected = select_suggestions(ctx, history=history, mark_shown=False)
    assert any(s.id == "pending-review-blocks-deploy" for s in selected)


def test_dismissal_suppresses_within_cooldown() -> None:
    ctx = _make_ctx_for_single_rule()
    history = SuggestionHistory()
    history.mark_dismissed("pending-review-blocks-deploy", 999.0)
    selected = select_suggestions(ctx, history=history, mark_shown=False)
    assert all(s.id != "pending-review-blocks-deploy" for s in selected)


def test_dismissal_expires_after_cooldown() -> None:
    """Well past the rule's cooldown (300s) → suggestion reappears."""
    ctx = GuidanceContext(pending_review_cards=1, now=10_000.0)
    history = SuggestionHistory()
    history.mark_dismissed("pending-review-blocks-deploy", 1000.0)
    selected = select_suggestions(ctx, history=history, mark_shown=False)
    assert any(s.id == "pending-review-blocks-deploy" for s in selected)


def test_accepted_applies_longer_cooldown() -> None:
    """Accepted suggestions stay suppressed ~10× the base cooldown."""
    # Base cooldown = 300s; accepted_at=1000, now=1200 → well inside 10× window.
    ctx = GuidanceContext(pending_review_cards=1, now=1200.0)
    history = SuggestionHistory()
    history.mark_accepted("pending-review-blocks-deploy", 1000.0)
    selected = select_suggestions(ctx, history=history, mark_shown=False)
    assert all(s.id != "pending-review-blocks-deploy" for s in selected)


def test_shown_applies_half_cooldown() -> None:
    """Shown-but-not-acted → suppressed for cooldown/2."""
    # Base cooldown = 300s; shown_at=1000, now=1100 → still inside 150s window.
    ctx = GuidanceContext(pending_review_cards=1, now=1100.0)
    history = SuggestionHistory()
    history.mark_shown("pending-review-blocks-deploy", 1000.0)
    selected = select_suggestions(ctx, history=history, mark_shown=False)
    assert all(s.id != "pending-review-blocks-deploy" for s in selected)


def test_shown_expires_past_half_cooldown() -> None:
    """Past cooldown/2 → the suggestion is eligible again."""
    ctx = GuidanceContext(pending_review_cards=1, now=1200.0)
    history = SuggestionHistory()
    history.mark_shown("pending-review-blocks-deploy", 1000.0)
    selected = select_suggestions(ctx, history=history, mark_shown=False)
    assert any(s.id == "pending-review-blocks-deploy" for s in selected)


def test_limit_caps_returned_suggestions() -> None:
    ctx = GuidanceContext(
        workspace_valid=False,
        mock_mode=True,
        pending_review_cards=1,
        now=1000.0,
    )
    selected = select_suggestions(ctx, history=SuggestionHistory(), limit=1, mark_shown=False)
    assert len(selected) == 1


def test_select_marks_shown_when_requested() -> None:
    ctx = _make_ctx_for_single_rule()
    history = SuggestionHistory()
    select_suggestions(ctx, history=history, mark_shown=True)
    assert "pending-review-blocks-deploy" in history.shown_at


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------


def test_history_roundtrip_json(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    history = SuggestionHistory(path=path)
    history.mark_dismissed("alpha", 1000.0)
    history.mark_accepted("beta", 2000.0)
    history.mark_shown("gamma", 3000.0)
    history.save()

    assert path.exists()
    loaded = SuggestionHistory.load(path)
    assert loaded.dismissed_at == {"alpha": 1000.0}
    assert loaded.accepted_at == {"beta": 2000.0}
    assert loaded.shown_at == {"gamma": 3000.0}


def test_history_load_corrupt_file_returns_empty(tmp_path: Path) -> None:
    """A corrupt file must not blow up status rendering."""
    path = tmp_path / "history.json"
    path.write_text("{not json", encoding="utf-8")
    history = SuggestionHistory.load(path)
    assert history.shown_at == {}
    assert history.dismissed_at == {}


def test_history_save_silent_on_write_failure(tmp_path: Path) -> None:
    """If the path is a directory, save must not raise."""
    bad = tmp_path / "dir-not-file"
    bad.mkdir()
    history = SuggestionHistory(path=bad)
    history.mark_dismissed("alpha", 1.0)
    # Should not raise.
    history.save()


def test_default_rules_registry_is_non_empty() -> None:
    assert len(DEFAULT_RULES) == len(RULES_REGISTRY) >= 5
