# Product Vision Review — Steve Jobs Style

You are a world-class product thinker channeling Steve Jobs' philosophy: ruthless simplicity, obsessive user experience, saying no to 1000 things to get 1 right.

Review the ENTIRE AutoAgent VNextCC codebase and product and produce a brutally honest product review.

## What to Read
1. README.md, ARCHITECTURE_OVERVIEW.md, all docs/ files
2. Every web page in web/src/pages/ — understand the full UI surface (31 pages)
3. The CLI surface in runner.py — all 87 commands
4. The API surface in api/routes/ — all 131 endpoints
5. Key backend: optimizer/, observer/, evals/, registry/, cx_studio/, adk/, agent_skills/

## What to Produce

Write `CODEX_PRODUCT_VISION_REVIEW.md` with:

1. **The One Sentence** — What this product IS (or should be)
2. **The Essential Experience** — The 3-5 screens that matter most
3. **The Kill List** — Features/pages/concepts to merge or remove
4. **The Simplification Map** — How to collapse 31 pages into ~7
5. **The Magic Moments** — 5 specific UX improvements that would create delight
6. **The Naming Audit** — Confusing terms and what to rename them
7. **The First 5 Minutes** — What the perfect new-user experience looks like
8. **The Daily Loop** — What a power user's daily workflow should feel like
9. **The VP Demo** — How to wow in 30 seconds, not 30 minutes
10. **Priority-Ordered Action Items** — Specific code/design changes, each with effort estimate

Think about:
- 31 pages is a LOT. What's the essential 5-7 page app?
- runs vs experiments vs change cards vs opportunities vs proposals — does a user need ALL of these?
- What's the 'one thing' this product does? One sentence.
- What would make a VP say 'wow' in 30 seconds?
- Where is complexity masquerading as power?

Be specific. Reference actual files, pages, components. Don't be polite — be right.

When completely finished, run: openclaw system event --text "Done: Codex product vision review — CODEX_PRODUCT_VISION_REVIEW.md written" --mode now
