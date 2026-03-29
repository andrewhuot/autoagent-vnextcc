# Distinguished Engineer + Technical PM Review

## Executive Summary

AutoAgent VNextCC is now in materially better shape than it was at the start of this review. The core architecture is directionally sound: the product has a coherent backend/API surface, a broad frontend, meaningful CLI coverage, and an unusually deep automated test suite. The main problems were not "missing product vision" problems. They were integration honesty, route-contract drift, packaging gaps, and a few real security flaws hiding behind preview-mode and demo flows.

The biggest change from this review is that the most embarrassing failures are no longer latent:

- The verified P0 arbitrary file write in Agent Skills apply is fixed.
- The verified P1 arbitrary file read / crash path in CX preview is fixed.
- The broken CLI install path is fixed, so `autoagent` now actually works after editable install.
- The first-run dashboard/demo journey, quick-fix honesty, assistant honesty, policy candidate workflow, and route shortcut flows now hold up under live browser verification.

### Top 3 strengths

1. Broad product surface with strong conceptual cohesion. The CLI, API, and web console all point at the same optimization platform story.
2. Strong automated safety net. After this pass the repo completes `2966` tests successfully, plus TypeScript and browser verification.
3. Good separation of concerns in many subsystems: route modules, stores/registries, policy backends, and builder/demo data are reasonably modular.

### Top 3 risks

1. Mock-mode boundaries are still a strategic risk. Several surfaces remain preview-first and require careful labeling to avoid trust erosion.
2. `runner.py` is still a large monolithic CLI entrypoint. It works, but it concentrates a lot of product-critical behavior in one file.
3. There are still production-path TODOs and broad exception handlers that are acceptable for preview/demo flows, but should be narrowed before a true production launch.

## Issues Found

| Severity | Category | Description | Status |
| --- | --- | --- | --- |
| P0 | Security | `POST /api/agent-skills/{skill_id}/apply` allowed generated files to escape the workspace root via absolute paths and traversal. | Fixed |
| P1 | Security | `GET /api/cx/preview` accepted arbitrary filesystem paths and could read outside the workspace; invalid snapshots could also bubble to 500s. | Fixed |
| P1 | Product trust | Dashboard quick-fix flow reported a successful fix even though the backend response was mock/simulated. | Fixed |
| P1 | Product trust | Assistant page and assistant actions were simulated but not clearly labeled as preview-only behavior. | Fixed |
| P1 | Shared layout | The mock-mode banner was mounted as a sibling in the root horizontal flex layout, collapsing the main content area on non-builder routes. This made real content exist in the DOM but fail visibility checks. | Fixed |
| P1 | CLI packaging | `autoagent` console script pointed at `runner:cli`, but `runner.py` was not packaged, causing `ModuleNotFoundError` after install. | Fixed |
| P1 | First-run journey | `start.sh` opened `/`, landing new users in the builder shell instead of the intended dashboard scorecard flow. | Fixed |
| P1 | Demo credibility | `setup.sh` seeded conversations only; traces and optimization history were missing, undermining the first-run demo. | Fixed |
| P1 | Runtime isolation | Quickstart/demo runtime artifacts were shared across directories, risking state collisions between runs. | Fixed |
| P1 | Operational safety | `start.sh` / `stop.sh` could interfere with unrelated local processes when handling occupied ports. | Fixed |
| P1 | Backend stability | What-if replay depended on missing app state and could crash on import/runtime paths. | Fixed |
| P1 | API honesty | Experiments archive and judge-calibration endpoints returned fabricated success payloads when backing stores were unavailable. | Fixed |
| P1 | File workflows | Assistant uploads had no retrieval route, breaking realistic file handoff behavior after upload. | Fixed |
| P1 | Frontend/backend contract | Command palette dashboard shortcut, conversations outcome filters, blame-map filters, and runbook shortcut query params had contract drift. | Fixed |
| P1 | Optimization contract | Optimize page advanced/research settings were not actually reaching the backend in a meaningful way. Mode and budgets now apply server-side. | Fixed |
| P1 | Policy optimization | Policy backend registration/persistence gaps prevented valid training, OPE persistence, and promotion gating from working correctly. | Fixed |
| P1 | Policy UX | Policy candidate dataset paths were rendered in a way that obscured/failed visibility in real browser checks. | Fixed |
| P2 | Logging | `api/server.py` still uses `print()` during boot/demo seeding rather than structured logging. | Documented |
| P2 | Error handling | There are still several broad `except Exception:` handlers in CLI and API code paths that should be narrowed over time. | Documented |
| P2 | Preview stubs | Assistant and knowledge flows still contain TODO-backed simulated actions/mutations; they are now honestly labeled, but not fully implemented. | Documented |
| P2 | Dependency hygiene | Quickstart/server paths emit `websockets` deprecation warnings through upstream stack usage. | Documented |

