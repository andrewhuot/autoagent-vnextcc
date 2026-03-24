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
  autoagent registry list [--type skills|policies|tools|handoffs]
  autoagent registry show <type> <name> [--version N]
  autoagent registry add <type> <name> --file <path>
  autoagent registry diff <type> <name> <v1> <v2>
  autoagent registry import <path>
  autoagent trace grade <trace-id>
  autoagent trace blame [--window 24h]
  autoagent trace graph <trace-id>
  autoagent scorer create "description" [--name NAME]
  autoagent scorer create --from-file criteria.txt [--name NAME]
  autoagent scorer list
  autoagent scorer show <name>
  autoagent scorer refine <name> "additional criteria"
  autoagent scorer test <name> --trace <trace-id>
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
REGISTRY_DB = os.environ.get("AUTOAGENT_REGISTRY_DB", "registry.db")
TRACE_DB = os.environ.get("AUTOAGENT_TRACE_DB", "traces.db")


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
# Human escape hatch CLI commands (from R2 simplicity thesis)
# ---------------------------------------------------------------------------

def _control_store():
    """Return a HumanControlStore using default or env-configured path."""
    from optimizer.human_control import HumanControlStore
    return HumanControlStore()


def _event_log():
    """Return an EventLog using default or env-configured path."""
    from data.event_log import EventLog
    return EventLog()


@cli.command("pause")
def pause_optimizer() -> None:
    """Pause the optimization loop (human escape hatch).

    Examples:
      autoagent pause
    """
    store = _control_store()
    store.pause()
    _event_log().append(event_type="human_pause", payload={"paused": True})
    click.echo("Optimizer paused. Run 'autoagent resume' to continue.")


@cli.command("resume")
def resume_optimizer() -> None:
    """Resume the optimization loop after a pause.

    Examples:
      autoagent resume
    """
    store = _control_store()
    store.resume()
    click.echo("Optimizer resumed.")


@cli.command("reject")
@click.argument("experiment_id", type=str)
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
def reject_experiment(experiment_id: str, configs_dir: str, db: str) -> None:
    """Reject a promoted experiment and rollback any active canary.

    Examples:
      autoagent reject abc12345
    """
    store = _control_store()
    store.reject_experiment(experiment_id)

    conv_store = ConversationStore(db_path=db)
    deployer = Deployer(configs_dir=configs_dir, store=conv_store)
    canary = deployer.version_manager.manifest.get("canary_version")
    if canary is not None:
        deployer.version_manager.rollback(canary)
        _event_log().append(
            event_type="rollback_triggered",
            payload={"canary_version": canary, "reason": "human_reject"},
            experiment_id=experiment_id,
        )
        click.echo(f"Rejected experiment {experiment_id} and rolled back canary v{canary:03d}.")
    else:
        click.echo(f"Rejected experiment {experiment_id}. No active canary to rollback.")

    _event_log().append(
        event_type="human_reject",
        payload={"experiment_id": experiment_id},
        experiment_id=experiment_id,
    )


@cli.command("pin")
@click.argument("surface", type=str)
def pin_surface(surface: str) -> None:
    """Mark a config surface as immutable (e.g. prompts.root, safety_instructions).

    Examples:
      autoagent pin safety_instructions
      autoagent pin prompts.root
    """
    store = _control_store()
    store.pin_surface(surface)
    click.echo(f"Pinned '{surface}' as immutable. Optimizer will not modify it.")


@cli.command("unpin")
@click.argument("surface", type=str)
def unpin_surface(surface: str) -> None:
    """Remove immutable marking from a config surface.

    Examples:
      autoagent unpin safety_instructions
    """
    store = _control_store()
    store.unpin_surface(surface)
    click.echo(f"Unpinned '{surface}'. Optimizer can now modify it.")


# ---------------------------------------------------------------------------
# autoagent autofix (subgroup)
# ---------------------------------------------------------------------------

@cli.group("autofix")
def autofix_group() -> None:
    """AutoFix Copilot — reviewable improvement proposals."""


