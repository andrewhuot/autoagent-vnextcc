# P4 Sessions And Paste Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship P4 Claude-Code-parity session storage, resume/fork UX, and paste/image externalization without colliding with the current `master` work or regressing existing session/conversation behavior.

**Architecture:** Keep the existing SQLite `ConversationStore` readable, but introduce a new append-only JSONL `SessionStore` rooted at `Settings.sessions.root` for forward-looking persistence. Preserve the current `cli.sessions` public import path by promoting `cli/sessions.py` into a package with compatibility re-exports, then layer fork, picker, migration, and paste/image helpers as pure modules with focused tests. Input routing remains the single classification point, but paste/image plumbing is additive so P1 router work can land first and P4 can rebase on top.

**Tech Stack:** Python 3.11, `pytest`, stdlib `json`/`hashlib`/`pathlib`/`uuid`, `prompt_toolkit`, Textual widgets, optional Pillow (`vision` extra).

---

## Implementation Notes

- Work in `/Users/andrew/Desktop/agentlab/.claude/worktrees/p4-sessions-paste` on branch `claude/cc-parity-p4`.
- Do not modify tracked files in the root `master` worktree.
- Preserve `tests/test_system_prompt.py` byte-for-byte.
- Prefer extending existing modules over introducing new abstractions unless the abstraction is required by multiple tasks.
- `cli/sessions.py` is already imported widely. Favor package promotion with re-exports over a sweeping rename.
- Session JSONL root must come from `Settings.sessions.root`, defaulting to `~/.agentlab/projects`.
- Paste inline threshold must come from settings. The schema currently exposes `Paste.inline_threshold_lines`; P4 needs `inline_threshold_bytes` added without breaking older config.
- Migration must respect `AGENTLAB_NO_MIGRATION=1`.
- `cli/workbench_app/input_router.py` is the one overlap risk with P1. If P1 lands router changes first, replay the P4 patch on top rather than competing on the same hunk.

## Task 0: Establish The Compatibility Surface

**Files:**
- Modify: `cli/settings/schema.py`
- Modify: `cli/settings/__init__.py`
- Modify: `cli/sessions.py` or replace with `cli/sessions/__init__.py`
- Test: existing import-heavy tests that reference `cli.sessions`

**Step 1: Write the failing test**

Add/adjust a lightweight test covering:
- `Settings().paste.inline_threshold_bytes` default is `2048`
- `Settings().paste.inline_threshold_lines` still validates for backward compatibility if retained
- `from cli.sessions import SessionStore` still resolves after package promotion

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_settings_loader.py tests/test_sessions.py -q`

Expected: FAIL because the new settings field and/or compatibility import path do not exist yet.

**Step 3: Write minimal implementation**

- Extend `Paste` settings with `inline_threshold_bytes: int = 2048`
- Preserve the old field long enough to avoid breaking existing settings loads
- Promote `cli/sessions.py` into a package only if needed for `cli/sessions/store.py`; keep `Session`, `SessionEntry`, and `SessionStore` import-compatible from `cli.sessions`

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_settings_loader.py tests/test_sessions.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add cli/settings/schema.py cli/settings/__init__.py cli/sessions.py cli/sessions/__init__.py tests/test_settings_loader.py tests/test_sessions.py
git commit -m "refactor(sessions): preserve compatibility surface"
```

## Task 1: JSONL Session Store (P4.1)

**Files:**
- Create: `cli/sessions/store.py`
- Modify: `cli/sessions/__init__.py`
- Test: `tests/test_session_jsonl_store.py`

**Step 1: Write the failing test**

Cover:
- `create(workspace_root)` generates UUID session ids and deterministic slugs
- slug collisions across distinct normalized paths append a 4-char hash suffix
- `append()` + `load()` round-trip turn records
- loader drops only a final partial JSON line and treats earlier corruption as fatal
- concurrent append safety (multiple threads appending complete JSON objects)

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_session_jsonl_store.py -q`

Expected: FAIL with missing module/classes or failing behavior assertions.

**Step 3: Write minimal implementation**

- Implement `SessionStore(root: Path)`
- Define typed records for persisted turn lines and summaries
- Use append-only writes with `open(..., "a", encoding="utf-8")`, flush, and `os.fsync`
- Stream JSONL on load; if the final line is partial/invalid, drop it with a warning
- Implement deterministic workspace slug generation with overflow handling

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_session_jsonl_store.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add cli/sessions/__init__.py cli/sessions/store.py tests/test_session_jsonl_store.py
git commit -m "feat(sessions): add append-only jsonl store"
```

