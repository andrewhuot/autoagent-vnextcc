# CX Deploy Hardening Plan

**Date**: 2026-04-08
**Branch**: `feat/cx-deploy-hardening-claude`
**Baseline**: `master @ 8527d54`

## Objective

Make CX export/deploy production-grade: diff clarity, preflight validation, safer round-trip, environment/version awareness, canary/promotion/rollback, and trustworthy UX so customers can safely push optimized agents back to CX production.

## Current State

- CX import/export works with portability reports and surface coverage matrix
- Basic deploy to CX environments (production, staging, draft)
- Version manager with pre/post-optimization snapshots
- ExportReadiness shows safe/lossy surfaces at the surface level
- Diff/sync against remote CX with conflict detection
- CxValidator validates agent type, tools, MCP transport, function deps

## Gaps

1. **No preflight gate** — Export/deploy routes don't run CxValidator before pushing
2. **Diff not classified** — Changes show as flat list without safe/lossy/blocked labels per change
3. **No canary workflow** — Deploy is all-or-nothing to an environment
4. **No environment state** — Deploy page doesn't show current environment versions
5. **No promote/rollback** — No way to promote canary or rollback after deploy
6. **UX doesn't communicate risk** — Frontend shows changes but doesn't classify what's risky vs safe

## Implementation

### Task 1: Backend Types & Models

Add to `cx_studio/types.py`:
- `DeployPhase` enum: `preflight | canary | promoted | rolled_back`
- `PreflightResult` model: validation result + export matrix + blockers/warnings
- `CanaryState` model: phase, traffic_pct, deployed_version, promoted_at, rolled_back_at
- Extend `DeployResult` with phase, preflight_result, canary_state

Add to `api/models.py`:
- `CxPreflightResponse` — preflight result for API consumers
- `CxCanaryRequest` / `CxPromoteRequest` / `CxRollbackRequest`
- `CxDeployStatusResponse` with environment versions and canary state

### Task 2: Exporter Diff Classification

Enhance `CxExporter.diff_agent()` / `compute_changes()` to tag each change with:
- `safety: "safe" | "lossy" | "blocked"` based on surface parity
- `surface: str` linking to cxas-surface-matrix coverage
- `rationale: str` explaining why

### Task 3: Canary/Promote/Rollback in Deployer

Add to `CxDeployer`:
- `deploy_canary(ref, traffic_pct=10)` — deploy to canary slice
- `promote_canary(ref)` — promote canary to full traffic
- `rollback(ref)` — rollback to previous version
- State tracked in `CanaryState`

### Task 4: Wire into API Routes

Add/modify routes in `api/routes/cx_studio.py`:
- `POST /cx/preflight` — run validation before export/deploy
- `POST /cx/deploy` — enhanced with preflight gate + canary support
- `POST /cx/promote` — promote canary to production
- `POST /cx/rollback` — rollback to previous version
- `GET /cx/deploy/status` — return environment versions + canary state

### Task 5: Frontend — CxDeploy Hardening

- Add preflight step before deploy (shows blockers/warnings, blocks if errors)
- Add canary controls (deploy canary → promote or rollback)
- Show current environment versions
- Classify each change in export preview as safe/lossy/blocked

### Task 6: Frontend — ExportReadiness Enhancement

- Per-change safety labels (safe/lossy/blocked) with color coding
- Blocked changes shown prominently with rationale
- Clear messaging: "These changes are safe to push" / "These require manual review"

### Task 7: Tests

Backend:
- Test preflight validation blocks on errors, passes with warnings
- Test diff classification labels
- Test canary deploy/promote/rollback state transitions
- Test new API routes

Frontend:
- Test preflight gate rendering
- Test canary control states
- Test change classification display

### Task 8: Verification

- `make test` — all backend tests pass
- `cd web && npm test` — all frontend tests pass
- `cd web && npm run build` — production build succeeds

## Non-Goals

- Deep projection/optimization work (Codex branch scope)
- Real CX API integration testing (requires live credentials)
- Telephony/CCaaS deploy targets (existing, unchanged)