@autofix_group.command("suggest")
def autofix_suggest() -> None:
    """Generate AutoFix proposals without applying them.

    Examples:
      autoagent autofix suggest
    """
    from optimizer.autofix import AutoFixEngine, AutoFixStore
    from optimizer.autofix_proposers import (
        CostOptimizationProposer,
        FailurePatternProposer,
        RegressionProposer,
    )
    from optimizer.mutations import create_default_registry

    store = AutoFixStore()
    registry = create_default_registry()
    proposers = [FailurePatternProposer(), RegressionProposer(), CostOptimizationProposer()]
    engine = AutoFixEngine(proposers=proposers, mutation_registry=registry, store=store)

    deployer = Deployer(configs_dir=CONFIGS_DIR, store=ConversationStore(db_path=DB_PATH))
    current_config = _ensure_active_config(deployer)
    failures = _build_failure_samples(ConversationStore(db_path=DB_PATH))

    proposals = engine.suggest(failures, current_config)
    if not proposals:
        click.echo("No proposals generated.")
        return

    click.echo(f"\n{len(proposals)} proposal(s) generated:\n")
    for p in proposals:
        risk_color = {"low": "green", "medium": "yellow", "high": "red"}.get(p.risk_class, "white")
        click.echo(f"  [{p.proposal_id}] {p.mutation_name}")
        click.echo(f"    Surface: {p.surface}  Risk: {click.style(p.risk_class, fg=risk_color)}")
        click.echo(f"    Expected lift: {p.expected_lift:.1%}  Cost impact: ${p.cost_impact_estimate:.4f}")
        if p.diff_preview:
            click.echo(f"    Preview: {p.diff_preview[:80]}")
        click.echo()


@autofix_group.command("apply")
@click.argument("proposal_id", type=str)
def autofix_apply(proposal_id: str) -> None:
    """Apply a specific AutoFix proposal.

    Examples:
      autoagent autofix apply abc123
    """
    from optimizer.autofix import AutoFixEngine, AutoFixStore
    from optimizer.mutations import create_default_registry

    store = AutoFixStore()
    registry = create_default_registry()
    engine = AutoFixEngine(proposers=[], mutation_registry=registry, store=store)

    deployer = Deployer(configs_dir=CONFIGS_DIR, store=ConversationStore(db_path=DB_PATH))
    current_config = _ensure_active_config(deployer)

    try:
        new_config, status_msg = engine.apply(proposal_id, current_config)
        click.echo(f"Applied: {status_msg}")
        if new_config:
            click.echo("New config generated. Run 'autoagent eval run' to validate.")
    except ValueError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"))


@autofix_group.command("history")
@click.option("--limit", default=20, show_default=True, type=int, help="Number of proposals to show.")
def autofix_history(limit: int) -> None:
    """Show past AutoFix proposals and outcomes.

    Examples:
      autoagent autofix history
    """
    from optimizer.autofix import AutoFixEngine, AutoFixStore

    store = AutoFixStore()
    engine = AutoFixEngine(proposers=[], mutation_registry=None, store=store)
    proposals = engine.history(limit=limit)

    if not proposals:
        click.echo("No AutoFix history found.")
        return

    click.echo(f"\nAutoFix history ({len(proposals)} proposals):\n")
    click.echo(f"{'ID':<14}  {'Mutation':<24}  {'Status':<12}  {'Lift':>8}  {'Risk':<8}")
    click.echo(f"{'─' * 14}  {'─' * 24}  {'─' * 12}  {'─' * 8}  {'─' * 8}")
    for p in proposals:
        click.echo(
            f"{p.proposal_id:<14}  {p.mutation_name:<24}  {p.status:<12}  "
            f"{p.expected_lift:>7.1%}  {p.risk_class:<8}"
        )


# ---------------------------------------------------------------------------
# autoagent judges (subgroup)
# ---------------------------------------------------------------------------

@cli.group("judges")
def judges_group() -> None:
    """Judge Ops — monitoring, calibration, and human feedback."""


