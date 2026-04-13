"""Terminal rendering helpers for CLI Workbench commands."""

from __future__ import annotations

from typing import Any

import click


def render_workbench_status(snapshot: dict[str, Any], *, verbose: bool = False) -> None:
    """Render a workbench project status dashboard."""
    project = snapshot.get("project") or snapshot
    plan = snapshot.get("plan")
    artifacts = snapshot.get("artifacts") or []

    project_id = project.get("project_id", "unknown")
    name = project.get("name", "Untitled")
    target = project.get("target", "portable")
    environment = project.get("environment", "draft")
    version = project.get("version", 0)
    build_status = project.get("build_status", "idle")
    active_run_id = project.get("active_run_id", "none")

    click.echo(click.style("\nWorkbench Status", bold=True))
    click.echo("━━━━━━━━━━━━━━━━━━")
    click.echo(click.style(f"  Project:     {name}", fg="cyan", bold=True))
    click.echo(f"  ID:          {project_id}")
    click.echo(f"  Target:      {target}")
    click.echo(f"  Environment: {environment}")
    click.echo(f"  Version:     Draft v{version}")
    click.echo(f"  Build:       {build_status}")
    if active_run_id and active_run_id != "none":
        click.echo(f"  Active run:  {active_run_id}")

    model = project.get("model") or {}
    agents = model.get("agents") or []
    tools = model.get("tools") or []
    guardrails = model.get("guardrails") or []
    sub_agents = model.get("sub_agents") or []

    click.echo(f"\n  Agents:      {len(agents)}")
    click.echo(f"  Tools:       {len(tools)}")
    click.echo(f"  Guardrails:  {len(guardrails)}")
    click.echo(f"  Sub-agents:  {len(sub_agents)}")

    if artifacts:
        click.echo(f"\n  Artifacts:   {len(artifacts)}")
        for art in artifacts[:5]:
            art_name = art.get("name", "unnamed")
            art_cat = art.get("category", "")
            click.echo(f"    - {art_name} ({art_cat})")
        if len(artifacts) > 5:
            click.echo(f"    ... and {len(artifacts) - 5} more")

    last_test = project.get("last_test")
    if last_test:
        test_status = last_test.get("status", "unknown")
        checks = last_test.get("checks") or []
        passed = sum(1 for c in checks if c.get("passed"))
        click.echo(f"\n  Validation:  {test_status} ({passed}/{len(checks)} checks)")
        if verbose:
            for check in checks:
                icon = "pass" if check.get("passed") else "FAIL"
                click.echo(f"    [{icon}] {check.get('name', 'check')}")

    if plan:
        tasks = plan.get("children") or plan.get("tasks") or []
        click.echo(f"\n  Plan tasks:  {len(tasks)}")

    activity = project.get("activity") or []
    if activity and verbose:
        click.echo("\n  Recent Activity:")
        for entry in activity[:5]:
            ts = entry.get("timestamp", "")[:19]
            kind = entry.get("kind", "")
            summary = entry.get("summary", "")
            click.echo(f"    {ts}  {kind:8s}  {summary}")

    next_step = _suggest_next_step(project)
    click.echo(click.style(f"\n  Next step:   {next_step}", fg="green"))


def render_workbench_event(event_name: str, data: dict[str, Any]) -> str | None:
    """Render a single streaming event as a terminal line. Returns None to suppress."""
    renderer = _EVENT_RENDERERS.get(event_name)
    if renderer is None:
        return None
    line = renderer(data)
    if line is not None:
        click.echo(line)
    return line


