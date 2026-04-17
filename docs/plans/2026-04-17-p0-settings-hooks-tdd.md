# P0 Settings Cascade And Hook Contract TDD Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Each implementation task also uses `superpowers:test-driven-development`.

**Goal:** Ship P0 of the Claude-Code-parity roadmap: a typed settings cascade, env-var bridge, and Claude-Code-compatible lifecycle hook contract wired into turns, tools, migration, and doctor diagnostics.

**Architecture:** Promote the current flat `cli/settings.py` module into a `cli/settings/` package that re-exports the old public API while adding a pydantic v2 `Settings` tree and loader. Preserve existing permission and hook call sites, then layer the new hook events into `LLMOrchestrator.run_turn()` and `execute_tool_call()` using the existing `HookRegistry.fire()` seam. Doctor integration should add pure data builders in `cli/doctor_sections.py` and minimally wire current inline surfaces to those builders.

**Tech Stack:** Python 3.11, pydantic v2, pytest, existing `cli.hooks`, `cli.permissions`, `cli.llm.orchestrator`, `cli.tools.executor`, Click slash-command registry.

---

## Ground Truth Read Before Planning

- Roadmap P0 section read from `/Users/andrew/Desktop/agentlab/docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`. Note: that roadmap file is untracked in the source checkout and is not present on the new worktree branch.
- Worktree: `/Users/andrew/Desktop/agentlab/.claude/worktrees/p0-settings-hooks` on branch `claude/cc-parity-p0`.
- Baseline focused tests passed:

```bash
.venv/bin/python -m pytest tests/test_system_prompt.py tests/test_settings.py tests/test_hooks.py tests/test_phase_d_prompt_hooks.py
```

- `cli/settings.py:11-149` is the current flat module. Important exports: `DEFAULTS`, `USER_CONFIG_DIR`, `USER_CONFIG_PATH`, `PROJECT_SETTINGS_FILENAME`, `LOCAL_SETTINGS_FILENAME`, `_load_json`, `_deep_merge`, `ResolvedSettings`, `_flatten_dotted`, `resolve_settings`, `save_user_config`, `save_project_settings`, `save_local_settings`, `settings_file_paths`.
- `cli/hooks/types.py:10-143` defines `HookEvent`, `HookVerdict`, `HookType`, `HookDefinition`, `HookOutcome`. Current events are `PreToolUse`, `PostToolUse`, `OnPermissionRequest`, and `Stop`. Current verdicts are `allow`, `deny`, and `inform`.
- `cli/hooks/registry.py:46-142` owns `HookRegistry.add()`, `hooks_for()`, `prompt_fragments_for()`, and `fire()`. `registry.py:150-181` is the subprocess runner. `registry.py:189-272` parses the current settings-shaped hook block.
- `cli/permissions.py:137-341` defines `PermissionManager`; `decision_for_tool()` is called by the executor at `cli/tools/executor.py:87`.
- `cli/llm/orchestrator.py:108-194` is `LLMOrchestrator.run_turn()`. It calls the model at line 133, executes tools at lines 156-160, appends tool results at line 171, finalizes at lines 173-194, and fires the old `Stop` hook via `_fire_stop_hook()` at lines 185-186.
- `cli/llm/orchestrator.py:261-299` injects prompt-fragment hooks using `HookEvent.PRE_TOOL_USE` and `HookEvent.POST_TOOL_USE`.
- `cli/tools/executor.py:47-198` is `execute_tool_call()`. It currently fires `OnPermissionRequest`, `PreToolUse`, and `PostToolUse`; post hooks only append metadata and do not mutate tool output.
- `tests/test_system_prompt.py:127-154` is the byte-stable system-prompt snapshot. Do not change expected text.
- `cli/workbench_app/app.py:1088-1129` currently has a TUI opt-in gate using `AGENTLAB_TUI`; no `AGENTLAB_NO_TUI` reference exists on this branch. P0 must preserve and add explicit `AGENTLAB_NO_TUI=1` compatibility when settings become the source of truth.
- `cli/doctor_sections.py` does not exist on this branch. Current `agentlab doctor` output is inline in `runner.py:4672-5038`; the line-mode doctor screen delegates to the Click command in `cli/workbench_app/screens/doctor.py:37-43`; the Textual doctor screen has local diagnostics in `cli/workbench_app/tui/screens/doctor.py:44-85`.
- Claude Code references were read for shape only:
  - `/Users/andrew/Desktop/claude-code-main/src/utils/permissions/permissionsLoader.ts`
  - `/Users/andrew/Desktop/claude-code-main/src/services/tools/toolHooks.ts`
  - `/Users/andrew/Desktop/claude-code-main/src/types/hooks.ts`

## Global Rules For Every Task

1. Fresh subagent per P0 task. Do not implement task code in the controller thread.
2. Give the subagent the full task text from this plan plus relevant code snippets and line numbers from the ground-truth section.
3. TDD order is mandatory:
   - Write failing tests.
   - Run the exact targeted pytest command and confirm RED.
   - Write minimal implementation.
   - Run targeted tests and confirm GREEN.
   - Run `.venv/bin/python -m pytest tests/test_system_prompt.py`.
   - Commit with a Conventional Commit message.
4. After each task returns, the controller runs:

```bash
.venv/bin/python -m pytest tests/
```