## Task 2: Session Forking (P4.2)

**Files:**
- Create: `cli/sessions/fork.py`
- Modify: `cli/workbench_app/slash.py`
- Modify: existing slash registration/tests if needed
- Test: `tests/test_session_fork.py`

**Step 1: Write the failing test**

Cover:
- forking at explicit turn `N` copies prefix `[0..N]`
- default fork uses the current last turn
- first line in the new session is metadata with `forked_from` and `forked_at_turn`
- original session is unchanged

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_session_fork.py -q`

Expected: FAIL due to missing module/command behavior.

**Step 3: Write minimal implementation**

- Build `fork(session_id, *, at_turn: int) -> Session`
- Register `/fork [turn_index]` in `cli/workbench_app/slash.py`
- Keep the slash handler thin: resolve current session id, delegate to `cli.sessions.fork`

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_session_fork.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add cli/sessions/fork.py cli/workbench_app/slash.py tests/test_session_fork.py
git commit -m "feat(sessions): add fork support"
```

## Task 3: Resume Picker Data + Widget (P4.3)

**Files:**
- Create: `cli/sessions/picker.py`
- Create: `cli/workbench_app/tui/widgets/resume_picker.py`
- Modify: `cli/workbench_app/resume_slash.py`
- Modify: `cli/workbench_app/conversation_resume.py` if picker metadata needs shared helpers
- Test: `tests/test_resume_picker.py`

**Step 1: Write the failing test**

Cover only the pure helper:
- rows ordered by most recent modification
- summary prefers session-level summary when present, otherwise first user message
- last user preview is truncated/readable
- empty workspace returns `[]`

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_resume_picker.py -q`

Expected: FAIL because helper does not exist yet.

**Step 3: Write minimal implementation**

- Implement `build_picker_rows(store, workspace_root)`
- Add a small Textual widget using existing widget patterns (`message_list.py`, etc.)
- Update `/resume` so no arg opens the picker and `/resume <uuid>` still loads directly

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_resume_picker.py tests/test_resume_slash.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add cli/sessions/picker.py cli/workbench_app/tui/widgets/resume_picker.py cli/workbench_app/resume_slash.py tests/test_resume_picker.py tests/test_resume_slash.py
git commit -m "feat(workbench): add resume picker"
```

## Task 4: SQLite To JSONL Migration (P4.4)

**Files:**
- Modify: `cli/workbench_app/conversation_store.py`
- Modify: `cli/workbench_app/conversation_resume.py`
- Modify: runtime/bootstrap entrypoints that create the conversation store
- Create or modify: migration helper near `cli/sessions/store.py` if cleaner
- Test: `tests/test_session_migration.py`

**Step 1: Write the failing test**

Cover:
- SQLite DB with `N` conversations migrates to `N` JSONL session files
- marker file prevents re-running successful migration
- failed migration leaves the SQLite DB readable and does not leave the system in partial-success state
- `AGENTLAB_NO_MIGRATION=1` skips migration and keeps fallback reads working

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_session_migration.py -q`

Expected: FAIL because migration path is missing or incomplete.

**Step 3: Write minimal implementation**

- Add one-time migration invoked during workbench startup
- Backup SQLite DB before copying any history
- Create a marker file only after all sessions are emitted successfully
- Preserve fallback reads from SQLite when JSONL does not yet exist

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_session_migration.py tests/test_conversation_resume.py tests/test_resume_slash.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add cli/workbench_app/conversation_store.py cli/workbench_app/conversation_resume.py cli/workbench_app/orchestrator_runtime.py tests/test_session_migration.py tests/test_conversation_resume.py tests/test_resume_slash.py
git commit -m "feat(sessions): migrate sqlite history to jsonl"
```

## Task 5: Paste Store + Placeholder Expansion (P4.5)

**Files:**
- Create: `cli/paste/store.py`
- Create: `cli/paste/placeholders.py`
- Modify: `cli/workbench_app/input_router.py`
- Modify: any message-send plumbing that builds the final model payload
- Test: `tests/test_paste_store.py`
- Test: `tests/test_paste_placeholders.py`
- Update: `tests/test_workbench_input_router.py`

