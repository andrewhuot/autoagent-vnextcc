# WOW Features Brief — 6 Features to Make AutoAgent Magical

## Overview
Build 6 high-impact UX features that create "wow" moments. These transform AutoAgent from a competent tool into something people want to show their boss.

**Current state**: 1,429 tests, 24 web pages, 38 CLI commands. All features are ADDITIVE — don't break anything.

---

## Feature 1: Animated Score Celebration

### Web Console
When a new optimization result improves the score, trigger a celebration:
- **Confetti burst**: Use a lightweight CSS-only confetti animation (no library). Create `web/src/components/Confetti.tsx` — absolutely positioned particles that burst from the score card and fade out over 2 seconds.
- **Score counter animation**: When the composite score updates, animate the number counting up from old → new value (like a slot machine). Create `web/src/components/AnimatedNumber.tsx` using `requestAnimationFrame`.
- **Glow pulse**: The MetricCard that improved gets a brief green glow border animation (CSS `@keyframes glow`).
- **"New personal best!" badge**: If the score exceeds all previous scores, show a gold badge with sparkle icon that appears for 5 seconds.

### CLI
- When a cycle improves score in quickstart/optimize: print `✨ New personal best!` in gold/yellow when it exceeds the all-time best.
- Add a subtle sparkle to the improvement line: `  ✓ composite=0.8342 (+0.065) ✨`

### Files to create/modify:
- CREATE: `web/src/components/Confetti.tsx` (~80 lines, CSS-only particles)
- CREATE: `web/src/components/AnimatedNumber.tsx` (~60 lines, counting animation)
- MODIFY: `web/src/pages/Dashboard.tsx` (integrate celebrations)
- MODIFY: `web/src/components/MetricCard.tsx` (glow animation on improvement)
- MODIFY: `runner.py` (sparkle on CLI improvements)

---

## Feature 2: Live Optimization Feed (Server-Sent Events)

### Backend
Add Server-Sent Events (SSE) endpoint for real-time optimization progress:
- **Endpoint**: `GET /api/optimize/stream` — SSE stream
- **Events emitted during optimization cycle**:
  1. `cycle_start` — `{ cycle: 1, total: 3 }`
  2. `diagnosis` — `{ failure_buckets: {...}, dominant: "routing_error", total_failures: 12 }`
  3. `proposal` — `{ change_description: "...", config_section: "routing", reasoning: "..." }`
  4. `evaluation` — `{ score_before: 0.72, score_after: 0.78, improvement: 0.06 }`
  5. `decision` — `{ accepted: true, p_value: 0.02, effect_size: 0.06 }`
  6. `cycle_complete` — `{ cycle: 1, best_score: 0.78 }`
  7. `optimization_complete` — `{ cycles: 3, baseline: 0.72, final: 0.83, improvement: 0.11 }`

Implementation:
- Create `api/routes/optimize_stream.py` with an SSE endpoint using `StreamingResponse`
- The endpoint accepts `?cycles=3&mode=standard` query params
- It runs the optimization loop internally, yielding SSE events at each phase
- Use `asyncio.Queue` to bridge the sync optimizer with async SSE

### Web Console
Create `web/src/pages/LiveOptimize.tsx` — a dedicated live optimization page:
- Big centered display showing the current phase with animation
- Phase indicator: `Diagnosing → Proposing → Evaluating → Deciding` with active step highlighted
- Live score chart that updates in real-time as cycles complete
- Each completed cycle appears as a card below with: change description, score delta, accept/reject badge
- A "Start Optimization" button that initiates the SSE stream
- When optimization completes: trigger the confetti celebration from Feature 1

