"""Terminal Workbench commands — build, inspect, iterate, and materialize candidates.

Provides the ``agentlab workbench`` command group integrating:
- Codex backbone: save/materialization, bridge-driven readiness, enriched JSON envelopes
- Claude ports: renderer split, broader command surface, graceful Ctrl+C, 30+ event renderers

Command surface: status (default), create, build, iterate, show, list, plan,
apply, test, rollback, cancel, save, bridge.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import click

from builder.workbench import WorkbenchService, WorkbenchStore
from cli.errors import click_error
from cli.json_envelope import render_json_envelope
from cli.output import resolve_output_format
from cli.workbench_render import (
    render_bridge_status,
    render_candidate_summary,
    render_plan,
    render_project_list,
    render_save_result,
    render_validation,
    render_workbench_event,
    render_workbench_status,
)
from cli.workspace import AgentLabWorkspace, discover_workspace
from shared.build_artifact_store import BuildArtifactStore


TARGET_CHOICES = click.Choice(["portable", "adk", "cx"], case_sensitive=False)
SPLIT_CHOICES = click.Choice(["train", "test", "all"], case_sensitive=False)
OUTPUT_FORMAT_CHOICES = click.Choice(["text", "json", "stream-json"], case_sensitive=False)


# ---------------------------------------------------------------------------
# Shared helpers (Codex backbone)
# ---------------------------------------------------------------------------


def _require_workspace() -> AgentLabWorkspace:
    """Return the active workspace because Workbench state must be workspace-scoped."""
    workspace = discover_workspace()
    if workspace is None:
        raise click_error("No AgentLab workspace found. Run agentlab new to create one.")
    return workspace


def _service_for_workspace(workspace: AgentLabWorkspace) -> WorkbenchService:
    """Create the Workbench service bound to the workspace-local JSON store."""
    return WorkbenchService(WorkbenchStore(workspace.agentlab_dir / "workbench_projects.json"))


def _artifact_store_for_workspace(workspace: AgentLabWorkspace) -> BuildArtifactStore:
    """Return the shared build artifact store used by materialized candidates."""
    return BuildArtifactStore(
        path=workspace.agentlab_dir / "build_artifacts.json",
        latest_path=workspace.agentlab_dir / "build_artifact_latest.json",
    )


def _emit_envelope(
    status: str,
    data: dict[str, Any],
    *,
    next_command: str | None = None,
    exit_code: int = 0,
) -> None:
    """Emit one standard machine-readable CLI envelope, then exit if needed."""
    click.echo(render_json_envelope(status, data, next_command=next_command))
    if exit_code:
        raise click.exceptions.Exit(exit_code)


def _resolve_project_id(
    service: WorkbenchService,
    project_id: str | None,
) -> str:
    """Resolve an explicit project id or the default latest Workbench project."""
    if project_id:
        return project_id
    payload = service.get_default_project()
    project = payload.get("project") if isinstance(payload, dict) else {}
    resolved = project.get("project_id") if isinstance(project, dict) else None
    if not resolved:
        raise click.ClickException(
            "No default project available. Create one with: agentlab workbench create"
        )
    return str(resolved)


# ---------------------------------------------------------------------------
# Data builders (Codex backbone)
# ---------------------------------------------------------------------------


def _latest_run(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Return the active run or newest known run from a plan snapshot."""
    active_run = snapshot.get("active_run")
    if isinstance(active_run, dict):
        return active_run
    runs = [run for run in snapshot.get("runs") or [] if isinstance(run, dict)]
    if not runs:
        return None
    return max(runs, key=lambda run: str(run.get("created_at") or ""))