**Step 1: Write the failing test**

Cover:
- identical pasted text deduplicates by content hash
- placeholder rendering uses numbered labels and line counts
- `expand_placeholders()` restores original pasted content for the model send path
- router replaces oversized bracketed paste content with a placeholder but leaves small pastes inline

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_paste_store.py tests/test_paste_placeholders.py tests/test_workbench_input_router.py -q`

Expected: FAIL because paste helpers/router behavior do not exist.

**Step 3: Write minimal implementation**

- Build content-addressed text store under `.agentlab/pastes`
- Keep placeholder numbering session-local/display-local while content ids remain hash-based
- Extend router/input path for bracketed paste payloads larger than `Settings.paste.inline_threshold_bytes`
- Ensure the model receives fully expanded content even when the visible transcript shows placeholders

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_paste_store.py tests/test_paste_placeholders.py tests/test_workbench_input_router.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add cli/paste/store.py cli/paste/placeholders.py cli/workbench_app/input_router.py tests/test_paste_store.py tests/test_paste_placeholders.py tests/test_workbench_input_router.py
git commit -m "feat(paste): store large pastes out of band"
```

## Task 6: Clipboard Image Capture (P4.6)

**Files:**
- Create: `cli/paste/image.py`
- Modify: `cli/workbench_app/pt_prompt.py`
- Modify: `pyproject.toml`
- Test: `tests/test_paste_image.py`

**Step 1: Write the failing test**

Cover:
- missing Pillow dependency returns `None` without raising
- longest-edge resize math clamps to `1568`
- placeholder rendering for images is stable
- Linux clipboard helper selection respects Wayland/X11 fallbacks where possible

**Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_paste_image.py -q`

Expected: FAIL because image capture helpers/keybinding do not exist.

**Step 3: Write minimal implementation**

- Add optional `vision` extra in `pyproject.toml`
- Implement clipboard image capture with graceful no-op when dependencies/tools are unavailable
- Bind `Ctrl+Shift+V` in `pt_prompt.py` to insert `[Image #N]` placeholder and attach image bytes for the next send

**Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_paste_image.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add cli/paste/image.py cli/workbench_app/pt_prompt.py pyproject.toml tests/test_paste_image.py
git commit -m "feat(paste): add clipboard image capture"
```

## Task 7: Full P4 Verification And Dogfood

**Files:**
- Verify all touched files only; no net-new scope

**Step 1: Run targeted verification**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_session_jsonl_store.py \
  tests/test_session_fork.py \
  tests/test_resume_picker.py \
  tests/test_session_migration.py \
  tests/test_paste_store.py \
  tests/test_paste_placeholders.py \
  tests/test_paste_image.py \
  tests/test_resume_slash.py \
  tests/test_conversation_resume.py \
  tests/test_workbench_input_router.py \
  tests/test_system_prompt.py -q
```

Expected: PASS

**Step 2: Run broad verification**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS

**Step 3: Dogfood the real workflow**

- Launch TUI with migration enabled against a dogfood copy of `conversations.db`
- Verify `/resume` picker, `/fork`, large text paste placeholder, and `Ctrl+Shift+V` image paste

**Step 4: Review + branch finishing**

- Run spec review first, then code-quality review
- Capture `git diff --stat` and a short `/diff`-style summary for human review

**Step 5: Commit / PR prep**

```bash
git status --short
git log --oneline --decorate -n 10
```

Use the repo’s conventional commits and prepare the branch for PR once all checks are green.

## Suggested Task Dispatch Order

1. Task 0
2. Task 1
3. Task 2
4. Task 3
5. Task 4
6. Task 5 and Task 6 can run in parallel after Task 4
7. Task 7

## Review Checklist

- JSONL store is append-only and drops only a trailing partial line
- Workspace slug is deterministic and collision-safe
- Existing `cli.sessions` imports still work
- `/resume` with no args opens picker; with UUID loads directly
- `/fork` records metadata and does not mutate the source session
- Migration backs up SQLite, is idempotent, and honors `AGENTLAB_NO_MIGRATION=1`
- Large pastes/images keep the visible input readable while full content still reaches the model
- Missing Pillow or clipboard helpers never crashes the app
- No unrelated file churn
