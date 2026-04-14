"""Terminal rendering helpers for CLI Workbench commands.

Pure rendering functions decoupled from command logic. Ported from the
Claude branch renderer split and enhanced with Codex summary/save renderers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Iterator, Literal, Mapping

import click

from cli.terminal_renderer import render_pane, render_progress_bar


# ---------------------------------------------------------------------------
# Streaming event rendering (from Claude — 30+ event types)
# ---------------------------------------------------------------------------


def format_workbench_event(event_name: str, data: dict[str, Any]) -> str | None:
    """Format a streaming event as a single terminal line without any side effects.

    Returns ``None`` when no renderer is registered for ``event_name`` or the
    renderer suppressed output (e.g. heartbeat pings). The workbench transcript
    pane (``cli/workbench_app/transcript.py``) uses this to capture event lines
    without the implicit ``click.echo`` of :func:`render_workbench_event`.
    """
    renderer = _EVENT_RENDERERS.get(event_name)
    if renderer is None:
        return None
    return renderer(data)


def render_workbench_event(event_name: str, data: dict[str, Any]) -> str | None:
    """Render a single streaming event as a terminal line. Returns None to suppress."""
    line = format_workbench_event(event_name, data)
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
        f"[task] {d.get('title', d.get('task_id', 'task'))} ...done"
        + (f" [{d['source']}]" if d.get("source") else ""),
        fg="green",
    ),
    "message.delta": lambda _d: None,
    "artifact.updated": lambda d: f"[artifact] {(d.get('artifact') or d).get('name', 'artifact')} updated",
    "iteration.started": lambda d: click.style(
        f"[iterate] Iteration {d.get('iteration', '?')} started", fg="yellow",
    ),
    "reflect.started": lambda _d: "[reflect] Starting validation...",
    "reflect.completed": lambda _d: "[reflect] Reflection complete",
    "reflection.completed": lambda d: f"[reflect] Quality: {d.get('quality_score', '?')}",
    "validation.ready": lambda d: click.style(
        f"[validate] Validation: {d.get('status', '?')}",
        fg="green" if d.get("status") == "passed" else "yellow",
    ),
    "present.ready": lambda d: f"[present] {d.get('summary', 'Presentation ready')}",
    "build.completed": lambda d: click.style("[build] Build pass complete", fg="green"),
    "run.completed": lambda d: click.style(
        f"[done] Run complete: Draft v{d.get('version', '?')}", fg="green", bold=True,
    ),
    "run.failed": lambda d: click.style(
        f"[error] Run failed: {d.get('failure_reason', d.get('message', 'unknown'))}",
        fg="red",
    ),
    "run.cancelled": lambda d: click.style(
        f"[cancelled] Run cancelled: {d.get('cancel_reason', '')}", fg="yellow",
    ),
    "harness.metrics": lambda _d: None,
    "harness.heartbeat": lambda _d: None,
    "progress.stall": lambda d: click.style("[warn] Progress stall detected", fg="yellow"),
    "error": lambda d: click.style(
        f"[error] {d.get('message', 'Unknown error')}", fg="red",
    ),
    # Stream-json progress events (cli/progress.py). Emitted by every Click
    # command that supports --output-format stream-json, including
    # `agentlab eval run`, `optimize`, `build`, `deploy`. The renderers below
    # let the workbench transcript render those subprocess outputs inline.
    "phase_started": lambda d: click.style(
        f"[{d.get('phase', 'phase')}] starting: {d.get('message', '')}".rstrip(": "),
        fg="cyan",
    ),
    "phase_completed": lambda d: click.style(
        f"[{d.get('phase', 'phase')}] done: {d.get('message', '')}".rstrip(": "),
        fg="green",
    ),
    "artifact_written": lambda d: (
        f"[artifact] {d.get('artifact', 'artifact')}: {d.get('path', d.get('message', ''))}"
    ),
    "next_action": lambda d: click.style(
        f"[next] {d.get('message', '')}", dim=True,
    ),
    "warning": lambda d: click.style(
        f"[warning] {d.get('message', '')}", fg="yellow",
    ),
}


# ---------------------------------------------------------------------------
# Tool-call block renderer (T08)
# ---------------------------------------------------------------------------
#
# Groups ``task.started`` / ``task.progress`` / ``task.completed`` (and the
# rare ``task.failed``) events that share a ``task_id`` into a single visually
# bounded block — header, indented body, footer — modelled on Claude Code's
# tool-call transcript block. Non-task events in the stream pass through the
# ordinary :func:`format_workbench_event` renderer so the block output is a
# drop-in replacement for the streaming transcript (T16 onwards).
#
# Layout (styled)::
#
#     ⏺ <title>                    # cyan + bold
#       ⎿ <progress note 1>        # dim
#       ⎿ <progress note 2>
#       ✓ done [generation_source] # green
#
# Failed tasks close with ``✗ failed: <reason>`` in red. Events for an unknown
# task_id open a new block on the fly (defensive — if ``task.started`` was
# dropped by a reconnecting stream, we still want a header).


_BLOCK_HEADER_GLYPH = "⏺"
_BLOCK_BODY_GLYPH = "⎿"
_BLOCK_DONE_GLYPH = "✓"
_BLOCK_FAIL_GLYPH = "✗"

_BlockStatus = Literal["running", "completed", "failed"]


@dataclass(frozen=True)
class ToolCallBlockState:
    """Snapshot of one tracked task block.

    ``progress_count`` is the number of ``task.progress`` events ingested for
    the block so far; the notes themselves are not retained because the
    transcript has already echoed them as they arrived. Retaining only the
    count keeps the renderer O(1) per task regardless of how chatty progress
    is, and matches the on-screen invariant ("progress lines are immutable
    once emitted").
    """

    task_id: str
    title: str
    status: _BlockStatus = "running"
    progress_count: int = 0
    source: str | None = None
    failure_reason: str | None = None


def _task_title(data: Mapping[str, Any]) -> str:
    """Pick the best available human-facing title for a task event."""
    for key in ("title", "task", "name"):
        value = data.get(key)
        if value:
            return str(value)
    task_id = data.get("task_id")
    if task_id:
        return str(task_id)
    return "task"


def _task_key(data: Mapping[str, Any]) -> str:
    """Stable dict key for grouping events — falls back to title if no id."""
    task_id = data.get("task_id")
    if task_id:
        return str(task_id)
    return _task_title(data)


def _format_header(title: str) -> str:
    return click.style(f"{_BLOCK_HEADER_GLYPH} {title}", fg="cyan", bold=True)


def _progress_ratio(data: Mapping[str, Any]) -> float | None:
    """Extract normalized progress when events carry structured counts."""

    raw_ratio = data.get("ratio")
    if raw_ratio is None:
        raw_ratio = data.get("progress")
    if raw_ratio is not None:
        try:
            ratio = float(raw_ratio)
        except (TypeError, ValueError):
            return None
        if ratio > 1.0 and ratio <= 100.0:
            ratio = ratio / 100.0
        return min(1.0, max(0.0, ratio))

    current = data.get("current")
    total = data.get("total")
    if current is None or total is None:
        return None
    try:
        current_value = float(current)
        total_value = float(total)
    except (TypeError, ValueError):
        return None
    if total_value <= 0:
        return None
    return min(1.0, max(0.0, current_value / total_value))


def _format_progress(note: str, data: Mapping[str, Any] | None = None) -> str:
    payload = data or {}
    ratio = _progress_ratio(payload)
    suffix = ""
    if ratio is not None:
        bar = render_progress_bar(ratio, width=10)
        suffix = f"  {bar} {round(ratio * 100):>3d}%"
    return click.style(f"  {_BLOCK_BODY_GLYPH} {note}{suffix}", dim=True)


def _format_completed(source: str | None) -> str:
    suffix = f" [{source}]" if source else ""
    return click.style(f"  {_BLOCK_DONE_GLYPH} done{suffix}", fg="green")


def _format_failed(reason: str | None) -> str:
    detail = f": {reason}" if reason else ""
    return click.style(f"  {_BLOCK_FAIL_GLYPH} failed{detail}", fg="red", bold=True)


class ToolCallBlockRenderer:
    """Stateful aggregator that turns a task.* event stream into block lines.

    The renderer is intentionally synchronous and pure — every mutation is
    driven by :meth:`feed`, which returns the ordered list of terminal lines
    to emit for that single event. The enclosing transport (the transcript
    pane in T07, prompt_toolkit's streaming view in T16) owns the actual
    echo / persistence side effects.

    Multiple concurrent task_ids are tracked independently so interleaved
    events render correctly. Non-task events fall through to
    :func:`format_workbench_event` so callers can route the entire stream
    through one object.
    """

    def __init__(self) -> None:
        self._open: dict[str, ToolCallBlockState] = {}
        self._completed: list[ToolCallBlockState] = []

    # ------------------------------------------------------------------ read

    @property
    def open_blocks(self) -> Mapping[str, ToolCallBlockState]:
        """Currently-running task blocks keyed by task_id / title."""
        return dict(self._open)

    @property
    def completed_blocks(self) -> tuple[ToolCallBlockState, ...]:
        """Terminal snapshots of every block closed so far (completed+failed)."""
        return tuple(self._completed)

    # ------------------------------------------------------------------ write

    def feed(
        self, event_name: str, data: Mapping[str, Any] | None = None
    ) -> list[str]:
        """Consume one event and return the lines to emit (possibly empty).

        The return value is a list — not an iterator — so callers can easily
        ``extend`` a transcript buffer or serialize the batch. Order within
        the list is the order the lines should appear on screen (header
        before progress, progress before footer).
        """
        payload: Mapping[str, Any] = data or {}

        if event_name == "task.started":
            return self._on_started(payload)
        if event_name == "task.progress":
            return self._on_progress(payload)
        if event_name == "task.completed":
            return self._on_completed(payload)
        if event_name == "task.failed":
            return self._on_failed(payload)

        # Fall through: emit the event via the standard renderer so the
        # caller doesn't need a separate dispatcher for non-task events.
        line = format_workbench_event(event_name, dict(payload))
        return [line] if line is not None else []

    def close_all(self, *, reason: str | None = "cancelled") -> list[str]:
        """Emit failure footers for any still-open blocks.

        Useful when a run is cancelled (ctrl-c) or the stream ends abruptly
        — the open blocks would otherwise hang without visual closure. Each
        closed block is moved to ``completed_blocks`` with ``status="failed"``
        and the supplied reason.
        """
        lines: list[str] = []
        for key in list(self._open.keys()):
            state = self._open.pop(key)
            closed = replace(
                state, status="failed", failure_reason=reason
            )
            self._completed.append(closed)
            lines.append(_format_failed(reason))
        return lines

    # ------------------------------------------------------------------ handlers

    def _on_started(self, data: Mapping[str, Any]) -> list[str]:
        key = _task_key(data)
        title = _task_title(data)
        # Duplicate task.started (resume, reconnect) — don't emit a second
        # header, but refresh the title in case the second event carries a
        # nicer label than the first.
        existing = self._open.get(key)
        if existing is not None:
            self._open[key] = replace(existing, title=title)
            return []
        self._open[key] = ToolCallBlockState(task_id=key, title=title)
        return [_format_header(title)]

    def _on_progress(self, data: Mapping[str, Any]) -> list[str]:
        note = str(data.get("note") or data.get("message") or "").strip()
        if not note:
            return []
        key = _task_key(data)
        state = self._open.get(key)
        lines: list[str] = []
        if state is None:
            # Implicit open — no prior task.started for this id.
            title = _task_title(data)
            state = ToolCallBlockState(task_id=key, title=title)
            lines.append(_format_header(title))
        self._open[key] = replace(state, progress_count=state.progress_count + 1)
        lines.append(_format_progress(note, data))
        return lines

    def _on_completed(self, data: Mapping[str, Any]) -> list[str]:
        key = _task_key(data)
        source = data.get("source")
        source_str = str(source) if source else None
        state = self._open.pop(key, None)
        lines: list[str] = []
        if state is None:
            # task.completed without a prior task.started — emit a synthetic
            # header so the footer still reads as a block rather than an
            # orphan line.
            title = _task_title(data)
            lines.append(_format_header(title))
            state = ToolCallBlockState(task_id=key, title=title)
        closed = replace(state, status="completed", source=source_str)
        self._completed.append(closed)
        lines.append(_format_completed(source_str))
        return lines

    def _on_failed(self, data: Mapping[str, Any]) -> list[str]:
        key = _task_key(data)
        reason = (
            data.get("reason")
            or data.get("failure_reason")
            or data.get("message")
        )
        reason_str = str(reason) if reason else None
        state = self._open.pop(key, None)
        lines: list[str] = []
        if state is None:
            title = _task_title(data)
            lines.append(_format_header(title))
            state = ToolCallBlockState(task_id=key, title=title)
        closed = replace(
            state, status="failed", failure_reason=reason_str
        )
        self._completed.append(closed)
        lines.append(_format_failed(reason_str))
        return lines


def render_tool_call_block(
    event_stream: Iterable[tuple[str, Mapping[str, Any]]],
    *,
    close_unfinished: bool = True,
) -> Iterator[str]:
    """Render a full event stream as tool-call block lines.

    ``event_stream`` is any iterable of ``(event_name, data)`` pairs. Each
    yielded string is a single terminal line, already styled with ANSI — pass
    through ``click.unstyle`` for plain text. When the stream ends with open
    blocks, ``close_unfinished=True`` synthesizes failure footers so the
    visual output is always balanced.
    """
    renderer = ToolCallBlockRenderer()
    for name, data in event_stream:
        for line in renderer.feed(name, data):
            yield line
    if close_unfinished:
        for line in renderer.close_all(reason="stream ended"):
            yield line


# ---------------------------------------------------------------------------
# Project status dashboard (from Claude)
# ---------------------------------------------------------------------------


def render_workbench_status(snapshot: dict[str, Any], *, verbose: bool = False) -> None:
    """Render a workbench project status dashboard from a raw snapshot."""
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
    click.echo("\u2501" * 18)
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


# ---------------------------------------------------------------------------
# Candidate summary (from Codex — renders enriched _build_summary data)
# ---------------------------------------------------------------------------


def render_candidate_summary(data: dict[str, Any], *, compact: bool = False) -> None:
    """Render a terminal-native Workbench candidate view with bridge readiness."""
    bridge = data.get("bridge") if isinstance(data.get("bridge"), dict) else {}
    evaluation = bridge.get("evaluation") if isinstance(bridge.get("evaluation"), dict) else {}
    optimization = bridge.get("optimization") if isinstance(bridge.get("optimization"), dict) else {}
    agent_card = data.get("agent_card") if isinstance(data.get("agent_card"), dict) else {}
    run = data.get("run") if isinstance(data.get("run"), dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    counts = agent_card.get("counts") if isinstance(agent_card.get("counts"), dict) else {}

    click.echo(click.style("\nAgentLab Workbench", bold=True))

    overview = [
        f"Project: {data.get('project_id')} ({data.get('name')})",
        f"Target: {data.get('target')} / {data.get('environment')}",
        f"Version: Draft v{data.get('version')}",
        f"Run: {run.get('status') or 'none'}",
    ]
    if run.get("execution_mode") or run.get("provider") or run.get("model"):
        execution_label = str(run.get("execution_mode") or "unknown")
        provider_label = str(run.get("provider") or "").strip()
        model_label = str(run.get("model") or "").strip()
        provider_model = ":".join(part for part in (provider_label, model_label) if part)
        suffix = f" via {provider_model}" if provider_model else ""
        overview.append(f"Execution: {execution_label}{suffix}")
    if run.get("failure_reason"):
        overview.append(f"Reason: {run.get('failure_reason')}")
    overview.extend(
        [
            f"Agent: {agent_card.get('name')} ({agent_card.get('model')})",
            "Card: "
            f"{counts.get('tools', 0)} tool(s), "
            f"{counts.get('guardrails', 0)} guardrail(s), "
            f"{counts.get('eval_suites', 0)} eval suite(s)",
            f"Artifacts: {data.get('artifact_count')} · Turns: {data.get('turn_count')}",
            f"Validation: {summary.get('validation_status') or 'not_run'}",
        ]
    )
    for line in render_pane("Workbench Candidate", overview):
        click.echo(line)

    readiness = [
        f"Eval: {evaluation.get('label') or 'Candidate needed'}",
    ]
    if evaluation.get("description"):
        readiness.append(str(evaluation.get("description")))
    readiness.append(f"Optimize: {optimization.get('label') or 'Eval candidate not ready'}")
    if optimization.get("description") and not compact:
        readiness.append(str(optimization.get("description")))
    blockers = list(evaluation.get("blocking_reasons") or [])
    if blockers:
        readiness.append("Blockers:")
        readiness.extend(f"- {reason}" for reason in blockers)
    for line in render_pane("Readiness", readiness):
        click.echo(line)

    provenance = [
        "Workbench structural validation is not an eval result.",
        "Save materializes this candidate before Eval or Optimize can trust it.",
    ]
    latest_artifact = data.get("latest_artifact")
    if isinstance(latest_artifact, dict) and latest_artifact.get("name"):
        category = latest_artifact.get("category")
        suffix = f" ({category})" if category else ""
        provenance.append(f"Latest artifact: {latest_artifact.get('name')}{suffix}")
    for line in render_pane("Provenance", provenance):
        click.echo(line)

    next_commands = data.get("next_commands") if isinstance(data.get("next_commands"), dict) else {}
    readiness_state = evaluation.get("readiness_state")
    if readiness_state == "needs_materialization":
        next_command = next_commands.get("save")
    elif readiness_state == "ready_for_eval":
        next_command = next_commands.get("eval")
    else:
        next_command = next_commands.get("iterate")
    for line in render_pane("Next Step", [str(next_command or "agentlab workbench show")]):
        click.echo(line)


# ---------------------------------------------------------------------------
# Save result (from Codex)
# ---------------------------------------------------------------------------


def render_save_result(data: dict[str, Any]) -> None:
    """Render a clear materialization result for terminal users."""
    bridge = data.get("bridge") if isinstance(data.get("bridge"), dict) else {}
    evaluation = bridge.get("evaluation") if isinstance(bridge.get("evaluation"), dict) else {}
    optimization = bridge.get("optimization") if isinstance(bridge.get("optimization"), dict) else {}
    save_result = data.get("save_result") if isinstance(data.get("save_result"), dict) else {}
    click.echo(click.style("\nWorkbench candidate saved", bold=True))
    click.echo("\u2501" * 26)
    click.echo(f"  Config: {save_result.get('config_path')}")
    click.echo(f"  Evals:  {save_result.get('eval_cases_path')}")
    click.echo(f"  Eval:   {evaluation.get('label')}")
    click.echo(f"  Next:   {data.get('next', {}).get('start_eval_command')}")
    click.echo(f"  Optimize waits for Eval: {optimization.get('label')}")
    click.echo("")
    click.echo("This saved candidate is now the active local config for Eval.")


# ---------------------------------------------------------------------------
# Bridge readiness (from Claude)
# ---------------------------------------------------------------------------


def render_bridge_status(bridge: dict[str, Any]) -> None:
    """Render the Eval/Optimize handoff readiness."""
    candidate = bridge.get("candidate") or {}
    evaluation = bridge.get("evaluation") or {}
    optimization = bridge.get("optimization") or {}

    click.echo(click.style("\nWorkbench Bridge Status", bold=True))
    click.echo("\u2501" * 24)

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


# ---------------------------------------------------------------------------
# Project list (from Claude)
# ---------------------------------------------------------------------------


def render_project_list(projects: list[dict[str, Any]]) -> None:
    """Render a table of workbench projects."""
    if not projects:
        click.echo("No workbench projects found.")
        click.echo(click.style(
            '  Create one: agentlab workbench create "your brief"', fg="green",
        ))
        return

    click.echo(click.style("\nWorkbench Projects", bold=True))
    click.echo("\u2501" * 19)
    dash = "\u2500"
    click.echo(f"  {'ID':<20s}  {'Name':<30s}  {'Version':>8s}  {'Target':<10s}  Status")
    click.echo(f"  {dash * 20}  {dash * 30}  {dash * 8}  {dash * 10}  {dash * 12}")
    for proj in projects:
        pid = proj.get("project_id", "?")[:20]
        name = (proj.get("name") or "Untitled")[:30]
        ver = str(proj.get("version", 0))
        tgt = proj.get("target", "portable")[:10]
        bs = proj.get("build_status", "idle")
        click.echo(f"  {pid:<20s}  {name:<30s}  {ver:>8s}  {tgt:<10s}  {bs}")


# ---------------------------------------------------------------------------
# Validation checks (from Claude)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Plan display (from Claude)
# ---------------------------------------------------------------------------


def render_plan(plan: dict[str, Any]) -> None:
    """Render a change plan summary."""
    click.echo(click.style("\nChange Plan", bold=True))
    click.echo("\u2501" * 12)
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _suggest_next_step(project: dict[str, Any]) -> str:
    """Determine the suggested next CLI command."""
    build_status = project.get("build_status", "idle")
    last_test = project.get("last_test")
    has_model = bool((project.get("model") or {}).get("agents"))

    if build_status == "idle" and not has_model:
        return 'agentlab workbench build "describe your agent"'
    if build_status in ("running", "reflecting", "presenting"):
        return "agentlab workbench status  (build in progress)"
    if build_status == "failed":
        return 'agentlab workbench build "try again with different brief"'
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
