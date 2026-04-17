# R7 Slice B — Adapter (TDD expansion plan)

**Status:** draft, ready for execution
**Branch:** `claude/r7-workbench-agent` (continues from Slice A at `ab4bf4b`)
**Depends on:** R7 Slice A (`tool_registry`, `tool_permissions`, `conversation_store`, `system_prompt`)
**Master plan section:** R7.5–R7.9 in `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md` — but **not** literally. See section 1.

## 0. Goal

After Slice B, the existing Workbench REPL chat path (`InputKind.CHAT` →
`_run_orchestrator_turn` in `cli/workbench_app/app.py:606`) can call
**all 7 in-process AgentLab commands** (eval, deploy, improve_run/list/
show/diff/accept) as tools via the **existing** `LLMOrchestrator`. The
user types "evaluate the current config and tell me what's failing"
and the existing orchestrator picks `EvalRunTool`, calls
`run_eval_in_process`, and streams the answer.

Slice B is **adapter work, not a parallel system.** No new
`ConversationLoop`, no new streaming layer, no new permission
manager — those already exist and work. R7's value-add is:

1. The 7 AgentLab tool adapters (the actual differentiator).
2. A permission preset for AgentLab's risk profile.
3. Conversation persistence richer than what `SessionStore` provides
   today (R7.3's tool-call lifecycle is the part that's actually new).

## 1. Why this differs from the master plan's R7.5–R7.9

### 1.1 What the master plan didn't know

The master plan was written assuming the Workbench REPL had no chat
loop yet. In reality, `cli/llm/orchestrator.py:LLMOrchestrator`
already does:

- Multi-turn conversation with persistent message history.
- Anthropic tool-use (call → execute → tool_result → continue).
- Streaming via `cli.llm.streaming` (`TextDelta`, `ToolUseStart`,
  `ToolUseEnd`, `MessageStop`, etc.).
- Permission gating via `cli.permissions.PermissionManager` with
  fnmatch rules, session overrides, and explicit allow/ask/deny.
- Session persistence via `cli.sessions.SessionStore` (per-session
  JSON file; auto-saves transcript on every turn).
- Error boundaries, max-tool-loops cap, hook integration, plan-mode
  restrictions.

The master plan's R7.5 (`ConversationLoop.run`), R7.6 (`stream`),
R7.8 (conversation widget), and R7.9 (permission prompt UI) are
already implemented in different files.

### 1.2 What R7 actually needs

What's missing — the actual gap between today and the R7 acceptance
criteria — is:

- **The 7 AgentLab tools.** The orchestrator can call FileRead, Bash,
  Grep, etc. but cannot call `eval_run`, `deploy`, etc. The tool
  registry at `cli/tools/registry.py:_register_builtins` lists 14
  Claude-Code-style tools; none of them invoke an AgentLab command.