5. Do not touch provider adapters in `cli/llm/providers/`.
6. Preserve existing imports: `from cli.settings import ...` must continue to work.
7. Keep `tests/test_system_prompt.py` byte-stable.
8. Hook subprocess timeouts must not hang or crash a turn.
9. Env vars override settings files.
10. Users with no settings files keep today's behavior.

---

## Task P0.1: Settings Package And Schema

**Commit:** `feat(settings): add typed settings cascade`

**Files:**
- Delete after copying public surface: `cli/settings.py`
- Create: `cli/settings/__init__.py`
- Create: `cli/settings/schema.py`
- Create: `cli/settings/loader.py`
- Test: `tests/test_settings_cascade.py`
- Keep passing: `tests/test_settings.py`

**Behavior:**
- Replace the flat module with a package while re-exporting the same names.
- Add pydantic v2 models: `Settings`, `Permissions`, `Hooks`, `Providers`, `Sessions`, `Paste`, `Input`, `MCP`.
- Every model field has a default. `Settings()` and `{}` settings files are valid.
- Loader deep-merge order:
  1. typed defaults,
  2. `/etc/agentlab/settings.json`,
  3. legacy `~/.agentlab/config.json` flat dotted keys for back-compat,
  4. `~/.agentlab/settings.json`,
  5. `<workspace>/.agentlab/settings.json`,
  6. `<workspace>/.agentlab/settings.local.json`.
- Dicts deep-merge. Lists replace.
- Preserve `resolve_settings()` and `ResolvedSettings.get("dotted.key")`.
- `ResolvedSettings.get()` should log one deprecation warning and traverse the pydantic tree first; it may fall back to `.values` for legacy callers.
- Keep old helper functions and constants exported from `cli/settings/__init__.py`.

**Suggested schema skeleton:**

```python
# cli/settings/schema.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class PermissionRules(BaseModel):
    """Allow, ask, and deny patterns used by PermissionManager."""

    model_config = ConfigDict(extra="forbid")

    allow: list[str] = Field(default_factory=list)
    ask: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class Permissions(BaseModel):
    """Permission defaults and explicit rules."""

    model_config = ConfigDict(extra="forbid")

    mode: str = "default"
    rules: PermissionRules = Field(default_factory=PermissionRules)


class HookCommand(BaseModel):
    """One executable or prompt hook entry."""

    model_config = ConfigDict(extra="forbid")

    type: str = "command"
    command: str = ""
    prompt: str = ""
    timeout_seconds: int | None = None
    timeout: int | None = None
    shell: str = "bash"
    env: dict[str, str] = Field(default_factory=dict)
    id: str = ""


class HookMatcher(BaseModel):
    """Matcher plus nested hooks, matching Claude Code settings shape."""

    model_config = ConfigDict(extra="forbid")

    matcher: str = ""
    hooks: list[HookCommand] = Field(default_factory=list)


class Hooks(BaseModel):
    """Lifecycle hooks keyed by Claude-Code-compatible event names."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    timeout_seconds: int = 5
    beforeQuery: list[HookMatcher] = Field(default_factory=list)
    afterQuery: list[HookMatcher] = Field(default_factory=list)
    PreToolUse: list[HookMatcher] = Field(default_factory=list)
    PostToolUse: list[HookMatcher] = Field(default_factory=list)
    OnPermissionRequest: list[HookMatcher] = Field(default_factory=list)
    SubagentStop: list[HookMatcher] = Field(default_factory=list)
    SessionEnd: list[HookMatcher] = Field(default_factory=list)
    Stop: list[HookMatcher] = Field(default_factory=list)

    def event_map(self) -> dict[str, list[HookMatcher]]:
        return {
            name: value
            for name, value in self.model_dump().items()
            if name != "timeout_seconds" and isinstance(value, list) and value
        }


class Providers(BaseModel):
    """Provider defaults and API keys loaded from files or env vars."""

    model_config = ConfigDict(extra="forbid")

    default_provider: str | None = None
    default_model: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    google_api_key: str | None = None
    gemini_api_key: str | None = None
    models: dict[str, str] = Field(default_factory=dict)


class Sessions(BaseModel):
    """Session storage options."""

    model_config = ConfigDict(extra="forbid")

    root: str | None = None


class Paste(BaseModel):
    """Paste and image-store options for later phases."""

    model_config = ConfigDict(extra="forbid")

    store_root: str | None = None
    inline_threshold_lines: int = 10


class Input(BaseModel):
    """Workbench input and TUI compatibility toggles."""

    model_config = ConfigDict(extra="forbid")

    expose_slash_to_model: bool = False
    no_tui: bool = False


class MCP(BaseModel):
    """MCP configuration placeholder for later transport parity."""

    model_config = ConfigDict(extra="forbid")

    servers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Settings(BaseModel):
    """Fully resolved AgentLab settings."""

    model_config = ConfigDict(extra="forbid")

    permissions: Permissions = Field(default_factory=Permissions)
    hooks: Hooks = Field(default_factory=Hooks)
    providers: Providers = Field(default_factory=Providers)
    sessions: Sessions = Field(default_factory=Sessions)
    paste: Paste = Field(default_factory=Paste)
    input: Input = Field(default_factory=Input)
    mcp: MCP = Field(default_factory=MCP)
    shell: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    mode: str = "default"
    editor: str | None = None

    _loaded_layers: list[dict[str, str]] = PrivateAttr(default_factory=list)
    _env_overrides: list[str] = PrivateAttr(default_factory=list)
```