### Phase Visualization
```
  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
  │  Diagnose    │ →  │   Propose   │ →  │  Evaluate   │ →  │   Decide    │
  │  ● active    │    │  ○ pending  │    │  ○ pending  │    │  ○ pending  │
  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

Each phase box: gray when pending, blue with pulse animation when active, green check when complete, red X if failed.

### Files to create/modify:
- CREATE: `api/routes/optimize_stream.py` (~200 lines, SSE endpoint)
- CREATE: `web/src/pages/LiveOptimize.tsx` (~350 lines, live optimization page)
- CREATE: `web/src/components/PhaseIndicator.tsx` (~100 lines, step visualization)
- CREATE: `web/src/components/LiveCycleCard.tsx` (~80 lines, completed cycle card)
- MODIFY: `api/server.py` (register new route)
- MODIFY: `web/src/App.tsx` (add route)
- MODIFY: `web/src/components/Sidebar.tsx` (add nav item with special styling)

---

## Feature 3: Agent Health Pulse

### Web Console
Replace the static health score display with a living, breathing indicator:

- **Pulse Ring**: A circular SVG around the health score that pulses:
  - Green, slow pulse (3s) = healthy (>0.85)
  - Amber, medium pulse (1.5s) = warning (0.65-0.85)  
  - Red, fast pulse (0.8s) = critical (<0.65)
- **Heart Rate Line**: A small ECG-style line animation next to the score (CSS animated SVG path)
- **Status Text**: Below the pulse ring, animated text: "Healthy", "Needs Attention", or "Critical"

Create `web/src/components/HealthPulse.tsx`:
```tsx
interface HealthPulseProps {
  score: number;        // 0-1
  label?: string;       // "Agent Health"
  size?: 'sm' | 'md' | 'lg';
}
```

The pulse should be pure CSS/SVG — no animation libraries. Use `@keyframes` with `scale()` and `opacity`.

Place this prominently on the Dashboard — it should be the first thing users see.

### Files to create/modify:
- CREATE: `web/src/components/HealthPulse.tsx` (~120 lines)
- MODIFY: `web/src/pages/Dashboard.tsx` (replace static score with HealthPulse)

---

## Feature 4: Natural Language Command Palette Search

### Enhance the existing CommandPalette
Currently the ⌘K palette searches pages and items by label. Enhance it to understand natural language queries:

**Query → Result mapping** (no LLM — keyword matching):
- "why is routing failing?" → Jump to Blame Map filtered on routing_error + show relevant traces
- "fix safety" → Show "Apply tighten-safety-policy runbook" action
- "what changed?" → Jump to Changes page
- "show me failures" → Jump to Conversations filtered on outcome=fail
- "how is my agent doing?" → Jump to Dashboard
- "deploy to production" → Jump to CX Deploy page
- "import agent" → Jump to CX Import page
- "optimize" → Jump to Live Optimize page (Feature 2)
- "compare configs" → Jump to Configs page

Implementation:
- Create a keyword → action mapping table
- Fuzzy match user input against keywords
- Show matched actions with relevance score
- Group results: "Suggested Actions" (runbook applies, optimization), "Navigate" (pages), "Recent" (items)

Add a `SmartSearch` category to the palette that appears above regular results when the query matches.

### Files to create/modify:
- MODIFY: `web/src/components/CommandPalette.tsx` (add smart search logic, ~100 lines added)

---

## Feature 5: Journey Timeline on Dashboard

### Web Console
A horizontal timeline visualization showing the agent's optimization journey:

```
 ──●──────●──────●──────●──────●──────●──
   │      │      │      │      │      │
  v001   v002   v003   v004   v005   v006
  0.65   0.69   0.73   0.73   0.78   0.83
  base   +0.04  +0.04  reject +0.05  +0.05
         routing safety  ✗     tools  examples
