# Cohesive Item 5 Product Polish Plan - Codex

## Scope

Execute Item 5 only from `/Users/andrew/Desktop/agentlab/docs/plans/2026-04-12-cohesive-product-hardening.md`.

This session is a cohesive UX language pass across navigation, labels, status language, empty states, degraded/error states, and action wording. It will not change Item 3 truthfulness semantics, backend verdict logic, drift/context-report behavior, or fake-progress detection.

## Current Surface Findings

- Shared shell already has a journey strip in `web/src/components/Layout.tsx`, but the sidebar uses `Improve` where the rest of the journey uses `Optimize` and `Review`.
- `web/src/lib/utils.ts` has `statusVariant()` and `statusLabel()`, but status copy is mostly pass-through formatting. Labels such as `pending_review`, `rolled_back`, `no-op`, `Fallback mode`, and `No deployment history yet.` are surfaced ad hoc.
- `web/src/components/StatusBadge.tsx` delegates only label casing to utils and requires each caller to choose a variant.
- `web/src/components/EmptyState.tsx` is present, but page-level empty/degraded states often use local dashed boxes with one-line copy.
- `web/src/pages/Build.tsx`, `web/src/pages/Optimize.tsx`, `web/src/pages/Improvements.tsx`, and `web/src/pages/Deploy.tsx` already contain strong journey/action concepts. The pass should normalize that copy rather than introduce a new UX model.
- `web/src/components/MockModeBanner.tsx` already distinguishes preview, frontend-only, workspace-invalid, and rate-limited states. It should keep that behavior while using the same degraded-state language family where possible.

## Implementation Plan

### Phase 1 - Status Language Contract

1. Add focused failing tests for product status formatting:
   - `blocked`
   - `ready`
   - `interrupted`
   - `review_required`
   - `pending_review`
   - `promoted`
   - `rejected`
   - `no_data`
   - deployed/rolled-back/no-op aliases already used in the product
2. Implement a central status metadata helper in `web/src/lib/utils.ts`.
3. Keep the existing `statusVariant()` and `statusLabel()` exports compatible, but route them through the central mapping.
4. Update status badges/action surfaces only where they already use product statuses.

Verification:

```bash
cd /Users/andrew/Desktop/agentlab-cohesive-product-polish-codex/web
npm run test -- src/lib/utils.test.ts src/components/Layout.test.ts src/pages/Build.test.tsx src/pages/Improvements.test.tsx src/pages/Deploy.test.tsx
```

### Phase 2 - Navigation And Action Wording

1. Align the sidebar guided flow to the product spine:
   - Setup
   - Build
   - Eval
   - Optimize
   - Review
   - Deploy
2. Keep the existing Layout journey strip as the main five-step product journey.
3. Normalize CTA wording around Eval, Review, and Deploy without changing behavior:
   - use `Run Eval` for eval handoff CTAs
   - use `Review pending change` / `Open Review` when routing to the review queue
   - use `Promote canary` for canary promotion actions
   - avoid `Deploy Now` where the action routes to Deploy rather than immediately deploying
4. Update Layout/Build/Improvements/Deploy tests to lock the wording.

Verification:

```bash
cd /Users/andrew/Desktop/agentlab-cohesive-product-polish-codex/web
npm run test -- src/components/Layout.test.ts src/pages/Build.test.tsx src/pages/Improvements.test.tsx src/pages/Deploy.test.tsx
```

### Phase 3 - Empty And Degraded State Component

1. Extend or reuse `web/src/components/EmptyState.tsx` so key empty/degraded states explain:
   - why no data is visible,
   - whether the state is expected, blocked, or degraded,
   - what the operator can do next.
2. Apply minimal page-level updates:
   - Build saved artifacts empty state
   - Improvements history loading/error/empty states
   - Deploy missing status, error, no canary, and no history states
   - keep MockModeBanner state behavior intact
3. Avoid large visual restyling. This is copy/structure cohesion, not a redesign.

Verification:

```bash
cd /Users/andrew/Desktop/agentlab-cohesive-product-polish-codex/web
npm run test -- src/pages/Build.test.tsx src/pages/Improvements.test.tsx src/pages/Deploy.test.tsx src/components/MockModeBanner.test.tsx
```

### Phase 4 - Checklist And Cross-Surface Validation

1. Create `docs/plans/ui-copy-cohesion-checklist.md`.
2. Include page-by-page checks for:
   - label consistency,
   - action clarity,
   - blocked-state clarity,
   - next-step clarity,
   - historical vs live state clarity.
3. Run targeted Vitest, Playwright coverage if available for touched journey surfaces, and `npm run build`.
4. Review `git diff` before committing.

Verification:

```bash
cd /Users/andrew/Desktop/agentlab-cohesive-product-polish-codex/web
npm run test -- src/lib/utils.test.ts src/components/Layout.test.ts src/components/MockModeBanner.test.tsx src/pages/Build.test.tsx src/pages/Improvements.test.tsx src/pages/Deploy.test.tsx
npx playwright test tests/mock-mode-banner.spec.ts tests/broken-route-regressions.spec.ts
npm run build
```

## Files Expected To Change

- `web/src/lib/utils.ts`
- `web/src/lib/types.ts`
- `web/src/lib/utils.test.ts`
- `web/src/components/StatusBadge.tsx`
- `web/src/components/EmptyState.tsx`
- `web/src/components/Sidebar.tsx`
- `web/src/components/Layout.test.ts`
- `web/src/pages/Build.tsx`
- `web/src/pages/Build.test.tsx`
- `web/src/pages/Improvements.tsx`
- `web/src/pages/Improvements.test.tsx`
- `web/src/pages/Deploy.tsx`
- `web/src/pages/Deploy.test.tsx`
- `docs/plans/ui-copy-cohesion-checklist.md`

## Commit And Push Plan

Use one logical commit for this scoped Item 5 pass unless the implementation naturally splits cleanly after tests:

```bash
git add docs/plans/ui-copy-cohesion-checklist.md working-docs/cohesive-item5-plan-codex.md web/src/lib web/src/components web/src/pages
git commit -m "feat(ui): polish cohesive product language"
git push origin feat/cohesive-product-polish-codex
```

After push, run:

```bash
openclaw system event --text "Done: Codex finished cohesive Item 5 product polish on feat/cohesive-product-polish-codex" --mode now
```
