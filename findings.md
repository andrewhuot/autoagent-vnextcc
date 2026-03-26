# Findings & Decisions

## Requirements
- Add a natural-language-first product feel so users ask the system for outcomes instead of manually wiring configuration.
- Support bulk transcript ingestion from zipped archives with multilingual handling, intent mining, procedure extraction, FAQ generation, suggested workflow additions, and suggested tests.
- Add a tight handoff from diagnosis to agent change with apply flow, drafted change prompt or patch, diff view, estimated impact, regression checks, and rollback/versioning.
- Add natural-language analytics over conversation data with searchable transcript corpus, failure clustering, journey analytics, quantified root causes, and prescriptive recommendations.
- Support prompt-to-agent creation from scratch with connector-aware prompting and generated artifacts such as workflows, tools, guardrails, and tests.
- Keep the overall product cohesive and mostly additive; do not severely refactor the existing golden path or core functionality.

## Research Findings
- The repo README positions AutoAgent around a closed-loop optimization cycle: trace, diagnose, search, eval, gate, deploy, learn, repeat.
- The current repository includes a Python backend and a Vite React frontend in `web/`, which suggests these new capabilities likely need coordinated backend data/model work plus frontend workflow surfaces.
- The current web README is still template-level, so product intent is better captured by source inspection than documentation.
- There is an untracked file `UX_AUDIT_FIX_PROMPT.md` in the repo root; it appears unrelated so far and should not be disturbed.
- The frontend already contains pages and components that map well to additive placement for the new work: `Conversations`, `ContextWorkbench`, `ChangeReview`, `CxImport`, `LiveOptimize`, `Optimize`, `Dashboard`, `Runbooks`, and related chat/diff/timeline components.
- There is no top-level `src/` backend package at the repo root, so backend modules likely live under a different package directory and need targeted discovery before implementation.
- The frontend router already exposes strong additive extension points: `/conversations`, `/context`, `/changes`, `/cx/import`, `/cx/deploy`, `/autofix`, and `/live-optimize`.
- `Conversations.tsx` already supports searchable conversation browsing with filters, summary stats, and expanded transcript inspection, which makes it a plausible home for natural-language analytics and corpus exploration.
- `ChangeReview.tsx` already supports pending change cards, metric deltas, confidence evidence, diff hunk review, export, apply, and reject actions, which is a strong foundation for the requested diagnosis-to-agent-change workflow.
- The API client already exposes conversation queries, change-card mutations, and CX import/export/deploy flows; the product is already organized around typed workflow APIs rather than ad hoc frontend state.
- `CxImport.tsx` implements a staged wizard for external agent import, and `/api/cx/import` returns a structured imported artifact with config paths, snapshot path, mapped surfaces, and imported test counts.
- The existing CX route design suggests transcript ingestion can be added as a parallel import/research capability instead of a disruptive rewrite of core optimization endpoints.
- The app already ships a conversational `DiagnosisChat` component wired to `/api/diagnose/chat`, which is a strong base for the “ask the product a question” interaction pattern.
- The `AutoFix` page already frames changes as constrained proposals with expected lift, diff previews, eval/canary application, and history, which aligns well with the requested tight handoff from diagnosis to agent change.
- The backend already centralizes API contracts in `api/models.py` and exposes dedicated routes for conversations, changes, diagnose, autofix, and CX import, so the most coherent implementation path is to add a new transcript-intelligence layer that feeds those existing surfaces.
- The repo already contains an `NL_INTELLIGENCE_BRIEF.md`, `api/routes/edit.py`, `optimizer/nl_editor.py`, and `tests/test_api_nl_intelligence.py`, so part of the requested direction was previously started.
- There are active integration mismatches in that unfinished NL layer: `api/routes/edit.py` instantiates `NLEditor(use_mock=True)` and passes `auto_apply=...`, but `optimizer/nl_editor.py` currently accepts neither, which means the current edit route is not a reliable base until fixed.
- There is also a change-review contract mismatch between frontend and backend: the frontend expects `id`, `risk`, `confidence.score`, and simple hunk payloads, while the backend change-card API returns `card_id`, `risk_class`, statistical confidence fields, and a different hunk update shape.
- `optimizer/change_card.py` already provides a persistent `ChangeCardStore`, which is the cleanest place to send transcript-derived recommendations so the new workflow inherits the current review model.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Use additive feature entry points rather than altering the existing optimizer loop | The user explicitly asked to avoid heavy refactors of the golden path |
| Work from current source structure instead of the generic frontend README | The web README does not describe the actual product architecture |
| Probe existing import, conversations, context, and change-review surfaces first | These are the most natural homes for transcript ingestion, natural-language analytics, and diagnosis-to-change handoff |
| Add a dedicated `/intelligence` workspace that links to the current conversation and change-review flows | The new transcript archive, research, and prompt-to-agent workflows are substantial enough to deserve a home, but can still remain additive to the current product |
| Model transcript ingestion as a sibling to current CX import flows | The current product already knows how to turn imported external artifacts into structured internal assets |
| Reuse the existing diagnosis chat and AutoFix metaphors instead of introducing a brand-new builder UX | These surfaces already embody the natural-language and apply-review workflows requested by the user |
| Implement the new feature set through a transcript-intelligence service plus frontend workspace, while repairing the existing NL-intelligence contract mismatches | This delivers new value without forcing a risky golden-path rewrite and makes the current ask/analyze/apply layers dependable |
| Route transcript-derived recommendations through `ChangeCardStore` instead of inventing a parallel review system | This preserves the current apply/reject/diff workflow and keeps agent edits reviewable |

