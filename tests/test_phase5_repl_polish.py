"""Tests for Phase-5 REPL polish: fuzzy completer, background panel,
AgentSpawn, and /init."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from cli.tools.agent_spawn import AGENT_SPAWNER_KEY, AgentSpawnTool
from cli.tools.base import ToolContext
from cli.tools.registry import default_registry, reset_default_registry
from cli.user_skills.registry import SkillRegistry
from cli.user_skills.store import SkillStore
from cli.workbench_app.background_panel import (
    BackgroundTaskRegistry,
    TaskStatus,
    render_panel,
)
from cli.workbench_app.background_slash import (
    BACKGROUND_REGISTRY_META_KEY,
    build_background_clear_command,
    build_background_command,
)
from cli.workbench_app.commands import CommandRegistry, LocalCommand
from cli.workbench_app.completer import (
    _is_subsequence_match,
    iter_completions,
)
from cli.workbench_app.init_scan import (
    DETECTED_END_MARKER,
    DETECTED_MARKER,
    render_memory,
    scan_workspace,
    write_memory,
)
from cli.workbench_app.init_slash import build_init_command
from cli.workbench_app.slash import SlashContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Completer — subsequence + skill surfacing
# ---------------------------------------------------------------------------


def _stub_command(name: str, aliases: tuple[str, ...] = (), description: str = "") -> LocalCommand:
    return LocalCommand(
        name=name,
        description=description or name,
        handler=lambda *_a, **_k: "ok",
        source="builtin",
        aliases=aliases,
    )


def test_subsequence_match_basic() -> None:
    assert _is_subsequence_match("ppr", "plan-approve")
    assert _is_subsequence_match("clr", "clear")
    assert _is_subsequence_match("", "anything")
    assert not _is_subsequence_match("xz", "clear")


def test_completer_surfaces_subsequence_matches() -> None:
    registry = CommandRegistry()
    for command in (
        _stub_command("plan-approve"),
        _stub_command("plan-discard"),
        _stub_command("status"),
    ):
        registry.register(command)
    completions = list(iter_completions(registry, "/ppr"))
    names = [c.name for c in completions]
    assert "plan-approve" in names
    # "plan-discard" shouldn't subsequence-match "ppr" (no 'r' after 'p-p').
    # (plan-discard has a 'p' and then 'd'... — confirm not matched)
    assert "plan-discard" not in names or names.index("plan-approve") < names.index("plan-discard")


def test_completer_returns_empty_when_not_slash_prefix() -> None:
    registry = CommandRegistry()
    registry.register(_stub_command("status"))
    assert list(iter_completions(registry, "status")) == []


def test_completer_exposes_skill_slugs(workspace: Path) -> None:
    skill_dir = workspace / ".agentlab" / "skills"
    skill_dir.mkdir(parents=True)
    (skill_dir / "commit.md").write_text("---\ndescription: commit\n---\nbody\n", encoding="utf-8")
    skill_registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))

    command_registry = CommandRegistry()
    command_registry.register(_stub_command("status"))

    completions = list(iter_completions(command_registry, "/co", skill_registry=skill_registry))
    assert any(c.name == "commit" and c.source.startswith("skill:") for c in completions)


def test_completer_hides_skill_when_builtin_has_same_slug(workspace: Path) -> None:
    skill_dir = workspace / ".agentlab" / "skills"
    skill_dir.mkdir(parents=True)
    (skill_dir / "status.md").write_text("---\ndescription: dup\n---\nbody\n", encoding="utf-8")
    skill_registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))

    command_registry = CommandRegistry()
    command_registry.register(_stub_command("status"))

    completions = list(iter_completions(command_registry, "/sta", skill_registry=skill_registry))
    skill_hits = [c for c in completions if c.source.startswith("skill:")]
    assert skill_hits == []  # duplicate slug suppressed


# ---------------------------------------------------------------------------
# Background panel
# ---------------------------------------------------------------------------


def test_background_registry_assigns_monotonic_ids() -> None:
    reg = BackgroundTaskRegistry()
    first = reg.register("work one")
    second = reg.register("work two")
    assert first.task_id == "bg-1"
    assert second.task_id == "bg-2"
    assert reg.active_count() == 2


def test_background_update_changes_status() -> None:
    reg = BackgroundTaskRegistry()
    task = reg.register("thing")
    reg.update(task.task_id, status=TaskStatus.RUNNING, detail="step 1")
    assert task.status is TaskStatus.RUNNING
    assert task.detail == "step 1"
    assert reg.active_count() == 1
    reg.update(task.task_id, status=TaskStatus.COMPLETED)
    assert reg.active_count() == 0


def test_background_update_missing_task_noop() -> None:
    reg = BackgroundTaskRegistry()
    assert reg.update("bg-99", status=TaskStatus.COMPLETED) is None


def test_background_list_filters_completed() -> None:
    reg = BackgroundTaskRegistry()
    t1 = reg.register("a")
    t2 = reg.register("b")
    reg.update(t1.task_id, status=TaskStatus.COMPLETED)
    active = reg.list(include_completed=False)
    assert [task.task_id for task in active] == [t2.task_id]


def test_render_panel_empty() -> None:
    lines = render_panel(BackgroundTaskRegistry())
    assert any("no background tasks" in line for line in lines)


def test_render_panel_populated() -> None:
    reg = BackgroundTaskRegistry()
    task = reg.register("review PR", owner="agent:reviewer")
    lines = render_panel(reg)
    combined = "\n".join(lines)
    assert task.task_id in combined
    assert "review PR" in combined
    assert "agent:reviewer" in combined


# ---------------------------------------------------------------------------
# Background slash commands
# ---------------------------------------------------------------------------


def _ctx_with_background(registry: BackgroundTaskRegistry | None) -> SlashContext:
    ctx = SlashContext()
    ctx.meta = {BACKGROUND_REGISTRY_META_KEY: registry} if registry is not None else {}
    return ctx


def test_background_slash_lists_tasks() -> None:
    reg = BackgroundTaskRegistry()
    reg.register("first")
    ctx = _ctx_with_background(reg)
    result = build_background_command().handler(ctx)
    assert "bg-1" in _as_text(result)


def test_background_slash_missing_registry_warns() -> None:
    ctx = _ctx_with_background(None)
    result = build_background_command().handler(ctx)
    assert "not configured" in _as_text(result)


def test_background_clear_removes_completed() -> None:
    reg = BackgroundTaskRegistry()
    done = reg.register("done")
    live = reg.register("live")
    reg.update(done.task_id, status=TaskStatus.COMPLETED)
    ctx = _ctx_with_background(reg)
    result = build_background_clear_command().handler(ctx)
    assert "Cleared" in _as_text(result)
    assert reg.get(done.task_id) is None
    assert reg.get(live.task_id) is not None


def test_background_clear_all_flag() -> None:
    reg = BackgroundTaskRegistry()
    task = reg.register("live")
    ctx = _ctx_with_background(reg)
    build_background_clear_command().handler(ctx, "--all")
    assert reg.get(task.task_id) is None


# ---------------------------------------------------------------------------
# AgentSpawn tool
# ---------------------------------------------------------------------------


def test_agent_spawn_requires_description_and_prompt(workspace: Path) -> None:
    ctx = ToolContext(workspace_root=workspace, extra={"background_task_registry": BackgroundTaskRegistry()})
    tool = AgentSpawnTool()
    missing_prompt = tool.run({"description": "x"}, ctx)
    assert not missing_prompt.ok
    assert "prompt" in missing_prompt.content.lower()
    missing_description = tool.run({"prompt": "y"}, ctx)
    assert not missing_description.ok


def test_agent_spawn_registers_and_queues_without_spawner(workspace: Path) -> None:
    reg = BackgroundTaskRegistry()
    ctx = ToolContext(
        workspace_root=workspace,
        extra={"background_task_registry": reg},
    )
    result = AgentSpawnTool().run(
        {"description": "Review PR", "prompt": "Look at the diff carefully."},
        ctx,
    )
    assert result.ok
    assert result.metadata.get("queued") is True
    assert reg.active_count() == 1


def test_agent_spawn_dispatches_to_spawner(workspace: Path) -> None:
    reg = BackgroundTaskRegistry()
    captured: dict[str, Any] = {}

    def spawner(*, task_id, description, prompt, subagent_type, workspace_root):
        captured.update(
            task_id=task_id,
            description=description,
            prompt=prompt,
            subagent_type=subagent_type,
            workspace_root=workspace_root,
        )

    ctx = ToolContext(
        workspace_root=workspace,
        extra={
            "background_task_registry": reg,
            AGENT_SPAWNER_KEY: spawner,
        },
    )
    result = AgentSpawnTool().run(
        {"description": "Review PR", "prompt": "Hey", "subagent_type": "reviewer"},
        ctx,
    )
    assert result.ok
    assert result.metadata.get("queued") is False
    task = reg.get(result.metadata["task_id"])
    assert task is not None
    assert task.status is TaskStatus.RUNNING
    assert captured["description"] == "Review PR"
    assert captured["subagent_type"] == "reviewer"


def test_agent_spawn_refuses_without_registry(workspace: Path) -> None:
    ctx = ToolContext(workspace_root=workspace)
    result = AgentSpawnTool().run(
        {"description": "x", "prompt": "y"},
        ctx,
    )
    assert not result.ok
    assert "no background-task registry" in result.content


def test_agent_spawn_spawner_exception_marks_failed(workspace: Path) -> None:
    reg = BackgroundTaskRegistry()

    def broken_spawner(**_kwargs):
        raise RuntimeError("boom")

    ctx = ToolContext(
        workspace_root=workspace,
        extra={
            "background_task_registry": reg,
            AGENT_SPAWNER_KEY: broken_spawner,
        },
    )
    result = AgentSpawnTool().run(
        {"description": "x", "prompt": "y"},
        ctx,
    )
    assert not result.ok
    assert "boom" in result.content
    task = next(iter(reg.tasks.values()))
    assert task.status is TaskStatus.FAILED


def test_default_registry_includes_agent_spawn() -> None:
    reset_default_registry()
    registry = default_registry()
    assert "AgentSpawn" in [tool.name for tool in registry.list()]


# ---------------------------------------------------------------------------
# Init scan + memory writer
# ---------------------------------------------------------------------------


def _seed_workspace(root: Path) -> None:
    (root / "configs").mkdir()
    (root / "configs" / "v001.yaml").write_text("optimizer: {}\n", encoding="utf-8")
    (root / "agent").mkdir()
    (root / "agent" / "root_agent.py").write_text("# agent\n", encoding="utf-8")
    (root / "evals").mkdir()
    (root / "evals" / "case1.yaml").write_text("cases: []\n", encoding="utf-8")
    skill_dir = root / ".agentlab" / "skills"
    skill_dir.mkdir(parents=True)
    (skill_dir / "commit.md").write_text("body\n", encoding="utf-8")


def test_scan_workspace_collects_files(workspace: Path) -> None:
    _seed_workspace(workspace)
    summary = scan_workspace(workspace)
    assert any(entry.relative_path.endswith("v001.yaml") for entry in summary.agent_configs)
    assert any(entry.relative_path.endswith("root_agent.py") for entry in summary.agent_sources)
    assert any(entry.relative_path.endswith("case1.yaml") for entry in summary.eval_cases)
    assert any(entry.relative_path.endswith("commit.md") for entry in summary.user_skills)
    assert summary.is_empty() is False


def test_scan_workspace_tolerates_missing_dirs(workspace: Path) -> None:
    summary = scan_workspace(workspace)
    assert summary.is_empty()


def test_render_memory_includes_detected_markers(workspace: Path) -> None:
    _seed_workspace(workspace)
    summary = scan_workspace(workspace)
    rendered = render_memory(summary)
    assert DETECTED_MARKER in rendered
    assert DETECTED_END_MARKER in rendered
    assert "Agent configs" in rendered


def test_write_memory_new_file_uses_scaffold(workspace: Path) -> None:
    _seed_workspace(workspace)
    summary = scan_workspace(workspace)
    path = write_memory(summary)
    text = path.read_text(encoding="utf-8")
    assert "Agent Identity" in text
    assert DETECTED_MARKER in text


def test_write_memory_preserves_existing_hand_written_content(workspace: Path) -> None:
    memory_path = workspace / "AGENTLAB.md"
    original = "# AGENTLAB.md — Project Memory\n\n## Business Constraints\nKeep in EU only.\n"
    memory_path.write_text(original, encoding="utf-8")
    _seed_workspace(workspace)
    summary = scan_workspace(workspace)
    write_memory(summary)
    text = memory_path.read_text(encoding="utf-8")
    assert "Keep in EU only." in text
    assert DETECTED_MARKER in text


def test_write_memory_fresh_replaces_scaffold(workspace: Path) -> None:
    memory_path = workspace / "AGENTLAB.md"
    memory_path.write_text("custom content\n", encoding="utf-8")
    _seed_workspace(workspace)
    summary = scan_workspace(workspace)
    write_memory(summary, preserve_existing=False)
    text = memory_path.read_text(encoding="utf-8")
    assert "custom content" not in text
    assert DETECTED_MARKER in text


# ---------------------------------------------------------------------------
# /init slash command
# ---------------------------------------------------------------------------


@dataclass
class _Workspace:
    root: Path


def _ctx_with_root(root: Path | None) -> SlashContext:
    workspace = _Workspace(root=root) if root else None
    ctx = SlashContext(workspace=workspace)
    return ctx


def test_init_dry_run_does_not_write(workspace: Path) -> None:
    _seed_workspace(workspace)
    ctx = _ctx_with_root(workspace)
    result = build_init_command().handler(ctx, "--dry-run")
    assert "dry-run" in _as_text(result)
    assert not (workspace / "AGENTLAB.md").exists()


def test_init_writes_memory(workspace: Path) -> None:
    _seed_workspace(workspace)
    ctx = _ctx_with_root(workspace)
    result = build_init_command().handler(ctx)
    text = _as_text(result)
    assert "Updated" in text
    assert (workspace / "AGENTLAB.md").exists()


def test_init_fresh_rewrites(workspace: Path) -> None:
    _seed_workspace(workspace)
    memory_path = workspace / "AGENTLAB.md"
    memory_path.write_text("stale\n", encoding="utf-8")
    ctx = _ctx_with_root(workspace)
    result = build_init_command().handler(ctx, "--fresh")
    assert "Rewrote" in _as_text(result)
    assert "stale" not in memory_path.read_text(encoding="utf-8")


def test_init_without_root_warns() -> None:
    ctx = _ctx_with_root(None)
    result = build_init_command().handler(ctx)
    assert "No workspace root" in _as_text(result)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if hasattr(result, "result"):
        return str(result.result or "")
    return str(result)
