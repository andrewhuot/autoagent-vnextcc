# P2 Handoff — Compaction + memory extraction

Paste the block below into a fresh Claude Code session at the repo root (`/Users/andrew/Desktop/agentlab`).

**Prerequisites:**
- **P0 merged** (settings cascade — compaction threshold + memory paths configurable).
- **P0.5 merged** (compaction reads `capabilities.max_context_tokens`; digest uses the active provider's cheap model — Haiku / gpt-4o-mini / Gemini Flash).
- **P1 merged** (streaming dispatch; P2 modifies the same call site in `orchestrator.py`).
- Parallel-safe with P3, P4, P5 once P1 ships.

**What this unlocks:** Long sessions that don't blow context; CLAUDE.md-style auto-memory loop; the `/uncompact` escape hatch.

---

## Session prompt

You are picking up the AgentLab Claude-Code-parity roadmap at **P2 — Compaction + memory extraction**. P0, P0.5, and P1 have all shipped. The roadmap lives at `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`.

### Your job

Ship **P2** in two slices, following subagent-driven TDD:

- **Slice A — Conversation compaction** (P2a). Turns that exceed the context budget get a digest + boundary marker; old turns archive to disk.
- **Slice B — Memory extraction + retrieval** (P2b). Background task harvests memories from the turn and writes to `MEMORY.md`; a retrieval layer surfaces relevant memories in the system prompt.

Slice A and Slice B are independent — can be dispatched in parallel with two engineers. Single-engineer: A first (higher user impact), then B.

- `.venv/bin/python -m pytest` (Python 3.11).
- Failing test → minimal impl → passing test → conventional commit.

### P2 goal

**Slice A:** When transcript size exceeds ~80% of `capabilities.max_context_tokens`, insert a `SystemCompactBoundaryMessage` and a `ToolUseSummaryMessage` digest. Old turns archived to `.agentlab/compact_archive/<session-id>/<turn-range>.jsonl` for `/uncompact` restoration. Mirrors Claude Code's `src/services/compact/compact.ts` pattern.

**Slice B:** After each completed turn, dispatch a background `TaskCreate` that runs a forked cheap-model call with a strict memory-extraction schema. Results write to `MEMORY.md` in the appropriate location (project `<workspace>/.agentlab/memory/MEMORY.md` or user `~/.agentlab/memory/MEMORY.md`). Retrieval layer (`find_relevant_memories`) injects up to K memories into the system prompt before each turn.

**Reference shape (read for architectural inspiration, do NOT copy code):**
- Claude Code compaction: `/Users/andrew/Desktop/claude-code-main/src/services/compact/compact.ts`, `autoCompact.ts`, `microCompact.ts`, `grouping.ts`, `prompt.ts`, `postCompactCleanup.ts`.
- Claude Code memory: `/Users/andrew/Desktop/claude-code-main/src/memdir/memdir.ts`, `findRelevantMemories.ts`, `memoryTypes.ts`, `paths.ts`.
- The user's own memory system at `~/.claude/projects/-Users-andrew-Desktop-agentlab/memory/` — a live example of the structure to match.

### Before dispatching anything

1. **Read the P2 section** of `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`.

2. **Ground-truth these files:**
   - `cli/llm/orchestrator.py` — `run_turn()` is the call site. Compaction check fires *after* a turn completes; memory extraction dispatches there too.
   - `cli/workbench_app/transcript.py` — renders the transcript; must render the new boundary message distinctly.
   - `cli/workbench_app/conversation_store.py` — where to archive the pre-compaction turns.
   - `cli/project_instructions/loader.py` — existing AGENTLAB.md loader; extend to also load `MEMORY.md`.
   - `cli/workbench_app/system_prompt.py` — accepts optional sections; `relevant_memories` becomes another kwarg with a `None` default (preserves snapshot).
   - `cli/llm/providers/factory.py` — for forked model selection (Haiku / mini / Flash).
   - `cli/llm/provider_capabilities.py` (P0.5) — `max_context_tokens`, `json_mode`.
   - `cli/tasks/` — `TaskStore`, `TaskExecutor`. Memory extraction dispatches as a background task.

3. **Write a TDD expansion plan** at `docs/plans/2026-04-17-p2-compaction-memory-tdd.md`. Commit alone before code.

### P2a — Conversation compaction (tasks)

**P2a.1 — Threshold + budget model.**
- Create `cli/llm/compaction.py`:
  ```python
  @dataclass
  class CompactionBudget:
      max_context_tokens: int
      threshold_ratio: float = 0.8
      min_retained_turns: int = 4

  def should_compact(transcript: list[TurnMessage], budget: CompactionBudget, *, token_counter) -> bool: ...
  def choose_compact_range(transcript: list[TurnMessage], budget: CompactionBudget) -> tuple[int, int]: ...
  ```
- Tests: `tests/test_compaction_threshold.py` — under threshold (no-op); over threshold (returns range); idempotent (compacting a compacted transcript is a no-op); respects `min_retained_turns` (never compacts the most recent N turns).

**P2a.2 — Tool-phase digest generator.**
- Create `cli/llm/digests.py`:
  - `digest_tool_phase(turns)` groups consecutive tool-call turns, summarizes into one `ToolUseSummaryMessage`.
  - Two strategies: extractive (drop blob content; keep first/last 20 lines + count) for big dumps; abstractive (forked-model summary) for chat-heavy phases.
  - Strategy selector: extractive when a single tool-result block > 2KB; abstractive otherwise.
- The forked model call uses `create_model_client(model=<cheap_model_for_provider>)` — Haiku on Anthropic, gpt-4o-mini on OpenAI, gemini-2.5-flash on Gemini. Provider is inferred from the active model.
- Tests: `tests/test_digests.py` — snapshot tests for canned tool-phase transcripts; extractive vs abstractive branch; token-count budget respected.

**P2a.3 — Compact / uncompact mechanics.**
- Create `cli/llm/compact_archive.py` — JSONL writer at `.agentlab/compact_archive/<session-id>/<start>-<end>.jsonl`. `load_archive(session_id)` reads back.
- Extend `orchestrator.py::run_turn` to call `should_compact` after each turn and, if true, replace the chosen range with the boundary + digest before the next turn starts.
- Add `/uncompact` slash in `cli/workbench_app/slash.py` — reloads the archive and restores the transcript (re-rendered in the TUI).
- Tests: `tests/test_compaction_flow.py` — drive a transcript past threshold, confirm it compacts, `/uncompact` restores byte-for-byte.

**P2a.4 — UI boundary rendering.**
- `cli/workbench_app/transcript.py` renders `SystemCompactBoundaryMessage` as a distinct visual element (horizontal rule + "Compacted N turns; /uncompact to restore").
- Status bar shows a "compacted" indicator when the current transcript includes at least one boundary.
- Tests: `tests/test_transcript_compaction_ui.py` — pure-helper render tests.

### P2b — Memory extraction + retrieval (tasks)

**P2b.1 — Memory store + frontmatter schema.**
- Create `cli/memory/__init__.py`, `cli/memory/types.py`, `cli/memory/store.py`:
  - `Memory` dataclass: `name, type, description, body, created_at, source_session_id`.
  - `MemoryStore(memory_dir: Path)` — CRUD for markdown files with YAML frontmatter. Layout matches the user's existing `~/.claude/projects/.../memory/` convention: one file per memory, one `MEMORY.md` index file.
  - Memory types: `user`, `feedback`, `project`, `reference` (mirror Claude Code's `memoryTypes.ts`).
- Tests: `tests/test_memory_store.py` — write/read round-trip; frontmatter parse/validate; index file stays under 200 lines.

**P2b.2 — Extractor (background task).**
- Create `cli/memory/extractor.py`:
  - `extract_memories(turn, *, existing_memories, model_client)` — runs a forked cheap-model call with a strict JSON-mode schema. When `capabilities.json_mode` is True (OpenAI, Gemini), use structured output; fall back to lenient parsing on Anthropic.
  - Per-turn cap: max 3 new memories; per-session cap: max 5. Over-cap extras dropped with a log line.
  - Deduplicates against existing memories (exact name match or ≥0.9 description similarity).
- Modify `cli/llm/orchestrator.py::run_turn` — after turn completion, dispatch extraction as a `TaskCreate` (background, non-blocking).
- Tests: `tests/test_memory_extractor.py` — fake model returns canned memories; cap enforced; dedup works; schema violations logged not raised.

**P2b.3 — Retrieval + injection.**
- Create `cli/memory/retrieval.py`:
  - `find_relevant(query, memories, *, k=5)` — BM25 over name + description + body, plus recency bonus. Semantic search is a future upgrade.
  - Returns `list[Memory]` with explain-trace (`reasons` list for `/memory-debug`).
- Modify `cli/workbench_app/system_prompt.py` — add optional `relevant_memories: Sequence[Memory] | None = None` kwarg (snapshot stays byte-stable). Renders under `## Relevant memories` section when provided.
- Modify `cli/llm/orchestrator.py::run_turn` — before each model call, `find_relevant(user_query, memories)` and pass into the system-prompt builder.
- Tests: `tests/test_memory_retrieval.py` — BM25 ranking; recency tiebreaker; K=0 yields nothing; score table is deterministic.

**P2b.4 — `/memory-debug` + `/memory-edit` slash commands.**
- `/memory-debug` — shows which memories were injected into the current turn and why (the `reasons` trace). Lets users correct false positives by editing/deleting.
- `/memory-edit` — opens the memory file in `$EDITOR`.
- Wire into `cli/workbench_app/slash.py` and `cli/workbench_app/commands.py` registry.

### Critical invariants P2 must preserve

- **Snapshot stability.** `tests/test_system_prompt.py` byte-stable (new `relevant_memories` kwarg defaults None).
- **Compaction is reversible.** `/uncompact` always works on the current session. Archive files are never auto-deleted within 30 days.
- **Compaction threshold conservative.** Default ratio 0.8; never compacts the most recent 4 turns.
- **Memory extraction is non-blocking.** A slow or failed extraction never blocks the next user turn. Errors go to `/doctor`.
- **Privacy note in `/doctor`.** `/doctor` surfaces "Memories sent to <provider> for extraction: count. Files at <path>." So users see what's happening.
- **Memory dedup.** Never writes two memories with the same name; update-in-place.
- **Cost transparency.** Extraction model calls aggregate into `cost_calculator` and appear in `/doctor` and the status bar drawer.
- **`AGENTLAB_NO_MEMORY=1` escape.** A new env var (bridged to `Settings.memory.enabled = false`) disables both extraction and retrieval — for users in sensitive contexts or CI.

### Workflow

1. Worktree: `git worktree add .claude/worktrees/p2-compaction-memory -b claude/cc-parity-p2 master` (after P1 merged).
2. Dispatch P2a or P2b first (either; independent). Single engineer: P2a first for user impact.
3. After each slice ships, dogfood: drive a long conversation past the threshold; confirm compaction + uncompact. Let memory extractor run across 5-10 turns; confirm `MEMORY.md` looks reasonable.
4. Open a PR per slice.

### If you get stuck

- Token-counting: each provider has a different tokenizer. P0.5 should have landed a `count_tokens()` method on `ModelClient`. If not, add a conservative `len(text) // 4` fallback and log a warning.
- Archive schema: use JSONL, not JSON — each line is one `TurnMessage`. Append-only, so concurrent writers don't clobber.
- Retrieval relevance is subjective. Ship BM25 + recency; let users see and edit. Don't over-engineer.
- Memory extraction prompt must be provider-neutral (no `<thinking>`-style markers). Test on all three providers before locking the prompt.
- Gemini's strict JSON mode makes extraction easier there; embrace it. Don't make the prompt lowest-common-denominator.
- Deduplication by name is good enough; avoid embedding-based dedup for now.

### Anti-goals

- Do not add a classifier / auto-approval — that is P3.
- Do not add MCP transports — that is P3.
- Do not add session JSONL — that is P4.
- Do not add semantic search / embeddings — future upgrade, BM25 is fine.
- Do not compress memories into one file — one file per memory, `MEMORY.md` as index. Mirrors the user's existing system.

### First action

After the user confirms, read the roadmap P2 section, read the nine ground-truth files, fetch Claude Code compact.ts + memdir.ts for shape inspiration, write the TDD expansion plan, commit, dispatch P2a.1 (or P2b.1 if starting with Slice B).

Use superpowers and TDD. Work in subagents. Be specific.