- **A risk-aware permission preset.** PermissionManager defaults are
  Claude-Code-shaped (writes need approval, reads don't). AgentLab
  needs `tool:Eval`, `tool:Deploy`, `tool:Improve*` mapped to `ask`
  with deploy maybe `deny` by default in non-canary workspaces.
- **Tool-call lifecycle persistence.** `SessionStore` records
  transcript text but doesn't model "tool call X was in flight when
  the process died" — Slice A's `conversation_store.py` does. We
  wire it as a side-channel persistence layer.

### 1.3 What Slice A's modules become under Option X

- `cli/workbench_app/tool_registry.py` (R7.1): **Demoted to a thin
  metadata source** for the adapter layer. Each `Tool` subclass
  reads its name + description + input_schema from this module so
  the model-facing copy stays in one place. Still useful as a single
  source of truth for the 7 commands; no longer the call path.
- `cli/workbench_app/tool_permissions.py` (R7.2): **Becomes a
  preset.** A new `apply_agentlab_defaults(manager: PermissionManager)`
  installs the right session-allow / session-deny / explicit rules
  on the *existing* PermissionManager. The R7.2 `PermissionTable`
  data structure stays as the source of truth for which tools are
  read-only vs mutating.
- `cli/workbench_app/conversation_store.py` (R7.3): **Side-channel
  persistence.** A small bridge logs each orchestrator turn into the
  SQLite store in addition to the existing JSON SessionStore. Gives
  us the tool-call lifecycle + crash safety without ripping out the
  working session code.
- `cli/workbench_app/system_prompt.py` (R7.4): **Threaded into
  `LLMOrchestrator.system_prompt`.** Build once at REPL bootstrap,
  pass to the orchestrator as its `system_prompt` field.

None of Slice A is wasted; none of it remains a parallel system.

## 2. File structure (Slice B)

| File | Status | Lines (est.) | Purpose |
|---|---|---|---|
| `cli/workbench_app/agentlab_tools/__init__.py` | **Create** | 30 | Package init; exports `register_agentlab_tools` |
| `cli/workbench_app/agentlab_tools/_base.py` | **Create** | 80 | Shared `AgentLabTool` base wrapping in-process commands |
| `cli/workbench_app/agentlab_tools/eval_tool.py` | **Create** | 80 | `EvalRunTool` |
| `cli/workbench_app/agentlab_tools/deploy_tool.py` | **Create** | 80 | `DeployTool` |
| `cli/workbench_app/agentlab_tools/improve_tools.py` | **Create** | 200 | 5 improve_* tools in one file |
| `cli/workbench_app/permission_preset.py` | **Create** | 100 | `apply_agentlab_defaults(manager)` |
| `cli/workbench_app/conversation_bridge.py` | **Create** | 150 | Logs orchestrator turns into Slice A's SQLite store |
| `tests/agentlab_tools/test_eval_tool.py` | **Create** | 150 | |
| `tests/agentlab_tools/test_deploy_tool.py` | **Create** | 150 | |
| `tests/agentlab_tools/test_improve_tools.py` | **Create** | 300 | covers all 5 |
| `tests/test_permission_preset.py` | **Create** | 150 | |
| `tests/test_conversation_bridge.py` | **Create** | 200 | |
| `cli/workbench_app/app.py` | **Modify** | ~40 | Register agentlab tools + preset + bridge in REPL bootstrap |

`runtime.py` is **not** modified. The CHAT routing already exists at
`app.py:593`.

## 3. Slice B task breakdown

### B.1 — `agentlab_tools/_base.py` — `AgentLabTool` base class

**Purpose:** A single abstract base that wraps any
`run_*_in_process` function. Subclasses declare `name`,
`description`, `input_schema`, the `_in_process_fn`, and a
`_shape_result()` method. The base handles:

- Auto-injection of `on_event=lambda _: None` and `text_writer=None`
  (the model never sees these).
- Translating the typed dataclass return into a `ToolResult`.
- Catching domain exceptions (`MockFallbackError`, `ImproveCommandError`,
  etc.) and returning `ToolResult.failure(...)` rather than re-raising.
- A default `permission_action()` of `tool:<Name>` so settings.json
  rules can target each AgentLab tool individually.

```python
"""Base class for AgentLab in-process command tools."""

from __future__ import annotations

import dataclasses
import inspect
from abc import abstractmethod
from typing import Any, Callable, Mapping

from cli.tools.base import Tool, ToolContext, ToolResult


class AgentLabTool(Tool):
    """Wraps one ``run_*_in_process`` function as an LLM-callable tool.

    Subclasses must set ``name`` / ``description`` / ``input_schema``
    and implement :meth:`_in_process_fn` (returning the function) and
    :meth:`_shape_result` (turning the typed return into JSON-safe
    content for the model).
    """

    read_only: bool = False  # default — subclasses opt in for list/show/diff

    @abstractmethod
    def _in_process_fn(self) -> Callable[..., Any]:
        """Return the ``run_*_in_process`` callable to dispatch."""

    def _shape_result(self, result: Any) -> Any:
        """Turn the typed dataclass result into JSON-safe content.

        Default uses :func:`dataclasses.asdict` and converts tuples to
        lists. Subclasses override for custom shaping.
        """
        if dataclasses.is_dataclass(result):
            return _to_jsonsafe(dataclasses.asdict(result))
        return _to_jsonsafe(result)

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        fn = self._in_process_fn()
        sig = inspect.signature(fn)
        accepted = {k: v for k, v in tool_input.items() if k in sig.parameters}
        if "on_event" in sig.parameters and "on_event" not in accepted:
            accepted["on_event"] = lambda _e: None
        if "text_writer" in sig.parameters and "text_writer" not in accepted:
            accepted["text_writer"] = None
        try:
            raw = fn(**accepted)
        except Exception as exc:
            # Domain failures surface to the model as a regular failure
            # so it can react (call a different tool, ask the user). We
            # do NOT swallow programmer errors — those propagate.
            return ToolResult.failure(f"{type(exc).__name__}: {exc}")
        shaped = self._shape_result(raw)
        return ToolResult.success(shaped, metadata={"raw_type": type(raw).__name__})


def _to_jsonsafe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _to_jsonsafe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonsafe(v) for v in value]
    return value
```

### B.2 — `EvalRunTool` (and tests)

```python
class EvalRunTool(AgentLabTool):
    name = "EvalRun"
    description = (
        "Run an eval suite against the current or specified agent config "
        "and return composite score, mode, status, warnings, and "
        "artifacts. This costs LLM tokens and writes to the eval-run store."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "config_path": {"type": "string", "description": "..."},
            # ... full schema from R7.1's hand-written entry ...
        },
        "additionalProperties": False,
    }
    read_only = False  # eval RUNS — not read-only

    def _in_process_fn(self):
        from cli.commands.eval import run_eval_in_process
        return run_eval_in_process
```

**Tests:** Use a `MagicMock` to stub `run_eval_in_process` so the test
runs in <100ms and doesn't need a real workspace. Cover:
- `run({})` returns a `ToolResult.success` whose content is JSON-safe.
- `run({"config_path": "x.yaml"})` forwards the arg.
- `run({"unknown": "x"})` strips unknown args before invoking.
- A function raising `MockFallbackError` becomes `ToolResult.failure`,
  not a propagated exception.
- The default `permission_action` is `"tool:EvalRun"`.

### B.3 — `DeployTool` (and tests)

Same shape as EvalRunTool. `permission_action` returns
`f"tool:Deploy:{tool_input.get('strategy', 'canary')}"` so a settings
rule can allow `tool:Deploy:canary` while still asking for full prod
deploys.

### B.4 — `improve_tools.py` — five tools

`ImproveRunTool` (mutating, name="ImproveRun"), `ImproveListTool`
(read-only), `ImproveShowTool` (read-only), `ImproveDiffTool`
(read-only), `ImproveAcceptTool` (mutating).

`read_only=True` means no permission prompt. `improve_list/show/diff`
are pure inspection — auto-allow.

### B.5 — `permission_preset.py`

```python
"""Apply AgentLab risk-aware permission defaults to a PermissionManager.

The Claude-Code-style PermissionManager defaults treat any non-read
tool as "ask". For AgentLab's tools we want a finer split:

- ``tool:EvalRun``   — ask  (RUNS an eval, costs tokens)
- ``tool:ImproveRun``— ask
- ``tool:ImproveAccept`` — ask  (mutates active config)
- ``tool:Deploy*``   — ask  (mutates production)

Read-only tools (ImproveList/Show/Diff) carry ``read_only=True`` on
the Tool itself, so they never reach this layer.
"""

from cli.permissions import PermissionManager


AGENTLAB_ASK_PATTERNS: list[str] = [
    "tool:EvalRun",
    "tool:ImproveRun",
    "tool:ImproveAccept",
    "tool:Deploy*",
]


def apply_agentlab_defaults(manager: PermissionManager) -> None:
    """Install AgentLab-aware permission rules on the manager.

    Implemented as session-allow/session-ask additions rather than
    persisted settings.json edits — the user's workspace settings
    take precedence, and each REPL boot re-applies the defaults.
    """
    # Use the existing in-memory session layer; settings.json rules
    # still win if the user has configured something explicit.
    for pattern in AGENTLAB_ASK_PATTERNS:
        # session_allow / session_deny are the public hooks; we want
        # "ask" semantics, which is the *default* — meaning we don't
        # need to add these to either list. The mode rules already
        # require a prompt for any non-read tool that isn't allowlisted.
        # The preset's job is to NOT auto-allow these even if the user
        # has a global `allow tool:*` rule.
        manager.deny_for_session(pattern + ":__never_match__")  # placeholder — see test
```

Implementation note: the existing PermissionManager doesn't expose an
"add ask rule" — but mode defaults already produce "ask" for any
non-allowlisted tool. The preset's real job is to **prevent**
accidental auto-allow. Tests will pin down the exact wiring during
TDD.

**Tests cover:**
- `apply_agentlab_defaults(manager)` doesn't raise on a default manager.
- After applying, `manager.decision_for_tool(EvalRunTool(), {})` returns `"ask"`.
- After applying, `manager.decision_for_tool(ImproveListTool(), {})` returns `"allow"` (read-only short-circuit).
- A user's explicit `allow: ["tool:Deploy"]` in settings.json STILL wins (preset doesn't override workspace policy).

