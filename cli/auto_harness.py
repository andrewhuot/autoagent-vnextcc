"""Claude-style terminal harness primitives for long-running AgentLab work.

The harness keeps the CLI readable while work is active: a compact transcript,
one active status line, a task checklist, queued input, and visible permission
mode.  It is intentionally UI-toolkit agnostic so command implementations can
emit events without knowing whether the caller is using a live TTY, classic
text output, or structured output.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Literal, TypeAlias

import click

from cli.permissions import DEFAULT_PERMISSION_MODE, PERMISSION_MODES


CliUiMode = Literal["auto", "claude", "classic"]
QueuePriority = Literal["now", "next", "later"]
TaskState = Literal["pending", "active", "completed", "failed"]
FormattedText: TypeAlias = list[tuple[str, str]]

_QUEUE_PRIORITY_ORDER: dict[str, int] = {"now": 0, "next": 1, "later": 2}
_CLAUDE_PROMPT = "›"
_CLAUDE_PERMISSION_SYMBOL = "⏵"
_CLAUDE_RULE = "─"
_CLAUDE_SEPARATOR = " · "
_PERMISSION_LABELS: dict[str, str] = {
    "plan": "plan mode",
    "default": "default permissions",
    "acceptEdits": "accept edits",
    "dontAsk": "don't ask",
    "bypass": "bypass permissions",
}


@dataclass(slots=True)
class HarnessEvent:
    """Canonical event envelope used by Claude-style interactive rendering."""

    event: str
    message: str | None = None
    task_id: str | None = None
    task: str | None = None
    stage: str | None = None
    tool: str | None = None
    tokens: int | None = None
    cost_usd: float | None = None
    thinking: bool | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True)
class HarnessTask:
    """Render-ready task row for the compact checklist."""

    task_id: str
    title: str
    state: TaskState = "pending"
    detail: str | None = None
    updated_at: float = field(default_factory=time.monotonic)


@dataclass(slots=True)
class QueuedInput:
    """A user message submitted while a model or command turn is still active."""

    text: str
    priority: QueuePriority = "next"
    created_at: float = field(default_factory=time.monotonic)
    sequence: int = 0


@dataclass(slots=True)
class HarnessSnapshot:
    """Immutable-ish state prepared for a terminal renderer."""

    transcript: list[str] = field(default_factory=list)
    tasks: list[HarnessTask] = field(default_factory=list)
    queued_inputs: list[QueuedInput] = field(default_factory=list)
    active_label: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    tokens: int | None = None
    cost_usd: float | None = None
    thinking: bool = False
    permission_mode: str = DEFAULT_PERMISSION_MODE
    agent_lines: list[str] = field(default_factory=list)
    show_manage_panel: bool = False


class MessageQueue:
    """Priority queue for user input captured while the harness is busy."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._items: list[QueuedInput] = []
        self._sequence = 0

    def add(self, text: str, *, priority: QueuePriority = "next") -> QueuedInput:
        """Queue text for the next safe execution point."""
        normalized = text.strip()
        if priority not in _QUEUE_PRIORITY_ORDER:
            raise ValueError(f"Unsupported queue priority: {priority}")
        self._sequence += 1
        item = QueuedInput(
            text=normalized,
            priority=priority,
            created_at=self._clock(),
            sequence=self._sequence,
        )
        self._items.append(item)
        self._items.sort(
            key=lambda queued: (
                _QUEUE_PRIORITY_ORDER[queued.priority],
                queued.sequence,
            )
        )
        return item

    def items(self) -> list[QueuedInput]:
        """Return queued items in execution order."""
        return list(self._items)

    def pop_next(self) -> QueuedInput:
        """Remove and return the highest-priority queued item."""
        if not self._items:
            raise IndexError("No queued input is available.")
        return self._items.pop(0)

    def clear(self) -> None:
        """Remove all queued input."""
        self._items.clear()


