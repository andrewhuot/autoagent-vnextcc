"""CLI entry point for AutoAgent VNextCC.

Full command set:
  autoagent init [--template NAME]
  autoagent eval run [OPTIONS]
  autoagent eval results [--run-id ID]
  autoagent eval list
  autoagent optimize [--cycles N]
  autoagent config list
  autoagent config diff V1 V2
  autoagent config show [VERSION]
  autoagent deploy [--strategy canary|immediate]
  autoagent loop [--max-cycles N] [--stop-on-plateau]
  autoagent status
  autoagent logs [--limit N] [--outcome fail|success]
  autoagent server
"""

from __future__ import annotations

import json
import os
import shutil
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from agent.config.loader import load_config
from agent.config.runtime import load_runtime_config
from agent.config.schema import validate_config, config_diff as schema_config_diff
from deployer import Deployer
from evals import EvalRunner
from logger import ConversationStore
from logger.structured import configure_structured_logging
from observer import Observer
from optimizer import Optimizer
from optimizer.memory import OptimizationMemory
from optimizer.proposer import Proposer
from optimizer.providers import build_router_from_runtime_config
from optimizer.reliability import (
    DeadLetterQueue,
    GracefulShutdown,
    LoopCheckpoint,
    LoopCheckpointStore,
    LoopScheduler,
    LoopWatchdog,
    ResourceMonitor,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("AUTOAGENT_DB", "conversations.db")
CONFIGS_DIR = os.environ.get("AUTOAGENT_CONFIGS", "configs")
MEMORY_DB = os.environ.get("AUTOAGENT_MEMORY_DB", "optimizer_memory.db")


def _load_config_dict(config_path: str) -> dict:
    """Load a raw config dictionary from disk."""
    with Path(config_path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _ensure_active_config(deployer: Deployer) -> dict:
    """Return active config; bootstrap from base config if none exists yet."""
    current = deployer.get_active_config()
    if current is not None:
        return current
    base_path = Path(__file__).parent / "agent" / "config" / "base_config.yaml"
    config = load_config(str(base_path)).model_dump()
    deployer.version_manager.save_version(config, scores={"composite": 0.0}, status="active")
    return config


def _print_score(score, heading: str) -> None:
    """Print a consistent score summary for eval output."""
    click.echo(f"\n{heading}")
    click.echo(f"  Cases: {score.passed_cases}/{score.total_cases} passed")
    click.echo(f"  Quality:   {score.quality:.4f}")
    click.echo(f"  Safety:    {score.safety:.4f} ({score.safety_failures} failures)")
    click.echo(f"  Latency:   {score.latency:.4f}")
    click.echo(f"  Cost:      {score.cost:.4f}")
    click.echo(f"  Composite: {score.composite:.4f}")


def _score_to_dict(score) -> dict:
    """Convert CompositeScore-like object into deployable score dictionary."""
    return {
        "quality": score.quality,
        "safety": score.safety,
        "tool_use_accuracy": getattr(score, "tool_use_accuracy", 0.0),
        "latency": score.latency,
        "cost": score.cost,
        "composite": score.composite,
    }


def _build_failure_samples(store: ConversationStore, limit: int = 25) -> list[dict]:
    """Return structured recent failure samples for optimizer proposal context."""
    samples: list[dict] = []
    for record in store.get_failures(limit=limit):
        samples.append(
            {
                "user_message": record.user_message,
                "agent_response": record.agent_response,
                "outcome": record.outcome,
                "error_message": record.error_message,
                "safety_flags": record.safety_flags,
                "tool_calls": record.tool_calls,
                "specialist_used": record.specialist_used,
                "latency_ms": record.latency_ms,
            }
        )
    return samples


def _ts(epoch: float) -> str:
    """Format epoch timestamp for display."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _build_runtime_components() -> tuple[object, EvalRunner, Proposer]:
    """Create runtime-configured eval runner and multi-model proposer."""
    runtime = load_runtime_config()
    eval_runner = EvalRunner(history_db_path=runtime.eval.history_db_path)
    router = build_router_from_runtime_config(runtime.optimizer)
    proposer = Proposer(use_mock=runtime.optimizer.use_mock, llm_router=router)
    return runtime, eval_runner, proposer


def _sleep_interruptibly(seconds: float, shutdown: GracefulShutdown) -> None:
    """Sleep in small increments and return early when shutdown is requested."""
    remaining = max(0.0, seconds)
    while remaining > 0 and not shutdown.stop_requested:
        step = min(0.5, remaining)
        shutdown.event.wait(timeout=step)
        remaining -= step


# ---------------------------------------------------------------------------
# Root CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(version="1.0.0", prog_name="autoagent")
def cli() -> None:
    """AutoAgent VNextCC — agent optimization platform.

    A product-grade platform for iterating ADK agent quality.
    CLI-first, API-ready, with a web console for visual insight.
    """


# ---------------------------------------------------------------------------
# autoagent init
# ---------------------------------------------------------------------------

@cli.command("init")
@click.option("--template", default="customer-support", show_default=True,
              type=click.Choice(["customer-support", "minimal"]),
              help="Project template to scaffold.")
@click.option("--dir", "target_dir", default=".", show_default=True,
              help="Directory to initialize in.")
def init_project(template: str, target_dir: str) -> None:
    """Scaffold a new AutoAgent project with config, eval suite, and structure."""
    target = Path(target_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)

    # Create directory structure
    dirs = ["configs", "evals/cases", "agent/config"]
    for d in dirs:
        (target / d).mkdir(parents=True, exist_ok=True)

    # Copy base config
    src_config = Path(__file__).parent / "agent" / "config" / "base_config.yaml"
    dst_config = target / "configs" / "v001_base.yaml"
    if src_config.exists() and not dst_config.exists():
        shutil.copy2(src_config, dst_config)

    # Copy eval cases
    src_evals = Path(__file__).parent / "evals" / "cases"
    if src_evals.exists():
        dst_evals = target / "evals" / "cases"
        for case_file in src_evals.glob("*.yaml"):
            dst = dst_evals / case_file.name
            if not dst.exists():
                shutil.copy2(case_file, dst)

    click.echo(f"Initialized AutoAgent project in {target}")
    click.echo(f"  Template: {template}")
    click.echo(f"  Config:   configs/v001_base.yaml")
    click.echo(f"  Evals:    evals/cases/")
    click.echo(f"\nNext steps:")
    click.echo(f"  autoagent eval run          # Run eval suite")
    click.echo(f"  autoagent optimize          # Run optimization cycle")
    click.echo(f"  autoagent server            # Start API + web console")


# ---------------------------------------------------------------------------
# autoagent eval (subgroup)
# ---------------------------------------------------------------------------

@cli.group("eval", invoke_without_command=True)
@click.pass_context
def eval_group(ctx: click.Context) -> None:
    """Evaluate agent configs against test suites."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(
            eval_run,
            config_path=None,
            suite=None,
            dataset=None,
            dataset_split="all",
            category=None,
            output=None,
        )


@eval_group.command("run")
@click.option("--config", "config_path", default=None, help="Path to config YAML.")
@click.option("--suite", default=None, help="Path to eval cases directory.")
@click.option("--dataset", default=None, help="Path to eval dataset (.jsonl or .csv).")
@click.option("--split", "dataset_split", default="all",
              type=click.Choice(["train", "test", "all"]),
              show_default=True,
              help="Dataset split to evaluate when using --dataset.")
@click.option("--category", default=None, help="Run only a specific category.")
@click.option("--output", default=None, help="Write results JSON to file.")
def eval_run(config_path: str | None, suite: str | None, dataset: str | None, dataset_split: str,
             category: str | None, output: str | None) -> None:
    """Run eval suite against a config.

    Examples:
      autoagent eval run
      autoagent eval run --config configs/v003.yaml
      autoagent eval run --config configs/v003.yaml --category safety
      autoagent eval run --output results.json
    """
    runtime = load_runtime_config()
    if runtime.optimizer.use_mock:
        click.echo(click.style(
            "\u26a0 Running with mock provider. Results are simulated. "
            "Set use_mock: false in autoagent.yaml for real evaluation.",
            fg="yellow",
        ))

    config = None
    if config_path:
        config = _load_config_dict(config_path)
        click.echo(f"Evaluating config: {config_path}")
    else:
        click.echo("Evaluating with default config")

    runner = EvalRunner(
        cases_dir=suite,
        history_db_path=runtime.eval.history_db_path,
    )

    if category:
        score = runner.run_category(category, config=config, dataset_path=dataset, split=dataset_split)
        _print_score(score, f"Category: {category}")
    else:
        score = runner.run(config=config, dataset_path=dataset, split=dataset_split)
        _print_score(score, "Full eval suite")

    if output:
        result = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "config_path": config_path,
            "category": category,
            "dataset": dataset,
            "split": dataset_split,
            "run_id": score.run_id,
            "provenance": score.provenance,
            "scores": _score_to_dict(score),
            "passed": score.passed_cases,
            "total": score.total_cases,
            "results": [
                {
                    "case_id": r.case_id,
                    "category": r.category,
                    "passed": r.passed,
                    "quality_score": r.quality_score,
                    "safety_passed": r.safety_passed,
                    "latency_ms": r.latency_ms,
                    "details": r.details,
                }
                for r in score.results
            ],
        }
        Path(output).write_text(json.dumps(result, indent=2), encoding="utf-8")
        click.echo(f"\nResults written to {output}")