def _agent_card(model: dict[str, Any] | None, fallback_name: str | None) -> dict[str, Any]:
    """Summarize the canonical agent card/config state for terminal output."""
    model = model if isinstance(model, dict) else {}
    agents = model.get("agents") if isinstance(model.get("agents"), list) else []
    root_agent = agents[0] if agents and isinstance(agents[0], dict) else {}
    tools = [item for item in model.get("tools") or [] if isinstance(item, dict)]
    guardrails = [item for item in model.get("guardrails") or [] if isinstance(item, dict)]
    eval_suites = [item for item in model.get("eval_suites") or [] if isinstance(item, dict)]
    instructions = str(root_agent.get("instructions") or "")
    return {
        "name": str(root_agent.get("name") or fallback_name or "Workbench Agent"),
        "model": str(root_agent.get("model") or "unknown"),
        "instruction_chars": len(instructions),
        "instruction_preview": " ".join(instructions.split())[:240],
        "tools": [str(item.get("name") or item.get("id") or "tool") for item in tools],
        "guardrails": [str(item.get("name") or item.get("id") or "guardrail") for item in guardrails],
        "eval_suites": [str(item.get("name") or item.get("id") or "eval") for item in eval_suites],
        "counts": {
            "agents": len(agents),
            "tools": len(tools),
            "guardrails": len(guardrails),
            "eval_suites": len(eval_suites),
        },
    }


