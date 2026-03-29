# AutoAgent VNextCC — Frontend & Docs Polish Task

Read PRODUCT_BRIEF.md for the full product vision and CUJs.

## Phase 1: Frontend Deep Polish

The web console exists at `web/src/` (React + Vite + TypeScript + Tailwind). 9 pages built:
Dashboard, EvalRuns, EvalDetail, Optimize, Configs, Conversations, Deploy, LoopMonitor, Settings.

Your job: make this feel like a product OpenAI or Vercel would ship.

### For EVERY page:
1. **Read the component code** thoroughly
2. **Check data flow** — does it connect to the API correctly? Handle loading/error/empty states?
3. **Polish the UI**:
   - Consistent spacing, alignment, typography
   - Proper loading skeletons (not just "Loading...")
   - Empty states with helpful CTAs ("No eval runs yet. Create your first →")
   - Error states with retry buttons
   - Responsive layout (desktop-first but don't break on tablet)
   - Smooth transitions between pages
4. **Enhance data visualization**:
   - Dashboard: health score should be a prominent gauge/ring, sparklines for trends
   - EvalDetail: score breakdown as horizontal bar chart, per-case results as color-coded table
   - Optimize: cycle-by-cycle timeline with score trajectory line chart
   - LoopMonitor: real-time score trajectory, cycle cards with accept/reject badges
   - Configs: syntax-highlighted YAML with diff view
5. **Navigation**: sidebar should highlight active page, collapse on mobile, have clean icons
6. **Design tokens**: ensure consistent color usage (blue=primary, green=success, amber=warning, red=error, gray=neutral)
7. **Typography**: Inter font, proper heading hierarchy, monospace for code/YAML/config

### Specific enhancements:
- Add a **global command palette** (Cmd+K) for power users — search across evals, configs, conversations
- Add **toast notifications** for async operations (eval started, optimization complete, deploy succeeded)
- Add **breadcrumbs** on detail pages
- Add **keyboard shortcuts** (n=new eval, o=optimize, d=deploy)
- Add **comparison mode** on EvalRuns — select 2 runs and compare side-by-side
- Ensure **WebSocket** connections for real-time updates actually work (eval progress, optimization cycles, loop monitor)

### Component library:
Create reusable components in `web/src/components/`:
- `StatusBadge` — colored badge for pass/fail/pending/running
- `ScoreDisplay` — formatted score with color gradient (red→yellow→green)
- `YamlViewer` — syntax-highlighted YAML with copy button
- `YamlDiff` — side-by-side diff of two YAML configs
- `MetricCard` — metric name, value, trend arrow, sparkline
- `TimelineEntry` — timestamp, title, description, status badge
- `ConversationView` — expandable conversation turns with role colors
- `EmptyState` — icon, title, description, CTA button
- `LoadingSkeleton` — shimmer loading placeholders

## Phase 2: Documentation Enhancement

Docs exist at `docs/` (9 files). Enhance them:

1. **README.md** — should be a compelling landing page:
   - Clear value prop in first sentence
   - Architecture diagram (ASCII art)
   - 3-step quickstart
   - Screenshot references
   - Badges (tests passing, Python version, license)

2. **docs/getting-started.md** — step-by-step with code blocks, expected output shown

3. **docs/concepts.md** — add diagrams (ASCII art flow diagrams), make the autoresearch loop crystal clear

4. **docs/cli-reference.md** — every command with:
   - Synopsis
   - Options table
   - Example with expected output
   - Related commands

5. **docs/api-reference.md** — every endpoint with:
   - Method + path
   - Request body (JSON example)
   - Response body (JSON example)
   - Status codes
   - curl example

6. **docs/app-guide.md** — walkthrough each page with what to look for

7. **docs/architecture.md** — technical deep dive with data model, extension points

8. **docs/cx-agent-studio.md** — practical integration guide for Google Cloud customers

9. **docs/deployment.md** — Cloud Run deployment steps, environment variables, production config

All docs should follow OpenAI's documentation style: clear, concise, code-heavy, no fluff.

## Phase 3: Integration Verification

1. Verify the full stack works: `python runner.py server` starts API + serves frontend
2. Verify all API endpoints return proper data
3. Verify frontend pages render with mock/seed data
4. Verify CLI commands work
5. Run all tests — fix any failures

When completely finished, run: openclaw system event --text 'Done: AutoAgent VNextCC Codex frontend + docs polish complete' --mode now