_EVENT_RENDERERS: dict[str, Any] = {
    "turn.started": lambda d: click.style(
        f"[turn] Started turn {d.get('turn_number', '')}", fg="cyan",
    ),
    "plan.ready": lambda d: click.style(
        f"[plan] Plan ready: {_count_plan_tasks(d)} tasks", fg="cyan",
    ),
    "task.started": lambda d: f"[task] {d.get('title', d.get('task_id', 'task'))} ...started",
    "task.progress": lambda d: f"[task] {d.get('title', '')}: {d.get('note', d.get('message', ''))}",
    "task.completed": lambda d: click.style(
        f"[task] {d.get('title', d.get('task_id', 'task'))} ...done", fg="green",
    ),
    "message.delta": lambda _d: None,
    "artifact.updated": lambda d: f"[artifact] {(d.get('artifact') or d).get('name', 'artifact')} updated",
    "iteration.started": lambda d: click.style(
        f"[iterate] Iteration {d.get('iteration', '?')} started", fg="yellow",
    ),
    "reflect.started": lambda _d: "[reflect] Starting validation...",
    "reflect.completed": lambda d: f"[reflect] Reflection complete",
    "reflection.completed": lambda d: f"[reflect] Quality: {d.get('quality_score', '?')}",
    "validation.ready": lambda d: click.style(
        f"[validate] Validation: {d.get('status', '?')}", fg="green" if d.get("status") == "passed" else "yellow",
    ),
    "present.ready": lambda d: f"[present] {d.get('summary', 'Presentation ready')}",
    "build.completed": lambda d: click.style("[build] Build pass complete", fg="green"),
    "run.completed": lambda d: click.style(
        f"[done] Run complete: Draft v{d.get('version', '?')}", fg="green", bold=True,
    ),
    "run.failed": lambda d: click.style(
        f"[error] Run failed: {d.get('failure_reason', d.get('message', 'unknown'))}", fg="red",
    ),
    "run.cancelled": lambda d: click.style(
        f"[cancelled] Run cancelled: {d.get('cancel_reason', '')}", fg="yellow",
    ),
    "harness.metrics": lambda _d: None,
    "harness.heartbeat": lambda _d: None,
    "progress.stall": lambda d: click.style("[warn] Progress stall detected", fg="yellow"),
    "error": lambda d: click.style(f"[error] {d.get('message', 'Unknown error')}", fg="red"),
}


def render_bridge_status(bridge: dict[str, Any]) -> None:
    """Render the Eval/Optimize handoff readiness."""
    candidate = bridge.get("candidate") or {}
    evaluation = bridge.get("evaluation") or {}
    optimization = bridge.get("optimization") or {}

    click.echo(click.style("\nWorkbench Bridge Status", bold=True))
    click.echo("━━━━━━━━━━━━━━━━━━━━━━━━")

    click.echo(f"  Agent:       {candidate.get('agent_name', 'unknown')}")
    click.echo(f"  Project:     {candidate.get('project_id', '?')}")
    click.echo(f"  Version:     v{candidate.get('version', '?')}")
    click.echo(f"  Target:      {candidate.get('target', 'portable')}")
    click.echo(f"  Validation:  {candidate.get('validation_status', '?')}")
    click.echo(f"  Review gate: {candidate.get('review_gate_status', '?')}")
    if candidate.get("config_path"):
        click.echo(f"  Config:      {candidate['config_path']}")

    eval_status = evaluation.get("readiness_state", evaluation.get("status", "?"))
    eval_label = evaluation.get("label", "Eval")
    eval_color = "green" if eval_status == "ready_for_eval" else "yellow"
    click.echo(click.style(f"\n  Eval:        {eval_label} ({eval_status})", fg=eval_color))
    for reason in evaluation.get("blocking_reasons") or []:
        click.echo(f"    - {reason}")
    if evaluation.get("description"):
        click.echo(f"    {evaluation['description']}")

    opt_status = optimization.get("readiness_state", optimization.get("status", "?"))
    opt_label = optimization.get("label", "Optimize")
    opt_color = "green" if opt_status == "ready_for_optimize" else "yellow"
    click.echo(click.style(f"  Optimize:    {opt_label} ({opt_status})", fg=opt_color))
    for reason in optimization.get("blocking_reasons") or []:
        click.echo(f"    - {reason}")

    if evaluation.get("primary_action_label"):
        click.echo(click.style(
            f"\n  Next step:   {evaluation['primary_action_label']}", fg="green",
        ))