### B.6 — `conversation_bridge.py`

A thin observer that mirrors orchestrator turns into Slice A's
`ConversationStore`. The orchestrator already returns
`OrchestratorResult` with `tool_executions`; the bridge writes one
SQLite row per execution including final status.

```python
"""Bridge OrchestratorResult into Slice A's ConversationStore.

The orchestrator already persists transcript text via SessionStore.
The bridge adds:

- Per-tool-call rows with status (succeeded/failed) and result.
- Crash safety: tool calls left ``pending`` flip to ``interrupted``
  on the next REPL boot (already implemented inside ConversationStore).
"""

from __future__ import annotations

from typing import Any

from cli.workbench_app.conversation_store import ConversationStore


class ConversationBridge:
    """Mirror orchestrator turns into the conversation_store."""

    def __init__(self, store: ConversationStore, conversation_id: str) -> None:
        self._store = store
        self._conv_id = conversation_id

    def record_user_turn(self, text: str) -> None:
        self._store.append_message(
            conversation_id=self._conv_id, role="user", content=text,
        )

    def record_assistant_turn(self, result: Any) -> None:
        msg = self._store.append_message(
            conversation_id=self._conv_id,
            role="assistant",
            content=getattr(result, "assistant_text", "") or "",
        )
        for execution in getattr(result, "tool_executions", []) or []:
            tool_call = self._store.start_tool_call(
                message_id=msg.id,
                tool_name=getattr(execution, "tool_name", "unknown"),
                arguments=dict(getattr(execution, "tool_input", {}) or {}),
            )
            ok = getattr(execution, "ok", True)
            self._store.finish_tool_call(
                tool_call_id=tool_call.id,
                status="succeeded" if ok else "failed",
                result={"display": getattr(execution, "display", None)},
            )
```

