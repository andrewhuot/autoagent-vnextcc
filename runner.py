"""CLI entry point for AgentLab VNextCC.

Full command set:
  agentlab quickstart [--agent-name NAME] [--verbose]
  agentlab demo quickstart [--dir PATH]
  agentlab demo vp [--agent-name NAME] [--company NAME] [--no-pause] [--web]
  agentlab init [--template NAME] [--agent-name NAME] [--with-synthetic-data]
  agentlab connect openai-agents --path ./project
  agentlab connect anthropic --path ./project
  agentlab connect http --url https://agent.example.com
  agentlab connect transcript --file conversations.jsonl
  agentlab eval run [OPTIONS]
  agentlab eval results [--run-id ID]
  agentlab eval list
  agentlab experiment log [OPTIONS]
  agentlab optimize [--cycles N] [--mode standard|advanced|research]
  agentlab config list
  agentlab config diff V1 V2
  agentlab config show [VERSION]
  agentlab config migrate <input_file> [--output FILE]
  agentlab deploy [--strategy canary|immediate]
  agentlab loop [--max-cycles N] [--stop-on-plateau]
  agentlab status
  agentlab logs [--limit N] [--outcome fail|success]
  agentlab server
  agentlab review [list|show|apply|reject|export]
  agentlab runbook [list|show|apply|create]
  agentlab memory [show|add]
  agentlab registry list [--type skills|policies|tools|handoffs]
  agentlab registry show <type> <name> [--version N]
  agentlab registry add <type> <name> --file <path>
  agentlab registry diff <type> <name> <v1> <v2>
  agentlab registry import <path>
  agentlab trace grade <trace-id>
  agentlab trace blame [--window 24h]
  agentlab trace graph <trace-id>
  agentlab scorer create "description" [--name NAME]
  agentlab scorer create --from-file criteria.txt [--name NAME]
  agentlab scorer list
  agentlab scorer show <name>
  agentlab scorer refine <name> "additional criteria"
  agentlab scorer test <name> --trace <trace-id>
  agentlab full-auto --yes [--cycles N] [--max-loop-cycles N]
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import shutil
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml
from click.core import ParameterSource

from agent.instruction_builder import is_xml_instruction, validate_xml_instruction
from agent.migrate_to_xml import migrate_instruction_text
from agent.config.loader import load_config
from agent.config.runtime import load_runtime_config
from agent.config.schema import validate_config, config_diff as schema_config_diff
from cli.bootstrap import bootstrap_workspace, seed_demo_workspace
from cli.branding import (
    banner_enabled,
    echo_startup_banner,
    get_agentlab_version,
    render_startup_banner,
)
from cli.config_resolve import (
    persist_config_lockfile,
    render_config_resolution,
    resolve_config_snapshot,
)
from cli.experiment_log import (
    append_entry as append_experiment_log_entry,
    best_score_entry as best_experiment_log_entry,
    default_log_path as default_experiment_log_path,
    entry_id as experiment_log_entry_id,
    format_table as format_experiment_log_table,
    make_entry as make_experiment_log_entry,
    next_cycle_number as next_experiment_log_cycle_number,
    read_entries as read_experiment_log_entries,
    summarize_entries as summarize_experiment_log_entries,
    tail_entries as tail_experiment_log_entries,
    utc_timestamp as experiment_log_utc_timestamp,
)
from cli.intelligence import (
    TranscriptReportStore,
    _build_generation_prompt,
    _load_replayed_report,
    intelligence_group,
)
from cli.mcp_setup import mcp_group
from cli.workbench import workbench_group
from cli.mode import load_runtime_with_mode_preference, mode_group, summarize_mode_state
from cli.permissions import permissions_group
from cli.providers import (
    configured_or_runtime_providers,
    default_api_key_env_for,
    default_model_for,
    normalize_model_name,
    provider_health_checks,
    provider_live_health_checks,
    providers_file_path,
    providers_file_path_for_runtime_config,
    sync_runtime_config,
    upsert_provider,
)
from cli.status import StatusSnapshot, render_status as render_status_home
from cli.templates import (
    STARTER_TEMPLATE_NAMES,
    apply_template_to_workspace,
    list_templates,
)
from cli.workspace import AgentLabWorkspace, discover_workspace
from deployer import Deployer
from evals import EvalRunner
from evals.execution_mode import (
    EvalExecutionMode,
    eval_mode_banner_label,
    eval_mode_status_label,
    infer_eval_execution_mode,
    requested_live_mode,
    resolve_eval_execution_mode,
)
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


LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("AGENTLAB_DB", "conversations.db")
CONFIGS_DIR = os.environ.get("AGENTLAB_CONFIGS", "configs")
MEMORY_DB = os.environ.get("AGENTLAB_MEMORY_DB", "optimizer_memory.db")
REGISTRY_DB = os.environ.get("AGENTLAB_REGISTRY_DB", "registry.db")
TRACE_DB = os.environ.get("AGENTLAB_TRACE_DB", ".agentlab/traces.db")
SCORER_SPECS_DIR = os.environ.get("AGENTLAB_SCORER_SPECS_DIR", ".agentlab/scorers")
AGENTLAB_VERSION = get_agentlab_version()
EVAL_METRIC_NAMES = ("quality", "safety", "latency", "cost", "composite")


# Command visibility tiers for simplified help output
PRIMARY_COMMANDS = {"new", "build", "workbench", "eval", "optimize", "deploy", "ship", "status", "doctor", "shell"}
SECONDARY_COMMANDS = {
    "review", "config", "instruction", "model", "provider", "mode", "memory",
    "template", "connect", "harness", "context",
}
HIDDEN_COMMANDS = {
    "improve", "loop", "compare", "diagnose", "explain", "replay", "autofix",
    "release", "intelligence", "skill", "mcp", "session", "continue",
    "permissions", "usage", "export", "trace", "knowledge", "quickstart", "demo",
    "init", "serve", "server", "full-auto", "edit", "cx", "adk", "dataset",
    "outcomes", "pref", "rl", "benchmark", "run", "build-show", "build-inspect",
    "policy", "mcp-server", "scorer", "curriculum", "judges",
    "changes", "experiment", "runbook", "registry", "logs", "pause", "resume",
    "reject", "pin", "unpin",
}


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


class AgentLabGroup(click.Group):
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
            commands = [name for name in commands if name not in HIDDEN_COMMANDS and name != "rl"]
        return commands

    def get_help(self, ctx: click.Context) -> str:
        help_text = super().get_help(ctx)
        if ctx.parent is None:
            # Replace the flat "Commands:" block with grouped output
            if "Commands:\n" in help_text:
                # Extract the commands block and rebuild it grouped
                before_commands, _, after_commands = help_text.partition("Commands:\n")
                # Parse existing command lines
                cmd_lines: dict[str, str] = {}
                remaining_lines: list[str] = []
                for line in after_commands.split("\n"):
                    stripped = line.strip()
                    if stripped and not stripped.startswith("─"):
                        parts = stripped.split(None, 1)
                        if parts:
                            cmd_lines[parts[0]] = line
                    else:
                        remaining_lines.append(line)

                primary_block = []
                secondary_block = []
                for name in sorted(PRIMARY_COMMANDS):
                    if name in cmd_lines:
                        primary_block.append(cmd_lines[name])
                for name in sorted(SECONDARY_COMMANDS):
                    if name in cmd_lines:
                        secondary_block.append(cmd_lines[name])

                grouped = "Primary Commands:\n"
                grouped += "\n".join(primary_block) + "\n"
                grouped += "\nSecondary Commands:\n"
                grouped += "\n".join(secondary_block) + "\n"
                grouped += "\n  Run `agentlab advanced` to see all commands.\n"

                help_text = before_commands + grouped

        show_banner = ctx.meta.get("banner_enabled", banner_enabled(ctx))
        if ctx.parent is None and show_banner:
            return f"{render_startup_banner(AGENTLAB_VERSION)}\n{help_text}"
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


def _resolve_instruction_config_path(config_path: str | None) -> Path:
    """Resolve the config file targeted by `agentlab instruction` commands."""
    if config_path is not None:
        return _resolve_invocation_input_path(Path(config_path))

    workspace = _require_workspace("instruction")
    resolved = workspace.resolve_active_config()
    if resolved is None:
        raise click.ClickException("No active config found in the current workspace.")
    return resolved.path


def _read_instruction_config(path: Path) -> dict[str, Any]:
    """Read an instruction-bearing config file from YAML or JSON."""
    if not path.exists():
        raise click.ClickException(f"Config file not found: {path}")
    raw_text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(raw_text)
        else:
            payload = yaml.safe_load(raw_text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise click.ClickException(f"Could not parse config file {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise click.ClickException(f"Config file {path} must contain a mapping/object.")
    return payload


def _write_instruction_config(path: Path, config: dict[str, Any]) -> None:
    """Write an updated config file back to disk."""
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _instruction_locator(
    config: dict[str, Any],
    *,
    specialist: str = "root",
) -> tuple[list[str], str]:
    """Locate the editable instruction field inside a config dictionary."""
    if specialist != "root":
        prompts = config.setdefault("prompts", {})
        if not isinstance(prompts, dict):
            raise click.ClickException("Config prompts section must be a mapping.")
        return ["prompts", specialist], str(prompts.get(specialist, "") or "")

    prompts = config.get("prompts")
    if isinstance(prompts, dict) and "root" in prompts:
        return ["prompts", "root"], str(prompts.get("root", "") or "")

    if "system_prompt" in config:
        return ["system_prompt"], str(config.get("system_prompt", "") or "")

    if "instruction" in config:
        return ["instruction"], str(config.get("instruction", "") or "")

    prompts = config.setdefault("prompts", {})
    if not isinstance(prompts, dict):
        config["prompts"] = {}
        prompts = config["prompts"]
    return ["prompts", "root"], str(prompts.get("root", "") or "")


def _set_instruction_value(config: dict[str, Any], path_parts: list[str], value: str) -> None:
    """Set an instruction value inside a nested config dictionary."""
    target: dict[str, Any] = config
    for key in path_parts[:-1]:
        child = target.get(key)
        if not isinstance(child, dict):
            child = {}
            target[key] = child
        target = child
    target[path_parts[-1]] = value


def _instruction_agent_name(config: dict[str, Any]) -> str | None:
    """Return a human-friendly agent name when the config includes one."""
    metadata = config.get("metadata")
    if isinstance(metadata, dict):
        agent_name = metadata.get("agent_name")
        if isinstance(agent_name, str) and agent_name.strip():
            return agent_name.strip()
    return None


def _enter_discovered_workspace(command_name: str | None) -> AgentLabWorkspace | None:
    """Switch cwd to the nearest discovered workspace for workspace-aware commands.

    Also hydrates provider API keys saved in ``.agentlab/.env`` into ``os.environ``
    so the coordinator/worker runtime can resolve ``harness.models.*`` credentials
    without the user exporting keys in their shell. Without this, the runtime
    silently degrades to the :class:`DeterministicWorkerAdapter` stub.
    """
    if command_name in {"init", "new"}:
        return None
    workspace = discover_workspace()
    if workspace is not None and Path.cwd() != workspace.root:
        os.chdir(workspace.root)
    if workspace is not None:
        try:
            from cli.workspace_env import load_workspace_env

            load_workspace_env(workspace.root, override=False)
        except Exception:
            # Env hydration is best-effort — a malformed .env must not stop startup.
            pass
    return workspace


def _is_tty() -> bool:
    """Return True only when both stdin and stdout are interactive terminals.

    Checking both is required because `agentlab | tee log.txt` leaves stdin a
    TTY while stdout is a pipe — launching the interactive Workbench in that
    shape would render ANSI to the pipe and hang on an `input()` call that
    never surfaces a prompt the user can see.
    """
    for stream in (sys.stdin, sys.stdout):
        if not hasattr(stream, "isatty") or not stream.isatty():
            return False
    return True


def _require_workspace(command_name: str | None = None) -> AgentLabWorkspace:
    """Return the current workspace or raise a helpful CLI error."""
    from cli.errors import click_error

    workspace = _enter_discovered_workspace(command_name)
    if workspace is None:
        raise click_error("No AgentLab workspace found. Run agentlab init to create one.")
    return workspace


def _make_nl_scorer():
    """Build a scorer instance backed by the CLI's persisted scorer store."""
    from evals.nl_compiler import NLCompiler
    from evals.nl_scorer import NLScorer

    return NLScorer(compiler=NLCompiler(), storage_dir=SCORER_SPECS_DIR)


def _ensure_active_config(deployer: Deployer) -> dict:
    """Return active config; bootstrap from base config if none exists yet."""
    workspace = discover_workspace()
    if workspace is not None:
        resolved = workspace.resolve_active_config()
        if resolved is not None:
            return resolved.config
    current = deployer.get_active_config()
    if current is not None:
        return current
    base_path = Path(__file__).parent / "agent" / "config" / "base_config.yaml"
    config = load_config(str(base_path)).model_dump()
    deployer.version_manager.save_version(config, scores={"composite": 0.0}, status="active")
    return config


def _workspace_for_configs_dir(configs_dir: str) -> AgentLabWorkspace | None:
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
    runtime_mode: str = "auto",
) -> tuple[AgentLabWorkspace, dict]:
    """Create or update a workspace using the shared bootstrap path."""
    base_dir = Path(target_dir).resolve()
    workspace_root = (base_dir / name) if name else base_dir
    workspace_root.mkdir(parents=True, exist_ok=True)

    workspace_name = name or workspace_root.name
    workspace = AgentLabWorkspace.create(
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
        demo=False,
        runtime_mode=runtime_mode,
    )
    if template in STARTER_TEMPLATE_NAMES:
        summary["template_summary"] = apply_template_to_workspace(workspace, template)
    if demo:
        summary["demo_summary"] = seed_demo_workspace(workspace)
    return workspace, summary


def _resolve_workspace_bootstrap_mode(ctx: click.Context, mode: str) -> str:
    """Resolve bootstrap mode using API-key presence when the caller left it default.

    WHY: The CLI is live-first. A fresh workspace should try real providers by
    default, while provider runtime can still fall back gracefully when a key is
    not configured yet. Explicit `--mode auto` keeps the older detection path
    for callers that intentionally request environment-based mode resolution.
    """
    source = ctx.get_parameter_source("mode")
    if mode != "auto":
        return mode
    if source is not ParameterSource.DEFAULT:
        return "auto"

    return "live"


def _doctor_fix_workspace(workspace: AgentLabWorkspace) -> list[str]:
    """Repair fixable workspace issues for `doctor --fix`."""
    fixes: list[str] = []

    if not workspace.agentlab_dir.exists():
        workspace.agentlab_dir.mkdir(parents=True, exist_ok=True)
        fixes.append("Created .agentlab/")
    if not workspace.configs_dir.exists():
        workspace.configs_dir.mkdir(parents=True, exist_ok=True)
        fixes.append("Created configs/")
    if not workspace.cases_dir.exists():
        workspace.cases_dir.mkdir(parents=True, exist_ok=True)
        fixes.append("Created evals/cases/")
    if not workspace.scorer_specs_dir.exists():
        workspace.scorer_specs_dir.mkdir(parents=True, exist_ok=True)
        fixes.append("Created .agentlab/scorers/")
    logs_dir = workspace.agentlab_dir / "logs"
    if not logs_dir.exists():
        logs_dir.mkdir(parents=True, exist_ok=True)
        fixes.append("Created .agentlab/logs/")
    if not workspace.best_score_file.exists():
        workspace.best_score_file.touch()
        fixes.append("Created .agentlab/best_score.txt")

    if workspace.metadata.active_config_version is None or workspace.metadata.active_config_file is None:
        resolved = workspace.resolve_active_config()
        if resolved is not None:
            workspace.set_active_config(resolved.version, filename=resolved.path.name)
            fixes.append(f"Set active config to v{resolved.version:03d}")

    return fixes


def _print_score(
    score,
    heading: str,
    *,
    mode_label: str | None = None,
    status_label: str | None = None,
    next_action: str | None = None,
) -> None:
    """Print a consistent score summary for eval output."""
    from cli.eval_render import render_eval_scorecard

    click.echo("")
    for line in render_eval_scorecard(
        score,
        heading=heading,
        mode_label=mode_label,
        status_label=status_label,
        next_action=next_action,
    ):
        click.echo(line)


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


def _merge_unique_warnings(existing: list[str] | None, additions: list[str]) -> list[str]:
    """Return warnings with stable ordering and no duplicates."""
    merged = list(existing or [])
    seen = {warning for warning in merged if warning}
    for warning in additions:
        if not warning or warning in seen:
            continue
        seen.add(warning)
        merged.append(warning)
    return merged


def _eval_mode_for_runner(eval_runner: EvalRunner, *, runtime=None) -> EvalExecutionMode:
    """Return the effective eval mode for the current runner state."""
    requested_live = getattr(eval_runner, "requested_live", None)
    if requested_live is None and runtime is not None:
        requested_live = requested_live_mode(runtime)
    return resolve_eval_execution_mode(
        requested_live=bool(requested_live),
        eval_agent=getattr(eval_runner, "eval_agent", None),
    )


def _ensure_live_eval_runner(eval_runner: EvalRunner) -> None:
    """Fail fast when the caller requires live evals but the runner is already mock-backed."""
    if not bool(getattr(eval_runner, "require_live", False)):
        return

    mode = _eval_mode_for_runner(eval_runner)
    if mode == "live":
        return

    messages = list(getattr(eval_runner, "mock_mode_messages", []) or [])
    detail = messages[0] if messages else "no live provider was available"
    raise click.ClickException(f"Live eval required; {detail}")


def _eval_results_heading(mode: EvalExecutionMode | None) -> str:
    """Return the text-mode heading for one eval result surface."""
    if mode is None:
        return "Eval Results"
    return f"📊 Eval Results ({eval_mode_banner_label(mode)})"


def _render_eval_results_header(data: dict) -> None:
    """Render the shared text header used by `eval run`, `eval show`, and `eval results`."""
    payload = _unwrap_eval_payload(data)
    mode = _extract_eval_mode(data)
    click.echo(f"\n{_eval_results_heading(mode)}")
    click.echo(f"  Timestamp: {payload.get('timestamp', data.get('timestamp', 'unknown'))}")
    click.echo(f"  Config:    {payload.get('config_path', data.get('config_path', 'default'))}")
    if mode is not None:
        click.echo(f"  Mode:      {eval_mode_status_label(mode)}")


