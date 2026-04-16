"""Improvement workflows: `agentlab improve ...` commands.

Extracted from runner.py in R2 Slice B.0 as the first step of the
modular CLI refactor. This module owns the shape of `agentlab improve`
— any new subcommand (run, accept, measure, diff, lineage) will be
added here in Slices B.1–B.5.

The behavior and help text of every subcommand is preserved byte-for-
byte from the pre-extraction state; `tests/test_cli_help_golden.py`
locks that guarantee.
"""
from __future__ import annotations

import json
import os
import sys
import time

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
        runner.deploy,
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


def _run_post_deploy_eval(*, strict_live: bool = False) -> float:
    """Run a fresh eval against the currently-active config and return its
    composite score. Separate helper so tests can patch it."""
    runner = _runner_module()
    runtime = runner.load_runtime_with_mode_preference()
    workspace = runner.discover_workspace()
    resolved_config = workspace.resolve_active_config() if workspace is not None else None
    config = resolved_config.config if resolved_config is not None else None
    eval_runner = runner._build_eval_runner(runtime, default_agent_config=config)
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
        runner.optimize,
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
    @click.option("--json", "json_output", "-j", is_flag=True,
                  help="Output as JSON.")
    def improve_measure(
        attempt_id: str,
        strict_live: bool,
        memory_db: str | None,
        lineage_db: str | None,
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

        post_composite = _run_post_deploy_eval(strict_live=strict_live)

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

        if json_output:
            click.echo(_json.dumps({
                "status": "ok",
                "attempt_id": full_id,
                "measurement_id": measurement_id,
                "post_composite": post_composite,
                "score_before": score_before,
                "composite_delta": composite_delta,
            }))
        else:
            click.echo(click.style(
                f"\n\u2713 Measured {full_id}",
                fg="green", bold=True))
            click.echo(f"  Post-deploy composite: {post_composite:.4f}")
            if composite_delta is not None:
                click.echo(f"  Delta vs score_before ({score_before:.4f}): "
                           f"{composite_delta:+.4f}")
            click.echo(f"  measurement_id: {measurement_id}")


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
            runner.optimize,
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