**Test code to write first:**

```python
# tests/test_settings_cascade.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli.settings import (
    LOCAL_SETTINGS_FILENAME,
    PROJECT_SETTINGS_FILENAME,
    Settings,
    load_settings,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_defaults_only_accepts_empty_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cli.settings.loader.SYSTEM_SETTINGS_PATH", tmp_path / "etc" / "settings.json")
    monkeypatch.setattr("cli.settings.loader.USER_SETTINGS_PATH", tmp_path / "home" / ".agentlab" / "settings.json")
    monkeypatch.setattr("cli.settings.loader.USER_CONFIG_PATH", tmp_path / "home" / ".agentlab" / "config.json")

    settings = load_settings(tmp_path)

    assert isinstance(settings, Settings)
    assert settings.permissions.mode == "default"
    assert settings.hooks.timeout_seconds == 5
    assert settings.input.no_tui is False


@pytest.mark.parametrize(
    ("layers", "expected_mode", "expected_model"),
    [
        ({"user": {"permissions": {"mode": "acceptEdits"}}}, "acceptEdits", None),
        (
            {
                "user": {"permissions": {"mode": "acceptEdits"}, "providers": {"default_model": "user-model"}},
                "project": {"permissions": {"mode": "dontAsk"}},
            },
            "dontAsk",
            "user-model",
        ),
        (
            {
                "project": {"permissions": {"mode": "dontAsk"}},
                "local": {"permissions": {"mode": "plan"}, "providers": {"default_model": "local-model"}},
            },
            "plan",
            "local-model",
        ),
    ],
)
def test_layer_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    layers: dict[str, dict],
    expected_mode: str,
    expected_model: str | None,
) -> None:
    system_path = tmp_path / "etc" / "settings.json"
    user_path = tmp_path / "home" / ".agentlab" / "settings.json"
    legacy_path = tmp_path / "home" / ".agentlab" / "config.json"
    monkeypatch.setattr("cli.settings.loader.SYSTEM_SETTINGS_PATH", system_path)
    monkeypatch.setattr("cli.settings.loader.USER_SETTINGS_PATH", user_path)
    monkeypatch.setattr("cli.settings.loader.USER_CONFIG_PATH", legacy_path)
    if "system" in layers:
        _write_json(system_path, layers["system"])
    if "user" in layers:
        _write_json(user_path, layers["user"])
    if "project" in layers:
        _write_json(tmp_path / ".agentlab" / PROJECT_SETTINGS_FILENAME, layers["project"])
    if "local" in layers:
        _write_json(tmp_path / ".agentlab" / LOCAL_SETTINGS_FILENAME, layers["local"])

    settings = load_settings(tmp_path)

    assert settings.permissions.mode == expected_mode
    assert settings.providers.default_model == expected_model


def test_deep_merge_nested_dicts_and_replace_lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cli.settings.loader.SYSTEM_SETTINGS_PATH", tmp_path / "etc" / "settings.json")
    monkeypatch.setattr("cli.settings.loader.USER_SETTINGS_PATH", tmp_path / "home" / ".agentlab" / "settings.json")
    monkeypatch.setattr("cli.settings.loader.USER_CONFIG_PATH", tmp_path / "home" / ".agentlab" / "config.json")
    _write_json(
        tmp_path / "home" / ".agentlab" / "settings.json",
        {
            "permissions": {"rules": {"allow": ["tool:FileRead:*"], "ask": ["tool:Bash:*"]}},
            "providers": {"models": {"fast": "user-fast", "smart": "user-smart"}},
        },
    )
    _write_json(
        tmp_path / ".agentlab" / PROJECT_SETTINGS_FILENAME,
        {
            "permissions": {"rules": {"allow": ["tool:Grep:*"]}},
            "providers": {"models": {"fast": "project-fast"}},
        },
    )

    settings = load_settings(tmp_path)

    assert settings.permissions.rules.allow == ["tool:Grep:*"]
    assert settings.permissions.rules.ask == ["tool:Bash:*"]
    assert settings.providers.models == {"fast": "project-fast", "smart": "user-smart"}


def test_legacy_flat_config_file_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cli.settings.loader.SYSTEM_SETTINGS_PATH", tmp_path / "etc" / "settings.json")
    monkeypatch.setattr("cli.settings.loader.USER_SETTINGS_PATH", tmp_path / "home" / ".agentlab" / "settings.json")
    monkeypatch.setattr("cli.settings.loader.USER_CONFIG_PATH", tmp_path / "home" / ".agentlab" / "config.json")
    _write_json(
        tmp_path / "home" / ".agentlab" / "config.json",
        {"permissions.mode": "acceptEdits", "providers.default_model": "legacy-model"},
    )

    settings = load_settings(tmp_path)

    assert settings.permissions.mode == "acceptEdits"
    assert settings.providers.default_model == "legacy-model"
```

**Run RED:**

```bash
.venv/bin/python -m pytest tests/test_settings_cascade.py -q
```

Expected: import failure for `Settings` or `load_settings`, then validation/loader failures until implementation exists.

**Minimal implementation steps:**

1. Move old `cli/settings.py` contents into package modules:
   - `schema.py` for pydantic models.
   - `loader.py` for constants, JSON helpers, merge helpers, `ResolvedSettings`, `resolve_settings`, and save helpers.
   - `__init__.py` re-exports everything currently imported by tests and callers.
