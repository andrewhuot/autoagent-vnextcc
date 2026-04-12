# Merge All 7 Remediations Plan - Codex

Date: 2026-04-12
Branch: merge/all-seven-remediations-codex
Base: origin/master at 888fe0aa4833f54ebe2e2b632ea3a92248241337

## Mission

Land all seven completed remediation branches onto master, preserving the product intent from the audit: make trust surfaces honest, make Workbench completion evidence-backed, make runtime state durable and coherent, and keep the BUILD -> EVAL -> OPTIMIZE -> REVIEW -> DEPLOY journey usable end to end.

## Source Context Read

- /Users/andrew/Desktop/agentlab-full-repo-audit-claude-sonnet/working-docs/repo-audit-exec-summary-claude-sonnet.md
- /Users/andrew/Desktop/agentlab-full-repo-audit-claude-sonnet/working-docs/repo-product-and-codebase-recommendations-opus.md
- /Users/andrew/Desktop/agentlab-workbench-harness-claude-code-audit-codex/working-docs/workbench-harness-claude-code-audit-codex.md

Key conclusions used for this merge:

- Truthful semantics outrank compatibility shims. If a feature is partial, the product surface must say so.
- Workspace state, runtime config wiring, and event persistence are foundational trust surfaces.
- Workbench terminal success must distinguish structural validity from actual change/evidence.
- Workbench should hand off to Eval/Optimize through typed evidence, not by shortcutting into AutoFix.
- Unified review should aggregate and dispatch to source stores rather than creating a risky third store.

## Branch Inventory

### 1. feat/p0-workspace-state-validation-codex @ 77059d7

Intent: expose invalid server/workspace state instead of letting CWD failures leak later.

Touched areas:

- api/models.py
- api/routes/health.py
- api/server.py
- api/workspace_state.py
- runner.py
- web/src/components/MockModeBanner.tsx
- web/src/lib/types.ts
- workspace tests and banner tests

Resolution guardrails:

- Keep health workspace fields and invalid-workspace UI.
- Keep `agentlab server --workspace`.
- Preserve startup `os.chdir()` only when a valid workspace resolves, and restore CWD on shutdown.
- Do not weaken downstream write paths to silently proceed outside a workspace.

### 2. feat/p0-truth-surface-alignment-claude @ d324cab

Intent: close P0 trust gaps by wiring real runtime behavior and making docs/UI honest.

Touched areas:

- api/server.py
- api/routes/autofix.py
- api/routes/context.py
- api/routes/judges.py
- context/analyzer.py
- judges/drift_monitor.py
- web/src/pages/AutoFix.tsx
- docs and truth-surface tests

Resolution guardrails:

- Preserve optimizer constructor wiring for `search_strategy` and `bandit_policy`.
- Preserve `DriftMonitor(drift_threshold=runtime.optimizer.drift_threshold)`.
- Preserve AutoFix response honesty: no fake eval/canary metrics.
- Preserve context report `no_data` semantics rather than pretending aggregate health exists.

### 3. feat/p1-runtime-coherence-claude @ ea91c9c

Intent: bridge runtime/builder/websocket events into a durable unified event surface.

Touched areas:

- api/server.py
- api/routes/events.py
- api/routes/eval.py
- api/routes/loop.py
- api/routes/optimize.py
- data/event_log.py
- event unification tests

Resolution guardrails:

- Create one shared `EventLog` early in startup.
- Pass that event log into the builder `EventBroker` with `DurableEventStore`.
- Assign the same instance to `app.state.event_log`.
- Preserve broadcast-to-event-log bridges in eval, optimize, and loop routes.

### 4. feat/p0-end-to-end-journeys-claude @ e82461c

Intent: close P0 broken journeys: task persistence, builder chat persistence, import registration, and canary promotion.

Touched areas:

- api/models.py
- api/routes/adk.py
- api/routes/builder.py
- api/routes/connect.py
- api/routes/cx_studio.py
- api/routes/deploy.py
- api/server.py
- api/tasks.py
- builder/chat_service.py
- deployer/versioning.py
- web/src/lib/api.ts
- web/src/lib/builder-chat-api.ts
- web/src/lib/types.ts
- web/src/pages/Build.tsx
- web/src/pages/Deploy.tsx

Resolution guardrails:

- Preserve SQLite-backed `TaskManager` and `interrupted` task status.
- Preserve persistent `BuilderChatService` and session resume endpoints/UI.
- Preserve import registration with the active `ConfigVersionManager`.
- Preserve `POST /api/deploy/promote` and Deploy page promote flow.

### 5. feat/p0-workbench-evidence-semantics-codex @ 6700a5b

Intent: make Workbench terminal evidence semantics honest and durable.

Touched areas:

- builder/workbench.py
- web/src/components/workbench/ArtifactViewer.tsx
- web/src/lib/workbench-api.ts
- web/src/lib/workbench-store.ts
- web/src/pages/AgentWorkbench.tsx
- Workbench tests

Resolution guardrails:

- Preserve `evidence_summary`.
- Preserve stricter terminal failure on insufficient completion evidence.
- Preserve deterministic correction iteration for repairable CX compatibility failures.
- Preserve `update_tool` operation support.
- Preserve frontend hydration of run summary, harness state, evidence, durable events, review gate, and handoff state.

### 6. feat/p1-workbench-eval-optimize-bridge-codex @ 496eed5

Intent: add typed Workbench -> Eval -> Optimize bridge without running downstream loops inline.

Touched areas:

- api/routes/workbench.py
- builder/workbench.py
- builder/workbench_bridge.py
- findings.md
- web/src/components/workbench/ArtifactViewer.tsx
- web/src/lib/workbench-api.ts
- web/src/pages/Optimize.tsx
- bridge tests

Resolution guardrails:

- Preserve bridge as a typed handoff, not an AutoFix shortcut.
- Preserve materialization endpoint `POST /api/workbench/projects/{project_id}/bridge/eval`.
- Compose bridge payload into evidence-aware presentation/handoff from the prior Workbench branch.
- Preserve Optimize query-param hydration for `evalRunId`.

### 7. feat/p1-unified-review-surface-claude @ 46ba6ce

Intent: aggregate optimizer pending reviews and change cards into one operator review surface.

Touched areas:

- api/models.py
- api/routes/reviews.py
- api/server.py
- web/src/components/Sidebar.tsx
- web/src/lib/api.ts
- web/src/lib/types.ts
- web/src/lib/utils.ts
- web/src/pages/Improvements.tsx
- web/src/pages/UnifiedReviewQueue.tsx
- review tests

Resolution guardrails:

- Preserve review aggregation/dispatch layer; do not merge source stores.
- Preserve approve/reject semantics per source.
- Preserve Improvements review tab as unified queue.
- Preserve sidebar pending badge.
- Keep TypeScript contracts unified with workspace and task changes.

## Chosen Merge Order

1. `feat/p0-workspace-state-validation-codex`
2. `feat/p0-truth-surface-alignment-claude`
3. `feat/p1-runtime-coherence-claude`
4. `feat/p0-end-to-end-journeys-claude`
5. `feat/p0-workbench-evidence-semantics-codex`
6. `feat/p1-workbench-eval-optimize-bridge-codex`
7. `feat/p1-unified-review-surface-claude`

Rationale:

- Start with workspace validation because it is the root runtime truth surface and affects where all persisted state is written.
- Add truth-surface runtime wiring next, before layering event observability over runtime actions.
- Add runtime event coherence before broader journey persistence so final long-running task and loop behavior can bridge to a single event surface.
- Add end-to-end journey persistence/promote/import fixes after the foundational server state is coherent.
- Add Workbench evidence semantics before the Workbench bridge, because the bridge must hand off a candidate whose terminal status and review gate are evidence-aware.
- Add unified review last so the final operator decision surface can aggregate proposals produced by the now-coherent optimize/change-card paths.

## Expected Conflict Hotspots

- `api/server.py`: compose workspace state, persistent task manager, persistent builder chat service, early shared EventLog, durable builder EventBroker, optimizer strategy/bandit wiring, drift threshold wiring, and reviews route import.
- `api/models.py`: compose `interrupted` task status, workspace health models, and unified review models with `Literal` import.
- `web/src/lib/types.ts`: compose workspace health types, interrupted task state, and unified review types.
- `web/src/lib/api.ts`: compose canary promote hook and unified review hooks.
- `builder/workbench.py`: compose evidence semantics with improvement bridge payload injection.
- `web/src/components/workbench/ArtifactViewer.tsx`: compose evidence/review/handoff rendering with eval/optimize bridge rendering.
- `web/src/lib/workbench-api.ts`: compose evidence summary and bridge TypeScript contracts.
- `web/src/pages/Deploy.tsx`: preserve promote and rollback coherence.
- `web/src/pages/Improvements.tsx`: preserve unified review tab and history semantics.
- `findings.md`: bridge branch appends planning notes; preserve without affecting product code.