## Implementation Outcome
- Added a new backend intelligence layer for ZIP transcript ingestion, multilingual transcript parsing, missing-intent mining, procedure extraction, FAQ generation, workflow suggestions, suggested regression tests, natural-language analytics answers, and prompt-to-agent artifact generation.
- Added new intelligence API routes for archive import, report history/detail, report questioning, insight application, and blank-slate agent artifact generation.
- Added a new frontend `Intelligence Studio` page and route that lets users upload transcript archives, inspect generated reports, ask natural-language questions over the corpus, draft transcript-derived changes into the current change-review flow, and generate structured agent artifacts from prompts and connectors.
- Repaired the existing NL-editor backend contract so the edit route can safely instantiate `NLEditor(use_mock=True)` and optionally auto-apply accepted changes.
- Repaired diagnose/change-review contract mismatches so existing diagnosis-to-change flows behave consistently with the frontend expectations used by the additive feature slice.

## Verification Findings
- Targeted backend verification passed for both the pre-existing NL intelligence tests and the new transcript-intelligence tests.
- Touched frontend files passed targeted ESLint checks, and targeted typecheck output did not report issues in the changed frontend files.
- Full frontend `npm run build` and `npm run lint` still fail because of unrelated pre-existing issues in other pages and components; those blockers were left untouched to avoid broad refactors outside this request.

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Planning session recovery helper failed without output | Recorded in `task_plan.md` and continued with manual planning files |
| Expected backend modules were not at repo-root `src/` | Continue discovery from the actual top-level package layout instead of assuming a standard structure |
| Existing NL-editor, diagnose, and change-review contracts did not agree with one another | Repaired the mismatches as part of implementation so the new workflow could reuse current product primitives instead of bypassing them |
| Global frontend quality gates surfaced unrelated existing issues | Scoped verification to the touched files after confirming the failures were outside this feature slice |

## Resources
- `/Users/andrew/Desktop/AutoAgent-VNextCC/README.md`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/web/README.md`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/web/src`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/pages`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/components`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/App.tsx`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/pages/Conversations.tsx`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/pages/ChangeReview.tsx`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/pages/CxImport.tsx`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/lib/api.ts`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/lib/types.ts`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/api/routes/cx_studio.py`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/components/DiagnosisChat.tsx`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/pages/AutoFix.tsx`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/api/models.py`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/NL_INTELLIGENCE_BRIEF.md`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/api/routes/edit.py`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/optimizer/nl_editor.py`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/optimizer/change_card.py`
- `/Users/andrew/Desktop/AutoAgent-VNextCC/api/server.py`

## Visual/Browser Findings
- No browser inspection yet; findings are from repository docs and filesystem exploration.
