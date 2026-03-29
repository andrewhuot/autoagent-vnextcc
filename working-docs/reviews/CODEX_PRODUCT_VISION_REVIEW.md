# CODEX Product Vision Review — AutoAgent VNextCC

Date: March 26, 2026

Scope reviewed (as requested):
- `README.md`, `ARCHITECTURE_OVERVIEW.md`, and all `docs/` markdown files.
- All web pages in `web/src/pages/` (31 product pages plus `AgentStudio.test.tsx`).
- Full CLI surface in `runner.py` (87 commands).
- Full API surface in `api/routes/` plus `api/server.py` task/websocket routes (131 endpoints total).
- Key backend packages: `optimizer/`, `observer/`, `evals/`, `registry/`, `cx_studio/`, `adk/`, `agent_skills/`.

---

## 1. The One Sentence

**AutoAgent should be: _the fastest way to find why an AI agent is failing in production and safely ship a measurable fix in one cycle._**

Right now, the product identity is split between:
- Continuous production optimization platform (`README.md`, `optimizer/loop.py`, `observer/opportunities.py`).
- Research playground (`optimizer/search.py`, `optimizer/prompt_opt/*`, `evals/scorer.py` multi-mode layering).
- Integration toolkit (`cx_studio/*`, `adk/*`, `web/src/pages/Cx*.tsx`, `web/src/pages/Adk*.tsx`).
- Insight lab (`web/src/pages/IntelligenceStudio.tsx`, `api/routes/intelligence.py`).

That is too many products wearing one brand.

---

## 2. The Essential Experience

If this product is excellent, a user should complete one loop in under 2 minutes:
1. See health and risk.
2. See the dominant root cause in plain English.
3. Review one proposed fix as a diff + confidence.
4. Run gated eval.
5. Deploy or rollback instantly.

### The 5 screens that matter

1. **Dashboard** (`web/src/pages/Dashboard.tsx`)
- Keep: health pulse, hard gates, core metrics, action buttons.
- Change: remove mode complexity (`Simple` vs `Advanced`) as top-level framing.

2. **Diagnosis** (merge from `Traces`, `BlameMap`, `Opportunities`, `AutoFix`)
- Current split across:
  - `web/src/pages/Traces.tsx`
  - `web/src/pages/BlameMap.tsx`
  - `web/src/pages/Opportunities.tsx`
  - `web/src/pages/AutoFix.tsx`
- User intent is single: “What is broken and what should I do next?”

3. **Changes** (merge from `Optimize`, `LiveOptimize`, `Experiments`, `ChangeReview`, and optional NL compose from `AgentStudio`)
- Current split across:
  - `web/src/pages/Optimize.tsx`
  - `web/src/pages/LiveOptimize.tsx`
  - `web/src/pages/Experiments.tsx`
  - `web/src/pages/ChangeReview.tsx`
  - `web/src/pages/AgentStudio.tsx`
- User intent is single: “Generate, compare, approve, or reject changes.”

4. **Evaluations** (`web/src/pages/EvalRuns.tsx`, `web/src/pages/EvalDetail.tsx`)
- This is the trust engine and should stay explicit.

5. **Deploy** (merge from `Deploy`, `LoopMonitor`, `EventLog`)
- Current split across:
  - `web/src/pages/Deploy.tsx`
  - `web/src/pages/LoopMonitor.tsx`
  - `web/src/pages/EventLog.tsx`
- User intent is single: “What is live, what changed, and can I rollback?”

---

## 3. The Kill List

### A) Kill from core product (or hide behind `--experimental`)

1. **Research-mode surface in primary UX**
- Evidence:
  - `web/src/pages/Optimize.tsx` exposes `standard|advanced|research` and research algorithm picker.
  - `optimizer/search.py` supports `simple|adaptive|full|pro`.
  - `optimizer/prompt_opt/strategy.py` routes MIPROv2 / BootstrapFewShot / GEPA / SIMBA.
- Decision: keep internals for advanced users, remove from day-1 UI.

2. **Multi-mode scorer controls as front-door complexity**
- Evidence: `evals/scorer.py` supports `weighted|constrained|lexicographic` plus expanded dimension stacks.
- Decision: lock default to constrained behavior in main flow; expose alternatives only in advanced settings.

3. **`Live Optimize` as separate page**
- Evidence:
  - Separate route in `web/src/App.tsx` and sidebar (`/live-optimize`).
  - `api/routes/optimize_stream.py` is currently simulated (`source: simulated`) rather than real cycle telemetry.