@eval_group.command("results")
@click.option("--run-id", default=None, help="Run ID to show results for.")
@click.option("--file", "results_file", default=None, help="Path to results JSON file.")
def eval_results(run_id: str | None, results_file: str | None) -> None:
    """View eval results from a previous run.

    Examples:
      autoagent eval results --file results.json
    """
    if results_file:
        data = json.loads(Path(results_file).read_text(encoding="utf-8"))
        click.echo(f"\nEval Results — {data.get('timestamp', 'unknown')}")
        click.echo(f"  Config:  {data.get('config_path', 'default')}")
        scores = data.get("scores", {})
        click.echo(f"  Cases:   {data.get('passed', '?')}/{data.get('total', '?')} passed")
        click.echo(f"  Quality:   {scores.get('quality', 0):.4f}")
        click.echo(f"  Safety:    {scores.get('safety', 0):.4f}")
        click.echo(f"  Latency:   {scores.get('latency', 0):.4f}")
        click.echo(f"  Cost:      {scores.get('cost', 0):.4f}")
        click.echo(f"  Composite: {scores.get('composite', 0):.4f}")

        # Show failed cases
        results = data.get("results", [])
        failed = [r for r in results if not r.get("passed")]
        if failed:
            click.echo(f"\nFailed cases ({len(failed)}):")
            for r in failed:
                click.echo(f"  {r['case_id']} [{r.get('category', '?')}] quality={r.get('quality_score', 0):.2f}")
    elif run_id:
        click.echo(f"Run ID lookup requires the API server. Use: autoagent server")
    else:
        click.echo("Provide --file or --run-id. Use 'autoagent eval run --output results.json' first.")