2. Preserve dotted-key helpers exactly enough for `tests/test_settings.py`.
3. Implement `load_settings(workspace_root: str | Path | None = None) -> Settings`.
4. Add `SYSTEM_SETTINGS_PATH = Path("/etc/agentlab/settings.json")` and `USER_SETTINGS_PATH = USER_CONFIG_DIR / "settings.json"`.
5. Attach metadata to the pydantic instance through private attrs:

```python
settings = Settings.model_validate(merged)
settings._loaded_layers = loaded_layers
return settings
```

6. Make `resolve_settings()` call `load_settings()`, then apply session and flag overrides by deep-merging into `settings.model_dump()`.

**Run GREEN:**

```bash
.venv/bin/python -m pytest tests/test_settings_cascade.py tests/test_settings.py -q
.venv/bin/python -m pytest tests/test_system_prompt.py -q
```

**Commit:**

```bash
git add cli/settings tests/test_settings_cascade.py tests/test_settings.py
git rm cli/settings.py
git commit -m "feat(settings): add typed settings cascade"
```

---

## Task P0.2: Environment Variable Bridge

**Commit:** `feat(settings): bridge legacy environment variables`

**Files:**
- Create: `cli/settings/env_bridge.py`
- Modify: `cli/settings/loader.py`
- Modify: `cli/workbench_app/app.py`
- Test: `tests/test_settings_env_bridge.py`

**Behavior:**
- `env_bridge.py` reads these env vars and applies them after file layers:
  - `AGENTLAB_NO_TUI` -> `settings.input.no_tui`
  - `AGENTLAB_EXPOSE_SLASH_TO_MODEL` -> `settings.input.expose_slash_to_model`
  - `ANTHROPIC_API_KEY` -> `settings.providers.anthropic_api_key`
  - `OPENAI_API_KEY` -> `settings.providers.openai_api_key`
  - `GOOGLE_API_KEY` -> `settings.providers.google_api_key`
  - `GEMINI_API_KEY` -> `settings.providers.gemini_api_key`
- Env var precedence is env > local > project > user > system > defaults.
- Absent env vars do not change loaded settings.
- Truthy values: `1`, `true`, `yes`, `on`.
- Falsey values: `0`, `false`, `no`, `off`.
- `AGENTLAB_NO_TUI=1` must explicitly prevent TUI launch even if settings or `AGENTLAB_TUI=1` request TUI.

**Test code to write first:**

```python
# tests/test_settings_env_bridge.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli.settings import load_settings
from cli.settings.env_bridge import env_overrides


def test_absent_env_vars_leave_settings_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "AGENTLAB_NO_TUI",
        "AGENTLAB_EXPOSE_SLASH_TO_MODEL",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    assert env_overrides() == ({}, [])


@pytest.mark.parametrize(
    ("env_name", "env_value", "dotted_path", "expected"),
    [
        ("AGENTLAB_NO_TUI", "1", "input.no_tui", True),
        ("AGENTLAB_NO_TUI", "false", "input.no_tui", False),
        ("AGENTLAB_EXPOSE_SLASH_TO_MODEL", "yes", "input.expose_slash_to_model", True),
        ("ANTHROPIC_API_KEY", "anthropic-key", "providers.anthropic_api_key", "anthropic-key"),
        ("OPENAI_API_KEY", "openai-key", "providers.openai_api_key", "openai-key"),
        ("GOOGLE_API_KEY", "google-key", "providers.google_api_key", "google-key"),
        ("GEMINI_API_KEY", "gemini-key", "providers.gemini_api_key", "gemini-key"),
    ],
)
def test_documented_env_vars_lift_to_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    env_value: str,
    dotted_path: str,
    expected: object,
) -> None:
    monkeypatch.setattr("cli.settings.loader.SYSTEM_SETTINGS_PATH", tmp_path / "etc" / "settings.json")
    monkeypatch.setattr("cli.settings.loader.USER_SETTINGS_PATH", tmp_path / "home" / ".agentlab" / "settings.json")
    monkeypatch.setattr("cli.settings.loader.USER_CONFIG_PATH", tmp_path / "home" / ".agentlab" / "config.json")
    monkeypatch.setenv(env_name, env_value)

    settings = load_settings(tmp_path)

    node: object = settings
    for part in dotted_path.split("."):
        node = getattr(node, part)
    assert node == expected
    assert env_name in settings._env_overrides


def test_env_overrides_project_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cli.settings.loader.SYSTEM_SETTINGS_PATH", tmp_path / "etc" / "settings.json")
    monkeypatch.setattr("cli.settings.loader.USER_SETTINGS_PATH", tmp_path / "home" / ".agentlab" / "settings.json")
    monkeypatch.setattr("cli.settings.loader.USER_CONFIG_PATH", tmp_path / "home" / ".agentlab" / "config.json")
    project_path = tmp_path / ".agentlab" / "settings.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text(
        json.dumps({"providers": {"anthropic_api_key": "from-file"}, "input": {"no_tui": False}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    monkeypatch.setenv("AGENTLAB_NO_TUI", "1")

    settings = load_settings(tmp_path)

    assert settings.providers.anthropic_api_key == "from-env"
    assert settings.input.no_tui is True
```

Add one app-level regression:

```python
def test_no_tui_env_disables_tui_even_when_tui_requested(monkeypatch, tmp_path):
    # Keep this test small by monkeypatching run_tui_app to raise if called,
    # then launch with AGENTLAB_TUI=1 and AGENTLAB_NO_TUI=1 plus input_provider.
```

