"""`agentlab optimize` command.

Extracted from runner.py in R2 Slice C.3. register_optimize_commands(cli)
is called from cli.commands.register_all().
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from typing import Any

import click


def _runner_module():
    """Late-bound import of runner to avoid circular imports."""
    import runner as _r
    return _r


def _summarize_failed_eval_cases(data: dict, limit: int = 3) -> list[str]:
    """Return short, human-readable summaries of failed eval cases."""
    runner = _runner_module()
    payload = runner._unwrap_eval_payload(data)
    summaries: list[str] = []
    for result in payload.get("results", []):
        if not isinstance(result, dict) or result.get("passed", True):
            continue
        case_id = str(result.get("case_id", "unknown"))
        category = str(result.get("category", "unknown"))
        details = str(result.get("details", "")).strip()
        if details:
            summaries.append(f"{case_id} [{category}] — {details}")
        else:
            summaries.append(f"{case_id} [{category}]")
        if len(summaries) >= limit:
            break
    return summaries


def _persist_candidate_config(
    deployer,
    *,
    candidate_config: dict,
    candidate_scores: dict[str, float],
) -> tuple[int, Path]:
    """Save an accepted optimizer candidate as a reviewable config version."""
    saved = deployer.version_manager.save_version(
        candidate_config,
        candidate_scores,
        status="candidate",
    )
    candidate_path = deployer.version_manager.configs_dir / saved.filename
    return saved.version, candidate_path


def _build_reviewable_change_card(
    *,
    attempt,
    baseline_eval_data: dict,
    candidate_score,
    candidate_version: int,
    candidate_path: Path,
    source_eval_path: Path | None,
    experiment_card_id: str,
):
    """Create a pending change card that links an accepted optimization to a saved candidate config."""
    from optimizer.change_card import ConfidenceInfo, DiffHunk, ProposedChangeCard

    runner = _runner_module()

    failed_cases = _summarize_failed_eval_cases(baseline_eval_data)
    why = "Linked to latest eval failures."
    if failed_cases:
        why = "Linked to latest eval failures: " + "; ".join(failed_cases)

    return ProposedChangeCard(
        title=str(attempt.change_description or "Accepted optimization candidate"),
        why=why,
        diff_hunks=[
            DiffHunk(
                hunk_id=str(uuid.uuid4())[:8],
                surface=str(attempt.config_section or "config"),
                old_value="(see diff)",
                new_value=str(attempt.config_diff or ""),
                status="pending",
            )
        ],
        metrics_before=runner._extract_eval_scores(baseline_eval_data),
        metrics_after=runner._score_to_dict(candidate_score),
        confidence=ConfidenceInfo(
            p_value=float(getattr(attempt, "significance_p_value", 1.0) or 1.0),
            effect_size=float(getattr(attempt, "significance_delta", 0.0) or 0.0),
            n_eval_cases=int(getattr(candidate_score, "total_cases", 0) or 0),
        ),
        risk_class="low",
        rollout_plan="Review diff -> apply locally -> re-run evals -> deploy canary if metrics hold",
        rollback_condition=(
            f"Rollback if composite drops below baseline {float(getattr(attempt, 'score_before', 0.0) or 0.0):.4f}"
        ),
        experiment_card_id=experiment_card_id,
        candidate_config_version=candidate_version,
        candidate_config_path=str(candidate_path),
        source_eval_path=str(source_eval_path) if source_eval_path is not None else "",
        status="pending",
    )


def _run_optimize_cycle(
    *,
    cycle_number: int,
    display_cycle: int,
    display_total: int | None,
    continuous: bool,
    json_output: bool,
    full_auto: bool,
    store,
    observer,
    optimizer,
    deployer,
    memory,
    eval_runner,
    best_score_file: Path,
    all_time_best: float,
    log_path: Path,
    config_path: Path | None = None,
    eval_run_id: str | None = None,
    require_eval_evidence: bool = False,
    spinner: "Any | None" = None,
    harness: Any | None = None,
) -> tuple[dict, float]:
    """Run one optimize iteration and persist a matching experiment-log entry."""
    runner = _runner_module()

    def _phase(label: str) -> None:
        if spinner is not None:
            spinner.update(label)
        if harness is not None:
            from cli.auto_harness import HarnessEvent

            runner._emit_harness_event(harness, HarnessEvent("stage.started", message=label))

    def _task(event: str, task_id: str, task: str, **payload: Any) -> None:
        if harness is None:
            return
        from cli.auto_harness import HarnessEvent

        runner._emit_harness_event(
            harness,
            HarnessEvent(event, task_id=task_id, task=task, payload=payload),
        )

    def _tool_started(label: str) -> float:
        started = time.monotonic()
        if harness is not None:
            from cli.auto_harness import HarnessEvent

            runner._emit_harness_event(
                harness,
                HarnessEvent("tool.started", tool=label, message=label),
            )
        return started

    def _tool_completed(
        label: str,
        started: float,
        *,
        output: str = "",
        exit_code: int = 0,
    ) -> None:
        if harness is None:
            return
        from cli.auto_harness import HarnessEvent

        runner._emit_harness_event(
            harness,
            HarnessEvent(
                "tool.completed",
                tool=label,
                payload={
                    "command": label,
                    "output": output,
                    "exit_code": exit_code,
                    "elapsed_seconds": time.monotonic() - started,
                },
            ),
        )

    try:
        _phase(f"Cycle {display_cycle} — loading eval evidence")
        _task("task.started", "load-evidence", "Load eval evidence")
        evidence_started = _tool_started("load eval evidence")
        workspace = runner.discover_workspace()
        active_config = workspace.resolve_active_config() if workspace is not None and config_path is None else None
        scoped_config_path = config_path or (active_config.path if active_config is not None else None)
        if eval_run_id:
            latest_eval_path, latest_eval_data = runner._eval_payload_for_run_id(
                eval_run_id,
                config_path=scoped_config_path,
            )
        else:
            latest_eval_path, latest_eval_data = runner._latest_eval_payload_for_active_config(scoped_config_path)
        _tool_completed(
            "load eval evidence",
            evidence_started,
            output=str(latest_eval_path or "no eval evidence"),
        )
        if latest_eval_path is None or latest_eval_data is None:
            if eval_run_id:
                description = f"Eval results not found for run id {eval_run_id}."
            elif scoped_config_path is not None:
                description = f"No eval results found for config {scoped_config_path}. Run `agentlab eval run --config {scoped_config_path}` first."
            else:
                description = "No eval results found for the active config. Run `agentlab eval run` first."
            blocked = bool(require_eval_evidence or eval_run_id)
            entry = runner.make_experiment_log_entry(
                cycle=cycle_number,
                status="crash" if blocked else "skip",
                description=description,
                score_before=None,
                score_after=None,
            )
            runner.append_experiment_log_entry(entry, path=log_path)
            _task("task.failed" if blocked else "task.completed", "load-evidence", "Load eval evidence", detail=description)
            if not json_output and not continuous and display_total is not None and harness is None:
                click.echo(
                    f"\n  Cycle {display_cycle}/{display_total} — {description}"
                )
            return (
                {
                    "cycle": cycle_number if continuous else display_cycle,
                    "experiment_cycle": cycle_number,
                    "total_cycles": None if continuous else display_total,
                    "status": entry.status,
                    "accepted": False,
                    "score_before": entry.score_before,
                    "score_after": entry.score_after,
                    "delta": entry.delta,
                    "change_description": entry.description,
                },
                all_time_best,
            )

        report = runner._health_report_from_eval(latest_eval_data)
        _task("task.completed", "load-evidence", "Load eval evidence")

        if not report.needs_optimization:
            _task("task.completed", "decide", "Decide outcome", detail="Latest eval passed")
            if not json_output and not continuous and display_total is not None and harness is None:
                click.echo(
                    f"\n  Cycle {display_cycle}/{display_total} — Latest eval passed; no optimization needed."
                )

            entry = runner.make_experiment_log_entry(
                cycle=cycle_number,
                status="skip",
                description="Latest eval passed; no optimization needed",
                score_before=None,
                score_after=None,
            )
            runner.append_experiment_log_entry(entry, path=log_path)
            return (
                {
                    "cycle": cycle_number if continuous else display_cycle,
                    "experiment_cycle": cycle_number,
                    "total_cycles": None if continuous else display_total,
                    "status": entry.status,
                    "accepted": False,
                    "score_before": entry.score_before,
                    "score_after": entry.score_after,
                    "delta": entry.delta,
                    "change_description": entry.description,
                },
                all_time_best,
            )

        failure_samples = runner._build_eval_failure_samples(latest_eval_data)
        current_config = runner._load_optimize_current_config(deployer=deployer, config_path=config_path)
        _phase(f"Cycle {display_cycle} — proposing candidate config")
        _task("task.started", "propose", "Propose candidate config")
        optimize_started = _tool_started("optimizer.optimize")
        new_config, opt_status = optimizer.optimize(
            report,
            current_config,
            failure_samples=failure_samples,
        )
        _tool_completed("optimizer.optimize", optimize_started, output=opt_status)
        _task("task.completed", "propose", "Propose candidate config", detail=opt_status)

        latest_attempts = memory.recent(limit=1)
        latest = latest_attempts[0] if latest_attempts else None
        proposal_desc = latest.change_description if latest else None
        score_after: float | None = latest.score_after if latest else None
        score_before: float | None = latest.score_before if latest else None
        p_value: float | None = latest.significance_p_value if latest else None

        normalized_status = runner._optimize_cycle_status(
            report_needs_optimization=report.needs_optimization,
            new_config=new_config,
            score_before=score_before,
            score_after=score_after,
        )
        description = proposal_desc or opt_status
        if proposal_desc and new_config is None and opt_status:
            description = f"{proposal_desc} ({opt_status})"

        if not json_output and not continuous and display_total is not None and harness is None:
            runner._stream_cycle_output(
                cycle_num=display_cycle,
                total=display_total,
                report=report,
                proposal_desc=proposal_desc,
                score_after=score_after,
                score_before=score_before,
                p_value=p_value,
                all_time_best=all_time_best,
                best_score_file=best_score_file,
                accepted=new_config is not None,
                decision_detail=opt_status if new_config is None else None,
            )
        else:
            all_time_best = runner._persist_best_score(
                score_after,
                all_time_best,
                best_score_file,
                announce=False,
            )

        if score_after is not None and score_after > all_time_best:
            all_time_best = score_after

        if new_config is not None:
            from optimizer.change_card import ChangeCardStore

            _phase(f"Cycle {display_cycle} — evaluating candidate")
            _task("task.started", "evaluate", "Evaluate candidate config")
            eval_started = _tool_started("eval_runner.run")
            score = eval_runner.run(config=new_config)
            _tool_completed(
                "eval_runner.run",
                eval_started,
                output=f"composite={score.composite:.4f}",
            )
            _task("task.completed", "evaluate", "Evaluate candidate config")
            _phase(f"Cycle {display_cycle} — deciding outcome")
            _task("task.started", "decide", "Decide outcome")
            candidate_scores = runner._score_to_dict(score)
            persist_started = _tool_started("persist candidate config")
            candidate_version, candidate_path = _persist_candidate_config(
                deployer,
                candidate_config=new_config,
                candidate_scores=candidate_scores,
            )
            _tool_completed(
                "persist candidate config",
                persist_started,
                output=str(candidate_path),
            )
            if harness is not None:
                from cli.auto_harness import HarnessEvent

                runner._emit_harness_event(
                    harness,
                    HarnessEvent(
                        "artifact.updated",
                        message=f"candidate v{candidate_version:03d} updated",
                    ),
                )
            latest = memory.recent(limit=1)[0]
            entry_timestamp = runner.experiment_log_utc_timestamp()
            preview_entry = runner.make_experiment_log_entry(
                cycle=cycle_number,
                status=normalized_status,
                description=description,
                score_before=score_before,
                score_after=score_after,
                timestamp=entry_timestamp,
            )
            change_card = _build_reviewable_change_card(
                attempt=latest,
                baseline_eval_data=latest_eval_data,
                candidate_score=score,
                candidate_version=candidate_version,
                candidate_path=candidate_path,
                source_eval_path=latest_eval_path,
                experiment_card_id=runner.experiment_log_entry_id(preview_entry),
            )
            ChangeCardStore().save(change_card)
            description = f"{description} (review {change_card.card_id}, candidate v{candidate_version:03d})"
            entry = runner.make_experiment_log_entry(
                cycle=cycle_number,
                status=normalized_status,
                description=description,
                score_before=score_before,
                score_after=score_after,
                timestamp=entry_timestamp,
            )

            if not json_output and not continuous and harness is None:
                click.echo(f"  Review: saved {change_card.card_id} for v{candidate_version:03d}")
            if full_auto:
                promoted = runner._promote_latest_version(deployer)
                if not json_output and not continuous and harness is None and promoted is not None:
                    click.echo(click.style(f"  FULL AUTO: promoted v{promoted:03d} to active", fg="yellow"))
            _task("task.completed", "decide", "Decide outcome", detail=entry.status)
        else:
            _task("task.started", "decide", "Decide outcome")
            entry = runner.make_experiment_log_entry(
                cycle=cycle_number,
                status=normalized_status,
                description=description,
                score_before=score_before,
                score_after=score_after,
            )
            _task("task.completed", "decide", "Decide outcome", detail=entry.status)
        runner.append_experiment_log_entry(entry, path=log_path)

        return (
            {
                "cycle": cycle_number if continuous else display_cycle,
                "experiment_cycle": cycle_number,
                "total_cycles": None if continuous else display_total,
                "status": entry.status,
                "accepted": entry.status == "keep",
                "score_before": score_before,
                "score_after": score_after,
                "delta": entry.delta,
                "change_description": description,
            },
            all_time_best,
        )
    except Exception as exc:
        entry = runner.make_experiment_log_entry(
            cycle=cycle_number,
            status="crash",
            description=str(exc),
            score_before=None,
            score_after=None,
        )
        runner.append_experiment_log_entry(entry, path=log_path)

        cycle_result = {
            "cycle": cycle_number if continuous else display_cycle,
            "experiment_cycle": cycle_number,
            "total_cycles": None if continuous else display_total,
            "status": entry.status,
            "accepted": False,
            "score_before": entry.score_before,
            "score_after": entry.score_after,
            "delta": entry.delta,
            "change_description": entry.description,
        }
        if continuous:
            if not json_output:
                click.echo(click.style(f"  Cycle {cycle_number} crashed: {exc}", fg="magenta"))
            return cycle_result, all_time_best
        raise


def register_optimize_commands(cli: click.Group) -> None:
    """Register the `optimize` command on *cli*."""
    runner = _runner_module()
    # Local aliases for module-level symbols that appear in decorator defaults.
    # Binding them as locals keeps help-text string representations identical
    # to when runner.py owned the command.
    DB_PATH = runner.DB_PATH
    CONFIGS_DIR = runner.CONFIGS_DIR
    MEMORY_DB = runner.MEMORY_DB

    @cli.command("optimize")
    @click.option("--cycles", default=1, show_default=True, type=int, help="Number of optimization cycles.")
    @click.option("--continuous", is_flag=True, default=False, help="Loop indefinitely until Ctrl+C.")
    @click.option("--mode", default=None, type=click.Choice(["standard", "advanced", "research"]),
                  help="Optimization mode (replaces --strategy).")
    @click.option("--strategy", default=None, hidden=True, help="[DEPRECATED] Use --mode instead.")
    @click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
    @click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
    @click.option("--config", "config_path", default=None, help="Optimize a specific config path instead of the active config.")
    @click.option("--eval-run-id", default=None, help="Use a specific eval run as optimization evidence.")
    @click.option(
        "--require-eval-evidence",
        is_flag=True,
        default=False,
        help="Fail if no completed eval evidence is available for this optimization.",
    )
    @click.option("--memory-db", default=MEMORY_DB, show_default=True, help="Optimizer memory DB.")
    @click.option("--full-auto", is_flag=True, default=False,
                  help="Danger mode: auto-promote accepted configs without manual review.")
    @click.option("--dry-run", is_flag=True, help="Preview the optimization run without mutating state.")
    @click.option(
        "--explain-strategy",
        is_flag=True,
        default=False,
        help="Print one line per ranked strategy showing why it was chosen.",
    )
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    @click.option("--max-budget-usd", default=None, type=float, help="Stop before running when workspace spend reaches this amount.")
    @click.option(
        "--strict-live/--no-strict-live",
        default=False,
        help="Exit non-zero (12) if optimizer would run in mock mode (no provider key).",
    )
    @click.option(
        "--output-format",
        type=click.Choice(["text", "json", "stream-json"], case_sensitive=False),
        default="text",
        show_default=True,
        help="Render text, a final JSON envelope, or stream JSON progress events.",
    )
    @click.option(
        "--ui",
        type=click.Choice(["auto", "claude", "classic"], case_sensitive=False),
        default=None,
        show_default="auto",
        help="Interactive UI mode for text output.",
    )
    def optimize(
        cycles: int,
        continuous: bool,
        mode: str | None,
        strategy: str | None,
        db: str,
        configs_dir: str,
        config_path: str | None,
        eval_run_id: str | None,
        require_eval_evidence: bool,
        memory_db: str,
        full_auto: bool,
        dry_run: bool,
        explain_strategy: bool = False,
        json_output: bool = False,
        max_budget_usd: float | None = None,
        strict_live: bool = False,
        output_format: str = "text",
        ui: str | None = None,
        harness: Any | None = None,
    ) -> None:
        """Run optimization cycles to improve agent config.

        Examples:
          agentlab optimize
          agentlab optimize --cycles 5
          agentlab optimize --continuous
          agentlab optimize --mode advanced --cycles 3
        """
        from cli.output import resolve_output_format
        from cli.progress import PhaseSpinner, ProgressRenderer
        from cli.usage import enforce_workspace_budget
        from optimizer.cost_tracker import CostTracker
        from optimizer.mode_router import ModeConfig, ModeRouter, OptimizationMode

        resolved_output_format = resolve_output_format(output_format, json_output=json_output)
        if harness is None:
            harness = runner._harness_session(
                title="AgentLab Optimize",
                stage="Running optimization cycle(s)",
                tasks=[
                    {"id": "load-evidence", "title": "Load eval evidence"},
                    {"id": "propose", "title": "Propose candidate config"},
                    {"id": "evaluate", "title": "Evaluate candidate config"},
                    {"id": "decide", "title": "Decide outcome"},
                ],
                output_format=resolved_output_format,
                ui=ui,
            )
        progress = ProgressRenderer(output_format=resolved_output_format, render_text=False)
        progress.phase_started("optimize", message="Run optimization cycle(s)")

        if resolved_output_format == "text" and harness is None:
            click.echo(click.style(f"\n✦ {runner._soul_line('optimize')}", fg="cyan"))
            if full_auto:
                click.echo(click.style("⚠ FULL AUTO ENABLED: skipping manual promotion gates.", fg="yellow"))
            runner._print_cli_plan(
                "Optimization plan",
                [
                    "Observe failures and select dominant issue",
                    "Propose and evaluate candidate config changes",
                    "Accept/deploy only when quality improves",
                ],
            )

        if strategy is not None:
            click.echo(click.style(
                "Warning: --strategy is deprecated. Use --mode instead. "
                "Mapping: simple->standard, adaptive->advanced, full/pro->research.",
                fg="yellow",
            ))
            if mode is None:
                mode = ModeRouter.from_legacy_strategy(strategy).value

        if mode is not None:
            mode_enum = OptimizationMode(mode)
            mode_config = ModeConfig(mode=mode_enum)
            resolved = ModeRouter().resolve(mode_config)
            if resolved_output_format == "text" and harness is None:
                click.echo(f"Mode: {mode} (strategy={resolved.search_strategy.value}, "
                           f"candidates={resolved.max_candidates})")

        if dry_run:
            from cli.stream2_helpers import json_response

            preview = {
                "cycles": cycles,
                "continuous": continuous,
                "mode": mode or "default",
                "full_auto": full_auto,
                "db": db,
                "configs_dir": configs_dir,
                "config_path": config_path,
                "eval_run_id": eval_run_id,
                "require_eval_evidence": require_eval_evidence,
                "memory_db": memory_db,
                "max_budget_usd": max_budget_usd,
                "ui": ui,
            }
            if resolved_output_format == "json":
                click.echo(json_response("ok", preview, next_cmd="agentlab optimize"))
            else:
                click.echo("Dry run: optimization would execute with the following plan:")
                click.echo(f"  cycles:      {cycles}")
                click.echo(f"  continuous:  {continuous}")
                click.echo(f"  mode:        {mode or 'default'}")
                click.echo(f"  full_auto:   {full_auto}")
                click.echo(f"  configs_dir: {configs_dir}")
            if explain_strategy:
                from optimizer.proposer import (
                    _LAST_EXPLANATION as _module_last_explanation,
                    format_strategy_explanation,
                )

                if _module_last_explanation:
                    for entry in _module_last_explanation:
                        click.echo(format_strategy_explanation(entry))
                else:
                    click.echo(
                        "No strategy explanation available (reflection data empty or mock mode)."
                    )
            return

        budget_ok, budget_message, budget_snapshot = enforce_workspace_budget(max_budget_usd)
        if not budget_ok:
            progress.warning(message=budget_message or "Budget reached")
            if resolved_output_format == "json":
                from cli.stream2_helpers import json_response

                click.echo(json_response("ok", {"message": budget_message, "usage": budget_snapshot}, next_cmd="agentlab usage"))
                return
            click.echo(budget_message)
            return

        (
            runtime,
            eval_runner,
            proposer,
            skill_engine,
            adversarial_simulator,
            skill_autolearner,
        ) = runner._build_runtime_components()
        resolved_config_path = runner._resolve_optimize_config_path(config_path)
        resolution = runner.resolve_config_snapshot(
            config_path=str(resolved_config_path) if resolved_config_path is not None else None,
            command="optimize",
        )
        runner.persist_config_lockfile(resolution)
        runner._warn_mock_modes(proposer=proposer, json_output=(resolved_output_format == "json"))
        store = runner.ConversationStore(db_path=db)
        observer = runner.Observer(store)
        deployer = runner.Deployer(configs_dir=configs_dir, store=store)
        memory = runner.OptimizationMemory(db_path=memory_db)
        tracker_db_path, per_cycle_dollars, daily_dollars, stall_threshold_cycles = runner._runtime_budget_config(runtime)
        cost_tracker = CostTracker(
            db_path=tracker_db_path,
            per_cycle_budget_dollars=per_cycle_dollars,
            daily_budget_dollars=daily_dollars,
            stall_threshold_cycles=stall_threshold_cycles,
        )

        # Build reflection engine and failure analyzer for LLM-driven optimization
        from optimizer.failure_analyzer import FailureAnalyzer
        from optimizer.reflection import ReflectionEngine

        reflection_engine = None
        failure_analyzer = None
        agent_card_markdown = ""

        if strict_live and proposer.use_mock:
            from cli.exit_codes import EXIT_MOCK_FALLBACK
            from cli.strict_live import MockFallbackError

            msg = "optimize: proposer is in mock mode (no provider key or use_mock=true in config)"
            click.echo(MockFallbackError([msg]).args[0], err=True)
            sys.exit(EXIT_MOCK_FALLBACK)

        if not proposer.use_mock:
            reflection_engine = ReflectionEngine(
                llm_router=proposer.llm_router,
                db_path=str(Path(memory_db).parent / "reflections.db"),
            )
            failure_analyzer = FailureAnalyzer(llm_router=proposer.llm_router)

            # Generate Agent Card from current config for LLM context
            try:
                from agent_card.converter import from_config_dict as card_from_config
                from agent_card.renderer import render_to_markdown as card_to_md

                if resolution.snapshot:
                    card_obj = card_from_config(resolution.snapshot)
                    agent_card_markdown = card_to_md(card_obj)
            except Exception:
                pass  # Agent Card generation is best-effort

        optimizer = runner.Optimizer(
            eval_runner=eval_runner,
            memory=memory,
            proposer=proposer,
            significance_alpha=runtime.eval.significance_alpha,
            significance_min_effect_size=runtime.eval.significance_min_effect_size,
            significance_iterations=runtime.eval.significance_iterations,
            significance_min_pairs=getattr(runtime.eval, "significance_min_pairs", 0),
            skill_engine=skill_engine,
            use_skills=True,
            skill_selection_strategy="auto",
            skill_max_candidates=5,
            adversarial_simulator=adversarial_simulator,
            skill_autolearner=skill_autolearner,
            auto_learn_skills=runtime.optimizer.skill_autolearn_enabled,
            failure_analyzer=failure_analyzer,
            reflection_engine=reflection_engine,
            agent_card_markdown=agent_card_markdown,
        )

        # Track all-time best score
        best_score_file = Path(".agentlab/best_score.txt")
        all_time_best = runner._read_best_score(best_score_file)
        log_path = runner.default_experiment_log_path()
        next_cycle_number = runner.next_experiment_log_cycle_number(log_path)

        json_cycle_results: list[dict] = []
        experiments_run = 0
        kept_count = 0
        discarded_count = 0
        skipped_count = 0
        display_cycle = 1

        if continuous and resolved_output_format == "text" and harness is None:
            click.echo("Starting continuous optimization. Press Ctrl+C to stop.")

        try:
            while True:
                cost_before = runner._proposer_total_cost(proposer)
                if harness is not None:
                    cycle_result, all_time_best = _run_optimize_cycle(
                        cycle_number=next_cycle_number,
                        display_cycle=display_cycle,
                        display_total=None if continuous else cycles,
                        continuous=continuous,
                        json_output=(resolved_output_format == "json"),
                        full_auto=full_auto,
                        store=store,
                        observer=observer,
                        optimizer=optimizer,
                        deployer=deployer,
                        memory=memory,
                        eval_runner=eval_runner,
                        best_score_file=best_score_file,
                        all_time_best=all_time_best,
                        log_path=log_path,
                        config_path=resolved_config_path,
                        eval_run_id=eval_run_id,
                        require_eval_evidence=require_eval_evidence,
                        spinner=None,
                        harness=harness,
                    )
                else:
                    with PhaseSpinner(
                        f"Cycle {display_cycle} — starting",
                        output_format=resolved_output_format,
                    ) as cycle_spinner:
                        cycle_result, all_time_best = _run_optimize_cycle(
                            cycle_number=next_cycle_number,
                            display_cycle=display_cycle,
                            display_total=None if continuous else cycles,
                            continuous=continuous,
                            json_output=(resolved_output_format == "json"),
                            full_auto=full_auto,
                            store=store,
                            observer=observer,
                            optimizer=optimizer,
                            deployer=deployer,
                            memory=memory,
                            eval_runner=eval_runner,
                            best_score_file=best_score_file,
                            all_time_best=all_time_best,
                            log_path=log_path,
                            config_path=resolved_config_path,
                            eval_run_id=eval_run_id,
                            require_eval_evidence=require_eval_evidence,
                            spinner=cycle_spinner,
                        )
                        cycle_spinner.update(
                            f"Cycle {cycle_result['experiment_cycle']} — {cycle_result['status']}"
                        )
                if harness is not None:
                    from cli.auto_harness import HarnessEvent

                    runner._emit_harness_event(
                        harness,
                        HarnessEvent(
                            "metrics.updated",
                            message=f"Cycle {cycle_result['experiment_cycle']} {cycle_result['status']}",
                            payload={"status": cycle_result["status"]},
                        ),
                    )
                cost_after = runner._proposer_total_cost(proposer)
                cycle_cost = max(0.0, round(cost_after - cost_before, 8))
                cycle_delta = float(cycle_result.get("delta") or 0.0)
                cost_tracker.record_cycle(
                    cycle_id=f"optimize-{cycle_result['experiment_cycle']}",
                    spent_dollars=cycle_cost,
                    improvement_delta=cycle_delta,
                )
                progress.phase_completed(
                    "optimize-cycle",
                    message=(
                        f"Cycle {cycle_result['experiment_cycle']} "
                        f"{cycle_result['status']} ({cycle_delta:+.2f})"
                    ),
                )
                if (require_eval_evidence or eval_run_id) and cycle_result["status"] == "crash":
                    raise click.ClickException(str(cycle_result.get("change_description") or "Missing eval evidence."))

                experiments_run += 1
                if cycle_result["status"] == "keep":
                    kept_count += 1
                elif cycle_result["status"] == "discard":
                    discarded_count += 1
                elif cycle_result["status"] == "skip":
                    skipped_count += 1

                if continuous:
                    if resolved_output_format == "json":
                        from cli.stream2_helpers import json_response

                        click.echo(json_response("ok", cycle_result))
                    elif resolved_output_format == "stream-json":
                        progress.next_action("agentlab status")
                    elif harness is None:
                        click.echo(
                            runner._continuous_status_line(
                                cycle=cycle_result["experiment_cycle"],
                                best_score=all_time_best,
                                last_status=cycle_result["status"],
                                delta=cycle_result["delta"],
                            )
                        )
                else:
                    json_cycle_results.append(cycle_result)
                    if display_cycle >= cycles:
                        break

                next_cycle_number += 1
                display_cycle += 1
        except KeyboardInterrupt:
            if continuous:
                if resolved_output_format == "text":
                    best_entry = runner.best_experiment_log_entry(runner.read_experiment_log_entries(log_path))
                    best_score = best_entry.score_after if best_entry is not None and best_entry.score_after is not None else all_time_best
                    click.echo(
                        f"Ran {experiments_run} experiments: "
                        f"{kept_count} kept, {discarded_count} discarded, {skipped_count} skipped. "
                        f"Best score: {best_score:.2f}"
                    )
                    click.echo("Experiment log saved to .agentlab/experiment_log.tsv")
                return
            raise

        progress.phase_completed("optimize", message="Optimization run complete")
        progress.next_action("agentlab status")

        if resolved_output_format == "stream-json":
            return

        if resolved_output_format == "json":
            from cli.stream2_helpers import json_response

            click.echo(json_response("ok", json_cycle_results, next_cmd="agentlab status"))
            return

        if cycles > 1 and not continuous:
            click.echo(f"\nOptimization complete. {cycles} cycles executed.")
        latest_attempts = memory.recent(limit=1)
        latest_score = latest_attempts[0].score_after if latest_attempts else None
        click.echo(click.style(f"  Status: {runner._score_status_label(latest_score)}", fg="magenta"))
        runner._print_next_actions(
            [
                "agentlab status",
                "agentlab runbook list",
                "agentlab optimize --continuous",
            ],
        )

        # Feature 4: recommendations
        final_report = observer.observe()
        recs = runner._generate_recommendations(final_report, None)
        if recs:
            click.echo(click.style("\n  ⚡ Recommended next steps:", fg="cyan", bold=True))
            for rec in recs:
                click.echo(rec)

        if explain_strategy:
            # The proposer stashes the last ranking explanation on itself and
            # on a module-level slot in `optimizer.proposer`. We check the
            # instance first (works for live runs and unit tests that reach
            # this exact `proposer` object) and fall back to the module slot,
            # which survives the full optimize pipeline without needing us to
            # thread the proposer object through runner glue.
            from optimizer.proposer import (
                _LAST_EXPLANATION as _module_last_explanation,
                format_strategy_explanation,
            )

            explanation = getattr(proposer, "_last_explanation", None) or list(
                _module_last_explanation
            )
            if explanation:
                for entry in explanation:
                    click.echo(format_strategy_explanation(entry))
            else:
                click.echo(
                    "No strategy explanation available (reflection data empty or mock mode)."
                )

        if proposer.llm_router is not None:
            summary = proposer.llm_router.cost_summary()
            if summary:
                click.echo("\nProvider cost summary:")
                for key, item in summary.items():
                    click.echo(
                        f"  {key}: requests={item['requests']} "
                        f"prompt_tokens={item['prompt_tokens']} "
                        f"completion_tokens={item['completion_tokens']} "
                        f"cost=${item['total_cost']:.6f}"
                    )