- Decision: remove page; add optional “stream progress” panel on Changes page only after real telemetry is integrated.

4. **Mock-only quick-fix path in core dashboard action loop**
- Evidence:
  - `web/src/components/FixButton.tsx` calls `/api/quickfix`.
  - `api/routes/quickfix.py` returns mock success and explicit warning “Full implementation pending.”
- Decision: remove from default UX until real implementation exists.

### B) Merge duplicate concepts

1. **Experiments + Change Cards**
- Evidence:
  - `api/routes/experiments.py`
  - `api/routes/changes.py`
  - CLI has both `reject` (experiment) and `review` group (change cards) in `runner.py`.
- Decision: one artifact model (`Change`) with consistent lifecycle.

2. **Opportunities + AutoFix + Diagnose Chat**
- Evidence:
  - `api/routes/opportunities.py`
  - `api/routes/autofix.py`
  - `api/routes/diagnose.py`
- Decision: one diagnosis workspace with ranked issues and one-click generated fixes.

3. **Skills + Runbooks + Registry + Agent Skills**
- Evidence:
  - `web/src/pages/Skills.tsx`
  - `web/src/pages/Runbooks.tsx`
  - `web/src/pages/Registry.tsx`
  - `web/src/pages/AgentSkills.tsx`
  - APIs split across `/api/skills`, `/api/runbooks`, `/api/registry`, `/api/agent-skills`.
- Decision: one “Library” IA with tabs: Skills, Playbooks, Policies, Integrations.

### C) Demote from top-level nav to Advanced

1. `Judge Ops` (`web/src/pages/JudgeOps.tsx`)
2. `Context Workbench` (`web/src/pages/ContextWorkbench.tsx`)
3. `Scorer Studio` (`web/src/pages/ScorerStudio.tsx`)
4. `Project Memory` (`web/src/pages/ProjectMemory.tsx`)

These are important expert tools, not first-run product pillars.

---

## 4. The Simplification Map (31 pages -> 7)

### Proposed 7-page product map

1. **Home**
- Source pages: `Dashboard`.

2. **Diagnose**
- Source pages: `Traces`, `BlameMap`, `Opportunities`, `AutoFix`.

3. **Changes**
- Source pages: `Optimize`, `LiveOptimize`, `Experiments`, `ChangeReview`, `AgentStudio`.

4. **Evaluate**
- Source pages: `EvalRuns`, `EvalDetail`.

5. **Deploy**
- Source pages: `Deploy`, `LoopMonitor`, `EventLog`.

6. **Library**
- Source pages: `Skills`, `Runbooks`, `Registry`, `AgentSkills`.

7. **Settings**
- Source pages: `Configs`, `Settings`, integration pages (`CxImport`, `CxDeploy`, `AdkImport`, `AdkDeploy`), advanced pages (`JudgeOps`, `ContextWorkbench`, `ScorerStudio`, `ProjectMemory`, optionally `IntelligenceStudio`).

### Concrete route collapse (example)

- Keep:
  - `/`
  - `/diagnose`
  - `/changes`
  - `/evals`
  - `/deploy`
  - `/library`
  - `/settings`
- Remove direct nav exposure of 24 routes; preserve deep links as subroutes/tabs where needed.

### Why this is necessary

The current route and nav wiring (`web/src/App.tsx`, `web/src/components/Sidebar.tsx`, `web/src/components/Layout.tsx`) surfaces too many internal subsystems as primary user choices. That makes the product feel like infrastructure, not workflow.

---

## 5. The Magic Moments (5 UX upgrades)

1. **One-click “Find and Fix” from Dashboard**
- Add a primary CTA on `Dashboard.tsx` that runs diagnosis + proposes one fix + opens diff confirmation.
- Powered by existing pieces in `api/routes/diagnose.py`, `api/routes/autofix.py`, and `api/routes/changes.py`.
- User value: from confusion to action in ~15 seconds.

2. **Executive Explain mode on every decision page**
- Add “Explain this in 3 sentences” button on Dashboard, Diagnose, Changes, Deploy.
- Reuse existing NL stack patterns in `runner.py` (`explain`, `diagnose`) and `api/routes/edit.py`.
- User value: instant stakeholder-ready updates.

3. **Universal Undo (not buried rollback)**
- Add prominent Undo action tied to last deployed change on Changes + Deploy.
- Backed by deployer controls (`api/routes/deploy.py`, `api/routes/control.py`).
- User value: confidence to iterate.