@judges_group.command("list")
def judges_list() -> None:
    """Show active judges with version and agreement stats.

    Examples:
      autoagent judges list
    """
    from judges.versioning import GraderVersionStore
    from judges.human_feedback import HumanFeedbackStore

    version_store = GraderVersionStore()
    feedback_store = HumanFeedbackStore()

    grader_ids = version_store.list_all_graders()
    if not grader_ids:
        click.echo("No judges registered yet.")
        return

    click.echo(f"\nActive judges ({len(grader_ids)}):\n")
    click.echo(f"{'Judge ID':<24}  {'Version':>8}  {'Agreement':>10}")
    click.echo(f"{'─' * 24}  {'─' * 8}  {'─' * 10}")
    for gid in grader_ids:
        latest = version_store.get_latest(gid)
        agreement = feedback_store.agreement_rate(judge_id=gid)
        ver = latest.version if latest else 0
        click.echo(f"{gid:<24}  v{ver:>6}  {agreement:>9.1%}")


@judges_group.command("calibrate")
@click.option("--sample", default=50, show_default=True, type=int, help="Number of cases to sample.")
@click.option("--judge-id", default=None, help="Filter to a specific judge.")
def judges_calibrate(sample: int, judge_id: str | None) -> None:
    """Sample cases for human calibration review.

    Examples:
      autoagent judges calibrate --sample 50
      autoagent judges calibrate --judge-id llm_judge
    """
    from judges.human_feedback import HumanFeedbackStore

    store = HumanFeedbackStore()
    cases = store.sample_for_review(judge_id=judge_id, n=sample)

    if not cases:
        click.echo("No feedback data available for sampling.")
        return

    agreement = store.agreement_rate(judge_id=judge_id)
    click.echo(f"\nCalibration sample ({len(cases)} cases):")
    click.echo(f"Overall agreement rate: {agreement:.1%}\n")

    click.echo(f"{'Case ID':<20}  {'Judge':>8}  {'Human':>8}  {'Gap':>8}")
    click.echo(f"{'─' * 20}  {'─' * 8}  {'─' * 8}  {'─' * 8}")
    for fb in cases:
        gap = abs(fb.judge_score - fb.human_score)
        click.echo(
            f"{fb.case_id:<20}  {fb.judge_score:>8.2f}  {fb.human_score:>8.2f}  {gap:>8.2f}"
        )


@judges_group.command("drift")
def judges_drift() -> None:
    """Show drift report for all judges.

    Examples:
      autoagent judges drift
    """
    from judges.drift_monitor import DriftMonitor

    monitor = DriftMonitor()
    alerts = monitor.run_all_checks(verdicts=[])

    if not alerts:
        click.echo("No drift detected. All judges are stable.")
        return

    click.echo(f"\nDrift alerts ({len(alerts)}):\n")
    for alert in alerts:
        severity_color = "red" if alert.severity > 0.5 else "yellow"
        click.echo(
            f"  [{alert.alert_type}] {alert.grader_id}  "
            f"severity={click.style(f'{alert.severity:.1%}', fg=severity_color)}"
        )


# ---------------------------------------------------------------------------
# autoagent context (subgroup)
# ---------------------------------------------------------------------------

@cli.group("context")
def context_group() -> None:
    """Context Engineering Workbench — diagnose and tune agent context."""


@context_group.command("analyze")
@click.option("--trace", "trace_id", required=True, help="Trace ID to analyze.")
def context_analyze(trace_id: str) -> None:
    """Analyze context utilization for a trace.

    Examples:
      autoagent context analyze --trace abc123
    """
    from context.analyzer import ContextAnalyzer
    from observer.traces import TraceStore

    trace_store = TraceStore(db_path=".autoagent/traces.db")
    analyzer = ContextAnalyzer(trace_store=trace_store)

    events = trace_store.get_events(trace_id=trace_id)
    if not events:
        click.echo(f"No events found for trace: {trace_id}")
        return

    event_dicts = [
        {
            "event_type": e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type),
            "tokens_in": e.tokens_in,
            "tokens_out": e.tokens_out,
            "error_message": e.error_message,
            "metadata": e.metadata if isinstance(e.metadata, dict) else {},
        }
        for e in events
    ]

    analysis = analyzer.analyze_trace(event_dicts)
    click.echo(f"\nContext Analysis for trace {trace_id}:")
    click.echo(f"  Growth pattern: {analysis.growth_pattern.pattern_type}")
    click.echo(f"  Peak utilization: {analysis.peak_utilization:.1%}")
    click.echo(f"  Avg utilization: {analysis.avg_utilization:.1%}")
    click.echo(f"  Compaction events: {analysis.growth_pattern.compaction_events}")

    if analysis.recommendations:
        click.echo("\n  Recommendations:")
        for r in analysis.recommendations:
            click.echo(f"    - {r}")