## Architecture Assessment

### Is the architecture sound?

Mostly yes, with caveats.

The system has a believable architecture for an internal platform or advanced demo product:

- FastAPI route modules are decomposed cleanly enough to reason about.
- The frontend is broad, but route/page ownership is legible.
- Registries and stores provide a reasonable persistence pattern.
- The policy optimization subsystem is capable of being extended rather than rewritten.

### What was weak

The architecture had three recurring failure modes:

1. Preview/live boundary drift
   Surfaces looked more real than they were. This is not just a copy problem; it is an architectural contract problem between backend payloads and frontend UX.

2. Packaging/integration blind spots
   The repo had strong unit coverage, but a real installed CLI still broke. That means install-time and journey-time verification were weaker than module-level verification.

3. Shared shell/layout coupling
   A single misplaced `MockModeBanner` in the root layout damaged visibility across multiple pages. That indicates the shell needs stronger structural invariants and browser-level regression coverage.

### Architectural conclusion

I would not call this architecture "fragile," but before this pass it was too easy for cross-cutting integration bugs to survive. After the fixes, the system is materially more coherent. The remaining risks are mostly around monolithic CLI surface area, preview-mode debt, and ongoing contract discipline.

## Verification Performed

The following checks were run during this review:

- `python3 -m compileall -q .`
- `cd web && npx tsc --noEmit`
- `source .venv/bin/activate && python3 -c "from api.server import app; print(len(app.routes))"`
- `source .venv/bin/activate && pytest -q`
- `./setup.sh`
- `./start.sh`
- Live Playwright route and workflow sweeps:
  - command palette/dashboard routing
  - conversations outcome query
  - runbooks shortcut apply flow
  - blame-map filter flow
  - quick-fix preview honesty
  - assistant preview honesty
  - preference inbox submission
  - policy candidate training + OPE flow
  - broken-route regression pages
- CLI smoke tests:
  - `autoagent --version`
  - `autoagent init --dir /tmp/autoagent-review-cli`
  - `autoagent loop --help`
  - `autoagent server --help`
  - live `autoagent server --host 127.0.0.1 --port 8011` boot + `/api/health` probe

### Verification result

- Python compile: pass
- TypeScript compile: pass
- Full pytest: `2966 passed, 10 warnings`
- Browser regression suite: `16 passed`
- CLI smoke tests: pass
- API app import: pass (`299` routes registered)

## Production Readiness Score

## 7/10

### Why not higher

- Too many important experiences still depend on mock mode or preview-mode behavior.
- There is still TODO debt in production-adjacent code paths.
- The CLI surface area is functional, but its implementation remains centralized and therefore higher-risk to evolve.

### Why not lower

- The system now survives the full clone -> setup -> start -> navigate -> optimize/policy/assistant -> CLI verification path without the previously verified P0/P1 failures.
- The repo has strong automated coverage and that coverage now includes the repaired journey gaps.
- The most serious security, packaging, and trust failures found in this review were fixed, not merely documented.

## Recommendations

### Priority 1

1. Continue reducing preview/live ambiguity.
   Every simulated action should expose explicit capability state from the backend, not inferred UI logic.

2. Split `runner.py`.
   Move CLI domains into dedicated modules so packaging, testing, and ownership are clearer.

3. Add journey-level install verification to setup/release checks.
   A small smoke test for `autoagent --version`, `autoagent init`, and `autoagent server --help` would have caught the packaging bug immediately.

### Priority 2

4. Replace broad `except Exception:` blocks in high-traffic routes with narrower error types and explicit fallback semantics.

5. Convert boot/demo `print()` calls to structured logging with severity and context.

6. Add a shared frontend contract test for "preview mode" payloads so simulated actions cannot silently present as real actions again.

### Priority 3

7. Reduce dependency on seeded/mock demo data by wiring a real non-demo eval harness path into the main product story.

8. Audit remaining TODO-backed preview surfaces and explicitly classify each one as:
   - launch blocker
   - preview-safe
   - internal-only

## Final Assessment

Before this review, I would have been uncomfortable showing the product to a skeptical VP without carefully curating the demo path. After this pass, the platform is much more defensible: the core flows boot, the browser routes render, the CLI works after install, the policy workflow completes, and the highest-risk trust/security problems are addressed.

It is not production-finished, but it is now substantially closer to "credible product" than "impressive but brittle demo."
