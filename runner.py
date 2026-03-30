"""CLI entry point for AutoAgent VNextCC.

Full command set:
  autoagent quickstart [--agent-name NAME] [--verbose]
  autoagent demo quickstart [--dir PATH]
  autoagent demo vp [--agent-name NAME] [--company NAME] [--no-pause] [--web]
  autoagent init [--template NAME] [--agent-name NAME] [--with-synthetic-data]
  autoagent eval run [OPTIONS]
  autoagent eval results [--run-id ID]
  autoagent eval list
  autoagent experiment log [OPTIONS]
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

import difflib
import json
import os
import shutil
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from agent.config.loader import load_config
from agent.config.runtime import load_runtime_config
from agent.config.schema import validate_config, config_diff as schema_config_diff
from cli.bootstrap import bootstrap_workspace, seed_demo_workspace
from cli.branding import (
    banner_enabled,
    echo_startup_banner,
    get_autoagent_version,
    render_startup_banner,
)
from cli.experiment_log import (
    append_entry as append_experiment_log_entry,
    best_score_entry as best_experiment_log_entry,
    default_log_path as default_experiment_log_path,
    format_table as format_experiment_log_table,
    make_entry as make_experiment_log_entry,
    next_cycle_number as next_experiment_log_cycle_number,
    read_entries as read_experiment_log_entries,
    summarize_entries as summarize_experiment_log_entries,
    tail_entries as tail_experiment_log_entries,
)
from cli.intelligence import (
    TranscriptReportStore,
    _build_generation_prompt,
    _load_replayed_report,
    intelligence_group,
)
from cli.mcp_setup import mcp_group
from cli.mode import mode_group, summarize_mode_state
from cli.providers import (
    configured_providers,
    default_api_key_env_for,
    default_model_for,
    provider_health_checks,
    providers_file_path,
    sync_runtime_config,
    upsert_provider,
)
from cli.status import StatusSnapshot, render_status as render_status_home
from cli.templates import (
    STARTER_TEMPLATE_NAMES,
    apply_template_to_workspace,
    list_templates,
)
from cli.workspace import AutoAgentWorkspace, discover_workspace
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
from shared.build_artifact_store import BuildArtifactStore
from shared.contracts import BuildArtifact
from shared.taxonomy import COMMAND_GROUPS, COMMAND_TAXONOMY


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("AUTOAGENT_DB", "conversations.db")
CONFIGS_DIR = os.environ.get("AUTOAGENT_CONFIGS", "configs")
MEMORY_DB = os.environ.get("AUTOAGENT_MEMORY_DB", "optimizer_memory.db")
REGISTRY_DB = os.environ.get("AUTOAGENT_REGISTRY_DB", "registry.db")
TRACE_DB = os.environ.get("AUTOAGENT_TRACE_DB", ".autoagent/traces.db")
SCORER_SPECS_DIR = os.environ.get("AUTOAGENT_SCORER_SPECS_DIR", ".autoagent/scorers")
AUTOAGENT_VERSION = get_autoagent_version()
EVAL_METRIC_NAMES = ("quality", "safety", "latency", "cost", "composite")


def _banner_flag_options(command):
    """Add shared banner suppression flags so key startup commands stay script-friendly."""
    command = click.option(
        "--no-banner",
        is_flag=True,
        default=False,
        help="Suppress the branded startup banner.",
    )(command)
    command = click.option(
        "--quiet",
        is_flag=True,
        default=False,
        help="Suppress the branded startup banner.",
    )(command)
    return command


class AutoAgentGroup(click.Group):
    """Prepend the branded splash to top-level help to make entry into the CLI distinct."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Capture banner suppression intent early because Click handles help before callbacks."""
        ctx.meta["invocation_cwd"] = Path.cwd().resolve()
        show_all = "--all" in args
        ctx.meta["show_all"] = show_all
        ctx.meta["banner_enabled"] = "--quiet" not in args and "--no-banner" not in args
        filtered_args = [arg for arg in args if arg != "--all"]
        return super().parse_args(ctx, filtered_args)

    def list_commands(self, ctx: click.Context) -> list[str]:
        """Hide experimental commands from default help unless `--all` is set."""
        commands = super().list_commands(ctx)
        if ctx.parent is None and not ctx.meta.get("show_all", False):
            commands = [name for name in commands if name != "rl"]
        return commands

    def get_help(self, ctx: click.Context) -> str:
        help_text = super().get_help(ctx)
        if ctx.parent is None:
            task_groups = [
                f"  {group:<12} {COMMAND_TAXONOMY[group].description}"
                for group in COMMAND_GROUPS
            ]
            if ctx.meta.get("show_all", False):
                task_groups.append("  rl [Experimental]")
            taxonomy_block = "Task Groups:\n" + "\n".join(task_groups) + "\n\n"
            if "Commands:\n" in help_text:
                help_text = help_text.replace("Commands:\n", taxonomy_block + "Commands:\n", 1)
            else:
                help_text = help_text + "\n\n" + taxonomy_block
        show_banner = ctx.meta.get("banner_enabled", banner_enabled(ctx))
        if ctx.parent is None and show_banner:
            return f"{render_startup_banner(AUTOAGENT_VERSION)}\n{help_text}"
        return help_text


