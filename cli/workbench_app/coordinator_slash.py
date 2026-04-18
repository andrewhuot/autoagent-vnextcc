"""Coordinator-backed slash commands for the Workbench."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from agent.config.schema import AgentConfig
from builder.workbench import apply_coordinator_synthesis
from cli.workbench_app.collaboration_presence import (
    build_presence_snapshot_from_tasks_snapshot,
    render_presence_lines,
)
from cli.workbench_app import theme
from cli.workbench_app.checkpoint import CheckpointManager
from cli.workbench_app.commands import LocalCommand, OnDoneResult, on_done
from cli.workbench_app.runtime import remember_turn_result
from cli.workbench_app.slash import SlashContext
from deployer.versioning import ConfigVersionManager

logger = logging.getLogger(__name__)


_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "build": "Build or change an agent with coordinator-managed workers",
    "eval": "Evaluate the active agent candidate and interpret loss patterns",
    "optimize": "Optimize the agent from eval and trace evidence",
    "deploy": "Prepare canary, release, and rollback gates",
    "skills": "Find and attach build-time skills through the coordinator",
}


def build_coordinator_command(intent: str) -> LocalCommand:
    """Return a coordinator-backed slash command for one workflow intent."""
    return LocalCommand(
        name=intent,
        description=_COMMAND_DESCRIPTIONS[intent],
        handler=make_coordinator_handler(intent),
        source="builtin",
        argument_hint="[request]",
        when_to_use=f"Use when you want the coordinator-worker harness to {intent} the agent.",
        effort="medium",
        sensitive=intent in {"deploy", "skills", "optimize"},
    )


def build_ship_command() -> LocalCommand:
    """Return `/ship` as a deploy-intent alias for canary-first release flow."""
    return LocalCommand(
        name="ship",
        description="Prepare auto-review and canary shipping gates",
        handler=make_coordinator_handler("deploy"),
        source="builtin",
        argument_hint="[request]",
        when_to_use=(
            "Use when you want to apply pending review, create a release, "
            "and prepare a canary deployment."
        ),
        effort="medium",
        sensitive=True,
    )


def build_skills_coordinator_command() -> LocalCommand:
    """Return the coordinator-backed ``/skills`` command with subcommands.

    V5 splits ``/skills`` into three subcommands:

    - ``/skills gap [notes]`` — route through the coordinator with a
      ``SKILL_AUTHOR`` worker to produce a ``skill_gap_report`` artifact.
    - ``/skills generate <slug>`` — route through the coordinator to emit a
      ``generated_skill`` artifact (code + manifest).
    - ``/skills list`` — render the local ``agent_skills/store`` contents
      with no coordinator involvement.
    """
    return LocalCommand(
        name="skills",
        description="Find skill gaps, generate skills, or list the local store",
        handler=_handle_skills,
        source="builtin",
        argument_hint="[gap|generate <slug>|list]",
        when_to_use=(
            "Use ``/skills gap`` to surface missing capabilities, ``/skills "
            "generate <slug>`` to author a new skill, or ``/skills list`` "
            "to inspect existing ones."
        ),
        effort="medium",
        sensitive=True,
    )


def build_context_command() -> LocalCommand:
    """Return the `/context` command that renders prior-turn session history."""
    return LocalCommand(
        name="context",
        description="Show recent coordinator turn history carried forward",
        handler=_handle_context,
        source="builtin",
        when_to_use="Use to inspect what prior turns the coordinator is carrying into the next plan.",
        effort="low",
        sensitive=False,
    )


def build_tasks_command() -> LocalCommand:
    """Return the `/tasks` command that renders latest coordinator state."""
    return LocalCommand(
        name="tasks",
        description="Show coordinator plans, worker state, and queued work",
        handler=_handle_tasks,
        source="builtin",
        aliases=("task",),
        when_to_use="Use to inspect what coordinator workers just did or where work is blocked.",
    )


def make_coordinator_handler(intent: str) -> Callable[..., OnDoneResult]:
    """Create a slash handler that seeds a coordinator turn."""

    def _handle(ctx: SlashContext, *args: str) -> OnDoneResult:
        runtime = ctx.meta.get("agent_runtime")
        session = ctx.coordinator_session or getattr(runtime, "coordinator_session", None)
        if session is None and runtime is None:
            return on_done(
                "  Coordinator runtime is not attached to this Workbench session.",
                display="system",
            )
        message = " ".join(args).strip() or _default_message(intent)
        if session is not None:
            result = session.process_turn(
                message,
                project_id=_meta_str(ctx, "builder_project_id"),
                session_id=_meta_str(ctx, "builder_session_id"),
                command_intent=intent,
                permission_mode=_meta_str(ctx, "permission_mode"),
            )
        else:
            result = runtime.process_turn(message, ctx=ctx, command_intent=intent)
        remember_turn_result(ctx, result)
        extra_lines: list[str] = []
        if intent == "build":
            applied = _apply_build_synthesis(ctx, session, result)
            if applied:
                extra_lines.append(applied)
        transcript = list(result.transcript_lines)
        transcript.extend(extra_lines)
        return on_done(
            "\n".join(transcript),
            display="user",
            meta_messages=tuple(result.next_actions),
        )

    return _handle


def _handle_skills(ctx: SlashContext, *args: str) -> OnDoneResult:
    """Parse ``/skills`` subcommand and dispatch gap/generate/list."""
    remaining = [arg for arg in args if arg]
    subcommand = (remaining[0].lower() if remaining else "list").strip()
    rest = remaining[1:]

    if subcommand == "list":
        return _handle_skills_list(ctx)
    if subcommand == "gap":
        return _handle_skills_coordinator(
            ctx,
            subcommand="gap",
            message=" ".join(rest).strip()
            or "Analyze the latest traces and surface missing skill capabilities.",
            skills_context={"subcommand": "gap", "notes": " ".join(rest).strip()},
        )
    if subcommand == "generate":
        if not rest:
            return on_done(
                "  /skills generate requires a skill slug. Try: /skills generate <slug>",
                display="system",
            )
        slug = rest[0].strip()
        extra_notes = " ".join(rest[1:]).strip()
        message = (
            f"Generate a build-time skill for slug '{slug}'. "
            f"{extra_notes}".strip()
        )
        return _handle_skills_coordinator(
            ctx,
            subcommand="generate",
            message=message,
            skills_context={
                "subcommand": "generate",
                "slug": slug,
                "notes": extra_notes,
            },
        )
    return on_done(
        f"  Unknown /skills subcommand: {subcommand}. Use gap | generate <slug> | list.",
        display="system",
    )


def _handle_skills_list(ctx: SlashContext) -> OnDoneResult:
    """Render the local agent_skills store without touching the coordinator."""
    try:
        from agent_skills.store import AgentSkillStore
    except Exception as exc:  # pragma: no cover - defensive import
        return on_done(
            f"  /skills list unavailable: {exc}",
            display="system",
        )
    store_path = _meta_str(ctx, "agent_skills_db_path") or ".agentlab/agent_skills.db"
    try:
        store = AgentSkillStore(db_path=store_path)
        skills = store.list()
    except Exception as exc:
        return on_done(
            f"  /skills list failed: {exc}",
            display="system",
        )
    lines = [theme.heading("\n  Local skills")]
    if not skills:
        lines.append("    (no skills stored yet — use /skills generate <slug> to add one)")
    else:
        for skill in skills:
            lines.append(
                f"    • {skill.name} [{skill.skill_type}] — {skill.status} "
                f"(gap={skill.gap_id or 'n/a'})"
            )
    return on_done("\n".join(lines), display="user")


def _handle_skills_coordinator(
    ctx: SlashContext,
    *,
    subcommand: str,
    message: str,
    skills_context: dict[str, Any],
) -> OnDoneResult:
    """Route gap/generate through the coordinator with a SKILL_AUTHOR roster."""
    runtime = ctx.meta.get("agent_runtime")
    session = ctx.coordinator_session or getattr(runtime, "coordinator_session", None)
    if session is None and runtime is None:
        return on_done(
            "  Coordinator runtime is not attached to this Workbench session.",
            display="system",
        )
    if session is not None:
        result = session.process_turn(
            message,
            project_id=_meta_str(ctx, "builder_project_id"),
            session_id=_meta_str(ctx, "builder_session_id"),
            command_intent="skills",
            permission_mode=_meta_str(ctx, "permission_mode"),
            context={"skills": skills_context},
        )
    else:
        result = runtime.process_turn(message, ctx=ctx, command_intent="skills")
    remember_turn_result(ctx, result)
    return on_done(
        "\n".join(result.transcript_lines),
        display="user",
        meta_messages=tuple(result.next_actions),
    )


def _apply_build_synthesis(
    ctx: SlashContext,
    session: Any | None,
    result: Any,
) -> str | None:
    """Persist a new config version from a successful ``/build`` run.

    The coordinator runtime already snapshots the active config before
    execution starts (pre-execution auto-snapshot). This step writes the
    post-build config as a new candidate version so the operator can
    review, promote, or rewind via the existing checkpoint slash surface.

    Returns a short transcript line to append, or ``None`` when nothing
    was applied (run not completed, no version manager, or no diff).
    """
    status = getattr(result, "status", None)
    run_id = getattr(result, "run_id", None) or ""
    if status != "completed" or not run_id or session is None:
        return None
    run = _fetch_coordinator_run(session, run_id)
    if run is None:
        return None
    version_manager = _resolve_version_manager(ctx)
    if version_manager is None:
        return None
    try:
        version_manager.reload()
        active = version_manager.get_active_config()
        base_config = AgentConfig.model_validate(active) if active else AgentConfig()
        new_config = apply_coordinator_synthesis(base_config, run)
    except Exception as exc:  # defensive — never abort the turn on apply failure
        logger.warning("apply_coordinator_synthesis failed: %s", exc)
        return None
    new_dict = new_config.model_dump()
    if active and new_dict == active:
        return None
    try:
        cv = version_manager.save_version(
            config=new_dict,
            scores={"_reason": f"build:{run_id}"},
            status="candidate",
        )
    except Exception as exc:  # defensive
        logger.warning("save_version failed: %s", exc)
        return None
    return f"  Wrote candidate config v{cv.version:03d} ({cv.filename})."


def _fetch_coordinator_run(session: Any, run_id: str) -> Any | None:
    """Return the :class:`CoordinatorExecutionRun` for ``run_id`` if available."""
    store = getattr(session, "_store", None)
    if store is None:
        return None
    try:
        return store.get_coordinator_run(run_id)
    except Exception:
        return None


def _resolve_version_manager(ctx: SlashContext) -> ConfigVersionManager | None:
    """Find the :class:`ConfigVersionManager` for the active workspace."""
    cached = ctx.meta.get("version_manager")
    if isinstance(cached, ConfigVersionManager):
        return cached
    checkpoint = ctx.meta.get("checkpoint_manager")
    if isinstance(checkpoint, CheckpointManager):
        versions = getattr(checkpoint, "_versions", None)
        if isinstance(versions, ConfigVersionManager):
            ctx.meta["version_manager"] = versions
            return versions
    configs_dir = _resolve_configs_dir(ctx)
    if configs_dir is None:
        return None
    versions = ConfigVersionManager(configs_dir=str(configs_dir))
    ctx.meta["version_manager"] = versions
    return versions


def _resolve_configs_dir(ctx: SlashContext) -> Path | None:
    """Return the ``configs/`` directory for the current workspace."""
    override = ctx.meta.get("configs_dir")
    if override:
        path = Path(override)
        return path if path.exists() else None
    workspace = ctx.workspace
    root = getattr(workspace, "root", None) if workspace is not None else None
    candidates: list[Path] = []
    if root is not None:
        candidates.append(Path(root) / "configs")
    candidates.append(Path.cwd() / "configs")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _handle_context(ctx: SlashContext, *_: str) -> OnDoneResult:
    """Render the coordinator session's prior-turn history."""
    session = ctx.coordinator_session
    if session is None:
        return on_done(
            "  No coordinator session bound. Start with /build <request>.",
            display="system",
        )
    history = list(getattr(session, "_turn_history", []) or [])
    lines = [theme.heading("\n  Coordinator Context")]
    if not history:
        lines.append("    (no prior turns yet)")
        return on_done("\n".join(lines), display="user")
    lines.append(f"    Prior turns: {len(history)} (cap "
                 f"{getattr(type(session), 'MAX_TURN_HISTORY', 5)})")
    for index, entry in enumerate(history, start=1):
        intent = entry.get("intent") or "turn"
        goal = entry.get("goal") or ""
        status = entry.get("status") or "unknown"
        run_id = entry.get("run_id") or ""
        next_step = entry.get("next_step") or ""
        lines.append("")
        lines.append(f"    {index}. /{intent} [{status}] {run_id}")
        if goal:
            lines.append(f"       goal: {goal}")
        summaries = entry.get("worker_summaries") or []
        for worker in summaries[:5]:
            role = str(worker.get("worker_role") or "").replace("_", " ")
            summary = worker.get("summary") or ""
            suffix = f" - {summary}" if summary else ""
            lines.append(f"       - {role}: {worker.get('status') or ''}{suffix}")
        if next_step:
            lines.append(f"       next: {next_step}")
    return on_done("\n".join(lines), display="user")


