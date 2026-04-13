"""CLI Workbench commands — design, build, validate, and hand off agent candidates.

Provides the ``agentlab workbench`` command group that drives the core
Workbench loop from the terminal: create a project, stream a build,
iterate, validate, inspect bridge readiness, and export for Eval.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import click
import yaml

from cli.errors import click_error
from cli.json_envelope import render_json_envelope
from cli.output import emit_stream_json, resolve_output_format
from cli.workbench_render import (
    render_bridge_status,
    render_plan,
    render_project_list,
    render_validation,
    render_workbench_event,
    render_workbench_status,
)
from cli.workspace import discover_workspace


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _workbench_service():
    """Lazy-build the canonical WorkbenchService from the discovered workspace."""
    from builder.workbench import WorkbenchService, WorkbenchStore

    workspace = discover_workspace()
    if workspace is None:
        raise click_error("No AgentLab workspace found. Run: agentlab new")
    store_path = workspace.root / ".agentlab" / "workbench_projects.json"
    store = WorkbenchStore(path=store_path)
    return WorkbenchService(store), workspace


def _resolve_project_id(service, project_id: str | None) -> str:
    """Resolve project_id, falling back to the default project."""
    if project_id:
        return project_id
    try:
        default = service.get_default_project()
        project = default.get("project", default)
        return project["project_id"]
    except (KeyError, TypeError) as exc:
        raise click_error(
            "No default project available. Create one with: agentlab workbench create"
        ) from exc


def _json_output(data: Any, *, next_command: str | None = None) -> None:
    """Emit the standard JSON envelope."""
    click.echo(render_json_envelope(status="ok", data=data, next_command=next_command))


# ---------------------------------------------------------------------------
# Command group
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
    """Agent Builder Workbench — design, build, validate, and hand off agents.

    The Workbench is the inspectable agent-candidate harness between Build and
    Eval. Use it to iterate on agent config from the terminal.

    Examples:
      agentlab workbench                                    # show status
      agentlab workbench create "Build a support agent"     # new project
      agentlab workbench build "Add flight status tool"     # stream a build
      agentlab workbench iterate "Add a guardrail for PII"  # follow-up turn
      agentlab workbench bridge --json                      # eval readiness
    """


# ---------------------------------------------------------------------------
# status (default)
# ---------------------------------------------------------------------------


@workbench_group.command("status", hidden=True)
@click.option("--project", "project_id", default=None, help="Project ID (default: most recent).")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
@click.option("--verbose", "-v", is_flag=True, help="Show extended details.")
def workbench_status(project_id: str | None, json_output: bool, verbose: bool) -> None:
    """Show the current Workbench project status."""
    service, _ws = _workbench_service()
    pid = _resolve_project_id(service, project_id)

    try:
        snapshot = service.get_plan_snapshot(project_id=pid)
    except KeyError:
        snapshot = service.get_project(pid)

    if json_output:
        _json_output(snapshot, next_command="agentlab workbench bridge")
        return
    render_workbench_status(snapshot, verbose=verbose)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@workbench_group.command("create")
@click.argument("brief")
@click.option("--target", default="portable", show_default=True,
              type=click.Choice(["portable", "adk", "cx"]),
              help="Compilation target for generated exports.")
@click.option("--environment", default="draft", show_default=True,
              help="Deployment environment label.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def workbench_create(brief: str, target: str, environment: str, json_output: bool) -> None:
    """Create a new Workbench project from a brief."""
    service, _ws = _workbench_service()
    result = service.create_project(brief=brief, target=target, environment=environment)

    if json_output:
        _json_output(result, next_command="agentlab workbench build")
        return

    project = result.get("project", result)
    click.echo(click.style("\nWorkbench project created", fg="green", bold=True))
    click.echo(f"  ID:      {project.get('project_id', '?')}")
    click.echo(f"  Name:    {project.get('name', 'Untitled')}")
    click.echo(f"  Target:  {target}")
    click.echo(click.style(f"\n  Next:    agentlab workbench build \"{brief[:60]}\"", fg="green"))


# ---------------------------------------------------------------------------
# build (streaming)
# ---------------------------------------------------------------------------


@workbench_group.command("build")
@click.argument("brief")
@click.option("--project", "project_id", default=None,
              help="Existing project ID. Omit to create or use default.")
@click.option("--target", default="portable", show_default=True,
              type=click.Choice(["portable", "adk", "cx"]))
@click.option("--environment", default="draft", show_default=True)
@click.option("--max-iterations", default=3, show_default=True, type=click.IntRange(1, 6),
              help="Maximum autonomous correction iterations per turn.")
@click.option("--max-seconds", default=None, type=int, help="Wall-clock budget in seconds.")
@click.option("--max-cost-usd", default=None, type=float, help="Cost budget in USD.")
@click.option("--no-auto-iterate", is_flag=True, default=False,
              help="Disable autonomous correction iterations.")
@click.option("--mock", is_flag=True, default=False, help="Force mock agent (no API keys needed).")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
@click.option("--output-format",
              type=click.Choice(["text", "json", "stream-json"], case_sensitive=False),
              default="text", show_default=True)
def workbench_build(
    brief: str,
    project_id: str | None,
    target: str,
    environment: str,
    max_iterations: int,
    max_seconds: int | None,
    max_cost_usd: float | None,
    no_auto_iterate: bool,
    mock: bool,
    json_output: bool,
    output_format: str,
) -> None:
    """Stream a Workbench build from a brief.

    Creates a project if none exists, then streams the plan-tree build with
    live task progress, artifact generation, validation, and presentation.

    Examples:
      agentlab workbench build "Build an airline support agent"
      agentlab workbench build "Add a booking tool" --project wb-abc123
      agentlab workbench build "Travel agent" --mock --output-format stream-json
    """
    from builder.workbench_agent import build_default_agent_with_readiness

    fmt = resolve_output_format(output_format, json_output=json_output)
    service, _ws = _workbench_service()
    agent, execution = build_default_agent_with_readiness(force_mock=mock)

    if project_id is None:
        default = service.get_default_project()
        project_id = default["project"]["project_id"]

    if fmt == "text":
        click.echo(click.style(f"\n[workbench] Building: {brief}", fg="cyan", bold=True))

    collected_events: list[dict[str, Any]] = []
    last_data: dict[str, Any] = {}

    async def _drain() -> dict[str, Any]:
        nonlocal last_data
        stream = await service.run_build_stream(
            project_id=project_id,
            brief=brief,
            target=target,
            environment=environment,
            agent=agent,
            auto_iterate=not no_auto_iterate,
            max_iterations=max_iterations,
            max_seconds=max_seconds,
            max_cost_usd=max_cost_usd,
            execution=execution,
        )
        async for event in stream:
            event_name = str(event.get("event", ""))
            data = event.get("data") or {}
            collected_events.append(event)
            last_data = data

            if fmt == "stream-json":
                emit_stream_json(event, writer=click.echo)
            elif fmt == "text":
                render_workbench_event(event_name, data)
        return last_data

    try:
        final = asyncio.run(_drain())
    except KeyboardInterrupt:
        click.echo(click.style("\nInterrupted. Cancelling run...", fg="yellow"))
        try:
            active_run_id = None
            for ev in reversed(collected_events):
                rid = (ev.get("data") or {}).get("run_id")
                if rid:
                    active_run_id = rid
                    break
            if active_run_id and project_id:
                service.cancel_run(
                    project_id=project_id,
                    run_id=active_run_id,
                    reason="Cancelled by operator (Ctrl+C).",
                )
        except Exception:
            pass
        raise SystemExit(130)

    if fmt == "json":
        _json_output(
            {"events": collected_events, "final": final},
            next_command="agentlab workbench status",
        )
    elif fmt == "text":
        click.echo(click.style("\n  Next:    agentlab workbench status", fg="green"))


# ---------------------------------------------------------------------------
# iterate (streaming)
# ---------------------------------------------------------------------------


@workbench_group.command("iterate")
@click.argument("follow_up")
@click.option("--project", "project_id", default=None, help="Project ID (default: most recent).")
@click.option("--target", default="portable", show_default=True,
              type=click.Choice(["portable", "adk", "cx"]))
@click.option("--max-iterations", default=3, show_default=True, type=click.IntRange(1, 6))
@click.option("--max-seconds", default=None, type=int, help="Wall-clock budget in seconds.")
@click.option("--max-cost-usd", default=None, type=float, help="Cost budget in USD.")
@click.option("--mock", is_flag=True, default=False, help="Force mock agent.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
@click.option("--output-format",
              type=click.Choice(["text", "json", "stream-json"], case_sensitive=False),
              default="text", show_default=True)
def workbench_iterate(
    follow_up: str,
    project_id: str | None,
    target: str,
    max_iterations: int,
    max_seconds: int | None,
    max_cost_usd: float | None,
    mock: bool,
    json_output: bool,
    output_format: str,
) -> None:
    """Iterate on an existing Workbench build with a follow-up message.

    Examples:
      agentlab workbench iterate "Add a guardrail for PII"
      agentlab workbench iterate "Remove the booking tool" --project wb-abc123
    """
    from builder.workbench_agent import build_default_agent_with_readiness

    fmt = resolve_output_format(output_format, json_output=json_output)
    service, _ws = _workbench_service()
    agent, execution = build_default_agent_with_readiness(force_mock=mock)
    pid = _resolve_project_id(service, project_id)

    if fmt == "text":
        click.echo(click.style(f"\n[workbench] Iterating: {follow_up}", fg="cyan", bold=True))

    collected_events: list[dict[str, Any]] = []
    last_data: dict[str, Any] = {}

    async def _drain() -> dict[str, Any]:
        nonlocal last_data
        stream = await service.run_iteration_stream(
            project_id=pid,
            follow_up=follow_up,
            target=target,
            agent=agent,
            max_iterations=max_iterations,
            max_seconds=max_seconds,
            max_cost_usd=max_cost_usd,
            execution=execution,
        )
        async for event in stream:
            event_name = str(event.get("event", ""))
            data = event.get("data") or {}
            collected_events.append(event)
            last_data = data

            if fmt == "stream-json":
                emit_stream_json(event, writer=click.echo)
            elif fmt == "text":
                render_workbench_event(event_name, data)
        return last_data

    try:
        final = asyncio.run(_drain())
    except KeyboardInterrupt:
        click.echo(click.style("\nInterrupted. Cancelling run...", fg="yellow"))
        try:
            active_run_id = None
            for ev in reversed(collected_events):
                rid = (ev.get("data") or {}).get("run_id")
                if rid:
                    active_run_id = rid
                    break
            if active_run_id and pid:
                service.cancel_run(
                    project_id=pid,
                    run_id=active_run_id,
                    reason="Cancelled by operator (Ctrl+C).",
                )
        except Exception:
            pass
        raise SystemExit(130)

    if fmt == "json":
        _json_output(
            {"events": collected_events, "final": final},
            next_command="agentlab workbench status",
        )
    elif fmt == "text":
        click.echo(click.style("\n  Next:    agentlab workbench status", fg="green"))


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


@workbench_group.command("plan")
@click.argument("message")
@click.option("--project", "project_id", default=None, help="Project ID (default: most recent).")
@click.option("--target", default=None, type=click.Choice(["portable", "adk", "cx"]),
              help="Override target for plan compatibility.")
@click.option("--mode", default="plan", show_default=True,
              type=click.Choice(["plan", "apply", "ask"]),
              help="Planning mode.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def workbench_plan(message: str, project_id: str | None, target: str | None,
                   mode: str, json_output: bool) -> None:
    """Plan changes without executing them.

    Creates a structured change plan that can be reviewed before applying.

    Examples:
      agentlab workbench plan "Add a flight status tool and a PII guardrail"
      agentlab workbench plan "Add eval suite" --mode apply
    """
    service, _ws = _workbench_service()
    pid = _resolve_project_id(service, project_id)

    result = service.plan_change(
        project_id=pid, message=message, target=target, mode=mode,
    )

    if json_output:
        _json_output(result, next_command="agentlab workbench apply <plan_id>")
        return

    plan = result.get("plan") or {}
    render_plan(plan)
    plan_id = plan.get("plan_id", "?")
    click.echo(click.style(f"\n  Next:    agentlab workbench apply {plan_id}", fg="green"))


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


@workbench_group.command("apply")
@click.argument("plan_id")
@click.option("--project", "project_id", default=None, help="Project ID (default: most recent).")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def workbench_apply(plan_id: str, project_id: str | None, json_output: bool) -> None:
    """Apply an approved change plan and run validation.

    Example:
      agentlab workbench apply plan-abc123
    """
    service, _ws = _workbench_service()
    pid = _resolve_project_id(service, project_id)

    result = service.apply_plan(project_id=pid, plan_id=plan_id)

    if json_output:
        _json_output(result, next_command="agentlab workbench status")
        return

    project = result.get("project", result)
    click.echo(click.style(f"\nPlan applied — now at Draft v{project.get('version', '?')}", fg="green", bold=True))
    last_test = project.get("last_test")
    if last_test:
        render_validation(last_test)
    click.echo(click.style("\n  Next:    agentlab workbench status", fg="green"))


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------


@workbench_group.command("test")
@click.option("--project", "project_id", default=None, help="Project ID (default: most recent).")
@click.option("--message", "-m", default="", help="Optional sample message for validation.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def workbench_test(project_id: str | None, message: str, json_output: bool) -> None:
    """Run deterministic validation on the current project.

    Checks: canonical model present, exports compile, target compatibility.

    Example:
      agentlab workbench test
    """
    service, _ws = _workbench_service()
    pid = _resolve_project_id(service, project_id)

    result = service.run_test(project_id=pid, message=message)

    if json_output:
        _json_output(result, next_command="agentlab workbench bridge")
        return

    project = result.get("project", result)
    last_test = project.get("last_test")
    if last_test:
        render_validation(last_test)
    else:
        click.echo("No validation results available.")
    click.echo(click.style("\n  Next:    agentlab workbench bridge", fg="green"))


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


@workbench_group.command("rollback")
@click.argument("version", type=int)
@click.option("--project", "project_id", default=None, help="Project ID (default: most recent).")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def workbench_rollback(version: int, project_id: str | None, json_output: bool) -> None:
    """Roll back to a prior version by creating a new version from that snapshot.

    Example:
      agentlab workbench rollback 2
    """
    service, _ws = _workbench_service()
    pid = _resolve_project_id(service, project_id)

    result = service.rollback(project_id=pid, version=version)

    if json_output:
        _json_output(result, next_command="agentlab workbench status")
        return

    project = result.get("project", result)
    click.echo(click.style(
        f"\nRolled back to v{version} — now at Draft v{project.get('version', '?')}",
        fg="green", bold=True,
    ))
    click.echo(click.style("  Next:    agentlab workbench status", fg="green"))


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------


@workbench_group.command("cancel")
@click.argument("run_id", required=False, default=None)
@click.option("--project", "project_id", default=None, help="Project ID (default: most recent).")
@click.option("--reason", default="Cancelled by operator.", help="Cancellation reason.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def workbench_cancel(run_id: str | None, project_id: str | None, reason: str,
                     json_output: bool) -> None:
    """Cancel an active Workbench run.

    If RUN_ID is omitted, cancels the active run on the default project.

    Example:
      agentlab workbench cancel run-abc123
    """
    service, _ws = _workbench_service()
    pid = _resolve_project_id(service, project_id)

    if run_id is None:
        project_data = service.get_project(pid)
        proj = project_data.get("project", project_data)
        run_id = proj.get("active_run_id")
        if not run_id:
            raise click.ClickException("No active run to cancel.")

    result = service.cancel_run(project_id=pid, run_id=run_id, reason=reason)

    if json_output:
        _json_output(result, next_command="agentlab workbench status")
        return

    click.echo(click.style(f"\nRun {run_id} cancelled.", fg="yellow"))
    click.echo(click.style("  Next:    agentlab workbench status", fg="green"))


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@workbench_group.command("list")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def workbench_list(json_output: bool) -> None:
    """List all Workbench projects in this workspace."""
    service, _ws = _workbench_service()
    projects = service.store.list_projects()

    if json_output:
        _json_output(projects, next_command="agentlab workbench status --project <id>")
        return

    render_project_list(projects)


# ---------------------------------------------------------------------------
# bridge
# ---------------------------------------------------------------------------


@workbench_group.command("bridge")
@click.option("--project", "project_id", default=None, help="Project ID (default: most recent).")
@click.option("--eval-run-id", default=None, help="Completed eval run ID to link.")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def workbench_bridge(project_id: str | None, eval_run_id: str | None,
                     json_output: bool) -> None:
    """Show Eval/Optimize handoff readiness for the current candidate.

    The bridge inspects the Workbench candidate and reports whether it is
    ready for Eval, and whether Optimize is available after Eval.

    Examples:
      agentlab workbench bridge
      agentlab workbench bridge --json
      agentlab workbench bridge --eval-run-id eval-abc123
    """
    service, _ws = _workbench_service()
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
        _json_output(bridge, next_command="agentlab workbench export")
        return

    render_bridge_status(bridge)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@workbench_group.command("export")
@click.option("--project", "project_id", default=None, help="Project ID (default: most recent).")
@click.option("--output", "-o", "output_path", default=None,
              help="Output path (default: configs/workbench_candidate.yaml).")
@click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
def workbench_export(project_id: str | None, output_path: str | None,
                     json_output: bool) -> None:
    """Export the candidate config to disk for use with agentlab eval run.

    Writes the generated Workbench config as a YAML file that the eval
    runner can discover and evaluate.

    Examples:
      agentlab workbench export
      agentlab workbench export -o configs/my_candidate.yaml
    """
    service, ws = _workbench_service()
    pid = _resolve_project_id(service, project_id)

    config = service.generated_config_for_bridge(project_id=pid)

    if output_path:
        dest = Path(output_path)
    else:
        dest = ws.root / "configs" / "workbench_candidate.yaml"

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    if json_output:
        _json_output(
            {"config_path": str(dest), "config": config},
            next_command=f"agentlab eval run --config {dest}",
        )
        return

    click.echo(click.style(f"\nCandidate config written to {dest}", fg="green", bold=True))
    click.echo(click.style(f"  Next:    agentlab eval run --config {dest}", fg="green"))