**Run RED:**

```bash
.venv/bin/python -m pytest tests/test_settings_env_bridge.py -q
```

**Minimal implementation steps:**

1. Implement `env_overrides(environ: Mapping[str, str] | None = None) -> tuple[dict[str, object], list[str]]`.
2. Call it at the end of `load_settings()`.
3. Store override names on `settings._env_overrides`.
4. In `cli/workbench_app/app.py:1114-1129`, read `load_settings(workspace.root if workspace else Path.cwd())` defensively and skip the TUI branch when `settings.input.no_tui` is true or `AGENTLAB_NO_TUI` is truthy.

**Run GREEN:**

```bash
.venv/bin/python -m pytest tests/test_settings_env_bridge.py tests/test_settings_cascade.py tests/test_settings.py -q
.venv/bin/python -m pytest tests/test_system_prompt.py -q
```

**Commit:**

```bash
git add cli/settings/env_bridge.py cli/settings/loader.py cli/workbench_app/app.py tests/test_settings_env_bridge.py
git commit -m "feat(settings): bridge legacy environment variables"
```

---

## Task P0.3: Hook Contract And Lifecycle Events

**Commit:** `feat(hooks): load lifecycle hooks from settings`

**Files:**
- Modify: `cli/hooks/types.py`
- Modify: `cli/hooks/registry.py`
- Modify: `cli/hooks/__init__.py`
- Test: `tests/test_hooks_lifecycle.py`
- Keep passing: `tests/test_hooks.py`, `tests/test_phase_d_prompt_hooks.py`

**Behavior:**
- Extend events to:
  - `BEFORE_QUERY = "beforeQuery"`
  - `AFTER_QUERY = "afterQuery"`
  - `PRE_TOOL_USE = "PreToolUse"`
  - `POST_TOOL_USE = "PostToolUse"`
  - `SUBAGENT_STOP = "SubagentStop"`
  - `SESSION_END = "SessionEnd"`
- Keep old names working:
  - `ON_PERMISSION_REQUEST = "OnPermissionRequest"`
  - `STOP = "Stop"`
  - Optional compatibility strings `beforeTool` and `afterTool` should normalize to `PreToolUse` and `PostToolUse` when loading settings.
- Add `HookVerdict.ASK = "ask"` and `HookVerdict.TIMEOUT = "timeout"`.
- Add `HookRegistry.load_from_settings(settings: Settings, runner: Runner | None = None) -> HookRegistry`.
- Keep module-level `load_hook_registry()` as a compatibility wrapper.
- Default timeout is `Settings.hooks.timeout_seconds` (5 seconds), overridden per hook by `timeout_seconds` or `timeout`.
- A timeout returns `HookVerdict.TIMEOUT`, logs or records a timeout message, and does not crash or wedge the turn.
- Denial is still first-deny-wins for gating events.
- Stderr/stdout messages continue surfacing through `HookOutcome.messages`.
- Parse simple JSON stdout when present:
  - `{"decision":"deny","reason":"..."}`
  - `{"decision":"ask","reason":"..."}`
  - `{"decision":"allow"}`
  - `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"..."}}`
  - `{"hookSpecificOutput":{"hookEventName":"PostToolUse","updatedMCPToolOutput": ...}}`

**Test code to write first:**

```python
# tests/test_hooks_lifecycle.py
from __future__ import annotations

from cli.hooks import HookEvent, HookRegistry, HookVerdict
from cli.hooks.registry import HookProcessResult
from cli.settings import Settings


def test_settings_defined_hook_fires_for_matching_tool() -> None:
    calls: list[tuple[str, dict]] = []

    def runner(hook, payload):
        calls.append((hook.command, payload))
        return HookProcessResult(returncode=0, stdout="", stderr="ok")

    settings = Settings.model_validate(
        {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}
                ]
            }
        }
    )
    registry = HookRegistry.load_from_settings(settings, runner=runner)

    outcome = registry.fire(
        HookEvent.PRE_TOOL_USE,
        tool_name="Bash",
        payload={"tool_name": "Bash", "tool_input": {"command": "pwd"}},
    )

    assert outcome.verdict is HookVerdict.INFORM
    assert calls == [("echo pre", {"tool_name": "Bash", "tool_input": {"command": "pwd"}})]


def test_non_matching_hook_does_not_fire() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "PostToolUse": [
                    {"matcher": "FileEdit", "hooks": [{"command": "echo post"}]}
                ]
            }
        }
    )
    registry = HookRegistry.load_from_settings(
        settings,
        runner=lambda *_: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    outcome = registry.fire(HookEvent.POST_TOOL_USE, tool_name="FileRead", payload={})

    assert outcome.fired == 0
    assert outcome.verdict is HookVerdict.ALLOW


def test_timeout_returns_timeout_verdict_without_crashing() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "timeout_seconds": 5,
                "beforeQuery": [{"hooks": [{"command": "slow"}]}],
            }
        }
    )
    registry = HookRegistry.load_from_settings(
        settings,
        runner=lambda hook, payload: HookProcessResult(
            returncode=124,
            stdout="",
            stderr="",
            timed_out=True,
        ),
    )

    outcome = registry.fire(HookEvent.BEFORE_QUERY, payload={"prompt": "hi"})

    assert outcome.verdict is HookVerdict.TIMEOUT
    assert outcome.fired == 1
    assert "timed out after 5s" in outcome.messages[0]


def test_json_ask_verdict_is_recorded() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "PreToolUse": [{"hooks": [{"command": "ask"}]}],
            }
        }
    )
    registry = HookRegistry.load_from_settings(
        settings,
        runner=lambda hook, payload: HookProcessResult(
            returncode=0,
            stdout='{"decision":"ask","reason":"needs review"}',
            stderr="",
        ),
    )

    outcome = registry.fire(HookEvent.PRE_TOOL_USE, tool_name="Bash", payload={})

    assert outcome.verdict is HookVerdict.ASK
    assert outcome.messages == ["needs review"]


def test_legacy_before_tool_name_normalizes_to_pre_tool_use() -> None:
    settings = Settings.model_validate(
        {
            "hooks": {
                "beforeTool": [{"hooks": [{"command": "legacy"}]}],
            }
        }
    )
    registry = HookRegistry.load_from_settings(settings)

    hooks = registry.hooks_for(HookEvent.PRE_TOOL_USE, tool_name="Anything")

    assert [hook.command for hook in hooks] == ["legacy"]
```

