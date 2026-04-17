"""Improvement workflows: `agentlab improve ...` commands.

Extracted from runner.py in R2 Slice B.0 as the first step of the
modular CLI refactor. This module owns the shape of `agentlab improve`
— any new subcommand (run, accept, measure, diff, lineage) will be
added here in Slices B.1–B.5.

The behavior and help text of every subcommand is preserved byte-for-
byte from the pre-extraction state; `tests/test_cli_help_golden.py`
locks that guarantee.

R4.5 extracts the 7 public ``improve`` subcommand bodies into module-level
``run_improve_<sub>_in_process`` pure functions so both the CLI and the
Workbench ``/improve`` slash handler can share business logic without
spawning a subprocess. Each function emits a terminal
``improve_<sub>_complete`` event for the slash handler to key session
updates off of, raises :class:`ImproveCommandError` on domain failures,
and accepts an optional ``text_writer`` for human-readable output.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

import click


def _runner_module():
    """Late-bound import of runner to avoid circular imports."""
    import runner as _r
    return _r


def _lookup_attempt_by_prefix(prefix: str, memory_db: str) -> list:
    """Return OptimizationAttempt rows whose attempt_id starts with *prefix*.

    Separate helper so tests can patch it and avoid a real OptimizationMemory
    fixture."""
    from optimizer.memory import OptimizationMemory
    memory = OptimizationMemory(db_path=memory_db)
    return [a for a in memory.get_all() if a.attempt_id.startswith(prefix)]


def _invoke_deploy(*, attempt_id: str, strategy: str, ctx=None) -> None:
    """Invoke `agentlab deploy` in-process with --attempt-id set.

    Kept as a thin helper so tests can patch it without running the real
    deployer machinery."""
    runner = _runner_module()
    if ctx is None:
        # Fall back to an implicit invocation; tests typically patch this.
        ctx = click.get_current_context()
    ctx.invoke(
        runner.cli.commands["deploy"],
        workflow=None,
        config_version=None,
        strategy=strategy,
        configs_dir=runner.CONFIGS_DIR,
        db=runner.DB_PATH,
        target="agentlab",
        project=None,
        location="global",
        agent_id=None,
        snapshot=None,
        credentials=None,
        output=None,
        push=False,
        dry_run=False,
        acknowledge=True,
        json_output=False,
        output_format="text",
        auto_review=False,
        force_deploy_degraded=False,
        force_reason=None,
        attempt_id=attempt_id,
        release_experiment_id=None,
    )


def _invoke_legacy_autofix(*, auto: bool, json_output: bool) -> None:
    """Run the pre-R2 autofix flow for back-compat with zero-arg `improve run`.

    Replicates the behavior the hidden command had before R2 Slice B.1.
    """
    runner = _runner_module()
    from cli.stream2_helpers import apply_autofix_to_config, json_response
    from optimizer.autofix import AutoFixEngine, AutoFixStore
    from optimizer.autofix_proposers import (
        CostOptimizationProposer,
        FailurePatternProposer,
        RegressionProposer,
    )
    from optimizer.diagnose_session import DiagnoseSession
    from optimizer.mutations import create_default_registry

    click.echo(click.style(
        "Tip: use `agentlab optimize --cycles 1` for the same result.",
        fg="yellow",
    ))

    runtime = runner.load_runtime_with_mode_preference()
    workspace = runner.discover_workspace()
    resolved_config = workspace.resolve_active_config() if workspace is not None else None
    config = resolved_config.config if resolved_config is not None else None
    eval_runner = runner._build_eval_runner(runtime, default_agent_config=config)
    score = eval_runner.run(config=config)

    store = runner.ConversationStore(db_path=runner.DB_PATH)
    observer = runner.Observer(store)
    deployer = runner.Deployer(configs_dir=runner.CONFIGS_DIR, store=store)
    diagnose_session = DiagnoseSession(store=store, observer=observer, deployer=deployer)
    diagnosis_summary = diagnose_session.start()

    proposal_store = AutoFixStore()
    engine = AutoFixEngine(
        proposers=[FailurePatternProposer(), RegressionProposer(), CostOptimizationProposer()],
        mutation_registry=create_default_registry(),
        store=proposal_store,
    )
    current_config = config or runner._ensure_active_config(deployer)
    proposals = engine.suggest(runner._build_failure_samples(store), current_config)
    proposal_payload = [
        {
            "proposal_id": proposal.proposal_id,
            "mutation_name": proposal.mutation_name,
            "surface": proposal.surface,
            "risk_class": proposal.risk_class,
            "expected_lift": proposal.expected_lift,
            "status": getattr(proposal, "status", "pending"),
        }
        for proposal in proposals
    ]

    applied: dict | None = None
    top_proposal = proposals[0] if proposals else None
    should_apply = bool(top_proposal and auto)
    if top_proposal and not auto and not json_output:
        should_apply = click.confirm(f"Apply the top proposal now ({top_proposal.proposal_id})?", default=False)

    if should_apply and top_proposal is not None:
        new_config, status_msg = engine.apply(top_proposal.proposal_id, current_config)
        if new_config:
            version_info = apply_autofix_to_config(top_proposal.proposal_id, new_config, configs_dir=runner.CONFIGS_DIR)
            applied = {
                "proposal_id": top_proposal.proposal_id,
                "status": status_msg,
                "config_version": version_info["version"],
                "config_path": version_info["path"],
            }
        else:
            applied = {
                "proposal_id": top_proposal.proposal_id,
                "status": status_msg,
                "config_version": None,
            }

    payload = {
        "eval": runner._score_to_dict(score),
        "diagnosis": diagnose_session.to_dict(),
        "diagnosis_summary": diagnosis_summary,
        "proposal_count": len(proposal_payload),
        "proposals": proposal_payload,
        "applied": applied,
    }
    if json_output:
        next_cmd = "agentlab status"
        if applied and applied.get("config_path"):
            next_cmd = f"agentlab eval run --config {applied['config_path']}"
        click.echo(json_response("ok", payload, next_cmd=next_cmd))
        return

    click.echo(click.style("\n\u2726 Improve", fg="cyan", bold=True))
    click.echo("")
    click.echo(f"Eval composite: {runner._score_to_dict(score)['composite']:.4f}")
    click.echo(diagnosis_summary)
    if proposal_payload:
        click.echo(f"\nSuggested fixes: {len(proposal_payload)}")
        top = proposal_payload[0]
        click.echo(
            f"  Top proposal: {top['proposal_id']} "
            f"({top['mutation_name']}, risk={top['risk_class']}, expected_lift={top['expected_lift']:.1%})"
        )
    else:
        click.echo("\nSuggested fixes: none")

    if applied is not None:
        click.echo("")
        click.echo(f"Applied: {applied['status']}")
        if applied.get("config_version") is not None:
            click.echo(f"  New config version: v{applied['config_version']:03d}")
            click.echo(f"  Path: {applied['config_path']}")
    else:
        click.echo("")
        click.echo("Next step:")
        click.echo("  agentlab autofix suggest")


def _run_post_deploy_eval(
    *, strict_live: bool = False, cases_path: str | None = None,
) -> float:
    """Run a fresh eval against the currently-active config and return its
    composite score. Separate helper so tests can patch it.

    When ``cases_path`` is provided it is forwarded as ``cases_dir=`` to
    :func:`runner._build_eval_runner`. Only directories of YAML cases are
    accepted today; single-file replay sets (``.jsonl`` etc.) are a TODO
    and raise :class:`ImproveCommandError` with a clear message.
    """
    if cases_path is not None:
        from pathlib import Path as _Path
        p = _Path(cases_path)
        if not p.exists():
            raise ImproveCommandError(
                f"Replay set not found or unsupported: {cases_path}"
            )
        if not p.is_dir():
            # Single files are not yet supported — only directories of
            # YAML cases. Surface a clear, directory-required message.
            raise ImproveCommandError(
                f"Replay set must be a directory of YAML cases "
                f"(got file): {cases_path}"
            )

    runner = _runner_module()
    runtime = runner.load_runtime_with_mode_preference()
    workspace = runner.discover_workspace()
    resolved_config = workspace.resolve_active_config() if workspace is not None else None
    config = resolved_config.config if resolved_config is not None else None
    if cases_path is not None:
        eval_runner = runner._build_eval_runner(
            runtime, default_agent_config=config, cases_dir=cases_path,
        )
    else:
        eval_runner = runner._build_eval_runner(
            runtime, default_agent_config=config,
        )
    # strict-live is enforced by the eval_runner's own gates; passing it through
    # is a no-op here but keeps the signature future-proof.
    score = eval_runner.run(config=config)
    return float(score.composite)


def _run_eval_step(*, ctx, config_path, strict_live, json_output):
    """Invoke `agentlab eval run --config <path> [--strict-live]` via ctx.invoke."""
    runner = _runner_module()
    eval_run_fn = runner.cli.commands["eval"].commands["run"]
    ctx.invoke(
        eval_run_fn,
        config_path=config_path,
        suite=None,
        dataset=None,
        dataset_split="all",
        category=None,
        output=None,
        instruction_overrides_path=None,
        real_agent=False,
        force_mock=False,
        require_live=False,
        strict_live=strict_live,
        json_output=json_output,
        output_format="json" if json_output else "text",
    )


def _run_optimize_step(*, ctx, config_path, cycles, mode, strict_live, json_output):
    """Invoke `agentlab optimize --config <path> --cycles N` via ctx.invoke."""
    runner = _runner_module()
    ctx.invoke(
        runner.cli.commands["optimize"],
        cycles=cycles,
        continuous=False,
        mode=mode,
        strategy=None,
        db=runner.DB_PATH,
        configs_dir=runner.CONFIGS_DIR,
        config_path=config_path,
        eval_run_id=None,
        require_eval_evidence=False,
        memory_db=runner.MEMORY_DB,
        full_auto=False,
        dry_run=False,
        json_output=json_output,
        max_budget_usd=None,
        strict_live=strict_live,
        output_format="json" if json_output else "text",
        ui=None,
    )
    return {}


def _present_top_attempt(*, result, json_output):
    """Print a summary of the top attempt.

    When `result` is empty, fall back to a pointer at `agentlab improve list`.
    """
    if json_output:
        click.echo(json.dumps({"status": "ok", **(result or {})}))
        return
    click.echo(click.style("\n\u2726 Improve", fg="cyan", bold=True))
    click.echo("")
    click.echo(
        "Next step: run `agentlab improve list` to review proposals, "
        "then `agentlab improve accept <attempt_id>`."
    )


# ---------------------------------------------------------------------------
# R4.5 — pure business-logic functions shared by CLI + `/improve` slash handler.
# ---------------------------------------------------------------------------


class ImproveCommandError(RuntimeError):
    """Raised when an ``improve`` subcommand fails with a user-facing error.

    The Click wrapper translates to ``click.ClickException``/``SystemExit``;
    the slash handler renders the message in the transcript.
    """


def _resolve_improve_db_paths(
    *,
    memory_db: str | None,
    lineage_db: str | None,
) -> tuple[str, str]:
    """Resolve ``memory_db`` / ``lineage_db`` from args + env + defaults.

    Mirrors the per-command resolution currently duplicated in each Click
    callback — the in-process functions centralise it.
    """
    runner = _runner_module()
    resolved_memory = memory_db or os.environ.get(
        "AGENTLAB_MEMORY_DB", runner.MEMORY_DB
    )
    resolved_lineage = lineage_db or os.environ.get(
        "AGENTLAB_IMPROVEMENT_LINEAGE_DB",
        ".agentlab/improvement_lineage.db",
    )
    return resolved_memory, resolved_lineage


def _find_unique_attempt(prefix: str, memory_db: str):
    """Look up an attempt by prefix; raise ``ImproveCommandError`` on miss/ambig."""
    matches = _lookup_attempt_by_prefix(prefix, memory_db)
    if not matches:
        raise ImproveCommandError(
            f"No improvement found with attempt_id prefix {prefix!r}."
        )
    if len(matches) > 1:
        raise ImproveCommandError(
            f"Ambiguous prefix {prefix!r} — matches {len(matches)} attempts."
        )
    return matches[0]


# --- Result dataclasses ----------------------------------------------------


@dataclass(frozen=True)
class ImproveRunResult:
    """Outcome of ``improve run`` (eval + optimize orchestration)."""

    attempt_id: str | None
    config_path: str | None
    eval_run_id: str | None
    status: str  # "ok" | "failed" | "cancelled"


@dataclass(frozen=True)
class ImproveAcceptResult:
    """Outcome of ``improve accept``: deploy + schedule measurement."""

    attempt_id: str | None
    deployment_id: str | None
    deployed_version: int | None
    strategy: str
    already_deployed: bool
    measurement_scheduled: bool
    status: str  # "ok" | "failed"


@dataclass(frozen=True)
class ImproveMeasureResult:
    """Outcome of ``improve measure``: post-deploy eval + composite_delta."""

    attempt_id: str | None
    measurement_id: str | None
    post_composite: float | None
    score_before: float | None
    composite_delta: float | None
    status: str  # "ok" | "failed"


@dataclass(frozen=True)
class ImproveDiffResult:
    """Outcome of ``improve diff``: rationale + config diff for an attempt."""

    attempt_id: str | None
    change_description: str | None
    config_section: str | None
    config_diff: str | None
    patch_bundle: Any | None
    score_before: float | None
    score_after: float | None
    status_raw: str | None
    diff_text: str | None
    status: str  # "ok" | "failed"


@dataclass(frozen=True)
class ImproveLineageResult:
    """Outcome of ``improve lineage``: full event chain for an attempt."""

    attempt_id: str | None
    status_classified: str | None
    eval_run_id: str | None
    deployment_id: str | None
    deployed_version: int | None
    measurement_id: str | None
    composite_delta: float | None
    score_before: float | None
    score_after: float | None
    parent_attempt_id: str | None
    rejection_reason: str | None
    rejection_detail: str | None
    rolled_back: bool
    nodes: tuple[dict[str, Any], ...]
    status: str  # "ok" | "failed"


@dataclass(frozen=True)
class ImproveListResult:
    """Outcome of ``improve list``: filtered + classified attempts."""

    attempts: tuple[dict[str, Any], ...]
    status: str  # "ok" | "failed"


@dataclass(frozen=True)
class ImproveShowResult:
    """Outcome of ``improve show``: one attempt's summary + lineage."""

    attempt_id: str | None
    attempt: dict[str, Any] | None
    status: str  # "ok" | "failed"


