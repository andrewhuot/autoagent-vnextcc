"""Terminal Workbench commands for candidate build, inspection, and handoff."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import click

from builder.workbench import WorkbenchService, WorkbenchStore
from cli.errors import click_error
from cli.json_envelope import render_json_envelope
from cli.output import resolve_output_format
from cli.workspace import AgentLabWorkspace, discover_workspace
from shared.build_artifact_store import BuildArtifactStore


TARGET_CHOICES = click.Choice(["portable", "adk", "cx"], case_sensitive=False)
SPLIT_CHOICES = click.Choice(["train", "test", "all"], case_sensitive=False)
OUTPUT_FORMAT_CHOICES = click.Choice(["text", "json", "stream-json"], case_sensitive=False)


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
        raise click.ClickException("Workbench project could not be resolved.")
    return str(resolved)


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
    iterate = f"agentlab workbench iterate --project-id {project_id} \"Refine the candidate\""
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


def _render_stream_event(event: dict[str, Any], *, plan_titles: dict[str, str]) -> None:
    """Render a concise human progress line for canonical Workbench events."""
    name = str(event.get("event") or "message")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if name == "turn.started":
        click.echo(f"Starting Workbench turn: {data.get('run_id')}")
    elif name == "plan.ready":
        plan = data.get("plan") if isinstance(data.get("plan"), dict) else {}
        _index_plan_titles(plan, plan_titles)
        title = plan.get("title") or "plan"
        click.echo(f"Plan ready: {title}")
    elif name == "task.started":
        task_id = str(data.get("task_id") or "")
        click.echo(f"  started: {plan_titles.get(task_id, task_id)}")
    elif name == "artifact.updated":
        artifact = data.get("artifact") if isinstance(data.get("artifact"), dict) else {}
        click.echo(f"  artifact: {artifact.get('name') or artifact.get('id')}")
    elif name == "validation.ready":
        click.echo(f"Validation: {data.get('status') or 'unknown'}")
    elif name == "run.completed":
        click.echo(f"Run completed: {data.get('status') or 'unknown'}")
    elif name == "run.failed":
        click.echo(f"Run failed: {data.get('error') or data.get('message') or 'unknown'}")


def _index_plan_titles(plan: dict[str, Any], index: dict[str, str]) -> None:
    """Index plan task titles so event-only updates are understandable."""
    task_id = plan.get("id") or plan.get("task_id")
    if task_id:
        index[str(task_id)] = str(plan.get("title") or task_id)
    for child in plan.get("children") or []:
        if isinstance(child, dict):
            _index_plan_titles(child, index)


async def _consume_workbench_stream(
    stream_factory: Any,
    *,
    output_format: str,
) -> list[dict[str, Any]]:
    """Consume a Workbench async stream after awaiting the service factory."""
    stream = await stream_factory
    events: list[dict[str, Any]] = []
    plan_titles: dict[str, str] = {}
    async for event in stream:
        events.append(event)
        if output_format == "stream-json":
            click.echo(json.dumps(event, default=str))
        elif output_format == "text":
            _render_stream_event(event, plan_titles=plan_titles)
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
        saved = persist_generated_config(
            generated_config,
            artifact_store=_artifact_store_for_workspace(workspace),
            source="workbench_cli",
            source_prompt=f"Workbench project {project_id}",
            builder_session_id=project_id,
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


def _render_summary_text(data: dict[str, Any], *, compact: bool = False) -> None:
    """Render a terminal-native Workbench status view."""
    bridge = data.get("bridge") if isinstance(data.get("bridge"), dict) else {}
    evaluation = bridge.get("evaluation") if isinstance(bridge.get("evaluation"), dict) else {}
    optimization = bridge.get("optimization") if isinstance(bridge.get("optimization"), dict) else {}
    agent_card = data.get("agent_card") if isinstance(data.get("agent_card"), dict) else {}
    run = data.get("run") if isinstance(data.get("run"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    counts = agent_card.get("counts") if isinstance(agent_card.get("counts"), dict) else {}

    click.echo(click.style("\nAgentLab Workbench", bold=True))
    click.echo("━━━━━━━━━━━━━━━━━━")
    click.echo(f"  Project:   {data.get('project_id')} ({data.get('name')})")
    click.echo(f"  Target:    {data.get('target')} / {data.get('environment')}")
    click.echo(f"  Version:   {data.get('version')}")
    click.echo(f"  Run:       {run.get('status') or 'none'}")
    if run.get("failure_reason"):
        click.echo(f"  Reason:    {run.get('failure_reason')}")
    click.echo(f"  Agent:     {agent_card.get('name')} ({agent_card.get('model')})")
    click.echo(
        "  Card:      "
        f"{counts.get('tools', 0)} tool(s), "
        f"{counts.get('guardrails', 0)} guardrail(s), "
        f"{counts.get('eval_suites', 0)} eval suite(s)"
    )
    click.echo(f"  Artifacts: {data.get('artifact_count')}")
    click.echo(f"  Validation:{summary.get('validation_status') or 'not_run'}")
    click.echo("")
    click.echo(click.style("Readiness", bold=True))
    click.echo(f"  Eval:      {evaluation.get('label') or 'Candidate needed'}")
    if evaluation.get("description"):
        click.echo(f"             {evaluation.get('description')}")
    click.echo(f"  Optimize:  {optimization.get('label') or 'Eval candidate not ready'}")
    if optimization.get("description") and not compact:
        click.echo(f"             {optimization.get('description')}")
    blockers = list(evaluation.get("blocking_reasons") or [])
    if blockers:
        click.echo("  Blockers:")
        for reason in blockers:
            click.echo(f"    - {reason}")
    click.echo("")
    click.echo("Note: Workbench structural validation is not an eval result.")
    click.echo("")
    click.echo(click.style("Next step", bold=True))
    next_commands = data.get("next_commands") if isinstance(data.get("next_commands"), dict) else {}
    readiness = evaluation.get("readiness_state")
    if readiness == "needs_materialization":
        click.echo(f"  {next_commands.get('save')}")
    elif readiness == "ready_for_eval":
        click.echo(f"  {next_commands.get('eval')}")
    else:
        click.echo(f"  {next_commands.get('iterate')}")


def _render_save_text(data: dict[str, Any]) -> None:
    """Render a clear materialization result for terminal users."""
    bridge = data.get("bridge") if isinstance(data.get("bridge"), dict) else {}
    evaluation = bridge.get("evaluation") if isinstance(bridge.get("evaluation"), dict) else {}
    optimization = bridge.get("optimization") if isinstance(bridge.get("optimization"), dict) else {}
    save_result = data.get("save_result") if isinstance(data.get("save_result"), dict) else {}
    click.echo(click.style("\nWorkbench candidate saved", bold=True))
    click.echo("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    click.echo(f"  Config: {save_result.get('config_path')}")
    click.echo(f"  Evals:  {save_result.get('eval_cases_path')}")
    click.echo(f"  Eval:   {evaluation.get('label')}")
    click.echo(f"  Next:   {data.get('next', {}).get('start_eval_command')}")
    click.echo(f"  Optimize waits for Eval: {optimization.get('label')}")
    click.echo("")
    click.echo("This saved candidate is now the active local config for Eval.")


@click.group("workbench")
def workbench_group() -> None:
    """Build, inspect, iterate, and materialize Workbench candidates."""


@workbench_group.command("build")
@click.argument("brief")
@click.option("--project-id", default=None, help="Existing Workbench project id to continue.")
@click.option("--new", "start_new", is_flag=True, help="Force a fresh Workbench project.")
@click.option("--target", default="portable", type=TARGET_CHOICES, show_default=True)
@click.option("--environment", default="draft", show_default=True)
@click.option("--mock", is_flag=True, help="Force deterministic mock Workbench builder mode.")
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
        click.echo(click.style("\nStarting AgentLab Workbench", bold=True))
        click.echo("Workbench builds a candidate. Eval still measures it afterward.")

    agent, execution = build_default_agent_with_readiness(force_mock=mock)
    events = asyncio.run(
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
            ),
            output_format=resolved_output_format,
        )
    )
    if resolved_output_format == "stream-json":
        return
    resolved_project_id = _last_project_id_from_events(events, fallback=selected_project_id)
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
    _render_summary_text(data)
    if status != "ok":
        raise click.ClickException(str((data.get("run") or {}).get("failure_reason") or "Workbench run failed."))


@workbench_group.command("iterate")
@click.argument("message")
@click.option("--project-id", default=None, help="Workbench project id to continue.")
@click.option("--target", default="portable", type=TARGET_CHOICES, show_default=True)
@click.option("--environment", default="draft", show_default=True)
@click.option("--mock", is_flag=True, help="Force deterministic mock Workbench builder mode.")
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
        click.echo(click.style("\nContinuing AgentLab Workbench", bold=True))
    agent, execution = build_default_agent_with_readiness(force_mock=mock)
    events = asyncio.run(
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
            ),
            output_format=resolved_output_format,
        )
    )
    if resolved_output_format == "stream-json":
        return
    resolved_project_id = _last_project_id_from_events(events, fallback=resolved_project_id)
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
    _render_summary_text(data)
    if status != "ok":
        raise click.ClickException(str((data.get("run") or {}).get("failure_reason") or "Workbench iteration failed."))


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
    _render_summary_text(data)


@workbench_group.command("status")
@click.option("--project-id", default=None, help="Workbench project id to inspect.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def status_command(project_id: str | None, json_output: bool) -> None:
    """Show a compact readiness status for the latest Workbench project."""
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    resolved_project_id = _resolve_project_id(service, project_id)
    data = _build_summary(service, resolved_project_id)
    if json_output:
        _emit_envelope("ok", data, next_command=data["next_commands"]["save"])
        return
    _render_summary_text(data, compact=True)


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
    """Materialize the Workbench candidate into the active local config path."""
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
    _render_save_text(data)


@workbench_group.command("handoff")
@click.option("--project-id", default=None, help="Workbench project id to inspect.")
@click.option("--save", "save_first", is_flag=True, help="Materialize before printing handoff.")
@click.option("--eval-run-id", default=None, help="Completed Eval run id for Optimize readiness.")
@click.option("--category", default=None, help="Optional Eval category hint.")
@click.option("--dataset", "dataset_path", default=None, help="Optional Eval dataset path.")
@click.option("--generated-suite-id", default=None, help="Optional generated Eval suite id.")
@click.option("--split", default="all", type=SPLIT_CHOICES, show_default=True)
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def handoff_command(
    project_id: str | None,
    save_first: bool,
    eval_run_id: str | None,
    category: str | None,
    dataset_path: str | None,
    generated_suite_id: str | None,
    split: str,
    json_output: bool,
) -> None:
    """Print the typed Workbench Eval/Optimize bridge for the current candidate."""
    workspace = _require_workspace()
    service = _service_for_workspace(workspace)
    resolved_project_id = _resolve_project_id(service, project_id)
    if save_first:
        data = _materialize_candidate(
            service,
            workspace,
            project_id=resolved_project_id,
            category=category,
            dataset_path=dataset_path,
            generated_suite_id=generated_suite_id,
            split=split,
        )
        bridge = data["bridge"]
    else:
        try:
            bridge = service.build_improvement_bridge_payload(
                project_id=resolved_project_id,
                eval_run_id=eval_run_id,
                category=category,
                dataset_path=dataset_path,
                generated_suite_id=generated_suite_id,
                split=split,
            )
        except KeyError as exc:
            raise click.ClickException("Workbench project or run not found.") from exc
        data = {
            "bridge": bridge,
            "eval_request": (bridge.get("evaluation") or {}).get("request"),
            "optimize_request_template": (bridge.get("optimization") or {}).get("request_template"),
            "next": {
                "save_command": f"agentlab workbench save --project-id {resolved_project_id}",
                "optimize_requires_eval_run": True,
            },
        }
    if json_output:
        _emit_envelope("ok", data, next_command=data["next"].get("save_command") or data["next"].get("start_eval_command"))
        return
    if save_first:
        _render_save_text(data)
        return
    _render_summary_text(_build_summary(service, resolved_project_id))
