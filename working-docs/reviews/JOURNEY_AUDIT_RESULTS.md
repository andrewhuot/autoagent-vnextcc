# Journey Audit Results

Audit date: 2026-03-29

| Journey | Status | Issues Found | Fixes Applied |
|---------|--------|-------------|---------------|
| Journey 1: First-Time Setup | PASS | `pip install -e ".[dev]"` failed because `setuptools` flat-layout package discovery was ambiguous in `pyproject.toml`. | Added explicit `tool.setuptools.packages.find` configuration in `pyproject.toml` and added `tests/test_packaging.py` to lock the editable-install contract. |
| Journey 2: Server Startup | PASS | No startup-blocking issues after validation. | Verified `/bin/bash -n start.sh`, clean `api.server` import, route imports, and frontend TypeScript build. |
| Journey 3: CLI Golden Path | PASS | No CLI import or help-command failures found. | Verified `runner.py --help`, `init --help`, `loop --help`, and a top-level command help sweep. |
| Journey 4: Web UI - All Pages Load | PASS | Several pages crashed or logged API/runtime errors on initial load: `/context`, `/changes`, `/registry`, `/blame`, `/scorer-studio`, `/reward-studio`, `/preference-inbox`, `/policy-candidates`, and later `/experiments` via optional-store 503s. Also documented five defined but unlinked nav routes: `/knowledge`, `/reviews`, `/sandbox`, `/settings`, `/what-if`. | Normalized mismatched frontend/backend payloads in shared hooks and page adapters, fixed `/changes` audit-summary routing, softened optional `/experiments` endpoints to safe empty responses, added Playwright regression coverage in `web/tests/broken-route-regressions.spec.ts`, and re-ran a full all-routes Playwright crawl with zero failures. |
| Journey 5: API - All Endpoints Respond | PASS | Slashless frontend calls for `/api/runbooks` and `/api/changes` 404ed or redirected, and `/api/changes/audit-summary` was shadowed by the dynamic `/{card_id}` route. Optional experiment endpoints returned 503s that polluted the web UI. | Added slashless aliases for list routes, moved `/api/changes/audit-summary` ahead of dynamic routes, updated experiment fallback endpoints to return empty/default payloads, and added/updated regression tests in `tests/test_api_route_aliases.py` and `tests/test_experiments_api.py`. |
| Journey 6: Database - No Schema Collisions | PASS | No store collision found in shared-schema checks. | Verified isolated in-memory initialization for `SkillStore` and `RegistryStore`, confirmed audit DB defaults differ, and smoke-tested coexistence of registry/runbook/skill tables in a shared temp DB. |
| Journey 7: Optimization Loop | PASS | No loop wiring break found. Environment lacked provider credentials, so the UI correctly warned and fell back to mock providers at runtime. | Verified `runner.py loop`, tracing integration, sane default config, and no default mutation registry `NotImplementedError` stubs. |
| Journey 8: Builder Workspace | PASS | No blocking issues found. | Verified `/builder` routing, builder page/component imports, backend builder endpoints, and `/api/builder/demo/status` live response. |
| Journey 9: Skills System | PASS | Registry page initially broke on response envelopes even though backend endpoints were mounted correctly. | Normalized registry payload handling in the frontend and verified skills, agent-skills, and registry routes/endpoints all respond cleanly. |
| Journey 10: Tests Pass | PASS | Full suite initially failed on route fallback state leakage in `policy_opt` and `what_if` lazy initialization. | Switched route-level fallback stores to app-isolated storage (`:memory:` for policy-opt registry, temp DB for what-if store), then re-ran the required full suite successfully. |

## Verification Summary

- `python3 -m pytest tests/ -x -q --tb=short 2>&1 | tail -30` -> `2959 passed, 10 warnings`
- `cd web && npx tsc --noEmit` -> passed
- `cd web && npx playwright test tests/broken-route-regressions.spec.ts --config=playwright.config.ts` -> `8 passed`
- `node output/playwright/route_audit.mjs` -> all audited routes passed in the final run (`output/playwright/route_audit.latest.json`)

## Notes

- The runtime banner about missing provider credentials is environment-driven, not a code regression. The app now clearly warns and falls back to mock mode instead of failing silently.
- The unlinked routes (`/knowledge`, `/reviews`, `/sandbox`, `/settings`, `/what-if`) are documented navigation gaps, but they are functional and load successfully.