# --- Pure in-process runners ----------------------------------------------


def _emit(text_writer: Callable[[str], None] | None, message: str) -> None:
    if text_writer is not None:
        text_writer(message)


def run_improve_run_in_process(
    *,
    config_path: str | None,
    cycles: int = 1,
    mode: str | None = None,
    strict_live: bool = False,
    auto: bool = False,
    on_event: Callable[[dict[str, Any]], None],
    text_writer: Callable[[str], None] | None = None,
) -> ImproveRunResult:
    """Run ``improve run``: orchestrate eval → optimize for a config.

    When ``config_path`` is ``None`` this raises
    :class:`ImproveCommandError` — the zero-arg legacy autofix path is
    reachable only through the Click wrapper and does not support the
    in-process event seam.
    """
    if config_path is None:
        terminal = {
            "event": "improve_run_complete",
            "attempt_id": None,
            "config_path": None,
            "eval_run_id": None,
            "status": "failed",
        }
        on_event(terminal)
        raise ImproveCommandError(
            "improve run: a config path is required for the in-process path."
        )

    from cli.commands.eval import run_eval_in_process
    from cli.commands.optimize import run_optimize_in_process

    on_event({"event": "phase_started", "phase": "improve-run", "message": "Run eval → optimize"})
    _emit(text_writer, f"Improve run for {config_path}")

    # Run eval.
    eval_result = run_eval_in_process(
        config_path=config_path,
        suite=None,
        category=None,
        dataset=None,
        dataset_split="all",
        output_path=None,
        instruction_overrides_path=None,
        real_agent=False,
        force_mock=False,
        require_live=False,
        strict_live=strict_live,
        on_event=on_event,
        text_writer=text_writer,
    )

    # Run optimize with the config path (eval evidence is implicit via latest).
    optimize_result = run_optimize_in_process(
        cycles=cycles,
        continuous=False,
        mode=mode,
        strategy=None,
        config_path=config_path,
        eval_run_id=eval_result.run_id,
        require_eval_evidence=False,
        full_auto=False,
        dry_run=False,
        explain_strategy=False,
        max_budget_usd=None,
        strict_live=strict_live,
        force_mock=False,
        on_event=on_event,
        text_writer=text_writer,
    )

    on_event({"event": "phase_completed", "phase": "improve-run", "message": "Improve run complete"})
    terminal = {
        "event": "improve_run_complete",
        "attempt_id": optimize_result.attempt_id,
        "config_path": config_path,
        "eval_run_id": eval_result.run_id,
        "status": optimize_result.status,
    }
    on_event(terminal)
    return ImproveRunResult(
        attempt_id=optimize_result.attempt_id,
        config_path=config_path,
        eval_run_id=eval_result.run_id,
        status=optimize_result.status,
    )