**Run RED:**

```bash
.venv/bin/python -m pytest tests/test_hooks_lifecycle.py -q
```

**Minimal implementation steps:**

1. Add new events and verdicts to `cli/hooks/types.py`.
2. Add a small normalization helper in `registry.py`:

```python
_EVENT_ALIASES = {
    "beforeTool": "PreToolUse",
    "afterTool": "PostToolUse",
    "Stop": "Stop",
}
```

3. Extend `HookOutcome` with metadata keys for parsed JSON and updates without breaking existing attributes.
4. Implement `HookRegistry.load_from_settings()` by reading `settings.hooks.event_map()`.
5. Keep `load_hook_registry(mapping)` working for existing tests by converting mappings through `Settings.model_validate()` where possible, with a fallback for raw dicts.
6. Change timeout handling in `fire()` from denial to `TIMEOUT`.
7. Add JSON stdout parsing in a helper. Do not let malformed JSON crash hooks.

**Run GREEN:**

```bash
.venv/bin/python -m pytest tests/test_hooks_lifecycle.py tests/test_hooks.py tests/test_phase_d_prompt_hooks.py -q
.venv/bin/python -m pytest tests/test_system_prompt.py -q
```

**Commit:**

```bash
git add cli/hooks tests/test_hooks_lifecycle.py tests/test_hooks.py tests/test_phase_d_prompt_hooks.py
git commit -m "feat(hooks): load lifecycle hooks from settings"
```

---

## Task P0.4: Orchestrator And Executor Wiring

**Commit:** `feat(hooks): fire turn and tool lifecycle events`

**Files:**
- Modify: `cli/llm/orchestrator.py`
- Modify: `cli/tools/executor.py`
- Test: `tests/test_orchestrator_hooks.py`
- Keep passing: `tests/test_phase_d_prompt_hooks.py`, `tests/test_hooks.py`

**Behavior:**
- `LLMOrchestrator.run_turn()` fires `HookEvent.BEFORE_QUERY` before the first model call.
- If `BEFORE_QUERY` returns `DENY`, abort the turn before any model call and return an `OrchestratorResult` with:
  - `assistant_text` containing the denial message or empty string,
  - `tool_executions=[]`,
  - `stop_reason="hook_deny"`,
  - metadata containing hook messages.
- `LLMOrchestrator.run_turn()` fires `HookEvent.AFTER_QUERY` after the final model call, before returning. It should include `stop_reason`, assistant text, execution names, and session id in payload.
- Replace old `_fire_stop_hook()` behavior with `SESSION_END` while keeping `STOP` as a best-effort compatibility event if old hooks are registered.
- `execute_tool_call()` fires `PRE_TOOL_USE` before dispatch and `POST_TOOL_USE` after the tool returns using Claude-Code-compatible payload keys:
  - pre payload: `tool_name`, `tool_input`
  - post payload: `tool_name`, `tool_input`, `tool_response`
- `PRE_TOOL_USE` `DENY` returns first-class tool-result error content exactly shaped like: `denied by hook: <name or message>`.
- `PRE_TOOL_USE` `ASK` falls through to the existing permission prompt. If current permission decision is already `allow`, an ask verdict should force the dialog path.
- `POST_TOOL_USE` can mutate the tool result. Use parsed JSON metadata from Task P0.3:
  - `updatedMCPToolOutput` or `updated_tool_response` replaces `ToolResult.content` while preserving `ok=True`.
  - Also preserve hook messages in metadata.
- Hook exceptions remain non-fatal.

**Test code to write first:**

