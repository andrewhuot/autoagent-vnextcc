# CLI UX Refactor V2 — "Make It Feel Like One Pipeline"

## North Star
AutoAgent should feel like one guided pipeline:
**workspace → build → eval → improve → deploy**

## Stream 1: CLI Grammar & Command Surface (P0)

### 1A: Standardize `<resource> <verb>` Grammar
- `build-show` → `build show`
- `import config` → `config import`  
- `import transcript` → `intelligence import`
- Global `pause`/`resume` → `loop pause`/`loop resume`
- Keep old forms as hidden aliases with deprecation warnings

### 1B: Bare `autoagent` = Status Home Screen
- Running `autoagent` with no args shows `autoagent status`
- Status should show: workspace, mode, active config, last eval score, pending actions, next suggested command

### 1C: Higher-Level Workflow Commands
- `autoagent new <name> --template <type> --demo` — create workspace + seed + print next 3 commands
- `autoagent improve` — run evals → cluster failures → suggest edits → optionally apply (wraps diagnose/edit/optimize/autofix)
- `autoagent compare` — side-by-side configs, eval results, candidates
- `autoagent ship` — review → release → deploy canary (guided flow)

### 1D: Unify Selectors Everywhere
- Define `latest`, `active`, `pending` once in shared module
- Drop `current` (alias for `active`)
- Support selectors on ALL resource commands:
  - `review apply pending`
  - `intelligence report show latest`
  - `release create latest-kept`
  - `context analyze latest`
  - `trace show latest --id-only`
- Add `--id-only`, `--path-only`, `--json` consistently to every command

### 1E: Standardize JSON Output
- Every command returns `{"status": "ok|error", "data": {...}, "next": "suggested command"}`
- Version the envelope: `{"api_version": "1", ...}`

### 1F: Mutating vs Read-Only
- Add `--dry-run` to all mutating commands
- Add undo/rollback: `config rollback`, `autofix revert`, `deploy rollback`

## Stream 2: Onboarding & Templates (P0)

### 2A: One-Command Starter
```bash
autoagent new my-project --template customer-support --demo
```
- Creates workspace, seeds demo data, explains mock/live, prints next 3 commands
- Templates: customer-support, it-helpdesk, sales-qualification, healthcare-intake

### 2B: Doctor --fix
- `autoagent doctor --fix` checks and fixes: workspace, active config, credentials, model access, deploy prereqs, writable paths
- `autoagent provider configure` — interactive LLM provider setup (not just env vars)

### 2C: Templates & Starter Packs
- Each template includes: starter config, eval suite, scorers, suggested skills
- `autoagent template list` — show available templates
- `autoagent template apply <name>` — apply to existing workspace

## Stream 3: Quick Start Guide Rewrite (P0)

### Structure (7 sections max):
1. **Install AutoAgent** — pipx/uv/pip (not editable install)
2. **Create a Workspace** — `autoagent new`, mode explanation, workspace diagram
3. **Build Your First Agent** — one prompt, explain build vs config output
4. **Run Evals** — `eval run`, show expected output
5. **Improve the Agent** — `autoagent improve` (the new unified command)
6. **Compare & Pick** — `autoagent compare`, accept candidate
7. **Deploy** — `autoagent ship` or `deploy canary --yes`

### Rules:
- One workspace name throughout (my-project)
- One use case throughout (customer support)
- No internal file paths
- No Python one-liners
- No shell parsing
- Show expected output after every key command
- Mode explanation before build/eval
- Decision points: "Starting from prompt? transcript? existing config?"
- Glossary: workspace, config, eval suite, trace, review card, release
- Dangerous commands get warnings
- Troubleshooting by symptom at the end

### Separate Docs (moved out of quickstart):
- `docs/guides/skills-and-registry.md`
- `docs/guides/scoring-and-judges.md`
- `docs/guides/transcript-intelligence.md`
- `docs/guides/mcp-integration.md`
- `docs/guides/context-engineering.md`
- `docs/COMMAND_REFERENCE.md` (the cheat sheet)

## Stream 4: CLI Enhancements (P1)

### 4A: Artifacts as First-Class
- `artifacts list` — show all build artifacts, eval results, configs
- `artifacts show <id>` — inspect any artifact
- `artifacts export <id>` — export to file
- `artifacts clean` — remove old artifacts

### 4B: Better Eval Tooling
- `eval compare <run1> <run2>` — side-by-side results
- `eval regression-gate` — fail if score drops
- `eval breakdown` — scores by safety, accuracy, latency, cost
- Failure clustering in eval output

### 4C: Budget-Aware Optimization
- `optimize --max-cost $5 --max-time 30m --stop-when "score > 0.85"`
- Show cost estimates before running

### 4D: Workspace Management
- `workspace list` — show all workspaces
- `workspace switch <name>` — change active workspace
- `workspace where` — print current workspace path

### 4E: Config Identity
- Add names, tags, labels to configs
- `config create --name "v2-stricter-refunds" --message "Tightened refund verification"`
- `config tag v3 production-ready`

### 4F: Merge optimize --continuous and loop
- Keep `optimize --continuous` as the canonical form
- `loop` becomes an alias for `optimize --continuous --full-auto`
- Clear docs: "Use optimize for manual cycles, optimize --continuous for overnight runs"

### 4G: Transcript Ingestion
- Accept JSON, CSV, folders, or ZIP directly
- `intelligence import ./transcripts/` (folder)
- `intelligence import data.csv`
- No Python ZIP generation needed

### 4H: Shell Completion
- `autoagent completion bash/zsh/fish` — generate completion script
- Richer `--help` with examples on every command

## Execution Strategy

### Codex Session (plaid-lobster replacement):
- Streams 1 + 2: CLI grammar, commands, templates, doctor --fix
- Focus: runner.py, cli/*.py, new command modules

### Claude Code Session (mild-canyon replacement):
- Streams 3 + 4: Guide rewrite, CLI enhancements
- Focus: docs/, eval tooling, artifacts, workspace management
- Use Sonnet subagents for parallel doc + code work

Both work on separate clones to avoid conflicts. Merge best-of after.