@eval_group.command("list")
def eval_list() -> None:
    """List recent eval runs.

    Note: Full run history requires the API server.
    Checks for local result files in the current directory.
    """
    results_files = sorted(Path(".").glob("*results*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not results_files:
        click.echo("No local eval result files found.")
        click.echo("Run: autoagent eval run --output results.json")
        return

    click.echo(f"\nLocal eval results ({len(results_files)} files):")
    for f in results_files[:10]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            ts = data.get("timestamp", "unknown")
            composite = data.get("scores", {}).get("composite", 0)
            passed = data.get("passed", "?")
            total = data.get("total", "?")
            click.echo(f"  {f.name}  {ts}  composite={composite:.4f}  {passed}/{total} passed")
        except (json.JSONDecodeError, KeyError):
            click.echo(f"  {f.name}  (invalid format)")


# ---------------------------------------------------------------------------
# autoagent optimize
# ---------------------------------------------------------------------------

@cli.command("optimize")
@click.option("--cycles", default=1, show_default=True, type=int, help="Number of optimization cycles.")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--memory-db", default=MEMORY_DB, show_default=True, help="Optimizer memory DB.")
def optimize(cycles: int, db: str, configs_dir: str, memory_db: str) -> None:
    """Run optimization cycles to improve agent config.

    Examples:
      autoagent optimize
      autoagent optimize --cycles 5
    """
    runtime, eval_runner, proposer = _build_runtime_components()
    store = ConversationStore(db_path=db)
    observer = Observer(store)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    memory = OptimizationMemory(db_path=memory_db)
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=proposer,
        significance_alpha=runtime.eval.significance_alpha,
        significance_min_effect_size=runtime.eval.significance_min_effect_size,
        significance_iterations=runtime.eval.significance_iterations,
    )

    for cycle in range(1, cycles + 1):
        if cycles > 1:
            click.echo(f"\n{'=' * 50}")
            click.echo(f"Cycle {cycle}/{cycles}")
            click.echo(f"{'=' * 50}")

        report = observer.observe()
        click.echo(f"Observed success={report.metrics.success_rate:.2%} error={report.metrics.error_rate:.2%}")

        if not report.needs_optimization:
            click.echo("System healthy; skipping optimization.")
            continue

        current_config = _ensure_active_config(deployer)
        failure_samples = _build_failure_samples(store)
        new_config, status = optimizer.optimize(
            report,
            current_config,
            failure_samples=failure_samples,
        )
        click.echo(f"Optimizer: {status}")

        if new_config is not None:
            score = eval_runner.run(config=new_config)
            deploy_result = deployer.deploy(new_config, _score_to_dict(score))
            click.echo(f"Deploy: {deploy_result}")
            _print_score(score, "New config score")

    if cycles > 1:
        click.echo(f"\nOptimization complete. {cycles} cycles executed.")

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


# ---------------------------------------------------------------------------
# autoagent config (subgroup)
# ---------------------------------------------------------------------------

@cli.group("config")
def config_group() -> None:
    """Manage agent config versions."""


@config_group.command("list")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
def config_list(configs_dir: str) -> None:
    """List all config versions.

    Examples:
      autoagent config list
    """
    store = ConversationStore(db_path=DB_PATH)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    history = deployer.version_manager.get_version_history()

    if not history:
        click.echo("No config versions found.")
        click.echo("Run: autoagent init")
        return

    active = deployer.version_manager.manifest.get("active_version")
    canary = deployer.version_manager.manifest.get("canary_version")

    click.echo(f"\nConfig versions ({len(history)} total):")
    click.echo(f"{'Ver':>5}  {'Status':<12}  {'Hash':<14}  {'Composite':>10}  {'Timestamp'}")
    click.echo(f"{'─' * 5}  {'─' * 12}  {'─' * 14}  {'─' * 10}  {'─' * 24}")

    for v in history:
        ver = v["version"]
        status = v["status"]
        marker = ""
        if ver == active:
            marker = " ●"
        elif ver == canary:
            marker = " ◐"
        composite = v.get("scores", {}).get("composite", 0)
        ts = _ts(v["timestamp"]) if v.get("timestamp") else "—"
        click.echo(
            f"v{ver:03d}   {status:<12}  {v['config_hash']:<14}  "
            f"{composite:>10.4f}  {ts}{marker}"
        )


@config_group.command("show")
@click.argument("version", type=int, required=False)
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
def config_show(version: int | None, configs_dir: str) -> None:
    """Show config YAML for a version (defaults to active).

    Examples:
      autoagent config show
      autoagent config show 3
    """
    store = ConversationStore(db_path=DB_PATH)
    deployer = Deployer(configs_dir=configs_dir, store=store)

    if version is None:
        config = deployer.get_active_config()
        if config is None:
            click.echo("No active config. Run: autoagent init")
            return
        active_ver = deployer.version_manager.manifest.get("active_version", "?")
        click.echo(f"# Active config: v{active_ver:03d}\n")
    else:
        # Find the version file
        history = deployer.version_manager.get_version_history()
        found = None
        for v in history:
            if v["version"] == version:
                found = v
                break
        if found is None:
            click.echo(f"Version {version} not found.")
            return

        filepath = Path(configs_dir) / found["filename"]
        with filepath.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        click.echo(f"# Config: v{version:03d} [{found['status']}]\n")

    click.echo(yaml.safe_dump(config, default_flow_style=False, sort_keys=False))


@config_group.command("diff")
@click.argument("v1", type=int)
@click.argument("v2", type=int)
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
def config_diff(v1: int, v2: int, configs_dir: str) -> None:
    """Diff two config versions.

    Examples:
      autoagent config diff 1 3
    """
    store = ConversationStore(db_path=DB_PATH)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    history = deployer.version_manager.get_version_history()

    configs = {}
    for target_ver in (v1, v2):
        found = None
        for v in history:
            if v["version"] == target_ver:
                found = v
                break
        if found is None:
            click.echo(f"Version {target_ver} not found.")
            return
        filepath = Path(configs_dir) / found["filename"]
        with filepath.open("r", encoding="utf-8") as f:
            configs[target_ver] = yaml.safe_load(f)

    config_a = validate_config(configs[v1])
    config_b = validate_config(configs[v2])
    diff_text = schema_config_diff(config_a, config_b)

    click.echo(f"\nDiff: v{v1:03d} → v{v2:03d}")
    click.echo(f"{'─' * 50}")
    click.echo(diff_text)


# ---------------------------------------------------------------------------
# autoagent deploy
# ---------------------------------------------------------------------------

@cli.command("deploy")
@click.option("--config-version", type=int, default=None,
              help="Config version to deploy. Defaults to latest accepted.")
@click.option("--strategy", type=click.Choice(["canary", "immediate"]),
              default="canary", show_default=True, help="Deployment strategy.")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
def deploy(config_version: int | None, strategy: str, configs_dir: str, db: str) -> None:
    """Deploy a config version.

    Examples:
      autoagent deploy --config-version 5 --strategy canary
      autoagent deploy --strategy immediate
    """
    store = ConversationStore(db_path=db)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    history = deployer.version_manager.get_version_history()

    if not history:
        click.echo("No config versions available. Run: autoagent optimize")
        return

    if config_version is None:
        # Use latest version
        config_version = history[-1]["version"]
        click.echo(f"Deploying latest version: v{config_version:03d}")

    # Find config
    found = None
    for v in history:
        if v["version"] == config_version:
            found = v
            break
    if found is None:
        click.echo(f"Version {config_version} not found.")
        return

    filepath = Path(configs_dir) / found["filename"]
    with filepath.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    scores = found.get("scores", {"composite": 0.0})

    if strategy == "immediate":
        deployer.version_manager.promote(config_version)
        click.echo(f"Deployed v{config_version:03d} immediately (promoted to active).")
    else:
        result = deployer.deploy(config, scores)
        click.echo(f"Deployed v{config_version:03d} as canary.")
        click.echo(f"  {result}")


# ---------------------------------------------------------------------------
# autoagent loop
# ---------------------------------------------------------------------------

@cli.command("loop")
@click.option("--max-cycles", default=50, show_default=True, type=int, help="Maximum optimization cycles.")
@click.option("--stop-on-plateau", is_flag=True, default=False,
              help="Stop if no improvement for 5 consecutive cycles.")
@click.option("--delay", default=1.0, show_default=True, type=float, help="Seconds between cycles.")
@click.option("--schedule", "schedule_mode", default=None,
              type=click.Choice(["continuous", "interval", "cron"]),
              help="Scheduling mode. Defaults to autoagent.yaml loop.schedule_mode.")
@click.option("--interval-minutes", default=None, type=float,
              help="Interval minutes for --schedule interval.")
@click.option("--cron", "cron_expression", default=None,
              help="Cron expression for --schedule cron (5-field UTC).")
@click.option("--checkpoint-file", default=None,
              help="Checkpoint file path. Defaults to autoagent.yaml loop.checkpoint_path.")
@click.option("--resume/--no-resume", default=True, show_default=True,
              help="Resume from checkpoint when available.")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--memory-db", default=MEMORY_DB, show_default=True, help="Optimizer memory DB.")
def loop(max_cycles: int, stop_on_plateau: bool, delay: float, schedule_mode: str | None,
         interval_minutes: float | None, cron_expression: str | None, checkpoint_file: str | None,
         resume: bool, db: str, configs_dir: str, memory_db: str) -> None:
    """Run the continuous autoresearch loop.

    Observes agent health, proposes improvements, evaluates them, and deploys
    accepted changes — automatically, cycle after cycle.

    Examples:
      autoagent loop
      autoagent loop --max-cycles 100 --stop-on-plateau
    """
    runtime, eval_runner, proposer = _build_runtime_components()
    store = ConversationStore(db_path=db)
    observer = Observer(store)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    memory = OptimizationMemory(db_path=memory_db)
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=proposer,
        significance_alpha=runtime.eval.significance_alpha,
        significance_min_effect_size=runtime.eval.significance_min_effect_size,
        significance_iterations=runtime.eval.significance_iterations,
    )

    effective_schedule = schedule_mode or runtime.loop.schedule_mode
    effective_interval = interval_minutes if interval_minutes is not None else runtime.loop.interval_minutes
    effective_cron = cron_expression or runtime.loop.cron
    effective_checkpoint = checkpoint_file or runtime.loop.checkpoint_path

    scheduler = LoopScheduler(
        mode=effective_schedule,
        delay_seconds=delay,
        interval_minutes=effective_interval,
        cron_expression=effective_cron,
    )
    checkpoint_store = LoopCheckpointStore(effective_checkpoint)
    dead_letter_queue = DeadLetterQueue(runtime.loop.dead_letter_db)
    watchdog = LoopWatchdog(runtime.loop.watchdog_timeout_seconds)
    resource_monitor = ResourceMonitor()
    shutdown = GracefulShutdown()
    log = configure_structured_logging(
        log_path=runtime.loop.structured_log_path,
        max_bytes=runtime.loop.log_max_bytes,
        backup_count=runtime.loop.log_backup_count,
    )

    plateau_count = 0
    plateau_threshold = 5
    start_cycle = 1
    completed_cycles = 0

    if resume:
        checkpoint = checkpoint_store.load()
        if checkpoint is not None and checkpoint.last_status != "completed":
            start_cycle = max(1, min(max_cycles, checkpoint.next_cycle))
            plateau_count = max(0, checkpoint.plateau_count)
            completed_cycles = max(0, checkpoint.completed_cycles)

    click.echo(f"Starting autoresearch loop (max {max_cycles} cycles)")
    click.echo(f"  Schedule: {effective_schedule}")
    if effective_schedule == "interval":
        click.echo(f"  Interval: {effective_interval:.2f} minutes")
    if effective_schedule == "cron":
        click.echo(f"  Cron (UTC): {effective_cron}")
    click.echo(f"  Checkpoint: {effective_checkpoint}")
    if start_cycle > 1:
        click.echo(f"  Resuming from cycle {start_cycle}")
    if stop_on_plateau:
        click.echo(f"  Will stop after {plateau_threshold} cycles with no improvement")

    with shutdown.install():
        for cycle in range(start_cycle, max_cycles + 1):
            watchdog.beat()
            cycle_started = time.time()
            checkpoint_store.save(
                LoopCheckpoint(
                    next_cycle=cycle,
                    completed_cycles=completed_cycles,
                    plateau_count=plateau_count,
                    last_status="running",
                    last_cycle_started_at=cycle_started,
                )
            )

            click.echo(f"\n{'═' * 50}")
            click.echo(f" Cycle {cycle}/{max_cycles}")
            click.echo(f"{'═' * 50}")

            improved = False
            try:
                report = observer.observe()
                click.echo(
                    f"  Health: success={report.metrics.success_rate:.2%}, "
                    f"errors={report.metrics.error_rate:.2%}"
                )

                if report.needs_optimization:
                    current_config = _ensure_active_config(deployer)
                    failure_samples = _build_failure_samples(store)
                    new_config, status = optimizer.optimize(
                        report,
                        current_config,
                        failure_samples=failure_samples,
                    )
                    click.echo(f"  Optimizer: {status}")
                    if new_config is not None:
                        improved = True
                        score = eval_runner.run(config=new_config)
                        deploy_result = deployer.deploy(new_config, _score_to_dict(score))
                        click.echo(f"  Deploy: {deploy_result}")
                        click.echo(f"  Score: {score.composite:.4f}")
                else:
                    click.echo("  Healthy; skipping optimization.")

                canary_result = deployer.check_and_act()
                click.echo(f"  Canary: {canary_result}")
            except Exception as exc:
                tb = traceback.format_exc()
                dead_letter_queue.push(
                    kind="loop_cycle",
                    payload={"cycle": cycle},
                    error=str(exc),
                    traceback_text=tb,
                )
                click.echo(f"  Cycle failed; queued in dead letter queue: {exc}")
                log.error(
                    "loop_cycle_failed",
                    extra={"event": "loop_cycle_failed", "cycle": cycle, "status": "failed"},
                )

            completed_cycles = cycle
            cycle_finished = time.time()

            if stop_on_plateau:
                if improved:
                    plateau_count = 0
                else:
                    plateau_count += 1
                    if plateau_count >= plateau_threshold:
                        click.echo(f"\nPlateau detected ({plateau_threshold} cycles with no improvement). Stopping.")
                        checkpoint_store.save(
                            LoopCheckpoint(
                                next_cycle=cycle + 1,
                                completed_cycles=completed_cycles,
                                plateau_count=plateau_count,
                                last_status="stopped_plateau",
                                last_cycle_started_at=cycle_started,
                                last_cycle_finished_at=cycle_finished,
                            )
                        )
                        break

            snapshot = resource_monitor.sample()
            if snapshot.memory_mb > runtime.loop.resource_warn_memory_mb:
                warning = f"Memory usage high: {snapshot.memory_mb:.2f}MB"
                click.echo(f"  Warning: {warning}")
                log.warning(
                    "resource_warning_memory",
                    extra={"event": "resource_warning", "memory_mb": snapshot.memory_mb, "cycle": cycle},
                )
            if snapshot.cpu_percent > runtime.loop.resource_warn_cpu_percent:
                warning = f"CPU usage high: {snapshot.cpu_percent:.2f}%"
                click.echo(f"  Warning: {warning}")
                log.warning(
                    "resource_warning_cpu",
                    extra={"event": "resource_warning", "cpu_percent": snapshot.cpu_percent, "cycle": cycle},
                )

            if watchdog.is_stalled(now=cycle_finished):
                stall_error = (
                    f"Watchdog detected stall: {watchdog.seconds_since_last_beat(now=cycle_finished):.2f}s "
                    f"> timeout {watchdog.timeout_seconds:.2f}s"
                )
                dead_letter_queue.push(
                    kind="watchdog",
                    payload={"cycle": cycle},
                    error=stall_error,
                )
                click.echo(f"  Watchdog: {stall_error}")
                log.warning("watchdog_stall", extra={"event": "watchdog_stall", "cycle": cycle})
            watchdog.beat()

            checkpoint_store.save(
                LoopCheckpoint(
                    next_cycle=cycle + 1,
                    completed_cycles=completed_cycles,
                    plateau_count=plateau_count,
                    last_status="running",
                    last_cycle_started_at=cycle_started,
                    last_cycle_finished_at=cycle_finished,
                )
            )

            if shutdown.stop_requested:
                click.echo("\nGraceful shutdown requested. Exiting after current cycle.")
                break

            if cycle < max_cycles:
                wait_seconds = scheduler.seconds_until_next(
                    now_epoch=time.time(),
                    cycle_started_at=cycle_started,
                    cycle_finished_at=cycle_finished,
                )
                _sleep_interruptibly(wait_seconds, shutdown)
                if shutdown.stop_requested:
                    click.echo("\nGraceful shutdown requested during wait. Exiting.")
                    break

    final_status = "completed" if completed_cycles >= max_cycles and not shutdown.stop_requested else "stopped"
    checkpoint_store.save(
        LoopCheckpoint(
            next_cycle=completed_cycles + 1,
            completed_cycles=completed_cycles,
            plateau_count=plateau_count,
            last_status=final_status,
            last_cycle_finished_at=time.time(),
        )
    )
    click.echo(f"\nLoop complete. {completed_cycles} cycles executed ({final_status}).")


