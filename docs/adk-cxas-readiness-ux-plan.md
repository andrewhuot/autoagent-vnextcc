# ADK / CXAS Readiness UX Plan

## Problem Statement

Customers importing ADK or CX agents into AgentLab currently see:
- A simple parse → preview → import wizard
- Minimal information about what was preserved, what is optimizable, and what is outside support
- No readiness/eligibility scoring
- No visibility into callbacks, graph complexity, tool-code boundaries, or round-trip risk
- Generic "next steps" guidance that doesn't differentiate based on import quality

This makes the product feel hand-wavy rather than trustworthy. Customers cannot make informed decisions about whether AgentLab is a good fit for their imported agent.

## Design Principles

1. **Honest, not hand-wavy** — surface real coverage/gap data; don't imply universal support
2. **Glanceable** — readiness score + color-coded surface breakdown visible at a glance
3. **Actionable** — every gap shown includes a next-step (optimize, inspect, manual fix)
4. **Tolerant** — UI must handle missing/optional fields gracefully (backend may not provide all data yet)
5. **Reusable** — shared ReadinessReport component used by both ADK and CX flows

## Architecture

### New Types (`types.ts`)

```typescript
// Portability readiness report — returned alongside import results
interface PortabilityReport {
  overall_score: number;             // 0-100 readiness %
  verdict: 'ready' | 'partial' | 'needs_work' | 'unsupported';
  surfaces: PortabilitySurface[];    // per-surface breakdown
  warnings: PortabilityWarning[];    // actionable warnings
  topology?: TopologySummary;        // graph complexity info (optional)
}

interface PortabilitySurface {
  name: string;                      // e.g., "instructions", "tools", "routing"
  status: 'full' | 'partial' | 'read_only' | 'unsupported';
  detail: string;                    // human-readable explanation
  item_count?: number;               // how many items in this surface
  optimizable_count?: number;        // how many can be optimized
}

interface PortabilityWarning {
  severity: 'info' | 'warning' | 'critical';
  category: string;                  // e.g., "callbacks", "code_tools", "round_trip"
  message: string;
  recommendation: string;
}

interface TopologySummary {
  node_count: number;
  edge_count: number;
  max_depth: number;
  has_cycles: boolean;
  callback_count: number;
  code_tool_count: number;           // tools with function_body (opaque code)
}
```

### New API Hooks (`api.ts`)

- Extend `AdkImportResult` and `CxImportResult` with optional `portability?: PortabilityReport`
- The UI renders the report when present, shows a "basic import" fallback when absent

### New Shared Component

`web/src/components/ReadinessReport.tsx`
- Takes a `PortabilityReport` (or null) as prop
- Renders: overall score ring, surface breakdown table, warnings list, next-step CTAs
- Renders graceful fallback when report is null (basic summary only)

### Page Changes

**AdkImport (Step 3: Done)**
- Show ReadinessReport panel after import success
- Replace generic "next steps" with report-driven guidance
- Surface topology info if present (graph complexity, callbacks, code tools)

**CxImport (Step 4: Done)**
- Same ReadinessReport panel
- Surface-specific: CX has test cases, playbooks, flows — show coverage per surface

**AdkDeploy**
- Add "Export Readiness" section showing round-trip risk
- Warn about surfaces that are read-only or will be lost on export

**CxDeploy**
- Add "Export Readiness" section before the push-to-CX button
- Show which changes are safe vs. which may cause conflicts

### Test Plan

- Unit tests for ReadinessReport component (full report, partial report, null report)
- Updated AdkImport test: verify readiness panel renders with portability data
- Updated CxImport test: verify readiness panel renders with portability data
- Build verification: `npm run build` must pass
- Type-check: `npx tsc --noEmit` must pass

## Surfaces & Status Labels

| Status | Color | Meaning |
|--------|-------|---------|
| full | green | Fully imported and optimizable |
| partial | amber | Imported but some items need manual review |
| read_only | blue | Imported for reference, not editable in AgentLab |
| unsupported | gray | Not imported — outside current support |

## Verdict Mapping

| Score | Verdict | Banner Color | Message |
|-------|---------|-------------|---------|
| 80-100 | ready | green | "Agent is ready for optimization in AgentLab" |
| 50-79 | partial | amber | "Agent imported with gaps — review before optimizing" |
| 20-49 | needs_work | orange | "Significant gaps — manual engineering may be needed" |
| 0-19 | unsupported | red | "Agent structure not well-suited for AgentLab optimization" |

## File Changes Summary

| File | Change |
|------|--------|
| `web/src/lib/types.ts` | Add portability report types |
| `web/src/lib/api.ts` | Extend import result types (optional portability field) |
| `web/src/components/ReadinessReport.tsx` | New reusable component |
| `web/src/pages/AdkImport.tsx` | Add readiness panel to success step |
| `web/src/pages/CxImport.tsx` | Add readiness panel to success step |
| `web/src/pages/AdkDeploy.tsx` | Add export readiness section |
| `web/src/pages/CxDeploy.tsx` | Add export readiness section |
| `web/src/pages/AdkImport.test.tsx` | Extend tests for readiness panel |
| `web/src/pages/CxImport.test.tsx` | Extend tests for readiness panel |
| `web/src/components/ReadinessReport.test.tsx` | New test file |
