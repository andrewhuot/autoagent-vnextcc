"""CLI entry point for AutoAgent VNext."""

from __future__ import annotations

import time
from pathlib import Path

import click
import yaml

from agent.config.loader import load_config
from deployer import Deployer
from evals import EvalRunner
from logger import ConversationStore
from observer import Observer
from optimizer import Optimizer
from optimizer.memory import OptimizationMemory


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


@click.group()
def cli() -> None:
    """AutoAgent VNext — self-healing, self-optimizing ADK agent."""


@cli.group("run")
def run_group() -> None:
    """Run one of the AutoAgent system workflows."""


@run_group.command("agent")
@click.option("--host", default="0.0.0.0", show_default=True, help="Host to bind to.")
@click.option("--port", default=8000, show_default=True, type=int, help="Port to bind to.")
def run_agent(host: str, port: int) -> None:
    """Start the ADK agent API server."""
    import uvicorn

    from agent.server import app

    click.echo(f"Starting AutoAgent server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


@run_group.command("eval")
@click.option("--config-path", default=None, help="Path to config YAML to evaluate.")
@click.option("--category", default=None, help="Run only a specific category.")
def run_eval(config_path: str | None, category: str | None) -> None:
    """Run eval suite against default or specified config."""
    config = None
    if config_path:
        config = _load_config_dict(config_path)
        click.echo(f"Evaluating config: {config_path}")
    else:
        click.echo("Evaluating with default config")

    runner = EvalRunner()
    if category:
        score = runner.run_category(category, config=config)
        _print_score(score, f"Category: {category}")
        return

    score = runner.run(config=config)
    _print_score(score, "Full eval suite")


@run_group.command("observe")
@click.option("--db", default="conversations.db", show_default=True, help="Conversation store DB path.")
@click.option("--window", default=100, show_default=True, type=int, help="Number of recent conversations to analyze.")
def run_observe(db: str, window: int) -> None:
    """Run observer once and report health metrics."""
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

    if report.anomalies:
        click.echo("\nAnomalies detected:")
        for anomaly in report.anomalies:
            click.echo(f"  ! {anomaly}")

    if report.failure_buckets:
        click.echo("\nFailure buckets:")
        for bucket, count in sorted(report.failure_buckets.items(), key=lambda item: -item[1]):
            if count > 0:
                click.echo(f"  {bucket}: {count}")

    if report.needs_optimization:
        click.echo(f"\nOptimization recommended: {report.reason}")
    else:
        click.echo("\nSystem healthy; no optimization needed.")


@run_group.command("optimize")
@click.option("--db", default="conversations.db", show_default=True, help="Conversation store DB path.")
@click.option("--configs-dir", default="configs", show_default=True, help="Configs directory.")
@click.option("--memory-db", default="optimizer_memory.db", show_default=True, help="Optimizer memory DB path.")
def run_optimize(db: str, configs_dir: str, memory_db: str) -> None:
    """Run one observe->optimize->deploy cycle."""
    store = ConversationStore(db_path=db)
    observer = Observer(store)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    memory = OptimizationMemory(db_path=memory_db)
    eval_runner = EvalRunner()
    optimizer = Optimizer(eval_runner=eval_runner, memory=memory)

    report = observer.observe()
    click.echo(f"Observed success={report.metrics.success_rate:.2%} error={report.metrics.error_rate:.2%}")
    if not report.needs_optimization:
        click.echo("System healthy; skipping optimization.")
        return

    current_config = _ensure_active_config(deployer)
    failure_samples = _build_failure_samples(store)
    new_config, status = optimizer.optimize(
        report,
        current_config,
        failure_samples=failure_samples,
    )
    click.echo(f"Optimizer result: {status}")

    if new_config is None:
        return

    score = eval_runner.run(config=new_config)
    deploy_result = deployer.deploy(new_config, _score_to_dict(score))
    click.echo(f"Deploy result: {deploy_result}")


@run_group.command("loop")
@click.option("--cycles", default=5, show_default=True, type=int, help="Number of optimization cycles.")
@click.option("--db", default="conversations.db", show_default=True, help="Conversation store DB path.")
@click.option("--configs-dir", default="configs", show_default=True, help="Configs directory.")
@click.option("--memory-db", default="optimizer_memory.db", show_default=True, help="Optimizer memory DB path.")
@click.option("--delay", default=1.0, show_default=True, type=float, help="Seconds between cycles.")
def run_loop(cycles: int, db: str, configs_dir: str, memory_db: str, delay: float) -> None:
    """Run the continuous self-healing loop for a fixed number of cycles."""
    store = ConversationStore(db_path=db)
    observer = Observer(store)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    memory = OptimizationMemory(db_path=memory_db)
    eval_runner = EvalRunner()
    optimizer = Optimizer(eval_runner=eval_runner, memory=memory)

    click.echo(f"Starting optimization loop ({cycles} cycles)")
    for cycle in range(1, cycles + 1):
        click.echo(f"\n{'=' * 50}")
        click.echo(f"Cycle {cycle}/{cycles}")
        click.echo(f"{'=' * 50}")

        report = observer.observe()
        click.echo(
            "  Health: "
            f"success={report.metrics.success_rate:.2%}, "
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
                score = eval_runner.run(config=new_config)
                deploy_result = deployer.deploy(new_config, _score_to_dict(score))
                click.echo(f"  Deploy: {deploy_result}")
        else:
            click.echo("  Healthy; skipping optimization.")

        canary_result = deployer.check_and_act()
        click.echo(f"  Canary: {canary_result}")

        if cycle < cycles:
            time.sleep(delay)

    click.echo(f"\nLoop complete. {cycles} cycles executed.")


@run_group.command("status")
@click.option("--db", default="conversations.db", show_default=True, help="Conversation store DB path.")
@click.option("--configs-dir", default="configs", show_default=True, help="Configs directory.")
@click.option("--memory-db", default="optimizer_memory.db", show_default=True, help="Optimizer memory DB path.")
def run_status(db: str, configs_dir: str, memory_db: str) -> None:
    """Show system health, config versions, and recent optimizer attempts."""
    store = ConversationStore(db_path=db)
    total_conversations = store.count()
    click.echo(f"\nConversations: {total_conversations} total")

    if total_conversations > 0:
        report = Observer(store).observe()
        metrics = report.metrics
        click.echo(f"  Success rate:  {metrics.success_rate:.2%}")
        click.echo(f"  Error rate:    {metrics.error_rate:.2%}")
        click.echo(f"  Avg latency:   {metrics.avg_latency_ms:.1f}ms")

    deployer = Deployer(configs_dir=configs_dir, store=store)
    deploy_status = deployer.status()
    click.echo(f"\nConfig versions: {deploy_status['total_versions']}")

    active = deploy_status["active_version"]
    canary = deploy_status["canary_version"]
    click.echo(f"  Active:  v{active:03d}" if active else "  Active:  none")
    click.echo(f"  Canary:  v{canary:03d}" if canary else "  Canary:  none")

    if deploy_status["history"]:
        click.echo("\nRecent versions:")
        for version in deploy_status["history"]:
            click.echo(
                f"  v{version['version']:03d} [{version['status']}] "
                f"hash={version['config_hash']}"
            )

    memory = OptimizationMemory(db_path=memory_db)
    recent_attempts = memory.recent(limit=5)
    if recent_attempts:
        click.echo("\nRecent optimization attempts:")
        for attempt in recent_attempts:
            click.echo(f"  [{attempt.status}] {attempt.change_description}")
            click.echo(f"    Score: {attempt.score_before:.4f} -> {attempt.score_after:.4f}")


if __name__ == "__main__":
    cli()
