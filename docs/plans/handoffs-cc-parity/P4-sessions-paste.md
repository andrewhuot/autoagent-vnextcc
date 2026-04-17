# P4 Handoff — Session storage + fork + paste/image store

Paste the block below into a fresh Claude Code session at the repo root (`/Users/andrew/Desktop/agentlab`).

**Prerequisites:**
- **P0 merged** (session root path read from `Settings.sessions.root`; paste size threshold from `Settings.paste.inline_threshold_bytes`).
- **Parallel-safe with P1, P2, P3.** Only overlap risk: `cli/workbench_app/input_router.py` — if P1 is landing simultaneously, coordinate by having P1 land its router changes first, then P4 adds paste detection on top.

**What this unlocks:** Delightful `/resume`; forked sessions from any turn; pastes and images don't bloat the input line.

---

## Session prompt

You are picking up the AgentLab Claude-Code-parity roadmap at **P4 — Session storage + fork + paste/image store**. P0 (settings+hooks) and P0.5 (provider parity) have shipped. P1, P2, P3 may or may not be shipped — P4 is parallel-safe with all of them. The roadmap lives at `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`.

### Your job

Ship **P4** following subagent-driven TDD:

- Fresh subagent per task with full task text + code.
- `.venv/bin/python -m pytest` (Python 3.11).
- Failing test → minimal impl → passing test → conventional commit.

### P4 goal

Match Claude Code's session model:
1. Each session has a UUID and appends to `~/.agentlab/projects/<workspace-slug>/history/<session-id>.jsonl` (one JSON object per line, append-only).
2. `/resume` opens a picker listing recent sessions with a summary + last-user-message preview.
3. Any session can be forked at turn N into a new session UUID (`/fork` slash).
4. Large pastes and clipboard images are stored content-addressed (`.agentlab/pastes/<hash>.*`), referenced inline as `[Pasted text #N +M lines]` or `[Image #N]`. Full content is threaded through to the model; the displayed input stays readable.

**Reference shape (read for architectural inspiration, do NOT copy code):**
- Claude Code session history: `/Users/andrew/Desktop/claude-code-main/src/history.ts`, `src/utils/sessionStorage.ts`.
- Fork: `/Users/andrew/Desktop/claude-code-main/src/utils/forkedAgent.ts`.
- Image pipeline: `/Users/andrew/Desktop/claude-code-main/src/utils/imagePaste.ts`, `src/utils/imageResizer.ts`.
- Paste placeholders: `/Users/andrew/Desktop/claude-code-main/src/components/renderPlaceholder.ts`.

### Before dispatching anything

1. **Read the P4 section** of `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`.

