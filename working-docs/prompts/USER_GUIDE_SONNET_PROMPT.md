# Task: Build a Comprehensive Beginner User Guide (Sonnet Track)

You are building the definitive beginner user guide for AutoAgent — a continuous optimization platform for AI agents.

## Your Role: SONNET BUILDER

You are the fast, thorough implementation track. Build the full guide independently.

## Research first — read ALL of these:
- `docs/AUTOAGENT_USER_GUIDE.md`, `docs/app-guide.md`, `docs/cli-reference.md`
- `docs/getting-started.md`, `docs/platform-overview.md`, `docs/concepts.md`
- `README.md`, `setup.sh`, `start.sh`
- `runner.py` (scan all CLI commands)
- `web/src/App.tsx` or router file (all routes)
- Every file in `web/src/pages/*.tsx` (understand each page)
- `api/routes/*.py` (all API endpoints)
- `core/skills/*.py` (skill types and capabilities)

## Create: `docs/BEGINNER_USER_GUIDE_SONNET.md`

### Required chapters:
1. **Welcome** — What is AutoAgent, who is this for, what you'll learn
2. **Getting Started** — Prerequisites, `./setup.sh`, `./start.sh`, first look
3. **Core Concepts** — Agents, optimization loops, metrics, experiments, skills
4. **CLI Walkthrough** — Every command with real examples and expected output
5. **Web UI Walkthrough** — Every page, every widget, every interaction
6. **Builder Workspace Deep Dive** — Modes, environments, composer, inspector tabs, slash commands, tasks
7. **Advanced Features** — CX integration, ADK, skill management, notifications, judge ops, AutoFix, prompt optimization
8. **CLI Reference** — Complete command reference with examples
9. **Troubleshooting & FAQ**
10. **Glossary & Appendix**

### Style:
- Stripe/Vercel docs quality — clear, friendly, professional
- Concrete examples with actual CLI output
- Callouts: 💡 Tip, ⚠️ Warning, 📝 Note
- Tables for reference, prose for tutorials
- Target: 3000-5000 lines
- Assume developer audience, no prior AutoAgent experience

### When done:
- `wc -l docs/BEGINNER_USER_GUIDE_SONNET.md`
- `openclaw system event --text 'Done: Sonnet beginner user guide — docs/BEGINNER_USER_GUIDE_SONNET.md' --mode now`
