# Port Codex7 + AgentStudio into VNextCC

## Track 1: Codex7 CLI/Backend Enhancements

Port the uncommitted changes from `~/Desktop/AutoAgent-VNextCC-Codex7/` into this repo. The diff touches 6 files (+404 lines):

1. **`runner.py`**: Add `--json` flag to `eval run`, `optimize`, `status`, `deploy list`, and other key CLI commands. When `--json` is set, suppress human-readable output and emit structured JSON instead.
2. **`core/project_memory.py`**: Add `_build_intelligence_section()` method that auto-generates a health/issues/changes/skill-gaps markdown block inside AUTOAGENT.md between `<!-- BEGIN AUTOAGENT INTELLIGENCE -->` and `<!-- END AUTOAGENT INTELLIGENCE -->` sentinel comments.
3. **`api/server.py`**: Any new route registrations from the diff.
4. **`web/src/lib/api.ts`** and **`web/src/lib/types.ts`**: New API hooks/types.
5. **`web/src/pages/Dashboard.tsx`**: Minor additions.

**How to port**: Read the diff at `~/Desktop/AutoAgent-VNextCC-Codex7/` (use `git diff HEAD` there), then apply equivalent changes here. Don't blindly copy — VNextCC master may have evolved past Codex7's base. Merge intelligently.

## Track 2: AgentStudio Page from v3

Port the AgentStudio feature from `~/Desktop/AutoAgent-v3/frontend/src/` into VNextCC's web app:

Source files:
- `~/Desktop/AutoAgent-v3/frontend/src/lib/agentStudio.ts` (264 lines) — NL prompt parser, changeset builder, metric projections
- `~/Desktop/AutoAgent-v3/frontend/src/pages/AgentStudio.tsx` (438 lines) — Full page with chat input, change cards with before/after diffs, metric projections, review checklist
- `~/Desktop/AutoAgent-v3/frontend/src/lib/agentStudio.test.ts` (16 lines)
- `~/Desktop/AutoAgent-v3/frontend/src/pages/AgentStudio.test.tsx` (31 lines)

**Adaptation needed**:
- VNextCC uses TypeScript with its own type system in `web/src/lib/types.ts` — adapt imports
- VNextCC uses its own design system (light neutral, Inter font, consistent with other pages) — adapt styling
- Add route in `web/src/App.tsx`
- Add to sidebar nav in `web/src/components/Sidebar.tsx` (under "Improve" group if grouped nav exists, otherwise add it)
- Add page title in `web/src/components/Layout.tsx`
- The AgentStudio concept: user types NL prompt like "Make BillingAgent verify invoices before answering", system generates a structured changeset with before/after diffs, projected metrics, and review checklist

## Execution

1. Use sub-agents (Task tool) to parallelize Track 1 and Track 2
2. Run `python3 -m pytest tests/ -x -q` after — must stay >= 1,825 tests
3. Add tests for new functionality
4. Commit with conventional commit messages
5. Do NOT break existing functionality

When completely finished, run: openclaw system event --text "Done: Ported Codex7 enhancements + AgentStudio into VNextCC" --mode now
