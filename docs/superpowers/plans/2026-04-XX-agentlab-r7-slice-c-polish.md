# R7 Slice C — Polish (TDD expansion plan)

**Status:** draft, ready for execution
**Branch:** `claude/r7-workbench-agent` (continues from Slice B at `631dd23`)
**Depends on:** Slices A and B
**Master plan section:** R7.10–R7.15 in `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md`

## 0. Goal

After Slice C, the conversational Workbench survives restarts (auto-resume),
exposes a `agentlab conversation` headless CLI, refuses to start in
strict-live workspaces without a real provider key, increments the
`cost_ticker_usd` on every LLM turn, and surfaces a "context changed"
notice when the active config switches mid-conversation. R7.15
documentation lands as the final commit.

## 1. Architectural decisions (Slice C scope)

### 1.1 Auto-resume is opt-in, not auto

The R7 master plan said "Crash mid-conversation → reopening Workbench
resumes it." That's the right behavior for a conversational shell —
but the existing Workbench has multiple chat sessions per workspace
already (`SessionStore`), and silently picking up a stale conversation
on every reopen is too aggressive. Compromise:

- `WorkbenchSession.current_conversation_id` tracks the active id.
- On startup, **if** the most recent conversation in the store has
  any `pending` → `interrupted` tool calls (set by R7.3's load
  sweep), surface a one-line resume hint: `"Conversation conv_xyz was
  interrupted mid-tool-call. /resume to continue."` Don't auto-resume.
- If no interruption was detected, pre-existing behavior holds: each
  Workbench launch creates a fresh conversation. (B.7's
  `build_workbench_runtime` already does this.)
- A `/resume` slash handler (small addition) loads the previous
  conversation's history into `LLMOrchestrator.messages`.

This matches Claude Code's `/resume` UX and avoids the "I opened
Workbench yesterday and now it's confused about today's task"
failure mode.

### 1.2 Headless CLI is `agentlab conversation`, not a slash command

R7.11 calls for `agentlab conversation list/show/resume/export`. This
is a Click command group registered in `cli/commands/conversation.py`,
following the exact pattern established by `cli/commands/eval.py`
etc. — `register_conversation_commands(cli)` added to
`cli/commands/__init__.py:register_all`. No subprocess spawning; reads
SQLite directly via `ConversationStore`.

### 1.3 Strict-live integration is a startup gate

`cli/strict_live.py:MockFallbackError` exists. R1 wired exit-14
(`EXIT_MISSING_PROVIDER`) and exit-12 (`EXIT_MOCK_FALLBACK`) at the
CLI boundary for build/eval/optimize/deploy. The conversation
provider needs the same gate **at runtime build time**: if the
workspace has `permissions.strict_live: true` (a new settings.json
flag), and no API key is available for the chosen chat model, the
runtime construction raises `MockFallbackError`. The REPL catches
it, prints the standard error, and exits with `EXIT_MISSING_PROVIDER`.

Alternative considered and rejected: a per-workspace strict-live mode
that applies to `eval`/`build`/etc. too. That's a bigger redesign
than R7 should take on. The R7 setting `chat.strict_live` (or the
existing `permissions.strict_live` if R1 already established one;
need to re-check) only gates the conversation provider. R1's
behavior for individual commands is unchanged.

**Verification needed during execution:** does R1 already define a
workspace-level strict-live setting? Search for `strict_live` in
settings.json fixtures. If yes, reuse the same key. If no, introduce
`chat.strict_live` and document it.

### 1.4 Cost ticker uses the existing capabilities table

`cli/llm/capabilities.py` already has per-model `input_cost_per_1m`
and `output_cost_per_1m`. R7.13 wires
`OrchestratorResult.usage["input_tokens"]` and `["output_tokens"]`
through a small `compute_turn_cost(usage, model_id)` helper into
`WorkbenchSession.increment_cost(...)` after every turn.