```python
# tests/test_orchestrator_hooks.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from cli.hooks import HookEvent, HookOutcome, HookVerdict
from cli.llm.orchestrator import LLMOrchestrator
from cli.llm.streaming import MessageStop, TextDelta, ToolUseEnd, ToolUseStart
from cli.permissions import PermissionManager
from cli.tools.base import PermissionDecision, Tool, ToolContext, ToolResult
from cli.tools.executor import execute_tool_call
from cli.tools.registry import ToolRegistry


class RecordingHookRegistry:
    def __init__(self, outcomes: dict[HookEvent, HookOutcome] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.calls: list[tuple[HookEvent, str, dict[str, Any]]] = []

    def fire(self, event: HookEvent, *, tool_name: str = "", payload=None):
        payload_dict = dict(payload or {})
        self.calls.append((event, tool_name, payload_dict))
        return self.outcomes.get(event, HookOutcome())

    def prompt_fragments_for(self, event: HookEvent, *, tool_name: str = "") -> list[str]:
        return []


class RecordingModel:
    def __init__(self, events: list[list[Any]]) -> None:
        self.events = list(events)
        self.calls = 0

    def stream(self, *, system_prompt, messages, tools) -> Iterator[Any]:
        self.calls += 1
        for event in self.events.pop(0):
            yield event


class EchoTool(Tool):
    name = "Echo"
    description = "Echo input."
    input_schema = {"type": "object", "properties": {"value": {"type": "string"}}}
    read_only = True

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.success(tool_input["value"], metadata={})


def _orchestrator(tmp_path: Path, model: RecordingModel, hooks: RecordingHookRegistry) -> LLMOrchestrator:
    registry = ToolRegistry()
    registry.register(EchoTool())
    return LLMOrchestrator(
        model=model,
        tool_registry=registry,
        permissions=PermissionManager(root=tmp_path),
        workspace_root=tmp_path,
        hook_registry=hooks,
        system_prompt="system",
        echo=lambda _: None,
    )


def test_turn_hooks_fire_in_order(tmp_path: Path) -> None:
    model = RecordingModel([[TextDelta(text="hi"), MessageStop(stop_reason="end_turn")]])
    hooks = RecordingHookRegistry()
    result = _orchestrator(tmp_path, model, hooks).run_turn("hello")

    assert result.stop_reason == "end_turn"
    assert [call[0] for call in hooks.calls] == [HookEvent.BEFORE_QUERY, HookEvent.AFTER_QUERY, HookEvent.SESSION_END]
    assert hooks.calls[0][2]["prompt"] == "hello"
    assert hooks.calls[1][2]["stop_reason"] == "end_turn"


def test_before_query_deny_aborts_before_model_call(tmp_path: Path) -> None:
    deny = HookOutcome(verdict=HookVerdict.DENY, messages=["blocked"])
    model = RecordingModel([[TextDelta(text="should not run")]])
    hooks = RecordingHookRegistry({HookEvent.BEFORE_QUERY: deny})

    result = _orchestrator(tmp_path, model, hooks).run_turn("hello")

    assert model.calls == 0
    assert result.stop_reason == "hook_deny"
    assert "blocked" in result.assistant_text


def test_tool_hooks_wrap_dispatch_and_payloads_use_claude_keys(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    hooks = RecordingHookRegistry()

    execution = execute_tool_call(
        "Echo",
        {"value": "ok"},
        registry=registry,
        permissions=PermissionManager(root=tmp_path),
        context=ToolContext(workspace_root=tmp_path),
        hook_registry=hooks,
    )

    assert execution.decision is PermissionDecision.ALLOW
    assert [call[0] for call in hooks.calls] == [HookEvent.PRE_TOOL_USE, HookEvent.POST_TOOL_USE]
    assert hooks.calls[0][2] == {"tool_name": "Echo", "tool_input": {"value": "ok"}}
    assert hooks.calls[1][2]["tool_response"]["content"] == "ok"


def test_pre_tool_deny_returns_first_class_tool_error(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    hooks = RecordingHookRegistry({HookEvent.PRE_TOOL_USE: HookOutcome(verdict=HookVerdict.DENY, messages=["policy"])} )

    execution = execute_tool_call(
        "Echo",
        {"value": "ok"},
        registry=registry,
        permissions=PermissionManager(root=tmp_path),
        context=ToolContext(workspace_root=tmp_path),
        hook_registry=hooks,
    )

    assert execution.decision is PermissionDecision.DENY
    assert execution.result is not None
    assert execution.result.ok is False
    assert "denied by hook: policy" in execution.result.content


def test_post_tool_hook_can_mutate_tool_result(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    outcome = HookOutcome(verdict=HookVerdict.INFORM, metadata={"updated_tool_response": "mutated"})
    hooks = RecordingHookRegistry({HookEvent.POST_TOOL_USE: outcome})

    execution = execute_tool_call(
        "Echo",
        {"value": "original"},
        registry=registry,
        permissions=PermissionManager(root=tmp_path),
        context=ToolContext(workspace_root=tmp_path),
        hook_registry=hooks,
    )

    assert execution.result is not None
    assert execution.result.content == "mutated"
```

**Run RED:**

```bash
.venv/bin/python -m pytest tests/test_orchestrator_hooks.py -q
```

**Minimal implementation steps:**

1. Add helper methods to `LLMOrchestrator`:
   - `_fire_before_query_hook(user_prompt: str) -> HookOutcome | None`
   - `_fire_after_query_hook(...) -> None`
   - `_fire_session_end_hook(...) -> None`
2. Call `_fire_before_query_hook()` after appending the user message but before building the renderer/model loop.
3. On deny, return without calling model.
4. Use `try/finally` or a single return path so `AFTER_QUERY` fires for normal endings and max-loop endings.
5. Update executor payloads and event names.
6. Add a local `_should_force_dialog_from_hook()` or equivalent for `ASK`.
7. Add `_apply_post_tool_mutation(result, outcome) -> ToolResult`.

**Run GREEN:**

```bash
.venv/bin/python -m pytest tests/test_orchestrator_hooks.py tests/test_hooks.py tests/test_phase_d_prompt_hooks.py -q
.venv/bin/python -m pytest tests/test_system_prompt.py -q
```

