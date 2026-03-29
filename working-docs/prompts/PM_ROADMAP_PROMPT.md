# Technical PM Review — Competitive Analysis + Roadmap Backlog

You are a Technical Product Manager reviewing AutoAgent VNextCC. Your job is three-fold:

## Part 1: Product Assessment (Internal)

Review the entire codebase and answer:
- What does this product actually do today vs. what it claims to do?
- What features are real vs. half-built vs. just UI shells?
- What's the value proposition for each user persona (agent builder, ML engineer, platform team)?
- What's the onboarding experience like? Time to first value?
- What would make a VP say "wow" in a 15-minute demo?
- What would make a VP say "this isn't ready" in a 15-minute demo?

Read these files for context:
- README.md
- docs/platform-overview.md
- docs/BEGINNER_USER_GUIDE.md
- docs/architecture.md
- All pages in web/src/pages/*.tsx (understand what's real)
- All routes in api/routes/*.py (understand what's implemented)
- runner.py (CLI capabilities)
- builder/ directory (Builder Workspace)

## Part 2: Competitive Research

Research these competitors using web search. For each, document:
- What they do
- Key features
- Pricing model
- Target audience
- What they do better than us
- What we do better than them
- Features we should steal

### Competitors to research:
1. **Braintrust** (braintrustdata.com) — AI eval platform
2. **Langsmith** (smith.langchain.com) — LangChain's tracing/eval
3. **Arize Phoenix** — Open-source observability for LLMs
4. **Humanloop** — Prompt management and eval
5. **Weights & Biases Weave** — LLM experiment tracking
6. **Patronus AI** — LLM security and eval
7. **Sierra AI** — Customer service AI platform (Ghostwriter)
8. **Observe.AI** — Contact center AI
9. **Parloa** — AI agent platform for customer service
10. **Google Vertex AI Agent Builder** — Our parent platform context

## Part 3: Prioritized Roadmap Backlog

Based on the product assessment and competitive research, create a prioritized backlog:

### Format for each item:
```
### [P0/P1/P2] Feature Name
**Category:** [Core Platform | UX | Integration | Competitive | Developer Experience]
**Effort:** [S/M/L/XL]
**Impact:** [1-10]
**Competitors who have this:** [list]
**Description:** What and why
**Acceptance criteria:** Bullet list
```

### Categories to cover:
- **Core Platform Gaps** — Things that should work but don't
- **Competitive Must-Haves** — Features every competitor has that we lack
- **Differentiation Features** — Things that would make us uniquely valuable
- **Developer Experience** — SDK, CLI, API improvements
- **Enterprise Readiness** — Auth, RBAC, audit logs, SSO, multi-tenant
- **Integration Ecosystem** — Connectors, plugins, marketplace
- **UX Polish** — Making existing features delightful
- **Documentation** — Gaps in docs, tutorials, examples
- **Infrastructure** — Deployment, scaling, monitoring, CI/CD

Target: 30-50 backlog items, ruthlessly prioritized.

## Output

Create `PM_ROADMAP_REPORT.md` with all three parts:
1. Product Assessment (2-3 pages)
2. Competitive Landscape (1 page per competitor, comparison matrix)
3. Prioritized Backlog (30-50 items)

## When done:
- `wc -l PM_ROADMAP_REPORT.md`
- `git add PM_ROADMAP_REPORT.md && git commit -m "docs: Technical PM review — competitive analysis + prioritized roadmap backlog" && git push`
- `openclaw system event --text "Done: PM roadmap report with competitive analysis and 30-50 backlog items" --mode now`