The hookup happens in the same place as the conversation bridge:
right after `bridge.record_assistant_turn(result)` in
`_run_orchestrator_turn`. Keeps the side-effect surface tight.

### 1.5 Workspace-change notice forks instead of resets

R7.14 says "when `current_config_path` changes mid-conversation,
surface a context-changed notice and offer to fork (don't silently
mix contexts)." Forking = create a new conversation seeded with a
summary message from the previous one ("Continuing from conv_xyz
which was working with config configs/v003.yaml; now switched to
configs/v007.yaml.") The user can also opt to discard.

Trigger: a Workbench-side observer on `WorkbenchSession.update(current_config_path=...)`.
The session already serializes through one lock so the observer can
hook in cleanly. We add an `on_change` callback list.

### 1.6 Documentation lives next to the code

R7.15 produces:
- `docs/r7-workbench-as-agent.md` — quickstart, talking to Workbench,
  how the model picks tools, how permissions work, conversation
  export/share.
- `docs/r7-tool-permission-reference.md` — complete table of the 7
  tools, their default policy, and how to override.

No separate "tutorial" — the quickstart IS the tutorial. AgentLab's
`docs/` already has flat-file guides; R7's docs follow that pattern.

## 2. File structure (Slice C)

| File | Status | Purpose |
|---|---|---|
| `cli/workbench_app/session_state.py` | **Modify** | Add `current_conversation_id`, `on_change` observer hook |
| `cli/workbench_app/orchestrator_runtime.py` | **Modify** | Strict-live gate at construction; pass session to bridge |
| `cli/workbench_app/conversation_bridge.py` | **Modify** | Optional `on_assistant_turn` callback for cost-ticker hook |
| `cli/workbench_app/app.py` | **Modify** | Wire cost ticker; resume hint on startup; workspace-change notice |
| `cli/workbench_app/cost_calculator.py` | **Create** | `compute_turn_cost(usage, model_id) -> float` |
| `cli/workbench_app/conversation_resume.py` | **Create** | `/resume` slash handler + load_history helper |
| `cli/commands/conversation.py` | **Create** | Headless `agentlab conversation list/show/resume/export` |
| `cli/commands/__init__.py` | **Modify** | Register conversation commands |
| `tests/test_session_state_r7.py` | **Create** | New `current_conversation_id` field, on_change hook |
| `tests/test_cost_calculator.py` | **Create** | |
| `tests/test_conversation_resume.py` | **Create** | |
| `tests/commands/test_conversation_command.py` | **Create** | |
| `tests/test_orchestrator_runtime_strict_live.py` | **Create** | |
| `tests/test_app_r7_workspace_change.py` | **Create** | |
| `docs/r7-workbench-as-agent.md` | **Create** | |
| `docs/r7-tool-permission-reference.md` | **Create** | |

## 3. Slice C task breakdown

### C.1 — `WorkbenchSession.current_conversation_id` + `on_change` hook

**Test file**: `tests/test_session_state_r7.py`. Don't modify the
existing `tests/test_session_state.py` — additive only.

**Modifications to `cli/workbench_app/session_state.py`**:
- Add `current_conversation_id: str | None = None` to the dataclass.
- Add `"current_conversation_id"` to `_SERIALIZED_FIELDS`.
- Add a `_observers: list[Callable[[str, Any], None]]` field
  (private, excluded from compare/repr).
- Add `add_observer(self, fn)` and `remove_observer(self, fn)`
  methods.
- In `update(...)`, after the lock-guarded mutations and flush, call
  each observer with `(field_name, new_value)` for each changed
  field. The flush is already inside the lock; observers run
  *after* the lock is released to avoid reentrancy.
- In `increment_cost`, observers do NOT fire (cost changes are
  high-frequency and not interesting for the workspace-change
  notice).

**Tests:**
1. `test_current_conversation_id_defaults_none`
2. `test_current_conversation_id_round_trips_to_disk`
3. `test_observer_fires_on_field_change` — single-field update
4. `test_observer_fires_once_per_update_call_with_multiple_fields` —
   `update(a=1, b=2)` calls observer twice
5. `test_observer_does_not_fire_on_increment_cost`
6. `test_remove_observer_stops_callbacks`
7. `test_observer_exception_does_not_block_other_observers` — first
   observer raises; second still receives the change

**Commit:** `feat(workbench): WorkbenchSession.current_conversation_id + on_change observers (R7.C.1)`

### C.2 — `cost_calculator.py` + tests

**File**: `cli/workbench_app/cost_calculator.py`

```python
"""Map LLM usage tokens × model pricing → USD cost."""

from __future__ import annotations

from typing import Mapping

from cli.llm.capabilities import get_capability  # or whatever the lookup fn is


def compute_turn_cost(usage: Mapping[str, int], model_id: str) -> float:
    """Return USD cost for one turn's usage dict.

    Returns 0.0 when the model is unknown or usage is empty — never
    raises. Cost calculation should NEVER block the user.
    """
    if not usage:
        return 0.0
    cap = get_capability(model_id)
    if cap is None:
        return 0.0
    input_tokens = int(usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0) or usage.get("completion_tokens", 0))
    cost = (
        input_tokens / 1_000_000.0 * cap.input_cost_per_1m
        + output_tokens / 1_000_000.0 * cap.output_cost_per_1m
    )
    return round(cost, 6)
```

(The actual import path / capability lookup function name needs to
be verified during execution. Read `cli/llm/capabilities.py` for the
public API.)

**Tests:**
1. `test_known_model_computes_cost` — Sonnet 4.5 with 1000 input + 500 output → expected USD
2. `test_unknown_model_returns_zero`
3. `test_empty_usage_returns_zero`
4. `test_handles_openai_key_aliases` — `prompt_tokens`/`completion_tokens` work
5. `test_handles_anthropic_key_aliases` — `input_tokens`/`output_tokens` work
6. `test_zero_tokens_returns_zero_not_negative`
7. `test_partial_usage_only_input_or_only_output_works`

**Commit:** `feat(workbench): per-turn cost calculator from usage tokens (R7.C.2)`

### C.3 — Wire cost-ticker into `_run_orchestrator_turn`

**Modifications to `cli/workbench_app/app.py:_run_orchestrator_turn`**:
- Accept an optional `session: WorkbenchSession | None = None` kwarg
  AND `model_id: str | None = None` kwarg.
- After `bridge.record_assistant_turn(result)` (added in B.7), if
  both are present:
  - Compute `delta = compute_turn_cost(result.usage, model_id)`.
  - Call `session.increment_cost(delta)` inside a try/except (cost
    failures must never block UX).

**Modifications to `cli/workbench_app/orchestrator_runtime.py`**:
- Add `session: WorkbenchSession | None = None` and `active_model: str` (already
  there) to the `WorkbenchRuntime` dataclass — actually `session`
  should be `workbench_session: WorkbenchSession | None = None` to
  avoid colliding with the existing `session: Session` field.
- `build_workbench_runtime(...)` gets a new `workbench_session` kwarg.
- The two `_run_orchestrator_turn` call sites (chat path, follow-up
  path in `app.py`) thread `session=getattr(bundle, "workbench_session", None)`
  and `model_id=getattr(bundle, "model_id", None)` through.

**Tests** (`tests/test_app_r7_cost_ticker.py`):
1. `test_cost_ticker_advances_after_assistant_turn` — fake orchestrator
   returns usage; ticker increases by computed amount.
2. `test_cost_ticker_unchanged_when_no_session` — None session, no crash.
3. `test_cost_ticker_unchanged_when_no_model_id`
4. `test_cost_ticker_unchanged_when_unknown_model`
5. `test_cost_ticker_does_not_block_on_compute_failure` — patch
   compute_turn_cost to raise; turn still completes, ticker stays at
   prior value.

**Commit:** `feat(workbench): per-turn cost-ticker increment after assistant turns (R7.C.3)`

### C.4 — Strict-live gate in `build_workbench_runtime`

**Verification first:** search settings.json fixtures and R1
documentation for a workspace-level strict-live setting. If none
exists, introduce `permissions.strict_live: bool` on workspace
settings (purely additive — defaults to False).

**Modifications to `cli/workbench_app/orchestrator_runtime.py`**:
- Read settings (already done in `build_workbench_runtime`).
- If `settings.get("permissions", {}).get("strict_live")` is truthy
  AND the chosen model resolves to a `MockProvider` (or otherwise
  has no real key), raise `MockFallbackError` with a clear message:
  `"chat: strict-live workspace + no provider key. Set ANTHROPIC_API_KEY (or remove strict-live)."`

**Modifications to `cli/workbench_app/app.py`**:
- Wherever `build_workbench_runtime` is called inside a try/except
  (currently swallows everything — see `app.py:1222`), special-case
  `MockFallbackError` so it propagates to the CLI boundary.
- The CLI boundary (the `agentlab` entry point or `cli/cli.py`)
  already catches `MockFallbackError` and exits 14. Verify path.

**Tests** (`tests/test_orchestrator_runtime_strict_live.py`):
1. `test_strict_live_with_real_key_builds_successfully`
2. `test_strict_live_without_key_raises_mock_fallback_error`
3. `test_no_strict_live_without_key_builds_with_mock` — back-compat
4. `test_strict_live_message_mentions_anthropic_api_key`
5. `test_strict_live_setting_is_workspace_scoped` — two workspaces,
   only one strict; the other still builds.

**Commit:** `feat(workbench): strict-live gate refuses chat runtime without provider key (R7.C.4)`

### C.5 — `agentlab conversation` headless CLI

**File**: `cli/commands/conversation.py`

```python
"""`agentlab conversation` — headless conversation management."""

from __future__ import annotations

import json
import click

from cli.workbench_app.conversation_store import ConversationStore


def register_conversation_commands(cli: click.Group) -> None:

    @cli.group("conversation")
    def conversation_group() -> None:
        """Manage Workbench conversation history."""

    @conversation_group.command("list")
    @click.option("--limit", type=int, default=20)
    @click.option("--json", "json_output", is_flag=True)
    def conversation_list(limit: int, json_output: bool) -> None:
        store = _store()
        items = store.list_recent(limit=limit)
        if json_output:
            click.echo(json.dumps([_brief(c) for c in items], indent=2))
            return
        for c in items:
            click.echo(f"{c.id}  {c.created_at}  {c.model or '(no model)'}")

    @conversation_group.command("show")
    @click.argument("conversation_id")
    @click.option("--json", "json_output", is_flag=True)
    def conversation_show(conversation_id: str, json_output: bool) -> None:
        # ...

    @conversation_group.command("export")
    @click.argument("conversation_id")
    @click.option("--format", "fmt", type=click.Choice(["json", "markdown"]),
                  default="json")
    def conversation_export(conversation_id: str, fmt: str) -> None:
        # ...

    @conversation_group.command("resume")
    @click.argument("conversation_id")
    def conversation_resume(conversation_id: str) -> None:
        """Mark this conversation as the active one for the next REPL."""
        # Updates WorkbenchSession.current_conversation_id and exits.
        # The next `agentlab` REPL launch picks it up.
        # ...


def _store() -> ConversationStore:
    from runner import discover_workspace
    workspace = discover_workspace()
    if workspace is None:
        raise click.ClickException("No workspace found in current directory.")
    return ConversationStore(workspace.root / ".agentlab" / "conversations.db")


def _brief(c) -> dict:
    return {
        "id": c.id, "created_at": c.created_at,
        "updated_at": c.updated_at, "model": c.model,
        "message_count": len(c.messages),
    }
```

(Final shape pinned during TDD. The export-markdown formatter
should produce a clean transcript: headers per role, fenced
`tool_call` blocks, prompt-injection-guard-aware fencing for tool
results.)

**Modifications to `cli/commands/__init__.py`**:
- Add `from cli.commands.conversation import register_conversation_commands`
- Add `register_conversation_commands(cli)`

**Tests** (`tests/commands/test_conversation_command.py`) — use
`CliRunner` to drive the command:
1. `test_list_empty_workspace_shows_no_conversations`
2. `test_list_after_seeding_shows_one_line_per_conversation`
3. `test_list_json_output_round_trips`
4. `test_list_respects_limit`
5. `test_show_returns_full_history`
6. `test_show_unknown_id_exits_nonzero`
7. `test_export_json_round_trips`
8. `test_export_markdown_includes_role_headers`
9. `test_export_markdown_fences_tool_results_with_tool_result_tag`
   — prompt-injection guard alignment
10. `test_resume_updates_workbench_session_current_conversation_id`
11. `test_resume_unknown_id_exits_nonzero`
12. `test_command_outside_workspace_exits_nonzero`

**Commit:** `feat(cli): agentlab conversation list/show/resume/export headless command (R7.C.5)`

### C.6 — `/resume` slash handler + interrupted-turn surfacing

**File**: `cli/workbench_app/conversation_resume.py`

- `load_history(store, conversation_id) -> list[TurnMessage]` — reads
  the SQLite store, materializes into `cli.llm.types.TurnMessage`
  shape so `LLMOrchestrator.messages` can be hydrated.
- `format_resume_hint(conversation) -> str | None` — returns a
  one-line hint when the conversation has any tool_call rows in
  `interrupted` status (already tagged on store load by R7.3).
  Returns None otherwise.

**Modifications to `cli/workbench_app/app.py`**:
- On REPL startup (after `build_workbench_runtime`), check if there's
  a previous conversation with interrupted tool calls. If yes, echo
  the hint as a dim line.
- Register a `/resume` slash handler in
  `cli/workbench_app/slash.py` (or wherever slash handlers are
  registered) that takes an optional `<conversation_id>` arg —
  defaults to the most recent one. Loads history into
  `runtime.orchestrator.messages` and updates
  `runtime.workbench_session.current_conversation_id`.

**Tests** (`tests/test_conversation_resume.py`):
1. `test_load_history_yields_turn_messages_in_position_order`
2. `test_format_resume_hint_returns_message_when_interrupted_calls_exist`
3. `test_format_resume_hint_returns_none_when_no_interruptions`
4. `test_format_resume_hint_includes_conversation_id`
5. `test_load_history_handles_empty_conversation`

(The slash-handler test belongs in whatever existing slash test file
is established — append rather than create new.)

**Commit:** `feat(workbench): /resume slash handler and interrupted-turn hint (R7.C.6)`

### C.7 — Workspace-change notice via WorkbenchSession observer

**Modifications to `cli/workbench_app/app.py`**:
- After building the runtime, register an observer on the
  `workbench_session`:
  ```python
  def _on_session_change(field, value):
      if field == "current_config_path" and value is not None:
          out(theme.warning(
              f"  ⚠  Active config switched to {value}. "
              f"The current conversation may be working with stale context. "
              f"Type /fork to start a new conversation, or /resume {old_id} to keep going."
          ))
  workbench_session.add_observer(_on_session_change)
  ```
  (Capture the previous-config-path in a closure; only fire when it
  actually changes from a non-None previous value.)

- Add a `/fork` slash handler that calls
  `bridge._store.create_conversation(...)`, sets
  `workbench_session.current_conversation_id = new_id`, swaps the
  bridge target, and clears `orchestrator.messages` (seeded with a
  short summary text noting the previous conversation id).

**Tests** (`tests/test_app_r7_workspace_change.py`):
1. `test_observer_fires_when_config_path_changes` — set initial
   path, call session.update with new path, observer recorded.
2. `test_observer_does_not_fire_on_first_set` — None → "x.yaml"
   should NOT trigger the warning (initial load isn't a "change").
3. `test_fork_creates_new_conversation_and_resets_messages`
4. `test_fork_preserves_old_conversation_in_store` — old id still
   readable via `get_conversation`.

**Commit:** `feat(workbench): workspace-change notice and /fork conversation (R7.C.7)`

### C.8 — Documentation

**Files**: `docs/r7-workbench-as-agent.md`, `docs/r7-tool-permission-reference.md`.

Quickstart covers:
1. What is conversational Workbench (one paragraph).
2. Talk to Workbench: examples for the 3 most useful queries
   ("evaluate the current config", "improve safety", "deploy the
   best canary candidate").
3. How permissions work — read-only auto, mutating asks, persisting
   approvals.
4. How to view past conversations: `agentlab conversation list/show`.
5. How to share a transcript: `agentlab conversation export <id> --format markdown`.
6. Strict-live: setting + behavior + error message.

Tool-permission reference: a table with columns Tool, Default
Policy, Permission Action String, How to Override (settings.json
example).

No tests — docs are docs.

**Commit:** `docs: R7 conversational Workbench quickstart and tool-permission reference (R7.C.8)`

## 4. Slice C acceptance

- All C.1–C.7 test files green.
- Existing test suite stays green (no regressions in
  `_run_orchestrator_turn`, `WorkbenchSession`, or any `cli/commands/*`).
- Manual: open Workbench, run a turn, observe `cost_ticker_usd`
  advances in the status bar.
- Manual: kill Workbench mid-tool-call (Ctrl-C while `Deploy` is
  running), reopen, see the resume hint, type `/resume`, conversation
  comes back with the interrupted call visible.
- Manual: `agentlab conversation export <id> --format markdown`
  produces a clean transcript suitable for paste-into-Slack.
- Manual: `permissions.strict_live: true` in workspace settings +
  no API key → REPL refuses to start with exit 14 and a clear
  message.

## 5. Risks specific to Slice C

- **Cost-table drift.** If Anthropic/OpenAI change pricing,
  `cli/llm/capabilities.py` becomes stale. The cost ticker would
  silently report the wrong number. Mitigation: a one-line note in
  the docs that the ticker is an estimate, plus a future periodic
  audit (out of R7 scope).
- **Resume hydration leaks tool-result content into context.** A
  `/resume` of a conversation that ran 30 expensive evals will
  blow up the context window on the next turn. Mitigation: the
  resume helper truncates each tool_call's result to a short
  summary when loading into orchestrator messages. Full history
  stays in the SQLite store for inspection via `agentlab
  conversation show`.
- **Forked conversations multiply storage.** A user who switches
  workspaces 10 times in a session creates 10 conversations.
  Acceptable — SQLite handles it — but `agentlab conversation list`
  could get noisy. Mitigation: list defaults to limit=20.
- **Observer reentrancy.** If `_on_session_change` calls back into
  `session.update`, we deadlock (observers run after lock release,
  but the `update()` they trigger acquires the lock fresh). The
  observer should be read-only. Test enforces this implicitly.
- **MockProvider detection.** `_select_chat_model` returns a
  `_ChatModelChoice`; we need to know whether the resolved model
  has a real key. The current shape carries `api_key: str | None`.
  C.4's gate keys off `choice.api_key is None and settings.strict_live`.
  Verify during implementation that this is the right signal —
  some keys come from env vars not the choice object.

## 6. Out of scope (handled in future releases or never)

- Multi-conversation simultaneous chat (one active per Workbench).
- Conversation search / full-text indexing.
- Conversation sharing via web URL.
- Per-user conversation isolation (single-user assumption today).
- Voice / multimodal input.
- Hooks specifically for conversation events (R7 doesn't add new
  hook surfaces; existing PreToolUse/PostToolUse fire for AgentLab
  tools the same as for any other tool).
