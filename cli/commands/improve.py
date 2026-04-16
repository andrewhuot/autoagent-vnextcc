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


    @improve_group.command("run", hidden=True)
    @click.option("--auto", is_flag=True, help="Apply the top suggested fix without prompting.")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    def improve_run(auto: bool, json_output: bool = False) -> None:
        """Run the eval -> diagnose -> suggest -> optional apply improvement flow."""
        click.echo(click.style(
            "Tip: use `agentlab optimize --cycles 1` for the same result.",
            fg="yellow",
        ))
        from cli.stream2_helpers import apply_autofix_to_config, json_response
        from optimizer.autofix import AutoFixEngine, AutoFixStore
        from optimizer.autofix_proposers import (
            CostOptimizationProposer,
            FailurePatternProposer,
            RegressionProposer,
        )
        from optimizer.diagnose_session import DiagnoseSession
        from optimizer.mutations import create_default_registry

        runtime = runner.load_runtime_with_mode_preference()
        workspace = runner.discover_workspace()
        resolved_config = workspace.resolve_active_config() if workspace is not None else None
        config = resolved_config.config if resolved_config is not None else None
        eval_runner = runner._build_eval_runner(runtime, default_agent_config=config)
        score = eval_runner.run(config=config)

        store = runner.ConversationStore(db_path=DB_PATH)
        observer = runner.Observer(store)
        deployer = runner.Deployer(configs_dir=CONFIGS_DIR, store=store)
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
                version_info = apply_autofix_to_config(top_proposal.proposal_id, new_config, configs_dir=CONFIGS_DIR)
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

        click.echo(click.style("\n✦ Improve", fg="cyan", bold=True))
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