## Known Pre-Merge Hygiene Issues

`git diff --check` on individual branch diffs found trailing whitespace in:

- `working-docs/p0-truth-surface-plan-claude.md`
- `working-docs/p0-end-to-end-journeys-plan-claude.md`
- `working-docs/p1-runtime-coherence-plan-claude.md`

These should be cleaned after the branches are merged and before final `git diff --check`.

## Verification Ladder

Run after conflict resolution:

1. `git diff --check`
2. Python targeted tests:
   - `python -m pytest tests/test_workspace_state.py tests/test_api_server_startup.py tests/test_cli_commands.py`
   - `python -m pytest tests/test_truth_surface_wiring.py tests/test_event_log.py tests/test_event_unification.py`
   - `python -m pytest tests/test_p0_journey_fixes.py tests/test_unified_reviews.py`
   - `python -m pytest tests/test_workbench_multi_turn.py tests/test_workbench_eval_optimize_bridge.py`
3. Frontend targeted tests:
   - Workbench store/component/page tests touched by the Workbench branches.
   - MockModeBanner tests.
   - Deploy, Improvements, Optimize tests if present and practical.
4. Broader frontend verification:
   - `npm run build` from `web/`.
   - Broader test command if package scripts make it practical.
5. Self-review:
   - `git status --short`
   - `git diff --stat origin/master...HEAD`
   - grep conflict markers.
   - inspect the merged hotspot files for duplicate routes/types/semantics.

## Progress Log

- Read all required source docs.
- Verified seven branch tips match requested SHAs.
- Reviewed branch commit summaries, touched files, stats, hotspot diffs, and specialist reports.
- Wrote this plan before starting merges.
- Merged all seven branches in the chosen order. No textual merge conflicts occurred.
- Patched Workbench Activity bridge rendering to avoid dereferencing a missing presentation during evidence-only hydration.
- Patched Build/Builder frontend tests for the merged persistent builder-session listing behavior.
- Patched Deploy/Layout mocks for canary promotion and unified review hooks exposed by the merged API surface.
- Patched Build runtime guards around restored builder sessions so config-less intermediate payloads render as drafts instead of crashing.
- Patched unified review queue to use its embedded prop in a build-safe way.
- Updated TaskManager unit tests to use isolated temp SQLite stores, preserving persistent task history in product code without leaking state between tests.
- Updated mutation-registry expectations and docstring from 13 to 14 first-party operators to preserve the merged workflow edit operator.
- Cleaned branch-plan trailing whitespace found by `git diff --check origin/master...HEAD`.
- Verification: `.tmp/merge-venv/bin/python -m pytest tests/test_workspace_state.py tests/test_api_server_startup.py tests/test_cli_commands.py` passed, 54 tests.
- Verification: `.tmp/merge-venv/bin/python -m pytest tests/test_truth_surface_wiring.py tests/test_event_log.py tests/test_event_unification.py` passed, 64 tests.
- Verification: `.tmp/merge-venv/bin/python -m pytest tests/test_p0_journey_fixes.py tests/test_unified_reviews.py` passed, 35 tests.
- Verification: `.tmp/merge-venv/bin/python -m pytest tests/test_workbench_multi_turn.py tests/test_workbench_eval_optimize_bridge.py` passed, 9 tests.
- Verification: `npm run test -- src/components/MockModeBanner.test.tsx src/components/workbench/ArtifactViewer.test.tsx src/lib/workbench-store.test.ts src/pages/AgentWorkbench.test.tsx src/pages/Deploy.test.tsx src/pages/Improvements.test.tsx src/pages/Optimize.test.tsx` passed, 7 files / 82 tests.
- Verification: `npm run test` passed, 53 files / 362 tests.
- Verification: `npm run build` passed, with the existing large bundle-size warning.
- Verification: `.tmp/merge-venv/bin/python -m pytest` passed, 3830 passed / 2 skipped.