@context_group.command("simulate")
@click.option("--strategy", default="balanced", show_default=True,
              type=click.Choice(["aggressive", "balanced", "conservative"]),
              help="Compaction strategy to simulate.")
def context_simulate(strategy: str) -> None:
    """Simulate a compaction strategy.

    Examples:
      autoagent context simulate --strategy aggressive
    """
    from context.simulator import CompactionSimulator

    simulator = CompactionSimulator()
    strategies = {s.name: s for s in simulator.default_strategies()}

    selected = strategies.get(strategy)
    if not selected:
        click.echo(f"Unknown strategy: {strategy}")
        return

    click.echo(f"\nCompaction Strategy: {selected.name}")
    click.echo(f"  Max tokens: {selected.max_tokens}")
    click.echo(f"  Trigger: {selected.compaction_trigger:.0%} utilization")
    click.echo(f"  Retention: {selected.retention_ratio:.0%}")
    click.echo(f"\n  (Provide trace data via API for full simulation)")


@context_group.command("report")
def context_report() -> None:
    """Show aggregate context health report.

    Examples:
      autoagent context report
    """
    click.echo("\nContext Health Report")
    click.echo("=" * 40)
    click.echo("  Utilization ratio:   — (no trace data)")
    click.echo("  Compaction loss:     — (no trace data)")
    click.echo("  Handoff fidelity:    — (no trace data)")
    click.echo("  Memory staleness:    — (no trace data)")
    click.echo("\n  Run 'autoagent context analyze --trace <id>' for per-trace analysis.")


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


# ---------------------------------------------------------------------------
# autoagent registry ...
# ---------------------------------------------------------------------------

REGISTRY_TYPES = ("skills", "policies", "tools", "handoffs")

_REGISTRY_MAP = {
    "skills": "SkillRegistry",
    "policies": "PolicyRegistry",
    "tools": "ToolContractRegistry",
    "handoffs": "HandoffSchemaRegistry",
}


def _get_registry(registry_type: str, store: object) -> object:
    """Return the correct registry instance for a given type string."""
    from registry import (
        HandoffSchemaRegistry,
        PolicyRegistry,
        SkillRegistry,
        ToolContractRegistry,
    )

    mapping = {
        "skills": SkillRegistry,
        "policies": PolicyRegistry,
        "tools": ToolContractRegistry,
        "handoffs": HandoffSchemaRegistry,
    }
    cls = mapping.get(registry_type)
    if cls is None:
        raise click.BadParameter(
            f"Unknown type '{registry_type}'. Choose from: {', '.join(REGISTRY_TYPES)}"
        )
    return cls(store)


@cli.group("registry")
def registry_group() -> None:
    """Modular registry — skills, policies, tool contracts, handoff schemas."""


@registry_group.command("list")
@click.option("--type", "registry_type", default=None,
              type=click.Choice(REGISTRY_TYPES, case_sensitive=False),
              help="Filter by registry type.")
@click.option("--db", default=REGISTRY_DB, show_default=True)
def registry_list(registry_type: str | None, db: str) -> None:
    """List registered items.

    Examples:
      autoagent registry list
      autoagent registry list --type skills
    """
    from registry import RegistryStore

    store = RegistryStore(db_path=db)
    types_to_show = [registry_type] if registry_type else list(REGISTRY_TYPES)

    for rtype in types_to_show:
        reg = _get_registry(rtype, store)
        items = reg.list()
        click.echo(f"\n{rtype.upper()} ({len(items)})")
        if not items:
            click.echo("  (none)")
            continue
        for item in items:
            name = item.get("name") or item.get("tool_name", "?")
            ver = item.get("version", "?")
            click.echo(f"  {name:30s}  v{ver}")