4. **Real-time trust panel during optimization**
- Replace simulated `LiveOptimize` with real event stream from actual task progress and gate decisions.
- Integrate task updates from `/api/tasks/{task_id}` and websocket `/ws`.
- User value: visible safety and significance checks, not black-box “running...”.

5. **Victory snapshots with sharable before/after**
- On accepted change, auto-generate a compact summary card: issue, diff summary, score delta, risk.
- Data is already present in `optimizer/change_card.py`, `optimizer/memory.py`, `evals/statistics.py`.
- User value: users remember wins and share proof.

---

## 6. The Naming Audit

Current naming mixes research jargon, infra language, and UX language in the same flow.

| Current term | Problem | Better term |
|---|---|---|
| Experiment | Academic framing for production users | Change |
| Change Review | Duplicates experiment concept | Changes |
| Opportunity Queue | Sounds like backlog grooming | Issues |
| Blame Map | Emotionally loaded and technical | Root Causes |
| AutoFix Copilot | Separate product vibe | Suggested Fixes |
| Judge Ops | Internal team language | Eval Quality |
| Context Workbench | Tool-builder language | Memory & Context |
| Scorer Studio | Meta-tool naming | Metrics Designer |
| Runbooks | Overlaps with skills/library | Playbooks |
| Agent Skills | Overlaps with skills | Generated Skills |
| Full/Adaptive/Pro search | Algorithm-first framing | Optimization Level (Basic/Smart/Experimental) |
| Holdout rotation | Statistical implementation detail | Validation Guard |

### Where this must be applied

- Nav labels in `web/src/components/Sidebar.tsx`.
- Page titles in `web/src/components/Layout.tsx` and page-level `<PageHeader/>` usage.
- CLI help output in `runner.py` command docs.
- API docs text in `docs/api-reference.md`, `docs/cli-reference.md`, `docs/app-guide.md`.

---

## 7. The First 5 Minutes (ideal new user flow)

### Current first 5 minutes (too much assembly)
- `autoagent init`
- `autoagent eval run`
- `autoagent optimize`
- `autoagent server`

This is capable, but not guided. The user has to infer intent and next step from tool-centric commands.

### Ideal first 5 minutes

1. `autoagent init --guided`
- Ask only 3 choices:
  - Agent platform (ADK/CX/Custom)
  - Primary goal (routing/safety/quality/cost)
  - Data source (import transcript / use sample data)

2. Auto-seed one realistic failure cluster
- Use existing synthetic tooling (`evals/synthetic.py`, `evals/vp_demo_data.py`) but scenario-match the user’s chosen goal.

3. Auto-run baseline eval and diagnosis
- Show one headline issue with confidence and business impact.

4. Offer one recommended change card
- Diff preview + expected lift + risk.

5. Ask one confirmation
- “Apply and test now?” -> run gated eval -> show before/after.

The user must see a meaningful improvement before minute five.

---

## 8. The Daily Loop (power-user rhythm)

A good daily workflow should be 3 moves, not 12 pages.

1. **Morning check (Home)**
- Health trend, active risks, overnight deployments, budget posture.
- One-line recommendation: “Run Diagnose for routing drift in BillingAgent.”

2. **Midday fix (Diagnose -> Changes)**
- Pick top issue.
- Review one candidate change.
- Approve or reject.

3. **Evening verify (Evaluate -> Deploy)**
- Confirm guardrails + significance.
- Promote or rollback.

### What to stop doing

- Forcing users to manually hop `Opportunities` -> `AutoFix` -> `Experiments` -> `Change Review` -> `Deploy` for one fix.
- Making users think in subsystem boundaries rather than task boundaries.

---

## 9. The VP Demo (30 seconds, not 30 minutes)

### 30-second script

1. Open Home. Say: “This agent is unhealthy because billing requests are misrouted.”
2. Click **Find and Fix**.
3. Show generated root cause and diff in one panel.
4. Click **Apply + Evaluate**.
5. Show delta: success up, violations unchanged, latency unchanged, significance passed.
6. Click **Deploy Canary**.

Done.

### What kills the current demo

- Long feature-tour narrative (`runner.py` `demo vp` is polished but too long for exec attention).
- Too many conceptual detours: judge calibration, Pareto frontier, context simulation, etc.

### Demo principle

Show one business problem, one fix, one measurable result, one safety proof.

---

## 10. Priority-Ordered Action Items (with effort)

Effort scale:
- **S** = 1-2 days
- **M** = 3-5 days
- **L** = 1-2 weeks
- **XL** = 3+ weeks

### P0 (do first)