```

Create `web/src/components/JourneyTimeline.tsx`:
- Horizontal scrollable timeline
- Each node is a circle: green (accepted), red (rejected), gray (baseline)
- Hover over a node → tooltip with: config version, score, change description, timestamp
- Click a node → navigate to that experiment's detail page
- The line between nodes animates on load (draws itself left to right)
- Current/latest node has a pulsing ring (reuse HealthPulse animation)
- Score values displayed below each node
- Change descriptions displayed above (truncated, full on hover)

Data source: optimization history from `/api/optimize/history`

Place this on the Dashboard between the health metrics and the failure breakdown.

### Files to create/modify:
- CREATE: `web/src/components/JourneyTimeline.tsx` (~200 lines)
- MODIFY: `web/src/pages/Dashboard.tsx` (integrate timeline)

---

## Feature 6: One-Click "Fix This" Buttons

### Web Console
On the Dashboard's failure breakdown section, add actionable "Fix →" buttons:

For each failure bucket displayed:
- Show a "Fix →" button next to the failure bar
- Button maps failure family to the matching runbook:
  - `routing_error` → `fix-retrieval-grounding`
  - `safety_violation` → `tighten-safety-policy`
  - `quality_issue` → `enhance-few-shot-examples`
  - `latency_problem` → `reduce-tool-latency`
  - `cost_overrun` → `optimize-cost-efficiency`
  - `tool_error` → `reduce-tool-latency`
  - `hallucination` → `fix-retrieval-grounding`
- Clicking "Fix →" opens a confirmation modal: "Apply runbook 'fix-retrieval-grounding' and run 1 optimization cycle?"
- On confirm: POST to a new API endpoint that applies the runbook + runs optimize
- While running: button shows a spinner, then shows ✓ or ✗ with the result

### Backend
- Create endpoint: `POST /api/quickfix` with body `{ failure_family: "routing_error" }`
- The endpoint: looks up the matching runbook, loads its surfaces/skills, runs one optimization cycle targeting those surfaces, returns the result
- This is the "one-click fix" — diagnosis → runbook → optimize → result in a single API call

### Files to create/modify:
- CREATE: `web/src/components/FixButton.tsx` (~80 lines, button + modal + loading state)
- CREATE: `api/routes/quickfix.py` (~100 lines, quickfix endpoint)
- MODIFY: `web/src/pages/Dashboard.tsx` (add FixButton to failure breakdown)
- MODIFY: `api/server.py` (register quickfix route)

---

## Implementation Plan

### Phase 1: Planning (Opus)
1. Read this brief thoroughly
2. Read the existing Dashboard.tsx, CommandPalette.tsx, api/server.py, and runner.py
3. Create a detailed IMPLEMENTATION_PLAN.md with exact component APIs, CSS animations, and endpoint schemas
4. Update tests/test_dependency_layers.py if any new modules need layer classification

### Phase 2: Parallel Execution (Sonnet sub-agents)
Dispatch 4 parallel tracks:

**Track A — Components**: Features 1 + 3 (Confetti, AnimatedNumber, HealthPulse, MetricCard glow)
**Track B — Live Feed**: Feature 2 (SSE endpoint, LiveOptimize page, PhaseIndicator, LiveCycleCard)
**Track C — Dashboard Integration**: Features 5 + 6 (JourneyTimeline, FixButton, quickfix API, Dashboard wiring)
**Track D — Command Palette + CLI**: Feature 4 (smart search) + Feature 1 CLI sparkles

### Phase 3: Integration (Opus)
1. Wire all components into Dashboard.tsx
2. Add routes, nav items, imports
3. Run full test suite
4. Run TypeScript check
5. Run dependency layer test
6. Commit and push

## Quality Bar
- `python3 -m pytest tests/ -x -q` — must pass with MORE tests than 1,429
- `cd web && npx tsc --noEmit` — must pass
- `python3 -m pytest tests/test_dependency_layers.py -v` — must pass
- New tests for: SSE endpoint, quickfix endpoint, CLI sparkles, recommendation mapping

## When Done
Commit: `feat: wow UX — celebrations, live feed, health pulse, smart search, journey timeline, one-click fix`
Push to master.
Run: `openclaw system event --text "Done: 6 wow features — celebrations, live feed, health pulse, smart search, timeline, quickfix" --mode now`