@registry_group.command("show")
@click.argument("registry_type", type=click.Choice(REGISTRY_TYPES, case_sensitive=False))
@click.argument("name")
@click.option("--version", "version", default=None, type=int, help="Specific version.")
@click.option("--db", default=REGISTRY_DB, show_default=True)
def registry_show(registry_type: str, name: str, version: int | None, db: str) -> None:
    """Show details for a registry item.

    Examples:
      autoagent registry show skills returns_handling
      autoagent registry show tools order_lookup --version 2
    """
    from registry import RegistryStore

    store = RegistryStore(db_path=db)
    reg = _get_registry(registry_type, store)
    item = reg.get(name, version)
    if item is None:
        click.echo(f"Not found: {registry_type}/{name}" +
                   (f" v{version}" if version else ""))
        raise SystemExit(1)
    click.echo(json.dumps(item, indent=2, default=str))


@registry_group.command("add")
@click.argument("registry_type", type=click.Choice(REGISTRY_TYPES, case_sensitive=False))
@click.argument("name")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True),
              help="YAML/JSON file with item data.")
@click.option("--db", default=REGISTRY_DB, show_default=True)
def registry_add(registry_type: str, name: str, file_path: str, db: str) -> None:
    """Add a new item (or new version) to the registry.

    Examples:
      autoagent registry add skills returns_handling --file skill.yaml
    """
    from registry import RegistryStore

    store = RegistryStore(db_path=db)
    reg = _get_registry(registry_type, store)

    path = Path(file_path)
    raw = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        data = yaml.safe_load(raw)
    else:
        data = json.loads(raw)

    if isinstance(data, dict):
        data["name"] = name
        result = reg.register(**data)
        click.echo(f"Registered {registry_type}/{name} -> v{result[1]}")
    else:
        click.echo("Error: file must contain a JSON/YAML object.", err=True)
        raise SystemExit(1)


@registry_group.command("diff")
@click.argument("registry_type", type=click.Choice(REGISTRY_TYPES, case_sensitive=False))
@click.argument("name")
@click.argument("v1", type=int)
@click.argument("v2", type=int)
@click.option("--db", default=REGISTRY_DB, show_default=True)
def registry_diff(registry_type: str, name: str, v1: int, v2: int, db: str) -> None:
    """Diff two versions of a registry item.

    Examples:
      autoagent registry diff skills returns_handling 1 2
    """
    from registry import RegistryStore

    store = RegistryStore(db_path=db)
    reg = _get_registry(registry_type, store)
    diff = reg.diff(name, v1, v2)
    click.echo(json.dumps(diff, indent=2, default=str))


@registry_group.command("import")
@click.argument("path", type=click.Path(exists=True))
@click.option("--db", default=REGISTRY_DB, show_default=True)
def registry_import(path: str, db: str) -> None:
    """Bulk-import registry items from a YAML/JSON file.

    Examples:
      autoagent registry import registry_export.yaml
    """
    from registry import RegistryStore
    from registry.importer import import_from_file

    store = RegistryStore(db_path=db)
    counts = import_from_file(path, store)
    click.echo("Imported:")
    for item_type, count in counts.items():
        click.echo(f"  {item_type}: {count}")


# ---------------------------------------------------------------------------
# autoagent trace ...
# ---------------------------------------------------------------------------

def _parse_window(window: str) -> float:
    """Parse a window string like '24h', '30m', '7d' into seconds."""
    unit_map = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if window and window[-1] in unit_map:
        try:
            return float(window[:-1]) * unit_map[window[-1]]
        except ValueError:
            pass
    raise click.BadParameter(f"Invalid window '{window}'. Use e.g. 24h, 30m, 7d.")


@cli.group("trace")
def trace_group() -> None:
    """Trace analysis — grading, blame maps, and graphs."""


@trace_group.command("grade")
@click.argument("trace_id")
@click.option("--db", default=TRACE_DB, show_default=True)
def trace_grade(trace_id: str, db: str) -> None:
    """Grade all spans in a trace.

    Examples:
      autoagent trace grade abc-123
    """
    from observer.trace_grading import TraceGrader
    from observer.traces import TraceStore

    store = TraceStore(db_path=db)
    grader = TraceGrader()
    grades = grader.grade_trace(trace_id, store)

    if not grades:
        click.echo(f"No spans found for trace {trace_id}")
        return

    click.echo(f"\nTrace {trace_id} — {len(grades)} grade(s):\n")
    for g in grades:
        status = click.style("PASS", fg="green") if g.passed else click.style("FAIL", fg="red")
        click.echo(f"  [{status}] {g.grader_name:25s}  score={g.score:.2f}  span={g.span_id}")
        if g.failure_reason:
            click.echo(f"         reason: {g.failure_reason}")


