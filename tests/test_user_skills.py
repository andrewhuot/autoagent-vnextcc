"""Tests for the Phase-4 user-skill loader, dispatch, and allowlist overlay."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cli.permissions import PermissionManager
from cli.tools.base import ToolContext
from cli.tools.file_edit import FileEditTool
from cli.tools.file_read import FileReadTool
from cli.user_skills.allowlist import scoped_allowlist
from cli.user_skills.registry import SkillRegistry, default_skill_store
from cli.user_skills.slash import (
    SKILL_REGISTRY_META_KEY,
    all_skill_commands,
    build_skill_command,
    build_skill_list_command,
    build_skill_reload_command,
)
from cli.user_skills.store import SkillStore, parse_skill_file
from cli.user_skills.types import Skill, SkillSource
from cli.workbench_app.commands import CommandRegistry
from cli.workbench_app.slash import SlashContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


@pytest.fixture
def user_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def _write_skill(root: Path, filename: str, body: str) -> Path:
    skill_dir = root / ".agentlab" / "skills"
    skill_dir.mkdir(parents=True, exist_ok=True)
    target = skill_dir / filename
    target.write_text(body, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def test_parse_skill_file_with_full_frontmatter(workspace: Path) -> None:
    path = _write_skill(
        workspace,
        "commit.md",
        """---
name: Commit Helper
description: Help the user write a commit message
allowed-tools: [Bash, FileRead]
---

Write a commit message for the staged changes.
$ARGUMENTS
""",
    )
    skill = parse_skill_file(path, source=SkillSource.WORKSPACE)
    assert skill.slug == "commit-helper"
    assert skill.name == "Commit Helper"
    assert skill.description == "Help the user write a commit message"
    assert skill.allowed_tools == ("Bash", "FileRead")
    assert skill.body.strip().startswith("Write a commit message")
    assert skill.source is SkillSource.WORKSPACE


def test_parse_skill_file_accepts_inline_list(workspace: Path) -> None:
    path = _write_skill(
        workspace,
        "inline.md",
        """---
description: inline list style
allowed-tools: FileRead, Grep, Glob
---
body
""",
    )
    skill = parse_skill_file(path, source=SkillSource.WORKSPACE)
    assert skill.allowed_tools == ("FileRead", "Grep", "Glob")


def test_parse_skill_file_without_frontmatter_treats_file_as_body(workspace: Path) -> None:
    path = _write_skill(workspace, "plain.md", "Just a body.\n")
    skill = parse_skill_file(path, source=SkillSource.WORKSPACE)
    assert skill.slug == "plain"
    assert skill.name == "plain"
    assert skill.description == ""
    assert skill.allowed_tools == ()
    assert "Just a body." in skill.body


def test_parse_skill_file_preserves_unknown_keys(workspace: Path) -> None:
    path = _write_skill(
        workspace,
        "meta.md",
        """---
description: Extra metadata
owner: andrew
priority: high
---
body
""",
    )
    skill = parse_skill_file(path, source=SkillSource.WORKSPACE)
    assert skill.extra == {"owner": "andrew", "priority": "high"}


def test_parse_skill_file_malformed_frontmatter_raises(workspace: Path) -> None:
    path = _write_skill(
        workspace,
        "bad.md",
        """---