def _compact_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep CLI JSON focused on the durable run fields scripts need."""
    if not isinstance(run, dict):
        return None
    return {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "phase": run.get("phase"),
        "error": run.get("error"),
        "failure_reason": run.get("failure_reason"),
        "cancel_reason": run.get("cancel_reason"),
        "execution_mode": run.get("execution_mode"),
        "provider": run.get("provider"),
        "model": run.get("model"),
    }


def _extract_bridge(service: WorkbenchService, project_id: str) -> dict[str, Any] | None:
    """Build the strict Workbench bridge when a run exists."""
    try:
        return service.build_improvement_bridge_payload(project_id=project_id)
    except KeyError:
        return None


def _next_commands(project_id: str, bridge: dict[str, Any] | None) -> dict[str, str]:
    """Return copy-pasteable next command hints for this Workbench state."""
    save = f"agentlab workbench save --project-id {project_id}"
    show = f"agentlab workbench show --project-id {project_id}"
    iterate = f'agentlab workbench iterate --project-id {project_id} "Refine the candidate"'
    eval_cmd = "agentlab eval run"
    optimize = "agentlab optimize --cycles 3"
    request = ((bridge or {}).get("evaluation") or {}).get("request")
    if isinstance(request, dict) and request.get("config_path"):
        eval_cmd = f"agentlab eval run --config {request['config_path']}"
    return {
        "show": show,
        "iterate": iterate,
        "save": save,
        "eval": eval_cmd,
        "optimize_after_eval": optimize,
    }


def _build_summary(service: WorkbenchService, project_id: str) -> dict[str, Any]:
    """Build a stable CLI payload from the hydrated Workbench snapshot."""
    snapshot = service.get_plan_snapshot(project_id=project_id)
    run = _latest_run(snapshot)
    bridge = _extract_bridge(service, project_id)
    validation = None
    if isinstance(run, dict) and isinstance(run.get("validation"), dict):
        validation = run.get("validation")
    elif isinstance(snapshot.get("last_test"), dict):
        validation = snapshot.get("last_test")
    presentation = run.get("presentation") if isinstance(run, dict) and isinstance(run.get("presentation"), dict) else {}
    review_gate = presentation.get("review_gate") if isinstance(presentation, dict) else None
    if review_gate is None and isinstance(run, dict):
        review_gate = run.get("review_gate")

    artifacts = [item for item in snapshot.get("artifacts") or [] if isinstance(item, dict)]
    turns = [item for item in snapshot.get("turns") or [] if isinstance(item, dict)]
    data = {
        "project_id": snapshot.get("project_id"),
        "name": snapshot.get("name"),
        "target": snapshot.get("target"),
        "environment": snapshot.get("environment"),
        "version": snapshot.get("version"),
        "build_status": snapshot.get("build_status"),
        "run": _compact_run(run),
        "summary": snapshot.get("run_summary"),
        "validation": validation,
        "review_gate": review_gate,
        "bridge": bridge,
        "agent_card": _agent_card(snapshot.get("model"), snapshot.get("name")),
        "artifact_count": len(artifacts),
        "latest_artifact": artifacts[-1] if artifacts else None,
        "turn_count": len(turns),
        "next_commands": _next_commands(str(snapshot.get("project_id") or project_id), bridge),
    }
    return data


def _terminal_status(data: dict[str, Any]) -> str:
    """Return the authoritative terminal status from stream output."""
    run = data.get("run") if isinstance(data.get("run"), dict) else {}
    status = str(run.get("status") or data.get("build_status") or "")
    if status == "completed":
        return "ok"
    return "error"


# ---------------------------------------------------------------------------
# Streaming helpers (Codex pattern + Claude Ctrl+C)
# ---------------------------------------------------------------------------


async def _consume_workbench_stream(
    stream_factory: Any,
    *,
    output_format: str,
) -> list[dict[str, Any]]:
    """Consume a Workbench async stream after awaiting the service factory."""
    stream = await stream_factory
    events: list[dict[str, Any]] = []
    async for event in stream:
        events.append(event)
        if output_format == "stream-json":
            click.echo(json.dumps(event, default=str))
        elif output_format == "text":
            render_workbench_event(
                str(event.get("event") or "message"),
                event.get("data") if isinstance(event.get("data"), dict) else {},
            )
    return events


def _last_project_id_from_events(events: list[dict[str, Any]], fallback: str | None = None) -> str:
    """Read the project id from the newest event that carries it."""
    for event in reversed(events):
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        project_id = data.get("project_id")
        if project_id:
            return str(project_id)
    if fallback:
        return fallback
    raise click.ClickException("Workbench run did not report a project id.")


def _cancel_active_run(service: WorkbenchService, events: list[dict[str, Any]], project_id: str | None) -> None:
    """Best-effort cancel of the active run after Ctrl+C."""
    active_run_id = None
    for ev in reversed(events):
        rid = (ev.get("data") or {}).get("run_id")
        if rid:
            active_run_id = rid
            break
    if active_run_id and project_id:
        try:
            service.cancel_run(
                project_id=project_id,
                run_id=active_run_id,
                reason="Cancelled by operator (Ctrl+C).",
            )
        except Exception as exc:
            click.echo(click.style(f"Warning: cancel failed: {exc}", fg="yellow"), err=True)


# ---------------------------------------------------------------------------
# Materialization (Codex backbone — authoritative save path)
# ---------------------------------------------------------------------------


def _materialize_candidate(
    service: WorkbenchService,
    workspace: AgentLabWorkspace,
    *,
    project_id: str,
    category: str | None = None,
    dataset_path: str | None = None,
    generated_suite_id: str | None = None,
    split: str = "all",
) -> dict[str, Any]:
    """Save the generated Workbench candidate into normal AgentLab workspace files."""
    from builder.workspace_config import persist_generated_config

    try:
        generated_config = service.generated_config_for_bridge(project_id=project_id)
        source_prompt = service.materialization_source_prompt(project_id=project_id)
        saved = persist_generated_config(
            generated_config,
            artifact_store=_artifact_store_for_workspace(workspace),
            source="workbench_cli",
            source_prompt=source_prompt,
            builder_session_id=project_id,
        )
        service.record_materialized_candidate(
            project_id=project_id,
            config_path=saved.config_path,
            eval_cases_path=saved.eval_cases_path,
            category=category,
            dataset_path=dataset_path,
            generated_suite_id=generated_suite_id,
            split=split,
        )
        bridge = service.build_improvement_bridge_payload(
            project_id=project_id,
            config_path=saved.config_path,
            eval_cases_path=saved.eval_cases_path,
            category=category,
            dataset_path=dataset_path,
            generated_suite_id=generated_suite_id,
            split=split,
        )
    except KeyError as exc:
        raise click.ClickException("Workbench project or run not found.") from exc
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    evaluation = bridge.get("evaluation") if isinstance(bridge.get("evaluation"), dict) else {}
    optimization = bridge.get("optimization") if isinstance(bridge.get("optimization"), dict) else {}
    return {
        "bridge": bridge,
        "save_result": saved.to_dict(),
        "eval_request": evaluation.get("request"),
        "optimize_request_template": optimization.get("request_template"),
        "next": {
            "start_eval_command": f"agentlab eval run --config {saved.config_path}",
            "start_optimize_command": "agentlab optimize --cycles 3",
            "optimize_requires_eval_run": True,
        },
    }


def _bridge_next_command(bridge: dict[str, Any]) -> str:
    """Choose the next CLI command from persisted bridge readiness."""
    evaluation = bridge.get("evaluation") if isinstance(bridge.get("evaluation"), dict) else {}
    optimization = bridge.get("optimization") if isinstance(bridge.get("optimization"), dict) else {}
    if optimization.get("readiness_state") == "ready_for_optimize":
        return "agentlab optimize --cycles 3"
    request = evaluation.get("request") if isinstance(evaluation.get("request"), dict) else {}
    config_path = request.get("config_path")
    if evaluation.get("readiness_state") == "ready_for_eval" and config_path:
        return f"agentlab eval run --config {config_path}"
    return "agentlab workbench save"


# ---------------------------------------------------------------------------
# Command group (Claude _WorkbenchGroup for bare invocation → status)
# ---------------------------------------------------------------------------


class _WorkbenchGroup(click.Group):
    """Route bare ``agentlab workbench`` to the status subcommand."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        help_flags = set(self.get_help_option_names(ctx))
        if not args:
            return super().parse_args(ctx, ["status"])
        if args and args[0] not in self.commands and args[0] not in help_flags:
            return super().parse_args(ctx, ["status", *args])
        return super().parse_args(ctx, args)