def _handle_tasks(ctx: SlashContext, *_: str) -> OnDoneResult:
    """Render latest coordinator task state from session metadata."""
    session = ctx.coordinator_session
    if session is not None and hasattr(session, "tasks_snapshot"):
        return on_done(_render_session_tasks(session.tasks_snapshot()), display="user")
    latest = ctx.meta.get("latest_coordinator_turn")
    if latest is None:
        return on_done(
            "  No coordinator tasks yet. Start with /build <what you want to make>.",
            display="system",
        )
    lines = [theme.heading("\n  Coordinator Tasks")]
    task_id = _attr(latest, "task_id")
    plan_id = _attr(latest, "plan_id")
    run_id = _attr(latest, "run_id")
    status = _attr(latest, "status") or "unknown"
    intent = _attr(latest, "command_intent") or "turn"
    lines.append(f"    Intent: /{intent}")
    lines.append(f"    Task:   {task_id}")
    lines.append(f"    Plan:   {plan_id}")
    lines.append(f"    Run:    {run_id}")
    lines.append(f"    Status: {status}")
    worker_roles = tuple(getattr(latest, "worker_roles", ()) or ())
    if worker_roles:
        lines.append("")
        lines.append("    Workers:")
        for role in worker_roles:
            lines.append(f"      • {str(role).replace('_', ' ')}")
    active = int(getattr(latest, "active_tasks", 0) or 0)
    queued = len(ctx.meta.get("queued_inputs", []) or [])
    lines.append("")
    lines.append(f"    Active tasks: {active}")
    lines.append(f"    Queued inputs: {queued}")
    next_actions = tuple(getattr(latest, "next_actions", ()) or ())
    if next_actions:
        lines.append("")
        lines.append("    Next:")
        for action in next_actions:
            lines.append(f"      • {action}")
    return on_done("\n".join(lines), display="user")