**Commit:**

```bash
git add cli/llm/orchestrator.py cli/tools/executor.py tests/test_orchestrator_hooks.py
git commit -m "feat(hooks): fire turn and tool lifecycle events"
```

---

## Task P0.5: Migration And Doctor Integration

**Commit:** `feat(settings): add migration and doctor diagnostics`

**Files:**
- Create: `cli/doctor_sections.py`
- Modify: `runner.py`
- Modify: `cli/workbench_app/slash.py`
- Modify: `cli/workbench_app/tui/screens/doctor.py`
- Test: `tests/test_doctor_sections.py`
- Test: `tests/test_workbench_slash.py` or new focused migration tests

**Behavior:**
- Add pure data builder:

```python
def settings_section(settings: Settings) -> dict[str, object]:
    """Return settings diagnostics for doctor surfaces."""
```

- It reports:
  - loaded layers from `settings._loaded_layers`,
  - env vars from `settings._env_overrides`,
  - hooks registered by event,
  - permission mode,
  - provider default model/provider without exposing API key values.
- Wire `settings_section()` into `agentlab doctor --json` and human output without rewriting the whole command.
- Wire `settings_section()` into the Textual doctor screen by replacing or extending `_run_diagnostics()`.
- Add `/migrate-settings` slash command:
  - Reads the current project `<workspace>/.agentlab/settings.json` when present.
  - If it contains flat dotted keys, archive it to `settings.json.bak`.
  - Write nested settings JSON to `settings.json`.
  - Also support legacy user config at `USER_CONFIG_PATH` if no project settings exists and make the output explicit about which file was migrated.
  - If nothing needs migrating, return a helpful no-op message.
  - Do not overwrite an existing `.bak`; choose `settings.json.bak`, then `settings.json.bak.1`, etc.
- Do not log or print secrets.

**Test code to write first:**

```python
# tests/test_doctor_sections.py
from __future__ import annotations

from cli.doctor_sections import settings_section
from cli.settings import Settings


def test_settings_section_reports_layers_env_and_hooks_without_secrets() -> None:
    settings = Settings.model_validate(
        {
            "permissions": {"mode": "acceptEdits"},
            "providers": {
                "default_provider": "anthropic",
                "default_model": "claude",
                "anthropic_api_key": "secret",
            },
            "hooks": {
                "beforeQuery": [{"hooks": [{"command": "echo before"}]}],
                "PreToolUse": [{"matcher": "Bash", "hooks": [{"command": "echo pre"}]}],
            },
        }
    )
    settings._loaded_layers = [
        {"name": "user", "path": "/tmp/user/settings.json"},
        {"name": "project", "path": "/tmp/project/.agentlab/settings.json"},
    ]
    settings._env_overrides = ["ANTHROPIC_API_KEY"]

    section = settings_section(settings)

    assert section["permission_mode"] == "acceptEdits"
    assert section["loaded_layers"] == settings._loaded_layers
    assert section["env_overrides"] == ["ANTHROPIC_API_KEY"]
    assert section["hooks"] == {"beforeQuery": 1, "PreToolUse": 1}
    assert section["providers"]["default_model"] == "claude"
    assert "secret" not in repr(section)
```

Add migration slash tests:

```python
def test_migrate_settings_archives_flat_project_settings(tmp_path):
    # Build SlashContext(workspace=workspace_stub) and dispatch "/migrate-settings".
    # Assert settings.json.bak has dotted keys and settings.json has nested keys.
```

**Run RED:**

```bash
.venv/bin/python -m pytest tests/test_doctor_sections.py -q
```

**Minimal implementation steps:**

1. Create `cli/doctor_sections.py` with pure builders only. No Click imports.
2. Import `load_settings()` and `settings_section()` in `runner.py` inside `doctor()` to avoid startup import churn.
3. Add settings block to JSON data at `runner.py:4720-4730`.
4. Add concise human block after the Configuration section at `runner.py:4779-4783`.
5. Add migration helpers in `cli/workbench_app/slash.py`, near other built-in handlers:
   - `_handle_migrate_settings()`
   - `_next_backup_path(path: Path) -> Path`
   - `_has_dotted_keys(mapping: dict[str, object]) -> bool`
6. Register `_BuiltinSpec("migrate-settings", ...)` in `_BUILTIN_SPECS`.
7. Update `cli/workbench_app/tui/screens/doctor.py` to include `settings_section(load_settings(root))` lines.

**Run GREEN:**

```bash
.venv/bin/python -m pytest tests/test_doctor_sections.py tests/test_workbench_slash.py -q
.venv/bin/python -m pytest tests/test_system_prompt.py -q
```

**Commit:**

```bash
git add cli/doctor_sections.py runner.py cli/workbench_app/slash.py cli/workbench_app/tui/screens/doctor.py tests/test_doctor_sections.py tests/test_workbench_slash.py
git commit -m "feat(settings): add migration and doctor diagnostics"
```

---

## Final Verification

After P0.5 and its review pass:

```bash
.venv/bin/python -m pytest tests/
git status --short
git log --oneline --decorate -6
```

Expected:
- Full suite passes.
- `tests/test_system_prompt.py` remains byte-stable.
- Branch contains one plan commit plus five implementation commits.
- No provider adapter files changed.
- No secrets printed or committed.

Then offer to open a PR before moving to provider parity.