# ---------------------------------------------------------------------------
# autoagent status
# ---------------------------------------------------------------------------

@cli.command("status")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--memory-db", default=MEMORY_DB, show_default=True, help="Optimizer memory DB.")
def status(db: str, configs_dir: str, memory_db: str) -> None:
    """Show system health, config versions, and recent activity.

    Examples:
      autoagent status
    """
    click.echo("\n╔══════════════════════════════════════════════════╗")
    click.echo("║           AutoAgent VNextCC Status               ║")
    click.echo("╚══════════════════════════════════════════════════╝")

    # Conversations
    store = ConversationStore(db_path=db)
    total_conversations = store.count()
    click.echo(f"\n  Conversations: {total_conversations}")

    if total_conversations > 0:
        report = Observer(store).observe()
        metrics = report.metrics
        # Color-code success rate
        sr = metrics.success_rate
        sr_indicator = "●" if sr >= 0.8 else "◐" if sr >= 0.6 else "○"
        click.echo(f"  {sr_indicator} Success rate:  {sr:.2%}")
        click.echo(f"    Error rate:    {metrics.error_rate:.2%}")
        click.echo(f"    Avg latency:   {metrics.avg_latency_ms:.1f}ms")
        click.echo(f"    Safety:        {metrics.safety_violation_rate:.2%} violations")

        if report.needs_optimization:
            click.echo(f"\n  ⚠ Optimization recommended: {report.reason}")

    # Deployment status
    deployer = Deployer(configs_dir=configs_dir, store=store)
    deploy_status = deployer.status()
    click.echo(f"\n  Config versions: {deploy_status['total_versions']}")

    active = deploy_status["active_version"]
    canary = deploy_status["canary_version"]
    click.echo(f"    Active:  v{active:03d}" if active else "    Active:  none")
    if canary:
        click.echo(f"    Canary:  v{canary:03d}")

    # Recent optimization attempts
    memory = OptimizationMemory(db_path=memory_db)
    recent = memory.recent(limit=5)
    if recent:
        click.echo("\n  Recent optimizations:")
        for attempt in recent:
            status_icon = "✓" if attempt.status == "accepted" else "✗"
            delta = attempt.score_after - attempt.score_before
            delta_str = f"+{delta:.4f}" if delta > 0 else f"{delta:.4f}"
            click.echo(f"    {status_icon} [{attempt.status}] {attempt.change_description}")
            click.echo(f"      Score: {attempt.score_before:.4f} → {attempt.score_after:.4f} ({delta_str})")