def _render_session_tasks(snapshot: dict[str, Any]) -> str:
    """Render persisted task/run state from :class:`CoordinatorSession`."""
    lines = [theme.heading("\n  Coordinator Tasks")]
    project_id = str(snapshot.get("project_id") or "")
    session_id = str(snapshot.get("session_id") or "")
    if project_id:
        lines.append(f"    Project: {project_id}")
    if session_id:
        lines.append(f"    Session: {session_id}")
    lines.append(f"    Active runs: {int(snapshot.get('active_run_count') or 0)}")
    lines.append("")
    lines.extend(
        render_presence_lines(
            build_presence_snapshot_from_tasks_snapshot(snapshot),
            markup=False,
            indent="    ",
        )
    )
    tasks = list(snapshot.get("tasks") or [])
    if tasks:
        lines.append("")
        lines.append("    Recent tasks:")
        for task in tasks:
            intent = task.get("command_intent") or "turn"
            title = task.get("title") or task.get("task_id")
            status = task.get("status") or "unknown"
            lines.append(f"      • /{intent} {title} [{status}]")
    runs = list(snapshot.get("runs") or [])
    if runs:
        lines.append("")
        lines.append("    Recent runs:")
        for run in runs:
            lines.append(
                "      • "
                f"{run.get('run_id')} {run.get('status')} "
                f"({run.get('worker_count', 0)} workers)"
            )
    if not tasks and not runs:
        lines.append("    No coordinator tasks yet. Start with /build <what you want to make>.")
    return "\n".join(lines)


def _default_message(intent: str) -> str:
    """Return a useful default prompt when the slash command has no args."""
    defaults = {
        "build": "Build or refine the active agent.",
        "eval": "Evaluate the active agent candidate and summarize failures.",
        "optimize": "Optimize the agent from the latest eval evidence.",
        "deploy": "Prepare a canary deployment and rollback plan.",
        "skills": "Recommend build-time skills that would improve this agent.",
    }
    return defaults.get(intent, "Continue the agent build.")


def _attr(value: Any, name: str) -> str:
    """Read an attribute or mapping key as display text."""
    if isinstance(value, dict):
        raw = value.get(name)
    else:
        raw = getattr(value, name, None)
    return "" if raw is None else str(raw)


def _meta_str(ctx: SlashContext, key: str) -> str | None:
    """Read a string metadata value from the slash context."""
    value = ctx.meta.get(key)
    return str(value) if value else None


__all__ = [
    "build_context_command",
    "build_coordinator_command",
    "build_ship_command",
    "build_skills_coordinator_command",
    "build_tasks_command",
    "make_coordinator_handler",
]