@trace_group.command("blame")
@click.option("--window", default="24h", show_default=True,
              help="Time window (e.g. 24h, 7d, 30m).")
@click.option("--top", "top_n", default=10, show_default=True,
              help="Number of clusters to show.")
@click.option("--db", default=TRACE_DB, show_default=True)
def trace_blame(window: str, top_n: int, db: str) -> None:
    """Build a blame map of failure clusters.

    Examples:
      autoagent trace blame --window 24h
      autoagent trace blame --window 7d --top 5
    """
    from observer.blame_map import BlameMap
    from observer.trace_grading import TraceGrader
    from observer.traces import TraceStore

    window_secs = _parse_window(window)
    store = TraceStore(db_path=db)
    grader = TraceGrader()
    bmap = BlameMap.from_store(store, grader, window_seconds=window_secs)
    clusters = bmap.get_top_clusters(top_n)

    if not clusters:
        click.echo("No failure clusters found.")
        return

    click.echo(f"\nTop {len(clusters)} blame cluster(s) (window={window}):\n")
    for i, c in enumerate(clusters, 1):
        click.echo(f"  {i}. {c.grader_name} | {c.agent_path}")
        click.echo(f"     Reason:  {c.failure_reason}")
        click.echo(f"     Count:   {c.count}/{c.total_traces}  Impact: {c.impact_score:.2%}  Trend: {c.trend}")
        if c.example_trace_ids:
            click.echo(f"     Example: {c.example_trace_ids[0]}")
        click.echo()


@trace_group.command("graph")
@click.argument("trace_id")
@click.option("--db", default=TRACE_DB, show_default=True)
def trace_graph(trace_id: str, db: str) -> None:
    """Render a trace as a dependency graph with critical-path analysis.

    Examples:
      autoagent trace graph abc-123
    """
    from observer.trace_grading import TraceGrader
    from observer.trace_graph import TraceGraph
    from observer.traces import TraceStore

    store = TraceStore(db_path=db)
    spans = store.get_spans(trace_id)
    if not spans:
        click.echo(f"No spans found for trace {trace_id}")
        return

    grader = TraceGrader()
    grades = grader.grade_trace(trace_id, store)
    graph = TraceGraph.from_spans(spans, grades)

    crit = graph.get_critical_path()
    bottlenecks = graph.get_bottlenecks()

    click.echo(f"\nTrace {trace_id} — {len(graph.nodes)} node(s), {len(graph.edges)} edge(s)")
    click.echo(f"\nCritical path ({len(crit)} node(s)):")
    for node in crit:
        click.echo(f"  {node.operation:30s}  {node.duration_ms:8.1f}ms  [{node.status}]")

    if bottlenecks:
        click.echo(f"\nBottlenecks ({len(bottlenecks)}):")
        for node in bottlenecks:
            click.echo(f"  {node.operation:30s}  {node.duration_ms:8.1f}ms  span={node.span_id}")

    click.echo("\nFull graph JSON:")
    click.echo(json.dumps(graph.to_dict(), indent=2, default=str))


# ---------------------------------------------------------------------------
# autoagent scorer ...
# ---------------------------------------------------------------------------

@cli.group("scorer")
def scorer_group() -> None:
    """NL Scorer — create eval scorers from natural language descriptions."""


@scorer_group.command("create")
@click.argument("description", required=False, default=None)
@click.option("--from-file", "from_file", type=click.Path(exists=True),
              help="Read NL description from a file.")
@click.option("--name", default=None, help="Name for the scorer (auto-generated if omitted).")
def scorer_create(description: str | None, from_file: str | None, name: str | None) -> None:
    """Create a scorer from a natural language description.

    Examples:
      autoagent scorer create "The agent should respond within 5 seconds"
      autoagent scorer create --from-file criteria.txt --name latency_check
    """
    from evals.nl_compiler import NLCompiler
    from evals.nl_scorer import NLScorer

    if from_file:
        nl_text = Path(from_file).read_text(encoding="utf-8").strip()
    elif description:
        nl_text = description
    else:
        click.echo("Error: provide a description argument or --from-file.", err=True)
        raise SystemExit(1)

    scorer = NLScorer(compiler=NLCompiler())
    spec = scorer.create(nl_text, name=name)
    click.echo(f"Created scorer: {spec.name} (v{spec.version})")
    click.echo(f"Dimensions: {len(spec.dimensions)}")
    for d in spec.dimensions:
        click.echo(f"  - {d.name} ({d.grader_type}, weight={d.weight})")
    click.echo(f"\nYAML:\n{spec.to_yaml()}")