def run_improve_list_in_process(
    *,
    status: str | None = None,
    reason: str | None = None,
    limit: int = 20,
    memory_db: str | None = None,
    lineage_db: str | None = None,
    on_event: Callable[[dict[str, Any]], None],
    text_writer: Callable[[str], None] | None = None,
) -> ImproveListResult:
    """Build the classified+filtered attempts list an ``improve list`` renders."""
    from optimizer.gates import RejectionReason, rejection_from_status
    from optimizer.improvement_lineage import ImprovementLineageStore
    from optimizer.memory import OptimizationMemory

    resolved_memory_db, resolved_lineage_db = _resolve_improve_db_paths(
        memory_db=memory_db, lineage_db=lineage_db,
    )

    valid_reasons = [r.value for r in RejectionReason]
    if reason is not None and reason not in valid_reasons:
        on_event({
            "event": "improve_list_complete",
            "attempts_total": 0,
            "status": "failed",
        })
        raise ImproveCommandError(
            f"invalid --reason value {reason!r}. "
            f"Valid values: {', '.join(valid_reasons)}"
        )

    memory = OptimizationMemory(db_path=resolved_memory_db)
    lineage = ImprovementLineageStore(db_path=resolved_lineage_db)
    attempts = sorted(memory.get_all(), key=lambda a: a.timestamp, reverse=True)

    def classify(raw_status: str, lineage_types: list[str]) -> str:
        if "promote" in lineage_types:
            return "measured" if "measurement" in lineage_types else "promoted"
        if "rollback" in lineage_types:
            return "rolled_back"
        if "deploy_canary" in lineage_types:
            return "deployed_canary"
        if raw_status.startswith("rejected"):
            return "rejected"
        if raw_status == "accepted":
            return "accepted"
        return "proposed"

    rows: list[dict[str, Any]] = []

    forced = os.environ.get("AGENTLAB_TEST_FORCE_REJECTION")
    if forced:
        try:
            forced_reason = RejectionReason(forced)
        except ValueError:
            pass
        else:
            rows.append({
                "attempt_id": "test-forced",
                "status": "rejected",
                "raw_status": f"rejected_{forced_reason.value}",
                "reason": forced_reason.value,
                "change": "[test] forced rejection via env var",
                "section": "prompt",
                "score_before": None,
                "score_after": None,
                "deployed_version": None,
                "measurement": None,
                "lineage": [],
            })

    for attempt in attempts:
        events = lineage.events_for(attempt.attempt_id)
        types = [e.event_type for e in events]
        classified = classify(attempt.status, types)
        if status and classified != status:
            continue
        try:
            row_reason = rejection_from_status(attempt.status).value
        except ValueError:
            row_reason = None
        rows.append(
            {
                "attempt_id": attempt.attempt_id,
                "status": classified,
                "raw_status": attempt.status,
                "reason": row_reason,
                "change": attempt.change_description,
                "section": attempt.config_section,
                "score_before": attempt.score_before,
                "score_after": attempt.score_after,
                "deployed_version": next(
                    (e.version for e in reversed(events)
                     if e.event_type in ("promote", "deploy_canary") and e.version is not None),
                    None,
                ),
                "measurement": next(
                    (e.payload for e in reversed(events) if e.event_type == "measurement"),
                    None,
                ),
                "lineage": types,
            }
        )
        if len(rows) >= limit:
            break

    if reason:
        rows = [r for r in rows if r.get("reason") == reason]

    if text_writer is not None:
        if not rows:
            _emit(text_writer, "No improvements found.")
        else:
            _emit(text_writer, click.style(
                f"Improvements ({len(rows)} shown):", fg="cyan", bold=True))
            _emit(text_writer,
                  f"{'ID':<10} {'STATUS':<18} {'REASON':<28} "
                  f"{'SECTION':<22} {'v':>4}  CHANGE")
            _emit(text_writer, "-" * 120)
            for row in rows:
                ver = (f"v{row['deployed_version']:03d}"
                       if row["deployed_version"] is not None else "—")
                _emit(text_writer,
                      f"{row['attempt_id'][:8]:<10} "
                      f"{row['status']:<18} "
                      f"{(row.get('reason') or '—')[:28]:<28} "
                      f"{(row['section'] or '—')[:22]:<22} "
                      f"{ver:>4}  "
                      f"{(row['change'] or '')[:60]}")

    terminal = {
        "event": "improve_list_complete",
        "attempts_total": len(rows),
        "status": "ok",
    }
    on_event(terminal)
    return ImproveListResult(attempts=tuple(rows), status="ok")


def run_improve_show_in_process(
    *,
    attempt_id: str,
    memory_db: str | None = None,
    lineage_db: str | None = None,
    on_event: Callable[[dict[str, Any]], None],
    text_writer: Callable[[str], None] | None = None,
) -> ImproveShowResult:
    """Build the per-attempt summary an ``improve show`` renders."""
    from optimizer.improvement_lineage import ImprovementLineageStore
    from optimizer.memory import OptimizationMemory

    resolved_memory_db, resolved_lineage_db = _resolve_improve_db_paths(
        memory_db=memory_db, lineage_db=lineage_db,
    )

    memory = OptimizationMemory(db_path=resolved_memory_db)
    lineage = ImprovementLineageStore(db_path=resolved_lineage_db)

    try:
        attempt = _find_unique_attempt(attempt_id, resolved_memory_db)
    except ImproveCommandError:
        # Re-lookup to preserve exact behaviour: get_all iterated once.
        matches = [a for a in memory.get_all() if a.attempt_id.startswith(attempt_id)]
        on_event({
            "event": "improve_show_complete",
            "attempt_id": attempt_id,
            "status": "failed",
        })
        if not matches:
            raise
        raise
    events = lineage.events_for(attempt.attempt_id)

    payload = {
        "attempt_id": attempt.attempt_id,
        "status": attempt.status,
        "change": attempt.change_description,
        "config_section": attempt.config_section,
        "score_before": attempt.score_before,
        "score_after": attempt.score_after,
        "timestamp": attempt.timestamp,
        "lineage": [
            {
                "event_type": e.event_type,
                "timestamp": e.timestamp,
                "version": e.version,
                "payload": e.payload,
            }
            for e in events
        ],
    }

    if text_writer is not None:
        _emit(text_writer, click.style(
            f"Improvement {attempt.attempt_id}", fg="cyan", bold=True))
        _emit(text_writer, f"  Change:   {attempt.change_description}")
        _emit(text_writer, f"  Section:  {attempt.config_section or '—'}")
        _emit(text_writer, f"  Status:   {attempt.status}")
        if attempt.score_before is not None or attempt.score_after is not None:
            before = (f"{attempt.score_before:.4f}"
                      if attempt.score_before is not None else "n/a")
            after = (f"{attempt.score_after:.4f}"
                     if attempt.score_after is not None else "n/a")
            _emit(text_writer, f"  Scores:   before={before} after={after}")
        _emit(text_writer, f"  Lineage ({len(events)} events):")
        for e in events:
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp))
            ver = f" v{e.version:03d}" if e.version is not None else ""
            _emit(text_writer, f"    [{when}] {e.event_type}{ver}")

    on_event({
        "event": "improve_show_complete",
        "attempt_id": attempt.attempt_id,
        "status": "ok",
    })
    return ImproveShowResult(
        attempt_id=attempt.attempt_id, attempt=payload, status="ok",
    )