bad frontmatter line
---
""",
    )
    with pytest.raises(ValueError):
        parse_skill_file(path, source=SkillSource.WORKSPACE)


def test_skill_render_prompt_substitution() -> None:
    skill = Skill(
        slug="echo",
        name="echo",
        description="",
        body="Summarise this: $ARGUMENTS",
    )
    assert skill.render_prompt("hello") == "Summarise this: hello"
    # Without arguments and without placeholder the body is returned verbatim.
    verbatim = Skill(slug="verbatim", name="v", description="", body="Do the thing")
    assert verbatim.render_prompt("") == "Do the thing"
    # Without placeholder but with arguments we still surface the args.
    assert verbatim.render_prompt("now") == "Do the thing\n\nUser arguments: now"


# ---------------------------------------------------------------------------
# SkillStore precedence
# ---------------------------------------------------------------------------


def test_workspace_skill_overrides_user_home(workspace: Path, user_home: Path) -> None:
    _write_skill(user_home, "commit.md", "---\nname: user-commit\n---\nuser body\n")
    _write_skill(workspace, "commit.md", "---\nname: ws-commit\n---\nworkspace body\n")
    store = SkillStore(workspace_root=workspace, user_home=user_home)
    skill = store.get("ws-commit")
    assert skill is not None
    assert skill.source is SkillSource.WORKSPACE
    assert "workspace body" in skill.body


def test_skill_store_warns_on_bad_file(workspace: Path) -> None:
    _write_skill(workspace, "bad.md", "---\nbroken\n---\n")
    store = SkillStore(workspace_root=workspace, user_home=None)
    assert store.list() == []
    assert len(store.warnings) == 1


def test_default_skill_store_respects_injected_home(workspace: Path, user_home: Path) -> None:
    _write_skill(user_home, "global.md", "body")
    store = default_skill_store(workspace_root=workspace, user_home=user_home)
    assert store.has("global")


# ---------------------------------------------------------------------------
# SkillRegistry
# ---------------------------------------------------------------------------


def test_skill_registry_lists_extras_override_store(workspace: Path) -> None:
    _write_skill(workspace, "commit.md", "---\nname: commit\n---\nbody\n")
    store = SkillStore(workspace_root=workspace, user_home=None)
    override = Skill(slug="commit", name="override", description="", body="override body")
    registry = SkillRegistry(store, extras=[override])
    assert registry.get("commit") is override
    slugs = [skill.slug for skill in registry.list()]
    assert slugs == ["commit"]


def test_skill_registry_reload_rescans(workspace: Path) -> None:
    store = SkillStore(workspace_root=workspace, user_home=None)
    assert store.list() == []
    _write_skill(workspace, "new.md", "body")
    registry = SkillRegistry(store)
    assert registry.has("new") is False  # not reloaded yet
    registry.reload()
    assert registry.has("new") is True


# ---------------------------------------------------------------------------
# Allowlist overlay
# ---------------------------------------------------------------------------


def test_scoped_allowlist_blocks_tools_outside_list(workspace: Path) -> None:
    manager = PermissionManager(root=workspace)
    with scoped_allowlist(manager, allowed={"FileRead"}):
        # Read-only tool on the allowlist still passes.
        assert manager.decision_for_tool(FileReadTool(), {"path": "x"}) == "allow"
        # Tool not on the allowlist is denied regardless of mode.
        assert manager.decision_for_tool(FileEditTool(), {"path": "x"}) == "deny"
    # After the scope exits the manager returns to normal decisions.
    assert manager.decision_for_tool(FileEditTool(), {"path": "x"}) == "ask"


def test_scoped_allowlist_nesting_intersects(workspace: Path) -> None:
    manager = PermissionManager(root=workspace)
    with scoped_allowlist(manager, allowed={"FileRead", "Grep"}):
        with scoped_allowlist(manager, allowed={"FileRead", "Bash"}):
            # Only tools in both outer and inner scopes are allowed.
            assert manager.decision_for_tool(FileReadTool(), {"path": "x"}) == "allow"
            # Bash was granted by inner only; outer scope blocks it.
            from cli.tools.bash_tool import BashTool

            assert manager.decision_for_tool(BashTool(), {"command": "ls"}) == "deny"
        # Outer scope survives: Grep (read-only) still allowed.
        from cli.tools.grep_tool import GrepTool

        assert manager.decision_for_tool(GrepTool(), {"pattern": "x"}) == "allow"


# ---------------------------------------------------------------------------
# Slash dispatch
# ---------------------------------------------------------------------------


def _ctx_with_registry(registry: SkillRegistry | None) -> SlashContext:
    ctx = SlashContext()
    ctx.meta = {SKILL_REGISTRY_META_KEY: registry} if registry is not None else {}
    return ctx


def test_skill_slash_runs_and_renders_prompt(workspace: Path) -> None:
    _write_skill(
        workspace,
        "commit.md",
        """---
name: commit
description: Helper
allowed-tools: [FileRead]
---
Write a commit message: $ARGUMENTS
""",
    )
    registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))
    ctx = _ctx_with_registry(registry)
    result = build_skill_command().handler(ctx, "commit", "wip fix")
    text = _as_text(result)
    assert "Skill: commit" in text
    assert "Write a commit message: wip fix" in text
    assert "FileRead" in text


def test_skill_slash_warns_on_unknown_slug(workspace: Path) -> None:
    registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))
    ctx = _ctx_with_registry(registry)
    result = build_skill_command().handler(ctx, "nope")
    assert "Unknown skill" in _as_text(result)


def test_skill_list_slash_renders_catalog(workspace: Path) -> None:
    _write_skill(workspace, "a.md", "---\ndescription: first\n---\nbody\n")
    _write_skill(workspace, "b.md", "---\ndescription: second\n---\nbody\n")
    registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))
    ctx = _ctx_with_registry(registry)
    result = build_skill_list_command().handler(ctx)
    text = _as_text(result)
    assert "/a" in text
    assert "/b" in text


def test_skill_list_slash_empty(workspace: Path) -> None:
    registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))
    ctx = _ctx_with_registry(registry)
    result = build_skill_list_command().handler(ctx)
    assert "No skills loaded" in _as_text(result)


def test_skill_reload_picks_up_new_file(workspace: Path) -> None:
    registry = SkillRegistry(SkillStore(workspace_root=workspace, user_home=None))
    _write_skill(workspace, "late.md", "body")
    ctx = _ctx_with_registry(registry)
    result = build_skill_reload_command().handler(ctx)
    assert "Reloaded skills" in _as_text(result)
    assert registry.has("late") is True


def test_skill_slash_without_registry_warns() -> None:
    ctx = _ctx_with_registry(None)
    for command in all_skill_commands():
        result = command.handler(ctx)
        assert "not configured" in _as_text(result)


def test_skill_commands_register_cleanly() -> None:
    registry = CommandRegistry()
    for command in all_skill_commands():
        registry.register(command)
    assert set(registry.names()) >= {"skill", "skill-list", "skill-reload"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if hasattr(result, "result"):
        return str(result.result or "")
    return str(result)