@dataclass(slots=True)
class PermissionFooter:
    """Visible permission-mode footer plus Claude-style cycling behavior.

    This mirrors Claude Code's `PromptInputFooterLeftSide`: permission mode is
    always first, live background work follows it, and the manage hint appears
    when there is work to inspect.
    """

    mode: str = DEFAULT_PERMISSION_MODE

    def __post_init__(self) -> None:
        if self.mode not in PERMISSION_MODES:
            self.mode = DEFAULT_PERMISSION_MODE

    def cycle(self) -> "PermissionFooter":
        """Advance to the next permission mode and return this footer."""
        index = PERMISSION_MODES.index(self.mode)
        self.mode = PERMISSION_MODES[(index + 1) % len(PERMISSION_MODES)]
        return self

    def render(self) -> str:
        """Render the footer text shown at the bottom of the live prompt."""
        return self.render_status()

    def render_status(
        self,
        background_status: str | None = None,
        *,
        show_manage_hint: bool | None = None,
    ) -> str:
        """Render the Claude-style permission and background activity footer."""
        label = _PERMISSION_LABELS.get(self.mode, self.mode)
        parts = [f"{_CLAUDE_PERMISSION_SYMBOL} {label} on"]
        if background_status:
            parts.append(background_status)
        manage_hint = bool(background_status) if show_manage_hint is None else show_manage_hint
        if manage_hint:
            parts.append("↓ to manage")
        elif not background_status:
            parts[0] = f"{parts[0]} (shift+tab to cycle)"
        return _CLAUDE_SEPARATOR.join(parts)

    def render_toolbar(
        self,
        snapshot: HarnessSnapshot | None = None,
        *,
        width: int | None = None,
    ) -> str:
        """Render the two-line bottom toolbar used under the live prompt."""
        fragments = self.render_toolbar_fragments(snapshot, width=width)
        return "".join(text for _style, text in fragments)

    def render_toolbar_fragments(
        self,
        snapshot: HarnessSnapshot | None = None,
        *,
        width: int | None = None,
    ) -> FormattedText:
        """Render styled prompt_toolkit fragments for the live footer."""
        terminal_width = max(1, width or _terminal_width())
        background = _background_status(snapshot) if snapshot is not None else None
        permission_style = (
            "class:permission.danger"
            if self.mode in {"bypass", "dontAsk"}
            else "class:permission.normal"
        )
        label = _PERMISSION_LABELS.get(self.mode, self.mode)
        fragments: FormattedText = [
            ("class:prompt.border", _CLAUDE_RULE * terminal_width),
            ("", "\n"),
            (permission_style, f"{_CLAUDE_PERMISSION_SYMBOL} {label} on"),
        ]
        if background:
            fragments.extend(
                [
                    ("class:separator", _CLAUDE_SEPARATOR),
                    ("class:activity", background),
                    ("class:separator", _CLAUDE_SEPARATOR),
                    ("class:hint", "↓ to manage"),
                ]
            )
        else:
            fragments.append(("class:hint", " (shift+tab to cycle)"))
        if snapshot is not None and snapshot.show_manage_panel:
            fragments.extend(_manage_panel_fragments(snapshot))
        return fragments


class ToolOutputSummarizer:
    """Collapse verbose command output into a short Bash-style progress block."""

    def __init__(self, *, max_tail_lines: int = 5) -> None:
        self.max_tail_lines = max(1, max_tail_lines)

    def summarize(
        self,
        *,
        command: str,
        output: str,
        exit_code: int | None,
        elapsed_seconds: float,
        expanded: bool = False,
    ) -> str:
        """Return command, duration, output count, status, and the latest tail."""
        lines = output.splitlines()
        status = "running" if exit_code is None else f"exit {exit_code}"
        if expanded or len(lines) <= self.max_tail_lines:
            visible = lines
            scope = f"showing all {len(lines)} lines"
        else:
            visible = lines[-self.max_tail_lines :]
            scope = f"showing last {len(visible)} of {len(lines)} lines"
        header = (
            f"● Bash {command} "
            f"({elapsed_seconds:.1f}s, {len(lines)} lines, {status}; {scope})"
        )
        if not visible:
            return header
        return "\n".join([header, *[f"  {line}" for line in visible]])


