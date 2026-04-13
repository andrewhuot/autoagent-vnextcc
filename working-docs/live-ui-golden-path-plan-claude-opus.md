# Live UI Golden Path Plan — Claude Opus

**Date:** 2026-04-13
**Branch:** feat/live-ui-golden-path-claude-opus
**Agent:** Claude Opus 4.6

## Mission

Test the full AgentLab UI golden path end-to-end in LIVE MODE using a real Gemini API key, then fix the highest-leverage UX issues found.

## Scenario

Build and iterate a **Verizon-like phone-company support agent** that explains bills to customers. It should help explain charges, plans, fees, and common billing confusion.

## Test Campaign

### Phase 1: Live Golden Path Test
1. **Build** — Create the phone billing support agent via the Build page Prompt tab
2. **Workbench** — Open the candidate in Workbench, inspect plan/artifacts, iterate
3. **Eval Runs** — Run an eval against the candidate
4. **Optimize** — Run an optimization cycle using eval results
5. **Improvements** — Review proposed changes
6. **Deploy** — Deploy the approved version

### Phase 2: Issue Documentation
- Capture every friction point, error, dead end, or confusing UX moment
- Classify by severity (blocker / high / medium / low)
- Note whether issue is product bug, UX gap, or environment limitation

### Phase 3: Fixes
- Focus on high-leverage fixes that improve the golden path
- Use subagents for parallel implementation
- Target: fewer clicks, clearer next steps, fewer dead ends

### Phase 4: Re-verification
- Re-run the golden path after fixes
- Confirm improvements
- Document what remains blocked

## Environment
- Backend: port 8000 (running)
- Frontend: port 5173 (running)
- GOOGLE_API_KEY: set (Gemini)
- OPENAI_API_KEY: set
- Mode: live (real API calls)

## Approach
- Use Playwright for automated browser testing against the live UI
- Capture screenshots at key moments
- Test both happy path and error recovery
- Document exact steps a user would take