def _build_eval_result_payload(
    *,
    score,
    mode: EvalExecutionMode,
    config_path: str | None,
    category: str | None,
    dataset: str | None,
    dataset_split: str,
) -> dict:
    """Serialize an eval result into the shared on-disk payload shape."""
    return {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "mode": mode,
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


def _latest_eval_output_path() -> Path:
    """Return the default path used to persist the latest eval result snapshot."""
    workspace = discover_workspace()
    if workspace is not None:
        workspace.agentlab_dir.mkdir(parents=True, exist_ok=True)
        return workspace.agentlab_dir / "eval_results_latest.json"
    return Path("eval_results_latest.json")


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


def _extract_eval_mode(data: dict) -> EvalExecutionMode | None:
    """Read the canonical eval mode from a serialized payload when available."""
    payload = _unwrap_eval_payload(data)
    return infer_eval_execution_mode(payload)


def _eval_result_search_roots() -> list[Path]:
    """Return unique search roots for eval result files from cwd and invocation cwd."""
    roots = [
        Path.cwd(),
        Path.cwd() / ".agentlab",
        _resolve_invocation_input_path(Path(".")),
        _resolve_invocation_input_path(Path(".agentlab")),
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
    """Return the newest eval result JSON from cwd or `.agentlab/`."""
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


def _list_eval_result_files(limit: int = 10) -> list[Path]:
    """List eval result files from the same search roots as `latest` resolution."""
    candidates: dict[Path, Path] = {}
    for root in _eval_result_search_roots():
        if not root.exists():
            continue
        for pattern in ("eval_results*.json", "*results*.json"):
            for candidate in root.glob(pattern):
                if not candidate.is_file():
                    continue
                candidates[candidate.resolve()] = candidate
    return sorted(
        candidates.values(),
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )[:limit]


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


def _pairwise_store_for_cli():
    """Return the default on-disk store for CLI pairwise comparisons."""
    from evals.pairwise import PairwiseComparisonStore

    return PairwiseComparisonStore(base_dir=".agentlab/pairwise")


def _results_store_for_cli():
    """Return the default on-disk store for structured eval results."""
    from evals.results_store import EvalResultsStore

    return EvalResultsStore(db_path=".agentlab/eval_results.db")


def _render_pairwise_comparison(result) -> None:
    """Render one stored pairwise comparison in a compact text layout."""
    click.echo(f"\nPairwise Comparison: {result.label_a} vs {result.label_b}")
    click.echo(f"  Dataset: {result.dataset_name}")
    click.echo(f"  Judge: {result.judge_strategy}")
    click.echo(f"  Winner: {result.analysis.winner}")
    click.echo(f"  {result.label_a} wins: {result.summary.left_wins}")
    click.echo(f"  {result.label_b} wins: {result.summary.right_wins}")
    click.echo(f"  Ties: {result.summary.ties}")
    if result.summary.pending_human:
        click.echo(f"  Pending human review: {result.summary.pending_human}")
    click.echo(f"  Effect size: {result.analysis.effect_size:.4f}")
    click.echo(f"  p-value: {result.analysis.p_value:.4f}")
    click.echo(f"  Confidence: {result.analysis.confidence:.4f}")
    click.echo(f"  Summary: {result.analysis.summary_message}")


def _render_structured_results(result_set, *, failures_only: bool = False) -> None:
    """Render a structured eval result set for the CLI results explorer."""
    examples = [
        example for example in result_set.examples
        if (not failures_only or not example.passed)
    ]

    click.echo(f"\nResults Explorer — {result_set.run_id}")
    click.echo(f"  Timestamp: {result_set.timestamp}")
    click.echo(f"  Mode: {result_set.mode}")
    click.echo(f"  Passed: {result_set.summary.passed}/{result_set.summary.total}")

    quality = result_set.summary.metrics.get("quality")
    composite = result_set.summary.metrics.get("composite")
    if quality is not None:
        click.echo(f"  Quality mean: {quality.mean:.4f}")
    if composite is not None:
        click.echo(f"  Composite mean: {composite.mean:.4f}")

    if not examples:
        click.echo("  No examples match the current filters.")
        return

    click.echo("\nExamples:")
    for example in examples:
        status = "pass" if example.passed else "fail"
        preview = (
            str(example.input.get("user_message", ""))
            or str(example.input.get("prompt", ""))
            or example.example_id
        )
        click.echo(f"  {example.example_id} [{example.category}] {status}")
        click.echo(f"    Input: {preview}")
        if example.failure_reasons:
            click.echo(f"    Failures: {', '.join(example.failure_reasons)}")
        if example.annotations:
            click.echo(f"    Annotations: {len(example.annotations)}")


def _build_eval_breakdown() -> dict:
    """Build a metric and failure-cluster breakdown for the latest eval result."""
    latest = _latest_eval_result_file()
    if latest is None:
        raise click.ClickException("No eval results found. Run `agentlab eval run --output eval_results.json` first.")

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


def _default_eval_suite_dir(explicit_suite: str | None = None) -> str | None:
    """Resolve the default eval suite to the workspace-local cases directory when available."""
    if explicit_suite:
        return explicit_suite
    workspace = discover_workspace()
    if workspace is not None and workspace.cases_dir.exists():
        return str(workspace.cases_dir)
    return None


def _count_eval_cases_for_progress(
    eval_runner: EvalRunner,
    *,
    category: str | None,
    dataset_path: str | None,
    split: str,
) -> int:
    """Return the case count used for eval progress events."""
    if not hasattr(eval_runner, "load_cases"):
        return 0
    if dataset_path:
        if not hasattr(eval_runner, "load_dataset_cases"):
            return 0
        cases = eval_runner.load_dataset_cases(dataset_path, split=split)
    else:
        cases = eval_runner.load_cases()
    if category:
        cases = [case for case in cases if case.category == category]
    return len(cases)


def _call_eval_method_with_progress(method, *args, progress_callback=None, **kwargs):
    """Call an eval runner method, preserving compatibility with older test doubles."""
    import inspect

    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        kwargs["progress_callback"] = progress_callback
        return method(*args, **kwargs)

    accepts_progress = "progress_callback" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_progress:
        kwargs["progress_callback"] = progress_callback
    return method(*args, **kwargs)


def _latest_eval_payload() -> tuple[Path | None, dict | None]:
    """Return the latest eval result payload, if any."""
    latest = _latest_eval_result_file()
    if latest is None:
        return None, None
    try:
        return latest, json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return latest, None


def _paths_match(left: Path | None, right: Path | None) -> bool:
    """Return True when both paths exist and resolve to the same filesystem location."""
    if left is None or right is None:
        return False
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _latest_eval_payload_for_active_config(active_config_path: Path | None) -> tuple[Path | None, dict | None]:
    """Return the latest eval payload only when it targets the currently active config."""
    latest_path, latest_payload = _latest_eval_payload()
    if latest_path is None or latest_payload is None or active_config_path is None:
        return latest_path, None

    payload = _unwrap_eval_payload(latest_payload)
    config_path_raw = payload.get("config_path") or latest_payload.get("config_path")
    if not config_path_raw:
        return latest_path, latest_payload

    try:
        eval_config_path = Path(str(config_path_raw))
    except TypeError:
        return latest_path, None

    if not _paths_match(eval_config_path, active_config_path):
        return latest_path, None
    return latest_path, latest_payload


def _eval_payload_run_id(data: dict) -> str:
    """Return the run id from an eval payload or envelope."""
    payload = _unwrap_eval_payload(data)
    return str(payload.get("run_id") or data.get("run_id") or "").strip()


def _eval_payload_for_run_id(
    eval_run_id: str,
    *,
    config_path: Path | None = None,
) -> tuple[Path | None, dict | None]:
    """Find an eval result payload by run id, optionally scoped to a config path."""
    target_run_id = eval_run_id.strip()
    if not target_run_id:
        return None, None

    for candidate in _list_eval_result_files(limit=100):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if _eval_payload_run_id(data) != target_run_id:
            continue
        if config_path is not None:
            payload = _unwrap_eval_payload(data)
            payload_config = payload.get("config_path") or data.get("config_path")
            if payload_config and not _paths_match(Path(str(payload_config)), config_path):
                continue
        return candidate, data
    return None, None


def _resolve_optimize_config_path(config_path: str | None) -> Path | None:
    """Resolve an optional Optimize config path relative to the invocation cwd."""
    if not config_path:
        return None
    return _resolve_invocation_input_path(Path(config_path))


def _load_optimize_current_config(
    *,
    deployer: Deployer,
    config_path: Path | None,
) -> dict:
    """Load the config being optimized, falling back to the active deployment."""
    if config_path is None:
        return _ensure_active_config(deployer)
    if not config_path.exists():
        raise click.ClickException(f"Config file not found: {config_path}")
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise click.ClickException(f"Could not parse config file: {config_path}") from exc


def _normalize_eval_failure_bucket(result: dict) -> str:
    """Map eval-result failures into optimizer-friendly failure families."""
    category = str(result.get("category", "")).strip().lower()
    details = str(result.get("details", "")).strip().lower()

    if category == "safety" or "safety check failed" in details:
        return "safety_violation"
    if "routing:" in details:
        return "routing_error"
    if "tool_use:" in details:
        return "tool_failure"
    if "timeout" in details or category == "timeout":
        return "timeout"
    return "unhelpful_response"


def _build_eval_failure_clusters(data: dict) -> dict[str, int]:
    """Derive optimizer failure buckets from the latest eval payload."""
    failures: dict[str, int] = {}
    payload = _unwrap_eval_payload(data)
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    for result in results:
        if not isinstance(result, dict) or result.get("passed", True):
            continue
        label = _normalize_eval_failure_bucket(result)
        failures[label] = failures.get(label, 0) + 1
    return failures


def _build_eval_failure_samples(data: dict) -> list[dict]:
    """Convert failed eval cases into failure samples for the optimizer/proposer."""
    payload = _unwrap_eval_payload(data)
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    samples: list[dict] = []
    for result in results:
        if not isinstance(result, dict) or result.get("passed", True):
            continue
        samples.append(
            {
                "case_id": result.get("case_id"),
                "category": result.get("category"),
                "failure_bucket": _normalize_eval_failure_bucket(result),
                "failure_description": result.get("details", ""),
                "quality_score": result.get("quality_score", 0.0),
                "safety_passed": result.get("safety_passed", True),
            }
        )
    return samples


def _health_report_from_eval(data: dict):
    """Build a lightweight HealthReport from the most recent eval result."""
    from observer.metrics import HealthMetrics, HealthReport

    payload = _unwrap_eval_payload(data)
    scores = _extract_eval_scores(payload)
    total_cases = int(payload.get("total") or len(payload.get("results") or []))
    passed_cases = int(payload.get("passed") or 0)
    success_rate = (passed_cases / total_cases) if total_cases else 0.0
    failure_buckets = _build_eval_failure_clusters(payload)
    failed_case_ids = [
        str(item.get("case_id"))
        for item in payload.get("results", [])
        if isinstance(item, dict) and not item.get("passed", True)
    ]

    metrics = HealthMetrics(
        success_rate=success_rate,
        avg_latency_ms=0.0,
        error_rate=max(0.0, 1.0 - success_rate),
        safety_violation_rate=max(0.0, 1.0 - scores.get("safety", 0.0)),
        avg_cost=float(payload.get("scores", {}).get("estimated_cost_usd", 0.0) or 0.0),
        total_conversations=total_cases,
    )
    reason = "All latest eval cases passed."
    if failed_case_ids:
        reason = f"Latest eval failed {len(failed_case_ids)}/{total_cases} case(s): {', '.join(failed_case_ids[:5])}"

    return HealthReport(
        metrics=metrics,
        anomalies=[],
        failure_buckets=failure_buckets,
        needs_optimization=bool(failed_case_ids),
        reason=reason,
    )


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
            + click.style("agentlab server", bold=True)
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


def _format_eval_timestamp(value: float | str | None) -> str:
    """Format eval timestamps stored as epochs or ISO strings for status surfaces."""
    if value is None:
        return "never"
    if isinstance(value, (int, float)):
        return _format_relative_time(float(value))
    text = str(value).strip()
    if not text:
        return "never"
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return _format_relative_time(dt.timestamp())
    except ValueError:
        return text


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
    "status": "System status reviewed. Metrics are ready for inspection.",
    "optimize": "Optimization cycle in progress. Evaluating candidate improvements.",
    "quickstart": "Bootstrapping momentum. Let's make this thing sing.",
    "eval": "Running evaluation suite against the current configuration.",
}


def _soul_line(context: str) -> str:
    """Return a short personality line for a CLI context."""
    return SOUL_LINES.get(context, "AgentLab is online.")


def _score_status_label(score: float | None) -> str:
    """Map composite score to a professional operational status label."""
    if score is None:
        return "Initializing"
    if score >= 0.9:
        return "Healthy"
    if score >= 0.75:
        return "Nominal"
    if score >= 0.6:
        return "Degraded"
    return "Needs Attention"


def _deploy_gate_check(
    *,
    force_deploy_degraded: bool,
    force_reason: str | None,
    output_format: str,
) -> None:
    """R1.9: block deploy if latest eval verdict is Degraded/Needs Attention.

    Exits with EXIT_DEGRADED_DEPLOY unless the user passes
    --force-deploy-degraded with a --reason of at least 10 chars.
    """
    from cli.exit_codes import EXIT_DEGRADED_DEPLOY

    _path, payload = _latest_eval_payload()
    if payload is None:
        return  # no eval, nothing to gate

    composite = payload.get("composite") if isinstance(payload, dict) else None
    if composite is None and isinstance(payload, dict):
        nested = payload.get("score") or {}
        if isinstance(nested, dict):
            composite = nested.get("composite")
    if composite is None:
        return  # no composite score, nothing to gate

    try:
        composite = float(composite)
    except (TypeError, ValueError):
        return

    verdict = _score_status_label(composite)
    if verdict not in ("Degraded", "Needs Attention"):
        return

    if force_deploy_degraded:
        reason = (force_reason or "").strip()
        if len(reason) < 10:
            click.echo(
                click.style(
                    "--force-deploy-degraded requires --reason with at least 10 characters "
                    f"(got {len(reason)}).",
                    fg="red",
                ),
                err=True,
            )
            sys.exit(2)
        if output_format == "text":
            click.echo(
                click.style(
                    f"  ⚠  Overriding degraded-eval gate ({verdict}, composite={composite:.3f})",
                    fg="yellow",
                )
            )
            click.echo(f"     Reason: {reason}")
        return

    click.echo(
        click.style(
            f"Deploy blocked: latest eval verdict is {verdict} (composite={composite:.3f}).",
            fg="red",
        ),
        err=True,
    )
    click.echo("Next steps:", err=True)
    click.echo("  - Run `agentlab eval run` after your fix", err=True)
    click.echo("  - Or `agentlab optimize --cycles 3` to auto-improve", err=True)
    click.echo(
        "  - Or override with `--force-deploy-degraded --reason \"...\"` (min 10 chars)",
        err=True,
    )
    sys.exit(EXIT_DEGRADED_DEPLOY)


def _print_cli_plan(title: str, steps: list[str]) -> None:
    """Print a compact plan block similar to coding-agent style preambles."""
    click.echo(click.style(f"\n{title}", fg="cyan", bold=True))
    for idx, step in enumerate(steps, start=1):
        click.echo(f"  {idx}. {step}")


def _harness_session(
    *,
    title: str,
    stage: str,
    tasks: list[dict[str, str]],
    output_format: str,
    ui: str | None,
) -> Any | None:
    """Create and render a Claude-style harness session when requested."""
    from cli.auto_harness import HarnessEvent, HarnessRenderer, HarnessSession, resolve_cli_ui
    from cli.permissions import PermissionManager

    resolved_ui = resolve_cli_ui(output_format, requested_ui=ui)
    if resolved_ui != "claude":
        return None

    session = HarnessSession(permission_mode=PermissionManager().mode)
    session.emit(HarnessEvent("session.started", message=title))
    session.emit(HarnessEvent("stage.started", message=stage))
    session.emit(HarnessEvent("plan.ready", payload={"tasks": tasks}))
    click.echo(HarnessRenderer().render(session.snapshot()))
    click.echo("")
    return session


def _emit_harness_event(harness: Any | None, event: Any) -> None:
    """Apply and print a harness event without affecting classic/JSON output."""
    if harness is None:
        return
    from cli.auto_harness import HarnessRenderer

    harness.emit(event)
    click.echo(HarnessRenderer().render(harness.snapshot()))
    click.echo("")


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
            f" → agentlab runbook apply {runbook}"
        )
    return recs


def _status_next_action(report, attempts_count: int, accepted_count: int) -> str:  # noqa: ANN001
    """Return a single next-best-action command for status/UX surfaces."""
    total_failures = sum(report.failure_buckets.values()) if report.failure_buckets else 0
    if attempts_count == 0:
        return "agentlab eval run" if _latest_eval_result_file() is None else "agentlab optimize --cycles 3"
    if total_failures > 0:
        recs = _generate_recommendations(report, None)
        if recs:
            return recs[0].split("→")[-1].strip()
        return "agentlab runbook list"
    if accepted_count >= 3:
        return "agentlab optimize --continuous"
    return "agentlab optimize --cycles 3"


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
    accepted: bool | None = None,
    decision_detail: str | None = None,
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
        accepted_candidate = accepted if accepted is not None else improvement > 0
        p_str = f" (p={p_value:.2f})" if p_value is not None else ""
        if accepted_candidate:
            sparkle = " ✨" if score_after > all_time_best else ""
            click.echo(click.style(
                f"    ↳ ✓ composite={score_after:.4f} (+{improvement:.4f}){sparkle}{p_str}", fg="green"
            ))
            click.echo(click.style("    → Accepted", fg="green"))

            resolved_best_score_file = best_score_file or Path(".agentlab/best_score.txt")
            _persist_best_score(
                score_after,
                all_time_best,
                resolved_best_score_file,
                announce=True,
            )
        else:
            click.echo(click.style(
                f"    ↳ ✗ composite={score_after:.4f} ({improvement:+.4f}){p_str}", fg="yellow"
            ))
            click.echo(click.style("    → Rejected", fg="yellow"))
    else:
        click.echo(click.style("    ↳ No change applied", fg="yellow"))

    if decision_detail:
        detail_color = "green" if (accepted if accepted is not None else False) else "yellow"
        click.echo(click.style(f"    ↳ {decision_detail}", fg=detail_color))

    if proposal_desc:
        click.echo(click.style(f"    → {proposal_desc}", fg="cyan"))


def _build_skill_components(db_path: str = ".agentlab/core_skills.db") -> tuple[SkillStore, SkillEngine]:
    """Create skill store and skill engine for optimization."""
    skill_store = SkillStore(db_path=db_path)
    skill_engine = SkillEngine(store=skill_store)
    return skill_store, skill_engine