@click.group("workbench", cls=_WorkbenchGroup)
def workbench_group() -> None:
    """Build, inspect, iterate, and materialize Workbench candidates.

    The Workbench is the inspectable agent-candidate harness between Build and
    Eval. Use it to iterate on agent config from the terminal.

    Examples:
      agentlab workbench                                    # show status
      agentlab workbench create "Build a support agent"     # new project
      agentlab workbench build "Add flight status tool"     # stream a build
      agentlab workbench iterate "Add a guardrail for PII"  # follow-up turn
      agentlab workbench save                               # materialize for eval
      agentlab workbench bridge --json                      # eval readiness
    """


# ---------------------------------------------------------------------------
# status (default bare invocation)
# ---------------------------------------------------------------------------


@workbench_group.command("status", hidden=True)
@click.option("--project-id", default=None, help="Workbench project id to inspect.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
@click.option("--verbose", "-v", is_flag=True, help="Show extended details.")
def status_command(project_id: str | None, json_output: bool, verbose: bool) -> None:
    """Show a compact readiness status for the latest Workbench project."""
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    resolved_project_id = _resolve_project_id(service, project_id)

    try:
        snapshot = service.get_plan_snapshot(project_id=resolved_project_id)
    except KeyError:
        snapshot = service.get_project(resolved_project_id)

    if json_output:
        _emit_envelope("ok", snapshot, next_command="agentlab workbench bridge")
        return
    render_workbench_status(snapshot, verbose=verbose)


# ---------------------------------------------------------------------------
# create (from Claude)
# ---------------------------------------------------------------------------


@workbench_group.command("create")
@click.argument("brief")
@click.option("--target", default="portable", type=TARGET_CHOICES, show_default=True,
              help="Compilation target for generated exports.")
@click.option("--environment", default="draft", show_default=True,
              help="Deployment environment label.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def create_command(brief: str, target: str, environment: str, json_output: bool) -> None:
    """Create a new Workbench project from a brief."""
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    result = service.create_project(brief=brief, target=target, environment=environment)

    if json_output:
        _emit_envelope("ok", result, next_command="agentlab workbench build")
        return

    project = result.get("project", result)
    click.echo(click.style("\nWorkbench project created", fg="green", bold=True))
    click.echo(f"  ID:      {project.get('project_id', '?')}")
    click.echo(f"  Name:    {project.get('name', 'Untitled')}")
    click.echo(f"  Target:  {target}")
    click.echo(click.style(f'\n  Next:    agentlab workbench build "{brief[:60]}"', fg="green"))


# ---------------------------------------------------------------------------
# build (Codex backbone + Claude Ctrl+C)
# ---------------------------------------------------------------------------


@workbench_group.command("build")
@click.argument("brief")
@click.option("--project-id", default=None, help="Existing Workbench project id to continue.")
@click.option("--new", "start_new", is_flag=True, help="Force a fresh Workbench project.")
@click.option("--target", default="portable", type=TARGET_CHOICES, show_default=True)
@click.option("--environment", default="draft", show_default=True)
@click.option("--mock", is_flag=True, help="Force deterministic mock Workbench builder mode.")
@click.option("--require-live", is_flag=True, help="Fail instead of using mock/template Workbench generation.")
@click.option("--auto-iterate/--no-auto-iterate", default=True, show_default=True)
@click.option("--max-iterations", default=3, type=click.IntRange(1, 6), show_default=True)
@click.option("--max-seconds", default=None, type=int, help="Optional wall-clock budget.")
@click.option("--max-tokens", default=None, type=int, help="Optional estimated-token budget.")
@click.option("--max-cost-usd", default=None, type=float, help="Optional estimated-cost budget.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output final summary as JSON.")
@click.option("--output-format", default="text", type=OUTPUT_FORMAT_CHOICES, show_default=True)
def build_command(
    brief: str,
    project_id: str | None,
    start_new: bool,
    target: str,
    environment: str,
    mock: bool,
    require_live: bool,
    auto_iterate: bool,
    max_iterations: int,
    max_seconds: int | None,
    max_tokens: int | None,
    max_cost_usd: float | None,
    json_output: bool,
    output_format: str,
) -> None:
    """Run the Workbench build loop from the terminal."""
    from builder.workbench_agent import build_default_agent_with_readiness

    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    resolved_output_format = resolve_output_format(output_format, json_output=json_output)
    selected_project_id = None if start_new else project_id
    if resolved_output_format == "text":
        click.echo(click.style(f"\n[workbench] Building: {brief}", fg="cyan", bold=True))
        click.echo("Workbench builds a candidate. Eval still measures it afterward.")

    agent, execution = build_default_agent_with_readiness(force_mock=mock)

    collected_events: list[dict[str, Any]] = []

    try:
        collected_events = asyncio.run(
            _consume_workbench_stream(
                service.run_build_stream(
                    project_id=selected_project_id,
                    brief=brief,
                    target=target,
                    environment=environment,
                    agent=agent,
                    auto_iterate=auto_iterate,
                    max_iterations=max_iterations,
                    max_seconds=max_seconds,
                    max_tokens=max_tokens,
                    max_cost_usd=max_cost_usd,
                    execution=execution,
                    require_live=require_live,
                ),
                output_format=resolved_output_format,
            )
        )
    except KeyboardInterrupt:
        click.echo(click.style("\nInterrupted. Cancelling run...", fg="yellow"))
        _cancel_active_run(service, collected_events, selected_project_id)
        raise SystemExit(130)

    if resolved_output_format == "stream-json":
        return
    resolved_project_id = _last_project_id_from_events(collected_events, fallback=selected_project_id)
    data = _build_summary(service, resolved_project_id)
    status = _terminal_status(data)
    if resolved_output_format == "json":
        _emit_envelope(
            status,
            data,
            next_command=data["next_commands"]["save"],
            exit_code=0 if status == "ok" else 1,
        )
        return
    render_candidate_summary(data)
    if status != "ok":
        run = data.get("run") if isinstance(data.get("run"), dict) else {}
        raise click.ClickException(str(run.get("error") or run.get("failure_reason") or "Workbench run failed."))


# ---------------------------------------------------------------------------
# iterate (Codex backbone + Claude Ctrl+C)
# ---------------------------------------------------------------------------


@workbench_group.command("iterate")
@click.argument("message")
@click.option("--project-id", default=None, help="Workbench project id to continue.")
@click.option("--target", default="portable", type=TARGET_CHOICES, show_default=True)
@click.option("--environment", default="draft", show_default=True)
@click.option("--mock", is_flag=True, help="Force deterministic mock Workbench builder mode.")
@click.option("--require-live", is_flag=True, help="Fail instead of using mock/template Workbench generation.")
@click.option("--max-iterations", default=3, type=click.IntRange(1, 6), show_default=True)
@click.option("--max-seconds", default=None, type=int, help="Optional wall-clock budget.")
@click.option("--max-tokens", default=None, type=int, help="Optional estimated-token budget.")
@click.option("--max-cost-usd", default=None, type=float, help="Optional estimated-cost budget.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output final summary as JSON.")
@click.option("--output-format", default="text", type=OUTPUT_FORMAT_CHOICES, show_default=True)
def iterate_command(
    message: str,
    project_id: str | None,
    target: str,
    environment: str,
    mock: bool,
    require_live: bool,
    max_iterations: int,
    max_seconds: int | None,
    max_tokens: int | None,
    max_cost_usd: float | None,
    json_output: bool,
    output_format: str,
) -> None:
    """Apply a follow-up Workbench turn to the latest or selected project."""
    from builder.workbench_agent import build_default_agent_with_readiness

    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    resolved_output_format = resolve_output_format(output_format, json_output=json_output)
    resolved_project_id = _resolve_project_id(service, project_id)
    if resolved_output_format == "text":
        click.echo(click.style(f"\n[workbench] Iterating: {message}", fg="cyan", bold=True))
    agent, execution = build_default_agent_with_readiness(force_mock=mock)

    collected_events: list[dict[str, Any]] = []

    try:
        collected_events = asyncio.run(
            _consume_workbench_stream(
                service.run_iteration_stream(
                    project_id=resolved_project_id,
                    follow_up=message,
                    target=target,
                    environment=environment,
                    agent=agent,
                    max_iterations=max_iterations,
                    max_seconds=max_seconds,
                    max_tokens=max_tokens,
                    max_cost_usd=max_cost_usd,
                    execution=execution,
                    require_live=require_live,
                ),
                output_format=resolved_output_format,
            )
        )
    except KeyboardInterrupt:
        click.echo(click.style("\nInterrupted. Cancelling run...", fg="yellow"))
        _cancel_active_run(service, collected_events, resolved_project_id)
        raise SystemExit(130)

    if resolved_output_format == "stream-json":
        return
    resolved_project_id = _last_project_id_from_events(collected_events, fallback=resolved_project_id)
    data = _build_summary(service, resolved_project_id)
    status = _terminal_status(data)
    if resolved_output_format == "json":
        _emit_envelope(
            status,
            data,
            next_command=data["next_commands"]["save"],
            exit_code=0 if status == "ok" else 1,
        )
        return
    render_candidate_summary(data)
    if status != "ok":
        run = data.get("run") if isinstance(data.get("run"), dict) else {}
        raise click.ClickException(str(run.get("error") or run.get("failure_reason") or "Workbench iteration failed."))


# ---------------------------------------------------------------------------
# show (Codex — detailed candidate inspection)
# ---------------------------------------------------------------------------


@workbench_group.command("show")
@click.option("--project-id", default=None, help="Workbench project id to inspect.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def show_command(project_id: str | None, json_output: bool) -> None:
    """Show the candidate card, validation, readiness, and next action."""
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    resolved_project_id = _resolve_project_id(service, project_id)
    data = _build_summary(service, resolved_project_id)
    if json_output:
        _emit_envelope("ok", data, next_command=data["next_commands"]["save"])
        return
    render_candidate_summary(data)


# ---------------------------------------------------------------------------
# list (from Claude)
# ---------------------------------------------------------------------------


@workbench_group.command("list")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def list_command(json_output: bool) -> None:
    """List all Workbench projects in this workspace."""
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    projects = service.store.list_projects()

    if json_output:
        _emit_envelope("ok", projects, next_command="agentlab workbench status --project-id <id>")
        return
    render_project_list(projects)


# ---------------------------------------------------------------------------
# plan (from Claude)
# ---------------------------------------------------------------------------


@workbench_group.command("plan")
@click.argument("message")
@click.option("--project-id", default=None, help="Workbench project id.")
@click.option("--target", default=None, type=TARGET_CHOICES,
              help="Override target for plan compatibility.")
@click.option("--mode", default="plan", show_default=True,
              type=click.Choice(["plan", "apply", "ask"]), help="Planning mode.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def plan_command(message: str, project_id: str | None, target: str | None,
                 mode: str, json_output: bool) -> None:
    """Plan changes without executing them.

    Creates a structured change plan that can be reviewed before applying.

    Examples:
      agentlab workbench plan "Add a flight status tool and a PII guardrail"
      agentlab workbench plan "Add eval suite" --mode apply
    """
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    pid = _resolve_project_id(service, project_id)

    result = service.plan_change(project_id=pid, message=message, target=target, mode=mode)

    if json_output:
        _emit_envelope("ok", result, next_command="agentlab workbench apply <plan_id>")
        return

    plan_data = result.get("plan") or {}
    render_plan(plan_data)
    plan_id = plan_data.get("plan_id", "?")
    click.echo(click.style(f"\n  Next:    agentlab workbench apply {plan_id}", fg="green"))


# ---------------------------------------------------------------------------
# apply (from Claude)
# ---------------------------------------------------------------------------


@workbench_group.command("apply")
@click.argument("plan_id")
@click.option("--project-id", default=None, help="Workbench project id.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def apply_command(plan_id: str, project_id: str | None, json_output: bool) -> None:
    """Apply an approved change plan and run validation.

    Example:
      agentlab workbench apply plan-abc123
    """
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    pid = _resolve_project_id(service, project_id)

    result = service.apply_plan(project_id=pid, plan_id=plan_id)

    if json_output:
        _emit_envelope("ok", result, next_command="agentlab workbench status")
        return

    project = result.get("project", result)
    click.echo(click.style(
        f"\nPlan applied — now at Draft v{project.get('version', '?')}",
        fg="green", bold=True,
    ))
    last_test = project.get("last_test")
    if last_test:
        render_validation(last_test)
    click.echo(click.style("\n  Next:    agentlab workbench status", fg="green"))


# ---------------------------------------------------------------------------
# test (from Claude)
# ---------------------------------------------------------------------------


@workbench_group.command("test")
@click.option("--project-id", default=None, help="Workbench project id.")
@click.option("--message", "-m", default="", help="Optional sample message for validation.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def test_command(project_id: str | None, message: str, json_output: bool) -> None:
    """Run deterministic validation on the current project.

    Checks: canonical model present, exports compile, target compatibility.

    Example:
      agentlab workbench test
    """
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    pid = _resolve_project_id(service, project_id)

    result = service.run_test(project_id=pid, message=message)

    if json_output:
        _emit_envelope("ok", result, next_command="agentlab workbench bridge")
        return

    project = result.get("project", result)
    last_test = project.get("last_test")
    if last_test:
        render_validation(last_test)
    else:
        click.echo("No validation results available.")
    click.echo(click.style("\n  Next:    agentlab workbench bridge", fg="green"))


# ---------------------------------------------------------------------------
# rollback (from Claude)
# ---------------------------------------------------------------------------


@workbench_group.command("rollback")
@click.argument("version", type=int)
@click.option("--project-id", default=None, help="Workbench project id.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def rollback_command(version: int, project_id: str | None, json_output: bool) -> None:
    """Roll back to a prior version by creating a new version from that snapshot.

    Example:
      agentlab workbench rollback 2
    """
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    pid = _resolve_project_id(service, project_id)

    result = service.rollback(project_id=pid, version=version)

    if json_output:
        _emit_envelope("ok", result, next_command="agentlab workbench status")
        return

    project = result.get("project", result)
    click.echo(click.style(
        f"\nRolled back to v{version} — now at Draft v{project.get('version', '?')}",
        fg="green", bold=True,
    ))
    click.echo(click.style("  Next:    agentlab workbench status", fg="green"))


# ---------------------------------------------------------------------------
# cancel (from Claude)
# ---------------------------------------------------------------------------


@workbench_group.command("cancel")
@click.argument("run_id", required=False, default=None)
@click.option("--project-id", default=None, help="Workbench project id.")
@click.option("--reason", default="Cancelled by operator.", help="Cancellation reason.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def cancel_command(run_id: str | None, project_id: str | None, reason: str,
                   json_output: bool) -> None:
    """Cancel an active Workbench run.

    If RUN_ID is omitted, cancels the active run on the default project.

    Example:
      agentlab workbench cancel run-abc123
    """
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    pid = _resolve_project_id(service, project_id)

    if run_id is None:
        project_data = service.get_project(pid)
        proj = project_data.get("project", project_data) if isinstance(project_data, dict) else {}
        run_id = proj.get("active_run_id")
        if not run_id:
            raise click.ClickException("No active run to cancel.")

    result = service.cancel_run(project_id=pid, run_id=run_id, reason=reason)

    if json_output:
        _emit_envelope("ok", result, next_command="agentlab workbench status")
        return

    click.echo(click.style(f"\nRun {run_id} cancelled.", fg="yellow"))
    click.echo(click.style("  Next:    agentlab workbench status", fg="green"))


# ---------------------------------------------------------------------------
# save (Codex backbone — authoritative materialization)
# ---------------------------------------------------------------------------


@workbench_group.command("save")
@click.option("--project-id", default=None, help="Workbench project id to materialize.")
@click.option("--category", default=None, help="Optional Eval category hint.")
@click.option("--dataset", "dataset_path", default=None, help="Optional Eval dataset path.")
@click.option("--generated-suite-id", default=None, help="Optional generated Eval suite id.")
@click.option("--split", default="all", type=SPLIT_CHOICES, show_default=True)
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def save_command(
    project_id: str | None,
    category: str | None,
    dataset_path: str | None,
    generated_suite_id: str | None,
    split: str,
    json_output: bool,
) -> None:
    """Materialize the Workbench candidate into the active local config path.

    Writes the generated config into configs/, creates eval cases, sets the
    saved candidate as the active local config, and returns Eval/Optimize
    handoff data. Does NOT start Eval or Optimize.
    """
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    resolved_project_id = _resolve_project_id(service, project_id)
    data = _materialize_candidate(
        service,
        workspace,
        project_id=resolved_project_id,
        category=category,
        dataset_path=dataset_path,
        generated_suite_id=generated_suite_id,
        split=split,
    )
    if json_output:
        _emit_envelope(
            "ok",
            data,
            next_command=data["next"]["start_eval_command"],
        )
        return
    render_save_result(data)


# ---------------------------------------------------------------------------
# bridge (from Claude — read-only eval/optimize readiness)
# ---------------------------------------------------------------------------


@workbench_group.command("bridge")
@click.option("--project-id", default=None, help="Workbench project id.")
@click.option("--eval-run-id", default=None, help="Completed Eval run id for Optimize readiness.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def bridge_command(project_id: str | None, eval_run_id: str | None,
                   json_output: bool) -> None:
    """Show Eval/Optimize handoff readiness for the current candidate.

    The bridge inspects the Workbench candidate and reports whether it is
    ready for Eval, and whether Optimize is available after Eval.

    Examples:
      agentlab workbench bridge
      agentlab workbench bridge --json
      agentlab workbench bridge --eval-run-id eval-abc123
    """
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    pid = _resolve_project_id(service, project_id)

    try:
        bridge = service.build_improvement_bridge_payload(
            project_id=pid,
            eval_run_id=eval_run_id,
        )
    except KeyError as exc:
        raise click.ClickException(
            f"No active run found for project {pid}. Run a build first: agentlab workbench build"
        ) from exc

    if json_output:
        _emit_envelope("ok", bridge, next_command=_bridge_next_command(bridge))
        return
    render_bridge_status(bridge)