@scorer_group.command("list")
def scorer_list() -> None:
    """List all scorer specs in memory.

    Examples:
      autoagent scorer list
    """
    from evals.nl_compiler import NLCompiler
    from evals.nl_scorer import NLScorer

    scorer = NLScorer(compiler=NLCompiler())
    specs = scorer.list()
    if not specs:
        click.echo("No scorers found. Create one with: autoagent scorer create")
        return
    click.echo(f"\n{len(specs)} scorer(s):\n")
    for s in specs:
        click.echo(f"  {s.name:30s}  v{s.version}  dims={len(s.dimensions)}")


@scorer_group.command("show")
@click.argument("name")
def scorer_show(name: str) -> None:
    """Show a scorer spec in detail.

    Examples:
      autoagent scorer show latency_check
    """
    from evals.nl_compiler import NLCompiler
    from evals.nl_scorer import NLScorer

    scorer = NLScorer(compiler=NLCompiler())
    spec = scorer.get(name)
    if spec is None:
        click.echo(f"Scorer '{name}' not found.")
        raise SystemExit(1)
    click.echo(json.dumps(spec.to_dict(), indent=2, default=str))


@scorer_group.command("refine")
@click.argument("name")
@click.argument("additional_nl")
def scorer_refine(name: str, additional_nl: str) -> None:
    """Refine an existing scorer with additional criteria.

    Examples:
      autoagent scorer refine latency_check "Also check for empathy"
    """
    from evals.nl_compiler import NLCompiler
    from evals.nl_scorer import NLScorer

    scorer = NLScorer(compiler=NLCompiler())
    try:
        spec = scorer.refine(name, additional_nl)
    except KeyError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)
    click.echo(f"Refined scorer: {spec.name} (v{spec.version})")
    click.echo(f"Dimensions: {len(spec.dimensions)}")
    for d in spec.dimensions:
        click.echo(f"  - {d.name} ({d.grader_type}, weight={d.weight})")


@scorer_group.command("test")
@click.argument("name")
@click.option("--trace", "trace_id", required=True, help="Trace ID to test against.")
@click.option("--db", default=TRACE_DB, show_default=True)
def scorer_test(name: str, trace_id: str, db: str) -> None:
    """Test a scorer against a trace.

    Examples:
      autoagent scorer test latency_check --trace abc-123
    """
    from evals.nl_compiler import NLCompiler
    from evals.nl_scorer import NLScorer
    from evals.scorer import EvalResult
    from observer.traces import TraceStore

    scorer = NLScorer(compiler=NLCompiler())
    spec = scorer.get(name)
    if spec is None:
        click.echo(f"Scorer '{name}' not found.", err=True)
        raise SystemExit(1)

    store = TraceStore(db_path=db)
    events = store.get_trace(trace_id)
    if not events:
        click.echo(f"Trace '{trace_id}' not found.", err=True)
        raise SystemExit(1)

    # Build a minimal EvalResult from trace events
    eval_result = EvalResult(
        run_id=trace_id,
        scores={},
        conversation=[
            {"role": "tool" if e.tool_name else "agent", "content": e.tool_output or e.error_message or ""}
            for e in events
        ],
        latency_ms=sum(e.latency_ms for e in events),
        outcome="success" if not any(e.error_message for e in events) else "error",
    )

    result = scorer.test(name, eval_result)
    status = click.style("PASS", fg="green") if result["passed"] else click.style("FAIL", fg="red")
    click.echo(f"\n{status}  aggregate_score={result['aggregate_score']:.4f}\n")
    for dim_name, dim_data in result["dimensions"].items():
        d_status = "PASS" if dim_data["passed"] else "FAIL"
        click.echo(f"  {dim_name:30s}  {d_status}  score={dim_data['score']:.4f}  weight={dim_data['weight']}")


if __name__ == "__main__":
    cli()