def render_project_list(projects: list[dict[str, Any]]) -> None:
    """Render a table of workbench projects."""
    if not projects:
        click.echo("No workbench projects found.")
        click.echo(click.style("  Create one: agentlab workbench create \"your brief\"", fg="green"))
        return

    click.echo(click.style("\nWorkbench Projects", bold=True))
    click.echo("━━━━━━━━━━━━━━━━━━━")
    click.echo(f"  {'ID':<20s}  {'Name':<30s}  {'Version':>8s}  {'Target':<10s}  Status")
    click.echo(f"  {'─' * 20}  {'─' * 30}  {'─' * 8}  {'─' * 10}  {'─' * 12}")
    for proj in projects:
        pid = proj.get("project_id", "?")[:20]
        name = (proj.get("name") or "Untitled")[:30]
        ver = str(proj.get("version", 0))
        tgt = proj.get("target", "portable")[:10]
        bs = proj.get("build_status", "idle")
        click.echo(f"  {pid:<20s}  {name:<30s}  {ver:>8s}  {tgt:<10s}  {bs}")


def render_validation(validation: dict[str, Any]) -> None:
    """Render validation check results."""
    status = validation.get("status", "unknown")
    checks = validation.get("checks") or []
    color = "green" if status == "passed" else "red"
    click.echo(click.style(f"\nValidation: {status}", fg=color, bold=True))
    for check in checks:
        icon = click.style("PASS", fg="green") if check.get("passed") else click.style("FAIL", fg="red")
        click.echo(f"  [{icon}] {check.get('name', 'check')}")
        if not check.get("passed") and check.get("reason"):
            click.echo(f"         {check['reason']}")


def render_plan(plan: dict[str, Any]) -> None:
    """Render a change plan summary."""
    click.echo(click.style("\nChange Plan", bold=True))
    click.echo("━━━━━━━━━━━━")
    click.echo(f"  Plan ID:     {plan.get('plan_id', '?')}")
    click.echo(f"  Status:      {plan.get('status', '?')}")
    click.echo(f"  Approval:    {'required' if plan.get('requires_approval') else 'not required'}")
    operations = plan.get("operations") or []
    if operations:
        click.echo(f"  Operations:  {len(operations)}")
        for op in operations:
            label = op.get("label", op.get("operation", "?"))
            compat_raw = op.get("compatibility_status", {})
            compat = compat_raw.get("status", "") if isinstance(compat_raw, dict) else str(compat_raw)
            suffix = f" ({compat})" if compat else ""
            click.echo(f"    - {label}{suffix}")


def _suggest_next_step(project: dict[str, Any]) -> str:
    """Determine the suggested next CLI command."""
    build_status = project.get("build_status", "idle")
    last_test = project.get("last_test")
    has_model = bool((project.get("model") or {}).get("agents"))

    if build_status == "idle" and not has_model:
        return "agentlab workbench build \"describe your agent\""
    if build_status in ("running", "reflecting", "presenting"):
        return "agentlab workbench status  (build in progress)"
    if build_status == "failed":
        return "agentlab workbench build \"try again with different brief\""
    if last_test and last_test.get("status") == "failed":
        return "agentlab workbench test  (re-run after fixing issues)"
    if has_model and build_status in ("completed", "done", "idle"):
        return "agentlab workbench bridge  (check eval readiness)"
    return "agentlab workbench status"


def _count_plan_tasks(data: dict[str, Any]) -> int:
    """Count tasks in a plan.ready event payload."""
    plan = data.get("plan") or data
    children = plan.get("children") or plan.get("tasks") or []
    return len(children) if children else data.get("total_tasks", 0)
