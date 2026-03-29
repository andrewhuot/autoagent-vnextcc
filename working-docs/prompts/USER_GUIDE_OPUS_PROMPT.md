# Task: Build a Comprehensive Beginner User Guide

You are building the definitive beginner user guide for AutoAgent — a continuous optimization platform for AI agents. This guide must be approachable enough for someone who's never optimized an agent before, but comprehensive enough to cover every feature.

## Your Role: OPUS PLANNER + WRITER

You are the planning and quality lead. Your job:

1. **Research phase** (read everything first):
   - `docs/AUTOAGENT_USER_GUIDE.md` (existing guide — build on this, don't duplicate)
   - `docs/app-guide.md` (web UI docs)
   - `docs/cli-reference.md` (CLI docs)
   - `docs/getting-started.md`
   - `docs/platform-overview.md`
   - `docs/concepts.md`
   - `docs/architecture.md`
   - `README.md` (quick start)
   - `setup.sh` / `start.sh` (first-run scripts)
   - `runner.py` (CLI entry point — scan all commands/subcommands)
   - `web/src/App.tsx` or routing file (all UI pages/routes)
   - `web/src/pages/*.tsx` (every page — understand what each does)
   - `api/routes/*.py` (all API routes)

2. **Create the guide** at `docs/BEGINNER_USER_GUIDE.md`:

## Structure Required

```markdown
# AutoAgent — Beginner User Guide

## Welcome
- What is AutoAgent? (2 paragraphs, no jargon)
- Who is this guide for?
- What you'll learn

## Chapter 1: Getting Started
- Prerequisites (Python, Node)
- Installation (./setup.sh)
- Starting AutoAgent (./start.sh)
- Your first look at the dashboard
- Understanding the navigation

## Chapter 2: Core Concepts
- What is an "agent"?
- What is "optimization"?
- The optimization loop explained simply
- Metrics: quality, safety, latency, cost
- Experiments and experiment cards
- Skills — what they are and why they matter

## Chapter 3: Your First Optimization (CLI)
- Step-by-step walkthrough
- `autoagent init` — creating a project
- `autoagent trace` — collecting data
- `autoagent diagnose` — finding problems
- `autoagent optimize` — running a cycle
- `autoagent loop` — letting it run autonomously
- Reading the results
- Every CLI command with examples

## Chapter 4: Your First Optimization (Web UI)
- Dashboard overview (every card/widget explained)
- Builder Workspace walkthrough
  - Left rail (projects, sessions, tasks)
  - Conversation pane
  - Inspector panel (every tab)
  - Composer (slash commands, modes)
  - Top bar (modes, environments, pause/resume)
- Optimize page
- Experiments page
- Traces page
- Skills pages (Registry, Agent Skills)
- Settings page
- Demo mode (how to use /builder/demo)

## Chapter 5: The Builder Workspace Deep Dive
- Modes: Ask, Draft, Apply, Delegate
- Environments: Dev, Staging, Production
- Working with artifacts
- Using slash commands
- Task management
- The Inspector tabs explained:
  - Overview, Diff, Evals, Traces, Skills, Guardrails, Files, Config

## Chapter 6: Advanced Features
- CX Agent Studio integration
- ADK import/export
- Skill creation and management
- Notifications (webhook, Slack, email)
- Judge operations
- AutoFix Copilot
- Context Engineering Workbench
- Prompt optimization (MIPROv2, etc.)

## Chapter 7: CLI Reference
- Every command with full examples
- Common workflows
- Tips and tricks

## Chapter 8: Troubleshooting
- Common errors and fixes
- FAQ
- Where to get help

## Appendix
- Glossary of terms
- Keyboard shortcuts
- API endpoints reference
```

## Style Guidelines
- Write like Stripe's docs or Vercel's docs — clear, friendly, professional
- Use concrete examples, not abstract descriptions
- Show actual CLI output and screenshots descriptions (describe what the user sees)
- Use callout boxes: 💡 Tip, ⚠️ Warning, 📝 Note
- Every section should answer "what does this do?" and "when would I use it?"
- Assume the reader is a developer but has never used AutoAgent
- Target length: 3000-5000 lines (comprehensive but not bloated)
- Use tables for reference material, prose for tutorials

## When done:
- Validate the markdown renders cleanly
- Run: `wc -l docs/BEGINNER_USER_GUIDE.md` and report the line count
- Run: `openclaw system event --text 'Done: Opus beginner user guide — docs/BEGINNER_USER_GUIDE.md' --mode now`