def run_improve_accept_in_process(
    *,
    attempt_id: str,
    strategy: str = "canary",
    memory_db: str | None = None,
    lineage_db: str | None = None,
    on_event: Callable[[dict[str, Any]], None],
    text_writer: Callable[[str], None] | None = None,
    deploy_invoker: Callable[..., None] | None = None,
) -> ImproveAcceptResult:
    """Deploy an accepted improvement and schedule a post-deploy measurement.

    The optional ``deploy_invoker`` lets callers (notably the Click wrapper)
    keep its existing ctx-aware deploy path. The slash handler passes a
    thin wrapper over ``runner.cli``'s deploy command.
    """
    from optimizer.improvement_lineage import ImprovementLineageStore

    resolved_memory_db, resolved_lineage_db = _resolve_improve_db_paths(
        memory_db=memory_db, lineage_db=lineage_db,
    )

    attempt = _find_unique_attempt(attempt_id, resolved_memory_db)
    full_id = attempt.attempt_id

    lineage = ImprovementLineageStore(db_path=resolved_lineage_db)
    view = lineage.view_attempt(full_id)
    if view.deployment_id is not None:
        msg = (
            f"Attempt {full_id} is already deployed "
            f"(version {view.deployed_version}, deployment_id {view.deployment_id})."
        )
        _emit(text_writer, click.style(msg, fg="yellow"))
        on_event({
            "event": "improve_accept_complete",
            "attempt_id": full_id,
            "deployment_id": view.deployment_id,
            "deployed_version": view.deployed_version,
            "strategy": strategy,
            "already_deployed": True,
            "measurement_scheduled": False,
            "status": "ok",
        })
        return ImproveAcceptResult(
            attempt_id=full_id,
            deployment_id=view.deployment_id,
            deployed_version=view.deployed_version,
            strategy=strategy,
            already_deployed=True,
            measurement_scheduled=False,
            status="ok",
        )

    # Deploy via the injected invoker (Click wrapper uses ctx; slash uses a
    # thin wrapper). Any exception propagates.
    if deploy_invoker is not None:
        deploy_invoker(attempt_id=full_id, strategy=strategy)
    else:
        _invoke_deploy(attempt_id=full_id, strategy=strategy, ctx=None)

    # Schedule measurement (failure must not break accept).
    try:
        lineage.record_measurement(
            attempt_id=full_id,
            measurement_id=f"scheduled-{full_id}",
            composite_delta=None,
            scheduled=True,
        )
        measurement_scheduled = True
    except Exception:
        measurement_scheduled = False

    # Re-view to pick up the deployment row.
    view_after = lineage.view_attempt(full_id)

    if text_writer is not None:
        _emit(text_writer, click.style(
            f"\n\u2713 Accepted {full_id}", fg="green", bold=True))
        _emit(text_writer, f"  Deployed via {strategy}.")
        _emit(text_writer,
              f"  Next: run `agentlab improve measure {full_id}` "
              f"after the canary window to record composite_delta.")

    on_event({
        "event": "improve_accept_complete",
        "attempt_id": full_id,
        "deployment_id": view_after.deployment_id,
        "deployed_version": view_after.deployed_version,
        "strategy": strategy,
        "already_deployed": False,
        "measurement_scheduled": measurement_scheduled,
        "status": "ok",
    })
    return ImproveAcceptResult(
        attempt_id=full_id,
        deployment_id=view_after.deployment_id,
        deployed_version=view_after.deployed_version,
        strategy=strategy,
        already_deployed=False,
        measurement_scheduled=measurement_scheduled,
        status="ok",
    )


def _maybe_record_calibration(
    attempt: Any,
    full_id: str,
    composite_delta: float | None,
    *,
    text_writer: Callable[[str], None] | None = None,
) -> bool | None:
    """Write a CalibrationStore row when the attempt has all three
    calibration fields set (predicted_effectiveness, strategy_surface,
    strategy_name) AND ``composite_delta`` is not None.

    Returns:
      - ``True``: row written.
      - ``False``: skipped because the attempt is missing one of the
        three calibration fields (legacy attempt).
      - ``None``: skipped due to missing ``composite_delta`` or because
        the underlying CalibrationStore call failed (warning emitted).
    """
    if composite_delta is None:
        # Don't fabricate 0.0 — skip with a log line so calibration
        # history stays trustworthy.
        logger = logging.getLogger(__name__)
        logger.info(
            "calibration skipped: attempt %s has no composite_delta "
            "(missing score_before)",
            full_id,
        )
        return None

    if (
        getattr(attempt, "predicted_effectiveness", None) is not None
        and getattr(attempt, "strategy_surface", None)
        and getattr(attempt, "strategy_name", None)
    ):
        try:
            from optimizer.calibration import CalibrationStore
            calibration_db = os.environ.get(
                "AGENTLAB_CALIBRATION_DB",
                ".agentlab/calibration.db",
            )
            store = CalibrationStore(db_path=calibration_db)
            store.record(
                attempt_id=full_id,
                surface=attempt.strategy_surface,
                strategy=attempt.strategy_name,
                predicted_effectiveness=float(
                    attempt.predicted_effectiveness
                ),
                actual_delta=float(composite_delta),
            )
            return True
        except Exception as exc:
            _emit(text_writer, click.style(
                f"Warning: failed to record calibration: {exc}",
                fg="yellow"))
            return None

    logger = logging.getLogger(__name__)
    logger.info(
        "calibration skipped: attempt %s missing predicted_effectiveness "
        "or strategy_surface or strategy_name (legacy attempt?)",
        full_id,
    )
    return False


def run_improve_measure_in_process(
    *,
    attempt_id: str,
    strict_live: bool = False,
    memory_db: str | None = None,
    lineage_db: str | None = None,
    cases_path: str | None = None,
    on_event: Callable[[dict[str, Any]], None],
    text_writer: Callable[[str], None] | None = None,
) -> ImproveMeasureResult:
    """Run a post-deploy eval and record composite_delta for an attempt.

    When ``cases_path`` is set the post-deploy eval runs against that
    directory of YAML cases instead of the workspace default. Default
    invocation (``cases_path=None``) is byte-identical to before.
    """
    from optimizer.improvement_lineage import ImprovementLineageStore

    resolved_memory_db, resolved_lineage_db = _resolve_improve_db_paths(
        memory_db=memory_db, lineage_db=lineage_db,
    )

    attempt = _find_unique_attempt(attempt_id, resolved_memory_db)
    full_id = attempt.attempt_id

    lineage = ImprovementLineageStore(db_path=resolved_lineage_db)
    view = lineage.view_attempt(full_id)
    if view.deployment_id is None:
        on_event({
            "event": "improve_measure_complete",
            "attempt_id": full_id,
            "measurement_id": None,
            "post_composite": None,
            "score_before": None,
            "composite_delta": None,
            "cases_path": cases_path,
            "status": "failed",
        })
        raise ImproveCommandError(
            f"Attempt {full_id} has not been deployed yet. "
            f"Run `agentlab improve accept {full_id}` first."
        )

    post_composite = _run_post_deploy_eval(
        strict_live=strict_live, cases_path=cases_path,
    )

    score_before = getattr(attempt, "score_before", None)
    if score_before is None:
        composite_delta = None
        _emit(text_writer, click.style(
            f"Warning: attempt {full_id} has no recorded score_before; "
            f"composite_delta will be None.",
            fg="yellow"))
    else:
        composite_delta = post_composite - float(score_before)

    measurement_id = f"meas-{uuid.uuid4().hex[:8]}"
    try:
        lineage.record_measurement(
            attempt_id=full_id,
            measurement_id=measurement_id,
            composite_delta=composite_delta,
            post_composite=post_composite,
            score_before=score_before,
        )
    except Exception as exc:
        _emit(text_writer, click.style(
            f"Warning: failed to record measurement event: {exc}",
            fg="yellow"))

    # R6.B.2d: write calibration row when the attempt carries the three
    # calibration fields and produced a composite_delta.
    calibration_recorded = _maybe_record_calibration(
        attempt, full_id, composite_delta, text_writer=text_writer,
    )

    if text_writer is not None:
        _emit(text_writer, click.style(
            f"\n\u2713 Measured {full_id}", fg="green", bold=True))
        _emit(text_writer, f"  Post-deploy composite: {post_composite:.4f}")
        if composite_delta is not None:
            _emit(text_writer,
                  f"  Delta vs score_before ({score_before:.4f}): "
                  f"{composite_delta:+.4f}")
        _emit(text_writer, f"  measurement_id: {measurement_id}")

    on_event({
        "event": "improve_measure_complete",
        "attempt_id": full_id,
        "measurement_id": measurement_id,
        "post_composite": post_composite,
        "score_before": score_before,
        "composite_delta": composite_delta,
        "cases_path": cases_path,
        "calibration_recorded": calibration_recorded,
        "status": "ok",
    })
    return ImproveMeasureResult(
        attempt_id=full_id,
        measurement_id=measurement_id,
        post_composite=post_composite,
        score_before=score_before,
        composite_delta=composite_delta,
        status="ok",
    )