# ---------------------------------------------------------------------------
# autoagent logs
# ---------------------------------------------------------------------------

@cli.command("logs")
@click.option("--limit", default=20, show_default=True, type=int, help="Number of logs to show.")
@click.option("--outcome", default=None, type=click.Choice(["success", "fail", "error", "abandon"]),
              help="Filter by outcome.")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
def logs(limit: int, outcome: str | None, db: str) -> None:
    """Browse conversation logs.

    Examples:
      autoagent logs
      autoagent logs --limit 50 --outcome fail
    """
    store = ConversationStore(db_path=db)

    if outcome:
        records = store.get_by_outcome(outcome)[:limit]
    else:
        records = store.get_recent(limit=limit)

    if not records:
        click.echo("No conversations found.")
        return

    click.echo(f"\nConversation logs ({len(records)} shown):")
    click.echo(f"{'ID':<38}  {'Outcome':<10}  {'Specialist':<16}  {'Latency':>8}  {'Message'}")
    click.echo(f"{'─' * 38}  {'─' * 10}  {'─' * 16}  {'─' * 8}  {'─' * 30}")

    for r in records:
        msg = (r.user_message[:40] + "...") if len(r.user_message) > 40 else r.user_message
        specialist = r.specialist_used or "—"
        latency = f"{r.latency_ms}ms" if r.latency_ms else "—"
        click.echo(f"{r.conversation_id:<38}  {r.outcome:<10}  {specialist:<16}  {latency:>8}  {msg}")