2. **Ground-truth these files:**
   - `cli/workbench_app/conversation_store.py` — existing SQLite-backed conversation persistence. P4 wraps this with a new JSONL store; existing rows are read-only migration source.
   - `cli/workbench_app/resume_slash.py` — existing; becomes an opener for the new picker.
   - `cli/workbench_app/conversation_resume.py` — existing load logic.
   - `cli/workbench_app/input_router.py` — input dispatch; paste detection hooks here.
   - `cli/workbench_app/pt_prompt.py` — prompt_toolkit integration; `Paste` bracket detection.
   - `cli/sessions.py` — existing session module (check if this conflicts with P4's new `cli/sessions/` package; rename or merge as needed).
   - `cli/workbench_app/tui/widgets/` — widget pattern (see `task_tree.py`).

3. **Write a TDD expansion plan** at `docs/plans/2026-04-17-p4-sessions-paste-tdd.md`. Commit alone first.

### P4 tasks

**P4.1 — Session JSONL store.**
- Evaluate the existing `cli/sessions.py` module first. If it's small and store-shaped, promote to package `cli/sessions/__init__.py` with legacy re-exports. If not, create `cli/sessions/store.py` alongside.
- Build `SessionStore(root: Path)`:
  - `create(workspace_root) -> Session` — generates UUID, computes slug from workspace path, ensures dir exists.
  - `append(session_id, turn: TurnRecord)` — atomic append (`open(path, "a")` + `fsync`).
  - `load(session_id) -> list[TurnRecord]` — streams the JSONL.
  - `list_for_workspace(workspace_root) -> list[SessionSummary]` — returns UUID, started_at, last-user-message preview, turn count.
- Root path from `Settings.sessions.root` (default `~/.agentlab/projects`).
- Tests: `tests/test_session_jsonl_store.py` — append crashes are recoverable (partial-line handling); slug collision across different paths; concurrent append safety.

**P4.2 — Fork.**
- Create `cli/sessions/fork.py`:
  - `fork(session_id, *, at_turn: int) -> Session` — copies turn prefix `[0..at_turn]` into a new UUID. Writes a `forked_from` metadata line as the new session's first entry.
- Add `/fork` slash command in `cli/workbench_app/slash.py`. Argument: optional turn index (defaults to current turn = fork the whole session).
- Tests: `tests/test_session_fork.py` — forked session has N turns; original untouched; metadata line points back.

**P4.3 — Resume picker.**
- Create `cli/sessions/picker.py` as a pure data builder: `build_picker_rows(store, workspace_root) -> list[ResumeRow]` returning `(session_id, started_at, last_modified, summary, last_user_preview)`.
- Summary source: if P2 shipped and memories were extracted this session, use the session-level summary; else first-user-message as fallback.
- Create `cli/workbench_app/tui/widgets/resume_picker.py` — Textual widget wrapping the pure helper. Arrow-key navigation, `enter` loads, `d` deletes (with confirm), `f` forks.
- Modify `cli/workbench_app/resume_slash.py` — open the picker when no argument given; load by UUID when one is given.
- Tests: `tests/test_resume_picker.py` — pure-helper only (no event loop).

**P4.4 — Migration from SQLite.**
- Add a one-time migration: on first workbench launch after P4, read all rows from `cli/workbench_app/conversation_store.py`'s SQLite DB, emit corresponding JSONL sessions, archive the DB as `conversations.db.migrated.bak`.
- Migration is idempotent (marker file at `~/.agentlab/projects/.migrated_jsonl`).
- Read path: if a session_id is requested and the JSONL doesn't exist, fall back to the SQLite store (for partial migrations).
- Tests: `tests/test_session_migration.py` — SQLite with N sessions → N JSONL files; idempotent on re-run; rollback path if migration fails mid-run (no partial state).

**P4.5 — Paste store + placeholders.**
- Create `cli/paste/store.py`:
  - `PasteStore(root: Path)` — content-addressed store at `.agentlab/pastes/<sha256>.txt`.
  - `store(text) -> PasteHandle` — returns `PasteHandle(id, line_count, preview)`.
  - `load(id) -> str` — reads back.
- Create `cli/paste/placeholders.py`:
  - `render_placeholder(handle) -> str` = `"[Pasted text #<N> +<M> lines]"`.
  - `expand_placeholders(text, store) -> str` — on send-to-model, replaces placeholders with full content.
- Modify `cli/workbench_app/input_router.py` — detect bracket-paste events from prompt_toolkit above `Settings.paste.inline_threshold_bytes` (default 2048). Store + replace in the visible input.
- Tests: `tests/test_paste_store.py`, `tests/test_paste_placeholders.py`.

**P4.6 — Clipboard image capture.**
- Create `cli/paste/image.py`:
  - `capture_clipboard_image() -> PIL.Image | None` — uses `PIL.ImageGrab` on macOS/Windows, `xclip -selection clipboard -t image/png -o` on Linux.
  - `resize_for_vision(image) -> bytes` — resize to ≤1568px longest edge (Anthropic's recommendation; generous enough for all three providers); output PNG.
- Make `PIL` an optional dep under a `vision` extras group in `pyproject.toml`. When absent, image-paste is a no-op with a log line.
- Bind a keybinding (e.g., `Ctrl+Shift+V`) in `cli/workbench_app/pt_prompt.py` to trigger image capture. Replaces input with `[Image #N]` placeholder; full image threaded into the message as a vision block.
- Tests: `tests/test_paste_image.py` — PIL-missing path returns None cleanly; resize math; placeholder rendering.

### Critical invariants P4 must preserve

- **Append-only, crash-safe.** A crash mid-append leaves at most one partial line; the loader handles it (drops the partial line, logs a warning).
- **Backward compatibility with SQLite store.** Users with existing `conversations.db` see their history after migration, not before. Archive, don't delete.
- **Workspace slug is deterministic.** Same workspace path → same slug. URL-safe. Collisions (different paths normalizing to the same slug) append a 4-char hash suffix.
- **Fork metadata is preserved.** `forked_from` + `forked_at_turn` are queryable.
- **Pastes never lost.** Content-addressed storage means a re-submitted placeholder resolves to the same content even across sessions.
- **Image resize is optional.** `vision` extra missing → log + no-op, not crash.
- **Snapshot stability.** `tests/test_system_prompt.py` byte-for-byte stable.
- **`AGENTLAB_NO_MIGRATION=1` escape.** A user who doesn't want migration can set it; the workbench runs dual-mode forever.

### Workflow

1. Worktree: `git worktree add .claude/worktrees/p4-sessions-paste -b claude/cc-parity-p4 master` (after P0 merged).
2. Tasks sequence: P4.1 → P4.2 → P4.3 → P4.4 → then P4.5 + P4.6 in parallel (independent of session work).
3. After P4.4 lands, run migration against a real `conversations.db` dogfood copy before merging.
4. Dogfood the picker: launch with `AGENTLAB_NO_TUI=` (TUI), resume, fork, paste a large doc, paste an image.
5. Open a PR.

### If you get stuck

- JSONL crash-safety: for each append, write then fsync. On load, catch `json.JSONDecodeError` on the last line only and drop it. Elsewhere, a JSON error is fatal (file corruption).
- Workspace slug: use `urllib.parse.quote_plus(str(workspace_root.resolve()), safe="")`. Cap at 200 chars; append sha256 prefix on overflow.
- Migration rollback: migration's first action is to copy the SQLite DB to `.migrated.bak`. If anything fails, the DB stays readable from the fallback read path.
- Picker UX: the existing conversation-store summary may be thin. OK to start with "first user message, 80 chars" as the summary and improve later.
- Bracket-paste detection: prompt_toolkit emits `Keys.BracketedPaste` events. When bracketed-paste mode is on, the terminal sends `\e[200~...\e[201~` around the pasted content; prompt_toolkit handles decoding.
- Image capture on Wayland is an ongoing pain: `wl-paste --type image/png` is the equivalent of xclip. Check `XDG_SESSION_TYPE`. If neither `xclip` nor `wl-paste` is available, log and skip.
- PIL's `ImageGrab.grabclipboard()` returns `None` on no image OR on unsupported formats. Don't treat None as an error; treat it as "no image available".

### Anti-goals

- Do not build a full search/indexing layer on sessions. Simple listing + preview is enough. Search is a future phase.
- Do not add semantic summarization of sessions — use first-message or memory-store summary.
- Do not add image OCR or vision-specific features. Resize + attach; model handles the rest.
- Do not add multi-session "merge" operations. Fork yes; merge no.

### First action

After the user confirms, read the roadmap P4 section, read the seven ground-truth files, write the TDD expansion plan, commit, dispatch P4.1.

Use superpowers and TDD. Work in subagents. Be specific.