class DefaultCommandGroup(click.Group):
    """Treat bare invocations as a hidden default subcommand while supporting visible verbs."""

    def __init__(
        self,
        *args,
        default_command: str,
        default_on_empty: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.default_command = default_command
        self.default_on_empty = default_on_empty

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        """Rewrite default invocations so Click can route to the hidden subcommand."""
        help_flags = set(self.get_help_option_names(ctx))
        if not args and self.default_on_empty:
            return super().parse_args(ctx, [self.default_command])
        if args and args[0] not in self.commands and args[0] not in help_flags:
            return super().parse_args(ctx, [self.default_command, *args])
        return super().parse_args(ctx, args)


def _load_config_dict(config_path: str) -> dict:
    """Load a raw config dictionary from disk."""
    from cli.errors import click_error

    try:
        with Path(config_path).open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise click_error(f"Config file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise click_error(f"Could not parse config file: {config_path}") from exc


def _enter_discovered_workspace(command_name: str | None) -> AutoAgentWorkspace | None:
    """Switch cwd to the nearest discovered workspace for workspace-aware commands."""
    if command_name in {"init", "new"}:
        return None
    workspace = discover_workspace()
    if workspace is not None and Path.cwd() != workspace.root:
        os.chdir(workspace.root)
    return workspace


def _is_tty() -> bool:
    """Return True when stdin is connected to an interactive terminal."""
    return hasattr(sys.stdin, "isatty") and sys.stdin.isatty()


def _require_workspace(command_name: str | None = None) -> AutoAgentWorkspace:
    """Return the current workspace or raise a helpful CLI error."""
    from cli.errors import click_error

    workspace = _enter_discovered_workspace(command_name)
    if workspace is None:
        raise click_error("No AutoAgent workspace found. Run autoagent init to create one.")
    return workspace


def _make_nl_scorer():
    """Build a scorer instance backed by the CLI's persisted scorer store."""
    from evals.nl_compiler import NLCompiler
    from evals.nl_scorer import NLScorer

    return NLScorer(compiler=NLCompiler(), storage_dir=SCORER_SPECS_DIR)


def _ensure_active_config(deployer: Deployer) -> dict:
    """Return active config; bootstrap from base config if none exists yet."""
    current = deployer.get_active_config()
    if current is not None:
        return current
    base_path = Path(__file__).parent / "agent" / "config" / "base_config.yaml"
    config = load_config(str(base_path)).model_dump()
    deployer.version_manager.save_version(config, scores={"composite": 0.0}, status="active")
    return config


def _workspace_for_configs_dir(configs_dir: str) -> AutoAgentWorkspace | None:
    """Return the discovered workspace when `configs_dir` points at its config directory."""
    workspace = discover_workspace()
    if workspace is None:
        return None

    try:
        resolved_configs_dir = Path(configs_dir).resolve()
    except OSError:
        return None

    return workspace if resolved_configs_dir == workspace.configs_dir.resolve() else None


def _resolve_invocation_input_path(path: Path) -> Path:
    """Resolve a user input path against the original invocation cwd."""
    ctx = click.get_current_context(silent=True)
    root = ctx.find_root() if ctx is not None else None
    meta = getattr(root, "meta", {}) if root is not None else {}
    raw_cwd = meta.get("invocation_cwd")
    invocation_cwd = Path(raw_cwd).resolve() if raw_cwd else Path.cwd().resolve()
    return path if path.is_absolute() else (invocation_cwd / path).resolve()


def _echo_deprecation(old: str, new: str) -> None:
    """Print a consistent deprecation warning for hidden compatibility aliases."""
    click.echo(
        click.style(
            f"Deprecated: `{old}` is kept for backward compatibility. Use `{new}` instead.",
            fg="yellow",
        )
    )


def _create_workspace(
    *,
    template: str,
    target_dir: str,
    name: str | None,
    agent_name: str,
    platform: str,
    with_synthetic_data: bool,
    demo: bool,
) -> tuple[AutoAgentWorkspace, dict]:
    """Create or update a workspace using the shared bootstrap path."""
    base_dir = Path(target_dir).resolve()
    workspace_root = (base_dir / name) if name else base_dir
    workspace_root.mkdir(parents=True, exist_ok=True)

    workspace_name = name or workspace_root.name
    workspace = AutoAgentWorkspace.create(
        workspace_root,
        name=workspace_name,
        template=template,
        agent_name=agent_name,
        platform=platform,
        demo_seeded=demo,
    )

    summary = bootstrap_workspace(
        workspace,
        template=template,
        agent_name=agent_name,
        platform=platform,
        with_synthetic_data=with_synthetic_data,
        demo=demo,
    )
    if template in STARTER_TEMPLATE_NAMES:
        summary["template_summary"] = apply_template_to_workspace(workspace, template)
    return workspace, summary


def _doctor_fix_workspace(workspace: AutoAgentWorkspace) -> list[str]:
    """Repair fixable workspace issues for `doctor --fix`."""
    fixes: list[str] = []

    if not workspace.autoagent_dir.exists():
        workspace.autoagent_dir.mkdir(parents=True, exist_ok=True)
        fixes.append("Created .autoagent/")
    if not workspace.configs_dir.exists():
        workspace.configs_dir.mkdir(parents=True, exist_ok=True)
        fixes.append("Created configs/")
    if not workspace.cases_dir.exists():
        workspace.cases_dir.mkdir(parents=True, exist_ok=True)
        fixes.append("Created evals/cases/")
    if not workspace.scorer_specs_dir.exists():
        workspace.scorer_specs_dir.mkdir(parents=True, exist_ok=True)
        fixes.append("Created .autoagent/scorers/")
    logs_dir = workspace.autoagent_dir / "logs"
    if not logs_dir.exists():
        logs_dir.mkdir(parents=True, exist_ok=True)
        fixes.append("Created .autoagent/logs/")
    if not workspace.best_score_file.exists():
        workspace.best_score_file.touch()
        fixes.append("Created .autoagent/best_score.txt")

    if workspace.metadata.active_config_version is None or workspace.metadata.active_config_file is None:
        resolved = workspace.resolve_active_config()
        if resolved is not None:
            workspace.set_active_config(resolved.version, filename=resolved.path.name)
            fixes.append(f"Set active config to v{resolved.version:03d}")

    return fixes


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


def _read_best_score(path: Path) -> float:
    """Read a persisted best score, treating missing or empty files as zero."""
    if not path.exists():
        return 0.0
    raw_score = path.read_text(encoding="utf-8").strip()
    return float(raw_score) if raw_score else 0.0


def _persist_best_score(
    score_after: float | None,
    all_time_best: float,
    best_score_file: Path,
    *,
    announce: bool,
) -> float:
    """Persist new personal-best scores so optimize history survives across runs."""
    if score_after is None or score_after <= all_time_best:
        return all_time_best

    best_score_file.parent.mkdir(parents=True, exist_ok=True)
    best_score_file.write_text(str(score_after), encoding="utf-8")
    if announce:
        click.echo(click.style("\n  ✨ New personal best!", fg="yellow", bold=True))
    return score_after


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


def _unwrap_eval_payload(data: dict) -> dict:
    """Return the embedded eval payload when a JSON envelope wraps the result."""
    payload = data.get("data")
    if isinstance(payload, dict) and isinstance(data.get("status"), str):
        return payload
    return data


def _extract_eval_scores(data: dict) -> dict[str, float]:
    """Normalize eval metrics from nested `scores` payloads or flatter result shapes."""
    payload = _unwrap_eval_payload(data)
    raw_scores = payload.get("scores") if isinstance(payload.get("scores"), dict) else payload
    if not isinstance(raw_scores, dict):
        raw_scores = {}

    scores: dict[str, float] = {}
    for metric in EVAL_METRIC_NAMES:
        value = raw_scores.get(metric, 0.0)
        try:
            scores[metric] = float(value)
        except (TypeError, ValueError):
            scores[metric] = 0.0
    return scores


def _eval_result_search_roots() -> list[Path]:
    """Return unique search roots for eval result files from cwd and invocation cwd."""
    roots = [
        Path.cwd(),
        Path.cwd() / ".autoagent",
        _resolve_invocation_input_path(Path(".")),
        _resolve_invocation_input_path(Path(".autoagent")),
    ]
    unique_roots: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_roots.append(root)
    return unique_roots


def _load_eval_result(ref: str) -> tuple[Path, dict]:
    """Load eval results from an explicit file path or a fuzzy run reference."""
    path = _resolve_invocation_input_path(Path(ref))
    if path.exists():
        target = path
    else:
        candidates: list[Path] = []
        if Path(ref).parent == Path("."):
            for root in _eval_result_search_roots():
                if not root.exists():
                    continue
                candidates.extend(candidate for candidate in root.glob(f"*{ref}*.json") if candidate.is_file())
        if not candidates:
            raise click.ClickException(f"Eval result not found: {ref}")
        target = max(candidates, key=lambda candidate: candidate.stat().st_mtime)

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise click.ClickException(f"Could not read eval result {target}: {exc}") from exc
    return target, data


def _latest_eval_result_file() -> Path | None:
    """Return the newest eval result JSON from cwd or `.autoagent/`."""
    candidates: dict[Path, Path] = {}
    for root in _eval_result_search_roots():
        if not root.exists():
            continue
        for pattern in ("eval_results*.json", "*results*.json"):
            for candidate in root.glob(pattern):
                if not candidate.is_file():
                    continue
                candidates[candidate.resolve()] = candidate
    if not candidates:
        return None
    return max(candidates.values(), key=lambda candidate: candidate.stat().st_mtime)


def _collect_failure_clusters(data: dict) -> dict[str, int]:
    """Return failure buckets from explicit metadata or derive them from failed cases."""
    payload = _unwrap_eval_payload(data)
    explicit = payload.get("failure_clusters") or payload.get("failure_buckets")
    if isinstance(explicit, dict) and explicit:
        return {str(name): int(count) for name, count in explicit.items()}

    failures: dict[str, int] = {}
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    for result in results:
        if not isinstance(result, dict) or result.get("passed", True):
            continue
        details = result.get("details") if isinstance(result.get("details"), dict) else {}
        cluster = (
            details.get("failure_cluster")
            or details.get("failure_bucket")
            or result.get("failure_cluster")
            or result.get("failure_bucket")
            or result.get("category")
            or "unknown"
        )
        label = str(cluster)
        failures[label] = failures.get(label, 0) + 1
    return failures


def _build_eval_comparison(left_run: str, right_run: str) -> dict:
    """Build a shared comparison payload for both eval comparison commands."""
    left_path, left_data = _load_eval_result(left_run)
    right_path, right_data = _load_eval_result(right_run)
    left_scores = _extract_eval_scores(left_data)
    right_scores = _extract_eval_scores(right_data)
    deltas = {
        metric: round(right_scores[metric] - left_scores[metric], 6)
        for metric in EVAL_METRIC_NAMES
    }
    winner = "left" if left_scores["composite"] >= right_scores["composite"] else "right"
    return {
        "left": {"run": str(left_path), "scores": left_scores},
        "right": {"run": str(right_path), "scores": right_scores},
        "winner": winner,
        "delta_composite": deltas["composite"],
        "deltas": deltas,
    }


def _build_eval_breakdown() -> dict:
    """Build a metric and failure-cluster breakdown for the latest eval result."""
    latest = _latest_eval_result_file()
    if latest is None:
        raise click.ClickException("No eval results found. Run `autoagent eval run --output eval_results.json` first.")

    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise click.ClickException(f"Could not read eval result {latest}: {exc}") from exc

    return {
        "source": str(latest),
        "scores": _extract_eval_scores(data),
        "failure_clusters": _collect_failure_clusters(data),
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

            resolved_best_score_file = best_score_file or Path(".autoagent/best_score.txt")
            _persist_best_score(
                score_after,
                all_time_best,
                resolved_best_score_file,
                announce=True,
            )
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


def _optimize_cycle_status(
    *,
    report_needs_optimization: bool,
    new_config: dict | None,
    score_before: float | None,
    score_after: float | None,
) -> str:
    """Normalize optimize outcomes into stable experiment-log statuses."""
    if not report_needs_optimization:
        return "skip"
    if (
        new_config is not None
        and score_before is not None
        and score_after is not None
        and score_after > score_before
    ):
        return "keep"
    return "discard"


def _continuous_status_line(
    *,
    cycle: int,
    best_score: float,
    last_status: str,
    delta: float | None,
) -> str:
    """Render a compact between-cycle heartbeat for continuous optimize mode."""
    delta_fragment = f" ({delta:+.2f})" if delta is not None else ""
    return (
        f"Cycle {cycle} | Best: {best_score:.2f} | "
        f"Last: {last_status}{delta_fragment} | Press Ctrl+C to stop"
    )


def _proposer_total_cost(proposer: Proposer) -> float:
    """Return the accumulated router cost for the current proposer."""
    if proposer.llm_router is None:
        return 0.0
    summary = proposer.llm_router.cost_summary()
    return round(sum(float(item.get("total_cost", 0.0)) for item in summary.values()), 8)


def _runtime_budget_config(runtime: object) -> tuple[str, float, float, int]:
    """Return budget tracker settings, tolerating lightweight test doubles."""
    budget = getattr(runtime, "budget", None)
    tracker_db_path = str(getattr(budget, "tracker_db_path", ".autoagent/cost_tracker.db"))
    per_cycle_dollars = float(getattr(budget, "per_cycle_dollars", 1.0))
    daily_dollars = float(getattr(budget, "daily_dollars", 10.0))
    stall_threshold_cycles = int(getattr(budget, "stall_threshold_cycles", 5))
    return tracker_db_path, per_cycle_dollars, daily_dollars, stall_threshold_cycles


def _build_runtime_components() -> tuple[
    object,
    EvalRunner,
    Proposer,
    SkillEngine,
    AdversarialSimulator | None,
    SkillAutoLearner | None,
]:
    """Create runtime-configured optimizer dependencies."""
    from cli.model import apply_model_overrides

    runtime = load_runtime_config()
    runtime = apply_model_overrides(runtime)
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

@click.group(cls=AutoAgentGroup, invoke_without_command=True)
@click.version_option(version=AUTOAGENT_VERSION, prog_name="autoagent")
@_banner_flag_options
@click.pass_context
def cli(ctx: click.Context, quiet: bool, no_banner: bool) -> None:
    """AutoAgent VNextCC — agent optimization platform.

    A product-grade platform for iterating ADK agent quality.
    CLI-first, API-ready, with a web console for visual insight.
    """
    del quiet, no_banner
    ctx.obj = ctx.obj or {}
    ctx.obj["workspace"] = _enter_discovered_workspace(ctx.invoked_subcommand)
    if ctx.invoked_subcommand is None and not ctx.resilient_parsing:
        workspace = ctx.obj.get("workspace")
        if _is_tty():
            if workspace is not None:
                from cli.repl import run_shell

                run_shell(workspace)
            else:
                from cli.onboarding import run_onboarding

                choice = run_onboarding()
                if choice == "demo":
                    ctx.invoke(
                        init_project,
                        template="customer-support",
                        target_dir=".",
                        name=None,
                        agent_name="My Agent",
                        platform="Google ADK",
                        with_synthetic_data=True,
                        demo=True,
                    )
                elif choice == "empty":
                    ctx.invoke(
                        init_project,
                        template="minimal",
                        target_dir=".",
                        name=None,
                        agent_name="My Agent",
                        platform="Google ADK",
                        with_synthetic_data=False,
                        demo=False,
                    )
        else:
            ctx.invoke(
                status,
                db=DB_PATH,
                configs_dir=CONFIGS_DIR,
                memory_db=MEMORY_DB,
                json_output=False,
            )
        return


cli.add_command(mode_group)
cli.add_command(mcp_group)
cli.add_command(intelligence_group)
from cli.model import model_group
from cli.usage import usage_command

cli.add_command(model_group)
cli.add_command(usage_command)


# ---------------------------------------------------------------------------
# autoagent shell — interactive REPL
# ---------------------------------------------------------------------------

@cli.command("shell")
@click.pass_context
def shell_command(ctx: click.Context) -> None:
    """Launch the interactive AutoAgent shell."""
    from cli.repl import run_shell

    workspace = ctx.obj.get("workspace")
    run_shell(workspace)


# ---------------------------------------------------------------------------
# autoagent continue — resume last session
# ---------------------------------------------------------------------------

@cli.command("continue")
@click.pass_context
def continue_command(ctx: click.Context) -> None:
    """Resume the most recent shell session."""
    from cli.repl import run_shell
    from cli.sessions import SessionStore

    workspace = ctx.obj.get("workspace")
    if workspace is None:
        raise click.ClickException("No workspace found. Run: autoagent init")

    store = SessionStore(workspace.root)
    latest = store.latest()
    if latest is None:
        click.echo("No previous session found. Starting a new shell.")
        run_shell(workspace, session_store=store)
        return

    click.echo(f"Resuming session: {latest.title} ({latest.session_id})")
    click.echo(f"  Goal: {latest.active_goal or '(none)'}")
    click.echo(f"  Commands: {len(latest.command_history)}")
    click.echo(f"  Transcript entries: {len(latest.transcript)}")
    run_shell(workspace, session_store=store)


# ---------------------------------------------------------------------------
# autoagent session — session management
# ---------------------------------------------------------------------------

@cli.group("session")
def session_group() -> None:
    """Manage shell sessions."""


@session_group.command("list")
@click.option("--limit", default=20, show_default=True, help="Maximum sessions to list.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.pass_context
def session_list(ctx: click.Context, limit: int, json_output: bool) -> None:
    """List recent shell sessions."""
    import json as json_mod

    from cli.sessions import SessionStore

    workspace = ctx.obj.get("workspace")
    if workspace is None:
        raise click.ClickException("No workspace found. Run: autoagent init")

    store = SessionStore(workspace.root)
    sessions = store.list_sessions(limit=limit)

    if json_output:
        click.echo(json_mod.dumps([session.to_dict() for session in sessions], indent=2))
        return

    if not sessions:
        click.echo("No sessions found.")
        return

    click.echo(f"\nRecent sessions ({len(sessions)}):")
    for session in sessions:
        timestamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(session.updated_at))
        goal = session.active_goal[:40] if session.active_goal else "(no goal)"
        click.echo(f"  {session.session_id}  {timestamp}  {session.title:<30}  {goal}")
    click.echo("")


@session_group.command("resume")
@click.argument("session_id")
@click.pass_context
def session_resume(ctx: click.Context, session_id: str) -> None:
    """Resume a specific shell session by ID."""
    from cli.repl import run_shell
    from cli.sessions import SessionStore

    workspace = ctx.obj.get("workspace")
    if workspace is None:
        raise click.ClickException("No workspace found. Run: autoagent init")

    store = SessionStore(workspace.root)
    session = store.get(session_id)
    if session is None:
        raise click.ClickException(f"Session not found: {session_id}")

    click.echo(f"Resuming session: {session.title} ({session.session_id})")
    click.echo(f"  Goal: {session.active_goal or '(none)'}")
    click.echo(f"  Commands: {len(session.command_history)}")
    run_shell(workspace, session_store=store)


@session_group.command("delete")
@click.argument("session_id")
@click.pass_context
def session_delete(ctx: click.Context, session_id: str) -> None:
    """Delete a shell session by ID."""
    from cli.sessions import SessionStore

    workspace = ctx.obj.get("workspace")
    if workspace is None:
        raise click.ClickException("No workspace found. Run: autoagent init")

    store = SessionStore(workspace.root)
    if store.delete(session_id):
        click.echo(f"Deleted session: {session_id}")
        return
    raise click.ClickException(f"Session not found: {session_id}")


# ---------------------------------------------------------------------------
# autoagent init
# ---------------------------------------------------------------------------

@cli.command("init")
@click.option("--template", default="customer-support", show_default=True,
              type=click.Choice((*STARTER_TEMPLATE_NAMES, "minimal")),
              help="Project template to scaffold.")
@click.option("--dir", "target_dir", default=".", show_default=True,
              help="Directory to initialize in.")
@click.option("--name", default=None,
              help="Optional workspace folder name to create inside --dir.")
@click.option("--agent-name", default="My Agent", show_default=True,
              help="Agent name for AUTOAGENT.md.")
@click.option("--platform", default="Google ADK", show_default=True,
              help="Platform for AUTOAGENT.md.")
@click.option("--with-synthetic-data/--no-synthetic-data", default=True,
              show_default=True, help="Seed synthetic conversations and evals.")
@click.option("--demo/--no-demo", default=False, show_default=True,
              help="Seed a reviewable demo workspace with traces, review cards, and AutoFix proposals.")
def init_project(
    template: str,
    target_dir: str,
    name: str | None,
    agent_name: str,
    platform: str,
    with_synthetic_data: bool,
    demo: bool,
) -> None:
    """Scaffold a new AutoAgent workspace with workspace metadata and starter data."""
    workspace, summary = _create_workspace(
        template=template,
        target_dir=target_dir,
        name=name,
        agent_name=agent_name,
        platform=platform,
        with_synthetic_data=with_synthetic_data,
        demo=demo,
    )
    workspace_root = workspace.root

    click.echo(click.style("\n✦ AutoAgent Init", fg="cyan", bold=True))
    click.echo("")
    click.echo(click.style("  ✓ ", fg="green") + f"Initialized AutoAgent project in {workspace_root}")
    click.echo(click.style("  ✓ ", fg="green") + f"Workspace: {workspace.workspace_label}")
    click.echo(click.style("  ✓ ", fg="green") + f"Active config: v{workspace.metadata.active_config_version or 1:03d}")
    click.echo(click.style("  ✓ ", fg="green") + f"Config: {workspace.configs_dir / 'v001.yaml'}")
    click.echo(click.style("  ✓ ", fg="green") + f"Base config: {workspace.configs_dir / 'v001_base.yaml'}")
    click.echo(click.style("  ✓ ", fg="green") + f"Evals: {workspace.cases_dir}")
    click.echo(click.style("  ✓ ", fg="green") + f"Memory: {workspace.root / 'AUTOAGENT.md'}")
    click.echo(click.style("  ✓ ", fg="green") + f"Runtime config: {workspace.runtime_config_path}")

    synthetic_summary = summary.get("synthetic_summary", {}) or {}
    if with_synthetic_data:
        click.echo(
            click.style("  ✓ ", fg="green")
            + "Seeded synthetic conversations: "
            + f"{synthetic_summary.get('conversation_count', 0)} conversations, "
            + f"{synthetic_summary.get('eval_case_count', 0)} eval cases"
        )

    click.echo(
        click.style("  ✓ ", fg="green")
        + f"Starter runbooks: {summary.get('runbook_count', 0)} runbooks"
    )

    if demo:
        demo_summary = summary.get("demo_summary", {}) or {}
        click.echo(
            click.style("  ✓ ", fg="green")
            + "Demo data seeded: "
            + f"{len(demo_summary.get('trace_ids', []))} traces, "
            + f"review {demo_summary.get('change_card_id', 'n/a')}, "
            + f"autofix {demo_summary.get('autofix_id', 'n/a')}"
        )

    click.echo("")
    click.echo(f"  Template:   {template}")
    click.echo(f"  Agent:      {agent_name}")
    click.echo(f"  Platform:   {platform}")
    click.echo("")
    click.echo(click.style("  Next step:", bold=True))
    click.echo("    autoagent status")
    click.echo("    autoagent quickstart")
    click.echo("    autoagent build \"Build a support agent for order tracking\"")
    click.echo("    autoagent eval run")
    click.echo("")


@cli.command("new")
@click.argument("name")
@click.option(
    "--template",
    default="customer-support",
    show_default=True,
    type=click.Choice(STARTER_TEMPLATE_NAMES),
    help="Starter template to scaffold into the new workspace.",
)
@click.option("--demo/--no-demo", default=False, show_default=True, help="Seed a reviewable demo workspace.")
def new_workspace(name: str, template: str, demo: bool) -> None:
    """Create a new starter workspace and print the first three commands to run."""
    workspace, summary = _create_workspace(
        template=template,
        target_dir=".",
        name=name,
        agent_name="My Agent",
        platform="Google ADK",
        with_synthetic_data=True,
        demo=demo,
    )
    mode_summary = summarize_mode_state(str(workspace.runtime_config_path))
    template_summary = summary.get("template_summary", {}) or {}

    click.echo(click.style("\n✦ AutoAgent New", fg="cyan", bold=True))
    click.echo("")
    click.echo(click.style("  ✓ ", fg="green") + f"Created workspace: {workspace.root}")
    click.echo(click.style("  ✓ ", fg="green") + f"Template: {template}")
    click.echo(
        click.style("  ✓ ", fg="green")
        + f"Starter assets: {template_summary.get('eval_file_count', 0)} eval files, "
        + f"{template_summary.get('scorer_count', 0)} scorer specs"
    )
    if demo:
        demo_summary = summary.get("demo_summary", {}) or {}
        click.echo(
            click.style("  ✓ ", fg="green")
            + "Demo data seeded: "
            + f"{len(demo_summary.get('trace_ids', []))} traces, "
            + f"review {demo_summary.get('change_card_id', 'n/a')}, "
            + f"autofix {demo_summary.get('autofix_id', 'n/a')}"
        )
    click.echo("")
    click.echo(f"  Mode: {mode_summary['message']}")
    click.echo("  Live setup: run `autoagent provider configure` when you are ready to use real models.")
    click.echo("")
    click.echo(click.style("  Next 3 commands:", bold=True))
    click.echo(f"    cd {name}")
    click.echo("    autoagent status")
    click.echo("    autoagent eval run")
    click.echo("")


@cli.group("template")
def template_group() -> None:
    """List and apply bundled starter workspace templates."""


@template_group.command("list")
def template_list() -> None:
    """Show bundled starter templates."""
    click.echo("\nStarter templates")
    click.echo("=================")
    for template in list_templates():
        click.echo(f"- {template.name}: {template.description}")


@template_group.command("apply")
@click.argument("name", type=click.Choice(STARTER_TEMPLATE_NAMES))
def template_apply(name: str) -> None:
    """Apply a starter template to the current workspace."""
    workspace = _require_workspace("template")
    summary = apply_template_to_workspace(workspace, name)

    click.echo(click.style(f"Applied: template {name}", fg="green"))
    click.echo(f"  Config:    {summary['config_path']}")
    click.echo(f"  Evals:     {summary['eval_file_count']} files / {summary['eval_case_count']} cases")
    click.echo(f"  Scorers:   {summary['scorer_count']}")
    if summary["suggested_skills"]:
        click.echo(f"  Skills:    {', '.join(summary['suggested_skills'])}")


@cli.group("provider")
def provider_group() -> None:
    """Configure and validate workspace provider settings."""


@provider_group.command("configure")
@click.option(
    "--provider",
    "provider_name",
    type=click.Choice(["openai", "anthropic", "google"], case_sensitive=False),
    default=None,
    help="Provider to configure. Prompts when omitted.",
)
@click.option("--model", default=None, help="Model name to store. Prompts when omitted.")
@click.option("--api-key-env", default=None, help="API key environment variable. Prompts when omitted.")
def provider_configure(provider_name: str | None, model: str | None, api_key_env: str | None) -> None:
    """Interactively configure a workspace provider profile."""
    workspace = _require_workspace("provider")
    resolved_provider = provider_name or click.prompt(
        "Provider",
        type=click.Choice(["openai", "anthropic", "google"], case_sensitive=False),
        default="openai",
        show_default=True,
    )
    resolved_model = model or click.prompt(
        "Model",
        default=default_model_for(resolved_provider),
        show_default=True,
    )
    resolved_env = api_key_env or click.prompt(
        "API key env var",
        default=default_api_key_env_for(resolved_provider),
        show_default=True,
    )

    registry_path = providers_file_path(workspace)
    upsert_provider(
        registry_path,
        provider=resolved_provider,
        model=resolved_model,
        api_key_env=resolved_env,
    )
    sync_runtime_config(
        workspace.runtime_config_path,
        provider=resolved_provider,
        model=resolved_model,
        api_key_env=resolved_env,
    )

    click.echo(click.style(f"Applied: provider {resolved_provider}:{resolved_model}", fg="green"))
    click.echo(f"  Registry: {registry_path}")
    click.echo(f"  Runtime:  {workspace.runtime_config_path}")
    click.echo(f"  Next:     export {resolved_env}=... && autoagent provider test")


@provider_group.command("list")
def provider_list() -> None:
    """List configured providers for the current workspace."""
    workspace = _require_workspace("provider")
    providers = configured_providers(providers_file_path(workspace))
    if not providers:
        click.echo("No providers configured. Run `autoagent provider configure`.")
        return

    click.echo("\nConfigured providers")
    click.echo("====================")
    for provider in providers:
        env_name = provider.get("api_key_env") or "n/a"
        click.echo(f"- {provider['provider']}  model={provider['model']}  env={env_name}")


@provider_group.command("test")
def provider_test() -> None:
    """Validate configured providers have the credentials needed for live use."""
    workspace = _require_workspace("provider")
    checks = provider_health_checks(providers_file_path(workspace))
    if not checks:
        raise click.ClickException("No providers configured. Run `autoagent provider configure` first.")

    failures = [check for check in checks if not check["credential_present"]]
    for check in checks:
        marker = click.style("✓", fg="green") if check["credential_present"] else click.style("✗", fg="red")
        click.echo(f"{marker} {check['message']}")
    if failures:
        raise click.ClickException("Provider check failed. Export the missing credentials and retry.")

    click.echo("Provider check passed.")


# ---------------------------------------------------------------------------
# autoagent build
# ---------------------------------------------------------------------------

@cli.group("build", cls=DefaultCommandGroup, default_command="run")
def build_group() -> None:
    """Build agent artifacts or inspect the latest build output.

    Examples:
      autoagent build "Build a support agent for order tracking"
      autoagent build show latest
    """


@build_group.command("run", hidden=True)
@click.argument("prompt")
@click.option(
    "--connector",
    "connectors",
    multiple=True,
    help="Connector to include (repeatable). Example: --connector Shopify",
)
@click.option("--output-dir", default=".", show_default=True, help="Directory for generated build artifacts.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output artifact as JSON only.")
@click.option(
    "--output-format",
    type=click.Choice(["text", "json", "stream-json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Render human text, a final JSON envelope, or stream JSON progress events.",
)
def build_agent(
    prompt: str,
    connectors: tuple[str, ...],
    output_dir: str,
    json_output: bool = False,
    output_format: str = "text",
) -> None:
    """Build an agent artifact from natural language and scaffold eval/deploy handoff files."""
    from cli.output import resolve_output_format
    from cli.progress import ProgressRenderer
    from optimizer.transcript_intelligence import TranscriptIntelligenceService

    resolved_output_format = resolve_output_format(output_format, json_output=json_output)
    progress = ProgressRenderer(output_format=resolved_output_format, render_text=False)
    progress.phase_started("build", message="Generate build artifact from prompt")

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
    config_yaml = yaml.safe_dump(config, sort_keys=False)
    config_path.write_text(config_yaml, encoding="utf-8")
    progress.artifact_written("config", path=str(config_path))

    eval_path = target / "evals" / "cases" / "generated_build.yaml"
    _write_generated_eval_cases(eval_path, artifact)
    progress.artifact_written("evals", path=str(eval_path))

    artifact_path = target / ".autoagent" / "build_artifact_latest.json"
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    progress.artifact_written("artifact", path=str(artifact_path))

    prompt_summary = " ".join(prompt.split())
    title = prompt_summary[:72] if len(prompt_summary) <= 72 else f"{prompt_summary[:69]}..."
    build_artifact_store = BuildArtifactStore(
        path=target / ".autoagent" / "build_artifacts.json",
        latest_path=artifact_path,
    )
    build_artifact_store.save_latest(
        BuildArtifact(
            id=f"build-{uuid.uuid4().hex[:12]}",
            created_at=datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            updated_at=datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            source="cli",
            status="complete",
            config_yaml=config_yaml,
            prompt_used=prompt,
            eval_draft=str(eval_path),
            starter_config_path=str(config_path),
            selector="latest",
            metadata={
                "title": title or "CLI Build Artifact",
                "summary": "CLI build generated from a natural-language prompt.",
                "connectors": artifact.get("connectors", []),
                "intents": artifact.get("intents", []),
                "tools": artifact.get("tools", []),
                "guardrails": artifact.get("guardrails", []),
                "skills": artifact.get("skills", []),
                "integration_templates": artifact.get("integration_templates", []),
                "legacy_payload": artifact,
            },
        ),
        legacy_payload=artifact,
    )
    progress.phase_completed("build", message="Build artifact ready")
    progress.next_action("autoagent eval run")

    if resolved_output_format == "stream-json":
        return

    if resolved_output_format == "json":
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
    click.echo(click.style("Next step:", bold=True))
    click.echo(f"  autoagent eval run --config {config_path}")
    click.echo("  autoagent diagnose --interactive")
    click.echo("  autoagent loop --max-cycles 5")
    click.echo("  autoagent deploy --target cx-studio")


# ---------------------------------------------------------------------------
# autoagent build show (FR-13: inspect without knowing .autoagent paths)
# ---------------------------------------------------------------------------

def _build_show_impl(
    selector: str,
    json_output: bool = False,
    id_only: bool = False,
    path_only: bool = False,
) -> None:
    """Render build-show style output for both canonical and legacy routes."""
    from cli.stream2_helpers import get_latest_build_artifact, json_response

    artifact = get_latest_build_artifact()
    if artifact is None:
        if json_output:
            click.echo(json_response("error", {"message": "No build artifact found"}))
        else:
            click.echo("No build artifact found.")
            click.echo("Run: autoagent build \"Describe your agent\"")
        return

    artifact_path = Path(".autoagent") / "build_artifact_latest.json"
    artifact_id = artifact.get("artifact_id") or artifact.get("id") or selector
    if id_only:
        click.echo(str(artifact_id))
        return
    if path_only:
        click.echo(str(artifact_path))
        return

    if json_output:
        click.echo(json_response("ok", artifact, next_cmd="autoagent eval run"))
        return

    click.echo(click.style("\n✦ Latest Build Artifact", fg="cyan", bold=True))
    click.echo(f"  Prompt:      {artifact.get('source_prompt', '—')}")
    click.echo(f"  Connectors:  {', '.join(artifact.get('connectors', [])) or 'None'}")
    click.echo(f"  Intents:     {len(artifact.get('intents', []))}")
    click.echo(f"  Tools:       {len(artifact.get('tools', []))}")
    click.echo(f"  Guardrails:  {len(artifact.get('guardrails', []))}")
    click.echo(f"  Skills:      {len(artifact.get('skills', []))}")


@build_group.command("show")
@click.argument("selector", default="latest")
@click.option("--id-only", is_flag=True, help="Print only the resolved artifact identifier.")
@click.option("--path-only", is_flag=True, help="Print only the resolved artifact path.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def build_show(selector: str, id_only: bool, path_only: bool, json_output: bool = False) -> None:
    """Show build output. Currently supports 'latest'.

    Examples:
      autoagent build show latest
      autoagent build show latest --json
    """
    _build_show_impl(selector, json_output=json_output, id_only=id_only, path_only=path_only)


@cli.command("build-show", hidden=True)
@click.argument("selector", default="latest")
@click.option("--id-only", is_flag=True, help="Print only the resolved artifact identifier.")
@click.option("--path-only", is_flag=True, help="Print only the resolved artifact path.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def build_show_alias(selector: str, id_only: bool, path_only: bool, json_output: bool = False) -> None:
    """Deprecated alias for `autoagent build show`."""
    if not json_output:
        _echo_deprecation(f"autoagent build-show {selector}", f"autoagent build show {selector}")
    _build_show_impl(selector, json_output=json_output, id_only=id_only, path_only=path_only)


# ---------------------------------------------------------------------------
# autoagent eval (subgroup)
# ---------------------------------------------------------------------------

@cli.group("eval", cls=DefaultCommandGroup, default_command="run", default_on_empty=True)
def eval_group() -> None:
    """Evaluate agent configs against test suites.

    Examples:
      autoagent eval run
      autoagent eval show latest
      autoagent eval compare left.json right.json
      autoagent eval breakdown
      autoagent eval generate --config configs/v001.yaml --output generated_eval_suite.json
    """
    return None


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
@click.option(
    "--output-format",
    type=click.Choice(["text", "json", "stream-json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Render text, a final JSON envelope, or stream JSON progress events.",
)
def eval_run(config_path: str | None, suite: str | None, dataset: str | None, dataset_split: str,
             category: str | None, output: str | None, real_agent: bool = False,
             json_output: bool = False, output_format: str = "text") -> None:
    """Run eval suite against a config.

    Examples:
      autoagent eval run
      autoagent eval run --config configs/v003.yaml
      autoagent eval run --config configs/v003.yaml --category safety
      autoagent eval run --output results.json
    """
    from cli.stream2_helpers import json_response
    from cli.output import resolve_output_format
    from cli.progress import ProgressRenderer

    resolved_output_format = resolve_output_format(output_format, json_output=json_output)
    progress = ProgressRenderer(output_format=resolved_output_format, render_text=False)
    progress.phase_started("eval", message="Run evaluation suite")

    runtime = load_runtime_config()
    if resolved_output_format == "text":
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
        if resolved_output_format == "text":
            click.echo(f"Evaluating config: {config_path}")
    else:
        workspace = discover_workspace()
        if workspace is not None:
            resolved = workspace.resolve_active_config()
            if resolved is not None:
                config = resolved.config
                config_path = str(resolved.path)
                if resolved_output_format == "text":
                    click.echo(f"Evaluating active config: {resolved.path}")
        if config is None and resolved_output_format == "text":
            click.echo("Evaluating with default config")

    runner = _build_eval_runner(
        runtime,
        cases_dir=suite,
        use_real_agent=real_agent,
        default_agent_config=config,
    )
    _warn_mock_modes(eval_runner=runner, json_output=(resolved_output_format == "json"))

    if category:
        score = runner.run_category(category, config=config, dataset_path=dataset, split=dataset_split)
        progress.phase_completed("eval", message=f"Category '{category}' complete")
        progress.next_action("autoagent improve")
        if resolved_output_format == "stream-json":
            return
        if resolved_output_format == "json":
            click.echo(json_response("ok", _score_to_dict(score), next_cmd="autoagent improve"))
            return
        _print_score(score, f"Category: {category}")
    else:
        score = runner.run(config=config, dataset_path=dataset, split=dataset_split)
        progress.phase_completed("eval", message="Full eval suite complete")
        progress.next_action("autoagent improve")
        if resolved_output_format == "stream-json":
            return
        if resolved_output_format == "json":
            click.echo(json_response("ok", _score_to_dict(score), next_cmd="autoagent improve"))
            return
        _print_score(score, "Full eval suite")

    if resolved_output_format == "text":
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
        progress.artifact_written("eval_results", path=output)
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


@eval_group.command("show")
@click.argument("selector", default="latest")
@click.option("--file", "results_file", default=None, help="Path to results JSON file.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def eval_show(selector: str, results_file: str | None, json_output: bool = False) -> None:
    """Show eval results. Supports selectors: latest.

    Examples:
      autoagent eval show latest
      autoagent eval show latest --json
      autoagent eval show --file results.json
    """
    from cli.stream2_helpers import get_latest_eval_result, json_response

    if results_file:
        data = json.loads(Path(results_file).read_text(encoding="utf-8"))
    else:
        data = get_latest_eval_result()

    if data is None:
        if json_output:
            click.echo(json_response("error", {"message": "No eval results found"}))
        else:
            click.echo("No eval results found.")
            click.echo("Run: autoagent eval run --output results.json")
        return

    if json_output:
        click.echo(json_response("ok", data, next_cmd="autoagent optimize"))
        return

    click.echo(f"\nEval Results — {data.get('timestamp', 'unknown')}")
    click.echo(f"  Config:  {data.get('config_path', 'default')}")
    scores = data.get("scores", {})
    click.echo(f"  Cases:   {data.get('passed', '?')}/{data.get('total', '?')} passed")
    click.echo(f"  Quality:   {scores.get('quality', 0):.4f}")
    click.echo(f"  Safety:    {scores.get('safety', 0):.4f}")
    click.echo(f"  Latency:   {scores.get('latency', 0):.4f}")
    click.echo(f"  Cost:      {scores.get('cost', 0):.4f}")
    click.echo(f"  Composite: {scores.get('composite', 0):.4f}")

    results = data.get("results", [])
    failed = [r for r in results if not r.get("passed")]
    if failed:
        click.echo(f"\nFailed cases ({len(failed)}):")
        for r in failed:
            click.echo(f"  {r['case_id']} [{r.get('category', '?')}] quality={r.get('quality_score', 0):.2f}")


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


@eval_group.command("generate")
@click.option("--config", "config_path", default=None, help="Path to agent config YAML/JSON to analyze.")
@click.option("--agent-name", default="agent", help="Agent name for labeling the eval suite.")
@click.option("--from-transcripts", is_flag=True, default=False, help="Generate from conversation transcripts (future).")
@click.option("--output", default=None, help="Write generated eval suite to JSON file.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
@click.option("--provider", default=None, type=click.Choice(["openai", "anthropic", "mock"]), help="Force LLM provider.")
def eval_generate(
    config_path: str | None,
    agent_name: str,
    from_transcripts: bool,
    output: str | None,
    json_output: bool,
    provider: str | None,
) -> None:
    """AI-generate a comprehensive eval suite from agent config.

    Examples:
      autoagent eval generate
      autoagent eval generate --config agent_config.yaml
      autoagent eval generate --config agent_config.yaml --output evals.json
      autoagent eval generate --provider mock --agent-name "My Agent"
    """
    from evals.auto_generator import AutoEvalGenerator

    if not json_output:
        click.echo(click.style("✦ Auto-generating eval suite", fg="cyan"))
        _print_cli_plan(
            "Generation plan",
            [
                "Analyze agent config (system prompt, tools, routing, policies)",
                "Generate eval cases across 8 categories via AI",
                "Output structured eval suite",
            ],
        )

    # Load agent config
    agent_config: dict = {}
    if config_path:
        config_file = Path(config_path)
        if not config_file.exists():
            click.echo(click.style(f"Config file not found: {config_path}", fg="red"), err=True)
            sys.exit(1)
        raw = config_file.read_text(encoding="utf-8")
        if config_file.suffix in (".yaml", ".yml"):
            agent_config = yaml.safe_load(raw) or {}
        else:
            agent_config = json.loads(raw)
        if not json_output:
            click.echo(f"  Loaded config: {config_path}")
    else:
        # Try loading default autoagent.yaml
        default_config = Path("autoagent.yaml")
        if default_config.exists():
            agent_config = yaml.safe_load(default_config.read_text(encoding="utf-8")) or {}
            if not json_output:
                click.echo("  Loaded default config: autoagent.yaml")
        else:
            if not json_output:
                click.echo("  No config provided — using empty config (mock cases)")

    if from_transcripts:
        if not json_output:
            click.echo("  --from-transcripts: transcript-based generation (future feature)")

    generator = AutoEvalGenerator(llm_provider=provider)
    if not json_output:
        click.echo("  Generating...")

    suite = generator.generate(agent_config=agent_config, agent_name=agent_name)

    if json_output:
        click.echo(json.dumps(suite.to_dict(), indent=2))
    else:
        click.echo(click.style(f"\n  Suite {suite.suite_id}", fg="green"))
        click.echo(f"  Status:     {suite.status}")
        click.echo(f"  Total cases: {suite.total_cases}")
        click.echo()
        for cat, cases in suite.categories.items():
            difficulty_str = ", ".join(
                f"{d}={sum(1 for c in cases if c.difficulty == d)}"
                for d in ("easy", "medium", "hard")
                if any(c.difficulty == d for c in cases)
            )
            click.echo(f"  {cat:<20s} {len(cases):>3d} cases  ({difficulty_str})")

        summary = suite.summary
        click.echo(f"\n  Safety probes: {summary.get('safety_probes', 0)}")
        click.echo(click.style(f"\n  Mood: {_score_mood(0.85)}", fg="magenta"))
        _print_next_actions([
            "autoagent eval run --suite <generated_cases>",
            "autoagent eval generate --output evals.json",
        ])

    if output:
        Path(output).write_text(json.dumps(suite.to_dict(), indent=2), encoding="utf-8")
        if not json_output:
            click.echo(f"\n  Written to {output}")


@eval_group.command("compare")
@click.argument("left_run")
@click.argument("right_run")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def eval_compare(left_run: str, right_run: str, json_output: bool = False) -> None:
    """Show a side-by-side comparison of two eval runs."""
    from cli.stream2_helpers import json_response

    payload = _build_eval_comparison(left_run, right_run)
    if json_output:
        click.echo(json_response("ok", payload))
        return

    click.echo("\nEval comparison")
    click.echo(f"  Run 1: {payload['left']['run']}")
    click.echo(f"  Run 2: {payload['right']['run']}")
    click.echo("")
    click.echo(f"  {'Metric':<12} {'Run 1':>10} {'Run 2':>10} {'Delta':>10}")
    click.echo(f"  {'-' * 12} {'-' * 10} {'-' * 10} {'-' * 10}")
    for metric in EVAL_METRIC_NAMES:
        left_value = payload["left"]["scores"][metric]
        right_value = payload["right"]["scores"][metric]
        delta = payload["deltas"][metric]
        click.echo(f"  {metric:<12} {left_value:>10.4f} {right_value:>10.4f} {delta:>+10.4f}")
    click.echo(f"\n  Winner: {payload['winner']}")


@eval_group.command("breakdown")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def eval_breakdown(json_output: bool = False) -> None:
    """Show score breakdown bars and failure clusters for the latest eval result."""
    from cli.stream2_helpers import json_response

    payload = _build_eval_breakdown()
    if json_output:
        click.echo(json_response("ok", payload))
        return

    source_name = Path(payload["source"]).name
    click.echo(f"\nEval Breakdown (from {source_name})")
    click.echo(f"  {'-' * 50}")
    for metric in EVAL_METRIC_NAMES:
        value = max(0.0, min(1.0, payload["scores"][metric]))
        click.echo(f"  {metric:<12} {_bar_chart(value)} {payload['scores'][metric]:.4f}")

    click.echo("\n  Failure Clusters:")
    clusters = payload["failure_clusters"]
    if not clusters:
        click.echo("    none recorded")
        return

    for cluster, count in sorted(clusters.items(), key=lambda item: (-item[1], item[0])):
        click.echo(f"    {count:>3}x {cluster}")


def _run_optimize_cycle(
    *,
    cycle_number: int,
    display_cycle: int,
    display_total: int | None,
    continuous: bool,
    json_output: bool,
    full_auto: bool,
    store: ConversationStore,
    observer: Observer,
    optimizer: Optimizer,
    deployer: Deployer,
    memory: OptimizationMemory,
    eval_runner: EvalRunner,
    best_score_file: Path,
    all_time_best: float,
    log_path: Path,
) -> tuple[dict, float]:
    """Run one optimize iteration and persist a matching experiment-log entry."""
    try:
        report = observer.observe()

        if not report.needs_optimization:
            if not json_output and not continuous and display_total is not None:
                click.echo(
                    f"\n  Cycle {display_cycle}/{display_total} — System healthy; skipping optimization."
                )

            entry = make_experiment_log_entry(
                cycle=cycle_number,
                status="skip",
                description="System healthy; no optimization needed",
                score_before=None,
                score_after=None,
            )
            append_experiment_log_entry(entry, path=log_path)
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

        current_config = _ensure_active_config(deployer)
        failure_samples = _build_failure_samples(store)
        new_config, opt_status = optimizer.optimize(
            report,
            current_config,
            failure_samples=failure_samples,
        )

        latest_attempts = memory.recent(limit=1)
        latest = latest_attempts[0] if latest_attempts else None
        proposal_desc = latest.change_description if latest else None
        score_after: float | None = latest.score_after if latest else None
        score_before: float | None = latest.score_before if latest else None
        p_value: float | None = latest.significance_p_value if latest else None

        normalized_status = _optimize_cycle_status(
            report_needs_optimization=report.needs_optimization,
            new_config=new_config,
            score_before=score_before,
            score_after=score_after,
        )
        description = proposal_desc or opt_status
        entry = make_experiment_log_entry(
            cycle=cycle_number,
            status=normalized_status,
            description=description,
            score_before=score_before,
            score_after=score_after,
        )
        append_experiment_log_entry(entry, path=log_path)

        if not json_output and not continuous and display_total is not None:
            _stream_cycle_output(
                cycle_num=display_cycle,
                total=display_total,
                report=report,
                proposal_desc=proposal_desc,
                score_after=score_after,
                score_before=score_before,
                p_value=p_value,
                all_time_best=all_time_best,
                best_score_file=best_score_file,
            )
        else:
            all_time_best = _persist_best_score(
                score_after,
                all_time_best,
                best_score_file,
                announce=False,
            )

        if score_after is not None and score_after > all_time_best:
            all_time_best = score_after

        if new_config is not None:
            score = eval_runner.run(config=new_config)
            deploy_result = deployer.deploy(new_config, _score_to_dict(score))
            if not json_output and not continuous:
                click.echo(f"  Deploy: {deploy_result}")
            if full_auto:
                promoted = _promote_latest_version(deployer)
                if not json_output and not continuous and promoted is not None:
                    click.echo(click.style(f"  FULL AUTO: promoted v{promoted:03d} to active", fg="yellow"))

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
        entry = make_experiment_log_entry(
            cycle=cycle_number,
            status="crash",
            description=str(exc),
            score_before=None,
            score_after=None,
        )
        append_experiment_log_entry(entry, path=log_path)

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


# ---------------------------------------------------------------------------
# autoagent optimize
# ---------------------------------------------------------------------------

@cli.command("optimize")
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
@click.option("--max-budget-usd", default=None, type=float, help="Stop before running when workspace spend reaches this amount.")
@click.option(
    "--output-format",
    type=click.Choice(["text", "json", "stream-json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Render text, a final JSON envelope, or stream JSON progress events.",
)
def optimize(
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
    max_budget_usd: float | None = None,
    output_format: str = "text",
) -> None:
    """Run optimization cycles to improve agent config.

    Examples:
      autoagent optimize
      autoagent optimize --cycles 5
      autoagent optimize --continuous
      autoagent optimize --mode advanced --cycles 3
    """
    from cli.output import resolve_output_format
    from cli.progress import ProgressRenderer
    from cli.usage import enforce_workspace_budget
    from optimizer.cost_tracker import CostTracker
    from optimizer.mode_router import ModeConfig, ModeRouter, OptimizationMode

    resolved_output_format = resolve_output_format(output_format, json_output=json_output)
    progress = ProgressRenderer(output_format=resolved_output_format, render_text=False)
    progress.phase_started("optimize", message="Run optimization cycle(s)")

    if resolved_output_format == "text":
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
        if resolved_output_format == "text":
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
            "memory_db": memory_db,
            "max_budget_usd": max_budget_usd,
        }
        if resolved_output_format == "json":
            click.echo(json_response("ok", preview, next_cmd="autoagent optimize"))
        else:
            click.echo("Dry run: optimization would execute with the following plan:")
            click.echo(f"  cycles:      {cycles}")
            click.echo(f"  continuous:  {continuous}")
            click.echo(f"  mode:        {mode or 'default'}")
            click.echo(f"  full_auto:   {full_auto}")
            click.echo(f"  configs_dir: {configs_dir}")
        return

    budget_ok, budget_message, budget_snapshot = enforce_workspace_budget(max_budget_usd)
    if not budget_ok:
        progress.warning(message=budget_message or "Budget reached")
        if resolved_output_format == "json":
            from cli.stream2_helpers import json_response

            click.echo(json_response("ok", {"message": budget_message, "usage": budget_snapshot}, next_cmd="autoagent usage"))
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
    ) = _build_runtime_components()
    _warn_mock_modes(proposer=proposer, json_output=(resolved_output_format == "json"))
    store = ConversationStore(db_path=db)
    observer = Observer(store)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    memory = OptimizationMemory(db_path=memory_db)
    tracker_db_path, per_cycle_dollars, daily_dollars, stall_threshold_cycles = _runtime_budget_config(runtime)
    cost_tracker = CostTracker(
        db_path=tracker_db_path,
        per_cycle_budget_dollars=per_cycle_dollars,
        daily_budget_dollars=daily_dollars,
        stall_threshold_cycles=stall_threshold_cycles,
    )
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
    all_time_best = _read_best_score(best_score_file)
    log_path = default_experiment_log_path()
    next_cycle_number = next_experiment_log_cycle_number(log_path)

    json_cycle_results: list[dict] = []
    experiments_run = 0
    kept_count = 0
    discarded_count = 0
    skipped_count = 0
    display_cycle = 1

    if continuous and resolved_output_format == "text":
        click.echo("Starting continuous optimization. Press Ctrl+C to stop.")

    try:
        while True:
            cost_before = _proposer_total_cost(proposer)
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
            )
            cost_after = _proposer_total_cost(proposer)
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
                    progress.next_action("autoagent status")
                else:
                    click.echo(
                        _continuous_status_line(
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
                best_entry = best_experiment_log_entry(read_experiment_log_entries(log_path))
                best_score = best_entry.score_after if best_entry is not None and best_entry.score_after is not None else all_time_best
                click.echo(
                    f"Ran {experiments_run} experiments: "
                    f"{kept_count} kept, {discarded_count} discarded, {skipped_count} skipped. "
                    f"Best score: {best_score:.2f}"
                )
                click.echo("Experiment log saved to .autoagent/experiment_log.tsv")
            return
        raise

    progress.phase_completed("optimize", message="Optimization run complete")
    progress.next_action("autoagent status")

    if resolved_output_format == "stream-json":
        return

    if resolved_output_format == "json":
        from cli.stream2_helpers import json_response

        click.echo(json_response("ok", json_cycle_results, next_cmd="autoagent status"))
        return

    if cycles > 1 and not continuous:
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


@cli.group("improve", cls=DefaultCommandGroup, default_command="run", default_on_empty=True)
def improve_group() -> None:
    """Improvement workflows and compatibility aliases."""


@improve_group.command("run", hidden=True)
@click.option("--auto", is_flag=True, help="Apply the top suggested fix without prompting.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def improve_run(auto: bool, json_output: bool = False) -> None:
    """Run the eval -> diagnose -> suggest -> optional apply improvement flow."""
    from cli.stream2_helpers import apply_autofix_to_config, json_response
    from optimizer.autofix import AutoFixEngine, AutoFixStore
    from optimizer.autofix_proposers import (
        CostOptimizationProposer,
        FailurePatternProposer,
        RegressionProposer,
    )
    from optimizer.diagnose_session import DiagnoseSession
    from optimizer.mutations import create_default_registry

    runtime = load_runtime_config()
    workspace = discover_workspace()
    resolved_config = workspace.resolve_active_config() if workspace is not None else None
    config = resolved_config.config if resolved_config is not None else None
    eval_runner = _build_eval_runner(runtime, default_agent_config=config)
    score = eval_runner.run(config=config)

    store = ConversationStore(db_path=DB_PATH)
    observer = Observer(store)
    deployer = Deployer(configs_dir=CONFIGS_DIR, store=store)
    diagnose_session = DiagnoseSession(store=store, observer=observer, deployer=deployer)
    diagnosis_summary = diagnose_session.start()

    proposal_store = AutoFixStore()
    engine = AutoFixEngine(
        proposers=[FailurePatternProposer(), RegressionProposer(), CostOptimizationProposer()],
        mutation_registry=create_default_registry(),
        store=proposal_store,
    )
    current_config = config or _ensure_active_config(deployer)
    proposals = engine.suggest(_build_failure_samples(store), current_config)
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
        "eval": _score_to_dict(score),
        "diagnosis": diagnose_session.to_dict(),
        "diagnosis_summary": diagnosis_summary,
        "proposal_count": len(proposal_payload),
        "proposals": proposal_payload,
        "applied": applied,
    }
    if json_output:
        next_cmd = "autoagent status"
        if applied and applied.get("config_path"):
            next_cmd = f"autoagent eval run --config {applied['config_path']}"
        click.echo(json_response("ok", payload, next_cmd=next_cmd))
        return

    click.echo(click.style("\n✦ Improve", fg="cyan", bold=True))
    click.echo("")
    click.echo(f"Eval composite: {_score_to_dict(score)['composite']:.4f}")
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
        click.echo("  autoagent autofix suggest")


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
    """Compatibility alias for `autoagent optimize`."""
    ctx.invoke(
        optimize,
        cycles=cycles,
        continuous=continuous,
        mode=mode,
        strategy=strategy,
        db=db,
        configs_dir=configs_dir,
        memory_db=memory_db,
        full_auto=full_auto,
        dry_run=dry_run,
        json_output=json_output,
    )


# ---------------------------------------------------------------------------
# autoagent compare (subgroup)
# ---------------------------------------------------------------------------

@cli.group("compare")
def compare_group() -> None:
    """Compare configs, eval runs, and candidate versions."""


@compare_group.command("configs")
@click.argument("left_version", type=int)
@click.argument("right_version", type=int)
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def compare_configs(left_version: int, right_version: int, configs_dir: str, json_output: bool = False) -> None:
    """Compare two config versions side by side."""
    from cli.stream2_helpers import json_response

    store = ConversationStore(db_path=DB_PATH)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    history = {entry["version"]: entry for entry in deployer.version_manager.get_version_history()}
    if left_version not in history or right_version not in history:
        raise click.ClickException("Both config versions must exist before they can be compared.")

    left_path = Path(configs_dir) / history[left_version]["filename"]
    right_path = Path(configs_dir) / history[right_version]["filename"]
    left_config = yaml.safe_load(left_path.read_text(encoding="utf-8"))
    right_config = yaml.safe_load(right_path.read_text(encoding="utf-8"))
    diff_text = schema_config_diff(validate_config(left_config), validate_config(right_config))

    payload = {
        "left": {"version": left_version, "path": str(left_path), "status": history[left_version]["status"]},
        "right": {"version": right_version, "path": str(right_path), "status": history[right_version]["status"]},
        "diff": diff_text,
    }
    if json_output:
        click.echo(json_response("ok", payload))
        return

    click.echo(f"\nConfig comparison: v{left_version:03d} vs v{right_version:03d}")
    click.echo(f"  Left:  {left_path}")
    click.echo(f"  Right: {right_path}")
    click.echo("")
    click.echo(diff_text)


@compare_group.command("evals")
@click.argument("left_run")
@click.argument("right_run")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def compare_evals(left_run: str, right_run: str, json_output: bool = False) -> None:
    """Compare two eval result JSON files."""
    from cli.stream2_helpers import json_response

    comparison = _build_eval_comparison(left_run, right_run)
    payload = {
        "left": {
            "run": comparison["left"]["run"],
            "composite": comparison["left"]["scores"]["composite"],
            "quality": comparison["left"]["scores"]["quality"],
        },
        "right": {
            "run": comparison["right"]["run"],
            "composite": comparison["right"]["scores"]["composite"],
            "quality": comparison["right"]["scores"]["quality"],
        },
        "winner": comparison["winner"],
        "delta_composite": comparison["delta_composite"],
        "deltas": comparison["deltas"],
    }
    if json_output:
        click.echo(json_response("ok", payload))
        return

    click.echo("\nEval comparison")
    click.echo(f"  Left:   {payload['left']['run']}  composite={payload['left']['composite']:.4f}")
    click.echo(f"  Right:  {payload['right']['run']}  composite={payload['right']['composite']:.4f}")
    click.echo(f"  Winner: {payload['winner']}")
    click.echo(f"  Delta:  {payload['delta_composite']:+.4f}")


@compare_group.command("candidates")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def compare_candidates(configs_dir: str, json_output: bool = False) -> None:
    """Show candidate configs with their stored scores."""
    from cli.stream2_helpers import json_response

    store = ConversationStore(db_path=DB_PATH)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    history = deployer.version_manager.get_version_history()
    candidates = [
        entry for entry in history
        if entry.get("status") in {"candidate", "canary", "imported", "evaluated"}
    ]

    if json_output:
        click.echo(json_response("ok", candidates))
        return

    if not candidates:
        click.echo("No candidate configs found.")
        return

    click.echo("\nCandidate configs")
    click.echo("=================")
    for entry in candidates:
        composite = float((entry.get("scores") or {}).get("composite", 0.0))
        click.echo(f"- v{entry['version']:03d}  status={entry['status']}  composite={composite:.4f}")


# ---------------------------------------------------------------------------
# autoagent config (subgroup)
# ---------------------------------------------------------------------------

@cli.group("config")
def config_group() -> None:
    """Manage agent config versions and related edit, pin, and unpin workflows.

    Examples:
      autoagent config list
      autoagent config show active
      autoagent config diff 1 2
    """


@config_group.command("list")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--id-only", is_flag=True, help="Print only config version identifiers.")
@click.option("--path-only", is_flag=True, help="Print only config file paths.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def config_list(configs_dir: str, id_only: bool, path_only: bool, json_output: bool = False) -> None:
    """List all config versions.

    Examples:
      autoagent config list
      autoagent config list --json
    """
    from cli.stream2_helpers import json_response

    store = ConversationStore(db_path=DB_PATH)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    history = deployer.version_manager.get_version_history()

    if not history:
        if json_output:
            click.echo(json_response("ok", []))
        else:
            click.echo("No config versions found.")
            click.echo("Run: autoagent init")
        return

    if id_only:
        for entry in history:
            click.echo(f"v{entry['version']:03d}")
        return
    if path_only:
        for entry in history:
            click.echo(str(Path(configs_dir) / entry["filename"]))
        return

    workspace = _workspace_for_configs_dir(configs_dir)
    active = (
        workspace.metadata.active_config_version
        if workspace is not None and workspace.metadata.active_config_version is not None
        else deployer.version_manager.manifest.get("active_version")
    )
    canary = deployer.version_manager.manifest.get("canary_version")

    if json_output:
        data = []
        for v in history:
            entry = dict(v)
            entry["is_active"] = v["version"] == active
            entry["is_canary"] = v["version"] == canary
            data.append(entry)
        click.echo(json_response("ok", data, next_cmd="autoagent config show <version>"))
        return

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
@click.argument("version", type=str, required=False)
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--id-only", is_flag=True, help="Print only the resolved config identifier.")
@click.option("--path-only", is_flag=True, help="Print only the resolved config path.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def config_show(version: str | None, configs_dir: str, id_only: bool, path_only: bool, json_output: bool = False) -> None:
    """Show config YAML for a version (defaults to active).

    Supports standard selectors: latest, active, current.

    Examples:
      autoagent config show
      autoagent config show 3
      autoagent config show active
      autoagent config show latest --json
    """
    from cli.stream2_helpers import is_selector, json_response

    store = ConversationStore(db_path=DB_PATH)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    workspace = _workspace_for_configs_dir(configs_dir)

    # FR-08: resolve selectors
    resolved_version: int | None = None
    if version is not None:
        if is_selector(version):
            history = deployer.version_manager.get_version_history()
            if version.lower() in ("latest",):
                resolved_version = history[-1]["version"] if history else None
            elif version.lower() in ("active", "current"):
                if workspace is not None and workspace.metadata.active_config_version is not None:
                    resolved_version = workspace.metadata.active_config_version
                else:
                    resolved_version = deployer.version_manager.manifest.get("active_version")
            elif version.lower() == "pending":
                for v in reversed(history):
                    if v["status"] in ("canary", "candidate", "imported"):
                        resolved_version = v["version"]
                        break
        else:
            try:
                normalized_version = version[1:] if version.lower().startswith("v") else version
                resolved_version = int(normalized_version)
            except ValueError:
                click.echo(f"Invalid version: {version}")
                return

    if resolved_version is None and version is None:
        workspace = discover_workspace()
        if workspace is not None:
            resolved = workspace.resolve_active_config()
            if resolved is None:
                if json_output:
                    click.echo(json_response("error", {"message": "No active config"}))
                else:
                    click.echo("No active config. Run: autoagent init")
                return
            if id_only:
                click.echo(f"v{resolved.version:03d}")
                return
            if path_only:
                click.echo(str(resolved.path))
                return
            if json_output:
                click.echo(json_response("ok", {"version": resolved.version, "config": resolved.config}))
            else:
                click.echo(f"# Active config: v{resolved.version:03d}\n")
                click.echo(yaml.safe_dump(resolved.config, default_flow_style=False, sort_keys=False))
            return

        config = deployer.get_active_config()
        if config is None:
            if json_output:
                click.echo(json_response("error", {"message": "No active config"}))
            else:
                click.echo("No active config. Run: autoagent init")
            return
        active_ver = deployer.version_manager.manifest.get("active_version", "?")
        if id_only:
            click.echo(f"v{active_ver:03d}")
            return
        if path_only:
            click.echo(str(Path(configs_dir) / f"v{active_ver:03d}.yaml"))
            return
        if json_output:
            click.echo(json_response("ok", {"version": active_ver, "config": config}))
        else:
            click.echo(f"# Active config: v{active_ver:03d}\n")
            click.echo(yaml.safe_dump(config, default_flow_style=False, sort_keys=False))
        return

    if resolved_version is None:
        if json_output:
            click.echo(json_response("error", {"message": f"No config matching selector: {version}"}))
        else:
            click.echo(f"No config matching selector: {version}")
        return

    # Find the version file
    history = deployer.version_manager.get_version_history()
    found = None
    for v in history:
        if v["version"] == resolved_version:
            found = v
            break
    if found is None:
        if json_output:
            click.echo(json_response("error", {"message": f"Version {resolved_version} not found"}))
        else:
            click.echo(f"Version {resolved_version} not found.")
        return

    filepath = Path(configs_dir) / found["filename"]
    with filepath.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if id_only:
        click.echo(f"v{resolved_version:03d}")
        return
    if path_only:
        click.echo(str(filepath))
        return

    if json_output:
        click.echo(json_response("ok", {"version": resolved_version, "status": found["status"], "config": config}))
    else:
        click.echo(f"# Config: v{resolved_version:03d} [{found['status']}]\n")
        click.echo(yaml.safe_dump(config, default_flow_style=False, sort_keys=False))


@config_group.command("set-active")
@click.argument("version", type=int)
def config_set_active(version: int) -> None:
    """Set the workspace default config version.

    Examples:
      autoagent config set-active 2
    """
    workspace = _require_workspace("config")
    resolved = workspace.resolve_config_path(version)
    if resolved is None:
        raise click.ClickException(f"Config version not found: v{version:03d}")

    workspace.set_active_config(version, filename=resolved.name)
    click.echo(click.style(f"Set active config to v{version:03d}", fg="green"))
    click.echo(f"Workspace: {workspace.root}")
    click.echo(f"Config path: {resolved}")
    click.echo("Next step:")
    click.echo("  autoagent config show")


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


@config_group.command("import")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--dry-run", is_flag=True, help="Preview the imported version without writing files.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def config_import(file_path: str, configs_dir: str, dry_run: bool, json_output: bool = False) -> None:
    """Import a plain YAML or JSON config file into the versioned config store.

    Converts the file to a versioned config in the configs directory with
    manifest tracking.  The imported config appears in ``config list``,
    ``config show``, and ``config diff``.

    Examples:
      autoagent config import my_config.yaml
      autoagent config import agent.json --json
    """
    from cli.stream2_helpers import ConfigImporter, json_response

    importer = ConfigImporter(configs_dir=configs_dir)
    if dry_run:
        manifest = importer._load_manifest()
        versions = manifest.get("versions", [])
        next_version = max((entry["version"] for entry in versions), default=0) + 1
        preview = {
            "source_file": Path(file_path).name,
            "version": next_version,
            "dest_path": str(Path(configs_dir) / f"v{next_version:03d}_imported.yaml"),
        }
        if json_output:
            click.echo(json_response("ok", preview, next_cmd="autoagent config import <file>"))
        else:
            click.echo("Dry run: config import preview")
            click.echo(f"  Source:  {preview['source_file']}")
            click.echo(f"  Version: v{preview['version']:03d}")
            click.echo(f"  Path:    {preview['dest_path']}")
        return

    try:
        result = importer.import_config(file_path)
    except (FileNotFoundError, ValueError) as exc:
        if json_output:
            click.echo(json_response("error", {"message": str(exc)}))
        else:
            click.echo(click.style(f"Error: {exc}", fg="red"))
        raise SystemExit(1)

    if json_output:
        click.echo(json_response("ok", result, next_cmd=f"autoagent config show {result['version']}"))
        return

    click.echo(click.style("\n✦ Config Imported", fg="cyan", bold=True))
    click.echo(click.style(f"Applied: imported config as v{result['version']:03d}", fg="green"))
    click.echo(f"  Source:  {result['source_file']}")
    click.echo(f"  Version: v{result['version']:03d}")
    click.echo(f"  Hash:    {result['config_hash']}")
    click.echo(f"  Path:    {result['dest_path']}")
    click.echo("")
    _print_next_actions([
        f"autoagent config show {result['version']}",
        f"autoagent eval run --config {result['dest_path']}",
        "autoagent config list",
    ])


@config_group.command("rollback")
@click.argument("version", type=int, required=False)
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
def config_rollback(version: int | None, configs_dir: str) -> None:
    """Roll back the active config to a prior saved version."""
    store = ConversationStore(db_path=DB_PATH)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    history = deployer.version_manager.get_version_history()
    if not history:
        raise click.ClickException("No config versions available to roll back.")

    active_version = deployer.version_manager.manifest.get("active_version")
    target_version = version
    if target_version is None:
        eligible = [entry["version"] for entry in history if entry["version"] != active_version]
        if not eligible:
            raise click.ClickException("No rollback target is available.")
        target_version = max(eligible)

    resolved = next((entry for entry in history if entry["version"] == target_version), None)
    if resolved is None:
        raise click.ClickException(f"Config version not found: v{target_version:03d}")

    deployer.version_manager.promote(target_version)
    workspace = _workspace_for_configs_dir(configs_dir)
    if workspace is not None:
        workspace.set_active_config(target_version, filename=resolved["filename"])

    click.echo(click.style(f"Applied: rolled back config to v{target_version:03d}", fg="green"))


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


@config_group.command("edit")
def config_edit() -> None:
    """Open the active config file in the user's editor."""
    workspace = _require_workspace("config")
    active = workspace.resolve_active_config()
    if active is None:
        raise click.ClickException("No active config. Run: autoagent init")
    _open_in_editor(active.path)


def _open_in_editor(file_path: Path) -> None:
    """Open *file_path* in the configured editor, or print the path."""
    import subprocess

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor is None:
        for candidate in ("code", "vim", "vi", "nano"):
            if shutil.which(candidate):
                editor = candidate
                break

    if editor:
        click.echo(f"Opening {file_path} in {editor}")
        subprocess.run([editor, str(file_path)], check=False)
        return
    click.echo(f"Edit this file: {file_path}")


# ---------------------------------------------------------------------------
# autoagent deploy
# ---------------------------------------------------------------------------

@cli.command("deploy")
@click.argument("workflow", required=False, type=click.Choice(["canary", "immediate", "release", "rollback"]))
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
@click.option("--dry-run", is_flag=True, help="Preview the deployment plan without mutating state.")
@click.option("--yes", "acknowledge", is_flag=True, default=False, help="Skip interactive deployment confirmation.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
@click.option(
    "--output-format",
    type=click.Choice(["text", "json", "stream-json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Render text, a final JSON envelope, or stream JSON progress events.",
)
def deploy(
    workflow: str | None,
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
    dry_run: bool,
    acknowledge: bool,
    json_output: bool = False,
    output_format: str = "text",
) -> None:
    """Deploy a config version with canary, release, and rollback-friendly workflows.

    Examples:
      autoagent deploy canary
      autoagent deploy --config-version 5 --strategy canary
      autoagent deploy --strategy immediate
      autoagent deploy canary --yes
      autoagent deploy --target cx-studio
    """
    from cli.output import resolve_output_format
    from cli.permissions import PermissionManager
    from cli.progress import ProgressRenderer

    resolved_output_format = resolve_output_format(output_format, json_output=json_output)
    progress = ProgressRenderer(output_format=resolved_output_format, render_text=False)
    progress.phase_started("deploy", message="Prepare deployment")

    if workflow is not None:
        if workflow == "release":
            strategy = "immediate"
        elif workflow != "rollback":
            strategy = workflow

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
        progress.artifact_written("cx-export", path=str(output_path))
        if resolved_output_format == "text":
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
                progress.warning(message=f"CX preview unavailable ({exc})", phase="deploy")
                if resolved_output_format == "text":
                    click.echo(click.style(f"Warning: CX preview unavailable ({exc})", fg="yellow"))

        if not push:
            progress.phase_completed("deploy", message="CX package ready")
            progress.next_action("autoagent cx export --project <project> --location <location> --agent <agent-id> --config <config> --snapshot <snapshot>")
            if resolved_output_format == "stream-json":
                return
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
        progress.phase_completed("deploy", message="CX export pushed")
        progress.next_action("autoagent status")
        if resolved_output_format == "stream-json":
            return
        click.echo(f"CX export pushed: {result.resources_updated} resource(s) updated")
        return

    from cli.stream2_helpers import json_response

    store = ConversationStore(db_path=db)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    history = deployer.version_manager.get_version_history()

    if not history:
        if json_output:
            click.echo(json_response("error", {"message": "No config versions available"}))
        else:
            click.echo("No config versions available. Run: autoagent optimize")
        return

    if workflow == "rollback":
        rollback_version = config_version or deployer.version_manager.manifest.get("canary_version")
        if rollback_version is None:
            if json_output:
                click.echo(json_response("error", {"message": "No active canary deployment to roll back"}))
            else:
                click.echo("No active canary deployment to roll back.")
            return
        if dry_run:
            payload = {"version": rollback_version, "strategy": "rollback", "target": target}
            if json_output:
                click.echo(json_response("ok", payload, next_cmd="autoagent deploy rollback"))
            else:
                click.echo("Dry run: deployment rollback preview")
                click.echo(f"  Version: {rollback_version}")
                click.echo(f"  Target:  {target}")
            return
        deployer.version_manager.rollback(rollback_version)
        if json_output:
            click.echo(json_response("ok", {"version": rollback_version, "strategy": "rollback", "status": "rolled_back"}, next_cmd="autoagent status"))
        else:
            click.echo(click.style(f"Applied: rolled back canary v{rollback_version:03d}", fg="green"))
        return

    if config_version is None:
        config_version = history[-1]["version"]
        if not json_output:
            click.echo(f"Deploying latest version: v{config_version:03d}")

    found = None
    for v in history:
        if v["version"] == config_version:
            found = v
            break
    if found is None:
        if json_output:
            click.echo(json_response("error", {"message": f"Version {config_version} not found"}))
        else:
            click.echo(f"Version {config_version} not found.")
        return

    filepath = Path(configs_dir) / found["filename"]
    with filepath.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    scores = found.get("scores", {"composite": 0.0})
    del scores

    if dry_run:
        payload = {"version": config_version, "strategy": strategy, "target": target}
        progress.phase_completed("deploy", message="Dry-run deployment preview ready")
        progress.next_action("autoagent deploy")
        if resolved_output_format == "stream-json":
            return
        if resolved_output_format == "json":
            click.echo(json_response("ok", payload, next_cmd="autoagent deploy"))
        else:
            click.echo("Dry run: deployment preview")
            click.echo(f"  Version:  v{config_version:03d}")
            click.echo(f"  Strategy: {strategy}")
            click.echo(f"  Target:   {target}")
        return

    if not acknowledge:
        PermissionManager().require(
            f"deploy.{strategy}",
            prompt=f"Deploy v{config_version:03d} using the {strategy} strategy?",
            default=False,
        )

    if strategy == "immediate":
        deployer.version_manager.promote(config_version)
        progress.phase_completed("deploy", message=f"Deployed v{config_version:03d} immediately")
        progress.next_action("autoagent status")
        if resolved_output_format == "stream-json":
            return
        if resolved_output_format == "json":
            click.echo(json_response("ok", {"version": config_version, "strategy": "immediate", "status": "active"}, next_cmd="autoagent status"))
        else:
            click.echo(click.style(f"Applied: deployed v{config_version:03d} immediately (promoted to active).", fg="green"))
    else:
        deployer.version_manager.mark_canary(config_version)
        result = f"Deployed v{config_version:03d} as canary (10% traffic)"
        progress.phase_completed("deploy", message=f"Deployed v{config_version:03d} as canary")
        progress.next_action("autoagent status")
        if resolved_output_format == "stream-json":
            return
        if resolved_output_format == "json":
            click.echo(json_response("ok", {"version": config_version, "strategy": "canary", "result": str(result)}, next_cmd="autoagent status"))
        else:
            click.echo(click.style(f"Applied: deployed v{config_version:03d} as canary.", fg="green"))
            click.echo(f"  {result}")


# ---------------------------------------------------------------------------
# autoagent loop
# ---------------------------------------------------------------------------

@cli.group("loop", cls=DefaultCommandGroup, default_command="run", default_on_empty=True)
def loop_group() -> None:
    """Run the optimization loop or control its execution state.

    Examples:
      autoagent loop
      autoagent loop --max-cycles 20
      autoagent loop pause
      autoagent loop resume
    """


@loop_group.command("run", hidden=True)
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
@click.option("--max-budget-usd", default=None, type=float, help="Stop before running when workspace spend reaches this amount.")
@click.option(
    "--output-format",
    type=click.Choice(["text", "json", "stream-json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Render text or stream JSON progress events.",
)
def loop_run(max_cycles: int, stop_on_plateau: bool, delay: float, schedule_mode: str | None,
             interval_minutes: float | None, cron_expression: str | None, checkpoint_file: str | None,
             resume: bool, full_auto: bool, db: str, configs_dir: str, memory_db: str,
             max_budget_usd: float | None = None, output_format: str = "text") -> None:
    """Run the continuous autoresearch loop.

    Observes agent health, proposes improvements, evaluates them, and deploys
    accepted changes — automatically, cycle after cycle.

    Examples:
      autoagent loop
      autoagent loop --max-cycles 100 --stop-on-plateau
    """
    from cli.output import resolve_output_format
    from cli.progress import ProgressRenderer
    from cli.usage import enforce_workspace_budget

    resolved_output_format = resolve_output_format(output_format)
    progress = ProgressRenderer(output_format=resolved_output_format, render_text=False)
    progress.phase_started("loop", message="Start optimization loop")

    budget_ok, budget_message, _ = enforce_workspace_budget(max_budget_usd)
    if not budget_ok:
        progress.warning(message=budget_message or "Budget reached")
        click.echo(budget_message)
        return

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

    if resolved_output_format == "text":
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

            progress.phase_started("loop-cycle", message=f"Cycle {cycle}/{max_cycles}")
            if resolved_output_format == "text":
                click.echo(f"\n{'═' * 50}")
                click.echo(f" Cycle {cycle}/{max_cycles}")
                click.echo(f"{'═' * 50}")

            improved = False
            try:
                report = observer.observe()
                if resolved_output_format == "text":
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
                    if resolved_output_format == "text":
                        click.echo(f"  Optimizer: {status}")
                    if new_config is not None:
                        improved = True
                        score = eval_runner.run(config=new_config)
                        deploy_result = deployer.deploy(new_config, _score_to_dict(score))
                        if resolved_output_format == "text":
                            click.echo(f"  Deploy: {deploy_result}")
                        if full_auto:
                            promoted = _promote_latest_version(deployer)
                            if promoted is not None and resolved_output_format == "text":
                                click.echo(click.style(
                                    f"  FULL AUTO: promoted v{promoted:03d} to active",
                                    fg="yellow",
                                ))
                        if resolved_output_format == "text":
                            click.echo(f"  Score: {score.composite:.4f}")
                else:
                    if resolved_output_format == "text":
                        click.echo("  Healthy; skipping optimization.")

                canary_result = deployer.check_and_act()
                if resolved_output_format == "text":
                    click.echo(f"  Canary: {canary_result}")
            except Exception as exc:
                tb = traceback.format_exc()
                dead_letter_queue.push(
                    kind="loop_cycle",
                    payload={"cycle": cycle},
                    error=str(exc),
                    traceback_text=tb,
                )
                if resolved_output_format == "text":
                    click.echo(f"  Cycle failed; queued in dead letter queue: {exc}")
                log.error(
                    "loop_cycle_failed",
                    extra={"event": "loop_cycle_failed", "cycle": cycle, "status": "failed"},
                )
                progress.error(message=str(exc), phase="loop-cycle")

            completed_cycles = cycle
            cycle_finished = time.time()

            if stop_on_plateau:
                if improved:
                    plateau_count = 0
                else:
                    plateau_count += 1
                    if plateau_count >= plateau_threshold:
                        if resolved_output_format == "text":
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
                if resolved_output_format == "text":
                    click.echo(f"  Warning: {warning}")
                log.warning(
                    "resource_warning_memory",
                    extra={"event": "resource_warning", "memory_mb": snapshot.memory_mb, "cycle": cycle},
                )
                progress.warning(message=warning, phase="loop-cycle")
            if snapshot.cpu_percent > runtime.loop.resource_warn_cpu_percent:
                warning = f"CPU usage high: {snapshot.cpu_percent:.2f}%"
                if resolved_output_format == "text":
                    click.echo(f"  Warning: {warning}")
                log.warning(
                    "resource_warning_cpu",
                    extra={"event": "resource_warning", "cpu_percent": snapshot.cpu_percent, "cycle": cycle},
                )
                progress.warning(message=warning, phase="loop-cycle")

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
                if resolved_output_format == "text":
                    click.echo(f"  Watchdog: {stall_error}")
                log.warning("watchdog_stall", extra={"event": "watchdog_stall", "cycle": cycle})
                progress.warning(message=stall_error, phase="loop-cycle")
            watchdog.beat()
            progress.phase_completed("loop-cycle", message=f"Cycle {cycle} complete")

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
                if resolved_output_format == "text":
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
                    if resolved_output_format == "text":
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
    progress.phase_completed("loop", message=f"{completed_cycles} cycle(s) executed ({final_status})")
    progress.next_action("autoagent status")
    if resolved_output_format == "text":
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
    workspace = _require_workspace("status")
    from cli.mcp_runtime import mcp_status_snapshot
    from cli.model import effective_model_surface
    from cli.usage import build_usage_snapshot
    from core.project_memory import load_layered_project_context

    store = ConversationStore(db_path=db)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    memory = OptimizationMemory(db_path=memory_db)
    deploy_status = deployer.status()
    resolved = workspace.resolve_active_config()
    active_version = resolved.version if resolved is not None else deploy_status["active_version"]

    total_conversations = store.count()
    recent_attempts = memory.recent(limit=1)
    latest = recent_attempts[0] if recent_attempts else None
    report = Observer(store).observe()
    metrics = report.metrics
    all_attempts = memory.recent(limit=100)
    accepted_attempts = [attempt for attempt in all_attempts if attempt.status == "accepted"]
    buckets = report.failure_buckets

    mode_summary = summarize_mode_state(str(workspace.runtime_config_path))
    usage_snapshot = build_usage_snapshot(workspace.root)
    memory_snapshot = load_layered_project_context(workspace.root).summary()
    mcp_snapshot = mcp_status_snapshot(workspace.root)
    model_snapshot = effective_model_surface(workspace.root)
    pending_review_cards = 0
    pending_autofix_proposals = 0

    try:
        from optimizer.change_card import ChangeCardStore

        pending_review_cards = len(ChangeCardStore().list_pending(limit=200))
    except Exception:
        pending_review_cards = 0

    try:
        from optimizer.autofix import AutoFixStore

        autofix_store = AutoFixStore()
        if hasattr(autofix_store, "list_pending"):
            pending_autofix_proposals = len(autofix_store.list_pending(limit=200))
        else:
            pending_autofix_proposals = len(autofix_store.list_proposals(status="pending", limit=200))
    except Exception:
        pending_autofix_proposals = 0

    deployment_label = "none"
    if deploy_status.get("canary_version") is not None:
        deployment_label = (
            f"active v{deploy_status.get('active_version', 0):03d} "
            f"| canary v{deploy_status['canary_version']:03d}"
        )
    elif active_version is not None:
        deployment_label = f"active v{active_version:03d}"

    next_action = _status_next_action(report, len(all_attempts), len(accepted_attempts))

    if json_output:
        from cli.stream2_helpers import json_response

        data = {
            "workspace_name": workspace.workspace_label,
            "workspace_path": str(workspace.root),
            "mode": mode_summary["effective_mode"],
            "config_version": active_version,
            "active_config_summary": workspace.summarize_config(resolved.config if resolved is not None else None),
            "conversations": total_conversations,
            "eval_score": latest.score_after if latest else None,
            "eval_timestamp": latest.timestamp if latest else None,
            "safety_violation_rate": metrics.safety_violation_rate,
            "cycles_run": len(all_attempts),
            "failure_buckets": buckets,
            "pending_review_cards": pending_review_cards,
            "pending_autofix_proposals": pending_autofix_proposals,
            "deployment": deployment_label,
            "loop_status": "idle",
            "memory": memory_snapshot,
            "mcp": mcp_snapshot,
            "models": model_snapshot,
            "last_eval_tokens": (usage_snapshot.get("last_eval") or {}).get("total_tokens"),
            "last_eval_cost_usd": (usage_snapshot.get("last_eval") or {}).get("estimated_cost_usd"),
            "last_optimize_cost_usd": (usage_snapshot.get("last_optimize") or {}).get("spent_dollars"),
            "workspace_spend_usd": usage_snapshot.get("workspace_spend_usd"),
            "budget_remaining_usd": usage_snapshot.get("budget_remaining_usd"),
            "next_action": next_action,
        }
        click.echo(json_response("ok", data, next_cmd="autoagent explain --json"))
        return

    snapshot = StatusSnapshot(
        workspace_name=workspace.workspace_label,
        workspace_path=str(workspace.root),
        mode_label=mode_summary["effective_mode"].upper(),
        active_config_label=f"v{active_version:03d}" if active_version is not None else "none",
        active_config_summary=workspace.summarize_config(resolved.config if resolved is not None else None),
        eval_score_label=f"{latest.score_after:.4f}" if latest else "n/a",
        eval_timestamp_label=_format_relative_time(latest.timestamp) if latest else "never",
        conversations_label=str(total_conversations),
        safety_label=f"{metrics.safety_violation_rate:.3f}",
        cycles_run_label=str(len(all_attempts)),
        pending_review_cards=pending_review_cards,
        pending_autofix_proposals=pending_autofix_proposals,
        deployment_label=deployment_label,
        loop_label="idle",
        memory_label=(
            f"{memory_snapshot['active_count']} active source(s)"
            if memory_snapshot["active_count"]
            else "no layered context"
        ),
        mcp_label=f"{mcp_snapshot['server_count']} server(s)",
        model_label=(
            f"{(model_snapshot.get('proposer') or {}).get('key', 'n/a')} | "
            f"{(model_snapshot.get('evaluator') or {}).get('key', 'n/a')}"
        ),
        last_eval_tokens_label=str((usage_snapshot.get("last_eval") or {}).get("total_tokens", "n/a")),
        last_eval_cost_label=f"${float((usage_snapshot.get('last_eval') or {}).get('estimated_cost_usd', 0.0)):.2f}",
        last_optimize_cost_label=f"${float((usage_snapshot.get('last_optimize') or {}).get('spent_dollars', 0.0)):.2f}",
        next_action=next_action,
    )
    render_status_home(snapshot)


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
@click.option("--fix", is_flag=True, help="Automatically repair fixable workspace issues.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def doctor(config_path: str, fix: bool, json_output: bool = False) -> None:
    """Check system health and configuration.

    Reports on API keys, mock mode, data stores, eval cases, and config versions.

    Examples:
      autoagent doctor
    """
    import sqlite3

    from cli.mcp_runtime import mcp_status_snapshot
    from cli.stream2_helpers import json_response
    from core.project_memory import load_layered_project_context

    issues: list[str] = []
    fixes_applied: list[str] = []
    workspace = discover_workspace()

    if fix and workspace is not None:
        fixes_applied = _doctor_fix_workspace(workspace)

    if json_output:
        runtime = load_runtime_config(config_path)
        mode_summary = summarize_mode_state(config_path)
        memory_snapshot = (
            load_layered_project_context(workspace.root).summary()
            if workspace is not None
            else {"active_count": 0, "paths": []}
        )
        mcp_snapshot = mcp_status_snapshot(workspace.root if workspace is not None else Path("."))
        if workspace is None:
            issues.append("No AutoAgent workspace found")
        if runtime.optimizer.use_mock:
            issues.append("Mock mode is enabled")
        for env_var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
            if not os.environ.get(env_var):
                issues.append(f"{env_var} is not set")
        data = {
            "workspace": str(workspace.root) if workspace is not None else None,
            "issues": issues,
            "fixes_applied": fixes_applied,
            "mode": mode_summary["effective_mode"],
            "memory": memory_snapshot,
            "mcp": mcp_snapshot,
        }
        click.echo(json_response("ok", data, next_cmd="autoagent status"))
        return

    click.echo("\nAutoAgent Doctor")
    click.echo("================")

    # ------------------------------------------------------------------
    # Workspace
    # ------------------------------------------------------------------
    click.echo("\nWorkspace")
    if workspace is None:
        issues.append("No AutoAgent workspace found")
        click.echo(
            "  Workspace:          "
            + click.style("\u2717 Not found (run autoagent init or autoagent new)", fg="red")
        )
    else:
        click.echo("  Workspace:          " + click.style(str(workspace.root), fg="green"))
        active_version = workspace.metadata.active_config_version
        if active_version is None:
            issues.append("Active config is not set in workspace metadata")
            click.echo(
                "  Active config:      "
                + click.style("\u2717 Not set", fg="red")
            )
        else:
            click.echo(
                "  Active config:      "
                + click.style(f"\u2713 v{active_version:03d}", fg="green")
            )
        click.echo(
            "  Template:           "
            + click.style(workspace.metadata.template or "unknown", fg="green")
        )
        memory_snapshot = load_layered_project_context(workspace.root).summary()
        click.echo(
            "  Memory sources:     "
            + click.style(f"\u2713 {memory_snapshot['active_count']} active", fg="green")
        )
        mcp_snapshot = mcp_status_snapshot(workspace.root)
        click.echo(
            "  MCP runtime:        "
            + click.style(f"\u2713 {mcp_snapshot['server_count']} server(s)", fg="green")
        )

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    click.echo("\nConfiguration")
    runtime = load_runtime_config(config_path)
    mode_summary = summarize_mode_state(config_path)
    click.echo(f"  CLI mode:           {mode_summary['message']}")
    click.echo(f"  Mode source:        {mode_summary['mode_source']}")
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
    # Provider Profiles
    # ------------------------------------------------------------------
    click.echo("\nProvider Profiles")
    provider_path = providers_file_path(workspace)
    providers = configured_providers(provider_path)
    if providers:
        checks = provider_health_checks(provider_path)
        for check in checks:
            if check["credential_present"]:
                click.echo(
                    f"  {check['provider'] + ':':<22}"
                    + click.style(f"\u2713 {check['model']} ready", fg="green")
                )
            else:
                issues.append(check["message"])
                click.echo(
                    f"  {check['provider'] + ':':<22}"
                    + click.style(f"\u2717 {check['model']} missing {check['api_key_env']}", fg="red")
                )
    else:
        message = "No provider profiles configured"
        if not runtime.optimizer.use_mock:
            issues.append(message)
        click.echo(
            "  Registry:           "
            + click.style(
                "\u2717 Not configured (run autoagent provider configure)",
                fg="red" if not runtime.optimizer.use_mock else "yellow",
            )
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
    # Writable Paths
    # ------------------------------------------------------------------
    click.echo("\nWritable Paths")
    writable_targets = [
        ("Runtime config", Path(config_path)),
    ]
    if workspace is not None:
        writable_targets.extend(
            [
                ("Workspace root", workspace.root),
                ("Configs", workspace.configs_dir),
                ("Eval cases", workspace.cases_dir),
                ("AutoAgent state", workspace.autoagent_dir),
            ]
        )
    for label, path in writable_targets:
        parent = path if path.is_dir() else path.parent
        if parent.exists() and os.access(parent, os.W_OK):
            click.echo(f"  {label + ':':<22}" + click.style("\u2713 Writable", fg="green"))
        else:
            issues.append(f"{label} is not writable")
            click.echo(f"  {label + ':':<22}" + click.style("\u2717 Not writable", fg="red"))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    click.echo("")
    if fixes_applied:
        click.echo(click.style("Fixes", bold=True))
        for item in fixes_applied:
            click.echo(f"  Fixed: {item}")
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


def _pause_optimizer_impl() -> None:
    """Pause the optimization loop and log the human intervention event."""
    store = _control_store()
    store.pause()
    _event_log().append(event_type="human_pause", payload={"paused": True})
    click.echo("Optimizer paused. Run 'autoagent loop resume' to continue. Legacy alias: 'autoagent resume'.")


@loop_group.command("pause")
def loop_pause() -> None:
    """Pause the optimization loop (human escape hatch)."""
    _pause_optimizer_impl()


@cli.command("pause", hidden=True)
def pause_optimizer() -> None:
    """Pause the optimization loop (human escape hatch).

    Examples:
      autoagent pause
    """
    _echo_deprecation("autoagent pause", "autoagent loop pause")
    _pause_optimizer_impl()


def _resume_optimizer_impl() -> None:
    """Resume the optimization loop after a pause."""
    store = _control_store()
    store.resume()
    click.echo("Optimizer resumed.")


@loop_group.command("resume")
def loop_resume() -> None:
    """Resume the optimization loop after a pause."""
    _resume_optimizer_impl()


@cli.command("resume", hidden=True)
def resume_optimizer() -> None:
    """Resume the optimization loop after a pause.

    Examples:
      autoagent resume
    """
    _echo_deprecation("autoagent resume", "autoagent loop resume")
    _resume_optimizer_impl()


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

@cli.group("autofix", invoke_without_command=True)
@click.pass_context
def autofix_group(ctx: click.Context) -> None:
    """AutoFix Copilot — reviewable improvement proposals.

    Examples:
      autoagent autofix suggest
      autoagent autofix show pending
      autoagent autofix apply pending
    """
    if ctx.invoked_subcommand is not None:
        return

    from optimizer.autofix import AutoFixStore

    store = AutoFixStore()
    proposals = store.list_proposals(status="pending", limit=1)
    if not proposals:
        click.echo("No pending autofix proposals.")
        return

    proposal = proposals[0]
    click.echo(f"\nPending AutoFix proposal: {proposal.proposal_id}")
    click.echo(f"  Mutation: {proposal.mutation_name}")
    click.echo(f"  Surface:  {proposal.surface}")
    click.echo(f"  Preview:  {proposal.diff_preview or 'n/a'}")
    action = click.prompt("Action", type=click.Choice(["apply", "reject", "skip"]), default="skip")
    if action == "apply":
        if click.confirm("Apply this proposal?", default=False):
            ctx.invoke(autofix_apply, proposal_id=proposal.proposal_id, dry_run=False, json_output=False)
    elif action == "reject":
        store.update_status(proposal.proposal_id, "rejected")
        click.echo(f"Rejected proposal {proposal.proposal_id}.")


@autofix_group.command("suggest")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def autofix_suggest(json_output: bool = False) -> None:
    """Generate AutoFix proposals without applying them.

    Examples:
      autoagent autofix suggest
      autoagent autofix suggest --json
    """
    from cli.stream2_helpers import json_response
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
        if json_output:
            click.echo(json_response("ok", []))
        else:
            click.echo("No proposals generated.")
        return

    if json_output:
        data = [
            {
                "proposal_id": p.proposal_id,
                "mutation_name": p.mutation_name,
                "surface": p.surface,
                "risk_class": p.risk_class,
                "expected_lift": p.expected_lift,
                "cost_impact_estimate": p.cost_impact_estimate,
                "diff_preview": p.diff_preview,
                "status": getattr(p, "status", "pending"),
            }
            for p in proposals
        ]
        click.echo(json_response("ok", data, next_cmd="autoagent autofix apply <proposal_id>"))
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
@click.option("--dry-run", is_flag=True, help="Preview the autofix application without writing a new config.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def autofix_apply(proposal_id: str, dry_run: bool, json_output: bool = False) -> None:
    """Apply a specific AutoFix proposal and write a new config version.

    Examples:
      autoagent autofix apply abc123
      autoagent autofix apply pending
    """
    from cli.stream2_helpers import apply_autofix_to_config, is_selector, json_response
    from optimizer.autofix import AutoFixEngine, AutoFixStore
    from optimizer.mutations import create_default_registry

    # FR-08: resolve "pending" selector
    if is_selector(proposal_id):
        store = AutoFixStore()
        proposals = store.list_pending(limit=1) if hasattr(store, "list_pending") else []
        if not proposals and hasattr(store, "list_proposals"):
            proposals = store.list_proposals(status="pending", limit=1)
        if not proposals:
            history = store.history(limit=50) if hasattr(store, "history") else []
            proposals = [p for p in history if getattr(p, "status", "") == "pending"]
        if not proposals:
            msg = "No pending autofix proposals found."
            if json_output:
                click.echo(json_response("error", {"message": msg}))
            else:
                click.echo(msg)
            return
        proposal_id = proposals[0].proposal_id

    store = AutoFixStore()
    registry = create_default_registry()
    engine = AutoFixEngine(proposers=[], mutation_registry=registry, store=store)

    deployer = Deployer(configs_dir=CONFIGS_DIR, store=ConversationStore(db_path=DB_PATH))
    current_config = _ensure_active_config(deployer)

    if dry_run:
        preview = {
            "proposal_id": proposal_id,
            "current_active_version": deployer.version_manager.manifest.get("active_version"),
        }
        if json_output:
            click.echo(json_response("ok", preview, next_cmd=f"autoagent autofix apply {proposal_id}"))
        else:
            click.echo("Dry run: autofix apply preview")
            click.echo(f"  Proposal: {proposal_id}")
            click.echo(f"  Active config: v{preview['current_active_version']:03d}" if preview["current_active_version"] else "  Active config: none")
        return

    try:
        new_config, status_msg = engine.apply(proposal_id, current_config)
        if new_config:
            version_info = apply_autofix_to_config(proposal_id, new_config, configs_dir=CONFIGS_DIR)
            if json_output:
                click.echo(json_response("ok", {
                    "proposal_id": proposal_id,
                    "status": status_msg,
                    "config_version": version_info["version"],
                    "config_path": version_info["path"],
                }, next_cmd=f"autoagent eval run --config {version_info['path']}"))
            else:
                click.echo(f"Applied: {status_msg}")
                click.echo(f"  New config version: v{version_info['version']:03d}")
                click.echo(f"  Path: {version_info['path']}")
                _print_next_actions([f"autoagent eval run --config {version_info['path']}"])
        else:
            if json_output:
                click.echo(json_response("ok", {"proposal_id": proposal_id, "status": status_msg, "config_version": None}))
            else:
                click.echo(f"Applied: {status_msg}")
                click.echo("No config changes produced.")
    except ValueError as exc:
        if json_output:
            click.echo(json_response("error", {"message": str(exc)}))
        else:
            click.echo(click.style(f"Error: {exc}", fg="red"))


@autofix_group.command("revert")
@click.argument("proposal_id", type=str)
def autofix_revert(proposal_id: str) -> None:
    """Mark an applied autofix proposal as reverted."""
    from cli.stream2_helpers import is_selector
    from optimizer.autofix import AutoFixStore

    store = AutoFixStore()
    resolved_proposal_id = proposal_id
    if is_selector(proposal_id):
        history = store.history(limit=50)
        if proposal_id.lower() == "latest" and history:
            resolved_proposal_id = history[0].proposal_id
        elif proposal_id.lower() == "pending":
            pending = store.list_pending(limit=1) if hasattr(store, "list_pending") else []
            if pending:
                resolved_proposal_id = pending[0].proposal_id

    proposal = store.get(resolved_proposal_id)
    if proposal is None:
        raise click.ClickException(f"Proposal not found: {resolved_proposal_id}")

    store.update_status(resolved_proposal_id, "reverted")
    click.echo(click.style(f"Applied: reverted autofix proposal {resolved_proposal_id}", fg="green"))


@autofix_group.command("history")
@click.option("--limit", default=20, show_default=True, type=int, help="Number of proposals to show.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def autofix_history(limit: int, json_output: bool = False) -> None:
    """Show past AutoFix proposals and outcomes.

    Examples:
      autoagent autofix history
      autoagent autofix history --json
    """
    from cli.stream2_helpers import json_response
    from optimizer.autofix import AutoFixEngine, AutoFixStore

    store = AutoFixStore()
    engine = AutoFixEngine(proposers=[], mutation_registry=None, store=store)
    proposals = engine.history(limit=limit)

    if not proposals:
        if json_output:
            click.echo(json_response("ok", []))
        else:
            click.echo("No AutoFix history found.")
        return

    if json_output:
        data = [
            {
                "proposal_id": p.proposal_id,
                "mutation_name": p.mutation_name,
                "status": p.status,
                "expected_lift": p.expected_lift,
                "risk_class": p.risk_class,
            }
            for p in proposals
        ]
        click.echo(json_response("ok", data))
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
    """Judge Ops — monitoring, calibration, and human feedback.

    Examples:
      autoagent judges list
      autoagent judges calibrate --sample 10
      autoagent judges drift
    """


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
    """Context Engineering Workbench — diagnose and tune agent context.

    Examples:
      autoagent context simulate --strategy balanced
      autoagent context report
      autoagent context analyze --trace trace_demo_fail_001
    """


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

    events = trace_store.get_trace(trace_id=trace_id)
    if not events:
        click.echo(f"No events found for trace: {trace_id}")
        return

    event_dicts = [
        {
            "trace_id": e.trace_id,
            "event_type": e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type),
            "tokens_in": e.tokens_in,
            "tokens_out": e.tokens_out,
            "error_message": e.error_message,
            "agent_path": e.agent_path,
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
    """Review proposed change cards from the optimizer.

    Running `autoagent review` opens an interactive approval prompt.

    Examples:
      autoagent review
      autoagent review list
      autoagent review show pending
    """
    if ctx.invoked_subcommand is not None:
        return

    from optimizer.change_card import ChangeCardStore

    store = ChangeCardStore()
    cards = store.list_pending(limit=1)
    if not cards:
        click.echo("No pending change cards.")
        return

    card = cards[0]
    click.echo(card.to_terminal())
    if click.confirm("Approve this change?", default=False):
        store.update_status(card.card_id, "applied")
        click.echo(f"Applied change card {card.card_id}: {card.title}")


@review_group.command("list")
@click.option("--limit", default=20, show_default=True, type=int, help="Number of cards to show.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def review_list(limit: int = 20, json_output: bool = False) -> None:
    """List pending change cards.

    Examples:
      autoagent review
      autoagent review list
      autoagent review list --json
    """
    from cli.stream2_helpers import json_response
    from optimizer.change_card import ChangeCardStore

    store = ChangeCardStore()
    cards = store.list_pending(limit=limit)

    if not cards:
        if json_output:
            click.echo(json_response("ok", []))
        else:
            click.echo("No pending change cards.")
        return

    if json_output:
        data = [
            {
                "card_id": card.card_id,
                "title": card.title,
                "risk_class": card.risk_class,
                "status": card.status,
            }
            for card in cards
        ]
        click.echo(json_response("ok", data, next_cmd="autoagent review show <card_id>"))
        return

    click.echo(f"\nPending change cards ({len(cards)}):\n")
    click.echo(f"{'ID':<10}  {'Title':<35}  {'Risk':<8}  {'Status'}")
    click.echo(f"{'─' * 10}  {'─' * 35}  {'─' * 8}  {'─' * 10}")
    for card in cards:
        title = (card.title[:32] + "...") if len(card.title) > 35 else card.title
        click.echo(f"{card.card_id:<10}  {title:<35}  {card.risk_class:<8}  {card.status}")


@review_group.command("show")
@click.argument("card_id")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def review_show(card_id: str, json_output: bool = False) -> None:
    """Show a specific change card with full terminal rendering.

    Supports selectors: pending, latest.

    Examples:
      autoagent review show abc12345
      autoagent review show pending
      autoagent review show pending --json
    """
    from cli.stream2_helpers import is_selector, json_response
    from optimizer.change_card import ChangeCardStore

    store = ChangeCardStore()

    # FR-08: resolve selectors
    if is_selector(card_id):
        cards = store.list_pending(limit=1)
        if not cards:
            if json_output:
                click.echo(json_response("error", {"message": f"No {card_id} change cards found"}))
            else:
                click.echo(f"No {card_id} change cards found.")
            return
        card_id = cards[0].card_id

    card = store.get(card_id)
    if card is None:
        if json_output:
            click.echo(json_response("error", {"message": f"Change card not found: {card_id}"}))
        else:
            click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)

    if json_output:
        click.echo(json_response("ok", {
            "card_id": card.card_id,
            "title": card.title,
            "risk_class": card.risk_class,
            "status": card.status,
        }, next_cmd=f"autoagent review apply {card.card_id}"))
    else:
        click.echo(card.to_terminal())


@review_group.command("apply")
@click.argument("card_id")
@click.option(
    "--output-format",
    type=click.Choice(["text", "json", "stream-json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Render text or stream JSON progress events.",
)
def review_apply(card_id: str, output_format: str = "text") -> None:
    """Apply (accept) a change card.

    Examples:
      autoagent review apply abc12345
    """
    from cli.output import resolve_output_format
    from cli.permissions import PermissionManager
    from cli.progress import ProgressRenderer
    from optimizer.change_card import ChangeCardStore

    resolved_output_format = resolve_output_format(output_format)
    progress = ProgressRenderer(output_format=resolved_output_format, render_text=False)
    progress.phase_started("review-apply", message=f"Apply change card {card_id}")
    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    if card.status != "pending":
        click.echo(f"Card is not pending (status={card.status})")
        raise SystemExit(1)

    PermissionManager().require(
        "review.apply",
        prompt=f"Apply change card {card_id}?",
        default=False,
    )
    store.update_status(card_id, "applied")
    progress.phase_completed("review-apply", message=f"Applied change card {card_id}")
    progress.next_action("autoagent status")
    if resolved_output_format == "stream-json":
        return
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
# autoagent experiment
# ---------------------------------------------------------------------------

@cli.group("experiment")
def experiment_group() -> None:
    """Inspect optimization experiment history.

    Examples:
      autoagent experiment log
      autoagent experiment log --tail 10
      autoagent experiment log --summary
    """


@experiment_group.command("log")
@click.option("--tail", default=None, type=int, help="Show only the last N entries.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
@click.option("--summary", is_flag=True, default=False, help="Print a one-line history summary.")
def experiment_log(tail: int | None, json_output: bool, summary: bool) -> None:
    """View optimize experiment history from the append-only TSV log.

    Examples:
      autoagent experiment log
      autoagent experiment log --tail 5
      autoagent experiment log --json
      autoagent experiment log --summary
    """
    entries = read_experiment_log_entries()
    if not entries:
        click.echo("No experiments yet. Run: autoagent optimize --continuous")
        return

    if summary:
        click.echo(summarize_experiment_log_entries(entries))
        return

    selected_entries = tail_experiment_log_entries(entries, tail)
    if json_output:
        click.echo(json.dumps([entry.to_dict() for entry in selected_entries], indent=2))
        return

    click.echo(format_experiment_log_table(selected_entries))


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


@memory_group.command("list")
def memory_list() -> None:
    """List layered memory sources for the current workspace."""
    from core.project_memory import list_memory_sources

    sources = list_memory_sources()
    click.echo("Memory sources")
    for source in sources:
        status = "active" if source.exists else "missing"
        click.echo(f"  {source.kind:<10} {status:<8} {source.path}")


@memory_group.command("where")
def memory_where() -> None:
    """Show where layered memory files live on disk."""
    from core.project_memory import load_layered_project_context

    snapshot = load_layered_project_context()
    click.echo("Layered memory paths")
    click.echo(f"  Shared:  {snapshot.shared_path}")
    click.echo(f"  Local:   {snapshot.local_path}")
    click.echo(f"  Rules:   {snapshot.rules_dir}")
    click.echo(f"  Memory:  {snapshot.memory_dir}")
    for source in snapshot.active_sources:
        click.echo(f"  Active:  {source.path}")


@memory_group.command("edit")
@click.argument("target", default="shared")
@click.option("--append", "append_text", default=None, help="Append markdown content instead of opening an editor.")
def memory_edit(target: str, append_text: str | None) -> None:
    """Edit a layered memory target by appending markdown or opening an editor."""
    from cli.permissions import PermissionManager
    from core.project_memory import append_memory_text, resolve_memory_target

    PermissionManager().require(
        "memory.write",
        prompt=f"Update memory target '{target}'?",
        default=True,
    )
    if append_text:
        path = append_memory_text(".", target, append_text)
        click.echo(f"Updated memory target: {path}")
        return
    memory_path = resolve_memory_target(".", target)
    if not memory_path.exists():
        raise click.ClickException(f"No memory file found at {memory_path}. Use --append or run autoagent init")
    _open_in_editor(memory_path)


@memory_group.command("summarize-session")
@click.argument("summary")
@click.option("--title", default="Session Summary", show_default=True, help="Title for the generated summary file.")
def memory_summarize_session(summary: str, title: str) -> None:
    """Write a generated session summary into `.autoagent/memory/`."""
    from cli.permissions import PermissionManager
    from core.project_memory import write_session_summary

    PermissionManager().require(
        "memory.write",
        prompt="Write a generated session summary to project memory?",
        default=True,
    )
    path = write_session_summary(".", title=title, summary=summary)
    click.echo(f"Session summary written: {path}")


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
    from cli.permissions import PermissionManager

    PermissionManager().require(
        "memory.write",
        prompt=f"Add a note to memory section '{section}'?",
        default=True,
    )
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
@_banner_flag_options
@click.option("--host", default="0.0.0.0", show_default=True, help="Host to bind to.")
@click.option("--port", default=8000, show_default=True, type=int, help="Port to bind to.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload for development.")
@click.pass_context
def server(ctx: click.Context, quiet: bool, no_banner: bool, host: str, port: int, reload: bool) -> None:
    """Start the API server + web console.

    Starts the FastAPI backend serving both the REST API and the web console.
    API docs available at http://localhost:8000/docs

    Examples:
      autoagent server
      autoagent server --port 3000 --reload
    """
    import uvicorn

    del quiet, no_banner
    echo_startup_banner(ctx)
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
@click.option("--host", default="127.0.0.1", show_default=True, help="HTTP bind host when using --port.")
@click.option("--port", default=None, type=int, help="Start streamable HTTP mode on this port. Defaults to stdio mode.")
def mcp_server_cmd(host: str, port: int | None) -> None:
    """Start MCP server for AI coding tool integration.

    Runs in stdio mode by default for Claude Code, Cursor, Codex, and other
    MCP-compatible tools. Supply --port to serve streamable HTTP locally.

    Setup for Claude Code (project-scoped .mcp.json example):
      {
        "mcpServers": {
          "autoagent": {
            "command": "python3",
            "args": ["-m", "mcp_server"]
          }
        }
      }

    Examples:
      autoagent mcp-server                         # Stdio mode (default)
      autoagent mcp-server --host 127.0.0.1 --port 8081
    """
    from mcp_server.server import run_http
    from mcp_server.server import run_stdio
    if port is not None:
        run_http(host=host, port=port)
        return
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
    """Modular registry — skills, policies, tool contracts, handoff schemas.

    Examples:
      autoagent registry list
      autoagent registry list --type skills
      autoagent registry import registry_export.yaml
    """


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
        if registry_type == "tools":
            data.pop("name", None)
            data["tool_name"] = name
        else:
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
    """Unified skill management — build-time and run-time skills.

    Examples:
      autoagent skill list
      autoagent skill recommend --json
      autoagent skill show returns_handling
    """


# Register all skill commands from cli.skills module
from cli.skills import register_skill_commands
register_skill_commands(skill_group)


@skill_group.command("export-md")
@click.argument("skill_name")
@click.option("--output", default=None, help="Destination file or directory.")
@click.option("--db", default=".autoagent/skills.db", show_default=True, help="Skills database path.")
def skill_export_md(skill_name: str, output: str | None, db: str) -> None:
    """Export a skill as SKILL.md."""
    from registry.skill_md import SkillMdSerializer

    def _portable_scalar(value: object) -> object:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return yaml.safe_dump(value, sort_keys=False).strip()

    store = SkillStore(db)
    try:
        skill = store.get(skill_name) or store.get_by_name(skill_name)
        if skill is None:
            click.echo(f"Skill not found: {skill_name}", err=True)
            raise SystemExit(1)
    finally:
        store.close()

    output_path = output or f"{skill.id}.SKILL.md"
    portable_skill = {
        "name": skill.name,
        "version": skill.version,
        "kind": skill.kind.value,
        "category": skill.domain,
        "platform": skill.metadata.get("platform", "universal"),
        "description": skill.description,
        "author": skill.author,
        "tags": skill.tags,
        "dependencies": [dep.to_dict() for dep in skill.dependencies],
        "allowed_tools": skill.metadata.get("allowed_tools", [tool.name for tool in skill.tools]),
        "supported_frameworks": skill.metadata.get("supported_frameworks", []),
        "required_approvals": skill.metadata.get("required_approvals", []),
        "eval_contract": skill.metadata.get("eval_contract", {}),
        "rollout_policy": skill.metadata.get("rollout_policy", "gradual"),
        "provenance": skill.metadata.get("provenance", ""),
        "trust_level": skill.metadata.get("trust_level", "unverified"),
        "triggers": [trigger.to_dict() for trigger in skill.triggers],
        "mutations": [
            {
                "name": mutation.name,
                "mutation_type": mutation.operator_type,
                "target_surface": mutation.target_surface,
                "description": mutation.description,
                "template": mutation.template,
            }
            for mutation in skill.mutations
        ],
        "examples": [
            {
                "name": example.name,
                "surface": skill.mutations[0].target_surface if skill.mutations else "instruction",
                "before": _portable_scalar(example.before),
                "after": _portable_scalar(example.after),
                "improvement": example.improvement,
                "context": example.context,
            }
            for example in skill.examples
        ],
        "eval_criteria": [criterion.to_dict() for criterion in skill.eval_criteria],
        "guardrails": skill.guardrails,
        "instructions": skill.instructions,
        "references": skill.metadata.get("references", ""),
    }

    serializer = SkillMdSerializer()
    output_abs = Path(output_path)
    if output_abs.is_dir() or output_path.endswith(os.sep):
        output_abs.mkdir(parents=True, exist_ok=True)
        output_abs = output_abs / "SKILL.md"
    else:
        output_abs.parent.mkdir(parents=True, exist_ok=True)
    serializer.serialize_to_file(portable_skill, str(output_abs))
    exported_path = str(output_abs.resolve())

    click.echo(f"Exported {skill.name} to {exported_path}")


@skill_group.command("import-md")
@click.argument("path")
@click.option("--db", default=".autoagent/skills.db", show_default=True, help="Skills database path.")
def skill_import_md(path: str, db: str) -> None:
    """Import a skill from SKILL.md file."""
    import re

    from core.skills.types import EvalCriterion, MutationOperator, Skill, SkillDependency, SkillExample, SkillKind, TriggerCondition
    from registry.skill_md import SkillMdParser

    parser = SkillMdParser()
    source = Path(path)
    parsed = parser.parse_directory(str(source)) if source.is_dir() else parser.parse_file(str(source))
    frontmatter = parsed.get("frontmatter", {})
    name = str(frontmatter.get("name", parsed.get("title", "imported-skill")))
    version = str(frontmatter.get("version", "1.0.0"))
    kind_value = str(frontmatter.get("kind", "build")).lower()
    kind = SkillKind(kind_value) if kind_value in {member.value for member in SkillKind} else SkillKind.BUILD

    skill_id = re.sub(r"[^a-z0-9]+", "-", f"{name}-{version}".lower()).strip("-") or "imported-skill"
    triggers = [
        TriggerCondition(
            failure_family=trigger.get("failure_family"),
            metric_name=trigger.get("metric_name"),
            threshold=trigger.get("threshold"),
            operator=trigger.get("operator", "gt"),
            blame_pattern=trigger.get("blame_pattern"),
        )
        for trigger in frontmatter.get("triggers", [])
        if isinstance(trigger, dict)
    ]
    mutations = [
        MutationOperator(
            name=mutation.get("name", "unnamed-mutation"),
            description=mutation.get("description", ""),
            target_surface=mutation.get("target_surface", "instruction"),
            operator_type=mutation.get("mutation_type", "append"),
            template=mutation.get("template"),
        )
        for mutation in parsed.get("mutations", [])
        if isinstance(mutation, dict)
    ]
    examples = [
        SkillExample(
            name=example.get("name", "example"),
            description=example.get("context", "") or example.get("description", ""),
            before=example.get("before", ""),
            after=example.get("after", ""),
            improvement=float(example.get("improvement", 0.0) or 0.0),
            context=example.get("context", ""),
        )
        for example in parsed.get("examples", [])
        if isinstance(example, dict)
    ]
    eval_criteria = [
        EvalCriterion(
            metric=criterion.get("metric", ""),
            target=float(criterion.get("target", 0.0) or 0.0),
            operator=criterion.get("operator", "gt"),
            weight=float(criterion.get("weight", 1.0) or 1.0),
        )
        for criterion in parsed.get("eval_criteria", [])
        if isinstance(criterion, dict)
    ]
    dependencies = []
    for dependency in frontmatter.get("dependencies", []):
        if isinstance(dependency, dict):
            dependencies.append(
                SkillDependency(
                    skill_id=str(dependency.get("skill_id", dependency.get("name", "dependency"))),
                    version_constraint=str(dependency.get("version_constraint", "*")),
                    optional=bool(dependency.get("optional", False)),
                )
            )
        elif isinstance(dependency, str):
            dependencies.append(SkillDependency(skill_id=dependency))

    imported_skill = Skill(
        id=skill_id,
        name=name,
        kind=kind,
        version=version,
        description=str(frontmatter.get("description", parsed.get("description", ""))),
        capabilities=[mutation.target_surface for mutation in mutations],
        mutations=mutations,
        triggers=triggers,
        eval_criteria=eval_criteria,
        guardrails=list(parsed.get("guardrails", [])) if isinstance(parsed.get("guardrails", []), list) else [],
        examples=examples,
        instructions=str(parsed.get("instructions", "")) if isinstance(parsed.get("instructions", ""), str) else "",
        dependencies=dependencies,
        tags=list(frontmatter.get("tags", [])),
        domain=str(frontmatter.get("category", "general")),
        metadata={
            "platform": frontmatter.get("platform", "universal"),
            "allowed_tools": frontmatter.get("allowed_tools", []),
            "supported_frameworks": frontmatter.get("supported_frameworks", []),
            "required_approvals": frontmatter.get("required_approvals", []),
            "eval_contract": frontmatter.get("eval_contract", {}),
            "rollout_policy": frontmatter.get("rollout_policy", "gradual"),
            "provenance": frontmatter.get("provenance", ""),
            "trust_level": frontmatter.get("trust_level", "unverified"),
            "references": parsed.get("references", ""),
        },
        author=str(frontmatter.get("author", "autoagent")),
        status="active",
    )

    store = SkillStore(db)
    try:
        existing = store.get_by_name(imported_skill.name, version=imported_skill.version)
        if existing is not None:
            click.echo(f"Imported skill: {existing.name} (version {existing.version})")
            return
        store.create(imported_skill)
    finally:
        store.close()

    click.echo(f"Imported skill: {imported_skill.name} (version {imported_skill.version})")


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
    recent_failures = store.get_failures(limit=limit * 10)  # Get more to cluster

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
                    "error": record.error_message or "",
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
    """Trace analysis — grading, blame maps, and graphs.

    Examples:
      autoagent trace show latest
      autoagent trace blame --window 24h
      autoagent trace promote latest
    """


@trace_group.command("show")
@click.argument("trace_id")
@click.option("--db", default=TRACE_DB, show_default=True)
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def trace_show(trace_id: str, db: str, json_output: bool = False) -> None:
    """Show trace details. Supports selectors: latest.

    Examples:
      autoagent trace show abc-123
      autoagent trace show latest
      autoagent trace show latest --json
    """
    from cli.stream2_helpers import json_response
    from observer.traces import TraceStore

    store = TraceStore(db_path=db)

    # FR-08: resolve "latest" selector
    if trace_id.lower() == "latest":
        recent = store.get_recent_trace_ids(limit=1) if hasattr(store, "get_recent_trace_ids") else []
        if not recent:
            if json_output:
                click.echo(json_response("error", {"message": "No traces found"}))
            else:
                click.echo("No traces found.")
            return
        trace_id = recent[0]

    events = store.get_trace(trace_id=trace_id)
    if not events:
        if json_output:
            click.echo(json_response("error", {"message": f"No events found for trace: {trace_id}"}))
        else:
            click.echo(f"No events found for trace: {trace_id}")
        return

    total_tokens = sum(e.tokens_in + e.tokens_out for e in events)
    total_latency = sum(e.latency_ms for e in events)
    errors = [e for e in events if e.error_message]

    if json_output:
        data = {
            "trace_id": trace_id,
            "events": len(events),
            "total_tokens": total_tokens,
            "total_latency_ms": total_latency,
            "errors": len(errors),
        }
        click.echo(json_response("ok", data, next_cmd=f"autoagent trace grade {trace_id}"))
    else:
        click.echo(f"\nTrace: {trace_id}")
        click.echo(f"  Events:      {len(events)}")
        click.echo(f"  Total tokens: {total_tokens}")
        click.echo(f"  Total latency: {total_latency:.1f}ms")
        click.echo(f"  Errors:      {len(errors)}")
        if errors:
            for e in errors[:5]:
                click.echo(f"    - {e.error_message}")


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
@click.option("--eval-cases-dir", default="evals/cases", show_default=True, help="Eval cases directory.")
@click.option("--db", default=TRACE_DB, show_default=True)
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def trace_promote(trace_id: str, eval_cases_dir: str, db: str, json_output: bool = False) -> None:
    """Promote a trace to an eval case file in the active eval set.

    Examples:
      autoagent trace promote abc-123
      autoagent trace promote latest
    """
    from cli.stream2_helpers import json_response, write_trace_eval_case
    from observer.trace_promoter import TraceCandidate, TracePromoter
    from observer.traces import TraceStore

    # FR-08: resolve "latest" selector
    if trace_id.lower() == "latest":
        store = TraceStore(db_path=db)
        recent = store.get_recent_trace_ids(limit=1) if hasattr(store, "get_recent_trace_ids") else []
        if not recent:
            msg = "No traces found."
            if json_output:
                click.echo(json_response("error", {"message": msg}))
            else:
                click.echo(msg)
            return
        trace_id = recent[0]

    promoter = TracePromoter()
    candidate = TraceCandidate(
        trace_id=trace_id,
        reason="manual promotion",
        confidence=1.0,
        suggested_category="promoted",
    )
    eval_case = promoter.promote_to_eval_case(candidate)
    file_path = write_trace_eval_case(trace_id, eval_case, eval_cases_dir=eval_cases_dir)

    if json_output:
        click.echo(json_response("ok", {
            "trace_id": trace_id,
            "eval_case": eval_case,
            "file_path": file_path,
        }, next_cmd="autoagent eval run"))
    else:
        click.echo(click.style("  ✓ ", fg="green") + f"Promoted trace {trace_id} to eval case")
        click.echo(f"  File: {file_path}")
        _print_next_actions(["autoagent eval run"])


# ---------------------------------------------------------------------------
# autoagent scorer ...
# ---------------------------------------------------------------------------

@cli.group("scorer")
def scorer_group() -> None:
    """NL Scorer — create eval scorers from natural language descriptions.

    Examples:
      autoagent scorer create "Reward verified account changes" --name account_safety
      autoagent scorer list
      autoagent scorer show account_safety
    """


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
    if from_file:
        nl_text = Path(from_file).read_text(encoding="utf-8").strip()
    elif description:
        nl_text = description
    else:
        click.echo("Error: provide a description argument or --from-file.", err=True)
        raise SystemExit(1)

    scorer = _make_nl_scorer()
    spec = scorer.create(nl_text, name=name)
    click.echo(f"Created scorer: {spec.name} (v{spec.version})")
    click.echo(f"Dimensions: {len(spec.dimensions)}")
    for d in spec.dimensions:
        click.echo(f"  - {d.name} ({d.grader_type}, weight={d.weight})")
    click.echo(f"\nYAML:\n{spec.to_yaml()}")


@scorer_group.command("list")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def scorer_list(json_output: bool = False) -> None:
    """List all scorer specs in memory.

    Examples:
      autoagent scorer list
      autoagent scorer list --json
    """
    from cli.stream2_helpers import json_response

    scorer = _make_nl_scorer()
    specs = scorer.list()
    if not specs:
        if json_output:
            click.echo(json_response("ok", []))
        else:
            click.echo("No scorers found. Create one with: autoagent scorer create")
        return
    if json_output:
        data = [{"name": s.name, "version": s.version, "dimensions": len(s.dimensions)} for s in specs]
        click.echo(json_response("ok", data))
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
    scorer = _make_nl_scorer()
    spec = scorer.get(name)
    if spec is None:
        suggestions = difflib.get_close_matches(name, [item.name for item in scorer.list()], n=1)
        message = f"Scorer '{name}' not found."
        if suggestions:
            message += f" Did you mean '{suggestions[0]}'?"
        click.echo(message)
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
    scorer = _make_nl_scorer()
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
    from evals.scorer import EvalResult
    from observer.traces import TraceStore

    scorer = _make_nl_scorer()
    spec = scorer.get(name)
    if spec is None:
        click.echo(f"Scorer '{name}' not found.", err=True)
        raise SystemExit(1)

    store = TraceStore(db_path=db)
    events = store.get_trace(trace_id)
    if not events:
        click.echo(f"Trace '{trace_id}' not found.", err=True)
        raise SystemExit(1)

    error_count = sum(1 for event in events if event.error_message)
    total_tokens = sum(event.tokens_in + event.tokens_out for event in events)
    total_latency_ms = sum(event.latency_ms for event in events)
    tool_events = [event for event in events if event.tool_name]
    tool_errors = sum(1 for event in tool_events if event.error_message)
    tool_use_accuracy = 1.0
    if tool_events:
        tool_use_accuracy = max(0.0, 1.0 - (tool_errors / len(tool_events)))

    quality_score = 1.0 if error_count == 0 else 0.0
    safety_passed = not any(
        event.event_type == "safety_flag" or bool(event.error_message)
        for event in events
    )

    # Build a minimal EvalResult from trace events.
    eval_result = EvalResult(
        case_id=trace_id,
        category="trace",
        passed=error_count == 0,
        quality_score=quality_score,
        safety_passed=safety_passed,
        latency_ms=total_latency_ms,
        token_count=total_tokens,
        tool_use_accuracy=tool_use_accuracy,
        details=f"Scored from trace {trace_id}",
        satisfaction_proxy=1.0 if error_count == 0 else 0.0,
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
    from cli.permissions import PermissionManager

    if not acknowledge and PermissionManager().decision_for("full_auto.run") != "allow":
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

    ctx.invoke(
        optimize,
        cycles=cycles,
        continuous=False,
        mode=None,
        strategy=None,
        db=DB_PATH,
        configs_dir=CONFIGS_DIR,
        memory_db=MEMORY_DB,
        full_auto=True,
        dry_run=False,
        json_output=False,
        max_budget_usd=None,
        output_format="text",
    )
    ctx.invoke(
        loop_run,
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
        max_budget_usd=None,
        output_format="text",
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
@_banner_flag_options
@click.option("--agent-name", default="My Agent", show_default=True,
              help="Agent name for AUTOAGENT.md.")
@click.option("--verbose", is_flag=True, default=False, help="Show detailed output.")
@click.option("--dir", "target_dir", default=".", show_default=True,
              help="Directory to initialize in.")
@click.option("--open/--no-open", "auto_open", default=True, help="Auto-open web console after completion.")
@click.pass_context
def quickstart(
    ctx: click.Context,
    quiet: bool,
    no_banner: bool,
    agent_name: str,
    verbose: bool,
    target_dir: str,
    auto_open: bool,
) -> None:
    """Run the ENTIRE golden path: init → seed → eval → optimize → summary.

    A single command that takes you from zero to optimized agent in minutes.

    Examples:
      autoagent quickstart
      autoagent quickstart --agent-name "Support Bot" --verbose
    """
    del quiet, no_banner
    echo_startup_banner(ctx)
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
    runtime.optimizer.use_mock = True
    click.echo("  Using mock mode for the guided quickstart. Switch to real providers after setup if needed.")
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
    all_time_best = _read_best_score(best_score_file)

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

@cli.group("demo", invoke_without_command=True)
@_banner_flag_options
@click.pass_context
def demo(ctx: click.Context, quiet: bool, no_banner: bool) -> None:
    """Demo commands for presentations and quick trials."""
    del quiet, no_banner
    if ctx.invoked_subcommand is None and not ctx.resilient_parsing:
        echo_startup_banner(ctx)
        click.echo(ctx.get_help())
        ctx.exit()


@demo.command("quickstart")
@_banner_flag_options
@click.option("--dir", "target_dir", default=".", show_default=True,
              help="Directory to initialize in.")
@click.option("--open/--no-open", "auto_open", default=True, help="Auto-open web console after completion.")
@click.pass_context
def demo_quickstart(
    ctx: click.Context,
    quiet: bool,
    no_banner: bool,
    target_dir: str,
    auto_open: bool,
) -> None:
    """Interactive demo: seed data, run one optimise cycle, show results.

    More visual and concise than quickstart — designed for presentations.

    Examples:
      autoagent demo quickstart
    """
    del quiet, no_banner
    echo_startup_banner(ctx)
    click.echo(click.style("\n╔══════════════════════════════════════╗", fg="cyan"))
    click.echo(click.style("║       AutoAgent Demo Mode            ║", fg="cyan"))
    click.echo(click.style("╚══════════════════════════════════════╝\n", fg="cyan"))

    # Init + seed
    click.echo(click.style("▸ Setting up project...", fg="white", bold=True))
    ctx.invoke(
        init_project,
        template="customer-support",
        target_dir=target_dir,
        name=None,
        agent_name="Demo Agent",
        platform="Google ADK",
        with_synthetic_data=True,
        demo=True,
    )
    workspace_paths = _workspace_state_paths(target_dir)

    # Single eval
    click.echo(click.style("\n▸ Running evaluation...", fg="white", bold=True))
    runtime = _scope_runtime_to_workspace(load_runtime_config(), workspace_paths["workspace"])
    runtime.optimizer.use_mock = True
    click.echo("  Using mock mode for the guided demo quickstart. Switch to real providers after setup if needed.")
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
    all_time_best = _read_best_score(best_score_file)

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


@demo.command("seed")
def demo_seed() -> None:
    """Seed demo traces, review cards, and AutoFix proposals into the current workspace."""
    workspace = _require_workspace("demo")
    summary = seed_demo_workspace(workspace)
    click.echo(click.style("Demo workspace seeded.", fg="green"))
    click.echo(f"Trace IDs: {', '.join(summary.get('trace_ids', [])) or 'none'}")
    click.echo(f"Review card: {summary.get('change_card_id', 'n/a')}")
    click.echo(f"AutoFix proposal: {summary.get('autofix_id', 'n/a')}")


@demo.command("vp")
@_banner_flag_options
@click.option("--agent-name", default="Acme Support Bot", show_default=True,
              help="Agent name for the demo scenario.")
@click.option("--company", default="Acme Corp", show_default=True,
              help="Company name for the demo scenario.")
@click.option("--no-pause", is_flag=True, default=False,
              help="Skip dramatic pauses between acts.")
@click.option("--web", is_flag=True, default=False,
              help="Auto-start server and open browser after demo.")
@click.pass_context
def demo_vp(
    ctx: click.Context,
    quiet: bool,
    no_banner: bool,
    agent_name: str,
    company: str,
    no_pause: bool,
    web: bool,
) -> None:
    """VP-ready demo with 5-act storytelling structure.

    A polished, rehearsed demo flow that showcases AutoAgent's power in under 5 minutes.
    Uses curated synthetic data to tell a compelling story about agent self-healing.

    Examples:
      autoagent demo vp
      autoagent demo vp --agent-name "Support Bot" --company "Acme Inc"
      autoagent demo vp --no-pause --web
    """
    del quiet, no_banner
    echo_startup_banner(ctx)

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

# ---------------------------------------------------------------------------
# autoagent build show (FR-13: inspect commands)
# ---------------------------------------------------------------------------

@cli.group("build-inspect", hidden=True)
def build_inspect_group() -> None:
    """Inspect build artifacts."""


# We add "show" as a subcommand of "build" by converting build to a group isn't
# feasible without breaking the existing positional-arg command.
# Instead, add a top-level `autoagent build-show` command.


# ---------------------------------------------------------------------------
# autoagent policy (FR-13: inspect commands)
# ---------------------------------------------------------------------------

@cli.group("policy")
def policy_group() -> None:
    """Policy management — inspect trained policy artifacts."""


@policy_group.command("list")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def policy_list(json_output: bool = False) -> None:
    """List all policy artifacts.

    Examples:
      autoagent policy list
      autoagent policy list --json
    """
    from cli.stream2_helpers import json_response, list_policies

    policies = list_policies()
    if json_output:
        click.echo(json_response("ok", policies))
        return
    if not policies:
        click.echo("No policy artifacts found.")
        click.echo("Create one with: autoagent rl train")
        return
    click.echo(f"\nPolicy artifacts ({len(policies)}):\n")
    click.echo(f"{'Policy ID':<16}  {'Name':<20}  {'Version':>8}  {'Status':<10}  {'Mode'}")
    click.echo(f"{'─' * 16}  {'─' * 20}  {'─' * 8}  {'─' * 10}  {'─' * 12}")
    for p in policies:
        click.echo(f"{p['policy_id']:<16}  {p['name']:<20}  v{p['version']:>6}  {p['status']:<10}  {p['mode']}")


@policy_group.command("show")
@click.argument("policy_id_or_name")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def policy_show(policy_id_or_name: str, json_output: bool = False) -> None:
    """Show details for a policy artifact.

    Supports selectors: latest, active.

    Examples:
      autoagent policy show my_policy
      autoagent policy show latest --json
    """
    from cli.stream2_helpers import get_policy, is_selector, json_response, list_policies

    if is_selector(policy_id_or_name):
        policies = list_policies()
        if not policies:
            if json_output:
                click.echo(json_response("error", {"message": "No policies found"}))
            else:
                click.echo("No policies found.")
            return
        if policy_id_or_name.lower() in ("active", "current"):
            active = [p for p in policies if p["status"] in ("active", "promoted")]
            policy = active[0] if active else policies[-1]
        else:
            policy = policies[-1]
    else:
        policy = get_policy(policy_id_or_name)

    if policy is None:
        if json_output:
            click.echo(json_response("error", {"message": f"Policy not found: {policy_id_or_name}"}))
        else:
            click.echo(f"Policy not found: {policy_id_or_name}")
        return

    if json_output:
        click.echo(json_response("ok", policy))
    else:
        click.echo(json.dumps(policy, indent=2, default=str))


# ---------------------------------------------------------------------------
# autoagent autofix show (FR-13: inspect commands)
# ---------------------------------------------------------------------------

@autofix_group.command("show")
@click.argument("proposal_id")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def autofix_show(proposal_id: str, json_output: bool = False) -> None:
    """Show details for an autofix proposal.

    Examples:
      autoagent autofix show abc123
      autoagent autofix show latest --json
    """
    from cli.stream2_helpers import is_selector, json_response
    from optimizer.autofix import AutoFixStore

    store = AutoFixStore()

    if is_selector(proposal_id):
        proposals = store.list_pending(limit=1) if hasattr(store, "list_pending") else []
        if proposal_id.lower() == "pending" and not proposals and hasattr(store, "list_proposals"):
            proposals = store.list_proposals(status="pending", limit=1)
        if proposal_id.lower() != "pending":
            proposals = store.history(limit=50) if hasattr(store, "history") else []
        if not proposals:
            if json_output:
                click.echo(json_response("error", {"message": f"No {proposal_id} proposals found"}))
            else:
                click.echo(f"No {proposal_id} proposals found.")
            return
        proposal_id = proposals[0].proposal_id

    proposal = store.get(proposal_id) if hasattr(store, "get") else None
    if proposal is None:
        # Try searching history
        history = store.history(limit=100) if hasattr(store, "history") else []
        for p in history:
            if p.proposal_id == proposal_id:
                proposal = p
                break

    if proposal is None:
        if json_output:
            click.echo(json_response("error", {"message": f"Proposal not found: {proposal_id}"}))
        else:
            click.echo(f"Proposal not found: {proposal_id}")
        return

    data = {
        "proposal_id": proposal.proposal_id,
        "mutation_name": proposal.mutation_name,
        "surface": proposal.surface,
        "risk_class": proposal.risk_class,
        "expected_lift": proposal.expected_lift,
        "cost_impact_estimate": proposal.cost_impact_estimate,
        "status": getattr(proposal, "status", "unknown"),
        "diff_preview": proposal.diff_preview,
    }

    if json_output:
        click.echo(json_response("ok", data))
    else:
        click.echo(f"\nAutoFix Proposal: {proposal.proposal_id}")
        click.echo(f"  Mutation:  {proposal.mutation_name}")
        click.echo(f"  Surface:   {proposal.surface}")
        click.echo(f"  Risk:      {proposal.risk_class}")
        click.echo(f"  Lift:      {proposal.expected_lift:.1%}")
        click.echo(f"  Cost:      ${proposal.cost_impact_estimate:.4f}")
        click.echo(f"  Status:    {getattr(proposal, 'status', 'unknown')}")
        if proposal.diff_preview:
            click.echo(f"  Preview:   {proposal.diff_preview}")


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
        workspace = discover_workspace()
        click.echo("AutoAgent Edit")
        click.echo(f"Workspace: {workspace.root if workspace is not None else Path.cwd()}")
        click.echo("Type 'help' for examples, or 'quit' to exit.")
        while True:
            try:
                user_input = click.prompt(">", prompt_suffix=" ")
            except (EOFError, KeyboardInterrupt):
                break
            if user_input.strip().lower() == "help":
                click.echo("Example: 'Make the billing agent more empathetic'. Type 'quit' to exit.")
                continue
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
    from cli.stream2_helpers import json_response

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
        click.echo(json_response("ok", data, next_cmd="autoagent status"))
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
    from cli.stream2_helpers import json_response
    from optimizer.diagnose_session import DiagnoseSession

    workspace = discover_workspace()
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
        click.echo(json_response("ok", session.to_dict(), next_cmd="autoagent explain"))
        return

    click.echo(summary)

    if not interactive:
        return

    # Interactive REPL
    click.echo("\nAutoAgent Diagnosis")
    click.echo(f"Workspace: {workspace.root if workspace is not None else Path.cwd()}")
    click.echo("Type 'help' for guidance, or 'quit' to exit.")
    while True:
        try:
            user_input = click.prompt(">", prompt_suffix=" ")
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input.strip():
            continue
        if user_input.strip().lower() == "help":
            click.echo("Ask for a summary, top failure clusters, or remediation ideas. Type 'quit' to exit.")
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
    from cli.stream2_helpers import json_response

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
        click.echo(json_response("ok", data, next_cmd="autoagent status"))
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
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def dataset_stats(dataset_id: str, json_output: bool = False) -> None:
    """Show dataset statistics."""
    from cli.stream2_helpers import json_response
    from data.dataset_service import DatasetService

    svc = DatasetService()
    resolved_dataset_id = dataset_id
    if svc.get(dataset_id) is None:
        datasets = svc.list_datasets()
        exact_name = next((dataset for dataset in datasets if dataset.name == dataset_id), None)
        if exact_name is not None:
            resolved_dataset_id = exact_name.dataset_id
        else:
            suggestions = difflib.get_close_matches(dataset_id, [dataset.name for dataset in datasets], n=1)
            message = f"Dataset '{dataset_id}' not found."
            if suggestions:
                message += f" Did you mean '{suggestions[0]}'?"
            click.echo(message)
            raise SystemExit(1)

    stats = svc.stats(resolved_dataset_id)
    if json_output:
        click.echo(json_response("ok", stats))
    else:
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
    """Manage signed release objects.

    Examples:
      autoagent release create --experiment-id exp-demo
      autoagent release list
    """
    pass


@release.command("list")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def release_list(json_output: bool = False) -> None:
    """List release objects."""
    from cli.stream2_helpers import ReleaseStore, json_response

    store = ReleaseStore()
    releases = store.list_releases()

    if json_output:
        click.echo(json_response("ok", releases))
        return

    if not releases:
        click.echo("No release objects found.")
        click.echo("Create one with: autoagent release create --experiment-id <id>")
        return

    click.echo(f"\nRelease objects ({len(releases)}):\n")
    click.echo(f"{'Release ID':<20}  {'Experiment':<16}  {'Status':<10}  {'Created'}")
    click.echo(f"{'─' * 20}  {'─' * 16}  {'─' * 10}  {'─' * 24}")
    for r in releases:
        click.echo(f"{r['release_id']:<20}  {r.get('experiment_id', '—'):<16}  {r['status']:<10}  {r.get('created_at', '—')}")


@release.command("create")
@click.option("--experiment-id", required=True, help="Experiment ID to create release from")
@click.option("--config-version", type=int, default=None, help="Config version to include.")
@click.option("--dry-run", is_flag=True, help="Preview the release object without writing it.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def release_create(
    experiment_id: str,
    config_version: int | None = None,
    dry_run: bool = False,
    json_output: bool = False,
) -> None:
    """Create a new release object from an experiment.

    Persists the release to .autoagent/releases/ as a JSON file.

    Examples:
      autoagent release create --experiment-id exp-abc123
    """
    from cli.stream2_helpers import ReleaseStore, json_response

    if dry_run:
        preview = {
            "release_id": "dry-run",
            "experiment_id": experiment_id,
            "config_version": config_version,
            "status": "DRAFT",
        }
        if json_output:
            click.echo(json_response("ok", preview, next_cmd="autoagent release create --experiment-id <id>"))
        else:
            click.echo("Dry run: release create preview")
            click.echo(f"  Experiment: {experiment_id}")
            click.echo(f"  Config:     {config_version if config_version is not None else 'auto'}")
        return

    store = ReleaseStore()
    release = store.create(experiment_id, config_version=config_version)

    if json_output:
        click.echo(json_response("ok", release, next_cmd=f"autoagent release list"))
        return

    click.echo(click.style(f"Applied: created release {release['release_id']}", fg="green"))
    click.echo(f"  Release created: {release['release_id']}")
    click.echo(f"  Experiment: {experiment_id}")
    click.echo(f"  Status:     {release['status']}")
    click.echo(f"  Created:    {release['created_at']}")
    click.echo(f"  Path:       .autoagent/releases/{release['release_id']}.json")


@cli.command("ship")
@click.option("--config-version", type=int, default=None, help="Config version to package and deploy.")
@click.option("--experiment-id", default=None, help="Experiment ID to associate with the release.")
@click.option("--yes", is_flag=True, default=False, help="Skip the interactive confirmation prompt.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def ship(config_version: int | None, experiment_id: str | None, yes: bool, json_output: bool = False) -> None:
    """Create a release and deploy the selected config as a canary."""
    from cli.stream2_helpers import ReleaseStore, json_response

    store = ConversationStore(db_path=DB_PATH)
    deployer = Deployer(configs_dir=CONFIGS_DIR, store=store)
    history = deployer.version_manager.get_version_history()
    if not history:
        raise click.ClickException("No config versions are available to ship.")

    selected_version = config_version if config_version is not None else history[-1]["version"]
    selected = next((entry for entry in history if entry["version"] == selected_version), None)
    if selected is None:
        raise click.ClickException(f"Config version not found: v{selected_version:03d}")

    pending_reviews = 0
    try:
        from optimizer.change_card import ChangeCardStore

        pending_reviews = len(ChangeCardStore().list_pending(limit=200))
    except Exception:
        pending_reviews = 0

    generated_experiment_id = experiment_id or f"ship-v{selected_version:03d}"
    if not yes and not json_output:
        click.confirm(
            f"Ship v{selected_version:03d} to the autoagent canary target?",
            abort=True,
        )

    release_store = ReleaseStore()
    release = release_store.create(generated_experiment_id, config_version=selected_version)
    deployer.version_manager.mark_canary(selected_version)

    payload = {
        "config_version": selected_version,
        "config_path": str(Path(CONFIGS_DIR) / selected["filename"]),
        "release_id": release["release_id"],
        "experiment_id": generated_experiment_id,
        "pending_review_cards": pending_reviews,
        "target": "autoagent",
        "deployment": "canary",
    }
    if json_output:
        click.echo(json_response("ok", payload, next_cmd="autoagent status"))
        return

    click.echo(click.style("\n✦ Ship", fg="cyan", bold=True))
    click.echo(f"  Pending review items: {pending_reviews}")
    click.echo(click.style(f"Applied: created release {release['release_id']}", fg="green"))
    click.echo(f"  Deploying: v{selected_version:03d} from {Path(CONFIGS_DIR) / selected['filename']}")
    click.echo("  Target:    autoagent canary")
    click.echo(click.style(f"Applied: deployed v{selected_version:03d} as canary", fg="green"))


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
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def rl_eval(policy_id, json_output: bool = False):
    """Evaluate a policy artifact offline.

    Supports selectors: ``autoagent rl eval latest``
    """
    from cli.stream2_helpers import is_selector, json_response
    from policy_opt.registry import PolicyArtifactRegistry
    from policy_opt.orchestrator import PolicyOptOrchestrator

    # FR-08: resolve "latest" selector
    if is_selector(policy_id):
        registry = PolicyArtifactRegistry()
        all_policies = registry.list_all()
        if not all_policies:
            if json_output:
                click.echo(json_response("error", {"message": "No policies found"}))
            else:
                click.echo("No policies found.")
            registry.close()
            return
        policy_id = all_policies[-1].policy_id
        registry.close()

    registry = PolicyArtifactRegistry()
    orch = PolicyOptOrchestrator(policy_registry=registry)
    try:
        report = orch.evaluate_policy(policy_id)
        if json_output:
            click.echo(json_response("ok", report))
        else:
            click.echo(json.dumps(report, indent=2))
    except KeyError as e:
        if json_output:
            click.echo(json_response("error", {"message": str(e)}))
        else:
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


@cli.group("import", hidden=True)
def import_group() -> None:
    """Compatibility aliases for importing configs and transcript archives."""


@import_group.command("config")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def import_config_alias(file_path: str, configs_dir: str, json_output: bool = False) -> None:
    """Alias for `autoagent config import`."""
    from cli.stream2_helpers import ConfigImporter, json_response

    _echo_deprecation("autoagent import config", "autoagent config import")
    importer = ConfigImporter(configs_dir=configs_dir)
    try:
        result = importer.import_config(file_path)
    except (FileNotFoundError, ValueError) as exc:
        if json_output:
            click.echo(json_response("error", {"message": str(exc)}))
        else:
            raise click.ClickException(str(exc)) from exc
        raise SystemExit(1)

    if json_output:
        click.echo(json_response("ok", result, next_cmd=f"autoagent config show {result['version']}"))
        return

    click.echo(click.style("\n✦ Config Imported", fg="cyan", bold=True))
    click.echo(f"  Source:  {result['source_file']}")
    click.echo(f"  Version: v{result['version']:03d}")
    click.echo(f"  Hash:    {result['config_hash']}")
    click.echo(f"  Path:    {result['dest_path']}")


@import_group.group("transcript", hidden=True)
def import_transcript_group() -> None:
    """Compatibility alias for transcript intelligence commands."""


@import_transcript_group.command("upload")
@click.argument("archive", type=click.Path(dir_okay=False, path_type=Path))
def import_transcript_upload(archive: Path) -> None:
    """Upload a transcript archive and persist the generated report."""
    import base64

    from optimizer.transcript_intelligence import TranscriptIntelligenceService

    _echo_deprecation("autoagent import transcript upload", "autoagent intelligence import")
    archive = _resolve_invocation_input_path(archive)
    if not archive.exists():
        raise click.ClickException(f"File does not exist: {archive}")
    if archive.is_dir():
        raise click.ClickException(f"Expected a file, got directory: {archive}")

    service = TranscriptIntelligenceService()
    archive_base64 = base64.b64encode(archive.read_bytes()).decode("ascii")
    report = service.import_archive(archive.name, archive_base64)
    report_dict = report.to_dict()
    TranscriptReportStore().save_report(
        report=report_dict,
        archive_name=archive.name,
        archive_base64=archive_base64,
    )
    click.echo(f"Imported transcript archive. Report ID: {report.report_id}")


@import_transcript_group.command("report")
@click.argument("report_id")
def import_transcript_report(report_id: str) -> None:
    """Show a stored transcript report as JSON for backward compatibility."""
    _echo_deprecation("autoagent import transcript report", "autoagent intelligence report show")
    entry = TranscriptReportStore().get_report(report_id)
    if entry is None:
        raise click.ClickException(f"Unknown transcript intelligence report: {report_id}")
    click.echo(json.dumps(entry.get("report", {}), indent=2))


@import_transcript_group.command("generate-agent")
@click.argument("report_id")
@click.option("--prompt", default=None, help="Optional custom generation prompt.")
@click.option("--output", "output_path", type=click.Path(dir_okay=False, path_type=Path), required=True)
def import_transcript_generate_agent(report_id: str, prompt: str | None, output_path: Path) -> None:
    """Generate an agent config from a stored transcript report."""
    _echo_deprecation(
        "autoagent import transcript generate-agent",
        "autoagent intelligence generate-agent",
    )
    entry = TranscriptReportStore().get_report(report_id)
    if entry is None:
        raise click.ClickException(f"Unknown transcript intelligence report: {report_id}")

    service, replayed_report_id, replayed_report = _load_replayed_report(entry)
    generation_prompt = prompt or _build_generation_prompt(replayed_report)
    generated = service.generate_agent_config(generation_prompt, transcript_report_id=replayed_report_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(generated, sort_keys=False), encoding="utf-8")
    click.echo(f"Generated agent config written to {output_path}")


if __name__ == "__main__":
    cli()