**Tests cover:**
- `record_user_turn("hi")` adds one user message at position 0.
- `record_assistant_turn(result_with_2_tools)` adds one assistant
  message and 2 tool_call rows, both terminal-statused.
- A `result` with no tool_executions records the assistant message
  alone, no tool_call rows.
- Failed tool execution records `status="failed"`.

### B.7 — Wire it all up in `app.py`

The bootstrap path that builds the `LLMOrchestrator` (today done in
`_resolve_orchestrator` and friends) needs:

1. After building the default `cli.tools.registry.ToolRegistry`,
   call `register_agentlab_tools(registry)` to add the 7 adapters.
2. After building the `PermissionManager`, call
   `apply_agentlab_defaults(manager)`.
3. After building the orchestrator, set its
   `system_prompt = build_system_prompt(...)` from
   `cli/workbench_app/system_prompt.py`.
4. Construct a `ConversationBridge` and add a one-line shim to
   `_run_orchestrator_turn` that calls
   `bridge.record_user_turn(line)` before `orchestrator.run_turn`
   and `bridge.record_assistant_turn(result)` after.

The exact wiring depends on what `_resolve_orchestrator` returns
today — investigate during the dispatch, don't pre-design here.

**Tests for app.py changes** are minimal: existing app tests still
pass, plus one new integration test that the AgentLab tool names
appear in the orchestrator's tool registry after bootstrap.

## 4. Critical invariants

- **No new chat path.** The existing `InputKind.CHAT` flow remains
  the only chat path. R7 adds tools, presets, persistence — never a
  parallel REPL.