1. **Collapse Improve IA into one Changes workflow** — **L**
- Merge UX from `Optimize.tsx`, `LiveOptimize.tsx`, `Experiments.tsx`, `ChangeReview.tsx`, `AgentStudio.tsx`.
- Add tabbed subviews instead of separate sidebar entries.
- Files: `web/src/App.tsx`, `web/src/components/Sidebar.tsx`, all five page files above.

2. **Create single Diagnose page** — **L**
- Merge `Traces`, `BlameMap`, `Opportunities`, `AutoFix` into one issue-centric flow.
- Files: `web/src/pages/Traces.tsx`, `BlameMap.tsx`, `Opportunities.tsx`, `AutoFix.tsx`, plus shared components.

3. **Remove simulated Live Optimize path from default UX** — **S**
- Hide `/live-optimize` route and nav.
- Keep API route as experimental until real telemetry is wired.
- Files: `web/src/App.tsx`, `web/src/components/Sidebar.tsx`, `api/routes/optimize_stream.py`.

4. **Unify “experiment” and “change card” data model naming** — **M**
- Choose one canonical artifact name (`change`).
- Map old endpoints for backward compatibility.
- Files: `api/routes/experiments.py`, `api/routes/changes.py`, `optimizer/experiments.py`, `optimizer/change_card.py`, `runner.py` (`reject`, `review` commands).

5. **Ship first-run guided setup** — **L**
- Add guided `init` flow with scenario and immediate diagnose+fix sequence.
- Files: `runner.py` (`init`, `quickstart`, `demo` sections), `evals/synthetic.py`, `evals/vp_demo_data.py`.

### P1 (next)

6. **Move advanced tools under Settings -> Advanced** — **M**
- Demote `JudgeOps`, `ContextWorkbench`, `ScorerStudio`, `ProjectMemory` from top nav.
- Files: `web/src/components/Sidebar.tsx`, `web/src/App.tsx`, `web/src/pages/Settings.tsx`.

7. **Consolidate Integrations into one page** — **M**
- Merge `CxImport`, `CxDeploy`, `AdkImport`, `AdkDeploy` into `/integrations`.
- Files: integration page components + routing + API hooks in `web/src/lib/api.ts`.

8. **Remove mock quick-fix CTA from production path** — **S**
- Disable dashboard `FixButton` or replace with real pipeline call.
- Files: `web/src/components/FixButton.tsx`, `api/routes/quickfix.py`, `web/src/pages/Dashboard.tsx`.

9. **Standardize route/documentation truth** — **M**
- Docs currently conflict with implementation (e.g., route names/counts differ across `ARCHITECTURE_OVERVIEW.md`, `docs/getting-started.md`, `docs/app-guide.md`).
- Produce one generated source-of-truth route/command table.
- Files: docs listed + generation script in `scripts/` or `docs/` tooling.

10. **Add executive summary controls on key pages** — **M**
- “Explain this” button and copy-to-Slack action on Home/Diagnose/Changes/Deploy.
- Files: shared component + integrations in key pages and API summary helper.

### P2 (after core simplification)

11. **Rationalize search/scoring mode exposure** — **L**
- Keep internal capabilities, reduce user-facing controls to default + experimental toggle.
- Files: `web/src/pages/Optimize.tsx`, `optimizer/mode_router.py`, `optimizer/search.py`, `evals/scorer.py`, `autoagent.yaml` docs.

12. **Library IA consolidation** — **L**
- Merge Skills/Runbooks/Registry/Agent Skills UX and reduce API fragmentation where possible.
- Files: `web/src/pages/Skills.tsx`, `Runbooks.tsx`, `Registry.tsx`, `AgentSkills.tsx`, routes `/api/skills`, `/api/runbooks`, `/api/registry`, `/api/agent-skills`.

13. **Reposition Intelligence Studio** — **M**
- Decide explicitly: core page, advanced page, or separate product module.
- Files: `web/src/pages/IntelligenceStudio.tsx`, `api/routes/intelligence.py`, nav and docs.

---

## Final Product Verdict

The engine is strong. The product is overloaded.

AutoAgent already has the ingredients to be exceptional:
- Real optimization loop and gating (`optimizer/loop.py`, `evals/*`, `observer/*`).
- Rich operator controls (`runner.py`, `api/routes/*`).
- Deep diagnostics and improvement primitives.

But the current surface area turns internal architecture into user-facing taxonomy. The result is cognitive drag where there should be momentum.

If you cut the top-level experience to 7 pages and enforce one canonical workflow (Diagnose -> Change -> Evaluate -> Deploy), this becomes a sharp product instead of a feature warehouse.
