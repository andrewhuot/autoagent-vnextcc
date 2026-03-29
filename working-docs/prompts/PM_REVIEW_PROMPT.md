# AutoAgent VNextCC — Frontier Lab PM Review

## Your Role

You are a **senior product manager at a frontier AI lab** (think OpenAI Evals team, Anthropic's agent platform, or Google DeepMind). You've been asked to review AutoAgent VNextCC — a self-optimizing agent platform — and determine:

1. **Is the current approach right?** Does the architecture solve real customer problems?
2. **Will customers actually use this?** What's the honest PMF assessment?
3. **What's missing or wrong?** Where does this fall short of what OpenAI/Anthropic/Google would ship?
4. **What changes should we make?** Concrete, prioritized recommendations.

## How to Execute

### Phase 1: Deep Review (use Sonnet for speed)

Read the ENTIRE codebase and docs. Specifically:
- `ARCHITECTURE_OVERVIEW.md` — system design
- `P0_FEATURE_REQUESTS.md` + `P0_IMPLEMENTATION_PLAN.md` — what was just built
- All Python source in `src/` — backend logic
- All React source in `web/src/` — frontend
- `autoagent.yaml` — config surface
- CLI commands in `src/cli/`
- API endpoints in `src/api/`
- All test files
- README and docs

Then research:
- Current state of OpenAI Evals platform (what they ship, how it works)
- Anthropic's agent evaluation approach
- Google Vertex Agent Engine evaluation service
- Braintrust, LangSmith, Arize Phoenix — competitive landscape
- What real customers struggle with when optimizing agents in production

### Phase 2: Write the Review (use Opus)

Create `PM_REVIEW.md` with:

**1. Executive Assessment** (1 paragraph — would you greenlight this?)

**2. What's Good** (be specific, reference code/architecture)

**3. Critical Gaps** (things that would prevent a customer from using this in production)

**4. UX/DX Problems** (user journey friction, confusing abstractions, missing affordances)

**5. Competitive Position** (how does this compare to Braintrust, LangSmith, etc.?)

**6. Recommended Changes** (P0/P1/P2, with concrete descriptions)
- For each P0: explain the change, why it matters, and how to implement it

**7. Product Vision Check** (is the "self-optimizing agent" framing right? Or should this be positioned differently?)

### Phase 3: Implement P0 Changes (use sub-agents with Sonnet)

For every P0 recommendation in your review, implement it immediately. Use sub-agents for parallel work. This includes:
- Code changes (backend + frontend)
- Test updates
- Doc updates
- Config changes

### Phase 4: Verify & Commit

- Run all tests
- Build frontend
- Commit with: `fix: PM review — [summary of changes]`

## Constraints

- Be brutally honest in the review — no sycophancy
- Think like a customer, not a builder
- Maintain: Gemini-first, single-process, SQLite, headless-first
- Keep Apple/Linear design language
- Don't add external service dependencies

## When Done

Run: `openclaw system event --text "Done: PM review + implementation — [summary]" --mode now`
