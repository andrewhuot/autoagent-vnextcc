# P5 Handoff — Output styles + vim mode + per-tool cost detail

Paste the block below into a fresh Claude Code session at the repo root (`/Users/andrew/Desktop/agentlab`).

**Prerequisites:**
- **P0 merged** — P5a and P5b read settings keys (`Settings.output.style_default`, `Settings.input.vim`).
- **P0.5 merged** — P5c per-tool cost needs the cross-provider pricing table from P0.5e.
- **Parallel-safe with everything.** P5 sub-phases are independent of each other and of P1-P4.

**What this unlocks:** Daily-driver polish — less than a week of total work across three independent tracks.

---

## Session prompt

You are picking up the AgentLab Claude-Code-parity roadmap at **P5 — Polish**. At minimum P0 and P0.5 have shipped. The roadmap lives at `docs/plans/2026-04-17-claude-code-parity-roadmap-v2.md`.

### Your job

Ship **P5** as three independent tracks. Each can ship alone; all three can run in parallel with two or more engineers.

- `.venv/bin/python -m pytest` (Python 3.11).
- Failing test → minimal impl → passing test → conventional commit.

### P5 tracks

**P5a — Output styles** (small, low risk).
**P5b — Vim mode in the input prompt** (small, low risk).
**P5c — Per-tool cost detail** (small, low risk).

Each track is its own sub-handoff below. They share nothing but the roadmap and the Settings cascade.

---

### P5a — Output styles

**Goal.** The model can request a rendering style for its next response (e.g., `<agentlab output-style="table">`). The renderer applies the style; default unchanged.

**Reference shape:** Claude Code's output-style system is gated behind a feature flag (`OUTPUT_STYLE`). The tag format is provider-neutral; use a plain XML-ish tag, not `<claude-code>`.

**Tasks:**

1. **Ground-truth** `cli/workbench_app/output_style.py` — check what's there. The roadmap flags it as a stub; verify before assuming blank slate.

2. **Pure helper:** `cli/workbench_app/output_style.py`:
   - `STYLES = Literal["table", "json", "markdown", "terse", "default"]`
   - `parse_style_directive(text: str) -> tuple[str, str | None]` — returns `(stripped_text, style_or_None)`. Scans for `<agentlab output-style="...">` tag at the start of an assistant message. Strips the tag on match.
   - `apply_style(text: str, style: str) -> str` — for "terse" compacts whitespace; for "table" validates markdown table syntax or falls back; for "json" wraps in a fenced `json` block and validates parse.

3. **System-prompt hint:** add a small, optional section in `cli/workbench_app/system_prompt.py` documenting the directive. Gated behind `Settings.output.styles_enabled` (default `False` — preserve snapshot).

4. **Renderer integration:** `cli/workbench_app/markdown_stream.py` consults the parsed style. Line-mode REPL passes through unchanged.

5. **Tests:** `tests/test_output_style.py` — parse cases (valid, invalid tag, missing quotes, no tag), apply cases per style, system-prompt snapshot stays byte-stable when disabled.

**Invariants:** Snapshot byte-stable. Default off. Invalid directive → fall back to default rendering (never crash).

---

### P5b — Vim mode in the input prompt

**Goal.** prompt_toolkit already supports vi editing mode. Add a settings flag + a cheat-sheet slash command.

**Reference shape:** Claude Code ships a hand-rolled vim (`/Users/andrew/Desktop/claude-code-main/src/vim/`). Don't reimplement — use prompt_toolkit's `vi_mode=True` and lean on its built-in motions/operators.

**Tasks:**

1. **Ground-truth** `cli/workbench_app/pt_prompt.py` — where prompt_toolkit is configured. Current mode is emacs by default.

2. **Setting:** `Settings.input.vim: bool = False` (P0 schema extension).

3. **Wire-up:** In `cli/workbench_app/pt_prompt.py`, pass `vi_mode=settings.input.vim` into the `PromptSession` constructor. Mode indicator at the bottom-right of the input area (e.g., `-- NORMAL --`, `-- INSERT --`).

