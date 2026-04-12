# README Audit Findings

**Auditor:** Claude Opus 4.6
**Date:** 2026-04-12
**Branch:** `audit/readme-accuracy-claude-opus`
**Scope:** README.md factual accuracy, approachability, and alignment with current product

---

## Methodology

1. Read README.md and all 23 linked docs (all exist).
2. Verified CLI commands against `runner.py` (8,600+ lines, Click-based).
3. Verified web console nav against `web/src/lib/navigation.ts` and `web/src/App.tsx`.
4. Verified MCP tool count against `mcp_server/tools.py` TOOL_REGISTRY.
5. Verified deploy infrastructure against `deploy/`, `docker-compose.yaml`, `Dockerfile`.
6. Verified Quick Start commands against actual CLI definitions and flags.
7. New-user readability review (agent-assisted).

---

## Findings by Category

### INACCURATE

1. **Web console simple-mode nav list is wrong** (README line 180-189)
   - README claims: Dashboard, Setup, Build, Connect, Eval Runs, Results Explorer, Compare, Optimize, Improvements, Deploy
   - Actual `SIMPLE_MODE_PATHS` in `navigation.ts:322-335`: /dashboard, /setup, /build, /workbench, /evals, /results, /compare, /studio, /optimize, /improvements, /deploy, /docs
   - **Connect is NOT in simple mode.** Workbench, Optimize Studio, and Docs ARE in simple mode but not listed.
   - Severity: Medium. A user looking for these pages in simple mode will be confused.

2. **Dev URL default route inconsistency** (README line 175)
   - README says to open `http://localhost:5173/dashboard`
   - `App.tsx:76` redirects `/` to `/build`, not `/dashboard`
   - `start.sh:49` opens `/dashboard` explicitly
   - The page exists and works, but the README and the app's root route tell different stories about where you "start."
   - Severity: Low. Dashboard exists and is valid; it's just not where the app sends you by default.

### STALE

3. **Repo clone URL mismatch** (README line 26)
   - `github.com/andrewhuot/autoagent-vnextcc.git` -- the product is called AgentLab but the repo is still `autoagent-vnextcc`.
   - This creates immediate confusion for a first-time user who wonders if they're looking at the right project.
   - Severity: Medium (confusing, but technically functional).

### ACCURATE

4. **CLI primary commands** -- all 8 verified: `new`, `build`, `eval`, `optimize`, `deploy`, `status`, `doctor`, `shell`.
5. **CLI secondary commands** -- all 9 verified: `config`, `connect`, `instruction`, `memory`, `mode`, `model`, `provider`, `review`, `template`.
6. **MCP server tool count** -- "22 tools" is exact. Counted 22 entries in `TOOL_REGISTRY`.
7. **MCP prompts and resources** -- confirmed in `mcp_server/prompts.py` and `mcp_server/resources.py`.
8. **Quick Start commands** -- all flags verified: `new --template --demo`, `instruction show`, `build <prompt>`, `eval run`, `optimize --cycles 1`, `deploy --auto-review --yes`.
9. **Deploy options** -- Docker, Cloud Run (`deploy/deploy.sh`), Fly.io (`deploy/fly.toml`) all have supporting files.
10. **All 23 doc links** -- every referenced doc file exists.
11. **start.sh** -- exists, well-structured, starts backend on 8000 and frontend on 5173 as described.
12. **`agentlab server`** -- confirmed at `runner.py:7302`.

### CONFUSING

13. **Opening line overpromises**
    - "AgentLab automatically makes your AI agents better" -- vague, aspirational, not concrete.
    - Doesn't say what kind of agents, what "better" means, or what artifact is being improved.
    - A reader from the OpenAI Agents, LangGraph, or CrewAI ecosystem can't tell if this tool applies to them.

14. **Feature list is overwhelming**
    - 12 Key Features + 4 Integrations = 16 named capabilities before a user has run a single command.
    - Mixes core workflow (eval, compare, optimize) with niche integrations (CX Studio, MCP) and implementation details (XML instructions, NL scorer).
    - Flat list gives equal weight to everything; nothing stands out as the main thing.

15. **Insider terminology without definitions**
    - "XML instructions" -- mentioned 3 times, never explained. Why XML? What problem does it solve?
    - "Change cards" -- in review command description, never defined. Diffs? PRs? Proposals?
    - "NL scorer" -- "Create eval scorers from natural language." What is a scorer? How does NL scoring compare to code-based scoring?
    - "Context workbench" -- "Inspect context usage and compaction tradeoffs." Token context? Retrieval context?

16. **How It Works placement**
    - Appears AFTER the Quick Start. A user runs 6 commands before they have a mental model of the product.
    - Should come before the Quick Start to orient the reader.

17. **Documentation section is too heavy**
    - 28 links in 4 groups. Functions as a docs site index, making the README feel like a manual.
    - No priority or progression guidance. A first-time user doesn't know which of the 28 links to read next.

### MISSING

18. **No visual of the web console**
    - The README describes a multi-tab web UI but shows zero screenshots or GIFs.
    - For a product with a web console, this is a significant omission.

19. **No concrete artifact examples**
    - Never shows what a workspace looks like on disk.
    - Never shows what an eval case looks like (YAML/JSON).
    - Never shows what a "config" contains.
    - The eval system is central but entirely opaque from the README.

20. **No explanation of what "optimize" actually does**
    - "Generate and test targeted changes" -- changes to what? The prompt? Tool definitions? Eval cases?
    - This is the core value proposition and it's hand-waved.

21. **No mock mode detail**
    - Says it "falls back to deterministic mock responses" without API keys.
    - Doesn't explain what mock mode actually produces or whether the Quick Start will look meaningful without keys.

22. **No troubleshooting in README**
    - Most common failure (`agentlab: command not found` after install) not addressed.
    - The Quick Start guide in docs/ has troubleshooting but the README doesn't.

23. **No product boundaries**
    - With 16+ features listed, readers need to know what AgentLab is NOT.
    - Is it an agent framework? A hosting platform? A prompt optimizer? Saying what it isn't would sharpen what it is.

---

## Approachability Rating: 6/10

**Strengths:** Well-structured, scannable, CLI tables are clean, How It Works builds a real mental model, `--demo` flag is thoughtful onboarding, Quick Start is genuinely short.

**Weaknesses:** Tells about the loop without showing what it produces. Lists 12 features without demonstrating any. Uses insider terms without defining them. No screenshots. Opening line oversells. Documentation section overwhelms.

A first-time user finishes reading and understands the *shape* of AgentLab but not the *substance*.