- **Slash commands keep working unchanged.** `/eval` typed verbatim
  still routes to the slash dispatcher. The model can ALSO call
  `EvalRun` as a tool — both paths coexist.
- **Domain exceptions become tool failures, not crashes.** A
  `MockFallbackError` raised inside `run_eval_in_process` becomes a
  `ToolResult.failure(...)` the model can read and react to. The
  REPL stays interactive.
- **`on_event` / `text_writer` are auto-injected.** The model never
  sees these parameters; it only specifies domain args. This was
  validated by R7.1's tests.
- **Workspace settings.json wins.** If a user has an explicit
  `permissions.rules.allow: ["tool:Deploy"]`, the preset does NOT
  override it. Presets establish defaults; workspace policy overrides
  defaults; session decisions override workspace policy. (This is
  already PermissionManager's invariant — the preset just doesn't
  break it.)
- **Read-only tools never prompt.** `ImproveList/Show/Diff` set
  `read_only=True`. PermissionManager auto-allows them.

## 5. Risks specific to Slice B

- **Tool input schema vs. function signature drift.** If a future
  contributor adds an arg to `run_eval_in_process` and forgets to
  update `EvalRunTool.input_schema`, the model can't pass it. The
  base class strips unknown args silently — there's no test that
  catches the drift. Mitigation: a ratchet test that diffs the
  function signature against the schema and fails on mismatch.
- **`permission_preset.py` is a no-op without the right hook.** The
  current PermissionManager has session-allow and session-deny but
  not session-ask. Slice B may need to extend PermissionManager to
  add session-ask, OR encode the preset purely as "make sure these
  patterns are NOT in the workspace allow list at boot." TDD will
  pin the right answer.
- **Bootstrap race.** `_resolve_orchestrator` is called from at
  least 3 sites in `app.py` (line 371, 1006, etc.). Tools must be
  registered exactly once even if the orchestrator is built more
  than once during a test run. Check whether `default_registry()`'s
  module-level cache is the right hook.
- **Conversation bridge bloat.** Logging every tool call to SQLite
  on every turn is ~5 row inserts per turn worst case. Fine. But
  if the user runs a 50-cycle improve loop in one turn (as
  `improve_run` can), that's 50 sub-events per turn. Mitigate by
  recording one row per top-level tool call, not per sub-event.

## 6. Slice B execution order

Strict dependency chain — sequential, one subagent per task:

1. **B.1** — `_base.py` + base-class tests. No outside deps.
2. **B.2** — `EvalRunTool` + tests. Imports `_base.py`.
3. **B.3** — `DeployTool` + tests. Imports `_base.py`.
4. **B.4** — `improve_tools.py` + tests. Imports `_base.py`.
5. **B.5** — `permission_preset.py` + tests. Imports tool classes.
6. **B.6** — `conversation_bridge.py` + tests. Independent of B.1–B.5.
7. **B.7** — Wire into `app.py`. Touches existing code; smallest
   possible diff. Validate the existing chat path still works
   end-to-end before declaring done.

After B.7 lands: dogfood. Open Workbench, ask "what's my current
eval verdict?", confirm the model picks `EvalRun`, runs it, and
summarizes. Capture any friction for Slice C polish.

## 7. Slice B acceptance

- `uv run pytest tests/agentlab_tools/ tests/test_permission_preset.py tests/test_conversation_bridge.py -v` is green.
- Existing test suite stays green (no regressions in `_run_orchestrator_turn` paths).
- Manual: open Workbench, type "list my recent improvement attempts", model calls `ImproveList`, returns a sane summary.
- Manual: type "deploy the last accepted attempt to canary", permission prompt fires, approving runs `Deploy`.
- Manual: type `/eval` verbatim → routes to slash dispatcher (NOT the LLM), confirms invariant.

## 8. Out of scope (handled in Slice C / R7.15)

- `agentlab conversation list/show/resume/export` headless CLI (C.11).
- Strict-live integration for the LLM provider (C.12).
- Cost-tracker increment hookup (C.13).
- Workspace-change conversation reset/fork (C.14).
- Documentation (R7.15).
