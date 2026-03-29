# Claude Code Task: Frontend Visual QA + Simplification

## Mission
Make AutoAgent VNextCC's web console look like it was shipped by OpenAI or Apple. Run Playwright visual QA, then simplify and polish everything.

## Phase 1: Playwright Visual QA
1. Install playwright + chromium in `web/`: `npx playwright install chromium`
2. Start the dev server: `cd web && npm run dev` (background)
3. Write a Playwright script `web/tests/visual-qa.spec.ts` that:
   - Screenshots every page (Dashboard, EvalRuns, EvalDetail, Optimize, Configs, Conversations, Deploy, LoopMonitor, Settings)
   - Screenshots light + dark mode if applicable
   - Screenshots empty states, loading states
   - Screenshots the CommandPalette open
   - Saves all screenshots to `web/screenshots/`
4. Run it and review every screenshot

## Phase 2: Simplify the UI (Apple/OpenAI aesthetic)
After reviewing screenshots, apply these principles:

### Design Language
- **Less is more**: Remove any visual clutter, unnecessary borders, excessive shadows
- **Whitespace**: Generous padding and margins. Let content breathe
- **Typography**: Clean hierarchy. One font family (Inter). Minimal font sizes (14px body, 13px secondary, 24-32px headings)
- **Colors**: Neutral grays (zinc/slate palette). ONE accent color (blue-600). No gradients on backgrounds
- **Cards**: Subtle borders (border-gray-200), no heavy shadows. radius-lg max
- **Tables**: Clean, minimal. Alternating rows only if needed. No heavy grid lines
- **Charts/Metrics**: Simple, bold numbers. Sparklines over complex charts
- **Empty states**: Centered, single icon, short message, one CTA button
- **Loading**: Subtle skeleton screens, not spinners
- **Navigation**: Clean sidebar, no icons unless they add clarity. Active state = subtle background, not bold colors

### Specific Targets
- Dashboard: Hero metrics at top (big numbers), then a clean table of recent runs
- EvalRuns: Simple sortable table. Status badges should be subtle (dot + text, not colored pills)
- Optimize: Clean form, results as a simple before/after comparison
- Settings: Grouped sections with clear labels
- Remove any "wow factor" animations that feel gimmicky
- CommandPalette: Should feel exactly like Cmd+K in Linear or Vercel

### Code Quality
- Extract repeated patterns into shared components
- Ensure consistent spacing (use Tailwind spacing scale consistently)
- Remove unused CSS/components
- Ensure all pages handle: loading, empty, error, populated states

## Phase 3: Documentation
- Update README.md with clean screenshots
- Ensure docs/ are accurate after UI changes

## Phase 4: Final Verification
1. Re-run Playwright screenshots after all changes
2. `npm run build` must pass with no errors
3. Commit with: `git commit -m "UI polish: Apple/OpenAI-grade simplification + visual QA"`

When completely finished, run: openclaw system event --text "Done: VNextCC frontend polish - Playwright QA + Apple/OpenAI simplification complete" --mode now
