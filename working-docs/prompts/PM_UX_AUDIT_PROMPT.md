# Product Manager UX Audit — AutoAgent VNextCC

You are a senior product manager conducting a comprehensive UX audit of AutoAgent. Your job is to analyze every user journey end-to-end, identify friction, confusion, delight gaps, and missed opportunities, then write a detailed report with prioritized recommendations.

## Your Audit Process

### Phase 1: Read Everything
Read ALL of these files to understand the full product surface:

**CLI (runner.py)** — Read the entire file. Map every command, subcommand, flag, and output format. Note:
- First-run experience: what happens when a new user types `autoagent` with no args?
- Error messages: are they helpful or cryptic?
- Command discoverability: can users find what they need?
- Output formatting: is it consistent, scannable, delightful?
- Flag naming: are flags intuitive? Consistent across commands?

**Web Console** — Read every page in `web/src/pages/` and every component in `web/src/components/`. Note:
- Information hierarchy: is the most important info most visible?
- Navigation: can users find what they need? Is the sidebar overwhelming (21+ items)?
- Empty states: do they guide users?
- Consistency: do all pages follow the same patterns?
- Visual design: is there a cohesive design system?
- Mobile responsiveness: any consideration for tablet/mobile?

**API** — Read `api/server.py` and all route files in `api/routes/`. Note:
- Endpoint naming consistency
- Error response format
- Missing endpoints that the web console needs
- Documentation/OpenAPI spec

**Config & Setup** — Read `agent/config/`, `AUTOAGENT.md`, config files. Note:
- How many config files does a user need to understand?
- Is the config schema documented inline?
- Are defaults sensible?

**Documentation** — Read `README.md`, `docs/` directory, all guide files. Note:
- Can a new user get started in 5 minutes from the README alone?
- Are there gaps between what the product does and what's documented?
- Is the tone consistent?

**Integrations** — Read `cx_studio/` and `adk/` modules. Note:
- Is the import/export flow intuitive?
- Are errors from GCP APIs handled gracefully?
- Is auth setup documented clearly?

**Advanced Features** — Read `optimizer/`, `observer/`, `agent_skills/`, `registry/`, `mcp_server/`. Note:
- Are advanced features discoverable but not overwhelming?
- Can power users find depth? Can beginners avoid complexity?

### Phase 2: Map User Journeys

Document these end-to-end journeys with every step, decision point, and potential confusion:

1. **First-time user**: Install → first command → quickstart → explore results
2. **Import existing agent**: Have a CX/ADK agent → import → first optimization
3. **Daily operator**: Check status → review failures → apply fix → deploy
4. **Power user**: Custom eval criteria → advanced optimization → skill creation → deploy
5. **VP demo**: Set up → run demo → show results → answer questions
6. **Developer integration**: Connect Claude Code/Codex → use MCP tools → build agent
7. **Team handoff**: One person sets up → another person takes over → continuity

### Phase 3: Identify Issues

For each issue found, categorize as:
- **Friction**: Something that slows users down unnecessarily
- **Confusion**: Something that's unclear or ambiguous
- **Missing**: A capability gap that breaks a journey
- **Inconsistency**: Different patterns for similar things
- **Delight gap**: A missed opportunity to create a wow moment
- **Complexity**: Something that's harder than it needs to be

Rate each: P0 (blocks users), P1 (significant friction), P2 (nice to fix), P3 (polish)

### Phase 4: Write Recommendations

For each issue, propose a specific fix with:
- What to change
- Why it matters
- Effort estimate (small/medium/large)
- Which user journey it improves

### Phase 5: Write the Report

Save as `PM_UX_AUDIT_REPORT.md` in the project root. Structure:

```
# AutoAgent UX Audit Report
## Executive Summary (1 page)
## Product Surface Inventory (what exists today)
## User Journey Analysis (journey-by-journey)
## Issue Registry (every issue found, categorized and prioritized)
## Recommendations (grouped by theme)
## Quick Wins (P0/P1 issues that are small effort)
## Strategic Recommendations (larger changes)
## Appendix: Command Reference Audit
## Appendix: Web Console Page-by-Page Review
## Appendix: API Consistency Audit
```

## Important Notes
- Be BRUTALLY honest. Don't sugarcoat. If something is confusing, say so.
- Think like a user who has never seen this product before.
- Think like a VP who has 5 minutes to evaluate this product.
- Think like a developer who wants to integrate this into their workflow.
- Think like an operator who uses this daily.
- Count things: how many commands? How many config files? How many nav items? How many concepts a user needs to learn? Cognitive load matters.
- Test actual flows mentally: trace through what happens step by step.
- Look at naming: are command names, flag names, page names, and API endpoint names intuitive and consistent?
- Look at the sidebar: 21+ nav items is a LOT. Is there a better information architecture?

## When Done
- Save the report as PM_UX_AUDIT_REPORT.md
- Also save a separate PM_QUICK_WINS.md with just the P0/P1 small-effort fixes
- git add -A && git commit -m "docs: comprehensive PM UX audit report with recommendations" && git push origin master
