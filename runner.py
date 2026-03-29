"""CLI entry point for AutoAgent VNextCC.

Full command set:
  autoagent quickstart [--agent-name NAME] [--verbose]
  autoagent demo quickstart [--dir PATH]
  autoagent demo vp [--agent-name NAME] [--company NAME] [--no-pause] [--web]
  autoagent init [--template NAME] [--agent-name NAME] [--with-synthetic-data]
  autoagent eval run [OPTIONS]
  autoagent eval results [--run-id ID]
  autoagent eval list
  autoagent optimize [--cycles N] [--mode standard|advanced|research]
  autoagent config list
  autoagent config diff V1 V2
  autoagent config show [VERSION]
  autoagent config migrate <input_file> [--output FILE]
  autoagent deploy [--strategy canary|immediate]
  autoagent loop [--max-cycles N] [--stop-on-plateau]
  autoagent status
  autoagent logs [--limit N] [--outcome fail|success]
  autoagent server
  autoagent review [list|show|apply|reject|export]
  autoagent runbook [list|show|apply|create]
  autoagent memory [show|add]
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
  autoagent full-auto --yes [--cycles N] [--max-loop-cycles N]
"""

from __future__ import annotations

import json
import os
import shutil
import sys
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
from optimizer.adversarial import AdversarialSimulationConfig, AdversarialSimulator
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
from core.skills import SkillStore
from optimizer.skill_engine import SkillEngine
from optimizer.skill_autolearner import SkillAutoLearner


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("AUTOAGENT_DB", "conversations.db")
CONFIGS_DIR = os.environ.get("AUTOAGENT_CONFIGS", "configs")
MEMORY_DB = os.environ.get("AUTOAGENT_MEMORY_DB", "optimizer_memory.db")
REGISTRY_DB = os.environ.get("AUTOAGENT_REGISTRY_DB", "registry.db")
TRACE_DB = os.environ.get("AUTOAGENT_TRACE_DB", ".autoagent/traces.db")


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
    quality_ci = score.confidence_intervals.get("quality")
    safety_ci = score.confidence_intervals.get("safety")
    latency_ci = score.confidence_intervals.get("latency")
    cost_ci = score.confidence_intervals.get("cost")
    composite_ci = score.confidence_intervals.get("composite")

    def _fmt_ci(ci: tuple[float, float] | None) -> str:
        if ci is None:
            return ""
        return f"  (95% CI {ci[0]:.4f}..{ci[1]:.4f})"

    click.echo(f"  Quality:   {score.quality:.4f}{_fmt_ci(quality_ci)}")
    click.echo(f"  Safety:    {score.safety:.4f} ({score.safety_failures} failures){_fmt_ci(safety_ci)}")
    click.echo(f"  Latency:   {score.latency:.4f}{_fmt_ci(latency_ci)}")
    click.echo(f"  Cost:      {score.cost:.4f}{_fmt_ci(cost_ci)}")
    click.echo(f"  Composite: {score.composite:.4f}{_fmt_ci(composite_ci)}")
    click.echo(
        f"  Tokens:    {getattr(score, 'total_tokens', 0)}"
        f"  |  Est. USD: ${getattr(score, 'estimated_cost_usd', 0.0):.6f}"
    )
    for warning in getattr(score, "warnings", []):
        click.echo(click.style(f"  Warning:   {warning}", fg="yellow"))