4. **Cheat sheet:** `cli/workbench_app/vim_help_slash.py` — `/vim-help` renders a cheatsheet card in the transcript. List prompt_toolkit's supported motions (hjkl / w / b / e / 0 / $ / gg / G / dd / yy / p), operators (d / y / c), text objects (iw / aw / i" / a"), search (/ ?), insert (i / a / I / A / o / O).

5. **Tests:** `tests/test_vim_mode.py` — settings flag propagates; slash command registered; help text contains the expected motions.

**Invariants:** Default off. Snapshot stable. Must not regress emacs users.

---

### P5c — Per-tool cost detail

**Goal.** Track input/output/cache/reasoning tokens per tool call, not just per turn. Surface in `/doctor` and the status-bar drawer.

**Reference shape:** Claude Code's `src/cost-tracker.ts` + `src/costHook.ts`. Granular, per-tool, per-cache-tier.

**Tasks:**

1. **Ground-truth** `cli/workbench_app/cost_calculator.py`, `cli/workbench_app/cost_stream.py`, `cli/doctor_sections.py::cost_section`, `cli/llm/pricing.py` (from P0.5).

2. **Track per-tool:**
   - Extend `ToolExecution` (in `cli/tools/executor.py`) with `tokens: TokenCounts` capturing input/output/cache-read/cache-write/reasoning tokens charged to this call.
   - Token attribution: input tokens for the tool-result message are attributed to the *next* model call that consumes them. Keep the attribution simple — attribute the follow-up model call's delta to the most recent tool call.

3. **Aggregation:** `cli/workbench_app/cost_calculator.py::CostTracker.attribute(tool_name, tokens)`. Maintains running totals per-tool across the session.

4. **Pricing:** use `cli/llm/pricing.py::PRICING[(provider, model)]` — do **not** hard-code Claude rates. For unknown `(provider, model)` pairs, fall back to a conservative default and log once.

5. **Surfaces:**
   - `cli/doctor_sections.py::cost_section` gains a `by_tool` dict.
   - Status-bar drawer (if it exists in `cli/workbench_app/status_bar.py`; check first) shows top 3 tools by cost.
   - `/cost` slash command (add to `cli/workbench_app/slash.py`) — full breakdown.

6. **Tests:** `tests/test_cost_per_tool.py` — attribution math, pricing lookup, provider-switch mid-session (new provider's costs aggregate separately under the same tool name with a provider tag).

**Invariants:** Snapshot byte-stable. Unknown models fall back, never crash. Pricing table is source-of-truth; `Settings.providers.pricing_overrides` wins when set.

---

## Workflow

1. Worktree: `git worktree add .claude/worktrees/p5-polish -b claude/cc-parity-p5 master` (after P0.5 merged).
2. Three tracks independent. Pick any one to start or dispatch all three in parallel if you have engineers.
3. Per track, use `superpowers:subagent-driven-development`. Dispatch one subagent per task within the track.
4. Land each track as its own PR (`claude/cc-parity-p5a`, `...p5b`, `...p5c` branches). Don't bundle — simpler review.

## If you get stuck

- **Output styles:** don't over-engineer the style grammar. Start with three or four well-defined styles; leave room for more.
- **Vim mode:** prompt_toolkit's vi mode has known edge cases with history navigation; document known-limitations in `vim_help_slash.py` rather than fixing upstream.
- **Per-tool cost:** token attribution is inherently approximate. Don't try to be exact; document the attribution rule clearly in the module docstring so future-you isn't confused.
- **Status-bar drawer:** may or may not exist yet as a distinct concept. If not, add `/cost` as the primary surface and defer drawer UI.

## Anti-goals

- Do not ship voice mode. Scope creep; separate phase.
- Do not ship output-style *autodetection*. Model opts in via tag; that's the contract.
- Do not rebuild prompt_toolkit's vim. Use what it has.
- Do not add per-token-type surfacing (thinking tokens, cache-write tokens) beyond what the pricing table already distinguishes. Keep the UI clean.

## First action

After the user confirms, read the roadmap P5 section, ground-truth the files per track, decide which track(s) to ship, write the TDD expansion plan for that track at `docs/plans/2026-04-17-p5<letter>-tdd.md`, commit, dispatch the first task.

Use superpowers and TDD. Work in subagents. Be specific.