class HarnessSession:
    """State reducer for a Claude-style AgentLab terminal session."""

    def __init__(
        self,
        *,
        permission_mode: str = DEFAULT_PERMISSION_MODE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._started_at = clock()
        self._transcript: list[str] = []
        self._tasks: dict[str, HarnessTask] = {}
        self._task_order: list[str] = []
        self._queue = MessageQueue(clock=clock)
        self._footer = PermissionFooter(permission_mode)
        self._active_label: str | None = None
        self._tokens: int | None = None
        self._cost_usd: float | None = None
        self._thinking = False
        self._agent_lines: list[str] = []
        self._show_manage_panel = False
        self.events: list[HarnessEvent] = []

    @property
    def queue(self) -> MessageQueue:
        """Return the live queued-input manager."""
        return self._queue

    @property
    def permission_mode(self) -> str:
        """Return the visible permission mode for this session."""
        return self._footer.mode

    def emit(self, event: HarnessEvent) -> HarnessSnapshot:
        """Apply an event and return the new render snapshot."""
        self.events.append(event)
        name = event.event

        if name in {"session.started", "message.delta"} and event.message:
            self._transcript.append(event.message)
        elif name == "stage.started":
            self._active_label = event.message or event.stage or "Working"
            if event.message:
                self._transcript.append(event.message)
        elif name == "stage.completed":
            self._active_label = None
            if event.message:
                self._transcript.append(event.message)
        elif name == "plan.ready":
            self._apply_plan(event.payload.get("tasks", []))
        elif name in {"task.started", "task.progress"}:
            self._upsert_task(event, state="active" if name == "task.started" else None)
        elif name == "task.completed":
            self._upsert_task(event, state="completed")
        elif name == "task.failed":
            self._upsert_task(event, state="failed")
        elif name == "tool.started":
            label = event.message or event.tool or "Running tool"
            self._active_label = label
            self._transcript.append(label)
        elif name == "tool.completed":
            rendered = event.message or self._tool_summary_from_payload(event.payload)
            if rendered:
                self._transcript.append(rendered)
        elif name == "artifact.updated" and event.message:
            self._transcript.append(event.message)
        elif name == "metrics.updated":
            self._apply_metrics(event)
        elif name == "permission.mode_changed":
            next_mode = event.message or str(event.payload.get("mode", ""))
            if next_mode in PERMISSION_MODES:
                self._footer.mode = next_mode
        elif name == "input.queued" and event.message:
            priority = event.payload.get("priority", "next")
            self._queue.add(str(event.message), priority=priority)
        elif name == "agent.progress":
            line = event.message or self._agent_line_from_payload(event.payload)
            if line:
                self._agent_lines.append(line)
                self._agent_lines = self._agent_lines[-5:]
        elif name == "manage.toggled":
            if "visible" in event.payload:
                self._show_manage_panel = bool(event.payload["visible"])
            else:
                self._show_manage_panel = not self._show_manage_panel
        elif name in {"warning", "error"} and event.message:
            prefix = "Warning" if name == "warning" else "Error"
            self._transcript.append(f"{prefix}: {event.message}")

        self._apply_metrics(event)
        return self.snapshot()

    def snapshot(self) -> HarnessSnapshot:
        """Return render-ready state for the current terminal frame."""
        return HarnessSnapshot(
            transcript=list(self._transcript[-20:]),
            tasks=[self._tasks[task_id] for task_id in self._task_order],
            queued_inputs=self._queue.items(),
            active_label=self._active_label,
            started_at=self._started_at,
            tokens=self._tokens,
            cost_usd=self._cost_usd,
            thinking=self._thinking,
            permission_mode=self._footer.mode,
            agent_lines=list(self._agent_lines),
            show_manage_panel=self._show_manage_panel,
        )

    def _upsert_task(self, event: HarnessEvent, *, state: TaskState | None) -> None:
        task_id = event.task_id or event.task or event.message
        if not task_id:
            return
        title = event.task or event.message
        if task_id not in self._tasks:
            self._task_order.append(task_id)
            self._tasks[task_id] = HarnessTask(task_id=task_id, title=title or task_id)
        task = self._tasks[task_id]
        if title:
            task.title = title
        if state is not None:
            if state == "active":
                self._mark_other_active_tasks_pending(task_id)
            task.state = state
        task.detail = event.payload.get("detail") if event.payload else task.detail
        task.updated_at = self._clock()

    def _apply_plan(self, raw_tasks: Any) -> None:
        if not isinstance(raw_tasks, list):
            return
        for index, raw_task in enumerate(raw_tasks):
            if isinstance(raw_task, dict):
                task_id = str(raw_task.get("id") or raw_task.get("task_id") or f"task-{index}")
                title = str(raw_task.get("title") or raw_task.get("task") or task_id)
            else:
                task_id = f"task-{index}"
                title = str(raw_task)
            if task_id not in self._tasks:
                self._task_order.append(task_id)
                self._tasks[task_id] = HarnessTask(task_id=task_id, title=title)
            else:
                self._tasks[task_id].title = title

    def _mark_other_active_tasks_pending(self, active_task_id: str) -> None:
        for task_id, task in self._tasks.items():
            if task_id != active_task_id and task.state == "active":
                task.state = "pending"

    def _apply_metrics(self, event: HarnessEvent) -> None:
        if event.tokens is not None:
            self._tokens = event.tokens
        if event.cost_usd is not None:
            self._cost_usd = event.cost_usd
        if event.thinking is not None:
            self._thinking = bool(event.thinking)

    @staticmethod
    def _agent_line_from_payload(payload: dict[str, Any]) -> str | None:
        name = payload.get("name")
        status = payload.get("status")
        last_action = payload.get("last_action") or payload.get("tool")
        if not name:
            return None
        pieces = [str(name)]
        if status:
            pieces.append(str(status))
        if last_action:
            pieces.append(str(last_action))
        return " | ".join(pieces)

    @staticmethod
    def _tool_summary_from_payload(payload: dict[str, Any]) -> str | None:
        command = payload.get("command") or payload.get("label") or payload.get("tool")
        if not command:
            return None
        return ToolOutputSummarizer(
            max_tail_lines=int(payload.get("max_tail_lines") or 5)
        ).summarize(
            command=str(command),
            output=str(payload.get("output") or ""),
            exit_code=(
                int(payload["exit_code"]) if payload.get("exit_code") is not None else None
            ),
            elapsed_seconds=float(payload.get("elapsed_seconds") or 0.0),
            expanded=bool(payload.get("expanded")),
        )


class HarnessRenderer:
    """Render a harness snapshot into compact terminal text."""

    def __init__(
        self,
        *,
        width: int | None = None,
        max_tasks: int = 6,
        include_footer: bool = True,
        styled: bool = False,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.width = max(40, width or _terminal_width())
        self.max_tasks = max(1, max_tasks)
        self.include_footer = include_footer
        self.styled = styled
        self._now = now

    def render(self, snapshot: HarnessSnapshot) -> str:
        """Render the visible Claude-style frame for tests or classic printing."""
        lines: list[str] = []
        if snapshot.transcript:
            for entry in snapshot.transcript[-6:]:
                lines.extend(
                    self._transcript_line(line) for line in entry.splitlines()
                )

        active = self._active_line(snapshot)
        if active:
            if lines:
                lines.append("")
            lines.append(self._fit(active))

        task_lines = list(self._render_tasks(snapshot.tasks))
        lines.extend(task_lines)

        for agent_line in snapshot.agent_lines:
            lines.append(self._fit(f"  • {agent_line}"))

        if snapshot.queued_inputs:
            lines.append("")
            lines.extend(self._render_queued_inputs(snapshot.queued_inputs))

        if snapshot.show_manage_panel:
            if lines:
                lines.append("")
            lines.extend(self._render_manage_panel(snapshot))

        if self.include_footer:
            lines.append("")
            lines.append(self.prompt_rule())
            lines.append(
                self._fit(
                    PermissionFooter(snapshot.permission_mode).render_status(
                        _background_status(snapshot)
                    )
                )
            )
        return "\n".join(lines)

    def prompt_message(self) -> str:
        """Return the Claude-style prompt marker used by prompt_toolkit."""
        return f"{_CLAUDE_PROMPT} "

    def prompt_rule(self) -> str:
        """Return the border line below the live prompt input region."""
        return _CLAUDE_RULE * self.width

    def _active_line(self, snapshot: HarnessSnapshot) -> str | None:
        if not snapshot.active_label:
            return None
        elapsed = max(0.0, self._now() - snapshot.started_at)
        meta = [_format_elapsed(elapsed)]
        if snapshot.tokens is not None:
            meta.append(_format_tokens(snapshot.tokens))
        if snapshot.cost_usd is not None:
            meta.append(f"${snapshot.cost_usd:.4f}")
        if snapshot.thinking:
            meta.append("thinking")
        return f"✱ {snapshot.active_label} ({' · '.join(meta)})"

    def _render_tasks(self, tasks: list[HarnessTask]) -> Iterable[str]:
        visible = self._visible_tasks(tasks)
        for collapsed_count, task in visible:
            if collapsed_count:
                plural = "tasks" if collapsed_count != 1 else "task"
                yield f"  ... {collapsed_count} older completed {plural}"
            if task is None:
                continue
            marker = {"completed": "✓", "active": "■", "failed": "✗", "pending": "□"}[
                task.state
            ]
            yield self._fit(f"  {marker} {task.title}")

    def _render_queued_inputs(self, queued_inputs: list[QueuedInput]) -> Iterable[str]:
        visible = queued_inputs[-3:]
        hidden = len(queued_inputs) - len(visible)
        if hidden > 0:
            plural = "commands" if hidden != 1 else "command"
            yield self._fit(f"  ... {hidden} queued {plural}")
        for queued in visible:
            yield self._fit(self._maybe_style(f"{_CLAUDE_PROMPT} {queued.text}", "user"))

    def _render_manage_panel(self, snapshot: HarnessSnapshot) -> Iterable[str]:
        yield self._fit(self._maybe_style("Shells and tasks", "panel_title"))
        if snapshot.active_label:
            yield self._fit(f"  Active: {snapshot.active_label}")
        for task in snapshot.tasks:
            if task.state in {"active", "failed"}:
                yield self._fit(f"  Task: {task.title} [{task.state}]")
        for agent_line in snapshot.agent_lines:
            yield self._fit(f"  Agent: {agent_line}")
        for queued in snapshot.queued_inputs[:3]:
            yield self._fit(f"  Queued: {queued.text}")

    def _visible_tasks(
        self, tasks: list[HarnessTask]
    ) -> list[tuple[int, HarnessTask | None]]:
        if len(tasks) <= self.max_tasks:
            return [(0, task) for task in tasks]

        active_index = next(
            (index for index, task in enumerate(tasks) if task.state == "active"),
            len(tasks) - 1,
        )
        start = max(0, active_index - 1)
        end = min(len(tasks), start + self.max_tasks)
        start = max(0, end - self.max_tasks)
        selected = tasks[start:end]
        collapsed_completed = sum(1 for task in tasks[:start] if task.state == "completed")
        rows: list[tuple[int, HarnessTask | None]] = []
        if collapsed_completed:
            rows.append((collapsed_completed, None))
        rows.extend((0, task) for task in selected)
        return rows

    def _fit(self, text: str) -> str:
        if len(text) <= self.width:
            return text
        if self.width <= 1:
            return text[: self.width]
        return text[: self.width - 3] + "..."

    def _transcript_line(self, text: str) -> str:
        fitted = self._fit(text)
        if text.startswith(_CLAUDE_PROMPT):
            return self._maybe_style(fitted, "user")
        if text.startswith("● Bash"):
            return self._maybe_style(fitted, "tool")
        return self._maybe_style(fitted, "transcript")

    def _maybe_style(self, text: str, role: str) -> str:
        if not self.styled:
            return text
        if role == "user":
            return click.style(text, fg="white", bg="bright_black")
        if role == "tool":
            return click.style(text, fg="green")
        if role == "panel_title":
            return click.style(text, fg="cyan", bold=True)
        return click.style(text, fg="bright_black")


def resolve_cli_ui(
    output_format: str,
    *,
    requested_ui: str | None = None,
    is_tty: bool | None = None,
    is_ci: bool | None = None,
) -> str:
    """Resolve the UI mode while keeping structured output non-interactive."""
    if output_format != "text":
        return "classic"

    raw_requested = requested_ui or os.environ.get("AGENTLAB_CLI_UI") or "auto"
    requested = raw_requested.strip().lower()
    if requested == "harness":
        requested = "claude"
    if requested not in {"auto", "claude", "classic"}:
        raise click.ClickException("Unsupported UI mode. Choose auto, claude, or classic.")
    if requested == "classic":
        return requested

    tty = _stdout_is_tty() if is_tty is None else is_tty
    ci = bool(os.environ.get("CI")) if is_ci is None else is_ci
    if requested == "claude":
        if tty and not ci:
            return "claude"
        raise click.ClickException(
            "Claude UI requires an interactive terminal. Use --ui auto or --ui classic "
            "for non-TTY runs."
        )
    return "claude" if tty and not ci else "classic"


def workbench_event_to_harness_event(
    event_name: str,
    data: dict[str, Any],
) -> HarnessEvent | None:
    """Adapt existing Workbench stream events into the shared harness schema."""
    if event_name == "plan.ready":
        raw_tasks = data.get("tasks") or data.get("children") or []
        tasks: list[dict[str, str]] = []
        if isinstance(raw_tasks, list):
            for index, raw_task in enumerate(raw_tasks):
                if isinstance(raw_task, dict):
                    task_id = str(raw_task.get("id") or raw_task.get("task_id") or f"task-{index}")
                    title = str(raw_task.get("title") or raw_task.get("task") or task_id)
                else:
                    task_id = f"task-{index}"
                    title = str(raw_task)
                tasks.append({"id": task_id, "title": title})
        return HarnessEvent("plan.ready", payload={"tasks": tasks})

    if event_name in {"task.started", "task.progress", "task.completed"}:
        task_id = str(data.get("task_id") or data.get("id") or data.get("title") or "task")
        title = str(data.get("title") or data.get("task") or task_id)
        return HarnessEvent(event_name, task_id=task_id, task=title, message=data.get("message"))

    if event_name == "message.delta":
        text = str(data.get("text") or data.get("delta") or data.get("message") or "")
        return HarnessEvent("message.delta", message=text) if text else None

    if event_name == "artifact.updated":
        artifact = data.get("artifact") if isinstance(data.get("artifact"), dict) else data
        artifact_name = str(artifact.get("name") or "artifact")
        return HarnessEvent("artifact.updated", message=f"{artifact_name} updated")

    if event_name in {"tool.started", "tool.completed"}:
        return HarnessEvent(
            event_name,
            message=str(data.get("message")) if data.get("message") else None,
            tool=str(data.get("tool") or data.get("command") or ""),
            payload=dict(data),
        )

    if event_name == "harness.metrics":
        tokens = data.get("tokens") or data.get("token_count")
        cost = data.get("cost_usd")
        return HarnessEvent(
            "metrics.updated",
            tokens=int(tokens) if tokens is not None else None,
            cost_usd=float(cost) if cost is not None else None,
            thinking=bool(data.get("thinking")) if "thinking" in data else None,
        )

    if event_name in {"run.failed", "error"}:
        return HarnessEvent(
            "error",
            message=str(data.get("message") or data.get("failure_reason") or "Workbench error"),
        )

    if event_name in {"run.completed", "build.completed"}:
        return HarnessEvent(
            "stage.completed",
            message=str(data.get("summary") or data.get("message") or "Workbench run complete"),
        )

    return None


def _terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 100


def _stdout_is_tty() -> bool:
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    remainder = int(seconds % 60)
    return f"{minutes}m {remainder}s"


def _format_tokens(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}m tokens"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}k tokens"
    return f"{tokens} tokens"


def _background_status(snapshot: HarnessSnapshot | None) -> str | None:
    """Summarize live work for the Claude-style footer activity segment."""
    if snapshot is None:
        return None

    parts: list[str] = []
    active_label = (snapshot.active_label or "").strip().lower()
    has_active_work = bool(snapshot.active_label) and active_label != "waiting for input"
    if has_active_work:
        parts.append("1 shell")

    monitored_tasks = [
        task for task in snapshot.tasks if task.state in {"active", "pending", "failed"}
    ]
    if has_active_work and monitored_tasks:
        parts.append("1 monitor")

    if snapshot.agent_lines:
        count = len(snapshot.agent_lines)
        noun = "agent" if count == 1 else "agents"
        parts.append(f"{count} {noun}")

    if snapshot.queued_inputs:
        count = len(snapshot.queued_inputs)
        noun = "queued" if count == 1 else "queued"
        parts.append(f"{count} {noun}")

    return ", ".join(parts) if parts else None


def _manage_panel_fragments(snapshot: HarnessSnapshot) -> FormattedText:
    """Return formatted rows for the bottom manage panel."""
    fragments: FormattedText = [
        ("", "\n"),
        ("class:panel.title", "Shells and tasks"),
    ]
    if snapshot.active_label:
        fragments.extend(
            [("", "\n"), ("class:panel.row", f"  Active: {snapshot.active_label}")]
        )
    for task in snapshot.tasks:
        if task.state in {"active", "failed"}:
            fragments.extend(
                [
                    ("", "\n"),
                    ("class:panel.row", f"  Task: {task.title} [{task.state}]"),
                ]
            )
    for agent_line in snapshot.agent_lines:
        fragments.extend(
            [("", "\n"), ("class:panel.row", f"  Agent: {agent_line}")]
        )
    for queued in snapshot.queued_inputs[:3]:
        fragments.extend(
            [("", "\n"), ("class:panel.row", f"  Queued: {queued.text}")]
        )
    return fragments
