# Product-Level Gaps (Beyond Docs Edits)

**Auditor:** Claude Opus 4.6
**Date:** 2026-04-12
**Branch:** `audit/readme-accuracy-claude-opus`

These are issues where updating the README alone cannot fix the underlying problem. They require product or code changes.

---

## P1: Should Fix

### 1. Repo URL still uses old name
- **What:** The repo is `autoagent-vnextcc` but the product is branded as AgentLab everywhere else.
- **Impact:** First-time users cloning the repo immediately question whether they have the right project. Every README mention, every docs reference, every stack trace will show the old name.
- **Fix:** Rename the GitHub repo to `agentlab` or set up a redirect. This is a one-time operation but has downstream effects on CI, deploy scripts, and any existing forks.

### 2. App root route and start.sh disagree on landing page
- **What:** `App.tsx` redirects `/` to `/build`. `start.sh` opens `/dashboard`. These tell different stories about where a new user should start.
- **Impact:** Low day-to-day, but it signals inconsistent product opinion about the entry point.
- **Fix:** Pick one. If Build is the primary entry, change `start.sh` to open `/build`. If Dashboard is the overview entry, change App.tsx root redirect to `/dashboard`. Either is fine; they just need to agree.

### 3. Simple-mode nav doesn't match the claimed set
- **What:** `SIMPLE_MODE_PATHS` includes Workbench, Optimize Studio, and Docs but excludes Connect. The README (and likely any onboarding guidance) lists a different set.
- **Impact:** The simple-mode nav was designed to reduce cognitive load for new users. If the actual paths diverge from what's documented, the onboarding experience is degraded.
- **Fix:** Decide the authoritative simple-mode set. If Connect should be in simple mode, add it. If Workbench/Studio/Docs are intentionally there, update all docs. Either way, the nav definition and docs must agree.

---

## P2: Would Improve the Product

### 4. No workspace visualization or onboarding tour
- **What:** "Workspace" is the core concept but there's no way for a new user to see what one looks like -- no `tree` output in docs, no onboarding walkthrough in the web console.
- **Impact:** The mental model gap is the single biggest barrier to a new user feeling oriented.
- **Fix:** Add a workspace visualization (could be as simple as a `tree` in the Quick Start guide) and consider an onboarding guided tour in the web console.

### 5. Mock mode output is opaque
- **What:** The product auto-detects missing API keys and falls back to mock mode. But there's no documentation or UI indication of what mock mode actually produces or how it differs from live mode.
- **Impact:** A user running the Quick Start without API keys will see... something. They won't know if the output is meaningful, representative, or garbage.
- **Fix:** Mock mode should produce clearly labeled output ("MOCK MODE - deterministic responses") and the docs should explain what to expect. The `status` command already shows mode, but the eval/build outputs should too.

### 6. No screenshots or visual assets for the web console
- **What:** The product has a full web UI with 40+ pages, but there are zero screenshots anywhere in the docs.
- **Impact:** A major omission for a product that has invested heavily in its web surface. Screenshots are the fastest way to convey product value.
- **Fix:** Generate 3-5 screenshots of key surfaces (Build, Eval Runs/Results, Optimize, Improvements, Deploy) and add them to the README or UI Quick Start guide.

### 7. Eval system is central but poorly explained at every level
- **What:** Eval is the foundation of the entire optimization loop, but the README, Quick Start, and even the Concepts doc give minimal concrete detail about what eval cases look like, who writes them, and what scores mean.
- **Impact:** Users can run `agentlab eval run` without understanding what it's evaluating or how to customize it. This limits both trust and adoption.
- **Fix:** Add a concrete eval case example (YAML) to the Quick Start guide. Consider a "Your First Eval" section that shows the full lifecycle: write a case, run it, see the result.

---

## P3: Nice to Have

### 8. No PyPI distribution
- **What:** Install requires `git clone` + `pip install -e .`. There's no `pip install agentlab` from PyPI.
- **Impact:** Adds friction for first-time users and prevents standard dependency management.
- **Fix:** Publish to PyPI when the project is stable enough for versioned releases.

### 9. Feature sprawl in navigation
- **What:** The full (pro mode) nav has 40+ items across 11 groups. Even simple mode has 12 items.
- **Impact:** The product feels like it has more surface area than depth in several areas (reward studio, policy candidates, what-if replay, etc. may be stubs or early-stage).
- **Fix:** Audit which pages are actually functional vs. scaffolded stubs. Consider hiding stub pages behind a feature flag until they're ready.

### 10. MCP integration lacks client-side setup guidance
- **What:** README mentions MCP support for "Claude Code, Codex, Cursor, Windsurf" but doesn't link to setup instructions for any of these clients.
- **Impact:** A user who wants to use AgentLab via MCP has to figure out client configuration on their own.
- **Fix:** The `docs/mcp-integration.md` presumably covers this, but the README should give a one-liner example of how to connect a client (e.g., the Claude Code MCP config snippet).