# ---------------------------------------------------------------------------
# autoagent doctor
# ---------------------------------------------------------------------------

@cli.command("doctor")
@click.option("--config", "config_path", default="autoagent.yaml", show_default=True,
              help="Path to runtime config YAML.")
def doctor(config_path: str) -> None:
    """Check system health and configuration.

    Reports on API keys, mock mode, data stores, eval cases, and config versions.

    Examples:
      autoagent doctor
    """
    import sqlite3

    issues: list[str] = []

    click.echo("\nAutoAgent Doctor")
    click.echo("================")

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    click.echo("\nConfiguration")
    runtime = load_runtime_config(config_path)
    if runtime.optimizer.use_mock:
        issues.append("Mock mode is enabled")
        click.echo(
            "  Mock mode:          "
            + click.style(
                "\u26a0 Enabled (set optimizer.use_mock: false in autoagent.yaml for production)",
                fg="yellow",
            )
        )
    else:
        click.echo(
            "  Mock mode:          " + click.style("\u2713 Disabled", fg="green")
        )

    # ------------------------------------------------------------------
    # API Keys
    # ------------------------------------------------------------------
    click.echo("\nAPI Keys")
    api_keys = [
        ("OPENAI_API_KEY", "OPENAI_API_KEY"),
        ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        ("GOOGLE_API_KEY", "GOOGLE_API_KEY"),
    ]
    for label, env_var in api_keys:
        if os.environ.get(env_var):
            click.echo(
                f"  {label + ':':<22}" + click.style("\u2713 Set", fg="green")
            )
        else:
            issues.append(f"{label} is not set")
            click.echo(
                f"  {label + ':':<22}" + click.style("\u2717 Not set", fg="red")
            )

    # ------------------------------------------------------------------
    # Data Stores
    # ------------------------------------------------------------------
    click.echo("\nData Stores")

    # Traces DB
    traces_db = Path(".autoagent") / "traces.db"
    if traces_db.exists():
        try:
            with sqlite3.connect(str(traces_db)) as conn:
                tables = [
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                ]
                row_count = 0
                for table in tables:
                    try:
                        row_count += conn.execute(
                            f"SELECT COUNT(*) FROM {table}"  # noqa: S608
                        ).fetchone()[0]
                    except sqlite3.OperationalError:
                        pass
            if row_count > 0:
                click.echo(
                    "  Traces:             "
                    + click.style(f"\u2713 {row_count} rows", fg="green")
                )
            else:
                issues.append("Traces DB is empty")
                click.echo(
                    "  Traces:             "
                    + click.style(
                        "\u2717 Empty (run your agent with tracing enabled)", fg="red"
                    )
                )
        except sqlite3.DatabaseError:
            issues.append("Traces DB is unreadable")
            click.echo(
                "  Traces:             "
                + click.style("\u2717 Unreadable (DB may be corrupt)", fg="red")
            )
    else:
        issues.append("Traces DB does not exist")
        click.echo(
            "  Traces:             "
            + click.style(
                "\u2717 Empty (run your agent with tracing enabled)", fg="red"
            )
        )

    # Eval cases
    eval_cases_dir = Path("evals") / "cases"
    if eval_cases_dir.is_dir():
        yaml_files = list(eval_cases_dir.glob("*.yaml"))
        if yaml_files:
            # Count individual cases (documents) across files
            total_cases = 0
            for f in yaml_files:
                try:
                    with f.open("r", encoding="utf-8") as fh:
                        docs = list(yaml.safe_load_all(fh))
                    total_cases += sum(1 for d in docs if d is not None)
                except Exception:
                    total_cases += 1  # count the file itself if unparseable
            click.echo(
                "  Eval cases:         "
                + click.style(
                    f"\u2713 {total_cases} cases in {len(yaml_files)} files", fg="green"
                )
            )
        else:
            issues.append("No eval case YAML files found")
            click.echo(
                "  Eval cases:         "
                + click.style("\u2717 No YAML files in evals/cases/", fg="red")
            )
    else:
        issues.append("evals/cases/ directory does not exist")
        click.echo(
            "  Eval cases:         "
            + click.style("\u2717 evals/cases/ not found", fg="red")
        )

    # Config versions
    configs_dir = Path(CONFIGS_DIR)
    if configs_dir.is_dir():
        version_files = list(configs_dir.glob("*.yaml"))
        if version_files:
            click.echo(
                "  Config versions:    "
                + click.style(f"\u2713 {len(version_files)} versions", fg="green")
            )
        else:
            issues.append("No config version files found")
            click.echo(
                "  Config versions:    "
                + click.style("\u2717 No versions in configs/", fg="red")
            )
    else:
        issues.append("configs/ directory does not exist")
        click.echo(
            "  Config versions:    "
            + click.style("\u2717 configs/ not found", fg="red")
        )

    # Conversations DB
    conversations_db = Path(DB_PATH)
    if conversations_db.exists():
        try:
            store = ConversationStore(db_path=str(conversations_db))
            count = store.count()
            if count > 0:
                click.echo(
                    "  Conversations:      "
                    + click.style(f"\u2713 {count} conversations", fg="green")
                )
            else:
                issues.append("Conversations DB is empty")
                click.echo(
                    "  Conversations:      "
                    + click.style("\u2717 Empty", fg="red")
                )
        except Exception:
            issues.append("Conversations DB is unreadable")
            click.echo(
                "  Conversations:      "
                + click.style("\u2717 Unreadable", fg="red")
            )
    else:
        issues.append("Conversations DB does not exist")
        click.echo(
            "  Conversations:      "
            + click.style("\u2717 Empty", fg="red")
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    click.echo("")
    if issues:
        click.echo(
            click.style(
                f"Status: {len(issues)} issue{'s' if len(issues) != 1 else ''} found \u2014 see warnings above",
                fg="yellow",
            )
        )
    else:
        click.echo(click.style("Status: All checks passed \u2713", fg="green"))


# ---------------------------------------------------------------------------
# autoagent server
# ---------------------------------------------------------------------------

@cli.command("server")
@click.option("--host", default="0.0.0.0", show_default=True, help="Host to bind to.")
@click.option("--port", default=8000, show_default=True, type=int, help="Port to bind to.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload for development.")
def server(host: str, port: int, reload: bool) -> None:
    """Start the API server + web console.

    Starts the FastAPI backend serving both the REST API and the web console.
    API docs available at http://localhost:8000/docs

    Examples:
      autoagent server
      autoagent server --port 3000 --reload
    """
    import uvicorn

    click.echo(f"Starting AutoAgent VNextCC server on {host}:{port}")
    click.echo(f"  API docs:     http://localhost:{port}/docs")
    click.echo(f"  Web console:  http://localhost:{port}")
    click.echo(f"  WebSocket:    ws://localhost:{port}/ws")

    uvicorn.run(
        "api.server:app",
        host=host,
        port=port,
        reload=reload,
    )


# ---------------------------------------------------------------------------
# Legacy: autoagent run (kept for backward compatibility)
# ---------------------------------------------------------------------------

@cli.group("run", hidden=True)
def run_group() -> None:
    """Legacy run commands (use top-level commands instead)."""


@run_group.command("agent")
@click.option("--host", default="0.0.0.0", show_default=True, help="Host to bind to.")
@click.option("--port", default=8000, show_default=True, type=int, help="Port to bind to.")
def run_agent(host: str, port: int) -> None:
    """Start the ADK agent API server (legacy)."""
    import uvicorn

    from agent.server import app

    click.echo(f"Starting AutoAgent server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


@run_group.command("eval")
@click.option("--config-path", default=None, help="Path to config YAML.")
@click.option("--category", default=None, help="Run only a specific category.")
def run_eval(config_path: str | None, category: str | None) -> None:
    """Run eval suite (legacy). Use: autoagent eval run"""
    config = None
    if config_path:
        config = _load_config_dict(config_path)
    runtime = load_runtime_config()
    runner = EvalRunner(history_db_path=runtime.eval.history_db_path)
    if category:
        score = runner.run_category(category, config=config)
        _print_score(score, f"Category: {category}")
    else:
        score = runner.run(config=config)
        _print_score(score, "Full eval suite")


@run_group.command("observe")
@click.option("--db", default=DB_PATH, show_default=True)
@click.option("--window", default=100, show_default=True, type=int)
def run_observe(db: str, window: int) -> None:
    """Run observer (legacy). Use: autoagent status"""
    store = ConversationStore(db_path=db)
    observer = Observer(store)
    report = observer.observe(window=window)
    metrics = report.metrics
    click.echo(f"\nHealth Report ({metrics.total_conversations} conversations)")
    click.echo(f"  Success rate:       {metrics.success_rate:.2%}")
    click.echo(f"  Avg latency:        {metrics.avg_latency_ms:.1f}ms")
    click.echo(f"  Error rate:         {metrics.error_rate:.2%}")
    click.echo(f"  Safety violations:  {metrics.safety_violation_rate:.2%}")
    click.echo(f"  Avg cost:           ${metrics.avg_cost:.4f}")


@run_group.command("optimize")
@click.option("--db", default=DB_PATH, show_default=True)
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True)
@click.option("--memory-db", default=MEMORY_DB, show_default=True)
def run_optimize(db: str, configs_dir: str, memory_db: str) -> None:
    """Run optimize (legacy). Use: autoagent optimize"""
    runtime, eval_runner, proposer = _build_runtime_components()
    store = ConversationStore(db_path=db)
    observer = Observer(store)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    memory = OptimizationMemory(db_path=memory_db)
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=proposer,
        significance_alpha=runtime.eval.significance_alpha,
        significance_min_effect_size=runtime.eval.significance_min_effect_size,
        significance_iterations=runtime.eval.significance_iterations,
    )
    report = observer.observe()
    click.echo(f"Observed success={report.metrics.success_rate:.2%} error={report.metrics.error_rate:.2%}")
    if not report.needs_optimization:
        click.echo("System healthy; skipping optimization.")
        return
    current_config = _ensure_active_config(deployer)
    failure_samples = _build_failure_samples(store)
    new_config, status_msg = optimizer.optimize(report, current_config, failure_samples=failure_samples)
    click.echo(f"Optimizer result: {status_msg}")
    if new_config is not None:
        score = eval_runner.run(config=new_config)
        deploy_result = deployer.deploy(new_config, _score_to_dict(score))
        click.echo(f"Deploy result: {deploy_result}")