def run_improve_diff_in_process(
    *,
    attempt_id: str,
    memory_db: str | None = None,
    on_event: Callable[[dict[str, Any]], None],
    text_writer: Callable[[str], None] | None = None,
) -> ImproveDiffResult:
    """Build the rationale + config diff payload ``improve diff`` renders."""
    resolved_memory_db, _ = _resolve_improve_db_paths(
        memory_db=memory_db, lineage_db=None,
    )

    attempt = _find_unique_attempt(attempt_id, resolved_memory_db)

    patch_bundle_parsed: Any | None = None
    raw_bundle = getattr(attempt, "patch_bundle", "") or ""
    if raw_bundle:
        try:
            patch_bundle_parsed = json.loads(raw_bundle)
        except Exception:
            patch_bundle_parsed = None

    score_before = getattr(attempt, "score_before", None)
    score_after = getattr(attempt, "score_after", None)
    status_raw = getattr(attempt, "status", None)
    config_section = getattr(attempt, "config_section", None)

    if text_writer is not None:
        _emit(text_writer, click.style(
            f"\nImprovement {attempt.attempt_id}", fg="cyan", bold=True))
        _emit(text_writer, f"  Section:  {config_section or '—'}")
        _emit(text_writer, f"  Status:   {status_raw or '—'}")
        if score_before is not None or score_after is not None:
            before = f"{score_before:.4f}" if score_before is not None else "n/a"
            after = f"{score_after:.4f}" if score_after is not None else "n/a"
            _emit(text_writer, f"  Scores:   before={before} after={after}")
        _emit(text_writer, "")
        _emit(text_writer, click.style("Rationale:", bold=True))
        _emit(text_writer, f"  {attempt.change_description or '(no description)'}")
        _emit(text_writer, "")
        _emit(text_writer, click.style("Config diff:", bold=True))
        if attempt.config_diff:
            for line in attempt.config_diff.splitlines():
                if line.startswith("+"):
                    _emit(text_writer, click.style(line, fg="green"))
                elif line.startswith("-"):
                    _emit(text_writer, click.style(line, fg="red"))
                else:
                    _emit(text_writer, line)
        else:
            _emit(text_writer, "  (no diff recorded — empty config_diff)")
        if patch_bundle_parsed is not None:
            _emit(text_writer, "")
            _emit(text_writer, click.style("Patch bundle:", bold=True))
            _emit(text_writer, json.dumps(patch_bundle_parsed, indent=2, sort_keys=True))

    on_event({
        "event": "improve_diff_complete",
        "attempt_id": attempt.attempt_id,
        "config_diff_len": len(attempt.config_diff or ""),
        "status": "ok",
    })
    return ImproveDiffResult(
        attempt_id=attempt.attempt_id,
        change_description=attempt.change_description,
        config_section=config_section,
        config_diff=attempt.config_diff,
        patch_bundle=patch_bundle_parsed,
        score_before=score_before,
        score_after=score_after,
        status_raw=status_raw,
        diff_text=attempt.config_diff,
        status="ok",
    )


def run_improve_lineage_in_process(
    *,
    attempt_id: str,
    memory_db: str | None = None,
    lineage_db: str | None = None,
    on_event: Callable[[dict[str, Any]], None],
    text_writer: Callable[[str], None] | None = None,
) -> ImproveLineageResult:
    """Render the full lineage chain for an attempt."""
    from optimizer.improvement_lineage import ImprovementLineageStore

    resolved_memory_db, resolved_lineage_db = _resolve_improve_db_paths(
        memory_db=memory_db, lineage_db=lineage_db,
    )

    attempt = _find_unique_attempt(attempt_id, resolved_memory_db)
    full_id = attempt.attempt_id

    store = ImprovementLineageStore(db_path=resolved_lineage_db)
    view = store.view_attempt(full_id)

    nodes = tuple(
        {
            "event_type": e.event_type,
            "timestamp": e.timestamp,
            "version": e.version,
            "payload": e.payload,
        }
        for e in view.events
    )

    if text_writer is not None:
        _emit(text_writer, click.style(
            f"\nLineage for {full_id}", fg="cyan", bold=True))
        _emit(text_writer,
              f"  Section:  {getattr(attempt, 'config_section', None) or '—'}")
        _emit(text_writer,
              f"  Status:   {view.status or getattr(attempt, 'status', '—')}")
        if view.eval_run_id:
            _emit(text_writer, f"  Eval run: {view.eval_run_id}")
        if view.parent_attempt_id:
            _emit(text_writer, f"  Parent:   {view.parent_attempt_id}")
        if view.score_before is not None or view.score_after is not None:
            before = (f"{view.score_before:.4f}"
                      if view.score_before is not None else "n/a")
            after = (f"{view.score_after:.4f}"
                     if view.score_after is not None else "n/a")
            _emit(text_writer, f"  Scores:   before={before} after={after}")
        if view.rejection_reason:
            _emit(text_writer, click.style(
                f"  Rejected: {view.rejection_reason} — {view.rejection_detail or ''}",
                fg="red"))
        if view.deployment_id:
            ver = (f"v{view.deployed_version:03d}"
                   if view.deployed_version is not None else "")
            _emit(text_writer, f"  Deployed: {view.deployment_id} {ver}".rstrip())
        if view.rolled_back:
            _emit(text_writer, click.style("  ⚠ rolled back", fg="yellow"))
        if view.measurement_id:
            delta = view.composite_delta
            delta_str = f"{delta:+.4f}" if delta is not None else "pending"
            _emit(text_writer, f"  Measured: {view.measurement_id} Δ={delta_str}")
        _emit(text_writer, "")
        _emit(text_writer, click.style("Events:", bold=True))
        if not view.events:
            _emit(text_writer, "  (no lineage events recorded for this attempt)")
        else:
            for e in view.events:
                when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp))
                ver = f" v{e.version:03d}" if e.version is not None else ""
                extra = ""
                if e.event_type == "rejection":
                    extra = (f" — {e.payload.get('reason', '')}: "
                             f"{e.payload.get('detail', '')}")
                elif e.event_type == "measurement":
                    delta = e.payload.get("composite_delta")
                    if delta is not None:
                        extra = f" — Δ={delta:+.4f}"
                    elif e.payload.get("scheduled"):
                        extra = " — scheduled (pending)"
                elif e.event_type == "eval_run":
                    cs = e.payload.get("composite_score")
                    if cs is not None:
                        extra = f" — composite={cs:.4f}"
                _emit(text_writer, f"  [{when}] {e.event_type}{ver}{extra}")

    on_event({
        "event": "improve_lineage_complete",
        "attempt_id": full_id,
        "event_count": len(nodes),
        "status": "ok",
    })
    return ImproveLineageResult(
        attempt_id=full_id,
        status_classified=view.status or getattr(attempt, "status", None),
        eval_run_id=view.eval_run_id,
        deployment_id=view.deployment_id,
        deployed_version=view.deployed_version,
        measurement_id=view.measurement_id,
        composite_delta=view.composite_delta,
        score_before=view.score_before,
        score_after=view.score_after,
        parent_attempt_id=view.parent_attempt_id,
        rejection_reason=view.rejection_reason,
        rejection_detail=view.rejection_detail,
        rolled_back=view.rolled_back,
        nodes=nodes,
        status="ok",
    )


