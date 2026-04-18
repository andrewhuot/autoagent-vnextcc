"""Built-in suggestion rules.

Each rule is a pure function ``(ctx) -> list[Suggestion]``. A rule returns
an empty list when it doesn't fire — that keeps the call sites (``any()``,
``filter``) simple at the engine layer.

Rules are grouped by theme so the next person reading this file can find
"the optimize-without-eval nudge" without scrolling through sign-in tips.
"""

from __future__ import annotations

from cli.guidance.types import (
    PRIORITY_BLOCKER,
    PRIORITY_INFO,
    PRIORITY_WARN,
    GuidanceContext,
    Rule,
    Suggestion,
)


# ---------------------------------------------------------------------------
# Setup / environment health
# ---------------------------------------------------------------------------


def _rule_broken_workspace(ctx: GuidanceContext) -> list[Suggestion]:
    """Workspace didn't resolve — send the user to ``/doctor``.

    Fires only when the caller passed an explicit ``workspace_valid=False``
    signal. We don't infer validity from ``workspace is None`` because many
    callers (SDK, smoke tests) legitimately run without a workspace bound.
    """
    if ctx.workspace_valid:
        return []
    return [
        Suggestion(
            id="broken-workspace",
            title="Workspace did not resolve",
            body=(
                "AgentLab couldn't find a valid workspace at the current path. "
                "Run /doctor to see what's missing, or pass --workspace."
            ),
            severity="blocker",
            priority=PRIORITY_BLOCKER,
            command="/doctor",
        )
    ]


def _rule_provider_mock_mode(ctx: GuidanceContext) -> list[Suggestion]:
    """Provider silently fell back to mock — warn before an eval lies to them.

    Mock mode is a genuine operational state (demos, offline dev) so this is
    a *warn*, not a blocker: the user might have asked for it. But it's easy
    to end up there by forgetting an API key, and a mock eval that reports
    "100% pass" is worse than a crash.
    """
    if not ctx.mock_mode:
        return []
    reason = ctx.mock_reason or "no provider key was detected"
    return [
        Suggestion(
            id="provider-mock-mode",
            title="Provider is in mock mode",
            body=(
                f"Evals and optimize runs will use a mock model ({reason}). "
                "Set a real API key in Setup to run against live providers."
            ),
            severity="warn",
            priority=PRIORITY_WARN,
            command="/doctor",
            href="/setup",
        )
    ]


def _rule_provider_key_missing(ctx: GuidanceContext) -> list[Suggestion]:
    """Active provider is configured but its key env var is unset."""
    if ctx.provider_key_present or ctx.mock_mode:
        return []
    name = ctx.provider_name or "active provider"
    return [
        Suggestion(
            id="provider-key-missing",
            title=f"No API key for {name}",
            body=(
                f"The {name} provider is selected but its API key env var is "
                "unset. Add a key on the Setup page or switch providers."
            ),
            severity="warn",
            priority=PRIORITY_WARN,
            href="/setup",
        )
    ]


def _rule_doctor_failing(ctx: GuidanceContext) -> list[Suggestion]:
    if not ctx.doctor_failing:
        return []
    summary = ctx.doctor_summary or "one or more doctor checks failed"
    return [
        Suggestion(
            id="doctor-failing",
            title="Doctor is reporting problems",
            body=f"{summary} — run /doctor for the full list.",
            severity="warn",
            priority=PRIORITY_WARN,
            command="/doctor",
        )
    ]


# ---------------------------------------------------------------------------
# Workflow: eval / optimize / review / deploy
# ---------------------------------------------------------------------------


def _rule_run_eval_before_optimize(ctx: GuidanceContext) -> list[Suggestion]:
    """Operator is optimizing without a recent eval baseline.

    Fires when an optimize has run but no eval has been recorded since the
    workspace was created, OR when the last eval is materially older than
    the last optimize (staleness means the "did we improve?" comparison
    isn't trustworthy).
    """
    if ctx.last_optimize_at is None:
        return []
    last_eval = ctx.last_eval_at
    last_opt = ctx.last_optimize_at
    stale = last_eval is None or (last_eval + 1.0 < last_opt)
    if not stale:
        return []
    return [
        Suggestion(
            id="run-eval-before-optimize",
            title="Run an eval before optimizing",
            body=(
                "There's no recent eval baseline — optimize results won't be "
                "comparable. Run /eval first so the next cycle has a ground truth."
            ),
            severity="info",
            priority=PRIORITY_INFO,
            command="/eval",
            href="/evaluate",
        )
    ]


def _rule_pending_review_blocks_deploy(ctx: GuidanceContext) -> list[Suggestion]:
    if ctx.pending_review_cards <= 0:
        return []
    count = ctx.pending_review_cards
    noun = "card" if count == 1 else "cards"
    return [
        Suggestion(
            id="pending-review-blocks-deploy",
            title=f"{count} pending review {noun}",
            body=(
                "Deploy is gated on review approvals. Clear the queue with "
                "/review (or reject cards you don't want shipped)."
            ),
            severity="warn",
            priority=PRIORITY_WARN,
            command="/review",
            href="/review",
        )
    ]


def _rule_deployment_blocked(ctx: GuidanceContext) -> list[Suggestion]:
    if not ctx.deployment_blocked_reason:
        return []
    return [
        Suggestion(
            id="deployment-blocked",
            title="Deployment blocked",
            body=ctx.deployment_blocked_reason,
            severity="warn",
            priority=PRIORITY_WARN,
            href="/deploy",
        )
    ]


# ---------------------------------------------------------------------------
# Session / continuity
# ---------------------------------------------------------------------------


def _rule_resume_prior_session(ctx: GuidanceContext) -> list[Suggestion]:
    """Offer /resume when the workbench launched fresh but a prior session
    exists on disk. Suppresses when the active session matches the latest —
    i.e. the user is already in the "most recent" one.
    """
    latest = ctx.latest_session_id
    if not latest:
        return []
    if ctx.active_session_id == latest:
        return []
    if ctx.session_count <= 0:
        return []
    return [
        Suggestion(
            id="resume-prior-session",
            title="Resume your prior session?",
            body=(
                f"Found a prior workbench session ({latest}). Run /resume to "
                "rehydrate its transcript, goal, and pending actions."
            ),
            severity="info",
            priority=PRIORITY_INFO,
            command=f"/resume {latest}",
        )
    ]


# ---------------------------------------------------------------------------
# Public rule registry
# ---------------------------------------------------------------------------


DEFAULT_RULES: tuple[Rule, ...] = (
    Rule("broken-workspace", _rule_broken_workspace),
    Rule("doctor-failing", _rule_doctor_failing),
    Rule("provider-mock-mode", _rule_provider_mock_mode),
    Rule("provider-key-missing", _rule_provider_key_missing),
    Rule("pending-review-blocks-deploy", _rule_pending_review_blocks_deploy),
    Rule("deployment-blocked", _rule_deployment_blocked),
    Rule("run-eval-before-optimize", _rule_run_eval_before_optimize),
    Rule("resume-prior-session", _rule_resume_prior_session),
)


__all__ = ["DEFAULT_RULES"]