@run_group.command("loop")
@click.option("--cycles", default=5, show_default=True, type=int)
@click.option("--db", default=DB_PATH, show_default=True)
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True)
@click.option("--memory-db", default=MEMORY_DB, show_default=True)
@click.option("--delay", default=1.0, show_default=True, type=float)
def run_loop(cycles: int, db: str, configs_dir: str, memory_db: str, delay: float) -> None:
    """Run loop (legacy). Use: autoagent loop"""
    runtime, eval_runner, proposer = _build_runtime_components()
    store = ConversationStore(db_path=db)
    observer = Observer(store)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    memory = OptimizationMemory(db_path=memory_db)
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=proposer,
        significance_alpha=runtime.eval.significance_alpha,
        significance_min_effect_size=runtime.eval.significance_min_effect_size,
        significance_iterations=runtime.eval.significance_iterations,
    )
    click.echo(f"Starting optimization loop ({cycles} cycles)")
    for cycle_num in range(1, cycles + 1):
        click.echo(f"\n{'=' * 50}\nCycle {cycle_num}/{cycles}\n{'=' * 50}")
        report = observer.observe()
        click.echo(f"  Health: success={report.metrics.success_rate:.2%}, errors={report.metrics.error_rate:.2%}")
        if report.needs_optimization:
            current_config = _ensure_active_config(deployer)
            failure_samples = _build_failure_samples(store)
            new_config, status_msg = optimizer.optimize(report, current_config, failure_samples=failure_samples)
            click.echo(f"  Optimizer: {status_msg}")
            if new_config is not None:
                score = eval_runner.run(config=new_config)
                deploy_result = deployer.deploy(new_config, _score_to_dict(score))
                click.echo(f"  Deploy: {deploy_result}")
        else:
            click.echo("  Healthy; skipping optimization.")
        canary_result = deployer.check_and_act()
        click.echo(f"  Canary: {canary_result}")
        if cycle_num < cycles:
            time.sleep(delay)
    click.echo(f"\nLoop complete. {cycles} cycles executed.")


@run_group.command("status")
@click.option("--db", default=DB_PATH, show_default=True)
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True)
@click.option("--memory-db", default=MEMORY_DB, show_default=True)
def run_status(db: str, configs_dir: str, memory_db: str) -> None:
    """Show status (legacy). Use: autoagent status"""
    store = ConversationStore(db_path=db)
    total = store.count()
    click.echo(f"\nConversations: {total} total")
    if total > 0:
        report = Observer(store).observe()
        m = report.metrics
        click.echo(f"  Success rate:  {m.success_rate:.2%}")
        click.echo(f"  Error rate:    {m.error_rate:.2%}")
        click.echo(f"  Avg latency:   {m.avg_latency_ms:.1f}ms")
    deployer = Deployer(configs_dir=configs_dir, store=store)
    ds = deployer.status()
    click.echo(f"\nConfig versions: {ds['total_versions']}")
    active = ds["active_version"]
    canary = ds["canary_version"]
    click.echo(f"  Active:  v{active:03d}" if active else "  Active:  none")
    click.echo(f"  Canary:  v{canary:03d}" if canary else "  Canary:  none")


if __name__ == "__main__":
    cli()