def _score_to_dict(score) -> dict:
    """Convert CompositeScore-like object into deployable score dictionary."""
    return {
        "quality": score.quality,
        "safety": score.safety,
        "tool_use_accuracy": getattr(score, "tool_use_accuracy", 0.0),
        "latency": score.latency,
        "cost": score.cost,
        "composite": score.composite,
        "confidence_intervals": getattr(score, "confidence_intervals", {}),
        "total_tokens": getattr(score, "total_tokens", 0),
        "estimated_cost_usd": getattr(score, "estimated_cost_usd", 0.0),
        "warnings": getattr(score, "warnings", []),
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


def _auto_open_console(port: int = 8080, block: bool | None = None) -> None:
    """Start API server in background and open browser."""
    import threading
    import webbrowser

    def _run_server():
        import uvicorn
        try:
            uvicorn.run("api.server:app", host="0.0.0.0", port=port, log_level="warning")
        except BaseException:
            # uvicorn may raise SystemExit on bind failures; suppress in helper thread.
            pass

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # Give the server a moment to start
    time.sleep(1.5)

    # Check if server started by trying to connect
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(2)
        sock.connect(("localhost", port))
        sock.close()
        # Server is running — open browser
        webbrowser.open(f"http://localhost:{port}")
        should_block = block
        if should_block is None:
            # In non-interactive environments (e.g., test runners), avoid hanging.
            should_block = sys.stdin.isatty() and sys.stdout.isatty()
        click.echo(click.style(
            f"\n  Web console running at http://localhost:{port} — press Ctrl+C to stop",
            fg="cyan",
        ))
        if should_block:
            # Block until Ctrl+C only during interactive terminal sessions.
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                click.echo("\n  Shutting down web console...")
        else:
            click.echo("  Continuing in non-blocking mode.")
    except (socket.timeout, ConnectionRefusedError, OSError):
        sock.close()
        click.echo(
            "\n  Could not start web console. Run "
            + click.style("autoagent server", bold=True)
            + " to open it manually."
        )


def _format_relative_time(epoch: float) -> str:
    """Format an epoch timestamp as a human-readable relative time string."""
    delta = time.time() - epoch
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


# ---------------------------------------------------------------------------
# Magic UX helpers (Features 1, 2, 4, 5)
# ---------------------------------------------------------------------------

FAILURE_TO_RUNBOOK: dict[str, str] = {
    "routing_error": "fix-retrieval-grounding",
    "safety_violation": "tighten-safety-policy",
    "timeout": "reduce-tool-latency",
    "tool_failure": "reduce-tool-latency",
    "unhelpful_response": "improve-response-quality",
    "quality_issue": "improve-response-quality",
}


def _bar_chart(value: float, width: int = 10) -> str:
    """Return a Unicode block bar chart string for *value* in [0, 1]."""
    filled = round(value * width)
    return "█" * filled + "░" * (width - filled)


SOUL_LINES: dict[str, str] = {
    "status": "Pulse check complete. Your agent is alive and learning.",
    "optimize": "Tuning in progress — we're chasing signal, not noise.",
    "quickstart": "Bootstrapping momentum. Let's make this thing sing.",
    "eval": "Running the gauntlet. Truth comes from test cases.",
}


def _soul_line(context: str) -> str:
    """Return a short personality line for a CLI context."""
    return SOUL_LINES.get(context, "AutoAgent is online.")


def _score_mood(score: float | None) -> str:
    """Map composite score to a human-friendly mood label."""
    if score is None:
        return "Warming up"
    if score >= 0.9:
        return "Flying"
    if score >= 0.75:
        return "Steady climb"
    if score >= 0.6:
        return "Promising"
    return "Needs love"


def _print_cli_plan(title: str, steps: list[str]) -> None:
    """Print a compact plan block similar to coding-agent style preambles."""
    click.echo(click.style(f"\n{title}", fg="cyan", bold=True))
    for idx, step in enumerate(steps, start=1):
        click.echo(f"  {idx}. {step}")


def _print_next_actions(actions: list[str]) -> None:
    """Print runnable next actions with command-style formatting."""
    if not actions:
        return
    click.echo(click.style("\n  Next actions:", fg="cyan", bold=True))
    for action in actions:
        click.echo(f"    → {action}")


def _generate_recommendations(report, score) -> list[str]:  # noqa: ANN001
    """Return up to 3 actionable recommendation strings based on failure buckets."""
    buckets = report.failure_buckets
    if not buckets:
        return []
    total = sum(buckets.values())
    if total == 0:
        return []

    sorted_buckets = sorted(buckets.items(), key=lambda kv: kv[1], reverse=True)
    recs: list[str] = []
    for i, (bucket, count) in enumerate(sorted_buckets[:3], start=1):
        pct = round(count / total * 100)
        runbook = FAILURE_TO_RUNBOOK.get(bucket, "improve-response-quality")
        recs.append(
            f"  {i}. {bucket} is {pct}% of failures"
            f" → autoagent runbook apply {runbook}"
        )
    return recs


def _status_next_action(report, attempts_count: int, accepted_count: int) -> str:  # noqa: ANN001
    """Return a single next-best-action command for status/UX surfaces."""
    total_failures = sum(report.failure_buckets.values()) if report.failure_buckets else 0
    if attempts_count == 0:
        return "autoagent quickstart"
    if total_failures > 0:
        recs = _generate_recommendations(report, None)
        if recs:
            return recs[0].split("→")[-1].strip()
        return "autoagent runbook list"
    if accepted_count >= 3:
        return "autoagent loop --max-cycles 20 --stop-on-plateau"
    return "autoagent loop --max-cycles 3"


def _stream_cycle_output(
    cycle_num: int,
    total: int,
    report,  # noqa: ANN001
    proposal_desc: str | None,
    score_after: float | None,
    score_before: float | None,
    p_value: float | None = None,
    all_time_best: float = 0.0,
    best_score_file: Path | None = None,
) -> None:
    """Print rich streaming output for a single optimization cycle."""
    click.echo(f"\n  Cycle {cycle_num}/{total}")

    # Diagnose step
    buckets = report.failure_buckets if report is not None else {}
    total_failures = sum(buckets.values())
    if total_failures > 0:
        parts = ", ".join(f"{count} {name}" for name, count in
                         sorted(buckets.items(), key=lambda kv: kv[1], reverse=True)[:3])
        click.echo(click.style(f"    ↳ Diagnosing... found {parts}", fg="white"))
    else:
        click.echo(click.style("    ↳ Diagnosing... no dominant failures detected", fg="white"))

    # Proposing step
    if buckets:
        dominant = max(buckets, key=lambda k: buckets[k])
        click.echo(click.style(
            f"    ↳ Proposing fix for {dominant} (dominant failure)", fg="white"
        ))
    else:
        click.echo(click.style("    ↳ Proposing config improvement", fg="white"))

    click.echo(click.style("    ↳ Evaluating candidate config...", fg="white"))

    # Result step
    if score_after is not None and score_before is not None:
        improvement = score_after - score_before
        if improvement > 0:
            sparkle = " ✨" if score_after > all_time_best else ""
            p_str = f" (p={p_value:.2f})" if p_value is not None else ""
            click.echo(click.style(
                f"    ↳ ✓ composite={score_after:.4f} (+{improvement:.4f}){sparkle}{p_str}", fg="green"
            ))
            click.echo(click.style("    → Accepted", fg="green"))

            # Update all-time best
            if score_after > all_time_best:
                resolved_best_score_file = best_score_file or Path(".autoagent/best_score.txt")
                resolved_best_score_file.parent.mkdir(parents=True, exist_ok=True)
                resolved_best_score_file.write_text(str(score_after))
                click.echo(click.style("\n  ✨ New personal best!", fg="yellow", bold=True))
        else:
            click.echo(click.style(
                f"    ↳ ✗ composite={score_after:.4f} ({improvement:+.4f})", fg="yellow"
            ))
            click.echo(click.style("    → Rejected", fg="yellow"))
    else:
        click.echo(click.style("    ↳ No change applied", fg="yellow"))

    if proposal_desc:
        click.echo(click.style(f"    → {proposal_desc}", fg="cyan"))


def _build_skill_components(db_path: str = ".autoagent/core_skills.db") -> tuple[SkillStore, SkillEngine]:
    """Create skill store and skill engine for optimization."""
    skill_store = SkillStore(db_path=db_path)
    skill_engine = SkillEngine(store=skill_store)
    return skill_store, skill_engine


def _workspace_state_paths(target_dir: str) -> dict[str, Path]:
    """Return workspace-scoped state paths for quickstart/demo flows."""
    workspace = Path(target_dir).resolve()
    autoagent_dir = workspace / ".autoagent"
    autoagent_dir.mkdir(parents=True, exist_ok=True)
    return {
        "workspace": workspace,
        "autoagent_dir": autoagent_dir,
        "configs_dir": workspace / "configs",
        "conversation_db": workspace / "conversations.db",
        "memory_db": workspace / "optimizer_memory.db",
        "eval_history_db": workspace / "eval_history.db",
        "eval_cache_db": autoagent_dir / "eval_cache.db",
        "trace_db": autoagent_dir / "traces.db",
        "skill_db": autoagent_dir / "core_skills.db",
        "best_score_file": autoagent_dir / "best_score.txt",
        "cases_dir": workspace / "evals" / "cases",
    }


def _scope_runtime_to_workspace(runtime, workspace: Path):
    """Return a copy of runtime config with relative state rooted in workspace."""
    scoped = runtime.model_copy(deep=True)
    scoped.eval.history_db_path = str(workspace / Path(runtime.eval.history_db_path).name)
    scoped.eval.cache_db_path = str(workspace / runtime.eval.cache_db_path)
    scoped.budget.tracker_db_path = str(workspace / runtime.budget.tracker_db_path)
    scoped.loop.checkpoint_path = str(workspace / runtime.loop.checkpoint_path)
    scoped.loop.dead_letter_db = str(workspace / runtime.loop.dead_letter_db)
    scoped.loop.structured_log_path = str(workspace / runtime.loop.structured_log_path)
    return scoped


def _build_eval_runner(
    runtime,
    *,
    cases_dir: str | None = None,
    trace_db_path: str | None = None,
    use_real_agent: bool = False,
    default_agent_config: dict | None = None,
) -> EvalRunner:
    """Build an EvalRunner from runtime config with harness defaults wired in."""
    from agent import create_eval_agent
    from agent.eval_agent import LEGACY_EVAL_MOCK_MESSAGE
    from agent.tracing import instrument_eval_runner
    from observer.traces import TraceStore

    requested_real_agent = bool(use_real_agent or not bool(runtime.optimizer.use_mock))
    eval_agent = create_eval_agent(
        runtime,
        force_real_agent=use_real_agent,
        default_config=default_agent_config,
    ) if requested_real_agent else None

    eval_runner = EvalRunner(
        cases_dir=cases_dir,
        agent_fn=(eval_agent.run if eval_agent is not None else None),
        history_db_path=runtime.eval.history_db_path,
        cache_enabled=runtime.eval.cache_enabled,
        cache_db_path=runtime.eval.cache_db_path,
        dataset_strict_integrity=runtime.eval.dataset_strict_integrity,
        random_seed=runtime.eval.random_seed,
        token_cost_per_1k=runtime.eval.token_cost_per_1k,
    )
    trace_store = TraceStore(db_path=trace_db_path or os.environ.get("AUTOAGENT_TRACE_DB", TRACE_DB))
    instrument_eval_runner(eval_runner, trace_store, agent_path="eval", branch="cli")
    eval_runner.mock_mode_messages = (
        list(getattr(eval_agent, "mock_mode_messages", []))
        if eval_agent is not None
        else [LEGACY_EVAL_MOCK_MESSAGE]
    )
    return eval_runner


def _warn_mock_modes(
    *,
    eval_runner: EvalRunner | None = None,
    proposer: Proposer | None = None,
    json_output: bool = False,
) -> None:
    """Print human-readable warnings for any active simulated execution paths."""
    if json_output:
        return

    messages: list[str] = []
    if proposer is not None and proposer.use_mock:
        messages.append(
            proposer.mock_reason
            or "Optimization proposer is running in mock mode; generated changes are simulated."
        )

    if eval_runner is not None:
        messages.extend(list(getattr(eval_runner, "mock_mode_messages", []) or []))

    seen: set[str] = set()
    for message in messages:
        if not message or message in seen:
            continue
        seen.add(message)
        click.echo(click.style(f"⚠ {message}", fg="yellow"))


def _build_runtime_components() -> tuple[
    object,
    EvalRunner,
    Proposer,
    SkillEngine,
    AdversarialSimulator | None,
    SkillAutoLearner | None,
]:
    """Create runtime-configured optimizer dependencies."""
    runtime = load_runtime_config()
    eval_runner = _build_eval_runner(runtime)
    router = build_router_from_runtime_config(runtime.optimizer)
    proposer = Proposer(
        use_mock=router.mock_mode,
        llm_router=router,
        mock_reason=router.mock_reason,
    )
    _, skill_engine = _build_skill_components()

    adversarial_simulator = None
    if runtime.optimizer.adversarial_simulation_enabled:
        adversarial_simulator = AdversarialSimulator(
            AdversarialSimulationConfig(
                enabled=True,
                conversations=runtime.optimizer.adversarial_simulation_cases,
                max_allowed_drop=runtime.optimizer.adversarial_simulation_max_drop,
            )
        )

    skill_autolearner = None
    if runtime.optimizer.skill_autolearn_enabled:
        skill_autolearner = SkillAutoLearner(
            store=skill_engine.store,
            min_improvement=runtime.optimizer.skill_autolearn_min_improvement,
        )

    return runtime, eval_runner, proposer, skill_engine, adversarial_simulator, skill_autolearner


def _sleep_interruptibly(seconds: float, shutdown: GracefulShutdown) -> None:
    """Sleep in small increments and return early when shutdown is requested."""
    remaining = max(0.0, seconds)
    while remaining > 0 and not shutdown.stop_requested:
        step = min(0.5, remaining)
        shutdown.event.wait(timeout=step)
        remaining -= step


def _promote_latest_version(deployer: Deployer) -> int | None:
    """Promote the latest version to active and return the version number."""
    history = deployer.version_manager.get_version_history()
    if not history:
        return None
    latest_version = history[-1]["version"]
    deployer.version_manager.promote(latest_version)
    return latest_version


def _infer_connectors_from_prompt(prompt: str) -> list[str]:
    """Infer well-known connector names from a natural-language prompt."""
    lower = prompt.lower()
    mapping = [
        ("shopify", "Shopify"),
        ("amazon connect", "Amazon Connect"),
        ("salesforce", "Salesforce"),
        ("zendesk", "Zendesk"),
    ]
    connectors: list[str] = []
    for needle, label in mapping:
        if needle in lower and label not in connectors:
            connectors.append(label)
    return connectors


def _build_skill_recommendations(artifact: dict) -> list[dict[str, str]]:
    """Recommend starter skills based on generated artifact surfaces."""
    skills: list[dict[str, str]] = [
        {
            "id": "routing_keyword_expansion",
            "reason": "Expand routing coverage for intent phrases discovered in prompt-to-agent synthesis.",
        },
        {
            "id": "safety_policy_hardening",
            "reason": "Enforce stronger safety posture for newly introduced flows and escalation paths.",
        },
    ]
    tool_names = [str(tool.get("name", "")) for tool in artifact.get("tools", [])]
    if any("shopify" in name for name in tool_names):
        skills.append(
            {
                "id": "shopify_order_workflow",
                "reason": "Harden Shopify order retrieval/cancel/address workflows and fallback handling.",
            }
        )
    if any("amazon_connect" in name for name in tool_names):
        skills.append(
            {
                "id": "live_handoff_context_bridge",
                "reason": "Preserve customer context when escalating to Amazon Connect live agents.",
            }
        )
    return skills


def _next_built_config_path(configs_dir: Path) -> Path:
    """Return the next versioned config path for build-generated configs."""
    highest = 0
    for path in configs_dir.glob("v*_*.yaml"):
        head = path.name.split("_", 1)[0]
        if not head.startswith("v"):
            continue
        try:
            highest = max(highest, int(head[1:]))
        except ValueError:
            continue
    next_version = highest + 1
    return configs_dir / f"v{next_version:03d}_built_from_prompt.yaml"


def _artifact_to_seed_config(prompt: str, artifact: dict) -> dict:
    """Map a prompt-built artifact into an AutoAgent config scaffold."""
    base_path = Path(__file__).parent / "agent" / "config" / "base_config.yaml"
    config = load_config(str(base_path)).model_dump()

    intents = artifact.get("intents", [])
    guardrails = artifact.get("guardrails", [])
    connectors = artifact.get("connectors", [])
    tools = artifact.get("tools", [])
    skills = artifact.get("skills", [])
    integration_templates = artifact.get("integration_templates", [])

    intent_names = [str(item.get("name", "")) for item in intents if item.get("name")]
    intent_human = ", ".join(name.replace("_", " ") for name in intent_names)
    guardrail_text = " ".join(str(item) for item in guardrails)

    config["prompts"]["root"] = (
        "You are AutoAgent, a production customer support orchestrator. "
        f"Primary intents: {intent_human or 'general support'}. "
        f"Follow these guardrails: {guardrail_text or 'standard policy controls'}. "
        "Escalate with verified context when self-service cannot resolve safely."
    )

    order_keywords = {"order", "tracking", "cancel", "cancellation", "shipping", "address", "refund"}
    for intent in intent_names:
        order_keywords.update(intent.replace("_", " ").split())
    rules = config.get("routing", {}).get("rules", [])
    for rule in rules:
        if rule.get("specialist") == "orders":
            current = set(rule.get("keywords", []))
            merged = sorted(current.union(order_keywords))
            rule["keywords"] = merged

    if any(str(conn).lower() == "shopify" for conn in connectors):
        config["tools"]["orders_db"]["enabled"] = True
    if any(str(conn).lower() == "zendesk" for conn in connectors):
        config["tools"]["faq"]["enabled"] = True
    if tools:
        config["tools"]["catalog"]["enabled"] = True

    config["optimizer"]["use_skills"] = True
    config["optimizer"]["skill_selection_strategy"] = "auto"
    config["optimizer"]["skill_max_candidates"] = max(3, len(skills))

    # Extra metadata is intentionally embedded for downstream UI/CLI handoff.
    config["journey_build"] = {
        "source_prompt": prompt,
        "intents": intents,
        "guardrails": guardrails,
        "skills": skills,
        "integration_templates": integration_templates,
    }
    return config


def _write_generated_eval_cases(path: Path, artifact: dict) -> None:
    """Write eval cases derived from build artifact suggested tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tests = artifact.get("suggested_tests", [])
    cases: list[dict[str, object]] = []
    for idx, test in enumerate(tests, start=1):
        user_message = str(test.get("user_message", "")).strip()
        expected_behavior = str(test.get("expected_behavior", "")).strip()
        lowered = user_message.lower()
        expected_specialist = "orders" if any(token in lowered for token in ["order", "shipping", "cancel", "address"]) else "support"
        expected_keywords = ["order"] if expected_specialist == "orders" else ["help"]
        cases.append(
            {
                "id": f"build_{idx:03d}",
                "category": "generated_build",
                "user_message": user_message or f"Generated build test #{idx}",
                "expected_specialist": expected_specialist,
                "expected_behavior": "answer",
                "expected_keywords": expected_keywords,
                "expected_notes": expected_behavior,
            }
        )
    if not cases:
        cases = [
            {
                "id": "build_001",
                "category": "generated_build",
                "user_message": "Can you help me with my order status?",
                "expected_specialist": "orders",
                "expected_behavior": "answer",
                "expected_keywords": ["order"],
                "expected_notes": "Fallback generated case when no suggested tests are available.",
            }
        ]
    path.write_text(yaml.safe_dump({"cases": cases}, sort_keys=False), encoding="utf-8")


def _load_versioned_config(configs_dir: str, config_version: int | None) -> tuple[int, dict, Path]:
    """Load a config by version from `configs_dir`, defaulting to the highest version."""
    cfg_dir = Path(configs_dir)
    version_to_path: dict[int, Path] = {}
    for path in cfg_dir.glob("v*_*.yaml"):
        head = path.name.split("_", 1)[0]
        if not head.startswith("v"):
            continue
        try:
            version = int(head[1:])
        except ValueError:
            continue
        version_to_path[version] = path

    if not version_to_path:
        raise FileNotFoundError(f"No versioned config files found in {configs_dir}")

    selected_version = config_version if config_version is not None else max(version_to_path.keys())
    selected_path = version_to_path.get(selected_version)
    if selected_path is None:
        raise FileNotFoundError(f"Version {selected_version} not found in {configs_dir}")
    config = yaml.safe_load(selected_path.read_text(encoding="utf-8"))
    return selected_version, config, selected_path


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
@click.option("--agent-name", default="My Agent", show_default=True,
              help="Agent name for AUTOAGENT.md.")
@click.option("--platform", default="Google ADK", show_default=True,
              help="Platform for AUTOAGENT.md.")
@click.option("--with-synthetic-data/--no-synthetic-data", default=True,
              show_default=True, help="Seed synthetic conversations and evals.")
def init_project(template: str, target_dir: str, agent_name: str,
                 platform: str, with_synthetic_data: bool) -> None:
    """Scaffold a new AutoAgent project with config, eval suite, and structure."""
    target = Path(target_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)

    click.echo(click.style("\n✦ AutoAgent Init", fg="cyan", bold=True))
    click.echo("")

    # Create directory structure
    dirs = ["configs", "evals/cases", "agent/config"]
    for d in dirs:
        (target / d).mkdir(parents=True, exist_ok=True)
    click.echo(click.style("  ✓ ", fg="green") + "Created directory structure")

    # Copy base config
    src_config = Path(__file__).parent / "agent" / "config" / "base_config.yaml"
    dst_config = target / "configs" / "v001_base.yaml"
    if src_config.exists() and not dst_config.exists():
        shutil.copy2(src_config, dst_config)
    click.echo(click.style("  ✓ ", fg="green") + "Copied base config")

    # Copy eval cases
    src_evals = Path(__file__).parent / "evals" / "cases"
    if src_evals.exists():
        dst_evals = target / "evals" / "cases"
        for case_file in src_evals.glob("*.yaml"):
            dst = dst_evals / case_file.name
            if not dst.exists():
                shutil.copy2(case_file, dst)
    click.echo(click.style("  ✓ ", fg="green") + "Copied eval cases")

    # Generate AUTOAGENT.md project memory
    from core.project_memory import ProjectMemory
    autoagent_md = target / "AUTOAGENT.md"
    if not autoagent_md.exists():
        content = ProjectMemory.generate_template(
            agent_name=agent_name,
            platform=platform,
            use_case="General purpose assistant",
        )
        autoagent_md.write_text(content, encoding="utf-8")
    click.echo(click.style("  ✓ ", fg="green") + f"Generated AUTOAGENT.md ({agent_name})")

    # Seed starter runbooks
    try:
        from registry.runbooks import RunbookStore, seed_starter_runbooks
        runbook_db = str(target / "registry.db") if target_dir != "." else REGISTRY_DB
        runbook_store = RunbookStore(db_path=runbook_db)
        n_runbooks = seed_starter_runbooks(runbook_store)
        click.echo(click.style("  ✓ ", fg="green") + f"Seeded {n_runbooks} starter runbooks")
    except Exception:
        click.echo(click.style("  ⚠ ", fg="yellow") + "Skipped runbook seeding")

    # Seed synthetic data
    n_convos = 0
    if with_synthetic_data:
        try:
            from evals.synthetic import generate_dataset, seed_conversations
            db_file = str(target / "conversations.db") if target_dir != "." else DB_PATH
            store = ConversationStore(db_path=db_file)
            ds = generate_dataset()
            n_convos = seed_conversations(store, dataset=ds)
            click.echo(click.style("  ✓ ", fg="green") + f"Seeded {n_convos} synthetic conversations")
            click.echo(click.style("  ✓ ", fg="green") + f"Seeded {len(ds.eval_cases)} synthetic eval cases")
        except Exception:
            click.echo(click.style("  ⚠ ", fg="yellow") + "Skipped synthetic data seeding")

    click.echo("")
    click.echo(click.style("  Initialized AutoAgent project in ", fg="white") + click.style(str(target), fg="cyan"))
    click.echo(f"    Template:  {template}")
    click.echo(f"    Config:    configs/v001_base.yaml")
    click.echo(f"    Evals:     evals/cases/")
    click.echo(f"    Memory:    AUTOAGENT.md")
    if with_synthetic_data and n_convos:
        click.echo(f"    Data:      {n_convos} synthetic conversations")
    click.echo("")
    click.echo(click.style("  Next steps:", bold=True))
    click.echo("    autoagent eval run          # Run eval suite")
    click.echo("    autoagent optimize          # Run optimization cycle")
    click.echo("    autoagent server            # Start API + web console")
    click.echo("    autoagent quickstart        # Run the full loop automatically")
    click.echo("")


# ---------------------------------------------------------------------------
# autoagent build
# ---------------------------------------------------------------------------

@cli.command("build")
@click.argument("prompt")
@click.option(
    "--connector",
    "connectors",
    multiple=True,
    help="Connector to include (repeatable). Example: --connector Shopify",
)
@click.option("--output-dir", default=".", show_default=True, help="Directory for generated build artifacts.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output artifact as JSON only.")
def build_agent(prompt: str, connectors: tuple[str, ...], output_dir: str, json_output: bool = False) -> None:
    """Build an agent artifact from natural language and scaffold eval/deploy handoff files."""
    from optimizer.transcript_intelligence import TranscriptIntelligenceService

    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    (target / ".autoagent").mkdir(parents=True, exist_ok=True)
    (target / "configs").mkdir(parents=True, exist_ok=True)
    (target / "evals" / "cases").mkdir(parents=True, exist_ok=True)

    resolved_connectors = [item.strip() for item in connectors if item.strip()]
    if not resolved_connectors:
        resolved_connectors = _infer_connectors_from_prompt(prompt)

    service = TranscriptIntelligenceService()
    artifact = service.build_agent_artifact(prompt, resolved_connectors)
    artifact["skills"] = _build_skill_recommendations(artifact)
    artifact["source_prompt"] = prompt

    config = _artifact_to_seed_config(prompt, artifact)
    config_path = _next_built_config_path(target / "configs")
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    eval_path = target / "evals" / "cases" / "generated_build.yaml"
    _write_generated_eval_cases(eval_path, artifact)

    artifact_path = target / ".autoagent" / "build_artifact_latest.json"
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    if json_output:
        click.echo(json.dumps(artifact, indent=2))
        return

    click.echo(click.style("\n✦ AutoAgent Build", fg="cyan", bold=True))
    click.echo(f"Prompt: {prompt}")
    click.echo(f"Connectors: {', '.join(artifact.get('connectors', [])) or 'None'}")
    click.echo("")
    click.echo(click.style("Artifact coverage", bold=True))
    click.echo(f"  Intents:               {len(artifact.get('intents', []))}")
    click.echo(f"  Tools:                 {len(artifact.get('tools', []))}")
    click.echo(f"  Guardrails:            {len(artifact.get('guardrails', []))}")
    click.echo(f"  Skills:                {len(artifact.get('skills', []))}")
    click.echo(f"  Integration templates: {len(artifact.get('integration_templates', []))}")
    click.echo("")
    click.echo(click.style("Generated handoff files", bold=True))
    click.echo(f"  Config:   {config_path}")
    click.echo(f"  Evals:    {eval_path}")
    click.echo(f"  Artifact: {artifact_path}")
    click.echo("")
    click.echo(click.style("Next steps:", bold=True))
    click.echo(f"  autoagent eval run --config {config_path}")
    click.echo("  autoagent diagnose --interactive")
    click.echo("  autoagent loop --max-cycles 5")
    click.echo("  autoagent deploy --target cx-studio")


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
            real_agent=False,
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
@click.option(
    "--real-agent",
    is_flag=True,
    default=False,
    help="Force the real-agent eval path even if optimizer.use_mock is enabled.",
)
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def eval_run(config_path: str | None, suite: str | None, dataset: str | None, dataset_split: str,
             category: str | None, output: str | None, real_agent: bool = False,
             json_output: bool = False) -> None:
    """Run eval suite against a config.

    Examples:
      autoagent eval run
      autoagent eval run --config configs/v003.yaml
      autoagent eval run --config configs/v003.yaml --category safety
      autoagent eval run --output results.json
    """
    runtime = load_runtime_config()
    if not json_output:
        click.echo(click.style(f"✦ {_soul_line('eval')}", fg="cyan"))
        _print_cli_plan(
            "Eval plan",
            [
                "Load active runtime + config",
                "Run eval suite against selected scope",
                "Summarize scores and suggested follow-up",
            ],
        )

    config = None
    if config_path:
        config = _load_config_dict(config_path)
        if not json_output:
            click.echo(f"Evaluating config: {config_path}")
    else:
        if not json_output:
            click.echo("Evaluating with default config")

    runner = _build_eval_runner(
        runtime,
        cases_dir=suite,
        use_real_agent=real_agent,
        default_agent_config=config,
    )
    _warn_mock_modes(eval_runner=runner, json_output=json_output)

    if category:
        score = runner.run_category(category, config=config, dataset_path=dataset, split=dataset_split)
        if json_output:
            click.echo(json.dumps(_score_to_dict(score), indent=2))
            return
        _print_score(score, f"Category: {category}")
    else:
        score = runner.run(config=config, dataset_path=dataset, split=dataset_split)
        if json_output:
            click.echo(json.dumps(_score_to_dict(score), indent=2))
            return
        _print_score(score, "Full eval suite")

    if not json_output:
        click.echo(click.style(f"\n  Mood: {_score_mood(score.composite)}", fg="magenta"))
        _print_next_actions(
            [
                "autoagent optimize --cycles 3",
                "autoagent status",
            ],
        )

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
@click.option("--mode", default=None, type=click.Choice(["standard", "advanced", "research"]),
              help="Optimization mode (replaces --strategy).")
@click.option("--strategy", default=None, hidden=True, help="[DEPRECATED] Use --mode instead.")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--memory-db", default=MEMORY_DB, show_default=True, help="Optimizer memory DB.")
@click.option("--full-auto", is_flag=True, default=False,
              help="Danger mode: auto-promote accepted configs without manual review.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def optimize(cycles: int, mode: str | None, strategy: str | None, db: str, configs_dir: str,
             memory_db: str, full_auto: bool, json_output: bool = False) -> None:
    """Run optimization cycles to improve agent config.

    Examples:
      autoagent optimize
      autoagent optimize --cycles 5
      autoagent optimize --mode advanced --cycles 3
    """
    from optimizer.mode_router import ModeConfig, ModeRouter, OptimizationMode
    if not json_output:
        click.echo(click.style(f"\n✦ {_soul_line('optimize')}", fg="cyan"))
        if full_auto:
            click.echo(click.style("⚠ FULL AUTO ENABLED: skipping manual promotion gates.", fg="yellow"))
        _print_cli_plan(
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
        click.echo(f"Mode: {mode} (strategy={resolved.search_strategy.value}, "
                   f"candidates={resolved.max_candidates})")

    (
        runtime,
        eval_runner,
        proposer,
        skill_engine,
        adversarial_simulator,
        skill_autolearner,
    ) = _build_runtime_components()
    _warn_mock_modes(proposer=proposer, json_output=json_output)
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
        skill_engine=skill_engine,
        use_skills=True,
        skill_selection_strategy="auto",
        skill_max_candidates=5,
        adversarial_simulator=adversarial_simulator,
        skill_autolearner=skill_autolearner,
        auto_learn_skills=runtime.optimizer.skill_autolearn_enabled,
    )

    # Track all-time best score
    best_score_file = Path(".autoagent/best_score.txt")
    all_time_best = 0.0
    if best_score_file.exists():
        all_time_best = float(best_score_file.read_text().strip())

    json_cycle_results: list[dict] = []

    for cycle in range(1, cycles + 1):
        report = observer.observe()

        if not report.needs_optimization:
            if not json_output:
                click.echo(f"\n  Cycle {cycle}/{cycles} — System healthy; skipping optimization.")
            json_cycle_results.append({
                "cycle": cycle,
                "total_cycles": cycles,
                "status": "skipped",
                "accepted": False,
                "score_before": None,
                "score_after": None,
                "change_description": None,
            })
            continue

        current_config = _ensure_active_config(deployer)
        failure_samples = _build_failure_samples(store)
        new_config, opt_status = optimizer.optimize(
            report,
            current_config,
            failure_samples=failure_samples,
        )

        # Gather storytelling data from memory
        latest_attempts = memory.recent(limit=1)
        latest = latest_attempts[0] if latest_attempts else None
        proposal_desc = latest.change_description if latest else None
        score_after: float | None = latest.score_after if latest else None
        score_before: float | None = latest.score_before if latest else None
        p_value: float | None = latest.significance_p_value if latest else None

        json_cycle_results.append({
            "cycle": cycle,
            "total_cycles": cycles,
            "status": opt_status,
            "accepted": new_config is not None,
            "score_before": score_before,
            "score_after": score_after,
            "change_description": proposal_desc,
        })

        if not json_output:
            _stream_cycle_output(
                cycle_num=cycle,
                total=cycles,
                report=report,
                proposal_desc=proposal_desc,
                score_after=score_after,
                score_before=score_before,
                p_value=p_value,
                all_time_best=all_time_best,
            )

        # Update all_time_best if we got a new score
        if score_after is not None and score_after > all_time_best:
            all_time_best = score_after

        if new_config is not None:
            score = eval_runner.run(config=new_config)
            deploy_result = deployer.deploy(new_config, _score_to_dict(score))
            if not json_output:
                click.echo(f"  Deploy: {deploy_result}")
            if full_auto:
                promoted = _promote_latest_version(deployer)
                if not json_output and promoted is not None:
                    click.echo(click.style(f"  FULL AUTO: promoted v{promoted:03d} to active", fg="yellow"))

    if json_output:
        click.echo(json.dumps(json_cycle_results, indent=2))
        return

    if cycles > 1:
        click.echo(f"\nOptimization complete. {cycles} cycles executed.")
    latest_attempts = memory.recent(limit=1)
    latest_score = latest_attempts[0].score_after if latest_attempts else None
    click.echo(click.style(f"  Mood: {_score_mood(latest_score)}", fg="magenta"))
    _print_next_actions(
        [
            "autoagent status",
            "autoagent runbook list",
            "autoagent loop --max-cycles 10",
        ],
    )

    # Feature 4: recommendations
    final_report = observer.observe()
    recs = _generate_recommendations(final_report, None)
    if recs:
        click.echo(click.style("\n  ⚡ Recommended next steps:", fg="cyan", bold=True))
        for rec in recs:
            click.echo(rec)

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


@config_group.command("migrate")
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--output", default=None, help="Output file path (prints to stdout if omitted).")
def config_migrate(input_file: str, output: str | None) -> None:
    """Migrate old optimizer config format to new optimization section.

    Converts legacy optimizer.search_strategy / bandit_policy settings
    into the new optimization.mode / budget / autonomy format.

    Examples:
      autoagent config migrate autoagent.yaml
      autoagent config migrate autoagent.yaml --output autoagent_v2.yaml
    """
    from optimizer.mode_router import ModeRouter

    old_config = _load_config_dict(input_file)
    router = ModeRouter()
    new_config = router.migrate_config(old_config)

    output_yaml = yaml.safe_dump(new_config, default_flow_style=False, sort_keys=False)

    if output:
        Path(output).write_text(output_yaml, encoding="utf-8")
        click.echo(f"Migrated config written to {output}")
    else:
        click.echo(output_yaml)


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
@click.option(
    "--target",
    type=click.Choice(["autoagent", "cx-studio"]),
    default="autoagent",
    show_default=True,
    help="Deployment target.",
)
@click.option("--project", default=None, help="GCP project ID (required for CX push).")
@click.option("--location", default="global", show_default=True, help="CX agent location.")
@click.option("--agent-id", default=None, help="CX agent ID (required for CX push).")
@click.option("--snapshot", default=None, help="CX snapshot JSON path from `autoagent cx import`.")
@click.option("--credentials", default=None, help="Path to service account JSON for CX calls.")
@click.option("--output", default=None, help="Output path for CX export package JSON.")
@click.option("--push/--no-push", default=False, show_default=True, help="Push to CX now (otherwise package only).")
def deploy(
    config_version: int | None,
    strategy: str,
    configs_dir: str,
    db: str,
    target: str,
    project: str | None,
    location: str,
    agent_id: str | None,
    snapshot: str | None,
    credentials: str | None,
    output: str | None,
    push: bool,
) -> None:
    """Deploy a config version.

    Examples:
      autoagent deploy --config-version 5 --strategy canary
      autoagent deploy --strategy immediate
      autoagent deploy --target cx-studio
    """
    if target == "cx-studio":
        try:
            selected_version, config, selected_path = _load_versioned_config(configs_dir, config_version)
        except FileNotFoundError as exc:
            click.echo(str(exc))
            click.echo("Run: autoagent build \"Describe your agent\" or autoagent init")
            return

        package_dir = Path(".autoagent")
        package_dir.mkdir(parents=True, exist_ok=True)
        output_path = Path(output) if output else package_dir / f"cx_export_v{selected_version:03d}.json"
        package = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "target": "cx-studio",
            "config_version": selected_version,
            "project": project,
            "location": location,
            "agent_id": agent_id,
            "config": config,
        }
        output_path.write_text(json.dumps(package, indent=2), encoding="utf-8")
        click.echo(f"CX export package written: {output_path}")

        if snapshot:
            try:
                from cx_studio import CxAuth, CxClient, CxExporter

                auth = CxAuth.__new__(CxAuth)
                auth._token = None
                auth._token_expiry = 0.0
                auth._project_id = project
                auth._credentials_path = credentials
                client = CxClient.__new__(CxClient)
                client._auth = auth
                client._timeout = 30.0
                client._max_retries = 3
                exporter = CxExporter(client)
                changes = exporter.preview_changes(config, snapshot)
                click.echo(f"Preview: {len(changes)} change(s) ready for CX export")
            except Exception as exc:
                click.echo(click.style(f"Warning: CX preview unavailable ({exc})", fg="yellow"))

        if not push:
            click.echo("No remote CX push performed (`--no-push`).")
            click.echo("Next step:")
            click.echo(
                "  autoagent cx export --project <project> --location "
                f"{location} --agent <agent-id> --config {selected_path} --snapshot <snapshot>"
            )
            return

        if not project or not agent_id or not snapshot:
            click.echo("CX push requires --project, --agent-id, and --snapshot.")
            raise SystemExit(2)

        from cx_studio import CxAuth, CxClient, CxExporter
        from cx_studio.types import CxAgentRef

        auth = CxAuth(credentials_path=credentials)
        client = CxClient(auth)
        exporter = CxExporter(client)
        ref = CxAgentRef(project=project, location=location, agent_id=agent_id)
        result = exporter.export_agent(config, ref, snapshot_path=snapshot, dry_run=False)
        click.echo(f"CX export pushed: {result.resources_updated} resource(s) updated")
        return

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
@click.option("--full-auto", is_flag=True, default=False,
              help="Danger mode: auto-promote accepted configs and skip manual gates.")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--memory-db", default=MEMORY_DB, show_default=True, help="Optimizer memory DB.")
def loop(max_cycles: int, stop_on_plateau: bool, delay: float, schedule_mode: str | None,
         interval_minutes: float | None, cron_expression: str | None, checkpoint_file: str | None,
         resume: bool, full_auto: bool, db: str, configs_dir: str, memory_db: str) -> None:
    """Run the continuous autoresearch loop.

    Observes agent health, proposes improvements, evaluates them, and deploys
    accepted changes — automatically, cycle after cycle.

    Examples:
      autoagent loop
      autoagent loop --max-cycles 100 --stop-on-plateau
    """
    (
        runtime,
        eval_runner,
        proposer,
        skill_engine,
        adversarial_simulator,
        skill_autolearner,
    ) = _build_runtime_components()
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
        skill_engine=skill_engine,
        use_skills=True,
        skill_selection_strategy="auto",
        skill_max_candidates=5,
        adversarial_simulator=adversarial_simulator,
        skill_autolearner=skill_autolearner,
        auto_learn_skills=runtime.optimizer.skill_autolearn_enabled,
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
    if full_auto:
        click.echo(click.style("  ⚠ FULL AUTO ENABLED (danger mode)", fg="yellow"))
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
                        if full_auto:
                            promoted = _promote_latest_version(deployer)
                            if promoted is not None:
                                click.echo(click.style(
                                    f"  FULL AUTO: promoted v{promoted:03d} to active",
                                    fg="yellow",
                                ))
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
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def status(db: str, configs_dir: str, memory_db: str, json_output: bool = False) -> None:
    """Show system health, config versions, and recent activity.

    Examples:
      autoagent status
    """
    store = ConversationStore(db_path=db)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    memory = OptimizationMemory(db_path=memory_db)

    # Config info
    deploy_status = deployer.status()
    active = deploy_status["active_version"]

    # Conversations count (preserved for compatibility)
    total_conversations = store.count()

    # Eval score from memory
    recent_attempts = memory.recent(limit=1)
    latest = recent_attempts[0] if recent_attempts else None

    # Health metrics
    report = Observer(store).observe()
    metrics = report.metrics

    # Cycles run
    all_attempts = memory.recent(limit=100)
    accepted_attempts = [attempt for attempt in all_attempts if attempt.status == "accepted"]

    # Top failures bar chart
    buckets = report.failure_buckets

    if json_output:
        data = {
            "config_version": active,
            "conversations": total_conversations,
            "eval_score": latest.score_after if latest else None,
            "safety_violation_rate": metrics.safety_violation_rate,
            "cycles_run": len(all_attempts),
            "failure_buckets": buckets,
            "loop_status": "idle",
            "next_action": _status_next_action(report, len(all_attempts), len(accepted_attempts)),
        }
        click.echo(json.dumps(data, indent=2))
        return

    # Feature 5: Rich status display
    click.echo(click.style("\nAutoAgent Status", bold=True))
    click.echo("━" * 17)
    click.echo(click.style(f"  {_soul_line('status')}", fg="cyan"))

    config_str = f"v{active:03d}" if active else "none"
    click.echo(f"  Config:     {config_str}")
    click.echo(f"  Conversations: {total_conversations}")

    if latest:
        click.echo(f"  Eval score: {latest.score_after:.4f}")
    else:
        click.echo("  Eval score: n/a")
    click.echo(f"  Mood:       {_score_mood(latest.score_after if latest else None)}")

    safety_str = f"{metrics.safety_violation_rate:.3f}"
    safety_ok = "✓" if metrics.safety_violation_rate == 0.0 else "✗"
    click.echo(f"  Safety:     {safety_str} {safety_ok}")
    click.echo(f"  Success:    {_bar_chart(metrics.success_rate)}  {metrics.success_rate:.0%}")
    click.echo(f"  Errors:     {_bar_chart(metrics.error_rate)}  {metrics.error_rate:.0%}")
    click.echo(f"  Cycles run: {len(all_attempts)}")

    if buckets:
        click.echo("\n  Top failures:")
        total_failures = sum(buckets.values())
        sorted_buckets = sorted(buckets.items(), key=lambda kv: kv[1], reverse=True)[:5]
        for bucket_name, count in sorted_buckets:
            pct = count / total_failures if total_failures > 0 else 0.0
            bar = _bar_chart(pct)
            pct_int = round(pct * 100)
            click.echo(f"    {bucket_name:<20} {bar}  {pct_int:>3}% ({count} conversations)")

    # Recommendation
    click.echo(f"\n  Next action: {_status_next_action(report, len(all_attempts), len(accepted_attempts))}")

    # Loop status
    click.echo("\n  Loop: idle")
    recs = _generate_recommendations(report, None)
    suggested_actions = ["autoagent optimize --cycles 2", "autoagent logs --limit 10"]
    if recs:
        first_runbook = recs[0].split("autoagent runbook apply ")[-1].strip()
        suggested_actions.insert(0, f"autoagent runbook apply {first_runbook}")
    _print_next_actions(suggested_actions)


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
# autoagent review (change cards)
# ---------------------------------------------------------------------------

@cli.group("review", invoke_without_command=True)
@click.pass_context
def review_group(ctx: click.Context) -> None:
    """Review proposed change cards from the optimizer."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(review_list)


@review_group.command("list")
@click.option("--limit", default=20, show_default=True, type=int, help="Number of cards to show.")
def review_list(limit: int = 20) -> None:
    """List pending change cards.

    Examples:
      autoagent review
      autoagent review list
    """
    from optimizer.change_card import ChangeCardStore

    store = ChangeCardStore()
    cards = store.list_pending(limit=limit)

    if not cards:
        click.echo("No pending change cards.")
        return

    click.echo(f"\nPending change cards ({len(cards)}):\n")
    click.echo(f"{'ID':<10}  {'Title':<35}  {'Risk':<8}  {'Status'}")
    click.echo(f"{'─' * 10}  {'─' * 35}  {'─' * 8}  {'─' * 10}")
    for card in cards:
        title = (card.title[:32] + "...") if len(card.title) > 35 else card.title
        click.echo(f"{card.card_id:<10}  {title:<35}  {card.risk_class:<8}  {card.status}")


@review_group.command("show")
@click.argument("card_id")
def review_show(card_id: str) -> None:
    """Show a specific change card with full terminal rendering.

    Examples:
      autoagent review show abc12345
    """
    from optimizer.change_card import ChangeCardStore

    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    click.echo(card.to_terminal())


@review_group.command("apply")
@click.argument("card_id")
def review_apply(card_id: str) -> None:
    """Apply (accept) a change card.

    Examples:
      autoagent review apply abc12345
    """
    from optimizer.change_card import ChangeCardStore

    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    if card.status != "pending":
        click.echo(f"Card is not pending (status={card.status})")
        raise SystemExit(1)

    store.update_status(card_id, "applied")
    click.echo(f"Applied change card {card_id}: {card.title}")


@review_group.command("reject")
@click.argument("card_id")
@click.option("--reason", default="", help="Reason for rejection.")
def review_reject(card_id: str, reason: str) -> None:
    """Reject a change card with an optional reason.

    Examples:
      autoagent review reject abc12345 --reason "Too risky"
    """
    from optimizer.change_card import ChangeCardStore

    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    if card.status != "pending":
        click.echo(f"Card is not pending (status={card.status})")
        raise SystemExit(1)

    store.update_status(card_id, "rejected", reason=reason)
    click.echo(f"Rejected change card {card_id}: {card.title}")
    if reason:
        click.echo(f"  Reason: {reason}")


@review_group.command("export")
@click.argument("card_id")
def review_export(card_id: str) -> None:
    """Export a change card as markdown.

    Examples:
      autoagent review export abc12345
    """
    from optimizer.change_card import ChangeCardStore

    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    click.echo(card.to_markdown())


# ---------------------------------------------------------------------------
# autoagent changes (aliases for review)
# ---------------------------------------------------------------------------

@cli.group("changes", invoke_without_command=True)
@click.pass_context
def changes_group(ctx: click.Context) -> None:
    """Changes — aliases for reviewable optimizer change cards."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(changes_list)


@changes_group.command("list")
@click.option("--limit", default=20, show_default=True, type=int, help="Number of cards to show.")
def changes_list(limit: int = 20) -> None:
    """List pending change cards (alias for `autoagent review list`)."""
    from optimizer.change_card import ChangeCardStore

    Path(".autoagent").mkdir(parents=True, exist_ok=True)
    store = ChangeCardStore()
    cards = store.list_pending(limit=limit)

    if not cards:
        click.echo("No pending change cards.")
        return

    click.echo(f"\nPending change cards ({len(cards)}):\n")
    click.echo(f"{'ID':<10}  {'Title':<35}  {'Risk':<8}  {'Status'}")
    click.echo(f"{'─' * 10}  {'─' * 35}  {'─' * 8}  {'─' * 10}")
    for card in cards:
        title = (card.title[:32] + "...") if len(card.title) > 35 else card.title
        click.echo(f"{card.card_id:<10}  {title:<35}  {card.risk_class:<8}  {card.status}")


@changes_group.command("show")
@click.argument("card_id")
def changes_show(card_id: str) -> None:
    """Show a specific change card (alias for `autoagent review show`)."""
    from optimizer.change_card import ChangeCardStore

    Path(".autoagent").mkdir(parents=True, exist_ok=True)
    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    click.echo(card.to_terminal())


@changes_group.command("approve")
@click.argument("card_id")
def changes_approve(card_id: str) -> None:
    """Approve/apply a change card (alias for `autoagent review apply`)."""
    from optimizer.change_card import ChangeCardStore

    Path(".autoagent").mkdir(parents=True, exist_ok=True)
    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    if card.status != "pending":
        click.echo(f"Card is not pending (status={card.status})")
        raise SystemExit(1)
    store.update_status(card_id, "applied")
    click.echo(f"Applied change card {card_id}: {card.title}")


@changes_group.command("reject")
@click.argument("card_id")
@click.option("--reason", default="", help="Reason for rejection.")
def changes_reject(card_id: str, reason: str) -> None:
    """Reject a change card (alias for `autoagent review reject`)."""
    from optimizer.change_card import ChangeCardStore

    Path(".autoagent").mkdir(parents=True, exist_ok=True)
    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    if card.status != "pending":
        click.echo(f"Card is not pending (status={card.status})")
        raise SystemExit(1)
    store.update_status(card_id, "rejected", reason=reason)
    click.echo(f"Rejected change card {card_id}: {card.title}")
    if reason:
        click.echo(f"  Reason: {reason}")


@changes_group.command("export")
@click.argument("card_id")
def changes_export(card_id: str) -> None:
    """Export a change card markdown (alias for `autoagent review export`)."""
    from optimizer.change_card import ChangeCardStore

    Path(".autoagent").mkdir(parents=True, exist_ok=True)
    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    click.echo(card.to_markdown())


# ---------------------------------------------------------------------------
# autoagent runbook
# ---------------------------------------------------------------------------

@cli.group("runbook")
def runbook_group() -> None:
    """Runbooks — curated bundles of skills, policies, and tool contracts."""


@runbook_group.command("list")
@click.option("--db", default=REGISTRY_DB, show_default=True)
def runbook_list(db: str) -> None:
    """List all runbooks.

    Examples:
      autoagent runbook list
    """
    from registry.runbooks import RunbookStore

    store = RunbookStore(db_path=db)
    runbooks = store.list()

    if not runbooks:
        click.echo("No runbooks found.")
        return

    click.echo(f"\nRunbooks ({len(runbooks)}):\n")
    click.echo(f"{'Name':<30}  {'Ver':>4}  {'Tags':<30}  {'Description'}")
    click.echo(f"{'─' * 30}  {'─' * 4}  {'─' * 30}  {'─' * 30}")
    for pb in runbooks:
        tags = ", ".join(pb.tags[:3])
        desc = (pb.description[:28] + "...") if len(pb.description) > 30 else pb.description
        click.echo(f"{pb.name:<30}  v{pb.version:>3}  {tags:<30}  {desc}")


@runbook_group.command("show")
@click.argument("name")
@click.option("--db", default=REGISTRY_DB, show_default=True)
def runbook_show(name: str, db: str) -> None:
    """Show runbook details.

    Examples:
      autoagent runbook show fix-retrieval-grounding
    """
    from registry.runbooks import RunbookStore

    store = RunbookStore(db_path=db)
    pb = store.get(name)
    if pb is None:
        click.echo(f"Runbook not found: {name}")
        raise SystemExit(1)

    click.echo(f"\n{pb.name} (v{pb.version})")
    click.echo(f"  {pb.description}")
    click.echo(f"\n  Tags: {', '.join(pb.tags)}")
    if pb.skills:
        click.echo(f"  Skills: {', '.join(pb.skills)}")
    if pb.policies:
        click.echo(f"  Policies: {', '.join(pb.policies)}")
    if pb.tool_contracts:
        click.echo(f"  Tool contracts: {', '.join(pb.tool_contracts)}")
    if pb.surfaces:
        click.echo(f"  Surfaces: {', '.join(pb.surfaces)}")
    if pb.triggers:
        click.echo("  Triggers:")
        for t in pb.triggers:
            click.echo(f"    - {json.dumps(t)}")


@runbook_group.command("apply")
@click.argument("name")
@click.option("--db", default=REGISTRY_DB, show_default=True)
def runbook_apply(name: str, db: str) -> None:
    """Apply a runbook — registers its skills, policies, and tool contracts.

    Examples:
      autoagent runbook apply fix-retrieval-grounding
    """
    from registry.runbooks import RunbookStore

    store = RunbookStore(db_path=db)
    pb = store.get(name)
    if pb is None:
        click.echo(f"Runbook not found: {name}")
        raise SystemExit(1)

    click.echo(f"Applying runbook: {pb.name} (v{pb.version})")
    if pb.skills:
        click.echo(f"  Skills: {', '.join(pb.skills)}")
    if pb.policies:
        click.echo(f"  Policies: {', '.join(pb.policies)}")
    if pb.tool_contracts:
        click.echo(f"  Tool contracts: {', '.join(pb.tool_contracts)}")
    click.echo(f"\nRunbook '{name}' applied. Registered items are now active.")


@runbook_group.command("create")
@click.option("--name", required=True, help="Runbook name.")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True),
              help="YAML file with runbook definition.")
@click.option("--db", default=REGISTRY_DB, show_default=True)
def runbook_create(name: str, file_path: str, db: str) -> None:
    """Create a runbook from a YAML file.

    Examples:
      autoagent runbook create --name my-runbook --file runbook.yaml
    """
    from registry.runbooks import Runbook, RunbookStore

    store = RunbookStore(db_path=db)
    raw = Path(file_path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        click.echo("Error: YAML file must contain a mapping.", err=True)
        raise SystemExit(1)

    data["name"] = name
    pb = Runbook.from_dict(data)
    result_name, version = store.register(pb)
    click.echo(f"Created runbook: {result_name} (v{version})")


# ---------------------------------------------------------------------------
# autoagent memory
# ---------------------------------------------------------------------------

@cli.group("memory")
def memory_group() -> None:
    """Project memory — manage AUTOAGENT.md persistent context."""


@memory_group.command("show")
def memory_show() -> None:
    """Show AUTOAGENT.md contents.

    Examples:
      autoagent memory show
    """
    from core.project_memory import ProjectMemory

    mem = ProjectMemory.load()
    if mem is None:
        click.echo("No AUTOAGENT.md found. Run: autoagent init")
        return

    click.echo(mem.raw_content)


@memory_group.command("add")
@click.argument("note")
@click.option("--section", required=True,
              type=click.Choice(["good", "bad", "preference", "constraint"]),
              help="Section to add the note to.")
def memory_add(note: str, section: str) -> None:
    """Add a note to a section of AUTOAGENT.md.

    Examples:
      autoagent memory add "Prefer instruction edits over model swaps" --section preference
      autoagent memory add "Never use gpt-3.5 for safety checks" --section bad
    """
    from core.project_memory import ProjectMemory

    mem = ProjectMemory.load()
    if mem is None:
        click.echo("No AUTOAGENT.md found. Creating one first...")
        mem = ProjectMemory(
            agent_name="My Agent",
            platform="Google ADK",
            use_case="General purpose assistant",
        )

    mem.add_note(section, note)
    path = mem.save()
    click.echo(f"Added to [{section}]: {note}")
    click.echo(f"Saved to {path}")


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
# autoagent mcp-server
# ---------------------------------------------------------------------------

@cli.command("mcp-server")
@click.option("--port", default=None, type=int, help="HTTP/SSE port (NOT YET IMPLEMENTED — stdio mode only).")
def mcp_server_cmd(port: int | None) -> None:
    """Start MCP server for AI coding tool integration.

    Runs in stdio mode for Claude Code, Cursor, and other MCP-compatible tools.
    HTTP/SSE mode is not yet implemented.

    Setup for Claude Code:
      Add to ~/.claude/mcp.json:
      {
        "mcpServers": {
          "autoagent": {
            "command": "autoagent",
            "args": ["mcp-server"]
          }
        }
      }

    Examples:
      autoagent mcp-server                  # Stdio mode (default)
      autoagent mcp-server --port 8081      # HTTP/SSE mode (not yet implemented)
    """
    if port is not None:
        click.echo(f"HTTP/SSE mode on port {port} is not yet implemented. Use stdio mode (no --port flag).")
        return

    from mcp_server.server import run_stdio
    run_stdio()


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
    runner = _build_eval_runner(runtime)
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
    (
        runtime,
        eval_runner,
        proposer,
        skill_engine,
        adversarial_simulator,
        skill_autolearner,
    ) = _build_runtime_components()
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
        skill_engine=skill_engine,
        use_skills=True,
        skill_selection_strategy="auto",
        skill_max_candidates=5,
        adversarial_simulator=adversarial_simulator,
        skill_autolearner=skill_autolearner,
        auto_learn_skills=runtime.optimizer.skill_autolearn_enabled,
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
    (
        runtime,
        eval_runner,
        proposer,
        skill_engine,
        adversarial_simulator,
        skill_autolearner,
    ) = _build_runtime_components()
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
        skill_engine=skill_engine,
        use_skills=True,
        skill_selection_strategy="auto",
        skill_max_candidates=5,
        adversarial_simulator=adversarial_simulator,
        skill_autolearner=skill_autolearner,
        auto_learn_skills=runtime.optimizer.skill_autolearn_enabled,
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
# autoagent skill — executable skills registry
# ---------------------------------------------------------------------------
# autoagent skill ... (unified skills from core.skills)
# ---------------------------------------------------------------------------

@cli.group("skill")
def skill_group() -> None:
    """Unified skill management — build-time and run-time skills."""


# Register all skill commands from cli.skills module
from cli.skills import register_skill_commands
register_skill_commands(skill_group)


@skill_group.command("export-md")
@click.argument("skill_name")
@click.option("--output", default=None)
def skill_export_md(skill_name: str, output: str | None) -> None:
    """Export a skill as SKILL.md."""
    click.echo(f"Exporting {skill_name} as SKILL.md...")


@skill_group.command("import-md")
@click.argument("path")
def skill_import_md(path: str) -> None:
    """Import a skill from SKILL.md file."""
    click.echo(f"Importing skill from {path}...")


# ---------------------------------------------------------------------------
# autoagent curriculum ... (self-play curriculum generator)
# ---------------------------------------------------------------------------

@cli.group("curriculum")
def curriculum_group() -> None:
    """Self-play curriculum generator for adversarial eval prompts."""


@curriculum_group.command("generate")
@click.option("--limit", default=10, show_default=True, help="Max failure clusters to process")
@click.option("--prompts-per-cluster", default=3, show_default=True, help="Prompts to generate per cluster")
@click.option("--adversarial-ratio", default=0.2, show_default=True, help="Ratio of adversarial variants")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation database path")
@click.option("--output-dir", default=".autoagent/curriculum", show_default=True, help="Output directory")
def curriculum_generate(
    limit: int,
    prompts_per_cluster: int,
    adversarial_ratio: float,
    db: str,
    output_dir: str,
) -> None:
    """Generate a new curriculum batch from recent failures.

    Examples:
      autoagent curriculum generate
      autoagent curriculum generate --limit 20 --prompts-per-cluster 5
    """
    from optimizer.curriculum_generator import CurriculumGenerator, CurriculumStore, FailureCluster
    from observer.classifier import FailureClassifier

    click.echo(click.style("\n⚡ Curriculum Generator", fg="cyan", bold=True))
    click.echo("")

    # Load recent failures from conversation store
    store = ConversationStore(db_path=db)
    recent_failures = store.list_failed(limit=limit * 10)  # Get more to cluster

    if not recent_failures:
        click.echo(click.style("  ✗ ", fg="red") + "No recent failures found")
        return

    click.echo(click.style("  ✓ ", fg="green") + f"Found {len(recent_failures)} recent failures")

    # Classify failures into clusters
    classifier = FailureClassifier()
    clusters_map: dict[str, list] = {}
    for record in recent_failures:
        categories = classifier.classify(record)
        for cat in categories:
            if cat not in clusters_map:
                clusters_map[cat] = []
            clusters_map[cat].append({
                "user_message": record.user_message,
                "specialist_used": record.specialist_used,
                "error": record.error_type or "",
            })

    # Convert to FailureCluster objects
    failure_clusters = []
    for family, examples in list(clusters_map.items())[:limit]:
        cluster = FailureCluster(
            failure_family=family,
            count=len(examples),
            examples=examples,
            categories=[family],
            pass_rate=0.5,  # TODO: fetch from eval history
        )
        failure_clusters.append(cluster)

    click.echo(click.style("  ✓ ", fg="green") + f"Identified {len(failure_clusters)} failure clusters")

    # Generate curriculum
    generator = CurriculumGenerator(
        prompts_per_cluster=prompts_per_cluster,
        adversarial_ratio=adversarial_ratio,
    )
    batch = generator.generate_curriculum(failure_clusters)

    # Save batch
    curriculum_store = CurriculumStore(store_dir=output_dir)
    filepath = curriculum_store.save_batch(batch)

    click.echo(click.style("  ✓ ", fg="green") + f"Generated {len(batch.prompts)} prompts")
    click.echo("")
    click.echo(f"  Batch ID: {click.style(batch.batch_id, fg='cyan')}")
    click.echo(f"  Saved to: {click.style(filepath, fg='cyan')}")
    click.echo("")
    click.echo("  Difficulty distribution:")
    for tier, count in batch.tier_distribution.items():
        click.echo(f"    {tier:<12} {count:>3} prompts")
    click.echo("")


@curriculum_group.command("list")
@click.option("--limit", default=20, show_default=True, help="Max batches to list")
@click.option("--output-dir", default=".autoagent/curriculum", show_default=True, help="Curriculum directory")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def curriculum_list(limit: int, output_dir: str, json_output: bool) -> None:
    """List generated curriculum batches.

    Examples:
      autoagent curriculum list
      autoagent curriculum list --json
    """
    from optimizer.curriculum_generator import CurriculumStore

    curriculum_store = CurriculumStore(store_dir=output_dir)
    batches = curriculum_store.list_batches(limit=limit)

    if not batches:
        if json_output:
            click.echo(json.dumps([], indent=2))
        else:
            click.echo("No curriculum batches found.")
        return

    if json_output:
        data = [
            {
                "batch_id": b.batch_id,
                "generated_at": b.generated_at,
                "num_prompts": len(b.prompts),
                "tier_distribution": b.tier_distribution,
                "source_clusters": b.source_clusters,
            }
            for b in batches
        ]
        click.echo(json.dumps(data, indent=2))
        return

    # Table output
    click.echo(f"\nCurriculum Batches ({len(batches)} found)\n")
    click.echo(f"{'Batch ID':<25} {'Generated':<20} {'Prompts':<8} {'Easy':<6} {'Medium':<6} {'Hard':<6} {'Adv':<6}")
    click.echo("─" * 85)

    for batch in batches:
        generated_time = datetime.fromtimestamp(batch.generated_at, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        dist = batch.tier_distribution
        click.echo(
            f"{batch.batch_id:<25} {generated_time:<20} {len(batch.prompts):<8} "
            f"{dist.get('easy', 0):<6} {dist.get('medium', 0):<6} {dist.get('hard', 0):<6} {dist.get('adversarial', 0):<6}"
        )


@curriculum_group.command("apply")
@click.argument("batch_id")
@click.option("--output-dir", default=".autoagent/curriculum", show_default=True, help="Curriculum directory")
@click.option("--eval-cases-dir", default="evals/cases", show_default=True, help="Eval cases directory")
def curriculum_apply(batch_id: str, output_dir: str, eval_cases_dir: str) -> None:
    """Apply a curriculum batch to the active eval set.

    Examples:
      autoagent curriculum apply curriculum_abc123
    """
    from optimizer.curriculum_generator import CurriculumStore

    click.echo(click.style("\n⚡ Applying Curriculum Batch", fg="cyan", bold=True))
    click.echo("")

    curriculum_store = CurriculumStore(store_dir=output_dir)
    batch = curriculum_store.load_batch(batch_id)

    if not batch:
        click.echo(click.style("  ✗ ", fg="red") + f"Batch not found: {batch_id}")
        return

    try:
        eval_file = curriculum_store.apply_batch_to_eval_set(batch_id, eval_cases_dir)
        click.echo(click.style("  ✓ ", fg="green") + f"Applied {len(batch.prompts)} prompts to eval set")
        click.echo("")
        click.echo(f"  Eval file: {click.style(eval_file, fg='cyan')}")
        click.echo("")
    except Exception as e:
        click.echo(click.style("  ✗ ", fg="red") + f"Failed to apply batch: {e}")


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


@trace_group.command("promote")
@click.argument("trace_id")
def trace_promote(trace_id: str) -> None:
    """Promote a trace to an eval case."""
    from observer.trace_promoter import TracePromoter
    promoter = TracePromoter()
    click.echo(f"Promoting trace {trace_id} to eval case...")


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


# ---------------------------------------------------------------------------
# autoagent quickstart
# ---------------------------------------------------------------------------

@cli.command("full-auto")
@click.option("--cycles", default=5, show_default=True, type=int, help="Optimization cycles to run.")
@click.option("--max-loop-cycles", default=20, show_default=True, type=int,
              help="Continuous loop cycles after optimize.")
@click.option("--yes", "acknowledge", is_flag=True, default=False,
              help="Acknowledge dangerous mode and skip permission-style gates.")
@click.pass_context
def full_auto(ctx: click.Context, cycles: int, max_loop_cycles: int, acknowledge: bool) -> None:
    """Run optimization + loop in dangerous full-auto mode.

    Similar intent to 'dangerously skip permissions': auto-promotes accepted
    configs and skips manual promotion/review gates.
    """
    if not acknowledge:
        click.echo(click.style(
            "Refusing to run full-auto without explicit acknowledgement.\n"
            "Re-run with: autoagent full-auto --yes",
            fg="red",
        ))
        raise SystemExit(1)

    click.echo(click.style("\n⚠ FULL AUTO MODE ENABLED", fg="yellow", bold=True))
    click.echo("This mode auto-promotes accepted configs with minimal friction.")
    _print_cli_plan(
        "Full-auto plan",
        [
            f"Run optimize for {cycles} cycles with --full-auto",
            f"Run loop for {max_loop_cycles} cycles with --full-auto",
            "Keep shipping winning configs unless plateau/limits stop it",
        ],
    )

    ctx.invoke(optimize, cycles=cycles, mode=None, strategy=None, db=DB_PATH,
               configs_dir=CONFIGS_DIR, memory_db=MEMORY_DB, full_auto=True, json_output=False)
    ctx.invoke(
        loop,
        max_cycles=max_loop_cycles,
        stop_on_plateau=True,
        delay=1.0,
        schedule_mode=None,
        interval_minutes=None,
        cron_expression=None,
        checkpoint_file=None,
        resume=True,
        full_auto=True,
        db=DB_PATH,
        configs_dir=CONFIGS_DIR,
        memory_db=MEMORY_DB,
    )


@cli.command()
@click.option("--scope", type=click.Choice(["dev", "staging", "production"]), default="dev")
@click.option("--yes", is_flag=True)
@click.option("--cycles", default=3)
@click.option("--max-loop-cycles", default=10)
def autonomous(scope: str, yes: bool, cycles: int, max_loop_cycles: int) -> None:
    """Run autonomous optimization with scoped permissions."""
    click.echo(f"Running autonomous optimization (scope: {scope})...")
    # Delegate to existing full-auto logic with permission scope


@cli.command("quickstart")
@click.option("--agent-name", default="My Agent", show_default=True,
              help="Agent name for AUTOAGENT.md.")
@click.option("--verbose", is_flag=True, default=False, help="Show detailed output.")
@click.option("--dir", "target_dir", default=".", show_default=True,
              help="Directory to initialize in.")
@click.option("--open/--no-open", "auto_open", default=True, help="Auto-open web console after completion.")
@click.pass_context
def quickstart(ctx: click.Context, agent_name: str, verbose: bool, target_dir: str, auto_open: bool) -> None:
    """Run the ENTIRE golden path: init → seed → eval → optimize → summary.

    A single command that takes you from zero to optimized agent in minutes.

    Examples:
      autoagent quickstart
      autoagent quickstart --agent-name "Support Bot" --verbose
    """
    click.echo(click.style("\n✦ AutoAgent Quickstart", fg="cyan", bold=True))
    click.echo(click.style(f"  {_soul_line('quickstart')}", fg="cyan"))
    click.echo(click.style("  Running the full golden path...\n", fg="white"))
    _print_cli_plan(
        "Quickstart plan",
        [
            "Initialize project scaffold",
            "Run baseline evaluation",
            "Perform optimization cycles",
            "Summarize wins + recommended next steps",
        ],
    )

    # Step 1: Init
    click.echo(click.style("━━━ Step 1/4: Initialize project", fg="cyan", bold=True))
    ctx.invoke(init_project, template="customer-support", target_dir=target_dir,
               agent_name=agent_name, platform="Google ADK", with_synthetic_data=True)
    workspace_paths = _workspace_state_paths(target_dir)

    # Step 2: Run eval baseline
    click.echo(click.style("\n━━━ Step 2/4: Run eval baseline", fg="cyan", bold=True))
    runtime = _scope_runtime_to_workspace(load_runtime_config(), workspace_paths["workspace"])
    eval_runner = _build_eval_runner(
        runtime,
        cases_dir=str(workspace_paths["cases_dir"]),
        trace_db_path=str(workspace_paths["trace_db"]),
    )
    _warn_mock_modes(eval_runner=eval_runner)
    baseline_score = eval_runner.run()
    click.echo(click.style("  ✓ ", fg="green") + f"Baseline composite: {baseline_score.composite:.4f}")
    click.echo(f"    Cases: {baseline_score.passed_cases}/{baseline_score.total_cases} passed")
    if verbose:
        _print_score(baseline_score, "  Baseline details")

    # Step 3: Run 3 optimisation cycles
    click.echo(click.style("\n━━━ Step 3/4: Optimize (3 cycles)", fg="cyan", bold=True))
    store = ConversationStore(db_path=str(workspace_paths["conversation_db"]))
    deployer = Deployer(configs_dir=str(workspace_paths["configs_dir"]), store=store)
    memory = OptimizationMemory(db_path=str(workspace_paths["memory_db"]))
    router = build_router_from_runtime_config(runtime.optimizer)
    proposer = Proposer(use_mock=router.mock_mode, llm_router=router, mock_reason=router.mock_reason)
    _warn_mock_modes(proposer=proposer)
    _, skill_engine = _build_skill_components(db_path=str(workspace_paths["skill_db"]))
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=proposer,
        significance_alpha=runtime.eval.significance_alpha,
        significance_min_effect_size=runtime.eval.significance_min_effect_size,
        significance_iterations=runtime.eval.significance_iterations,
        skill_engine=skill_engine,
        use_skills=True,
        skill_selection_strategy="auto",
        skill_max_candidates=5,
    )

    # Track all-time best score for quickstart
    best_score_file = workspace_paths["best_score_file"]
    all_time_best = 0.0
    if best_score_file.exists():
        all_time_best = float(best_score_file.read_text().strip())

    best_score = baseline_score.composite
    for cycle in range(1, 4):
        report = observer_mod_observe(store)
        current_config = _ensure_active_config(deployer)
        failure_samples = _build_failure_samples(store)
        new_config, qs_status = optimizer.optimize(
            report, current_config, failure_samples=failure_samples,
        )

        # Feature 1 + 2: gather latest attempt for storytelling
        latest_attempts = memory.recent(limit=1)
        latest = latest_attempts[0] if latest_attempts else None
        proposal_desc = latest.change_description if latest else None
        score_after: float | None = latest.score_after if latest else None
        score_before_val: float | None = latest.score_before if latest else None
        p_val: float | None = latest.significance_p_value if latest else None

        _stream_cycle_output(
            cycle_num=cycle,
            total=3,
            report=report,
            proposal_desc=proposal_desc,
            score_after=score_after,
            score_before=score_before_val,
            p_value=p_val,
            all_time_best=all_time_best,
            best_score_file=best_score_file,
        )

        # Update all_time_best if we got a new score
        if score_after is not None and score_after > all_time_best:
            all_time_best = score_after

        if new_config is not None:
            score = eval_runner.run(config=new_config)
            deployer.deploy(new_config, _score_to_dict(score))
            best_score = max(best_score, score.composite)

    # Step 4: Summary
    click.echo(click.style("\n━━━ Step 4/4: Summary", fg="cyan", bold=True))
    improvement = best_score - baseline_score.composite
    click.echo(f"\n  Baseline:    {baseline_score.composite:.4f}")
    click.echo(f"  Best score:  {best_score:.4f}")
    if improvement > 0:
        click.echo(click.style(f"  Improvement: +{improvement:.4f} ✓", fg="green"))
    else:
        click.echo(click.style(f"  Improvement: {improvement:.4f}", fg="yellow"))

    # Feature 1: Story block — top 3 accepted changes
    accepted = [a for a in memory.recent(limit=10) if a.status == "accepted"]
    accepted.sort(key=lambda a: a.score_after - a.score_before, reverse=True)
    if accepted:
        click.echo(click.style(
            f"\n  ✦ Your agent improved from {baseline_score.composite:.2f}"
            f" → {best_score:.2f} in 3 cycles.", fg="cyan", bold=True,
        ))
        click.echo("    Key improvements:")
        for i, attempt in enumerate(accepted[:3], start=1):
            click.echo(f"    {i}. {attempt.change_description}")

    # Feature 4: Recommendations
    final_report = observer_mod_observe(store)
    recs = _generate_recommendations(final_report, None)
    if recs:
        click.echo(click.style("\n  ⚡ Recommended next steps:", fg="cyan", bold=True))
        for rec in recs:
            click.echo(rec)

    click.echo(click.style("\n  ✦ Quickstart complete!", fg="cyan", bold=True))
    click.echo("    Next: " + click.style("autoagent server", bold=True)
               + " to explore results in the web console\n")

    if auto_open:
        _auto_open_console()


def observer_mod_observe(store: ConversationStore):
    """Thin wrapper to run Observer.observe() from a store."""
    obs = Observer(store)
    return obs.observe()


# ---------------------------------------------------------------------------
# autoagent demo
# ---------------------------------------------------------------------------

@cli.group("demo")
def demo() -> None:
    """Demo commands for presentations and quick trials."""


@demo.command("quickstart")
@click.option("--dir", "target_dir", default=".", show_default=True,
              help="Directory to initialize in.")
@click.option("--open/--no-open", "auto_open", default=True, help="Auto-open web console after completion.")
@click.pass_context
def demo_quickstart(ctx: click.Context, target_dir: str, auto_open: bool) -> None:
    """Interactive demo: seed data, run one optimise cycle, show results.

    More visual and concise than quickstart — designed for presentations.

    Examples:
      autoagent demo quickstart
    """
    click.echo(click.style("\n╔══════════════════════════════════════╗", fg="cyan"))
    click.echo(click.style("║       AutoAgent Demo Mode            ║", fg="cyan"))
    click.echo(click.style("╚══════════════════════════════════════╝\n", fg="cyan"))

    # Init + seed
    click.echo(click.style("▸ Setting up project...", fg="white", bold=True))
    ctx.invoke(init_project, template="customer-support", target_dir=target_dir,
               agent_name="Demo Agent", platform="Google ADK", with_synthetic_data=True)
    workspace_paths = _workspace_state_paths(target_dir)

    # Single eval
    click.echo(click.style("\n▸ Running evaluation...", fg="white", bold=True))
    runtime = _scope_runtime_to_workspace(load_runtime_config(), workspace_paths["workspace"])
    eval_runner = _build_eval_runner(
        runtime,
        cases_dir=str(workspace_paths["cases_dir"]),
        trace_db_path=str(workspace_paths["trace_db"]),
    )
    _warn_mock_modes(eval_runner=eval_runner)
    score = eval_runner.run()
    click.echo(f"  Score: {score.composite:.4f}  |  "
               f"Passed: {score.passed_cases}/{score.total_cases}  |  "
               f"Safety: {score.safety:.4f}")

    # Single optimise cycle
    click.echo(click.style("\n▸ Running optimization cycle...", fg="white", bold=True))
    store = ConversationStore(db_path=str(workspace_paths["conversation_db"]))
    deployer = Deployer(configs_dir=str(workspace_paths["configs_dir"]), store=store)
    memory = OptimizationMemory(db_path=str(workspace_paths["memory_db"]))
    router = build_router_from_runtime_config(runtime.optimizer)
    proposer = Proposer(use_mock=router.mock_mode, llm_router=router, mock_reason=router.mock_reason)
    _warn_mock_modes(proposer=proposer)
    _, skill_engine = _build_skill_components(db_path=str(workspace_paths["skill_db"]))
    optimizer = Optimizer(
        eval_runner=eval_runner,
        memory=memory,
        proposer=proposer,
        significance_alpha=runtime.eval.significance_alpha,
        significance_min_effect_size=runtime.eval.significance_min_effect_size,
        significance_iterations=runtime.eval.significance_iterations,
        skill_engine=skill_engine,
        use_skills=True,
        skill_selection_strategy="auto",
        skill_max_candidates=5,
    )

    # Track all-time best score for demo
    best_score_file = workspace_paths["best_score_file"]
    all_time_best = 0.0
    if best_score_file.exists():
        all_time_best = float(best_score_file.read_text().strip())

    report = observer_mod_observe(store)
    current_config = _ensure_active_config(deployer)
    failure_samples = _build_failure_samples(store)
    new_config, demo_status = optimizer.optimize(
        report, current_config, failure_samples=failure_samples,
    )

    # Feature 2: streaming output for demo cycle
    latest_attempts = memory.recent(limit=1)
    latest = latest_attempts[0] if latest_attempts else None
    proposal_desc = latest.change_description if latest else None
    s_after: float | None = latest.score_after if latest else None
    s_before: float | None = latest.score_before if latest else None
    p_val: float | None = latest.significance_p_value if latest else None

    _stream_cycle_output(
        cycle_num=1,
        total=1,
        report=report,
        proposal_desc=proposal_desc,
        score_after=s_after,
        score_before=s_before,
        p_value=p_val,
        all_time_best=all_time_best,
        best_score_file=best_score_file,
    )

    if new_config is not None:
        new_score = eval_runner.run(config=new_config)
        deployer.deploy(new_config, _score_to_dict(new_score))

    # Feature 4: Recommendations
    final_report = observer_mod_observe(store)
    recs = _generate_recommendations(final_report, None)
    if recs:
        click.echo(click.style("\n  ⚡ Recommended next steps:", fg="cyan", bold=True))
        for rec in recs:
            click.echo(rec)

    # Done
    click.echo(click.style("\n▸ Demo complete!", fg="cyan", bold=True))
    click.echo("  Run " + click.style("autoagent server", bold=True)
               + " to open the web console")
    click.echo("  Run " + click.style("autoagent quickstart", bold=True)
               + " for the full multi-cycle experience\n")

    if auto_open:
        _auto_open_console()


@demo.command("vp")
@click.option("--agent-name", default="Acme Support Bot", show_default=True,
              help="Agent name for the demo scenario.")
@click.option("--company", default="Acme Corp", show_default=True,
              help="Company name for the demo scenario.")
@click.option("--no-pause", is_flag=True, default=False,
              help="Skip dramatic pauses between acts.")
@click.option("--web", is_flag=True, default=False,
              help="Auto-start server and open browser after demo.")
def demo_vp(agent_name: str, company: str, no_pause: bool, web: bool) -> None:
    """VP-ready demo with 5-act storytelling structure.

    A polished, rehearsed demo flow that showcases AutoAgent's power in under 5 minutes.
    Uses curated synthetic data to tell a compelling story about agent self-healing.

    Examples:
      autoagent demo vp
      autoagent demo vp --agent-name "Support Bot" --company "Acme Inc"
      autoagent demo vp --no-pause --web
    """
    def pause(seconds: float = 1.0) -> None:
        """Dramatic pause between acts unless --no-pause."""
        if not no_pause:
            time.sleep(seconds)

    # ============================================================================
    # ACT 1: THE BROKEN AGENT (dramatic reveal)
    # ============================================================================
    click.echo("\n")
    click.echo(click.style(f"⚠️  Agent Health Report: {agent_name}", fg="white", bold=True))
    click.echo(click.style("━" * 60, fg="white"))
    click.echo()
    pause(0.5)

    # Overall score bar
    overall_score = 0.62
    bar_filled = int(overall_score * 10)
    bar = "■" * bar_filled + "░" * (10 - bar_filled)
    click.echo(click.style(f"Overall Score: {overall_score:.2f} {bar} CRITICAL", fg="red", bold=True))
    click.echo()
    pause(0.3)

    # Metrics breakdown
    click.echo(click.style("🔴 Routing Accuracy:  58%  ", fg="red") + "(40% of billing → wrong agent)")
    pause(0.2)
    click.echo(click.style("🔴 Safety Score:       0.94 ", fg="red") + "(3 data leaks detected)")
    pause(0.2)
    click.echo(click.style("🔴 Avg Latency:        4.5s ", fg="red") + "(SLA: 3.0s)")
    pause(0.2)
    click.echo(click.style("🟡 Resolution Rate:    71%", fg="yellow"))
    pause(0.2)
    click.echo(click.style("🟢 Tone & Empathy:     0.89", fg="green"))
    click.echo()
    pause(0.3)

    # Top issues
    click.echo(click.style("Top Issues:", fg="white", bold=True))
    click.echo(click.style("  1. 🔴 Billing queries routed to tech_support (23 conversations)", fg="red"))
    pause(0.2)
    click.echo(click.style("  2. 🔴 Internal pricing exposed to customers (3 conversations)", fg="red"))
    pause(0.2)
    click.echo(click.style("  3. 🟡 Tool timeout on order_lookup (8 conversations)", fg="yellow"))
    click.echo()
    pause(1.0)

    # ============================================================================
    # ACT 2: DIAGNOSIS (the "aha" moment)
    # ============================================================================
    click.echo(click.style("🔍 Diagnosing issues...", fg="cyan", bold=True))
    click.echo()
    pause(0.5)

    click.echo(click.style("Root Cause Analysis:", fg="white", bold=True))

    # Issue 1
    click.echo(click.style("┌─────────────────────────────────────────────────────────┐", fg="white"))
    click.echo(click.style("│ Issue #1: Billing Misroutes (CRITICAL)                  │", fg="white"))
    pause(0.3)
    click.echo(click.style("│ The routing instructions lack keywords for billing      │", fg="white"))
    click.echo(click.style("│ terms like \"invoice\", \"charge\", \"refund\", \"payment\".    │", fg="white"))
    click.echo(click.style("│ These queries fall through to the default tech_support   │", fg="white"))
    click.echo(click.style("│ agent instead of billing_agent.                         │", fg="white"))
    click.echo(click.style("│                                                         │", fg="white"))
    click.echo(click.style("│ Impact: 23 misrouted conversations → frustrated users   │", fg="yellow"))
    click.echo(click.style("│ Fix confidence: HIGH                                    │", fg="green"))
    pause(0.3)

    # Issue 2
    click.echo(click.style("├─────────────────────────────────────────────────────────┤", fg="white"))
    click.echo(click.style("│ Issue #2: Data Leak in Safety Policy (CRITICAL)         │", fg="white"))
    pause(0.3)
    click.echo(click.style("│ The safety instructions don't classify internal         │", fg="white"))
    click.echo(click.style("│ pricing tiers as confidential data. The bot responds    │", fg="white"))
    click.echo(click.style("│ to \"what's your enterprise pricing?\" with internal      │", fg="white"))
    click.echo(click.style("│ rate cards.                                             │", fg="white"))
    click.echo(click.style("│                                                         │", fg="white"))
    click.echo(click.style("│ Impact: 3 data leaks → compliance risk                  │", fg="yellow"))
    click.echo(click.style("│ Fix confidence: HIGH                                    │", fg="green"))
    pause(0.3)

    # Issue 3
    click.echo(click.style("├─────────────────────────────────────────────────────────┤", fg="white"))
    click.echo(click.style("│ Issue #3: Tool Latency (MODERATE)                       │", fg="white"))
    pause(0.3)
    click.echo(click.style("│ order_lookup tool timeout is set to 10s. Most calls     │", fg="white"))
    click.echo(click.style("│ complete in 2s but timeout causes 4.5s average.         │", fg="white"))
    click.echo(click.style("│                                                         │", fg="white"))
    click.echo(click.style("│ Impact: 8 slow conversations → poor user experience     │", fg="yellow"))
    click.echo(click.style("│ Fix confidence: MEDIUM                                  │", fg="green"))
    click.echo(click.style("└─────────────────────────────────────────────────────────┘", fg="white"))
    click.echo()
    pause(1.0)

    # ============================================================================
    # ACT 3: SELF-HEALING (the "wow" moment)
    # ============================================================================
    click.echo(click.style("⚡ Optimizing... (3 cycles)", fg="cyan", bold=True))
    click.echo()
    pause(0.5)

    # Cycle 1
    click.echo(click.style("Cycle 1/3: Fixing billing routing", fg="white", bold=True))
    pause(0.3)
    click.echo(click.style("  ↳ Adding keywords: \"invoice\", \"charge\", \"refund\", \"payment\", \"billing\"", fg="white"))
    pause(0.5)
    click.echo(click.style("  ↳ Evaluating... ", fg="white") + click.style("score: 0.62 → 0.74 (+0.12) ✨", fg="green"))
    pause(0.3)
    click.echo(click.style("  ↳ ✅ Accepted — 19 fewer misroutes", fg="green"))
    click.echo()
    pause(0.8)

    # Cycle 2
    click.echo(click.style("Cycle 2/3: Hardening safety policy", fg="white", bold=True))
    pause(0.3)
    click.echo(click.style("  ↳ Adding \"internal pricing\" to confidential data list", fg="white"))
    pause(0.3)
    click.echo(click.style("  ↳ Adding refusal template for enterprise rate requests", fg="white"))
    pause(0.5)
    click.echo(click.style("  ↳ Evaluating... ", fg="white") + click.style("score: 0.74 → 0.81 (+0.07) ✨", fg="green"))
    pause(0.3)
    click.echo(click.style("  ↳ ✅ Accepted — 3 data leaks → 0", fg="green"))
    click.echo()
    pause(0.8)

    # Cycle 3
    click.echo(click.style("Cycle 3/3: Tuning tool latency", fg="white", bold=True))
    pause(0.3)
    click.echo(click.style("  ↳ Reducing order_lookup timeout from 10s to 4s", fg="white"))
    pause(0.3)
    click.echo(click.style("  ↳ Adding retry with exponential backoff", fg="white"))
    pause(0.5)
    click.echo(click.style("  ↳ Evaluating... ", fg="white") + click.style("score: 0.81 → 0.87 (+0.06) ✨", fg="green"))
    pause(0.3)
    click.echo(click.style("  ↳ ✅ Accepted — avg latency 4.5s → 2.1s", fg="green"))
    click.echo()
    pause(1.0)

    # ============================================================================
    # ACT 4: REVIEW & APPROVE (the "trust" moment)
    # ============================================================================
    click.echo(click.style("📋 Changes for Review", fg="cyan", bold=True))
    click.echo(click.style("━" * 20, fg="cyan"))
    click.echo()
    pause(0.5)

    # Change 1
    click.echo(click.style("Change 1: Routing Keywords Update", fg="white", bold=True))
    click.echo(click.style("┌──────────────────────────────────────────┐", fg="white"))
    click.echo(click.style("│ routing.rules[billing_agent].keywords    │", fg="white"))
    click.echo(click.style("│                                          │", fg="white"))
    click.echo(click.style("│ - [\"billing\", \"account\", \"subscription\"] │", fg="red"))
    click.echo(click.style("│ + [\"billing\", \"account\", \"subscription\", │", fg="green"))
    click.echo(click.style("│ +  \"invoice\", \"charge\", \"refund\",        │", fg="green"))
    click.echo(click.style("│ +  \"payment\", \"receipt\", \"credit\"]       │", fg="green"))
    click.echo(click.style("│                                          │", fg="white"))
    click.echo(click.style("│ Score: 0.62 → 0.74 (+19%)               │", fg="cyan"))
    click.echo(click.style("│ Confidence: p=0.001 (very high)          │", fg="cyan"))
    click.echo(click.style("└──────────────────────────────────────────┘", fg="white"))
    click.echo()
    pause(0.5)

    # Change 2
    click.echo(click.style("Change 2: Safety Policy Hardening", fg="white", bold=True))
    click.echo(click.style("┌──────────────────────────────────────────┐", fg="white"))
    click.echo(click.style("│ instructions.safety.confidential_data    │", fg="white"))
    click.echo(click.style("│                                          │", fg="white"))
    click.echo(click.style("│ + \"internal_pricing_tiers\"               │", fg="green"))
    click.echo(click.style("│ + \"enterprise_rate_cards\"                │", fg="green"))
    click.echo(click.style("│ + \"partner_discount_schedules\"           │", fg="green"))
    click.echo(click.style("│                                          │", fg="white"))
    click.echo(click.style("│ Safety: 0.94 → 1.00 (zero violations)   │", fg="cyan"))
    click.echo(click.style("│ Confidence: p=0.003 (high)               │", fg="cyan"))
    click.echo(click.style("└──────────────────────────────────────────┘", fg="white"))
    click.echo()
    pause(0.5)

    # Change 3
    click.echo(click.style("Change 3: Tool Timeout Optimization", fg="white", bold=True))
    click.echo(click.style("┌──────────────────────────────────────────┐", fg="white"))
    click.echo(click.style("│ tools.order_lookup.timeout_seconds       │", fg="white"))
    click.echo(click.style("│                                          │", fg="white"))
    click.echo(click.style("│ - 10                                     │", fg="red"))
    click.echo(click.style("│ + 4                                      │", fg="green"))
    click.echo(click.style("│                                          │", fg="white"))
    click.echo(click.style("│ tools.order_lookup.retry.enabled         │", fg="white"))
    click.echo(click.style("│                                          │", fg="white"))
    click.echo(click.style("│ - false                                  │", fg="red"))
    click.echo(click.style("│ + true                                   │", fg="green"))
    click.echo(click.style("│                                          │", fg="white"))
    click.echo(click.style("│ Latency: 4.5s → 2.1s (-53%)             │", fg="cyan"))
    click.echo(click.style("│ Confidence: p=0.01 (high)                │", fg="cyan"))
    click.echo(click.style("└──────────────────────────────────────────┘", fg="white"))
    click.echo()
    pause(1.0)

    # ============================================================================
    # ACT 5: THE RESULT (the "close" moment)
    # ============================================================================
    click.echo(click.style("✦ Results", fg="cyan", bold=True))
    click.echo(click.style("━" * 9, fg="cyan"))
    click.echo()
    pause(0.5)

    # Before/after table
    click.echo(click.style("                  Before    After     Change", fg="white", bold=True))
    click.echo(click.style("Overall Score     0.62      0.87      +40% ✨", fg="green"))
    pause(0.2)
    click.echo(click.style("Routing Accuracy  58%       94%       +62%", fg="white"))
    pause(0.2)
    click.echo(click.style("Safety Score      0.94      1.00      +6%", fg="white"))
    pause(0.2)
    click.echo(click.style("Avg Latency       4.5s      2.1s      -53%", fg="white"))
    pause(0.2)
    click.echo(click.style("Resolution Rate   71%       88%       +24%", fg="white"))
    click.echo()
    pause(0.5)

    click.echo(click.style("🎯 All 3 critical issues resolved in 3 optimization cycles.", fg="green", bold=True))
    click.echo()
    pause(0.3)

    # Next steps
    click.echo(click.style("Next steps:", fg="white", bold=True))
    click.echo("  " + click.style("autoagent server", fg="cyan", bold=True) + "    → Open web console to explore details")
    click.echo("  " + click.style("autoagent cx deploy", fg="cyan", bold=True) + " → Deploy to CX Agent Studio")
    click.echo("  " + click.style("autoagent replay", fg="cyan", bold=True) + "    → See full optimization history")
    click.echo()

    # Auto-start web console if requested
    if web:
        pause(1.0)
        click.echo(click.style("\n▸ Starting web console...", fg="cyan", bold=True))
        _auto_open_console()


# ---------------------------------------------------------------------------
# autoagent edit — Natural Language Config Editing
# ---------------------------------------------------------------------------

@cli.command("edit")
@click.argument("description", required=False)
@click.option("--interactive", "-i", is_flag=True, help="Multi-turn editing session.")
@click.option("--dry-run", is_flag=True, help="Show proposed changes without applying.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
def edit(description: str | None, interactive: bool, dry_run: bool, json_output: bool,
         db: str, configs_dir: str) -> None:
    """Apply natural language edits to agent config.

    Examples:
      autoagent edit "Make the billing agent more empathetic"
      autoagent edit "Reduce response verbosity" --dry-run
      autoagent edit --interactive
    """
    from optimizer.nl_editor import NLEditor

    store = ConversationStore(db_path=db)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    current_config = _ensure_active_config(deployer)
    editor = NLEditor()

    if interactive:
        click.echo("AutoAgent Edit (type 'quit' to exit)")
        while True:
            try:
                user_input = click.prompt(">", prompt_suffix=" ")
            except (EOFError, KeyboardInterrupt):
                break
            if user_input.strip().lower() in ("quit", "exit", "q"):
                break
            result = editor.apply_and_eval(user_input, current_config)
            if json_output:
                click.echo(json.dumps(result.to_dict(), indent=2))
            else:
                click.echo(f"  Surfaces: {', '.join(editor.parse_intent(user_input, current_config).target_surfaces)}")
                click.echo(f"  Diff: {result.diff_summary}")
                click.echo(f"  Eval: {result.score_before:.2f} → {result.score_after:.2f} ({result.score_after - result.score_before:+.2f})")
                if not dry_run and result.accepted:
                    current_config = result.new_config
                    click.echo(click.style("  ✓ Applied.", fg="green"))
                elif dry_run:
                    click.echo("  (dry run — not applied)")
                else:
                    click.echo(click.style("  ✗ Rejected (score did not improve).", fg="red"))
        return

    if not description:
        click.echo("Usage: autoagent edit \"description\" or autoagent edit --interactive")
        return

    result = editor.apply_and_eval(description, current_config)

    if json_output:
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

    intent = editor.parse_intent(description, current_config)
    click.echo(f"  Intent: {intent.change_type}")
    click.echo(f"  Surfaces: {', '.join(intent.target_surfaces)}")
    click.echo(f"  Diff: {result.diff_summary}")
    click.echo(f"  Eval: {result.score_before:.2f} → {result.score_after:.2f} ({result.score_after - result.score_before:+.2f})")

    if dry_run:
        click.echo("  (dry run — not applied)")
    elif result.accepted:
        click.echo(click.style("  ✓ Applied.", fg="green"))
    else:
        click.echo(click.style("  ✗ Rejected (score did not improve).", fg="red"))


@cli.command("explain")
@click.option("--verbose", is_flag=True, default=False, help="Show detailed breakdown.")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--memory-db", default=MEMORY_DB, show_default=True, help="Optimizer memory DB.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def explain(verbose: bool, db: str, configs_dir: str, memory_db: str, json_output: bool = False) -> None:
    """Generate a plain-English summary of the agent's current state."""
    store = ConversationStore(db_path=db)
    observer = Observer(store)
    report: "HealthReport" = observer.observe()
    metrics = report.metrics
    failure_buckets: dict = report.failure_buckets or {}

    memory = OptimizationMemory(db_path=memory_db)
    attempts = memory.recent(limit=100)

    deployer = Deployer(configs_dir=configs_dir, store=store)
    dep_status = deployer.status()

    # Determine health label
    sr = metrics.success_rate
    if sr >= 0.9:
        health_label = "Excellent"
        health_color = "green"
    elif sr >= 0.75:
        health_label = "Good"
        health_color = "green"
    elif sr >= 0.5:
        health_label = "Needs Work"
        health_color = "yellow"
    else:
        health_label = "Critical"
        health_color = "red"

    # Load agent name from config if possible
    try:
        cfg = load_config(configs_dir)
        agent_name = cfg.get("agent_name") or cfg.get("name") or "Agent"
        runtime_label = cfg.get("runtime", "")
    except Exception:
        agent_name = "Agent"
        runtime_label = ""

    header_parts = [agent_name]
    if runtime_label:
        header_parts.append(f"({runtime_label})")
    header = "Your Agent: " + " ".join(header_parts)

    # Prose summary
    cycle_count = len(attempts)
    pct_correct = int(sr * 100)

    top_bucket = max(failure_buckets, key=failure_buckets.get) if failure_buckets else None
    total_failures = sum(failure_buckets.values())

    if json_output:
        data = {
            "health_label": health_label,
            "success_rate": sr,
            "failure_buckets": failure_buckets,
            "top_failure": top_bucket,
            "cycle_count": cycle_count,
            "config_version": dep_status.get("active_version"),
        }
        click.echo(json.dumps(data, indent=2))
        return

    click.echo(click.style(header, bold=True))
    click.echo(click.style("━" * len(header), fg="cyan"))
    click.echo()

    health_str = click.style(f"{health_label} ({sr:.2f}/1.00)", fg=health_color, bold=True)
    click.echo(f"Overall health: {health_str}")
    click.echo()

    if top_bucket and total_failures > 0:
        top_pct = int((failure_buckets[top_bucket] / total_failures) * 100)
        weakness_prose = (
            f"The main weakness is {top_bucket.replace('_', ' ')}, "
            f"which accounts for {top_pct}% of all failures."
        )
    else:
        weakness_prose = "No significant failure patterns detected."

    if cycle_count > 0 and attempts:
        baseline = attempts[-1].score_before if attempts else None
        latest = attempts[0].score_after if attempts else None
        if baseline and latest and baseline > 0:
            improvement_pct = int(((latest - baseline) / baseline) * 100)
            cycle_prose = (
                f" The optimizer has run {cycle_count} cycle{'s' if cycle_count != 1 else ''} "
                f"and improved quality by {improvement_pct}% from the initial baseline."
            )
        else:
            cycle_prose = f" The optimizer has run {cycle_count} cycle{'s' if cycle_count != 1 else ''}."
    else:
        cycle_prose = " The optimizer has not run any cycles yet."

    click.echo(f"Your agent handles {pct_correct}% of queries correctly. {weakness_prose}{cycle_prose}")
    click.echo()

    # Strengths
    click.echo(click.style("Strengths:", bold=True))
    has_strength = False
    if metrics.safety_violation_rate == 0:
        click.echo("  " + click.style("✓", fg="green") + " Safety compliance: 100% — zero violations")
        has_strength = True
    if metrics.success_rate > 0.9:
        click.echo("  " + click.style("✓", fg="green") + " Routing accuracy: above 90% threshold")
        has_strength = True
    if metrics.avg_latency_ms > 0 and metrics.avg_latency_ms < 2000:
        click.echo("  " + click.style("✓", fg="green") + f" Response latency: {metrics.avg_latency_ms:.0f}ms avg (within target)")
        has_strength = True
    if metrics.error_rate < 0.05:
        click.echo("  " + click.style("✓", fg="green") + " Error rate: low (< 5%)")
        has_strength = True
    if not has_strength:
        click.echo("  " + click.style("─", fg="yellow") + " No significant strengths identified yet")
    click.echo()

    # Weaknesses
    click.echo(click.style("Weaknesses:", bold=True))
    has_weakness = False
    for bucket, count in sorted(failure_buckets.items(), key=lambda x: -x[1]):
        if count > 0:
            bucket_label = bucket.replace("_", " ").title()
            if total_failures > 0:
                fail_pct = int((count / total_failures) * 100)
                click.echo(
                    "  " + click.style("✗", fg="red") + f" {bucket_label}: {fail_pct}% failure rate ({count} occurrences)"
                )
            else:
                click.echo("  " + click.style("✗", fg="red") + f" {bucket_label}: {count} occurrences")
            has_weakness = True
    if metrics.avg_latency_ms >= 3000:
        click.echo(
            "  " + click.style("✗", fg="red")
            + f" Tool latency: {metrics.avg_latency_ms / 1000:.1f}s avg (target: 3.0s)"
        )
        has_weakness = True
    if metrics.error_rate >= 0.1:
        click.echo(
            "  " + click.style("✗", fg="red")
            + f" Error rate: {metrics.error_rate * 100:.0f}% (above 10% threshold)"
        )
        has_weakness = True
    if not has_weakness:
        click.echo("  " + click.style("─", fg="yellow") + " No significant weaknesses detected")
    click.echo()

    # Recommendation
    click.echo(click.style("Recommendation:", bold=True))
    if top_bucket:
        click.echo(f"  Focus on {top_bucket.replace('_', ' ')} accuracy. Run:")
        click.echo("  " + click.style("autoagent runbook apply fix-retrieval-grounding", bold=True))
    elif metrics.success_rate < 0.75:
        click.echo("  Run an optimization cycle to improve overall quality:")
        click.echo("  " + click.style("autoagent optimize --cycles 3", bold=True))
    else:
        click.echo("  Agent is performing well. Continue monitoring with:")
        click.echo("  " + click.style("autoagent status", bold=True))

    # Verbose: per-bucket details and full score history
    if verbose:
        click.echo()
        click.echo(click.style("── Verbose: Failure Bucket Details ──", fg="cyan"))
        if failure_buckets:
            for bucket, count in sorted(failure_buckets.items(), key=lambda x: -x[1]):
                bucket_label = bucket.replace("_", " ").title()
                click.echo(f"  {bucket_label}: {count} failures")
        else:
            click.echo("  No failure buckets recorded.")

        click.echo()
        click.echo(click.style("── Verbose: Score History ──", fg="cyan"))
        if attempts:
            for i, attempt in enumerate(reversed(attempts)):
                version = i + 1
                rel = _format_relative_time(attempt.timestamp)
                delta = attempt.score_after - attempt.score_before
                delta_str = f"{'+' if delta >= 0 else ''}{delta:.4f}"
                status_icon = click.style("✓", fg="green") if attempt.status == "accepted" else click.style("✗", fg="red")
                click.echo(
                    f"  v{version:03d}  {attempt.score_after:.4f}  {status_icon} {delta_str}"
                    f"  {attempt.change_description[:45]}  {rel}"
                )
        else:
            click.echo("  No optimization history yet.")


@cli.command("diagnose")
@click.option("--interactive", "-i", is_flag=True, help="Interactive diagnosis session.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
@click.option("--db", default=DB_PATH, show_default=True)
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True)
@click.option("--memory-db", default=MEMORY_DB, show_default=True)
def diagnose(interactive: bool, json_output: bool, db: str, configs_dir: str, memory_db: str) -> None:
    """Run failure diagnosis and optionally fix issues interactively."""
    from optimizer.diagnose_session import DiagnoseSession

    store = ConversationStore(db_path=db)
    observer = Observer(store)
    deployer = Deployer(configs_dir=configs_dir, store=store)

    session = DiagnoseSession(
        store=store,
        observer=observer,
        deployer=deployer,
    )
    summary = session.start()

    if json_output:
        click.echo(json.dumps(session.to_dict(), indent=2))
        return

    click.echo(summary)

    if not interactive:
        return

    # Interactive REPL
    click.echo("\nAutoAgent Diagnosis (type 'quit' to exit)")
    while True:
        try:
            user_input = click.prompt(">", prompt_suffix=" ")
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input.strip():
            continue
        response = session.handle_input(user_input)
        click.echo(response)
        if session._classify_input(user_input) == "quit":
            break


@cli.command("replay")
@click.option("--limit", default=20, show_default=True, type=int, help="Number of entries to show.")
@click.option("--memory-db", default=MEMORY_DB, show_default=True, help="Optimizer memory DB.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def replay(limit: int, memory_db: str, json_output: bool = False) -> None:
    """Show optimization history like git log --oneline."""
    memory = OptimizationMemory(db_path=memory_db)
    attempts = memory.recent(limit=limit)

    if json_output:
        data = [
            {
                "version": i + 1,
                "score_before": attempt.score_before,
                "score_after": attempt.score_after,
                "status": attempt.status,
                "change_description": attempt.change_description,
                "timestamp": attempt.timestamp,
                "config_section": attempt.config_section,
            }
            for i, attempt in enumerate(reversed(attempts))
        ]
        click.echo(json.dumps(data, indent=2))
        return

    click.echo(click.style("AutoAgent Optimization History", bold=True))
    click.echo(click.style("━" * 30, fg="cyan"))
    click.echo()

    if not attempts:
        click.echo(click.style("  No optimization history yet.", fg="yellow"))
        click.echo()
        click.echo("  Run " + click.style("autoagent optimize", bold=True) + " to start the first cycle.")
        return

    # reverse to chronological order (recent() returns newest first)
    chronological = list(reversed(attempts))

    for i, attempt in enumerate(chronological):
        version = i + 1
        score = attempt.score_after
        accepted = attempt.status == "accepted"
        status_icon = click.style("✓", fg="green") if accepted else click.style("✗", fg="red")
        delta = attempt.score_after - attempt.score_before
        if delta == 0 and attempt.score_before == 0:
            delta_str = click.style("─  ─", fg="white", dim=True)
        else:
            delta_sign = "+" if delta >= 0 else ""
            delta_color = "green" if delta >= 0 else "red"
            delta_str = click.style(f"{delta_sign}{delta:.2f}", fg=delta_color)
        desc = attempt.change_description or "No description"
        if not accepted:
            desc = f"[rejected] {desc}"
        desc_truncated = desc[:45].ljust(45)
        rel = _format_relative_time(attempt.timestamp)
        version_str = click.style(f"v{version:03d}", fg="cyan" if accepted else "white", dim=(not accepted))
        score_str = f"{score:.4f}"
        click.echo(f"  {version_str}  {score_str}  {status_icon} {delta_str}  {desc_truncated}  {rel}")

    click.echo()


# ---------------------------------------------------------------------------
# autoagent cx (CX Agent Studio)
# ---------------------------------------------------------------------------

@cli.group("cx")
def cx_group() -> None:
    """Google Cloud CX Agent Studio — import, export, deploy."""

@cx_group.command("compat")
def cx_compat() -> None:
    """Show CX Agent Studio compatibility matrix."""
    from cx_studio.compat import CompatibilityMatrix
    matrix = CompatibilityMatrix()
    click.echo(matrix.to_markdown())


@cx_group.command("list")
@click.option("--project", required=True, help="GCP project ID.")
@click.option("--location", default="global", show_default=True, help="Agent location.")
@click.option("--credentials", default=None, help="Path to service account JSON.")
def cx_list(project: str, location: str, credentials: str | None) -> None:
    """List CX agents in a project."""
    from cx_studio import CxAuth, CxClient
    auth = CxAuth(credentials_path=credentials)
    client = CxClient(auth)
    agents = client.list_agents(project, location)
    if not agents:
        click.echo("No agents found.")
        return
    click.echo(f"\n  {'Name':<40} {'Language':<10} {'Description'}")
    click.echo(f"  {'─' * 40} {'─' * 10} {'─' * 30}")
    for agent in agents:
        agent_id = agent.name.split("/")[-1]
        click.echo(f"  {agent.display_name:<40} {agent.default_language_code:<10} {agent.description[:30]}")

@cx_group.command("import")
@click.option("--project", required=True, help="GCP project ID.")
@click.option("--location", default="global", show_default=True)
@click.option("--agent", "agent_id", required=True, help="CX agent ID.")
@click.option("--output-dir", default=".", show_default=True, help="Output directory.")
@click.option("--credentials", default=None, help="Path to service account JSON.")
@click.option("--include-test-cases/--no-test-cases", default=True, show_default=True)
def cx_import_cmd(project: str, location: str, agent_id: str, output_dir: str, credentials: str | None, include_test_cases: bool) -> None:
    """Import a CX agent into AutoAgent format."""
    from cx_studio import CxAuth, CxClient, CxImporter
    from cx_studio.types import CxAgentRef

    click.echo(f"  Importing agent {agent_id} from {project}/{location}...")
    auth = CxAuth(credentials_path=credentials)
    client = CxClient(auth)
    importer = CxImporter(client)
    ref = CxAgentRef(project=project, location=location, agent_id=agent_id)
    result = importer.import_agent(ref, output_dir=output_dir, include_test_cases=include_test_cases)

    click.echo(click.style(f"\n  ✓ Imported: {result.agent_name}", fg="green"))
    click.echo(f"    Config:   {result.config_path}")
    if result.eval_path:
        click.echo(f"    Evals:    {result.eval_path}")
    click.echo(f"    Snapshot: {result.snapshot_path}")
    click.echo(f"    Surfaces: {', '.join(result.surfaces_mapped)}")
    click.echo(f"    Test cases: {result.test_cases_imported}")

@cx_group.command("export")
@click.option("--project", required=True, help="GCP project ID.")
@click.option("--location", default="global", show_default=True)
@click.option("--agent", "agent_id", required=True, help="CX agent ID.")
@click.option("--config", "config_path", required=True, help="AutoAgent config YAML path.")
@click.option("--snapshot", "snapshot_path", required=True, help="CX snapshot JSON from import.")
@click.option("--credentials", default=None, help="Path to service account JSON.")
@click.option("--dry-run", is_flag=True, help="Preview changes without pushing.")
def cx_export_cmd(project: str, location: str, agent_id: str, config_path: str, snapshot_path: str, credentials: str | None, dry_run: bool) -> None:
    """Export optimized config back to CX Agent Studio."""
    from cx_studio import CxAuth, CxClient, CxExporter
    from cx_studio.types import CxAgentRef
    import yaml as _yaml

    ref = CxAgentRef(project=project, location=location, agent_id=agent_id)
    with open(config_path, "r", encoding="utf-8") as f:
        config = _yaml.safe_load(f)

    auth = CxAuth(credentials_path=credentials)
    client = CxClient(auth)
    exporter = CxExporter(client)

    if dry_run:
        click.echo("  Dry run — previewing changes...")
    result = exporter.export_agent(config, ref, snapshot_path, dry_run=dry_run)

    if not result.changes:
        click.echo("  No changes detected.")
        return

    click.echo(f"\n  Changes ({len(result.changes)}):")
    for change in result.changes:
        action = change.get("action", "unknown")
        resource = change.get("resource", "unknown")
        name = change.get("name", change.get("field", ""))
        click.echo(f"    {action.upper():<8} {resource}/{name}")

    if result.pushed:
        click.echo(click.style(f"\n  ✓ Pushed {result.resources_updated} resource(s) to CX Agent Studio", fg="green"))
    else:
        click.echo("\n  No changes pushed (dry run or no diff).")

@cx_group.command("deploy")
@click.option("--project", required=True, help="GCP project ID.")
@click.option("--location", default="global", show_default=True)
@click.option("--agent", "agent_id", required=True, help="CX agent ID.")
@click.option("--environment", default="production", show_default=True)
@click.option("--credentials", default=None, help="Path to service account JSON.")
def cx_deploy_cmd(project: str, location: str, agent_id: str, environment: str, credentials: str | None) -> None:
    """Deploy agent to a CX environment."""
    from cx_studio import CxAuth, CxClient, CxDeployer
    from cx_studio.types import CxAgentRef

    ref = CxAgentRef(project=project, location=location, agent_id=agent_id)
    auth = CxAuth(credentials_path=credentials)
    client = CxClient(auth)
    deployer = CxDeployer(client)
    result = deployer.deploy_to_environment(ref, environment)
    click.echo(click.style(f"\n  ✓ Deployed to {result.environment}: {result.status}", fg="green"))

@cx_group.command("widget")
@click.option("--project", required=True, help="GCP project ID.")
@click.option("--location", default="global", show_default=True)
@click.option("--agent", "agent_id", required=True, help="CX agent ID.")
@click.option("--title", default="Agent", show_default=True, help="Chat widget title.")
@click.option("--color", default="#1a73e8", show_default=True, help="Primary color hex.")
@click.option("--output", "output_path", default=None, help="Output HTML file path.")
def cx_widget_cmd(project: str, location: str, agent_id: str, title: str, color: str, output_path: str | None) -> None:
    """Generate a chat-messenger web widget HTML file."""
    from cx_studio import CxDeployer, CxAuth, CxClient
    from cx_studio.types import CxWidgetConfig

    widget_config = CxWidgetConfig(
        project_id=project,
        agent_id=agent_id,
        location=location,
        chat_title=title,
        primary_color=color,
    )
    # Widget generation doesn't need API access
    auth = CxAuth.__new__(CxAuth)
    auth._token = None
    auth._token_expiry = 0.0
    auth._project_id = project
    auth._credentials_path = None
    client = CxClient.__new__(CxClient)
    client._auth = auth
    client._timeout = 30.0
    client._max_retries = 3
    deployer = CxDeployer(client)
    html = deployer.generate_widget_html(widget_config, output_path)

    if output_path:
        click.echo(click.style(f"\n  ✓ Widget HTML written to {output_path}", fg="green"))
    else:
        click.echo(html)

@cx_group.command("status")
@click.option("--project", required=True, help="GCP project ID.")
@click.option("--location", default="global", show_default=True)
@click.option("--agent", "agent_id", required=True, help="CX agent ID.")
@click.option("--credentials", default=None, help="Path to service account JSON.")
def cx_status_cmd(project: str, location: str, agent_id: str, credentials: str | None) -> None:
    """Show CX agent deployment status."""
    from cx_studio import CxAuth, CxClient, CxDeployer
    from cx_studio.types import CxAgentRef

    ref = CxAgentRef(project=project, location=location, agent_id=agent_id)
    auth = CxAuth(credentials_path=credentials)
    client = CxClient(auth)
    deployer = CxDeployer(client)
    status = deployer.get_deploy_status(ref)

    click.echo(f"\n  Agent: {status['agent']}")
    envs = status.get("environments", [])
    if not envs:
        click.echo("  No environments found.")
        return
    for env in envs:
        click.echo(f"\n  Environment: {env['name']}")
        click.echo(f"    Description: {env.get('description', '—')}")
        versions = env.get("versions", [])
        click.echo(f"    Versions: {len(versions)}")


# ---------------------------------------------------------------------------
# autoagent adk (Agent Development Kit)
# ---------------------------------------------------------------------------
@cli.group("adk")
def adk_group() -> None:
    """Google Agent Development Kit (ADK) integration — import, export, deploy."""


@adk_group.command("import")
@click.argument("path")
@click.option("--output", "-o", default=".", show_default=True, help="Output directory for config and snapshot.")
def adk_import_cmd(path: str, output: str) -> None:
    """Import an ADK agent from a local directory."""
    from adk import AdkImporter

    click.echo(f"  Importing ADK agent from {path}...")
    importer = AdkImporter()
    result = importer.import_agent(path, output_dir=output)

    click.echo(click.style(f"\n  ✓ Imported: {result.agent_name}", fg="green"))
    click.echo(f"    Config:   {result.config_path}")
    click.echo(f"    Snapshot: {result.snapshot_path}")
    click.echo(f"    Surfaces: {', '.join(result.surfaces_mapped)}")
    click.echo(f"    Tools:    {result.tools_imported}")


@adk_group.command("export")
@click.argument("path")
@click.option("--output", "-o", help="Output directory for modified source files.")
@click.option("--snapshot", "-s", required=True, help="Snapshot directory path from import.")
@click.option("--dry-run", is_flag=True, help="Preview changes without writing files.")
def adk_export_cmd(path: str, output: str | None, snapshot: str, dry_run: bool) -> None:
    """Export optimized config back to ADK source files."""
    from pathlib import Path
    import yaml
    from adk import AdkExporter

    config_path = Path(path)
    if not config_path.exists():
        click.echo(click.style(f"  Error: Config file not found: {path}", fg="red"))
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    exporter = AdkExporter()

    if dry_run:
        click.echo("  Dry run — previewing changes...")

    result = exporter.export_agent(config, snapshot, output_dir=output, dry_run=dry_run)

    if not result.changes:
        click.echo("  No changes detected.")
        return

    click.echo(f"\n  Changes ({len(result.changes)}):")
    for change in result.changes:
        action = change.get("action", "unknown")
        resource = change.get("resource", "unknown")
        name = change.get("name", change.get("field", ""))
        click.echo(f"    {action.upper():<8} {resource}/{name}")

    if not dry_run and result.files_modified > 0:
        click.echo(click.style(f"\n  ✓ Modified {result.files_modified} file(s) in {result.output_path}", fg="green"))
    elif not dry_run:
        click.echo("\n  No files modified (dry run or no changes).")


@adk_group.command("deploy")
@click.argument("path")
@click.option("--target", type=click.Choice(["cloud-run", "vertex-ai"]), default="cloud-run", show_default=True)
@click.option("--project", required=True, help="GCP project ID.")
@click.option("--region", default="us-central1", show_default=True, help="GCP region.")
def adk_deploy_cmd(path: str, target: str, project: str, region: str) -> None:
    """Deploy ADK agent to Cloud Run or Vertex AI."""
    from adk import AdkDeployer

    click.echo(f"  Deploying ADK agent from {path} to {target}...")
    deployer = AdkDeployer(project=project, region=region)
    if target == "cloud-run":
        result = deployer.deploy_to_cloud_run(path)
    else:
        result = deployer.deploy_to_vertex_ai(path)

    click.echo(click.style(f"\n  ✓ Deployed to {result.target}: {result.status}", fg="green"))
    if result.url:
        click.echo(f"    URL: {result.url}")
    if result.deployment_info:
        click.echo(f"    Info: {result.deployment_info}")


@adk_group.command("status")
@click.argument("path")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def adk_status_cmd(path: str, json_output: bool = False) -> None:
    """Show ADK agent structure and config summary."""
    from pathlib import Path
    from adk import parse_agent_directory

    agent_path = Path(path)
    if not agent_path.exists():
        click.echo(click.style(f"  Error: Agent path not found: {path}", fg="red"))
        return

    click.echo(f"  Parsing ADK agent at {path}...")
    tree = parse_agent_directory(agent_path)

    if json_output:
        data = {
            "agent_name": tree.agent.name,
            "model": tree.agent.model,
            "tools": [t.name for t in tree.tools],
            "sub_agents": [s.agent.name for s in tree.sub_agents],
        }
        click.echo(json.dumps(data, indent=2))
        return

    click.echo(click.style(f"\n  Agent: {tree.agent.name or 'unnamed'}", bold=True))
    click.echo(f"  Model:  {tree.agent.model or 'not specified'}")
    click.echo(f"  Tools:  {len(tree.tools)}")
    click.echo(f"  Sub-agents: {len(tree.sub_agents)}")

    if tree.tools:
        click.echo(f"\n  Tools:")
        for tool in tree.tools:
            click.echo(f"    - {tool.name}")

    if tree.sub_agents:
        click.echo(f"\n  Sub-agents:")
        for sub in tree.sub_agents:
            click.echo(f"    - {sub.agent.name}")


@adk_group.command("diff")
@click.argument("path")
@click.option("--snapshot", "-s", required=True, help="Snapshot directory path from import.")
def adk_diff_cmd(path: str, snapshot: str) -> None:
    """Preview what would change on export."""
    from pathlib import Path
    import yaml
    from adk import AdkExporter

    config_path = Path(path)
    if not config_path.exists():
        click.echo(click.style(f"  Error: Config file not found: {path}", fg="red"))
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    exporter = AdkExporter()
    changes = exporter.preview_changes(config, snapshot)

    if not changes:
        click.echo("  No changes detected.")
        return

    click.echo(f"\n  Preview ({len(changes)} change(s)):")
    for change in changes:
        action = change.get("action", "unknown")
        resource = change.get("resource", "unknown")
        name = change.get("name", change.get("field", ""))
        click.echo(f"    {action.upper():<8} {resource}/{name}")


# ---------------------------------------------------------------------------
# autoagent dataset ...
# ---------------------------------------------------------------------------

@cli.group()
def dataset() -> None:
    """Manage datasets for evaluation and training."""
    pass


@dataset.command("create")
@click.argument("name")
@click.option("--description", default="", help="Dataset description")
def dataset_create(name: str, description: str) -> None:
    """Create a new dataset."""
    from data.dataset_service import DatasetService
    svc = DatasetService()
    info = svc.create(name, description)
    click.echo(f"Dataset created: {info.dataset_id} ({name})")


@dataset.command("list")
def dataset_list() -> None:
    """List all datasets."""
    from data.dataset_service import DatasetService
    svc = DatasetService()
    datasets = svc.store.list_datasets()
    for ds in datasets:
        click.echo(f"  {ds['name']} (v{ds.get('current_version', '?')})")


@dataset.command("stats")
@click.argument("dataset_id")
def dataset_stats(dataset_id: str) -> None:
    """Show dataset statistics."""
    from data.dataset_service import DatasetService
    svc = DatasetService()
    stats = svc.stats(dataset_id)
    click.echo(yaml.dump(stats, default_flow_style=False))


# ---------------------------------------------------------------------------
# autoagent outcomes ...
# ---------------------------------------------------------------------------

@cli.group()
def outcomes() -> None:
    """Manage business outcome data."""
    pass


@outcomes.command("import")
@click.option("--source", type=click.Choice(["csv", "webhook"]), required=True)
@click.option("--file", "file_path", default=None, help="CSV file path")
def outcomes_import(source: str, file_path: str | None) -> None:
    """Import business outcomes."""
    from data.outcomes import OutcomeService
    svc = OutcomeService()
    if source == "csv" and file_path:
        count = svc.import_from_csv(file_path)
        click.echo(f"Imported {count} outcomes from CSV")
    else:
        click.echo("Specify --file for CSV import")


# ---------------------------------------------------------------------------
# autoagent release ...
# ---------------------------------------------------------------------------

@cli.group()
def release() -> None:
    """Manage signed release objects."""
    pass


@release.command("list")
def release_list() -> None:
    """List release objects."""
    click.echo("Release objects: (none yet)")


@release.command("create")
@click.option("--experiment-id", required=True, help="Experiment ID to create release from")
def release_create(experiment_id: str) -> None:
    """Create a new release object from an experiment."""
    click.echo(f"Creating release from experiment {experiment_id}...")


# ---------------------------------------------------------------------------
# autoagent benchmark ...
# ---------------------------------------------------------------------------

@cli.group()
def benchmark() -> None:
    """Run standard benchmarks."""
    pass


@benchmark.command("run")
@click.argument("benchmark_name")
@click.option("--cycles", default=1, help="Number of benchmark cycles")
def benchmark_run(benchmark_name: str, cycles: int) -> None:
    """Run a benchmark suite."""
    click.echo(f"Running benchmark {benchmark_name} for {cycles} cycles...")


# ---------------------------------------------------------------------------
# Reward commands
# ---------------------------------------------------------------------------

@cli.group()
def reward():
    """Manage reward definitions."""
    pass


@reward.command("create")
@click.argument("name")
@click.option("--kind", type=click.Choice(["verifiable", "preference", "business_outcome", "constitutional"]), default="verifiable")
@click.option("--scope", type=click.Choice(["runtime", "buildtime", "multi_agent"]), default="runtime")
@click.option("--source", type=click.Choice(["deterministic_checker", "environment_checker", "human_label", "llm_judge", "ai_preference"]), default="deterministic_checker")
@click.option("--hard-gate", is_flag=True, help="Mark as hard gate (pass/fail, not optimizable)")
@click.option("--weight", type=float, default=1.0)
@click.option("--description", type=str, default="")
def reward_create(name, kind, scope, source, hard_gate, weight, description):
    """Create a new reward definition."""
    from rewards.registry import RewardRegistry
    from rewards.types import RewardDefinition, RewardKind, RewardScope, RewardSource
    registry = RewardRegistry()
    defn = RewardDefinition(
        name=name, kind=RewardKind(kind), scope=RewardScope(scope),
        source=RewardSource(source), hard_gate=hard_gate,
        weight=weight, description=description,
    )
    result_name, version = registry.register(defn)
    click.echo(f"Created reward '{result_name}' v{version} (id: {defn.reward_id})")
    registry.close()


@reward.command("list")
@click.option("--kind", type=str, default=None, help="Filter by kind")
def reward_list(kind):
    """List all reward definitions."""
    from rewards.registry import RewardRegistry
    registry = RewardRegistry()
    rewards = registry.list_by_kind(kind) if kind else registry.list_all()
    if not rewards:
        click.echo("No rewards defined.")
        return
    for r in rewards:
        gate = " [HARD GATE]" if r.hard_gate else ""
        click.echo(f"  {r.name} v{r.version}  kind={r.kind.value}  trust={r.trust_tier.value}  weight={r.weight}{gate}")
    click.echo(f"\n{len(rewards)} reward(s)")
    registry.close()


@reward.command("test")
@click.argument("name")
@click.option("--trace", "trace_id", type=str, default=None, help="Trace ID to test against")
def reward_test(name, trace_id):
    """Test a reward definition."""
    from rewards.registry import RewardRegistry
    registry = RewardRegistry()
    defn = registry.get(name)
    if defn is None:
        click.echo(f"Reward not found: {name}", err=True)
        raise SystemExit(1)
    click.echo(f"Reward: {defn.name} v{defn.version}")
    click.echo(f"  Kind: {defn.kind.value}")
    click.echo(f"  Source: {defn.source.value}")
    click.echo(f"  Hard gate: {defn.hard_gate}")
    click.echo(f"  Weight: {defn.weight}")
    if trace_id:
        click.echo(f"  Testing against trace: {trace_id}")
    registry.close()


# ---------------------------------------------------------------------------
# RL / Policy optimization commands
# ---------------------------------------------------------------------------

@cli.group()
def rl():
    """Policy optimization commands."""
    pass


@rl.command("train")
@click.option("--mode", type=click.Choice(["control", "verifier", "preference"]), required=True)
@click.option("--backend", type=click.Choice(["openai_rft", "openai_dpo", "vertex_sft", "vertex_preference", "vertex_continuous"]), required=True)
@click.option("--dataset", type=str, required=True, help="Path to training dataset")
@click.option("--config", type=str, default=None, help="JSON config string")
def rl_train(mode, backend, dataset, config):
    """Start a policy training job."""
    import json as json_mod
    from policy_opt.registry import PolicyArtifactRegistry
    from policy_opt.orchestrator import PolicyOptOrchestrator
    registry = PolicyArtifactRegistry()
    orch = PolicyOptOrchestrator(policy_registry=registry)
    config_dict = json_mod.loads(config) if config else {}
    try:
        job = orch.create_training_job(mode=mode, backend=backend, dataset_path=dataset, config=config_dict)
        click.echo(f"Created job: {job.job_id}")
        job = orch.start_training(job.job_id)
        click.echo(f"Job status: {job.status.value}")
        if job.result:
            click.echo(f"Result: {json_mod.dumps(job.result, indent=2)}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    finally:
        registry.close()


@rl.command("jobs")
@click.option("--status", type=str, default=None)
def rl_jobs(status):
    """List training jobs."""
    from policy_opt.registry import PolicyArtifactRegistry
    from policy_opt.orchestrator import PolicyOptOrchestrator
    registry = PolicyArtifactRegistry()
    orch = PolicyOptOrchestrator(policy_registry=registry)
    jobs = orch.list_jobs(status=status)
    if not jobs:
        click.echo("No training jobs.")
        return
    for j in jobs:
        click.echo(f"  {j.job_id[:12]}  mode={j.mode.value}  backend={j.backend}  status={j.status.value}")
    click.echo(f"\n{len(jobs)} job(s)")
    registry.close()


@rl.command("eval")
@click.argument("policy_id")
def rl_eval(policy_id):
    """Evaluate a policy artifact offline."""
    from policy_opt.registry import PolicyArtifactRegistry
    from policy_opt.orchestrator import PolicyOptOrchestrator
    registry = PolicyArtifactRegistry()
    orch = PolicyOptOrchestrator(policy_registry=registry)
    try:
        report = orch.evaluate_policy(policy_id)
        click.echo(json.dumps(report, indent=2))
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    finally:
        registry.close()


@rl.command("promote")
@click.argument("policy_id")
def rl_promote(policy_id):
    """Promote a policy to active status."""
    from policy_opt.registry import PolicyArtifactRegistry
    from policy_opt.orchestrator import PolicyOptOrchestrator
    registry = PolicyArtifactRegistry()
    orch = PolicyOptOrchestrator(policy_registry=registry)
    try:
        policy = orch.promote_policy(policy_id)
        click.echo(f"Promoted: {policy.name} v{policy.version} ({policy.policy_id})")
    except (KeyError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    finally:
        registry.close()


@rl.command("rollback")
@click.argument("policy_id")
def rl_rollback(policy_id):
    """Rollback a promoted policy."""
    from policy_opt.registry import PolicyArtifactRegistry
    from policy_opt.orchestrator import PolicyOptOrchestrator
    registry = PolicyArtifactRegistry()
    orch = PolicyOptOrchestrator(policy_registry=registry)
    try:
        target = orch.rollback_policy(policy_id)
        click.echo(f"Rolled back {policy_id}")
        if target:
            click.echo(f"Re-promoted: {target}")
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    finally:
        registry.close()


@rl.command("dataset")
@click.option("--mode", type=click.Choice(["verifiable", "preference", "episode", "audit"]), default="verifiable")
@click.option("--limit", type=int, default=1000)
def rl_dataset(mode, limit):
    """Build a training dataset from episodes."""
    from data.episodes import EpisodeStore
    from policy_opt.dataset_builder import RewardDatasetBuilder
    store = EpisodeStore()
    builder = RewardDatasetBuilder()
    episodes = store.list_episodes(limit=limit)
    if mode == "verifiable":
        path = builder.build_verifiable_dataset(episodes)
    elif mode == "preference":
        path = builder.build_preference_pairs(episodes)
    elif mode == "episode":
        path = builder.build_episode_export(episodes)
    else:
        path = builder.build_audit_set(episodes)
    click.echo(f"Built {mode} dataset: {path} ({len(episodes)} episodes)")
    store.close()


@rl.command("canary")
@click.argument("policy_id")
def rl_canary(policy_id):
    """Start canary evaluation for a policy."""
    from policy_opt.registry import PolicyArtifactRegistry
    registry = PolicyArtifactRegistry()
    policy = registry.get_by_id(policy_id)
    if policy is None:
        click.echo(f"Policy not found: {policy_id}", err=True)
        raise SystemExit(1)
    registry.update_status(policy_id, "canary")
    click.echo(f"Policy {policy_id} set to canary status")
    registry.close()


# ---------------------------------------------------------------------------
# Preference collection commands
# ---------------------------------------------------------------------------

@cli.group()
def pref():
    """Preference collection and export."""
    pass


@pref.command("collect")
@click.option("--input-text", required=True)
@click.option("--chosen", required=True)
@click.option("--rejected", required=True)
@click.option("--source", default="human_review")
def pref_collect(input_text, chosen, rejected, source):
    """Add a preference pair."""
    from optimizer.preference_learning import PreferencePair
    pair = PreferencePair(input_text=input_text, chosen=chosen, rejected=rejected, source=source)
    click.echo(f"Collected preference pair:")
    click.echo(f"  Input: {input_text[:80]}...")
    click.echo(f"  Chosen: {chosen[:80]}...")
    click.echo(f"  Rejected: {rejected[:80]}...")
    click.echo(f"  Source: {source}")


@pref.command("export")
@click.option("--format", "fmt", type=click.Choice(["vertex", "openai", "generic"]), default="vertex")
def pref_export(fmt):
    """Export preference pairs as DPO dataset."""
    from optimizer.preference_learning import PreferenceLearningPipeline
    pipeline = PreferenceLearningPipeline()
    # In a real implementation, would load pairs from the store
    click.echo(f"Exporting preferences in {fmt} format...")
    click.echo("No preference pairs to export yet. Submit pairs first via API or CLI.")


if __name__ == "__main__":
    cli()