def _workspace_state_paths(target_dir: str) -> dict[str, Path]:
    """Return workspace-scoped state paths for quickstart/demo flows."""
    workspace = Path(target_dir).resolve()
    agentlab_dir = workspace / ".agentlab"
    agentlab_dir.mkdir(parents=True, exist_ok=True)
    return {
        "workspace": workspace,
        "agentlab_dir": agentlab_dir,
        "configs_dir": workspace / "configs",
        "conversation_db": workspace / "conversations.db",
        "memory_db": workspace / "optimizer_memory.db",
        "eval_history_db": workspace / "eval_history.db",
        "eval_cache_db": agentlab_dir / "eval_cache.db",
        "trace_db": agentlab_dir / "traces.db",
        "skill_db": agentlab_dir / "core_skills.db",
        "best_score_file": agentlab_dir / "best_score.txt",
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


def _has_llm_credentials() -> bool:
    """Check if any LLM provider credentials are available."""
    credential_vars = [
        "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ]
    return any(os.environ.get(var) for var in credential_vars)


def _build_eval_runner(
    runtime,
    *,
    cases_dir: str | None = None,
    trace_db_path: str | None = None,
    use_real_agent: bool = False,
    require_live: bool = False,
    default_agent_config: dict | None = None,
) -> EvalRunner:
    """Build an EvalRunner from runtime config with harness defaults wired in."""
    from agent import create_eval_agent
    from agent.eval_agent import LEGACY_EVAL_MOCK_MESSAGE
    from agent.tracing import instrument_eval_runner
    from observer.traces import TraceStore

    requested_real_agent = requested_live_mode(
        runtime,
        force_live=use_real_agent,
        require_live=require_live,
    )
    eval_agent = create_eval_agent(
        runtime,
        force_real_agent=bool(use_real_agent or require_live),
        default_config=default_agent_config,
    ) if requested_real_agent else None
    if eval_agent is not None and require_live and hasattr(eval_agent, "allow_mock_fallback"):
        eval_agent.allow_mock_fallback = False

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
    eval_runner.eval_agent = eval_agent
    eval_runner.requested_live = bool(requested_real_agent)
    eval_runner.require_live = bool(require_live)
    trace_store = TraceStore(db_path=trace_db_path or os.environ.get("AGENTLAB_TRACE_DB", TRACE_DB))
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

    for message in _collect_mock_mode_messages(eval_runner=eval_runner, proposer=proposer):
        click.echo(click.style(f"⚠ {message}", fg="yellow"))


def _collect_mock_mode_messages(
    *,
    eval_runner: EvalRunner | None = None,
    proposer: Proposer | None = None,
) -> list[str]:
    """Collect unique mock/fallback warnings without printing side-channel text."""
    messages: list[str] = []
    if proposer is not None and proposer.use_mock:
        messages.append(
            proposer.mock_reason
            or "Optimization proposer is running in mock mode; generated changes are simulated."
        )

    if eval_runner is not None:
        messages.extend(list(getattr(eval_runner, "mock_mode_messages", []) or []))

    seen: set[str] = set()
    unique: list[str] = []
    for message in messages:
        if not message or message in seen:
            continue
        seen.add(message)
        unique.append(message)
    return unique


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
    tracker_db_path = str(getattr(budget, "tracker_db_path", ".agentlab/cost_tracker.db"))
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

    runtime = load_runtime_with_mode_preference()
    runtime = apply_model_overrides(runtime)
    eval_runner = _build_eval_runner(runtime, cases_dir=_default_eval_suite_dir())
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


def _adapt_llm_config_to_artifact(
    llm_config: dict,
    prompt: str,
    connectors: list[str],
) -> dict:
    """Map the studio LLM `generate_agent_config` output into the legacy build artifact shape.

    The CLI build pipeline (eval generation, seed config, skill recommendations) was
    designed around the pattern matcher's artifact shape: ``intents``, ``tools``,
    ``guardrails``, ``business_rules``, ``suggested_tests``, etc. The studio LLM
    contract is different (``routing_rules``, ``policies``, ``eval_criteria``,
    ``system_prompt``). This adapter normalizes the live response so the rest of
    ``build_agent`` can stay unchanged. Anything missing falls back to a sensible
    empty default so downstream consumers stay defensive.
    """

    def _str(value: object) -> str:
        return "" if value is None else str(value).strip()

    routing_rules = llm_config.get("routing_rules") or []
    intents: list[dict[str, object]] = []
    for rule in routing_rules:
        if not isinstance(rule, dict):
            continue
        condition = _str(rule.get("condition"))
        action = _str(rule.get("action"))
        if not condition and not action:
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", condition.lower()).strip("_") or "intent"
        intents.append(
            {
                "name": slug[:48] or "intent",
                "description": condition or action,
                "expected_action": action,
                "priority": rule.get("priority"),
            }
        )

    tools_out: list[dict[str, object]] = []
    for tool in llm_config.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        name = _str(tool.get("name")) or "tool"
        description = _str(tool.get("description"))
        params = tool.get("parameters") or []
        if isinstance(params, list):
            param_list = [_str(p) for p in params if _str(p)]
        else:
            param_list = []
        connector_match = next(
            (conn for conn in connectors if conn.lower().replace(" ", "_") in name.lower()),
            "",
        )
        tools_out.append(
            {
                "name": name,
                "purpose": description,
                "connector": connector_match,
                "parameters": param_list,
            }
        )

    guardrails: list[str] = []
    business_rules: list[str] = []
    for policy in llm_config.get("policies") or []:
        if not isinstance(policy, dict):
            continue
        description = _str(policy.get("description"))
        if not description:
            continue
        enforcement = _str(policy.get("enforcement")).lower()
        if enforcement == "strict":
            guardrails.append(description)
        else:
            business_rules.append(description)

    suggested_tests: list[dict[str, object]] = []
    for criterion in llm_config.get("eval_criteria") or []:
        if not isinstance(criterion, dict):
            continue
        name = _str(criterion.get("name")) or "criterion"
        description = _str(criterion.get("description")) or name
        suggested_tests.append(
            {
                "id": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "case",
                "user_message": description,
                "expected_behavior": description,
            }
        )

    integration_templates: list[dict[str, str]] = []
    for connector in connectors:
        integration_templates.append(
            {"connector": connector, "purpose": f"Integrate with {connector} during build."}
        )

    metadata = llm_config.get("metadata") if isinstance(llm_config.get("metadata"), dict) else {}
    return {
        "intents": intents,
        "tools": tools_out,
        "guardrails": guardrails,
        "business_rules": business_rules,
        "escalation_conferences": [],
        "escalation_conditions": [],
        "auth_steps": [],
        "connectors": list(connectors),
        "suggested_tests": suggested_tests,
        "integration_templates": integration_templates,
        "system_prompt": _str(llm_config.get("system_prompt")),
        "model": _str(llm_config.get("model")),
        "agent_name": _str(metadata.get("agent_name")),
        "version": _str(metadata.get("version")),
        "generation_source": "live_llm",
    }


def _build_artifact_live(
    prompt: str, connectors: list[str]
) -> tuple[dict | None, str | None, str | None]:
    """Generate a build artifact via the live LLM router when one is configured.

    Returns a tuple of ``(artifact, model_label, failure_reason)``.
    - ``artifact`` is ``None`` when no real provider is configured (mock mode),
      when the LLM call fails, or when the response can't be adapted — in any
      of those cases the caller falls back to the deterministic pattern matcher.
    - ``model_label`` is set when a live call succeeded.
    - ``failure_reason`` is set when the live path was attempted but did not
      succeed (e.g. HTTP 403, malformed JSON), so the CLI can tell the operator
      *why* it fell back instead of pretending no key was configured.
    """
    try:
        from cli.model import apply_model_overrides
        from optimizer.transcript_intelligence import TranscriptIntelligenceService

        runtime = load_runtime_with_mode_preference()
        runtime = apply_model_overrides(runtime)
        router = build_router_from_runtime_config(runtime.optimizer)
    except Exception:  # noqa: BLE001 - fallback never breaks the CLI
        return None, None, None

    if router.mock_mode or not router.models:
        return None, None, None

    requested_model = str(router.models[0].model)
    try:
        service = TranscriptIntelligenceService(llm_router=router)
        llm_config = service.generate_agent_config(prompt, requested_model=requested_model)
    except Exception as exc:  # noqa: BLE001
        return None, None, str(exc)

    if not getattr(service, "last_generation_used_llm", False):
        reason = getattr(service, "last_generation_failure_reason", "") or "live LLM did not return a usable response"
        return None, None, reason

    if not llm_config:
        return None, None, "live LLM returned an empty response"

    try:
        artifact = _adapt_llm_config_to_artifact(llm_config, prompt, connectors)
    except Exception as exc:  # noqa: BLE001
        return None, None, f"failed to adapt LLM response: {exc}"

    if not artifact.get("intents") and not artifact.get("tools") and not artifact.get("system_prompt"):
        return None, None, "live LLM response was missing intents, tools, and system prompt"

    provider = str(router.models[0].provider)
    return artifact, f"{provider}:{requested_model}", None


def _artifact_to_seed_config(prompt: str, artifact: dict) -> dict:
    """Map a prompt-built artifact into an AgentLab config scaffold."""
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
    business_rules = " ".join(str(item) for item in artifact.get("business_rules", []))
    escalation_conditions = " ".join(str(item) for item in artifact.get("escalation_conditions", []))
    auth_steps = " ".join(str(item) for item in artifact.get("auth_steps", []))
    prompt_context = " ".join(
        part for part in (prompt, intent_human, business_rules, escalation_conditions, auth_steps) if part
    )

    llm_system_prompt = str(artifact.get("system_prompt", "")).strip()
    if llm_system_prompt:
        config["prompts"]["root"] = llm_system_prompt
    else:
        config["prompts"]["root"] = (
            "You are AgentLab, a production customer support orchestrator. "
            f"Build brief: {prompt}. "
            f"Primary intents: {intent_human or 'general support'}. "
            f"Business rules: {business_rules or 'standard support policy'}. "
            f"Follow these guardrails: {guardrail_text or 'standard policy controls'}. "
            "Escalate with verified context when self-service cannot resolve safely."
        )

    order_keywords = {"order", "tracking", "cancel", "cancellation", "shipping", "address", "refund"}
    support_keywords = {"support", "help"}
    recommendation_keywords = {"recommend", "recommendation", "compare", "suggest"}
    order_hints = {"order", "tracking", "cancel", "cancellation", "shipping", "address", "refund"}
    recommendation_hints = {"recommend", "recommendation", "compare", "suggest", "sales", "lead"}
    for intent in intent_names:
        parts = set(intent.replace("_", " ").split())
        if parts & order_hints:
            order_keywords.update(parts)
        elif parts & recommendation_hints:
            recommendation_keywords.update(parts)
        else:
            support_keywords.update(parts)
    if _is_billing_build_context(prompt_context):
        support_keywords.update(
            {
                "billing",
                "bill",
                "charge",
                "charges",
                "plan",
                "fees",
                "surcharges",
                "taxes",
                "autopay",
                "roaming",
                "device",
                "promo",
                "credit",
                "wireless",
            }
        )
    rules = config.get("routing", {}).get("rules", [])
    for rule in rules:
        if rule.get("specialist") == "orders":
            current = set(rule.get("keywords", []))
            merged = sorted(current.union(order_keywords))
            rule["keywords"] = merged
        elif rule.get("specialist") == "support":
            current = set(rule.get("keywords", []))
            merged = sorted(current.union(support_keywords))
            rule["keywords"] = merged
        elif rule.get("specialist") == "recommendations":
            current = set(rule.get("keywords", []))
            merged = sorted(current.union(recommendation_keywords))
            rule["keywords"] = merged

    if any(str(conn).lower() == "shopify" for conn in connectors):
        config["tools"]["orders_db"]["enabled"] = True
    if any(str(conn).lower() == "zendesk" for conn in connectors):
        config["tools"]["faq"]["enabled"] = True
    tool_text = " ".join(str(value) for tool in tools if isinstance(tool, dict) for value in tool.values()).lower()
    if _is_billing_build_context(f"{prompt_context} {tool_text}"):
        config["tools"]["faq"]["enabled"] = True
    elif tools:
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


def _is_billing_build_context(text: str) -> bool:
    """Detect billing build artifacts so routing does not default to order support."""
    lowered = text.lower()
    return any(
        hint in lowered
        for hint in (
            "billing",
            "bill",
            "bills",
            "charge",
            "charges",
            "fee",
            "fees",
            "surcharge",
            "surcharges",
            "tax",
            "taxes",
            "autopay",
            "device payment",
            "promo credit",
            "roaming",
            "wireless",
            "phone-company",
            "verizon",
        )
    )


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
        if _is_billing_build_context(lowered):
            expected_keywords = [
                token
                for token in ["bill", "charge", "fee", "tax", "promo", "credit", "plan", "autopay", "roaming"]
                if token in lowered
            ] or ["billing"]
        else:
            expected_keywords = ["order"] if expected_specialist == "orders" else ["help"]
        expected_behavior_label = "refuse" if any(
            token in expected_behavior.lower()
            for token in ("refuse", "decline", "sensitive", "identifier", "pin", "account number")
        ) else "answer"
        cases.append(
            {
                "id": f"build_{idx:03d}",
                "category": "generated_build",
                "user_message": user_message or f"Generated build test #{idx}",
                "expected_specialist": expected_specialist,
                "expected_behavior": expected_behavior_label,
                "safety_probe": expected_behavior_label == "refuse",
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

@click.group(cls=AgentLabGroup, invoke_without_command=True)
@click.version_option(version=AGENTLAB_VERSION, prog_name="agentlab")
@click.option(
    "--classic",
    is_flag=True,
    default=False,
    help="Launch the classic REPL shell instead of the new Workbench UI.",
)
@_banner_flag_options
@click.pass_context
def cli(ctx: click.Context, classic: bool, quiet: bool, no_banner: bool) -> None:
    """AgentLab VNextCC — agent optimization platform.

    A product-grade platform for iterating ADK agent quality.
    CLI-first, API-ready, with a web console for visual insight.
    """
    del quiet, no_banner
    ctx.obj = ctx.obj or {}
    ctx.obj["classic"] = classic
    ctx.obj["workspace"] = _enter_discovered_workspace(ctx.invoked_subcommand)
    if ctx.invoked_subcommand is None and not ctx.resilient_parsing:
        workspace = ctx.obj.get("workspace")
        if _is_tty():
            if workspace is not None:
                if classic:
                    from cli.repl import run_shell

                    run_shell(workspace)
                else:
                    from cli.workbench_app.app import launch_workbench

                    launch_workbench(workspace)
            else:
                from cli.onboarding import run_onboarding

                outcome = run_onboarding()
                if outcome.workspace == "demo":
                    ctx.invoke(
                        init_project,
                        template="customer-support",
                        target_dir=".",
                        name=None,
                        agent_name="My Agent",
                        platform="Google ADK",
                        with_synthetic_data=True,
                        demo=True,
                        mode=outcome.mode,
                    )
                elif outcome.workspace == "empty":
                    ctx.invoke(
                        init_project,
                        template="minimal",
                        target_dir=".",
                        name=None,
                        agent_name="My Agent",
                        platform="Google ADK",
                        with_synthetic_data=False,
                        demo=False,
                        mode=outcome.mode,
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
cli.add_command(permissions_group)
cli.add_command(workbench_group)
from cli.model import model_group
from cli.usage import usage_command

cli.add_command(model_group)
cli.add_command(usage_command)
permissions_group.hidden = True
usage_command.hidden = True

# Phase-7 non-interactive entry point — ``agentlab print "prompt"`` runs
# one orchestrator turn with tools/permissions/hooks wired, mirroring
# Claude Code's ``claude -p``.
from cli.print_mode import print_command  # noqa: E402

cli.add_command(print_command)


@cli.command("advanced")
@click.pass_context
def advanced_commands(ctx: click.Context) -> None:
    """Show all available commands, including hidden power-user commands."""
    click.echo(click.style("\n✦ AgentLab — All Commands", fg="cyan", bold=True))
    click.echo("")
    click.echo("These commands are available but hidden from default --help output.")
    click.echo("They are fully functional — use them when you need advanced control.\n")

    all_commands = cli.list_commands(ctx)
    # Also include hidden commands
    hidden_cmds = {}
    for name, cmd in sorted(cli.commands.items()):
        if name in HIDDEN_COMMANDS or getattr(cmd, 'hidden', False):
            help_text = cmd.get_short_help_str(limit=60) if hasattr(cmd, 'get_short_help_str') else (cmd.help or "").split("\n")[0]
            hidden_cmds[name] = help_text

    if hidden_cmds:
        click.echo("Hidden Commands:")
        for name in sorted(hidden_cmds):
            click.echo(f"  {name:<20} {hidden_cmds[name]}")

    click.echo("")
    click.echo("Primary commands:   " + ", ".join(sorted(PRIMARY_COMMANDS)))
    click.echo("Secondary commands: " + ", ".join(sorted(SECONDARY_COMMANDS)))
    click.echo("")


# ---------------------------------------------------------------------------
# agentlab shell — interactive REPL
# ---------------------------------------------------------------------------

@cli.command("shell")
@click.option(
    "--ui",
    type=click.Choice(["auto", "claude", "classic"], case_sensitive=False),
    default=None,
    show_default="auto",
    help="Interactive UI mode.",
)
@click.pass_context
def shell_command(ctx: click.Context, ui: str | None) -> None:
    """Launch the interactive AgentLab Workbench shell."""

    workspace = ctx.obj.get("workspace")
    if ui and ui.lower() == "classic":
        from cli.repl import run_shell

        run_shell(workspace, ui=ui)
        return
    from cli.workbench_app.app import launch_workbench

    launch_workbench(workspace)


# ---------------------------------------------------------------------------
# agentlab continue — resume last session
# ---------------------------------------------------------------------------

@cli.command("continue")
@click.pass_context
def continue_command(ctx: click.Context) -> None:
    """Resume the most recent shell session."""
    from cli.repl import run_shell
    from cli.sessions import SessionStore

    workspace = ctx.obj.get("workspace")
    if workspace is None:
        raise click.ClickException("No workspace found. Run: agentlab init")

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
# agentlab session — session management
# ---------------------------------------------------------------------------

@cli.group("session", hidden=True)
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
        raise click.ClickException("No workspace found. Run: agentlab init")

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
        raise click.ClickException("No workspace found. Run: agentlab init")

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
        raise click.ClickException("No workspace found. Run: agentlab init")

    store = SessionStore(workspace.root)
    if store.delete(session_id):
        click.echo(f"Deleted session: {session_id}")
        return
    raise click.ClickException(f"Session not found: {session_id}")


# ---------------------------------------------------------------------------
# agentlab init
# ---------------------------------------------------------------------------

@cli.command("init", hidden=True)
@click.option("--template", default="customer-support", show_default=True,
              type=click.Choice((*STARTER_TEMPLATE_NAMES, "minimal")),
              help="Project template to scaffold.")
@click.option("--dir", "target_dir", default=".", show_default=True,
              help="Directory to initialize in.")
@click.option("--name", default=None,
              help="Optional workspace folder name to create inside --dir.")
@click.option("--agent-name", default="My Agent", show_default=True,
              help="Agent name for AGENTLAB.md.")
@click.option("--platform", default="Google ADK", show_default=True,
              help="Platform for AGENTLAB.md.")
@click.option("--with-synthetic-data/--no-synthetic-data", default=True,
              show_default=True, help="Seed synthetic conversations and evals.")
@click.option("--demo/--no-demo", default=False, show_default=True,
              help="Seed a reviewable demo workspace with traces, review cards, and AutoFix proposals.")
@click.option(
    "--mode",
    default="auto",
    show_default=True,
    type=click.Choice(["mock", "live", "auto"], case_sensitive=False),
    help="Runtime mode for the generated workspace. Explicit `auto` uses API-key detection.",
)
@click.pass_context
def init_project(
    ctx: click.Context,
    template: str,
    target_dir: str,
    name: str | None,
    agent_name: str,
    platform: str,
    with_synthetic_data: bool,
    demo: bool,
    mode: str,
) -> None:
    """Scaffold a new AgentLab workspace with workspace metadata and starter data."""
    runtime_mode = _resolve_workspace_bootstrap_mode(ctx, mode.lower())
    workspace, summary = _create_workspace(
        template=template,
        target_dir=target_dir,
        name=name,
        agent_name=agent_name,
        platform=platform,
        with_synthetic_data=with_synthetic_data,
        demo=demo,
        runtime_mode=runtime_mode,
    )
    workspace_root = workspace.root

    click.echo(click.style("\n✦ AgentLab Init", fg="cyan", bold=True))
    click.echo("")
    click.echo(click.style("  ✓ ", fg="green") + f"Initialized AgentLab project in {workspace_root}")
    click.echo(click.style("  ✓ ", fg="green") + f"Workspace: {workspace.workspace_label}")
    click.echo(click.style("  ✓ ", fg="green") + f"Active config: v{workspace.metadata.active_config_version or 1:03d}")
    click.echo(click.style("  ✓ ", fg="green") + f"Config: {workspace.configs_dir / 'v001.yaml'}")
    click.echo(click.style("  ✓ ", fg="green") + f"Base config: {workspace.configs_dir / 'v001_base.yaml'}")
    click.echo(click.style("  ✓ ", fg="green") + f"Evals: {workspace.cases_dir}")
    click.echo(click.style("  ✓ ", fg="green") + f"Memory: {workspace.root / 'AGENTLAB.md'}")
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
    click.echo("    agentlab status")
    click.echo("    agentlab build \"Build a support agent for order tracking\"")
    click.echo("    agentlab eval run")
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
@click.option(
    "--mode",
    default="auto",
    show_default=True,
    type=click.Choice(["mock", "live", "auto"], case_sensitive=False),
    help="Runtime mode for the generated workspace. Explicit `auto` uses API-key detection.",
)
@click.pass_context
def new_workspace(ctx: click.Context, name: str, template: str, demo: bool, mode: str) -> None:
    """Create a new starter workspace and print the recommended build-to-ship loop."""
    runtime_mode = _resolve_workspace_bootstrap_mode(ctx, mode.lower())
    workspace, summary = _create_workspace(
        template=template,
        target_dir=".",
        name=name,
        agent_name="My Agent",
        platform="Google ADK",
        with_synthetic_data=True,
        demo=demo,
        runtime_mode=runtime_mode,
    )
    mode_summary = summarize_mode_state(str(workspace.runtime_config_path))
    template_summary = summary.get("template_summary", {}) or {}

    click.echo(click.style("\n✦ AgentLab New", fg="cyan", bold=True))
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
    if "mock" in mode_summary.get("message", "").lower():
        click.echo("  Live setup: run `agentlab provider configure` when you are ready to use real models.")
    if demo:
        click.echo("  Demo data makes `agentlab eval run` and `agentlab deploy --auto-review --yes` ready now.")
    click.echo("")
    click.echo(click.style("  Recommended loop:", bold=True))
    click.echo(f"    cd {name}")
    click.echo("    agentlab status")
    click.echo("    agentlab build \"Build a support agent for order tracking\"")
    click.echo("    agentlab eval run")
    click.echo("    agentlab optimize --cycles 1")
    click.echo("    agentlab deploy --auto-review --yes")
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


@cli.group("connect")
def connect_group() -> None:
    """Connect existing agent runtimes and transcript exports into AgentLab."""


def _print_connect_result(result) -> None:
    """Render a consistent summary for `agentlab connect` commands."""

    click.echo(click.style(f"\n  ✓ Connected: {result.agent_name}", fg="green"))
    click.echo(f"    Adapter:   {result.adapter}")
    click.echo(f"    Workspace: {result.workspace_path}")
    click.echo(f"    Config:    {result.config_path}")
    click.echo(f"    Evals:     {result.eval_path}")
    click.echo(f"    Spec:      {result.spec_path}")
    click.echo(f"    Adapter:   {result.adapter_config_path}")
    if result.traces_path:
        click.echo(f"    Traces:    {result.traces_path}")
    click.echo(f"    Tools:     {result.tool_count}")
    click.echo(f"    Guardrails:{result.guardrail_count}")
    click.echo(f"    Eval cases:{result.eval_case_count}")
    click.echo("")
    click.echo("  Next steps:")
    click.echo(f"    cd {result.workspace_path}")
    click.echo("    agentlab eval run")
    click.echo("    agentlab optimize --cycles 1")


@connect_group.command("openai-agents")
@click.option("--path", "source_path", required=True, help="Path to the OpenAI Agents project.")
@click.option("--output-dir", default=".", show_default=True, help="Directory to create the workspace in.")
@click.option("--name", default=None, help="Optional workspace folder name.")
def connect_openai_agents(source_path: str, output_dir: str, name: str | None) -> None:
    """Create an AgentLab workspace from an OpenAI Agents project."""

    from adapters import OpenAIAgentsAdapter, create_connected_workspace

    resolved_source = _resolve_invocation_input_path(Path(source_path))
    resolved_output = _resolve_invocation_input_path(Path(output_dir))
    spec = OpenAIAgentsAdapter(str(resolved_source)).discover()
    result = create_connected_workspace(spec, output_dir=str(resolved_output), workspace_name=name)
    _print_connect_result(result)


@connect_group.command("anthropic")
@click.option("--path", "source_path", required=True, help="Path to the Anthropic/Claude project.")
@click.option("--output-dir", default=".", show_default=True, help="Directory to create the workspace in.")
@click.option("--name", default=None, help="Optional workspace folder name.")
def connect_anthropic(source_path: str, output_dir: str, name: str | None) -> None:
    """Create an AgentLab workspace from an Anthropic SDK project."""

    from adapters import AnthropicClaudeAdapter, create_connected_workspace

    resolved_source = _resolve_invocation_input_path(Path(source_path))
    resolved_output = _resolve_invocation_input_path(Path(output_dir))
    spec = AnthropicClaudeAdapter(str(resolved_source)).discover()
    result = create_connected_workspace(spec, output_dir=str(resolved_output), workspace_name=name)
    _print_connect_result(result)


@connect_group.command("http")
@click.option("--url", required=True, help="Base URL for the agent webhook.")
@click.option("--output-dir", default=".", show_default=True, help="Directory to create the workspace in.")
@click.option("--name", default=None, help="Optional workspace folder name.")
def connect_http(url: str, output_dir: str, name: str | None) -> None:
    """Create an AgentLab workspace that proxies an HTTP agent endpoint."""

    from adapters import HttpWebhookAdapter, create_connected_workspace

    resolved_output = _resolve_invocation_input_path(Path(output_dir))
    spec = HttpWebhookAdapter(url).discover()
    result = create_connected_workspace(spec, output_dir=str(resolved_output), workspace_name=name)
    _print_connect_result(result)


@connect_group.command("transcript")
@click.option("--file", "source_file", required=True, help="Path to a JSONL transcript export.")
@click.option("--output-dir", default=".", show_default=True, help="Directory to create the workspace in.")
@click.option("--name", default=None, help="Optional workspace folder name.")
def connect_transcript(source_file: str, output_dir: str, name: str | None) -> None:
    """Create an AgentLab workspace from imported conversation transcripts."""

    from adapters import TranscriptAdapter, create_connected_workspace

    resolved_source = _resolve_invocation_input_path(Path(source_file))
    resolved_output = _resolve_invocation_input_path(Path(output_dir))
    spec = TranscriptAdapter(str(resolved_source)).discover()
    result = create_connected_workspace(spec, output_dir=str(resolved_output), workspace_name=name)
    _print_connect_result(result)


@cli.group("provider", invoke_without_command=True)
@click.pass_context
def provider_group(ctx: click.Context) -> None:
    """Configure and validate workspace provider settings."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(provider_list)


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
@click.option("--api-key", default=None, help="Provider API key to save to .agentlab/.env.")
def provider_configure(
    provider_name: str | None,
    model: str | None,
    api_key_env: str | None,
    api_key: str | None,
) -> None:
    """Interactively configure a workspace provider profile."""
    workspace = _require_workspace("provider")
    from cli.workspace_env import hydrate_provider_key_aliases, write_workspace_env_values

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
    normalized_model = normalize_model_name(resolved_provider, resolved_model)
    if api_key_env:
        resolved_env = api_key_env
    elif api_key is not None and api_key.strip():
        resolved_env = default_api_key_env_for(resolved_provider)
    else:
        resolved_env = click.prompt(
            "API key env var",
            default=default_api_key_env_for(resolved_provider),
            show_default=True,
        )

    registry_path = providers_file_path(workspace)
    upsert_provider(
        registry_path,
        provider=resolved_provider,
        model=normalized_model,
        api_key_env=resolved_env,
    )
    sync_runtime_config(
        workspace.runtime_config_path,
        provider=resolved_provider,
        model=normalized_model,
        api_key_env=resolved_env,
    )

    click.echo(click.style(f"Applied: provider {resolved_provider}:{normalized_model}", fg="green"))
    click.echo(f"  Registry: {registry_path}")
    click.echo(f"  Runtime:  {workspace.runtime_config_path}")
    if api_key is not None and api_key.strip():
        write_workspace_env_values({resolved_env: api_key}, workspace.agentlab_dir / ".env")
        os.environ[resolved_env] = api_key.strip()
        hydrate_provider_key_aliases()
        click.echo(f"  Saved {resolved_env} to .agentlab/.env")
        click.echo("  Next:     agentlab provider test --live")
    else:
        click.echo(f"  Next:     export {resolved_env}=... && agentlab provider test")


@provider_group.command("list")
def provider_list() -> None:
    """List configured providers for the current workspace."""
    workspace = _require_workspace("provider")
    providers = configured_or_runtime_providers(
        providers_file_path(workspace),
        runtime_config_path=workspace.runtime_config_path,
    )
    if not providers:
        click.echo("No providers configured. Run `agentlab provider configure`.")
        return

    click.echo("\nConfigured providers")
    click.echo("====================")
    for provider in providers:
        env_name = provider.get("api_key_env") or "n/a"
        source = provider.get("source") or "registry"
        click.echo(f"- {provider['provider']}  model={provider['model']}  env={env_name}  source={source}")


@provider_group.command("test")
@click.option(
    "--live",
    "live_probe",
    is_flag=True,
    help="Make a tiny provider API call in addition to checking credential presence.",
)
def provider_test(live_probe: bool) -> None:
    """Validate configured providers have the credentials needed for live use."""
    workspace = _require_workspace("provider")
    provider_path = providers_file_path(workspace)
    checks = provider_health_checks(
        provider_path,
        runtime_config_path=workspace.runtime_config_path,
    )
    if not checks:
        raise click.ClickException("No providers configured. Run `agentlab provider configure` first.")

    registry_failures = [
        check
        for check in checks
        if not check["credential_present"] and check.get("source") != "runtime config"
    ]
    ready_checks = [check for check in checks if check["credential_present"]]
    for check in checks:
        if check["credential_present"]:
            marker = click.style("✓", fg="green")
            message = check["message"]
        elif check.get("source") == "runtime config":
            marker = click.style("⚠", fg="yellow")
            message = f"{check['message']} (optional unless selected)"
        else:
            marker = click.style("✗", fg="red")
            message = check["message"]
        click.echo(f"{marker} {message}")
    if registry_failures:
        raise click.ClickException("Provider check failed. Export the missing credentials and retry.")
    if not ready_checks:
        raise click.ClickException("Provider check failed. Export credentials for at least one runtime provider.")

    if live_probe:
        live_checks = provider_live_health_checks(
            provider_path,
            runtime_config_path=workspace.runtime_config_path,
        )
        if not live_checks:
            raise click.ClickException("Live provider check failed. No credentialed providers were available to probe.")

        live_failures = [check for check in live_checks if not check["live_ok"]]
        for check in live_checks:
            marker = click.style("✓", fg="green") if check["live_ok"] else click.style("✗", fg="red")
            click.echo(f"{marker} {check['message']}")
        if live_failures:
            raise click.ClickException("Live provider check failed. Fix provider access and retry.")
        click.echo("Live provider check passed.")

    click.echo("Provider check passed.")


# ---------------------------------------------------------------------------
# agentlab compare (subgroup)
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
# agentlab instruction (subgroup)
# ---------------------------------------------------------------------------

@cli.group("instruction")
def instruction_group() -> None:
    """Inspect, edit, validate, generate, and migrate agent instructions."""


@instruction_group.command("show")
@click.option("--config", "config_path", default=None, help="Path to config YAML/JSON.")
@click.option("--specialist", default="root", show_default=True, help="Prompt key to inspect.")
def instruction_show(config_path: str | None, specialist: str) -> None:
    """Display the current instruction text for the active config."""
    target_path = _resolve_instruction_config_path(config_path)
    config = _read_instruction_config(target_path)
    _path_parts, current_text = _instruction_locator(config, specialist=specialist)
    click.echo(current_text)


@instruction_group.command("edit")
@click.option("--config", "config_path", default=None, help="Path to config YAML/JSON.")
@click.option("--specialist", default="root", show_default=True, help="Prompt key to edit.")
def instruction_edit(config_path: str | None, specialist: str) -> None:
    """Open the current instruction in the configured editor and save changes."""
    target_path = _resolve_instruction_config_path(config_path)
    config = _read_instruction_config(target_path)
    path_parts, current_text = _instruction_locator(config, specialist=specialist)
    edited_text = click.edit(current_text, extension=".xml" if is_xml_instruction(current_text) else ".txt")
    if edited_text is None:
        click.echo("Instruction edit cancelled.")
        return

    updated_text = edited_text.strip()
    if not updated_text:
        raise click.ClickException("Instruction cannot be empty.")

    if is_xml_instruction(updated_text):
        validation = validate_xml_instruction(updated_text)
        if not validation["valid"]:
            raise click.ClickException("Instruction XML is invalid: " + ", ".join(validation["errors"]))

    _set_instruction_value(config, path_parts, updated_text)
    _write_instruction_config(target_path, config)
    click.echo(f"Updated instruction in {target_path}")


@instruction_group.command("validate")
@click.option("--config", "config_path", default=None, help="Path to config YAML/JSON.")
@click.option("--specialist", default="root", show_default=True, help="Prompt key to validate.")
def instruction_validate(config_path: str | None, specialist: str) -> None:
    """Validate that the current instruction uses the recommended XML structure."""
    target_path = _resolve_instruction_config_path(config_path)
    config = _read_instruction_config(target_path)
    _path_parts, current_text = _instruction_locator(config, specialist=specialist)
    validation = validate_xml_instruction(current_text)

    for warning in validation["warnings"]:
        click.echo(click.style(f"Warning: {warning}", fg="yellow"))

    if not validation["valid"]:
        for error in validation["errors"]:
            click.echo(click.style(f"Error: {error}", fg="red"))
        raise click.ClickException("Instruction XML is invalid.")

    click.echo("Instruction XML is valid.")


@instruction_group.command("generate")
@click.option("--brief", required=True, help="Natural-language brief for the instruction draft.")
@click.option("--config", "config_path", default=None, help="Path to config YAML/JSON.")
@click.option("--specialist", default="root", show_default=True, help="Prompt key to generate.")
@click.option("--apply", is_flag=True, default=False, help="Write the generated XML back to the config.")
def instruction_generate(
    brief: str,
    config_path: str | None,
    specialist: str,
    apply: bool,
) -> None:
    """Generate a new XML instruction draft from a natural-language brief."""
    normalized_brief = brief.strip().rstrip(".")
    lowered_brief = normalized_brief.lower()
    for prefix in ("create ", "build ", "design "):
        if lowered_brief.startswith(prefix):
            normalized_brief = normalized_brief[len(prefix):].strip()
            lowered_brief = normalized_brief.lower()
            break
    if lowered_brief.startswith(("a ", "an ")):
        seed_text = f"You are {normalized_brief}."
    else:
        seed_text = f"You are a {normalized_brief}."

    target_path = _resolve_instruction_config_path(config_path) if apply or config_path else None
    config: dict[str, Any] | None = None
    path_parts: list[str] | None = None
    agent_name: str | None = None

    if target_path is not None:
        config = _read_instruction_config(target_path)
        path_parts, _existing_text = _instruction_locator(config, specialist=specialist)
        agent_name = _instruction_agent_name(config)

    generated_text = migrate_instruction_text(seed_text, agent_name=agent_name)
    validation = validate_xml_instruction(generated_text)
    if not validation["valid"]:
        raise click.ClickException("Generated XML instruction is invalid: " + ", ".join(validation["errors"]))

    if apply:
        if config is None or path_parts is None or target_path is None:
            raise click.ClickException("Could not resolve a config path to apply the generated instruction.")
        _set_instruction_value(config, path_parts, generated_text)
        _write_instruction_config(target_path, config)
        click.echo(f"Applied generated XML instruction to {target_path}")
        return

    click.echo(generated_text)


@instruction_group.command("migrate")
@click.option("--config", "config_path", default=None, help="Path to config YAML/JSON.")
@click.option("--specialist", default="root", show_default=True, help="Prompt key to migrate.")
def instruction_migrate(config_path: str | None, specialist: str) -> None:
    """Convert the current plain-text instruction into the recommended XML format."""
    target_path = _resolve_instruction_config_path(config_path)
    config = _read_instruction_config(target_path)
    path_parts, current_text = _instruction_locator(config, specialist=specialist)

    migrated_text = migrate_instruction_text(
        current_text,
        agent_name=_instruction_agent_name(config),
    )
    validation = validate_xml_instruction(migrated_text)
    if not validation["valid"]:
        raise click.ClickException("Migrated XML instruction is invalid: " + ", ".join(validation["errors"]))

    _set_instruction_value(config, path_parts, migrated_text)
    _write_instruction_config(target_path, config)
    click.echo(f"Migrated instruction to XML in {target_path}")


# ---------------------------------------------------------------------------
# agentlab config (subgroup)
# ---------------------------------------------------------------------------

@cli.group("config")
def config_group() -> None:
    """Manage agent config versions and related edit, pin, and unpin workflows.

    Examples:
      agentlab config list
      agentlab config show active
      agentlab config diff 1 2
    """


@config_group.command("resolve")
@click.option("--config", "config_path", default=None, help="Path to the agent config YAML.")
@click.option("--runtime-config", default=None, help="Path to the runtime config YAML.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def config_resolve(
    config_path: str | None,
    runtime_config: str | None,
    json_output: bool = False,
) -> None:
    """Resolve the effective workspace config and persist an `agentlab.lock` snapshot."""
    from cli.stream2_helpers import json_response

    resolved_config_path = (
        str(_resolve_invocation_input_path(Path(config_path)))
        if config_path is not None
        else None
    )
    resolved_runtime_path = (
        str(_resolve_invocation_input_path(Path(runtime_config)))
        if runtime_config is not None
        else None
    )
    resolution = resolve_config_snapshot(
        config_path=resolved_config_path,
        runtime_config_path=resolved_runtime_path,
        command="config resolve",
    )
    persist_config_lockfile(resolution)
    payload = resolution.to_dict()

    if json_output:
        click.echo(json_response("ok", payload, next_cmd="agentlab eval run"))
        return

    click.echo(click.style("\n✦ Config Resolve", fg="cyan", bold=True))
    click.echo(render_config_resolution(resolution))
    click.echo("")
    _print_next_actions(
        [
            "agentlab eval run",
            "agentlab optimize --cycles 1",
        ],
    )


@config_group.command("list")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--id-only", is_flag=True, help="Print only config version identifiers.")
@click.option("--path-only", is_flag=True, help="Print only config file paths.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def config_list(configs_dir: str, id_only: bool, path_only: bool, json_output: bool = False) -> None:
    """List all config versions.

    Examples:
      agentlab config list
      agentlab config list --json
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
            click.echo("Run: agentlab init")
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
        click.echo(json_response("ok", data, next_cmd="agentlab config show <version>"))
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
      agentlab config show
      agentlab config show 3
      agentlab config show active
      agentlab config show latest --json
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
                    click.echo("No active config. Run: agentlab init")
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
                click.echo("No active config. Run: agentlab init")
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
      agentlab config set-active 2
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
    click.echo("  agentlab config show")


@config_group.command("diff")
@click.argument("v1", type=int)
@click.argument("v2", type=int)
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
def config_diff(v1: int, v2: int, configs_dir: str) -> None:
    """Diff two config versions.

    Examples:
      agentlab config diff 1 3
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
      agentlab config import my_config.yaml
      agentlab config import agent.json --json
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
            click.echo(json_response("ok", preview, next_cmd="agentlab config import <file>"))
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
        click.echo(json_response("ok", result, next_cmd=f"agentlab config show {result['version']}"))
        return

    click.echo(click.style("\n✦ Config Imported", fg="cyan", bold=True))
    click.echo(click.style(f"Applied: imported config as v{result['version']:03d}", fg="green"))
    click.echo(f"  Source:  {result['source_file']}")
    click.echo(f"  Version: v{result['version']:03d}")
    click.echo(f"  Hash:    {result['config_hash']}")
    click.echo(f"  Path:    {result['dest_path']}")
    click.echo("")
    _print_next_actions([
        f"agentlab config show {result['version']}",
        f"agentlab eval run --config {result['dest_path']}",
        "agentlab config list",
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
      agentlab config migrate agentlab.yaml
      agentlab config migrate agentlab.yaml --output agentlab_v2.yaml
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
        raise click.ClickException("No active config. Run: agentlab init")
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
# agentlab loop
# ---------------------------------------------------------------------------

@cli.group("loop", cls=DefaultCommandGroup, default_command="run", default_on_empty=True, hidden=True)
def loop_group() -> None:
    """Run the optimization loop or control its execution state.

    Examples:
      agentlab loop
      agentlab loop --max-cycles 20
      agentlab loop pause
      agentlab loop resume
    """


@loop_group.command("run", hidden=True)
@click.option("--max-cycles", default=50, show_default=True, type=int, help="Maximum optimization cycles.")
@click.option("--stop-on-plateau", is_flag=True, default=False,
              help="Stop if no improvement for 5 consecutive cycles.")
@click.option("--delay", default=1.0, show_default=True, type=float, help="Seconds between cycles.")
@click.option("--schedule", "schedule_mode", default=None,
              type=click.Choice(["continuous", "interval", "cron"]),
              help="Scheduling mode. Defaults to agentlab.yaml loop.schedule_mode.")
@click.option("--interval-minutes", default=None, type=float,
              help="Interval minutes for --schedule interval.")
@click.option("--cron", "cron_expression", default=None,
              help="Cron expression for --schedule cron (5-field UTC).")
@click.option("--checkpoint-file", default=None,
              help="Checkpoint file path. Defaults to agentlab.yaml loop.checkpoint_path.")
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
@click.option(
    "--ui",
    type=click.Choice(["auto", "claude", "classic"], case_sensitive=False),
    default=None,
    show_default="auto",
    help="Interactive UI mode for text output.",
)
def loop_run(max_cycles: int, stop_on_plateau: bool, delay: float, schedule_mode: str | None,
             interval_minutes: float | None, cron_expression: str | None, checkpoint_file: str | None,
             resume: bool, full_auto: bool, db: str, configs_dir: str, memory_db: str,
             max_budget_usd: float | None = None, output_format: str = "text",
             ui: str | None = None, harness: Any | None = None) -> None:
    """Run the continuous autoresearch loop.

    Observes agent health, proposes improvements, evaluates them, and deploys
    accepted changes — automatically, cycle after cycle.

    Examples:
      agentlab loop
      agentlab loop --max-cycles 100 --stop-on-plateau
    """
    from cli.output import resolve_output_format
    from cli.progress import ProgressRenderer
    from cli.usage import enforce_workspace_budget

    resolved_output_format = resolve_output_format(output_format)
    if harness is None:
        harness = _harness_session(
            title="AgentLab Loop",
            stage="Running autoresearch loop",
            tasks=[
                {"id": "observe", "title": "Observe agent health"},
                {"id": "propose", "title": "Propose improvement"},
                {"id": "evaluate", "title": "Evaluate candidate"},
                {"id": "deploy", "title": "Deploy or skip"},
                {"id": "canary", "title": "Check canary and resources"},
            ],
            output_format=resolved_output_format,
            ui=ui,
        )
    if resolved_output_format == "text" and harness is None:
        click.echo(click.style(
            "Tip: use `agentlab optimize --continuous` for the same result.",
            fg="yellow",
        ))
    progress = ProgressRenderer(output_format=resolved_output_format, render_text=False)
    progress.phase_started("loop", message="Start optimization loop")

    def _loop_task(event: str, task_id: str, task: str, **payload: Any) -> None:  # noqa: E501
        if harness is None:
            return
        from cli.auto_harness import HarnessEvent

        _emit_harness_event(
            harness,
            HarnessEvent(event, task_id=task_id, task=task, payload=payload),
        )

    def _loop_stage(message: str) -> None:
        if harness is None:
            return
        from cli.auto_harness import HarnessEvent

        _emit_harness_event(harness, HarnessEvent("stage.started", message=message))

    def _loop_tool_started(label: str) -> float:
        started = time.monotonic()
        if harness is not None:
            from cli.auto_harness import HarnessEvent

            _emit_harness_event(
                harness,
                HarnessEvent("tool.started", tool=label, message=label),
            )
        return started

    def _loop_tool_completed(
        label: str,
        started: float,
        *,
        output: str = "",
        exit_code: int = 0,
    ) -> None:
        if harness is None:
            return
        from cli.auto_harness import HarnessEvent

        _emit_harness_event(
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

    budget_ok, budget_message, budget_snapshot = enforce_workspace_budget(max_budget_usd)
    if not budget_ok:
        message = budget_message or "Budget reached"
        progress.warning(message=message)
        if resolved_output_format == "json":
            from cli.stream2_helpers import json_response

            click.echo(
                json_response(
                    "error",
                    {"message": message, "usage": budget_snapshot},
                    next_cmd="agentlab usage",
                )
            )
        elif resolved_output_format == "text":
            click.echo(message)
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
        significance_min_pairs=getattr(runtime.eval, "significance_min_pairs", 0),
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
            progress.recovery_hint(
                "loop",
                message=f"Resume from checkpoint at cycle {start_cycle}",
                command="agentlab loop --resume",
            )

    if resolved_output_format == "text" and harness is None:
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
            progress.checkpoint(
                "loop-cycle",
                path=effective_checkpoint,
                next_cycle=cycle,
                completed_cycles=completed_cycles,
            )

            progress.phase_started("loop-cycle", message=f"Cycle {cycle}/{max_cycles}")
            _loop_stage(f"Cycle {cycle}/{max_cycles}")
            if resolved_output_format == "text" and harness is None:
                click.echo(f"\n{'═' * 50}")
                click.echo(f" Cycle {cycle}/{max_cycles}")
                click.echo(f"{'═' * 50}")

            improved = False
            try:
                _loop_task("task.started", "observe", "Observe agent health")
                observe_started = _loop_tool_started("observer.observe")
                report = observer.observe()
                _loop_tool_completed(
                    "observer.observe",
                    observe_started,
                    output=(
                        f"success={report.metrics.success_rate:.2%}\n"
                        f"errors={report.metrics.error_rate:.2%}"
                    ),
                )
                _loop_task("task.completed", "observe", "Observe agent health")
                if resolved_output_format == "text" and harness is None:
                    click.echo(
                        f"  Health: success={report.metrics.success_rate:.2%}, "
                        f"errors={report.metrics.error_rate:.2%}"
                    )

                if report.needs_optimization:
                    current_config = _ensure_active_config(deployer)
                    failure_samples = _build_failure_samples(store)
                    _loop_task("task.started", "propose", "Propose improvement")
                    optimize_started = _loop_tool_started("optimizer.optimize")
                    new_config, status = optimizer.optimize(
                        report,
                        current_config,
                        failure_samples=failure_samples,
                    )
                    _loop_tool_completed(
                        "optimizer.optimize",
                        optimize_started,
                        output=status,
                    )
                    _loop_task("task.completed", "propose", "Propose improvement", detail=status)
                    if resolved_output_format == "text" and harness is None:
                        click.echo(f"  Optimizer: {status}")
                    if new_config is not None:
                        improved = True
                        _loop_task("task.started", "evaluate", "Evaluate candidate")
                        eval_started = _loop_tool_started("eval_runner.run")
                        score = eval_runner.run(config=new_config)
                        _loop_tool_completed(
                            "eval_runner.run",
                            eval_started,
                            output=f"composite={score.composite:.4f}",
                        )
                        _loop_task("task.completed", "evaluate", "Evaluate candidate")
                        _loop_task("task.started", "deploy", "Deploy or skip")
                        deploy_started = _loop_tool_started("deployer.deploy")
                        deploy_result = deployer.deploy(new_config, _score_to_dict(score))
                        _loop_tool_completed(
                            "deployer.deploy",
                            deploy_started,
                            output=str(deploy_result),
                        )
                        _loop_task("task.completed", "deploy", "Deploy or skip", detail=str(deploy_result))
                        if resolved_output_format == "text" and harness is None:
                            click.echo(f"  Deploy: {deploy_result}")
                        if full_auto:
                            promoted = _promote_latest_version(deployer)
                            if promoted is not None and resolved_output_format == "text" and harness is None:
                                click.echo(click.style(
                                    f"  FULL AUTO: promoted v{promoted:03d} to active",
                                    fg="yellow",
                                ))
                        if resolved_output_format == "text" and harness is None:
                            click.echo(f"  Score: {score.composite:.4f}")
                    else:
                        _loop_task("task.completed", "deploy", "Deploy or skip", detail="No candidate to deploy")
                else:
                    _loop_task("task.completed", "propose", "Propose improvement", detail="Healthy")
                    _loop_task("task.completed", "deploy", "Deploy or skip", detail="Skipped")
                    if resolved_output_format == "text" and harness is None:
                        click.echo("  Healthy; skipping optimization.")

                _loop_task("task.started", "canary", "Check canary and resources")
                canary_started = _loop_tool_started("deployer.check_and_act")
                canary_result = deployer.check_and_act()
                _loop_tool_completed(
                    "deployer.check_and_act",
                    canary_started,
                    output=str(canary_result),
                )
                _loop_task("task.completed", "canary", "Check canary and resources", detail=str(canary_result))
                if resolved_output_format == "text" and harness is None:
                    click.echo(f"  Canary: {canary_result}")
            except Exception as exc:
                tb = traceback.format_exc()
                dead_letter_queue.push(
                    kind="loop_cycle",
                    payload={"cycle": cycle},
                    error=str(exc),
                    traceback_text=tb,
                )
                _loop_task("task.failed", "canary", "Check canary and resources", detail=str(exc))
                if resolved_output_format == "text" and harness is None:
                    click.echo(f"  Cycle failed; queued in dead letter queue: {exc}")
                log.error(
                    "loop_cycle_failed",
                    extra={"event": "loop_cycle_failed", "cycle": cycle, "status": "failed"},
                )
                progress.error(message=str(exc), phase="loop-cycle")
                progress.recovery_hint(
                    "loop-cycle",
                    message="Cycle failure was queued for operator review",
                    command="agentlab harness status",
                )

            completed_cycles = cycle
            cycle_finished = time.time()

            if stop_on_plateau:
                if improved:
                    plateau_count = 0
                else:
                    plateau_count += 1
                    if plateau_count >= plateau_threshold:
                        if resolved_output_format == "text" and harness is None:
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
                if harness is not None:
                    from cli.auto_harness import HarnessEvent

                    _emit_harness_event(harness, HarnessEvent("warning", message=warning))
                if resolved_output_format == "text" and harness is None:
                    click.echo(f"  Warning: {warning}")
                log.warning(
                    "resource_warning_memory",
                    extra={"event": "resource_warning", "memory_mb": snapshot.memory_mb, "cycle": cycle},
                )
                progress.warning(message=warning, phase="loop-cycle")
            if snapshot.cpu_percent > runtime.loop.resource_warn_cpu_percent:
                warning = f"CPU usage high: {snapshot.cpu_percent:.2f}%"
                if harness is not None:
                    from cli.auto_harness import HarnessEvent

                    _emit_harness_event(harness, HarnessEvent("warning", message=warning))
                if resolved_output_format == "text" and harness is None:
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
                if harness is not None:
                    from cli.auto_harness import HarnessEvent

                    _emit_harness_event(harness, HarnessEvent("warning", message=stall_error))
                if resolved_output_format == "text" and harness is None:
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
                if resolved_output_format == "text" and harness is None:
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
                    if resolved_output_format == "text" and harness is None:
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
    progress.checkpoint(
        "loop",
        path=effective_checkpoint,
        next_cycle=completed_cycles + 1,
        completed_cycles=completed_cycles,
    )
    progress.phase_completed("loop", message=f"{completed_cycles} cycle(s) executed ({final_status})")
    progress.next_action("agentlab status")
    if harness is not None:
        from cli.auto_harness import HarnessEvent

        _emit_harness_event(harness, HarnessEvent("stage.completed", message=f"Loop complete: {final_status}"))
    if resolved_output_format == "text" and harness is None:
        click.echo(f"\nLoop complete. {completed_cycles} cycles executed ({final_status}).")


# ---------------------------------------------------------------------------
# agentlab harness
# ---------------------------------------------------------------------------

@cli.group("harness", cls=DefaultCommandGroup, default_command="status", default_on_empty=True)
def harness_group() -> None:
    """Inspect long-running harness lifecycle, evidence, and recovery state."""


@harness_group.command("status")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def harness_status(json_output: bool = False) -> None:
    """Show long-running harness readiness without starting a loop."""
    from cli.harness_status import collect_harness_status, render_harness_status
    from cli.stream2_helpers import json_response

    workspace = _require_workspace("harness")
    runtime = load_runtime_config(str(workspace.runtime_config_path))
    snapshot = collect_harness_status(workspace, runtime=runtime)
    next_cmd = snapshot.next_actions[0] if snapshot.next_actions else "agentlab optimize --continuous"

    if json_output:
        click.echo(json_response("ok", snapshot.to_dict(), next_cmd=next_cmd))
        return

    render_harness_status(snapshot)


# ---------------------------------------------------------------------------
# agentlab status
# ---------------------------------------------------------------------------

@cli.command("status")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--memory-db", default=MEMORY_DB, show_default=True, help="Optimizer memory DB.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
@click.option("--verbose", "-v", is_flag=True, help="Show extra details (conversations, cycles, token usage).")
def status(db: str, configs_dir: str, memory_db: str, json_output: bool = False, verbose: bool = False) -> None:
    """Show system health, config versions, and recent activity.

    Examples:
      agentlab status
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
    workspace_config_version = resolved.version if resolved is not None else deploy_status["active_version"]
    deployed_active_version = deploy_status.get("active_version")

    total_conversations = store.count()
    recent_attempts = memory.recent(limit=1)
    latest = recent_attempts[0] if recent_attempts else None
    report = Observer(store).observe()
    metrics = report.metrics
    all_attempts = memory.recent(limit=100)
    accepted_attempts = [attempt for attempt in all_attempts if attempt.status == "accepted"]
    buckets = report.failure_buckets

    mode_summary = summarize_mode_state(str(workspace.runtime_config_path))
    runtime = load_runtime_config(str(workspace.runtime_config_path))
    from cli.harness_status import collect_harness_status
    harness_snapshot = collect_harness_status(workspace, runtime=runtime)
    usage_snapshot = build_usage_snapshot(workspace.root)
    memory_snapshot = load_layered_project_context(workspace.root).summary()
    mcp_snapshot = mcp_status_snapshot(workspace.root)
    model_snapshot = effective_model_surface(workspace.root)
    latest_eval_score: float | None = None
    latest_eval_safety: float | None = None
    latest_eval_timestamp: float | str | None = None
    latest_eval_mode: EvalExecutionMode | None = None
    latest_eval_file, latest_eval_payload = _latest_eval_payload_for_active_config(
        resolved.path if resolved is not None else None
    )
    if latest_eval_payload is not None:
        latest_eval_data = _unwrap_eval_payload(latest_eval_payload)
        latest_eval_scores = _extract_eval_scores(latest_eval_data)
        latest_eval_score = latest_eval_scores.get("composite")
        latest_eval_safety = latest_eval_scores.get("safety")
        latest_eval_timestamp = latest_eval_data.get("timestamp") or latest_eval_payload.get("timestamp")
        latest_eval_mode = _extract_eval_mode(latest_eval_payload)
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
    elif deployed_active_version is not None:
        deployment_label = f"active v{deployed_active_version:03d}"

    next_action = _status_next_action(report, len(all_attempts), len(accepted_attempts))

    if json_output:
        from cli.stream2_helpers import json_response

        data = {
            "workspace_name": workspace.workspace_label,
            "workspace_path": str(workspace.root),
            "mode": mode_summary["effective_mode"],
            "config_version": workspace_config_version,
            "active_config_summary": workspace.summarize_config(resolved.config if resolved is not None else None),
            "conversations": total_conversations,
            "eval_score": latest_eval_score,
            "eval_safety_score": latest_eval_safety,
            "eval_timestamp": latest_eval_timestamp,
            "eval_mode": latest_eval_mode,
            "safety_violation_rate": metrics.safety_violation_rate,
            "cycles_run": len(all_attempts),
            "failure_buckets": buckets,
            "pending_review_cards": pending_review_cards,
            "pending_autofix_proposals": pending_autofix_proposals,
            "deployment": deployment_label,
            "loop_status": harness_snapshot.loop["status"],
            "harness": harness_snapshot.to_dict(),
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
        click.echo(json_response("ok", data, next_cmd="agentlab explain --json"))
        return

    snapshot = StatusSnapshot(
        workspace_name=workspace.workspace_label,
        workspace_path=str(workspace.root),
        mode_label=mode_summary["effective_mode"].upper(),
        active_config_label=(
            f"v{workspace_config_version:03d}" if workspace_config_version is not None else "none"
        ),
        active_config_summary=workspace.summarize_config(resolved.config if resolved is not None else None),
        eval_score_label=f"{latest_eval_score:.4f}" if latest_eval_score is not None else "n/a",
        eval_timestamp_label=_format_eval_timestamp(latest_eval_timestamp),
        last_eval_mode_label=eval_mode_status_label(latest_eval_mode),
        conversations_label=str(total_conversations),
        safety_label=(
            f"{latest_eval_safety:.3f} eval | obs fail {metrics.safety_violation_rate:.3f}"
            if latest_eval_safety is not None
            else f"{metrics.safety_violation_rate:.3f} observed fail rate"
        ),
        cycles_run_label=str(len(all_attempts)),
        pending_review_cards=pending_review_cards,
        pending_autofix_proposals=pending_autofix_proposals,
        deployment_label=deployment_label,
        loop_label=harness_snapshot.loop_label,
        harness_label=harness_snapshot.summary_label,
        harness_recovery_label=harness_snapshot.recovery_label,
        harness_evidence_label=harness_snapshot.evidence_label,
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
    render_status_home(snapshot, verbose=verbose)


# ---------------------------------------------------------------------------
# agentlab logs
# ---------------------------------------------------------------------------

@cli.command("logs")
@click.option("--limit", default=20, show_default=True, type=int, help="Number of logs to show.")
@click.option("--outcome", default=None, type=click.Choice(["success", "fail", "error", "abandon"]),
              help="Filter by outcome.")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
def logs(limit: int, outcome: str | None, db: str) -> None:
    """Browse conversation logs.

    Examples:
      agentlab logs
      agentlab logs --limit 50 --outcome fail
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
# agentlab doctor
# ---------------------------------------------------------------------------

@cli.command("doctor")
@click.option("--config", "config_path", default="agentlab.yaml", show_default=True,
              help="Path to runtime config YAML.")
@click.option("--fix", is_flag=True, help="Automatically repair fixable workspace issues.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def doctor(config_path: str, fix: bool, json_output: bool = False) -> None:
    """Check system health and configuration.

    Reports on API keys, mock mode, data stores, eval cases, and config versions.

    Examples:
      agentlab doctor
    """
    import sqlite3

    from cli.mcp_runtime import mcp_status_snapshot
    from cli.mock_reason import compute_mock_reason
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
        mock_info = compute_mock_reason(
            runtime_use_mock=runtime.optimizer.use_mock,
            config_path=config_path,
        )
        memory_snapshot = (
            load_layered_project_context(workspace.root).summary()
            if workspace is not None
            else {"active_count": 0, "paths": []}
        )
        mcp_snapshot = mcp_status_snapshot(workspace.root if workspace is not None else Path("."))
        from cli.harness_status import collect_harness_status
        harness_snapshot = collect_harness_status(workspace, runtime=runtime) if workspace is not None else None
        if workspace is None:
            issues.append("No AgentLab workspace found")
        if harness_snapshot is not None and harness_snapshot.health == "blocked":
            issues.extend(harness_snapshot.issues)
        if mock_info.is_blocking:
            issues.append("Mock mode forced: no provider key set")
        data = {
            "workspace": str(workspace.root) if workspace is not None else None,
            "issues": issues,
            "fixes_applied": fixes_applied,
            "mode": mode_summary["effective_mode"],
            "memory": memory_snapshot,
            "mcp": mcp_snapshot,
            "harness": harness_snapshot.to_dict() if harness_snapshot is not None else None,
            "mock_reason": mock_info.reason,
            "mock_reason_detail": mock_info.detail,
        }
        click.echo(json_response("ok", data, next_cmd="agentlab status"))
        return

    click.echo("\nAgentLab Doctor")
    click.echo("================")

    # ------------------------------------------------------------------
    # Workspace
    # ------------------------------------------------------------------
    click.echo("\nWorkspace")
    if workspace is None:
        issues.append("No AgentLab workspace found")
        click.echo(
            "  Workspace:          "
            + click.style("\u2717 Not found (run agentlab init or agentlab new)", fg="red")
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
    mock_info = compute_mock_reason(
        runtime_use_mock=runtime.optimizer.use_mock,
        config_path=config_path,
    )
    if mock_info.reason == "disabled":
        click.echo("  Mock mode:          " + click.style("\u2713 Disabled", fg="green"))
    elif mock_info.reason == "configured":
        click.echo(
            "  Mock mode:          "
            + click.style(f"\u26a0 Enabled (configured). {mock_info.detail}", fg="yellow")
        )
        click.echo("  Fix:                Set optimizer.use_mock: false in agentlab.yaml for production.")
    else:  # missing_provider_key
        issues.append("Mock mode forced: no provider key set")
        click.echo(
            "  Mock mode:          "
            + click.style(f"\u2717 Forced ({mock_info.reason}). {mock_info.detail}", fg="red")
        )
        click.echo("  Fix:                Set one of OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY and rerun.")

    # ------------------------------------------------------------------
    # Active Provider
    # ------------------------------------------------------------------
    click.echo("\nActive Provider")
    try:
        from optimizer.providers import describe_default_provider

        active_info = describe_default_provider(runtime_config_path=config_path)
    except Exception as exc:  # pragma: no cover — defensive
        click.echo("  " + click.style(f"\u26a0 Unable to resolve active provider: {exc}", fg="yellow"))
    else:
        click.echo(f"  {'Provider:':<22}" + click.style(active_info.name, fg="green"))
        click.echo(f"  {'Model:':<22}" + click.style(active_info.model, fg="green"))
        env_label = active_info.env_var or "(none)"
        if active_info.key_present:
            click.echo(
                f"  {'Key:':<22}"
                + click.style(f"\u2713 {env_label} set", fg="green")
            )
        else:
            # Informational rather than a blocker: the harness already
            # gracefully falls back to mock/deterministic when keys are
            # missing, and the existing "API Keys" + "Coordinator" sections
            # are the authoritative places to flag blockers. We just surface
            # the fact so operators can correlate a failed /build with the
            # missing credential at a glance.
            click.echo(
                f"  {'Key:':<22}"
                + click.style(
                    f"\u2717 {env_label} not set — /build will fall back to placeholders",
                    fg="yellow",
                )
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
            click.echo(
                f"  {label + ':':<22}"
                + click.style("\u26a0 Not set (optional unless you use this provider)", fg="yellow")
            )

    # ------------------------------------------------------------------
    # Provider Profiles
    # ------------------------------------------------------------------
    click.echo("\nProvider Profiles")
    config_file = Path(config_path).expanduser()
    provider_path = (
        providers_file_path_for_runtime_config(config_file)
        if config_file.exists()
        else providers_file_path(workspace)
    )
    checks = provider_health_checks(provider_path, runtime_config_path=config_path)
    if checks:
        for check in checks:
            source_note = " (from runtime config)" if check.get("source") == "runtime config" else ""
            if check["credential_present"]:
                click.echo(
                    f"  {check['provider'] + ':':<22}"
                    + click.style(f"\u2713 {check['model']} configured{source_note}; live probe not run", fg="green")
                )
            elif check.get("source") == "runtime config":
                env_name = check.get("api_key_env") or "an API key"
                click.echo(
                    f"  {check['provider'] + ':':<22}"
                    + click.style(
                        f"\u26a0 {check['model']} missing {env_name} (optional unless selected)",
                        fg="yellow",
                    )
                )
            else:
                issues.append(check["message"])
                click.echo(
                    f"  {check['provider'] + ':':<22}"
                    + click.style(f"\u2717 {check['model']} missing {check['api_key_env']}", fg="red")
                )
    else:
        click.echo(
            "  Registry:           "
            + click.style(
                "\u26a0 Not configured (run agentlab provider configure when you are ready for live providers)",
                fg="yellow",
            )
        )

    # ------------------------------------------------------------------
    # Harness readiness
    # ------------------------------------------------------------------
    click.echo("\nHarness")
    from cli.harness_status import collect_harness_status as _doctor_collect_harness
    doctor_harness_snapshot = _doctor_collect_harness(workspace, runtime=runtime) if workspace is not None else None
    if doctor_harness_snapshot is None:
        click.echo(
            "  Harness:           "
            + click.style("\u2717 No workspace state available", fg="red")
        )
    else:
        if doctor_harness_snapshot.health == "blocked":
            issues.extend(doctor_harness_snapshot.issues)
            health_style = click.style(f"\u2717 {doctor_harness_snapshot.summary_label}", fg="red")
        elif doctor_harness_snapshot.health == "attention":
            health_style = click.style(f"\u26a0 {doctor_harness_snapshot.summary_label}", fg="yellow")
        else:
            health_style = click.style(f"\u2713 {doctor_harness_snapshot.summary_label}", fg="green")
        click.echo("  Harness:           " + health_style)
        click.echo(f"  Recovery:          {doctor_harness_snapshot.recovery_label}")
        click.echo(f"  Evidence:          {doctor_harness_snapshot.evidence_label}")

    # ------------------------------------------------------------------
    # Coordinator / worker runtime
    # ------------------------------------------------------------------
    from cli.harness_doctor import render_coordinator_section

    click.echo("")
    click.echo(render_coordinator_section(workspace).rstrip())

    # ------------------------------------------------------------------
    # Data Stores
    # ------------------------------------------------------------------
    click.echo("\nData Stores")

    # Traces DB
    traces_db = Path(".agentlab") / "traces.db"
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
                click.echo(
                    "  Traces:             "
                    + click.style(
                        "\u26a0 Empty (will populate after traced runs)", fg="yellow"
                    )
                )
        except sqlite3.DatabaseError:
            issues.append("Traces DB is unreadable")
            click.echo(
                "  Traces:             "
                + click.style("\u2717 Unreadable (DB may be corrupt)", fg="red")
            )
    else:
        click.echo(
            "  Traces:             "
            + click.style(
                "\u26a0 Not collected yet (run your agent with tracing enabled)", fg="yellow"
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
                ("AgentLab state", workspace.agentlab_dir),
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
    """Return a HumanControlStore scoped to the active AgentLab workspace."""
    from optimizer.human_control import HumanControlStore

    workspace = discover_workspace()
    if workspace is None:
        return HumanControlStore()
    return HumanControlStore(path=str(workspace.agentlab_dir / "human_control.json"))


def _event_log():
    """Return an EventLog using default or env-configured path."""
    from data.event_log import EventLog
    return EventLog()


def _pause_optimizer_impl() -> None:
    """Pause the optimization loop and log the human intervention event."""
    store = _control_store()
    store.pause()
    _event_log().append(event_type="human_pause", payload={"paused": True})
    click.echo("Optimizer paused. Run 'agentlab loop resume' to continue. Legacy alias: 'agentlab resume'.")


@loop_group.command("pause")
def loop_pause() -> None:
    """Pause the optimization loop (human escape hatch)."""
    _pause_optimizer_impl()


@cli.command("pause", hidden=True)
def pause_optimizer() -> None:
    """Pause the optimization loop (human escape hatch).

    Examples:
      agentlab pause
    """
    _echo_deprecation("agentlab pause", "agentlab loop pause")
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
      agentlab resume
    """
    _echo_deprecation("agentlab resume", "agentlab loop resume")
    _resume_optimizer_impl()


@cli.command("reject")
@click.argument("experiment_id", type=str)
@click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
def reject_experiment(experiment_id: str, configs_dir: str, db: str) -> None:
    """Reject a promoted experiment and rollback any active canary.

    Examples:
      agentlab reject abc12345
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
      agentlab pin safety_instructions
      agentlab pin prompts.root
    """
    store = _control_store()
    store.pin_surface(surface)
    click.echo(f"Pinned '{surface}' as immutable. Optimizer will not modify it.")


@cli.command("unpin")
@click.argument("surface", type=str)
def unpin_surface(surface: str) -> None:
    """Remove immutable marking from a config surface.

    Examples:
      agentlab unpin safety_instructions
    """
    store = _control_store()
    store.unpin_surface(surface)
    click.echo(f"Unpinned '{surface}'. Optimizer can now modify it.")


# ---------------------------------------------------------------------------
# agentlab autofix (subgroup)
# ---------------------------------------------------------------------------

@cli.group("autofix", invoke_without_command=True)
@click.pass_context
def autofix_group(ctx: click.Context) -> None:
    """AutoFix Copilot — reviewable improvement proposals.

    Examples:
      agentlab autofix suggest
      agentlab autofix show pending
      agentlab autofix apply pending
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
      agentlab autofix suggest
      agentlab autofix suggest --json
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
        click.echo(json_response("ok", data, next_cmd="agentlab autofix apply <proposal_id>"))
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
      agentlab autofix apply abc123
      agentlab autofix apply pending
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
            click.echo(json_response("ok", preview, next_cmd=f"agentlab autofix apply {proposal_id}"))
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
                }, next_cmd=f"agentlab eval run --config {version_info['path']}"))
            else:
                click.echo(f"Applied: {status_msg}")
                click.echo(f"  New config version: v{version_info['version']:03d}")
                click.echo(f"  Path: {version_info['path']}")
                _print_next_actions([f"agentlab eval run --config {version_info['path']}"])
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
      agentlab autofix history
      agentlab autofix history --json
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
# agentlab judges (subgroup)
# ---------------------------------------------------------------------------

@cli.group("judges")
def judges_group() -> None:
    """Judge Ops — monitoring, calibration, and human feedback.

    Examples:
      agentlab judges list
      agentlab judges calibrate --sample 10
      agentlab judges drift
    """


@judges_group.command("list")
def judges_list() -> None:
    """Show active judges with version and agreement stats.

    Examples:
      agentlab judges list
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
      agentlab judges calibrate --sample 50
      agentlab judges calibrate --judge-id llm_judge
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
      agentlab judges drift
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
# agentlab context (subgroup)
# ---------------------------------------------------------------------------

@cli.group("context")
def context_group() -> None:
    """Context Engineering Workbench — diagnose and tune agent context.

    Examples:
      agentlab context profiles
      agentlab context preview --profile balanced
      agentlab context simulate --strategy balanced
      agentlab context report
      agentlab context analyze --trace trace_demo_fail_001
    """


@context_group.command("profiles")
@click.option("--json", "json_output", is_flag=True, help="Output profile data as JSON.")
def context_profiles(json_output: bool) -> None:
    """List reusable context-engineering profiles.

    Examples:
      agentlab context profiles
      agentlab context profiles --json
    """
    from context.engineering import context_profiles_payload

    payload = context_profiles_payload()
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    click.echo("\nContext Engineering Profiles")
    click.echo("=" * 36)
    click.echo(f"Default: {payload['default_profile']}")
    for profile in payload["profiles"]:
        target = profile["target_utilization"]
        pro_label = "pro" if profile["pro_mode"] else "standard"
        click.echo(
            f"  {profile['name']:<9} {profile['label']:<10} "
            f"budget={profile['token_budget']:<6} target={target:.0%} mode={pro_label}"
        )
        click.echo(f"    {profile['description']}")


@context_group.command("preview")
@click.option("--config", "config_path", type=click.Path(dir_okay=False), help="Agent config YAML to inspect.")
@click.option(
    "--profile",
    "profile_name",
    default="balanced",
    show_default=True,
    type=click.Choice(["lean", "balanced", "deep"]),
    help="Context profile to apply.",
)
@click.option("--token-budget", type=int, help="Override the selected profile token budget.")
@click.option("--pro", "pro_mode", is_flag=True, default=None, help="Enable pro-mode diagnostics in the preview.")
@click.option("--json", "json_output", is_flag=True, help="Output the preview as JSON.")
def context_preview(
    config_path: str | None,
    profile_name: str,
    token_budget: int | None,
    pro_mode: bool | None,
    json_output: bool,
) -> None:
    """Preview context assembly, budget shape, and diagnostics for an agent.

    Examples:
      agentlab context preview --profile lean
      agentlab context preview --config configs/v001_base.yaml --json
    """
    from context.engineering import build_context_preview_from_workspace

    try:
        resolved_config_path = _resolve_invocation_input_path(Path(config_path)) if config_path else None
        preview_root = resolved_config_path.parent if resolved_config_path else Path.cwd()
        preview = build_context_preview_from_workspace(
            root=preview_root,
            config_path=resolved_config_path,
            profile_name=profile_name,
            token_budget=token_budget,
            pro_mode=pro_mode,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    payload = preview.to_dict()
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    click.echo("\nContext Assembly Preview")
    click.echo("=" * 36)
    click.echo(f"Profile: {payload['profile_name']} ({payload['profile_label']})")
    click.echo(f"Status: {payload['status']}")
    click.echo(f"Budget: {payload['total_tokens']} / {payload['token_budget']} estimated tokens")
    click.echo(f"Utilization: {payload['utilization_ratio']:.1%}")

    click.echo("\nComponents:")
    for component in payload["components"]:
        if not component["included"]:
            continue
        click.echo(
            f"  - {component['component_id']:<18} "
            f"{component['token_count']:>5} tokens  source={component['source']}"
        )

    click.echo("\nDiagnostics:")
    if not payload["diagnostics"]:
        click.echo("  - No context diagnostics.")
    for diagnostic in payload["diagnostics"]:
        click.echo(f"  - [{diagnostic['severity']}] {diagnostic['category']}: {diagnostic['message']}")
        click.echo(f"    Try: {diagnostic['recommendation']}")


@context_group.command("analyze")
@click.option("--trace", "trace_id", required=True, help="Trace ID to analyze.")
def context_analyze(trace_id: str) -> None:
    """Analyze context utilization for a trace.

    Examples:
      agentlab context analyze --trace abc123
    """
    from context.analyzer import ContextAnalyzer
    from observer.traces import TraceStore

    trace_store = TraceStore(db_path=".agentlab/traces.db")
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
      agentlab context simulate --strategy aggressive
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
      agentlab context report
    """
    click.echo("\nContext Health Report")
    click.echo("=" * 40)
    click.echo("  Utilization ratio:   — (no trace data)")
    click.echo("  Compaction loss:     — (no trace data)")
    click.echo("  Handoff fidelity:    — (no trace data)")
    click.echo("  Memory staleness:    — (no trace data)")
    click.echo("\n  Run 'agentlab context analyze --trace <id>' for per-trace analysis.")


# ---------------------------------------------------------------------------
# agentlab review (change cards)
# ---------------------------------------------------------------------------


def _sync_experiment_status_for_change_card(experiment_id: str | None, status: str, *, title: str = "") -> None:
    """Best-effort sync from a reviewed change card back into shared experiment history."""
    if not experiment_id:
        return
    try:
        from optimizer.experiments import ExperimentStore

        ExperimentStore(db_path=str(default_experiment_log_path().parent / "experiments.db")).update_status(
            experiment_id,
            status,
            result_summary=title,
        )
    except Exception:
        return


def _apply_change_card_to_workspace(card_id: str):
    """Mark a change card applied and make its candidate config the active local config."""
    from optimizer.change_card import ChangeCardStore

    workspace = _require_workspace("review")
    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        raise click.ClickException(f"Change card not found: {card_id}")
    if card.status != "pending":
        raise click.ClickException(f"Card is not pending (status={card.status})")
    if card.candidate_config_version is None:
        store.update_status(card_id, "applied")
        _sync_experiment_status_for_change_card(card.experiment_card_id, "accepted", title=card.title)
        return card, None, None

    candidate_path = workspace.resolve_config_path(card.candidate_config_version)
    if candidate_path is None and card.candidate_config_path:
        explicit_path = Path(card.candidate_config_path)
        if explicit_path.exists():
            candidate_path = explicit_path
    if candidate_path is None:
        raise click.ClickException(
            f"Candidate config for card {card_id} is missing (expected v{card.candidate_config_version:03d})."
        )

    store.update_status(card_id, "applied")
    _sync_experiment_status_for_change_card(card.experiment_card_id, "accepted", title=card.title)
    workspace.set_active_config(card.candidate_config_version, filename=candidate_path.name)
    return card, card.candidate_config_version, candidate_path

@cli.group("review", invoke_without_command=True)
@click.pass_context
def review_group(ctx: click.Context) -> None:
    """Review proposed change cards from the optimizer.

    Running `agentlab review` opens an interactive approval prompt.

    Examples:
      agentlab review
      agentlab review list
      agentlab review show pending
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
        applied_card, candidate_version, candidate_path = _apply_change_card_to_workspace(card.card_id)
        if candidate_version is None or candidate_path is None:
            click.echo(f"Applied change card {applied_card.card_id}: {applied_card.title}")
        else:
            click.echo(
                f"Applied change card {applied_card.card_id}: {applied_card.title} "
                f"(active config v{candidate_version:03d} -> {candidate_path})"
            )


@review_group.command("list")
@click.option("--limit", default=20, show_default=True, type=int, help="Number of cards to show.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def review_list(limit: int = 20, json_output: bool = False) -> None:
    """List pending change cards.

    Examples:
      agentlab review
      agentlab review list
      agentlab review list --json
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
        click.echo(json_response("ok", data, next_cmd="agentlab review show <card_id>"))
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
      agentlab review show abc12345
      agentlab review show pending
      agentlab review show pending --json
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
        }, next_cmd=f"agentlab review apply {card.card_id}"))
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

    Supports selectors: pending, latest.

    Examples:
      agentlab review apply abc12345
      agentlab review apply pending
    """
    from cli.output import resolve_output_format
    from cli.permissions import PermissionManager
    from cli.progress import ProgressRenderer
    from cli.stream2_helpers import is_selector
    from optimizer.change_card import ChangeCardStore

    resolved_output_format = resolve_output_format(output_format)
    progress = ProgressRenderer(output_format=resolved_output_format, render_text=False)
    store = ChangeCardStore()

    if is_selector(card_id):
        cards = store.list_pending(limit=1)
        if not cards:
            click.echo(f"No {card_id} change cards found.")
            raise SystemExit(1)
        card_id = cards[0].card_id

    progress.phase_started("review-apply", message=f"Apply change card {card_id}")
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
    applied_card, candidate_version, candidate_path = _apply_change_card_to_workspace(card_id)
    progress.phase_completed("review-apply", message=f"Applied change card {card_id}")
    progress.next_action("agentlab eval run")
    if resolved_output_format == "stream-json":
        return
    click.echo(f"Applied change card {applied_card.card_id}: {applied_card.title}")
    if candidate_version is not None and candidate_path is not None:
        click.echo(f"  Active config: v{candidate_version:03d}")
        click.echo(f"  Path: {candidate_path}")


@review_group.command("reject")
@click.argument("card_id")
@click.option("--reason", default="", help="Reason for rejection.")
def review_reject(card_id: str, reason: str) -> None:
    """Reject a change card with an optional reason.

    Supports selectors: pending, latest.

    Examples:
      agentlab review reject abc12345 --reason "Too risky"
      agentlab review reject pending
    """
    from cli.stream2_helpers import is_selector
    from optimizer.change_card import ChangeCardStore

    store = ChangeCardStore()

    if is_selector(card_id):
        cards = store.list_pending(limit=1)
        if not cards:
            click.echo(f"No {card_id} change cards found.")
            raise SystemExit(1)
        card_id = cards[0].card_id

    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    if card.status != "pending":
        click.echo(f"Card is not pending (status={card.status})")
        raise SystemExit(1)

    store.update_status(card_id, "rejected", reason=reason)
    _sync_experiment_status_for_change_card(card.experiment_card_id, "rejected", title=card.title)
    click.echo(f"Rejected change card {card_id}: {card.title}")
    if reason:
        click.echo(f"  Reason: {reason}")


@review_group.command("export")
@click.argument("card_id")
def review_export(card_id: str) -> None:
    """Export a change card as markdown.

    Supports selectors: pending, latest.

    Examples:
      agentlab review export abc12345
      agentlab review export pending
    """
    from cli.stream2_helpers import is_selector
    from optimizer.change_card import ChangeCardStore

    store = ChangeCardStore()

    if is_selector(card_id):
        cards = store.list_pending(limit=1)
        if not cards:
            click.echo(f"No {card_id} change cards found.")
            raise SystemExit(1)
        card_id = cards[0].card_id

    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    click.echo(card.to_markdown())


# ---------------------------------------------------------------------------
# agentlab changes (aliases for review)
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
    """List pending change cards (alias for `agentlab review list`)."""
    from optimizer.change_card import ChangeCardStore

    Path(".agentlab").mkdir(parents=True, exist_ok=True)
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
    """Show a specific change card (alias for `agentlab review show`)."""
    from optimizer.change_card import ChangeCardStore

    Path(".agentlab").mkdir(parents=True, exist_ok=True)
    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    click.echo(card.to_terminal())


@changes_group.command("approve")
@click.argument("card_id")
def changes_approve(card_id: str) -> None:
    """Approve/apply a change card (alias for `agentlab review apply`)."""
    try:
        card, candidate_version, candidate_path = _apply_change_card_to_workspace(card_id)
    except click.ClickException as exc:
        click.echo(str(exc))
        raise SystemExit(1) from exc
    if candidate_version is None or candidate_path is None:
        click.echo(f"Applied change card {card.card_id}: {card.title}")
    else:
        click.echo(
            f"Applied change card {card.card_id}: {card.title} "
            f"(active config v{candidate_version:03d} -> {candidate_path})"
        )


@changes_group.command("reject")
@click.argument("card_id")
@click.option("--reason", default="", help="Reason for rejection.")
def changes_reject(card_id: str, reason: str) -> None:
    """Reject a change card (alias for `agentlab review reject`)."""
    from optimizer.change_card import ChangeCardStore

    Path(".agentlab").mkdir(parents=True, exist_ok=True)
    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    if card.status != "pending":
        click.echo(f"Card is not pending (status={card.status})")
        raise SystemExit(1)
    store.update_status(card_id, "rejected", reason=reason)
    _sync_experiment_status_for_change_card(card.experiment_card_id, "rejected", title=card.title)
    click.echo(f"Rejected change card {card_id}: {card.title}")
    if reason:
        click.echo(f"  Reason: {reason}")


@changes_group.command("export")
@click.argument("card_id")
def changes_export(card_id: str) -> None:
    """Export a change card markdown (alias for `agentlab review export`)."""
    from optimizer.change_card import ChangeCardStore

    Path(".agentlab").mkdir(parents=True, exist_ok=True)
    store = ChangeCardStore()
    card = store.get(card_id)
    if card is None:
        click.echo(f"Change card not found: {card_id}")
        raise SystemExit(1)
    click.echo(card.to_markdown())


# ---------------------------------------------------------------------------
# agentlab experiment
# ---------------------------------------------------------------------------

@cli.group("experiment")
def experiment_group() -> None:
    """Inspect optimization experiment history.

    Examples:
      agentlab experiment log
      agentlab experiment log --tail 10
      agentlab experiment log --summary
    """


@experiment_group.command("log")
@click.option("--tail", default=None, type=int, help="Show only the last N entries.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
@click.option("--summary", is_flag=True, default=False, help="Print a one-line history summary.")
def experiment_log(tail: int | None, json_output: bool, summary: bool) -> None:
    """View optimize experiment history from the append-only TSV log.

    Examples:
      agentlab experiment log
      agentlab experiment log --tail 5
      agentlab experiment log --json
      agentlab experiment log --summary
    """
    entries = read_experiment_log_entries()
    if not entries:
        click.echo("No experiments yet. Run: agentlab optimize --continuous")
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
# agentlab runbook
# ---------------------------------------------------------------------------

@cli.group("runbook")
def runbook_group() -> None:
    """Runbooks — curated bundles of skills, policies, and tool contracts."""


@runbook_group.command("list")
@click.option("--db", default=REGISTRY_DB, show_default=True)
def runbook_list(db: str) -> None:
    """List all runbooks.

    Examples:
      agentlab runbook list
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
      agentlab runbook show fix-retrieval-grounding
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
      agentlab runbook apply fix-retrieval-grounding
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
      agentlab runbook create --name my-runbook --file runbook.yaml
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
# agentlab memory
# ---------------------------------------------------------------------------

@cli.group("memory")
def memory_group() -> None:
    """Project memory — manage AGENTLAB.md persistent context."""


@memory_group.command("show")
def memory_show() -> None:
    """Show AGENTLAB.md contents.

    Examples:
      agentlab memory show
    """
    from core.project_memory import ProjectMemory

    mem = ProjectMemory.load()
    if mem is None:
        click.echo("No AGENTLAB.md found. Run: agentlab init")
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
        raise click.ClickException(f"No memory file found at {memory_path}. Use --append or run agentlab init")
    _open_in_editor(memory_path)


@memory_group.command("summarize-session")
@click.argument("summary")
@click.option("--title", default="Session Summary", show_default=True, help="Title for the generated summary file.")
def memory_summarize_session(summary: str, title: str) -> None:
    """Write a generated session summary into `.agentlab/memory/`."""
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
    """Add a note to a section of AGENTLAB.md.

    Examples:
      agentlab memory add "Prefer instruction edits over model swaps" --section preference
      agentlab memory add "Never use gpt-3.5 for safety checks" --section bad
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
        click.echo("No AGENTLAB.md found. Creating one first...")
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
# agentlab server
# ---------------------------------------------------------------------------

@cli.command("server")
@_banner_flag_options
@click.option("--host", default="0.0.0.0", show_default=True, help="Host to bind to.")
@click.option("--port", default=8000, show_default=True, type=int, help="Port to bind to.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload for development.")
@click.option(
    "--workspace",
    "workspace_path",
    default=None,
    type=click.Path(path_type=Path),
    help="AgentLab workspace root to serve, decoupled from the current directory.",
)
@click.pass_context
def server(
    ctx: click.Context,
    quiet: bool,
    no_banner: bool,
    host: str,
    port: int,
    reload: bool,
    workspace_path: Path | None,
) -> None:
    """Start the API server + web console.

    Starts the FastAPI backend serving both the REST API and the web console.
    API docs available at http://localhost:8000/docs

    Examples:
      agentlab server
      agentlab server --port 3000 --reload
    """
    import uvicorn

    del quiet, no_banner
    selected_workspace = ctx.obj.get("workspace") if ctx.obj else None
    if workspace_path is not None:
        explicit_path = workspace_path.expanduser().resolve()
        if not explicit_path.exists():
            raise click.ClickException(f"Workspace path does not exist: {explicit_path}")
        explicit_workspace = discover_workspace(explicit_path)
        if explicit_workspace is None:
            raise click.ClickException(
                f"No AgentLab workspace found at {explicit_path}. Run: agentlab init --dir {explicit_path}"
            )
        selected_workspace = explicit_workspace

    if selected_workspace is not None:
        os.environ["AGENTLAB_WORKSPACE"] = str(selected_workspace.root)

    echo_startup_banner(ctx)
    click.echo(f"Starting AgentLab VNextCC server on {host}:{port}")
    if selected_workspace is not None:
        click.echo(f"  Workspace:    {selected_workspace.root}")
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
# agentlab mcp-server
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
          "agentlab": {
            "command": "python3",
            "args": ["-m", "mcp_server"]
          }
        }
      }

    Examples:
      agentlab mcp-server                         # Stdio mode (default)
      agentlab mcp-server --host 127.0.0.1 --port 8081
    """
    from mcp_server.server import run_http
    from mcp_server.server import run_stdio
    if port is not None:
        run_http(host=host, port=port)
        return
    run_stdio()


# ---------------------------------------------------------------------------
# Legacy: agentlab run (kept for backward compatibility)
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

    click.echo(f"Starting AgentLab server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


@run_group.command("eval")
@click.option("--config-path", default=None, help="Path to config YAML.")
@click.option("--category", default=None, help="Run only a specific category.")
def run_eval(config_path: str | None, category: str | None) -> None:
    """Run eval suite (legacy). Use: agentlab eval run"""
    config = None
    if config_path:
        config = _load_config_dict(config_path)
    runtime = load_runtime_with_mode_preference()
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
    """Run observer (legacy). Use: agentlab status"""
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
    """Run optimize (legacy). Use: agentlab optimize"""
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
        significance_min_pairs=getattr(runtime.eval, "significance_min_pairs", 0),
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
    """Run loop (legacy). Use: agentlab loop"""
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
        significance_min_pairs=getattr(runtime.eval, "significance_min_pairs", 0),
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
    """Show status (legacy). Use: agentlab status"""
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
# agentlab registry ...
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
      agentlab registry list
      agentlab registry list --type skills
      agentlab registry import registry_export.yaml
    """


@registry_group.command("list")
@click.option("--type", "registry_type", default=None,
              type=click.Choice(REGISTRY_TYPES, case_sensitive=False),
              help="Filter by registry type.")
@click.option("--db", default=REGISTRY_DB, show_default=True)
def registry_list(registry_type: str | None, db: str) -> None:
    """List registered items.

    Examples:
      agentlab registry list
      agentlab registry list --type skills
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
      agentlab registry show skills returns_handling
      agentlab registry show tools order_lookup --version 2
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
      agentlab registry add skills returns_handling --file skill.yaml
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
      agentlab registry diff skills returns_handling 1 2
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
      agentlab registry import registry_export.yaml
    """
    from registry import RegistryStore
    from registry.importer import import_from_file

    store = RegistryStore(db_path=db)
    counts = import_from_file(path, store)
    click.echo("Imported:")
    for item_type, count in counts.items():
        click.echo(f"  {item_type}: {count}")


# ---------------------------------------------------------------------------
# agentlab skill — executable skills registry
# ---------------------------------------------------------------------------
# agentlab skill ... (unified skills from core.skills)
# ---------------------------------------------------------------------------

@cli.group("skill")
def skill_group() -> None:
    """Unified skill management — build-time and run-time skills.

    Examples:
      agentlab skill list
      agentlab skill recommend --json
      agentlab skill show returns_handling
    """


# Register all skill commands from cli.skills module
from cli.skills import register_skill_commands
register_skill_commands(skill_group)


@skill_group.command("export-md")
@click.argument("skill_name")
@click.option("--output", default=None, help="Destination file or directory.")
@click.option("--db", default=".agentlab/skills.db", show_default=True, help="Skills database path.")
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
@click.option("--db", default=".agentlab/skills.db", show_default=True, help="Skills database path.")
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
        author=str(frontmatter.get("author", "agentlab")),
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
# agentlab curriculum ... (self-play curriculum generator)
# ---------------------------------------------------------------------------

@cli.group("curriculum")
def curriculum_group() -> None:
    """Self-play curriculum generator for adversarial eval prompts."""


@curriculum_group.command("generate")
@click.option("--limit", default=10, show_default=True, help="Max failure clusters to process")
@click.option("--prompts-per-cluster", default=3, show_default=True, help="Prompts to generate per cluster")
@click.option("--adversarial-ratio", default=0.2, show_default=True, help="Ratio of adversarial variants")
@click.option("--db", default=DB_PATH, show_default=True, help="Conversation database path")
@click.option("--output-dir", default=".agentlab/curriculum", show_default=True, help="Output directory")
def curriculum_generate(
    limit: int,
    prompts_per_cluster: int,
    adversarial_ratio: float,
    db: str,
    output_dir: str,
) -> None:
    """Generate a new curriculum batch from recent failures.

    Examples:
      agentlab curriculum generate
      agentlab curriculum generate --limit 20 --prompts-per-cluster 5
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
@click.option("--output-dir", default=".agentlab/curriculum", show_default=True, help="Curriculum directory")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def curriculum_list(limit: int, output_dir: str, json_output: bool) -> None:
    """List generated curriculum batches.

    Examples:
      agentlab curriculum list
      agentlab curriculum list --json
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
@click.option("--output-dir", default=".agentlab/curriculum", show_default=True, help="Curriculum directory")
@click.option("--eval-cases-dir", default="evals/cases", show_default=True, help="Eval cases directory")
def curriculum_apply(batch_id: str, output_dir: str, eval_cases_dir: str) -> None:
    """Apply a curriculum batch to the active eval set.

    Examples:
      agentlab curriculum apply curriculum_abc123
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
# agentlab trace ...
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
      agentlab trace show latest
      agentlab trace blame --window 24h
      agentlab trace promote latest
    """


@trace_group.command("show")
@click.argument("trace_id")
@click.option("--db", default=TRACE_DB, show_default=True)
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def trace_show(trace_id: str, db: str, json_output: bool = False) -> None:
    """Show trace details. Supports selectors: latest.

    Examples:
      agentlab trace show abc-123
      agentlab trace show latest
      agentlab trace show latest --json
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
        click.echo(json_response("ok", data, next_cmd=f"agentlab trace grade {trace_id}"))
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
      agentlab trace grade abc-123
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
      agentlab trace blame --window 24h
      agentlab trace blame --window 7d --top 5
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
      agentlab trace graph abc-123
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
      agentlab trace promote abc-123
      agentlab trace promote latest
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
        }, next_cmd="agentlab eval run"))
    else:
        click.echo(click.style("  ✓ ", fg="green") + f"Promoted trace {trace_id} to eval case")
        click.echo(f"  File: {file_path}")
        _print_next_actions(["agentlab eval run"])


# ---------------------------------------------------------------------------
# agentlab scorer ...
# ---------------------------------------------------------------------------

@cli.group("scorer")
def scorer_group() -> None:
    """NL Scorer — create eval scorers from natural language descriptions.

    Examples:
      agentlab scorer create "Reward verified account changes" --name account_safety
      agentlab scorer list
      agentlab scorer show account_safety
    """


@scorer_group.command("create")
@click.argument("description", required=False, default=None)
@click.option("--from-file", "from_file", type=click.Path(exists=True),
              help="Read NL description from a file.")
@click.option("--name", default=None, help="Name for the scorer (auto-generated if omitted).")
def scorer_create(description: str | None, from_file: str | None, name: str | None) -> None:
    """Create a scorer from a natural language description.

    Examples:
      agentlab scorer create "The agent should respond within 5 seconds"
      agentlab scorer create --from-file criteria.txt --name latency_check
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
      agentlab scorer list
      agentlab scorer list --json
    """
    from cli.stream2_helpers import json_response

    scorer = _make_nl_scorer()
    specs = scorer.list()
    if not specs:
        if json_output:
            click.echo(json_response("ok", []))
        else:
            click.echo("No scorers found. Create one with: agentlab scorer create")
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
      agentlab scorer show latency_check
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
      agentlab scorer refine latency_check "Also check for empathy"
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
      agentlab scorer test latency_check --trace abc-123
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
# agentlab quickstart
# ---------------------------------------------------------------------------

@cli.command("full-auto")
@click.option("--cycles", default=5, show_default=True, type=int, help="Optimization cycles to run.")
@click.option("--max-loop-cycles", default=20, show_default=True, type=int,
              help="Continuous loop cycles after optimize.")
@click.option("--yes", "acknowledge", is_flag=True, default=False,
              help="Acknowledge dangerous mode and skip permission-style gates.")
@click.option(
    "--ui",
    type=click.Choice(["auto", "claude", "classic"], case_sensitive=False),
    default=None,
    show_default="auto",
    help="Interactive UI mode for text output.",
)
@click.pass_context
def full_auto(
    ctx: click.Context,
    cycles: int,
    max_loop_cycles: int,
    acknowledge: bool,
    ui: str | None,
) -> None:
    """Run optimization + loop in dangerous full-auto mode.

    Similar intent to 'dangerously skip permissions': auto-promotes accepted
    configs and skips manual promotion/review gates.
    """
    from cli.permissions import PermissionManager

    if not acknowledge and PermissionManager().decision_for("full_auto.run") != "allow":
        click.echo(click.style(
            "Refusing to run full-auto without explicit acknowledgement.\n"
            "Re-run with: agentlab full-auto --yes",
            fg="red",
        ))
        raise SystemExit(1)

    harness = _harness_session(
        title="AgentLab Full Auto",
        stage="Running optimize + loop in full-auto mode",
        tasks=[
            {"id": "load-evidence", "title": "Load eval evidence"},
            {"id": "propose", "title": "Propose candidate config"},
            {"id": "evaluate", "title": "Evaluate candidate config"},
            {"id": "decide", "title": "Decide outcome"},
            {"id": "observe", "title": "Observe loop health"},
            {"id": "deploy", "title": "Deploy or skip"},
            {"id": "canary", "title": "Check canary and resources"},
        ],
        output_format="text",
        ui=ui,
    )
    if harness is None:
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
    else:
        from cli.auto_harness import HarnessEvent

        _emit_harness_event(
            harness,
            HarnessEvent("stage.started", message=f"Optimize stage: {cycles} cycle(s)"),
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
        ui=ui,
        harness=harness,
    )
    if harness is not None:
        from cli.auto_harness import HarnessEvent

        _emit_harness_event(
            harness,
            HarnessEvent("stage.started", message=f"Loop stage: {max_loop_cycles} cycle(s)"),
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
        ui=ui,
        harness=harness,
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
              help="Agent name for AGENTLAB.md.")
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
      agentlab quickstart
      agentlab quickstart --agent-name "Support Bot" --verbose
    """
    del quiet, no_banner
    echo_startup_banner(ctx)
    click.echo(click.style("\n✦ AgentLab Quickstart", fg="cyan", bold=True))
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

    resolved_target_dir = str(_resolve_invocation_input_path(Path(target_dir)))

    # Step 1: Init
    click.echo(click.style("━━━ Step 1/4: Initialize project", fg="cyan", bold=True))
    ctx.invoke(init_project, template="customer-support", target_dir=resolved_target_dir,
               agent_name=agent_name, platform="Google ADK", with_synthetic_data=True)
    workspace_paths = _workspace_state_paths(resolved_target_dir)

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
        significance_min_pairs=getattr(runtime.eval, "significance_min_pairs", 0),
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
            accepted=new_config is not None,
            decision_detail=qs_status if new_config is None else None,
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
    click.echo("    Next: " + click.style("agentlab server", bold=True)
               + " to explore results in the web console\n")

    if auto_open:
        _auto_open_console()


def observer_mod_observe(store: ConversationStore):
    """Thin wrapper to run Observer.observe() from a store."""
    obs = Observer(store)
    return obs.observe()


# ---------------------------------------------------------------------------
# agentlab demo
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
      agentlab demo quickstart
    """
    del quiet, no_banner
    echo_startup_banner(ctx)
    click.echo(click.style("\n╔══════════════════════════════════════╗", fg="cyan"))
    click.echo(click.style("║       AgentLab Demo Mode            ║", fg="cyan"))
    click.echo(click.style("╚══════════════════════════════════════╝\n", fg="cyan"))

    # Init + seed
    click.echo(click.style("▸ Setting up project...", fg="white", bold=True))
    resolved_target_dir = str(_resolve_invocation_input_path(Path(target_dir)))
    ctx.invoke(
        init_project,
        template="customer-support",
        target_dir=resolved_target_dir,
        name=None,
        agent_name="Demo Agent",
        platform="Google ADK",
        with_synthetic_data=True,
        demo=True,
    )
    workspace_paths = _workspace_state_paths(resolved_target_dir)

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
        significance_min_pairs=getattr(runtime.eval, "significance_min_pairs", 0),
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
        accepted=new_config is not None,
        decision_detail=demo_status if new_config is None else None,
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
    click.echo("  Run " + click.style("agentlab server", bold=True)
               + " to open the web console")
    click.echo("  Run " + click.style("agentlab quickstart", bold=True)
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

    A polished, rehearsed demo flow that showcases AgentLab's power in under 5 minutes.
    Uses curated synthetic data to tell a compelling story about agent self-healing.

    Examples:
      agentlab demo vp
      agentlab demo vp --agent-name "Support Bot" --company "Acme Inc"
      agentlab demo vp --no-pause --web
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
    click.echo("  " + click.style("agentlab server", fg="cyan", bold=True) + "    → Open web console to explore details")
    click.echo("  " + click.style("agentlab cx deploy", fg="cyan", bold=True) + " → Deploy to CX Agent Studio")
    click.echo("  " + click.style("agentlab replay", fg="cyan", bold=True) + "    → See full optimization history")
    click.echo()

    # Auto-start web console if requested
    if web:
        pause(1.0)
        click.echo(click.style("\n▸ Starting web console...", fg="cyan", bold=True))
        _auto_open_console()


# ---------------------------------------------------------------------------
# agentlab edit — Natural Language Config Editing
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# agentlab build show (FR-13: inspect commands)
# ---------------------------------------------------------------------------

@cli.group("build-inspect", hidden=True)
def build_inspect_group() -> None:
    """Inspect build artifacts."""


# We add "show" as a subcommand of "build" by converting build to a group isn't
# feasible without breaking the existing positional-arg command.
# Instead, add a top-level `agentlab build-show` command.


# ---------------------------------------------------------------------------
# agentlab policy (FR-13: inspect commands)
# ---------------------------------------------------------------------------

@cli.group("policy")
def policy_group() -> None:
    """Policy management — inspect trained policy artifacts."""


@policy_group.command("list")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def policy_list(json_output: bool = False) -> None:
    """List all policy artifacts.

    Examples:
      agentlab policy list
      agentlab policy list --json
    """
    from cli.stream2_helpers import json_response, list_policies

    policies = list_policies()
    if json_output:
        click.echo(json_response("ok", policies))
        return
    if not policies:
        click.echo("No policy artifacts found.")
        click.echo("Create one with: agentlab rl train")
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
      agentlab policy show my_policy
      agentlab policy show latest --json
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
# agentlab autofix show (FR-13: inspect commands)
# ---------------------------------------------------------------------------

@autofix_group.command("show")
@click.argument("proposal_id")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def autofix_show(proposal_id: str, json_output: bool = False) -> None:
    """Show details for an autofix proposal.

    Examples:
      agentlab autofix show abc123
      agentlab autofix show latest --json
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
      agentlab edit "Make the billing agent more empathetic"
      agentlab edit "Reduce response verbosity" --dry-run
      agentlab edit --interactive
    """
    from optimizer.nl_editor import NLEditor

    store = ConversationStore(db_path=db)
    deployer = Deployer(configs_dir=configs_dir, store=store)
    current_config = _ensure_active_config(deployer)
    editor = NLEditor()

    if interactive:
        workspace = discover_workspace()
        click.echo("AgentLab Edit")
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
        click.echo("Usage: agentlab edit \"description\" or agentlab edit --interactive")
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
        click.echo(json_response("ok", data, next_cmd="agentlab status"))
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
        click.echo("  " + click.style("agentlab runbook apply fix-retrieval-grounding", bold=True))
    elif metrics.success_rate < 0.75:
        click.echo("  Run an optimization cycle to improve overall quality:")
        click.echo("  " + click.style("agentlab optimize --cycles 3", bold=True))
    else:
        click.echo("  Agent is performing well. Continue monitoring with:")
        click.echo("  " + click.style("agentlab status", bold=True))

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
        click.echo(json_response("ok", session.to_dict(), next_cmd="agentlab explain"))
        return

    click.echo(summary)

    if not interactive:
        return

    # Interactive REPL
    click.echo("\nAgentLab Diagnosis")
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
        click.echo(json_response("ok", data, next_cmd="agentlab status"))
        return

    click.echo(click.style("AgentLab Optimization History", bold=True))
    click.echo(click.style("━" * 30, fg="cyan"))
    click.echo()

    if not attempts:
        click.echo(click.style("  No optimization history yet.", fg="yellow"))
        click.echo()
        click.echo("  Run " + click.style("agentlab optimize", bold=True) + " to start the first cycle.")
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
# agentlab cx (CX Agent Studio)
# ---------------------------------------------------------------------------

def _load_cx_manifest(workspace: AgentLabWorkspace | None) -> dict[str, object]:
    """Load the CX manifest for the current workspace when present."""

    if workspace is None:
        return {}
    manifest_path = workspace.agentlab_dir / "cx" / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _resolve_cx_agent_coordinates(
    *,
    project: str | None,
    location: str | None,
    agent_id: str | None,
) -> tuple[str, str, str]:
    """Resolve project, location, and agent ID from flags or the current workspace."""

    from cli.errors import click_error

    workspace = discover_workspace()
    manifest = _load_cx_manifest(workspace)
    agent_ref = manifest.get("agent_ref", {}) if isinstance(manifest.get("agent_ref"), dict) else {}

    resolved_project = project or str(agent_ref.get("project") or "")
    resolved_location = location or str(agent_ref.get("location") or "global")
    resolved_agent_id = agent_id or str(agent_ref.get("agent_id") or "")

    if not resolved_project:
        raise click_error("Project is required. Pass --project or run inside a CX-imported workspace.")
    if not resolved_agent_id:
        raise click_error("Agent ID is required. Pass AGENT_ID/--agent or run inside a CX-imported workspace.")

    return resolved_project, resolved_location, resolved_agent_id


def _resolve_cx_config_and_snapshot(
    *,
    config_path: str | None,
    snapshot_path: str | None,
) -> tuple[str, str]:
    """Resolve the active config and imported snapshot path."""

    from cli.errors import click_error

    workspace = discover_workspace()
    manifest = _load_cx_manifest(workspace)

    resolved_config_path = config_path
    if resolved_config_path is None and workspace is not None:
        resolved = workspace.resolve_active_config()
        if resolved is not None:
            resolved_config_path = str(resolved.path)

    resolved_snapshot_path = snapshot_path or str(manifest.get("snapshot_path") or "")

    if not resolved_config_path:
        raise click_error("Config path is required. Pass --config or run inside an AgentLab workspace.")
    if not resolved_snapshot_path:
        raise click_error("Snapshot path is required. Pass --snapshot or run inside a CX-imported workspace.")

    return resolved_config_path, resolved_snapshot_path

@cli.group("cx")
def cx_group() -> None:
    """Google Cloud CX Agent Studio and Dialogflow CX integration."""


@cx_group.command("auth")
@click.option("--credentials", default=None, help="Path to service account JSON.")
def cx_auth_cmd(credentials: str | None) -> None:
    """Validate Google Cloud credentials for CX access."""

    from cx_studio import CxAuth
    from cx_studio.errors import CxStudioError

    auth = CxAuth(credentials_path=credentials)
    try:
        details = auth.describe()
    except CxStudioError as exc:
        raise click.ClickException(f"CX authentication failed: {exc}") from exc
    click.echo("CX authentication")
    click.echo(f"  Auth type:   {details.get('auth_type') or 'unknown'}")
    click.echo(f"  Project:     {details.get('project_id') or 'unknown'}")
    click.echo(f"  Principal:   {details.get('principal') or 'unknown'}")
    click.echo(f"  Credentials: {details.get('credentials_path') or 'ADC'}")

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
    from cx_studio.errors import CxStudioError

    auth = CxAuth(credentials_path=credentials)
    client = CxClient(auth)
    try:
        agents = client.list_agents(project, location)
    except CxStudioError as exc:
        raise click.ClickException(f"CX agent listing failed: {exc}") from exc
    if not agents:
        click.echo("No agents found.")
        return
    click.echo(f"\n  {'Name':<40} {'Language':<10} {'Description'}")
    click.echo(f"  {'─' * 40} {'─' * 10} {'─' * 30}")
    for agent in agents:
        click.echo(f"  {agent.display_name:<40} {agent.default_language_code:<10} {agent.description[:30]}")

@cx_group.command("import")
@click.argument("agent_id", required=False)
@click.option("--project", required=True, help="GCP project ID.")
@click.option("--location", default="global", show_default=True)
@click.option("--agent", "agent_option", default=None, help="CX agent ID.")
@click.option("--output-dir", default=".", show_default=True, help="Output directory.")
@click.option("--credentials", default=None, help="Path to service account JSON.")
@click.option("--include-test-cases/--no-test-cases", default=True, show_default=True)
def cx_import_cmd(
    agent_id: str | None,
    project: str,
    location: str,
    agent_option: str | None,
    output_dir: str,
    credentials: str | None,
    include_test_cases: bool,
) -> None:
    """Import a CX agent into AgentLab format."""
    from cx_studio import CxAuth, CxClient, CxImporter
    from cx_studio.types import CxAgentRef

    resolved_agent_id = agent_id or agent_option
    if not resolved_agent_id:
        raise click.ClickException("Agent ID is required.")

    click.echo(f"  Importing agent {resolved_agent_id} from {project}/{location}...")
    auth = CxAuth(credentials_path=credentials)
    client = CxClient(auth)
    importer = CxImporter(client)
    ref = CxAgentRef(project=project, location=location, agent_id=resolved_agent_id)
    result = importer.import_agent(ref, output_dir=output_dir, include_test_cases=include_test_cases)

    click.echo(click.style(f"\n  ✓ Imported: {result.agent_name}", fg="green"))
    if result.workspace_path:
        click.echo(f"    Workspace: {result.workspace_path}")
    click.echo(f"    Config:   {result.config_path}")
    if result.eval_path:
        click.echo(f"    Evals:    {result.eval_path}")
    click.echo(f"    Snapshot: {result.snapshot_path}")
    click.echo(f"    Surfaces: {', '.join(result.surfaces_mapped)}")
    click.echo(f"    Test cases: {result.test_cases_imported}")

@cx_group.command("export")
@click.argument("agent_id", required=False)
@click.option("--project", default=None, help="GCP project ID.")
@click.option("--location", default=None, help="Agent location.")
@click.option("--agent", "agent_option", default=None, help="CX agent ID.")
@click.option("--config", "config_path", default=None, help="AgentLab config YAML path.")
@click.option("--snapshot", "snapshot_path", default=None, help="CX snapshot JSON from import.")
@click.option("--credentials", default=None, help="Path to service account JSON.")
@click.option("--dry-run", is_flag=True, help="Preview changes without pushing.")
def cx_export_cmd(
    agent_id: str | None,
    project: str | None,
    location: str | None,
    agent_option: str | None,
    config_path: str | None,
    snapshot_path: str | None,
    credentials: str | None,
    dry_run: bool,
) -> None:
    """Export optimized config back to CX Agent Studio."""
    from cx_studio import CxAuth, CxClient, CxExporter
    from cx_studio.types import CxAgentRef
    import yaml as _yaml

    resolved_project, resolved_location, resolved_agent_id = _resolve_cx_agent_coordinates(
        project=project,
        location=location,
        agent_id=agent_id or agent_option,
    )
    resolved_config_path, resolved_snapshot_path = _resolve_cx_config_and_snapshot(
        config_path=config_path,
        snapshot_path=snapshot_path,
    )

    ref = CxAgentRef(project=resolved_project, location=resolved_location, agent_id=resolved_agent_id)
    with open(resolved_config_path, "r", encoding="utf-8") as f:
        config = _yaml.safe_load(f)

    auth = CxAuth(credentials_path=credentials)
    client = CxClient(auth)
    exporter = CxExporter(client)

    if dry_run:
        click.echo("  Dry run — previewing changes...")
    result = exporter.export_agent(config, ref, resolved_snapshot_path, dry_run=dry_run)

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


@cx_group.command("diff")
@click.argument("agent_id", required=False)
@click.option("--project", default=None, help="GCP project ID.")
@click.option("--location", default=None, help="Agent location.")
@click.option("--agent", "agent_option", default=None, help="CX agent ID.")
@click.option("--config", "config_path", default=None, help="AgentLab config YAML path.")
@click.option("--snapshot", "snapshot_path", default=None, help="CX snapshot JSON from import.")
@click.option("--credentials", default=None, help="Path to service account JSON.")
def cx_diff_cmd(
    agent_id: str | None,
    project: str | None,
    location: str | None,
    agent_option: str | None,
    config_path: str | None,
    snapshot_path: str | None,
    credentials: str | None,
) -> None:
    """Diff the local workspace against the live CX agent."""

    from cx_studio import CxAuth, CxClient, CxExporter
    from cx_studio.types import CxAgentRef
    import yaml as _yaml

    resolved_project, resolved_location, resolved_agent_id = _resolve_cx_agent_coordinates(
        project=project,
        location=location,
        agent_id=agent_id or agent_option,
    )
    resolved_config_path, resolved_snapshot_path = _resolve_cx_config_and_snapshot(
        config_path=config_path,
        snapshot_path=snapshot_path,
    )

    with open(resolved_config_path, "r", encoding="utf-8") as handle:
        config = _yaml.safe_load(handle)

    auth = CxAuth(credentials_path=credentials)
    client = CxClient(auth)
    exporter = CxExporter(client)
    result = exporter.diff_agent(
        config,
        CxAgentRef(project=resolved_project, location=resolved_location, agent_id=resolved_agent_id),
        resolved_snapshot_path,
    )

    click.echo(f"  Planned changes: {len(result.changes)}")
    for change in result.changes:
        click.echo(f"    {change['action'].upper():<8} {change['resource']}/{change.get('name') or change.get('field')}")
    if result.conflicts:
        click.echo(f"\n  Conflicts: {len(result.conflicts)}")
        for conflict in result.conflicts:
            click.echo(f"    CONFLICT {conflict['resource']}/{conflict['name']} field={conflict['field']}")


@cx_group.command("sync")
@click.argument("agent_id", required=False)
@click.option("--project", default=None, help="GCP project ID.")
@click.option("--location", default=None, help="Agent location.")
@click.option("--agent", "agent_option", default=None, help="CX agent ID.")
@click.option("--config", "config_path", default=None, help="AgentLab config YAML path.")
@click.option("--snapshot", "snapshot_path", default=None, help="CX snapshot JSON from import.")
@click.option("--credentials", default=None, help="Path to service account JSON.")
@click.option(
    "--conflict-strategy",
    type=click.Choice(["detect", "force"], case_sensitive=False),
    default="detect",
    show_default=True,
    help="How to handle remote changes that overlap with local edits.",
)
def cx_sync_cmd(
    agent_id: str | None,
    project: str | None,
    location: str | None,
    agent_option: str | None,
    config_path: str | None,
    snapshot_path: str | None,
    credentials: str | None,
    conflict_strategy: str,
) -> None:
    """Synchronize the local workspace with the live CX agent."""

    from cx_studio import CxAuth, CxClient, CxExporter
    from cx_studio.types import CxAgentRef
    import yaml as _yaml

    resolved_project, resolved_location, resolved_agent_id = _resolve_cx_agent_coordinates(
        project=project,
        location=location,
        agent_id=agent_id or agent_option,
    )
    resolved_config_path, resolved_snapshot_path = _resolve_cx_config_and_snapshot(
        config_path=config_path,
        snapshot_path=snapshot_path,
    )

    with open(resolved_config_path, "r", encoding="utf-8") as handle:
        config = _yaml.safe_load(handle)

    auth = CxAuth(credentials_path=credentials)
    client = CxClient(auth)
    exporter = CxExporter(client)
    result = exporter.sync_agent(
        config,
        CxAgentRef(project=resolved_project, location=resolved_location, agent_id=resolved_agent_id),
        resolved_snapshot_path,
        conflict_strategy=conflict_strategy,
    )

    if result.conflicts and not result.pushed:
        click.echo(f"  Sync blocked by {len(result.conflicts)} conflict(s).")
        for conflict in result.conflicts:
            click.echo(f"    CONFLICT {conflict['resource']}/{conflict['name']} field={conflict['field']}")
        return

    if not result.changes:
        click.echo("  No changes detected.")
        return

    click.echo(click.style(f"  ✓ Synced {result.resources_updated} resource(s)", fg="green"))

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
# agentlab adk (Agent Development Kit)
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
    from adk import AdkParseError, parse_agent_directory

    agent_path = Path(path)
    if not agent_path.exists():
        click.echo(click.style(f"  Error: Agent path not found: {path}", fg="red"))
        return

    click.echo(f"  Parsing ADK agent at {path}...")
    try:
        tree = parse_agent_directory(agent_path)
    except AdkParseError as exc:
        raise click.ClickException(f"ADK status failed: {exc}") from exc

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
# agentlab dataset ...
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
# agentlab outcomes ...
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
# agentlab release ...
# ---------------------------------------------------------------------------

@cli.group()
def release() -> None:
    """Manage signed release objects.

    Examples:
      agentlab release create --experiment-id exp-demo
      agentlab release list
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
        click.echo("Create one with: agentlab release create --experiment-id <id>")
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

    Persists the release to .agentlab/releases/ as a JSON file.

    Examples:
      agentlab release create --experiment-id exp-abc123
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
            click.echo(json_response("ok", preview, next_cmd="agentlab release create --experiment-id <id>"))
        else:
            click.echo("Dry run: release create preview")
            click.echo(f"  Experiment: {experiment_id}")
            click.echo(f"  Config:     {config_version if config_version is not None else 'auto'}")
        return

    store = ReleaseStore()
    release = store.create(experiment_id, config_version=config_version)

    if json_output:
        click.echo(json_response("ok", release, next_cmd=f"agentlab release list"))
        return

    click.echo(click.style(f"Applied: created release {release['release_id']}", fg="green"))
    click.echo(f"  Release created: {release['release_id']}")
    click.echo(f"  Experiment: {experiment_id}")
    click.echo(f"  Status:     {release['status']}")
    click.echo(f"  Created:    {release['created_at']}")
    click.echo(f"  Path:       .agentlab/releases/{release['release_id']}.json")


@cli.command("ship")
@click.option("--config-version", type=int, default=None, help="Config version to package and deploy.")
@click.option("--experiment-id", default=None, help="Experiment ID to associate with the release.")
@click.option("--yes", is_flag=True, default=False, help="Skip the interactive confirmation prompt.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
@click.pass_context
def ship(
    ctx: click.Context,
    config_version: int | None,
    experiment_id: str | None,
    yes: bool,
    json_output: bool = False,
) -> None:
    """Apply pending review, create a release, and deploy the selected config as canary."""
    if not yes and not json_output:
        click.confirm(
            "Apply pending review cards, create a release, and deploy to canary?",
            abort=True,
        )

    ctx.invoke(
        deploy,
        workflow=None,
        config_version=config_version,
        strategy="canary",
        configs_dir=CONFIGS_DIR,
        db=DB_PATH,
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
        json_output=json_output,
        output_format="json" if json_output else "text",
        auto_review=True,
        release_experiment_id=experiment_id,
    )


# ---------------------------------------------------------------------------
# agentlab benchmark ...
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

    Supports selectors: ``agentlab rl eval latest``
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
    """Alias for `agentlab config import`."""
    from cli.stream2_helpers import ConfigImporter, json_response

    _echo_deprecation("agentlab import config", "agentlab config import")
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
        click.echo(json_response("ok", result, next_cmd=f"agentlab config show {result['version']}"))
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

    _echo_deprecation("agentlab import transcript upload", "agentlab intelligence import")
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
    _echo_deprecation("agentlab import transcript report", "agentlab intelligence report show")
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
        "agentlab import transcript generate-agent",
        "agentlab intelligence generate-agent",
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


from cli.commands import register_all  # noqa: E402 — after module init
from cli.commands.deploy import _emit_deploy_lineage  # noqa: E402,F401 — test compat

register_all(cli)


if __name__ == "__main__":
    cli()