def register_improve_commands(cli: click.Group) -> None:
    """Register the `improve` group and its subcommands on *cli*.

    Runner-internal symbols are imported lazily here to avoid a circular
    dependency with runner.py.
    """
    import runner  # late-bound; runner finishes its own module init before
                   # calling register_all() at the bottom of its module.

    DefaultCommandGroup = runner.DefaultCommandGroup
    MEMORY_DB = runner.MEMORY_DB
    DB_PATH = runner.DB_PATH
    CONFIGS_DIR = runner.CONFIGS_DIR

    @cli.group("improve", cls=DefaultCommandGroup, default_command="run", default_on_empty=True)
    def improve_group() -> None:
        """Improvement workflows and compatibility aliases."""


    @improve_group.command("run")
    @click.argument("config_path", required=False, type=click.Path())
    @click.option("--cycles", default=1, type=int, show_default=True,
                  help="Number of optimization cycles.")
    @click.option("--mode", default=None,
                  type=click.Choice(["standard", "advanced", "research"]),
                  help="Optimization mode.")
    @click.option("--strict-live/--no-strict-live", default=False,
                  help="Exit non-zero (12) if eval or optimize would run in mock mode.")
    @click.option("--auto", is_flag=True,
                  help="(Legacy, zero-arg mode only) apply top autofix proposal.")
    @click.option("--json", "json_output", "-j", is_flag=True,
                  help="Output as JSON.")
    @click.pass_context
    def improve_run(
        ctx: click.Context,
        config_path: str | None,
        cycles: int,
        mode: str | None,
        strict_live: bool,
        auto: bool,
        json_output: bool,
    ) -> None:
        """Run the improve loop: eval, optimize 1 cycle, present top proposal.

        With no config argument, prints a deprecation notice and falls back
        to the legacy autofix workflow. Prefer `agentlab autofix apply`.
        """
        if config_path is None:
            click.echo(click.style(
                "Note: `agentlab improve run` with no arguments is deprecated. "
                "Use `agentlab autofix apply` for the legacy autofix workflow.",
                fg="yellow",
            ), err=True)
            _invoke_legacy_autofix(auto=auto, json_output=json_output)
            return

        _run_eval_step(
            ctx=ctx, config_path=config_path,
            strict_live=strict_live, json_output=json_output,
        )
        result = _run_optimize_step(
            ctx=ctx, config_path=config_path,
            cycles=cycles, mode=mode,
            strict_live=strict_live, json_output=json_output,
        )
        _present_top_attempt(result=result, json_output=json_output)


    @improve_group.command("list")
    @click.option("--status", default=None, help="Filter by classified status (proposed, pending_review, accepted, rejected, deployed_canary, promoted, rolled_back, measured).")
    @click.option("--reason", default=None, help="Filter rejected rows by RejectionReason value (e.g. regression_detected, safety_violation).")
    @click.option("--limit", default=20, show_default=True, type=int, help="Max rows to show.")
    @click.option("--memory-db", default=MEMORY_DB, show_default=True, help="Optimizer memory DB.")
    @click.option("--lineage-db", default=os.environ.get("AGENTLAB_IMPROVEMENT_LINEAGE_DB", ".agentlab/improvement_lineage.db"), show_default=True, help="Improvement lineage DB.")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    def improve_list(
        status: str | None,
        reason: str | None,
        limit: int,
        memory_db: str,
        lineage_db: str,
        json_output: bool,
    ) -> None:
        """List improvements with their lineage (proposal -> deploy -> measurement)."""
        from optimizer.gates import RejectionReason, rejection_from_status
        from optimizer.improvement_lineage import ImprovementLineageStore
        from optimizer.memory import OptimizationMemory

        valid_reasons = [r.value for r in RejectionReason]
        if reason is not None and reason not in valid_reasons:
            click.echo(
                f"Error: invalid --reason value {reason!r}. "
                f"Valid values: {', '.join(valid_reasons)}",
                err=True,
            )
            sys.exit(1)

        memory = OptimizationMemory(db_path=memory_db)
        lineage = ImprovementLineageStore(db_path=lineage_db)

        attempts = sorted(memory.get_all(), key=lambda a: a.timestamp, reverse=True)

        def classify(raw_status: str, lineage_types: list[str]) -> str:
            if "promote" in lineage_types:
                return "measured" if "measurement" in lineage_types else "promoted"
            if "rollback" in lineage_types:
                return "rolled_back"
            if "deploy_canary" in lineage_types:
                return "deployed_canary"
            if raw_status.startswith("rejected"):
                return "rejected"
            if raw_status == "accepted":
                return "accepted"
            return "proposed"

        rows: list[dict] = []

        forced = os.environ.get("AGENTLAB_TEST_FORCE_REJECTION")
        if forced:
            try:
                forced_reason = RejectionReason(forced)
            except ValueError:
                pass  # silently ignore invalid forced value in test hook
            else:
                rows.append({
                    "attempt_id": "test-forced",
                    "status": "rejected",
                    "raw_status": f"rejected_{forced_reason.value}",
                    "reason": forced_reason.value,
                    "change": "[test] forced rejection via env var",
                    "section": "prompt",
                    "score_before": None,
                    "score_after": None,
                    "deployed_version": None,
                    "measurement": None,
                    "lineage": [],
                })

        for attempt in attempts:
            events = lineage.events_for(attempt.attempt_id)
            types = [e.event_type for e in events]
            classified = classify(attempt.status, types)
            if status and classified != status:
                continue
            try:
                row_reason = rejection_from_status(attempt.status).value
            except ValueError:
                row_reason = None
            rows.append(
                {
                    "attempt_id": attempt.attempt_id,
                    "status": classified,
                    "raw_status": attempt.status,
                    "reason": row_reason,
                    "change": attempt.change_description,
                    "section": attempt.config_section,
                    "score_before": attempt.score_before,
                    "score_after": attempt.score_after,
                    "deployed_version": next(
                        (e.version for e in reversed(events) if e.event_type in ("promote", "deploy_canary") and e.version is not None),
                        None,
                    ),
                    "measurement": next(
                        (e.payload for e in reversed(events) if e.event_type == "measurement"),
                        None,
                    ),
                    "lineage": types,
                }
            )
            if len(rows) >= limit:
                break

        if reason:
            rows = [r for r in rows if r.get("reason") == reason]

        if json_output:
            click.echo(json.dumps({"total": len(rows), "items": rows}, indent=2))
            return

        if not rows:
            click.echo("No improvements found.")
            return

        click.echo(click.style(f"Improvements ({len(rows)} shown):", fg="cyan", bold=True))
        click.echo(
            f"{'ID':<10} {'STATUS':<18} {'REASON':<28} {'SECTION':<22} {'v':>4}  CHANGE"
        )
        click.echo("-" * 120)
        for row in rows:
            ver = f"v{row['deployed_version']:03d}" if row["deployed_version"] is not None else "—"
            click.echo(
                f"{row['attempt_id'][:8]:<10} "
                f"{row['status']:<18} "
                f"{(row.get('reason') or '—')[:28]:<28} "
                f"{(row['section'] or '—')[:22]:<22} "
                f"{ver:>4}  "
                f"{(row['change'] or '')[:60]}"
            )


    @improve_group.command("show")
    @click.argument("attempt_id", required=True)
    @click.option("--memory-db", default=MEMORY_DB, show_default=True, help="Optimizer memory DB.")
    @click.option("--lineage-db", default=os.environ.get("AGENTLAB_IMPROVEMENT_LINEAGE_DB", ".agentlab/improvement_lineage.db"), show_default=True, help="Improvement lineage DB.")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    def improve_show(attempt_id: str, memory_db: str, lineage_db: str, json_output: bool) -> None:
        """Show a single improvement with its full lineage."""
        from optimizer.improvement_lineage import ImprovementLineageStore
        from optimizer.memory import OptimizationMemory

        memory = OptimizationMemory(db_path=memory_db)
        lineage = ImprovementLineageStore(db_path=lineage_db)

        matches = [a for a in memory.get_all() if a.attempt_id.startswith(attempt_id)]
        if not matches:
            click.echo(click.style(f"No improvement with attempt_id prefix {attempt_id!r}", fg="red"), err=True)
            raise SystemExit(1)
        if len(matches) > 1:
            click.echo(click.style(f"Ambiguous prefix {attempt_id!r}, matches {len(matches)} improvements.", fg="yellow"), err=True)
            raise SystemExit(1)

        attempt = matches[0]
        events = lineage.events_for(attempt.attempt_id)

        if json_output:
            click.echo(json.dumps(
                {
                    "attempt_id": attempt.attempt_id,
                    "status": attempt.status,
                    "change": attempt.change_description,
                    "config_section": attempt.config_section,
                    "score_before": attempt.score_before,
                    "score_after": attempt.score_after,
                    "timestamp": attempt.timestamp,
                    "lineage": [
                        {
                            "event_type": e.event_type,
                            "timestamp": e.timestamp,
                            "version": e.version,
                            "payload": e.payload,
                        }
                        for e in events
                    ],
                },
                indent=2,
            ))
            return

        click.echo(click.style(f"Improvement {attempt.attempt_id}", fg="cyan", bold=True))
        click.echo(f"  Change:   {attempt.change_description}")
        click.echo(f"  Section:  {attempt.config_section or '—'}")
        click.echo(f"  Status:   {attempt.status}")
        if attempt.score_before is not None or attempt.score_after is not None:
            before = f"{attempt.score_before:.4f}" if attempt.score_before is not None else "n/a"
            after = f"{attempt.score_after:.4f}" if attempt.score_after is not None else "n/a"
            click.echo(f"  Scores:   before={before} after={after}")
        click.echo(f"  Lineage ({len(events)} events):")
        for e in events:
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp))
            ver = f" v{e.version:03d}" if e.version is not None else ""
            click.echo(f"    [{when}] {e.event_type}{ver}")


    @improve_group.command("accept")
    @click.argument("attempt_id", required=True)
    @click.option("--strategy", type=click.Choice(["canary", "immediate"]),
                  default="canary", show_default=True,
                  help="Deployment strategy to use.")
    @click.option("--memory-db", default=None,
                  help="Optimizer memory DB. Defaults to $AGENTLAB_MEMORY_DB or "
                       "optimizer_memory.db.")
    @click.option("--lineage-db", default=None,
                  help="Improvement lineage DB. Defaults to "
                       "$AGENTLAB_IMPROVEMENT_LINEAGE_DB or "
                       ".agentlab/improvement_lineage.db.")
    @click.option("--json", "json_output", "-j", is_flag=True,
                  help="Output as JSON.")
    @click.pass_context
    def improve_accept(
        ctx,
        attempt_id: str,
        strategy: str,
        memory_db: str | None,
        lineage_db: str | None,
        json_output: bool,
    ) -> None:
        """Deploy an accepted improvement and schedule a post-deploy measurement.

        The attempt_id may be a prefix; it must uniquely identify one attempt.
        """
        from optimizer.improvement_lineage import ImprovementLineageStore

        # Resolve DB paths at call time so env vars set by tests/harness win.
        if memory_db is None:
            memory_db = os.environ.get("AGENTLAB_MEMORY_DB", MEMORY_DB)
        if lineage_db is None:
            lineage_db = os.environ.get(
                "AGENTLAB_IMPROVEMENT_LINEAGE_DB",
                ".agentlab/improvement_lineage.db",
            )

        matches = _lookup_attempt_by_prefix(attempt_id, memory_db)
        if not matches:
            click.echo(click.style(
                f"No improvement found with attempt_id prefix {attempt_id!r}.",
                fg="red"), err=True)
            raise click.exceptions.Exit(1)
        if len(matches) > 1:
            click.echo(click.style(
                f"Ambiguous prefix {attempt_id!r} — matches {len(matches)} attempts. "
                f"Use more characters.",
                fg="yellow"), err=True)
            raise click.exceptions.Exit(1)

        attempt = matches[0]
        full_id = attempt.attempt_id

        lineage = ImprovementLineageStore(db_path=lineage_db)
        view = lineage.view_attempt(full_id)
        if view.deployment_id is not None:
            msg = (f"Attempt {full_id} is already deployed "
                   f"(version {view.deployed_version}, deployment_id {view.deployment_id}).")
            if json_output:
                import json as _json
                click.echo(_json.dumps({
                    "status": "ok",
                    "attempt_id": full_id,
                    "already_deployed": True,
                    "deployment_id": view.deployment_id,
                    "deployed_version": view.deployed_version,
                }))
            else:
                click.echo(click.style(msg, fg="yellow"))
            return

        # Deploy. Any exception propagates (and should fail the command).
        _invoke_deploy(attempt_id=full_id, strategy=strategy, ctx=ctx)

        # Schedule measurement: write a measurement event with composite_delta=None
        # and scheduled=True so improve lineage can show "measurement pending".
        try:
            lineage.record_measurement(
                attempt_id=full_id,
                measurement_id=f"scheduled-{full_id}",
                composite_delta=None,
                scheduled=True,
            )
        except Exception:
            pass  # Measurement scheduling failure must not break accept.

        if json_output:
            import json as _json
            click.echo(_json.dumps({
                "status": "ok",
                "attempt_id": full_id,
                "strategy": strategy,
                "measurement_scheduled": True,
            }))
        else:
            click.echo(click.style(
                f"\n\u2713 Accepted {full_id}",
                fg="green", bold=True))
            click.echo(f"  Deployed via {strategy}.")
            click.echo(f"  Next: run `agentlab improve measure {full_id}` "
                       f"after the canary window to record composite_delta.")


    @improve_group.command("measure")
    @click.argument("attempt_id", required=True)
    @click.option("--strict-live/--no-strict-live", default=False,
                  help="Exit non-zero (12) if eval would run in mock mode.")
    @click.option("--memory-db", default=None,
                  help="Optimizer memory DB (default: AGENTLAB_MEMORY_DB or optimizer_memory.db).")
    @click.option("--lineage-db", default=None,
                  help="Improvement lineage DB (default: AGENTLAB_IMPROVEMENT_LINEAGE_DB or .agentlab/improvement_lineage.db).")
    @click.option("--replay-set", "replay_set", default=None,
                  type=str,
                  help="Path to a directory of replay eval cases. "
                       "When set, measures against this set instead "
                       "of the workspace default.")
    @click.option("--json", "json_output", "-j", is_flag=True,
                  help="Output as JSON.")
    def improve_measure(
        attempt_id: str,
        strict_live: bool,
        memory_db: str | None,
        lineage_db: str | None,
        replay_set: str | None,
        json_output: bool,
    ) -> None:
        """Run a post-deploy eval and record composite_delta for an attempt."""
        import json as _json
        import uuid
        from optimizer.improvement_lineage import ImprovementLineageStore

        resolved_memory_db = memory_db or os.environ.get("AGENTLAB_MEMORY_DB", MEMORY_DB)
        resolved_lineage_db = lineage_db or os.environ.get(
            "AGENTLAB_IMPROVEMENT_LINEAGE_DB",
            ".agentlab/improvement_lineage.db",
        )

        matches = _lookup_attempt_by_prefix(attempt_id, resolved_memory_db)
        if not matches:
            click.echo(click.style(
                f"No improvement found with attempt_id prefix {attempt_id!r}.",
                fg="red"), err=True)
            raise click.exceptions.Exit(1)
        if len(matches) > 1:
            click.echo(click.style(
                f"Ambiguous prefix {attempt_id!r} — matches {len(matches)} attempts.",
                fg="yellow"), err=True)
            raise click.exceptions.Exit(1)

        attempt = matches[0]
        full_id = attempt.attempt_id

        lineage = ImprovementLineageStore(db_path=resolved_lineage_db)
        view = lineage.view_attempt(full_id)
        if view.deployment_id is None:
            click.echo(click.style(
                f"Attempt {full_id} has not been deployed yet. "
                f"Run `agentlab improve accept {full_id}` first.",
                fg="red"), err=True)
            raise click.exceptions.Exit(1)

        if replay_set is not None:
            click.echo(f"Using replay set: {replay_set}")

        try:
            post_composite = _run_post_deploy_eval(
                strict_live=strict_live, cases_path=replay_set,
            )
        except ImproveCommandError as exc:
            click.echo(click.style(str(exc), fg="red"), err=True)
            raise click.exceptions.Exit(1)

        score_before = getattr(attempt, "score_before", None)
        if score_before is None:
            composite_delta = None
            click.echo(click.style(
                f"Warning: attempt {full_id} has no recorded score_before; "
                f"composite_delta will be None.",
                fg="yellow"), err=True)
        else:
            composite_delta = post_composite - float(score_before)

        measurement_id = f"meas-{uuid.uuid4().hex[:8]}"
        try:
            lineage.record_measurement(
                attempt_id=full_id,
                measurement_id=measurement_id,
                composite_delta=composite_delta,
                post_composite=post_composite,
                score_before=score_before,
            )
        except Exception as exc:
            click.echo(click.style(
                f"Warning: failed to record measurement event: {exc}",
                fg="yellow"), err=True)

        # R6.B.2d: write calibration row when fields are present.
        def _stderr_writer(line: str) -> None:
            click.echo(line, err=True)
        calibration_recorded = _maybe_record_calibration(
            attempt, full_id, composite_delta, text_writer=_stderr_writer,
        )

        if json_output:
            payload = {
                "status": "ok",
                "attempt_id": full_id,
                "measurement_id": measurement_id,
                "post_composite": post_composite,
                "score_before": score_before,
                "composite_delta": composite_delta,
                "calibration_recorded": calibration_recorded,
            }
            if replay_set is not None:
                payload["replay_set"] = replay_set
            click.echo(_json.dumps(payload))
        else:
            click.echo(click.style(
                f"\n\u2713 Measured {full_id}",
                fg="green", bold=True))
            click.echo(f"  Post-deploy composite: {post_composite:.4f}")
            if composite_delta is not None:
                click.echo(f"  Delta vs score_before ({score_before:.4f}): "
                           f"{composite_delta:+.4f}")
            click.echo(f"  measurement_id: {measurement_id}")


    @improve_group.command("diff")
    @click.argument("attempt_id", required=True)
    @click.option("--memory-db", default=None,
                  help="Optimizer memory DB (default: AGENTLAB_MEMORY_DB or optimizer_memory.db).")
    @click.option("--json", "json_output", "-j", is_flag=True,
                  help="Output as JSON.")
    def improve_diff(
        attempt_id: str,
        memory_db: str | None,
        json_output: bool,
    ) -> None:
        """Show the full config diff and rationale for an attempt."""
        import json as _json

        resolved_memory_db = memory_db or os.environ.get(
            "AGENTLAB_MEMORY_DB", MEMORY_DB
        )

        matches = _lookup_attempt_by_prefix(attempt_id, resolved_memory_db)
        if not matches:
            click.echo(click.style(
                f"No improvement found with attempt_id prefix {attempt_id!r}.",
                fg="red"), err=True)
            raise click.exceptions.Exit(1)
        if len(matches) > 1:
            click.echo(click.style(
                f"Ambiguous prefix {attempt_id!r} — matches {len(matches)} attempts.",
                fg="yellow"), err=True)
            raise click.exceptions.Exit(1)

        attempt = matches[0]
        patch_bundle_parsed = None
        raw_bundle = getattr(attempt, "patch_bundle", "") or ""
        if raw_bundle:
            try:
                patch_bundle_parsed = _json.loads(raw_bundle)
            except Exception:
                patch_bundle_parsed = None

        if json_output:
            click.echo(_json.dumps({
                "status": "ok",
                "attempt_id": attempt.attempt_id,
                "change_description": attempt.change_description,
                "config_section": getattr(attempt, "config_section", None),
                "config_diff": attempt.config_diff,
                "patch_bundle": patch_bundle_parsed,
                "score_before": getattr(attempt, "score_before", None),
                "score_after": getattr(attempt, "score_after", None),
                "status_raw": getattr(attempt, "status", None),
            }))
            return

        click.echo(click.style(
            f"\nImprovement {attempt.attempt_id}",
            fg="cyan", bold=True))
        click.echo(f"  Section:  {getattr(attempt, 'config_section', None) or '—'}")
        click.echo(f"  Status:   {getattr(attempt, 'status', '—')}")
        score_before = getattr(attempt, "score_before", None)
        score_after = getattr(attempt, "score_after", None)
        if score_before is not None or score_after is not None:
            before = f"{score_before:.4f}" if score_before is not None else "n/a"
            after = f"{score_after:.4f}" if score_after is not None else "n/a"
            click.echo(f"  Scores:   before={before} after={after}")
        click.echo("")
        click.echo(click.style("Rationale:", bold=True))
        click.echo(f"  {attempt.change_description or '(no description)'}")
        click.echo("")
        click.echo(click.style("Config diff:", bold=True))
        if attempt.config_diff:
            for line in attempt.config_diff.splitlines():
                if line.startswith("+"):
                    click.echo(click.style(line, fg="green"))
                elif line.startswith("-"):
                    click.echo(click.style(line, fg="red"))
                else:
                    click.echo(line)
        else:
            click.echo("  (no diff recorded — empty config_diff)")
        if patch_bundle_parsed is not None:
            click.echo("")
            click.echo(click.style("Patch bundle:", bold=True))
            click.echo(_json.dumps(patch_bundle_parsed, indent=2, sort_keys=True))


    @improve_group.command("lineage")
    @click.argument("attempt_id", required=True)
    @click.option("--memory-db", default=None,
                  help="Optimizer memory DB (default: AGENTLAB_MEMORY_DB or optimizer_memory.db).")
    @click.option("--lineage-db", default=None,
                  help="Improvement lineage DB (default: AGENTLAB_IMPROVEMENT_LINEAGE_DB or .agentlab/improvement_lineage.db).")
    @click.option("--json", "json_output", "-j", is_flag=True,
                  help="Output as JSON.")
    def improve_lineage(
        attempt_id: str,
        memory_db: str | None,
        lineage_db: str | None,
        json_output: bool,
    ) -> None:
        """Render the full lineage chain for an attempt.

        eval_run → attempt → (rejection?) → deployment → measurement
        """
        import json as _json
        from optimizer.improvement_lineage import ImprovementLineageStore

        resolved_memory_db = memory_db or os.environ.get(
            "AGENTLAB_MEMORY_DB", MEMORY_DB
        )
        resolved_lineage_db = lineage_db or os.environ.get(
            "AGENTLAB_IMPROVEMENT_LINEAGE_DB",
            ".agentlab/improvement_lineage.db",
        )

        matches = _lookup_attempt_by_prefix(attempt_id, resolved_memory_db)
        if not matches:
            click.echo(click.style(
                f"No improvement found with attempt_id prefix {attempt_id!r}.",
                fg="red"), err=True)
            raise click.exceptions.Exit(1)
        if len(matches) > 1:
            click.echo(click.style(
                f"Ambiguous prefix {attempt_id!r} — matches {len(matches)} attempts.",
                fg="yellow"), err=True)
            raise click.exceptions.Exit(1)

        attempt = matches[0]
        full_id = attempt.attempt_id

        store = ImprovementLineageStore(db_path=resolved_lineage_db)
        view = store.view_attempt(full_id)

        if json_output:
            click.echo(_json.dumps({
                "status": "ok",
                "attempt_id": view.attempt_id,
                "status_classified": view.status or getattr(attempt, "status", None),
                "eval_run_id": view.eval_run_id,
                "deployment_id": view.deployment_id,
                "deployed_version": view.deployed_version,
                "measurement_id": view.measurement_id,
                "composite_delta": view.composite_delta,
                "score_before": view.score_before,
                "score_after": view.score_after,
                "parent_attempt_id": view.parent_attempt_id,
                "rejection_reason": view.rejection_reason,
                "rejection_detail": view.rejection_detail,
                "rolled_back": view.rolled_back,
                "events": [
                    {
                        "event_type": e.event_type,
                        "timestamp": e.timestamp,
                        "version": e.version,
                        "payload": e.payload,
                    }
                    for e in view.events
                ],
            }))
            return

        click.echo(click.style(
            f"\nLineage for {full_id}",
            fg="cyan", bold=True))
        click.echo(f"  Section:  {getattr(attempt, 'config_section', None) or '—'}")
        click.echo(f"  Status:   {view.status or getattr(attempt, 'status', '—')}")
        if view.eval_run_id:
            click.echo(f"  Eval run: {view.eval_run_id}")
        if view.parent_attempt_id:
            click.echo(f"  Parent:   {view.parent_attempt_id}")
        if view.score_before is not None or view.score_after is not None:
            before = f"{view.score_before:.4f}" if view.score_before is not None else "n/a"
            after = f"{view.score_after:.4f}" if view.score_after is not None else "n/a"
            click.echo(f"  Scores:   before={before} after={after}")
        if view.rejection_reason:
            click.echo(click.style(
                f"  Rejected: {view.rejection_reason} — {view.rejection_detail or ''}",
                fg="red"))
        if view.deployment_id:
            ver = f"v{view.deployed_version:03d}" if view.deployed_version is not None else ""
            click.echo(f"  Deployed: {view.deployment_id} {ver}".rstrip())
        if view.rolled_back:
            click.echo(click.style("  ⚠ rolled back", fg="yellow"))
        if view.measurement_id:
            delta = view.composite_delta
            delta_str = f"{delta:+.4f}" if delta is not None else "pending"
            click.echo(f"  Measured: {view.measurement_id} Δ={delta_str}")
        click.echo("")
        click.echo(click.style("Events:", bold=True))
        if not view.events:
            click.echo("  (no lineage events recorded for this attempt)")
        else:
            for e in view.events:
                when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp))
                ver = f" v{e.version:03d}" if e.version is not None else ""
                extra = ""
                if e.event_type == "rejection":
                    extra = f" — {e.payload.get('reason', '')}: {e.payload.get('detail', '')}"
                elif e.event_type == "measurement":
                    delta = e.payload.get("composite_delta")
                    if delta is not None:
                        extra = f" — Δ={delta:+.4f}"
                    elif e.payload.get("scheduled"):
                        extra = " — scheduled (pending)"
                elif e.event_type == "eval_run":
                    cs = e.payload.get("composite_score")
                    if cs is not None:
                        extra = f" — composite={cs:.4f}"
                click.echo(f"  [{when}] {e.event_type}{ver}{extra}")


    @improve_group.command("optimize")
    @click.option("--cycles", default=1, show_default=True, type=int, help="Number of optimization cycles.")
    @click.option("--continuous", is_flag=True, default=False, help="Loop indefinitely until Ctrl+C.")
    @click.option("--mode", default=None, type=click.Choice(["standard", "advanced", "research"]),
                  help="Optimization mode (replaces --strategy).")
    @click.option("--strategy", default=None, hidden=True, help="[DEPRECATED] Use --mode instead.")
    @click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
    @click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
    @click.option("--memory-db", default=MEMORY_DB, show_default=True, help="Optimizer memory DB.")
    @click.option("--full-auto", is_flag=True, default=False,
                  help="Danger mode: auto-promote accepted configs without manual review.")
    @click.option("--dry-run", is_flag=True, help="Preview the optimization run without mutating state.")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    @click.pass_context
    def improve_optimize(
        ctx: click.Context,
        cycles: int,
        continuous: bool,
        mode: str | None,
        strategy: str | None,
        db: str,
        configs_dir: str,
        memory_db: str,
        full_auto: bool,
        dry_run: bool,
        json_output: bool = False,
    ) -> None:
        """Compatibility alias for `agentlab optimize`."""
        ctx.invoke(
            runner.cli.commands["optimize"],
            cycles=cycles,
            continuous=continuous,
            mode=mode,
            strategy=strategy,
            db=db,
            configs_dir=configs_dir,
            config_path=None,
            eval_run_id=None,
            require_eval_evidence=False,
            memory_db=memory_db,
            full_auto=full_auto,
            dry_run=dry_run,
            json_output=json_output,
        )
