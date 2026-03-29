# P0 Fix Report

## Scope
This task started from `P0_FIXES_PROMPT.md`, which listed five P0/P1 showstopper issues plus a broader investigation checklist. I verified each item against the current checkout, fixed the issues that were still real, documented the stale items that were already resolved, and added regression coverage for the behavior changes.

## What Changed

### 1. DB schema collisions
- The prompt's specific `registry.db` collision between registry, skill, and runbook stores did not reproduce in the current checkout. Those stores already use compatible schemas and boot cleanly.
- The investigation did uncover a real SQLite collision between `api.audit.AuditStore` and `control.audit.AuditLog`. Both defaulted to `.autoagent/audit.db` and both created `audit_log` with incompatible columns, which made initialization order matter and could break startup paths.
- I fixed that by moving `api.audit.AuditStore` to its own default DB path, `.autoagent/api_audit.db`.
- Regression coverage was added in [tests/test_audit_defaults.py](/Users/andrew/Desktop/AutoAgent-VNextCC/tests/test_audit_defaults.py).

### 2. Trace engine wiring
- `TraceCollector` and `TracingMiddleware` existed, but the eval runner execution path was not instrumented, so traces were never persisted when the runner executed.
- I added `instrument_eval_runner()` in [agent/tracing.py](/Users/andrew/Desktop/AutoAgent-VNextCC/agent/tracing.py) and used it in both [runner.py](/Users/andrew/Desktop/AutoAgent-VNextCC/runner.py) and [api/server.py](/Users/andrew/Desktop/AutoAgent-VNextCC/api/server.py).
- I also aligned the default trace DB path to `.autoagent/traces.db` so CLI and API paths write to the same expected location.
- Regression coverage was added in [tests/test_runner.py](/Users/andrew/Desktop/AutoAgent-VNextCC/tests/test_runner.py).

### 3. Poisoned registry defaults
- The prompt's Google mutation default issue was already fixed in this checkout.
- `optimizer.mutations.create_default_registry()` already excludes the not-ready Google Vertex stubs, and the existing mutation tests already enforce that.
- No production code change was required here; I treated this as a verification item and documented it rather than churning code that was already correct.

### 4. Mock-first overrides
- The repo shipped with `use_mock: true` defaults in both config and runtime code, which made the system silently simulate optimization behavior unless a developer manually changed it.
- I changed the defaults to real mode in [autoagent.yaml](/Users/andrew/Desktop/AutoAgent-VNextCC/autoagent.yaml) and [agent/config/runtime.py](/Users/andrew/Desktop/AutoAgent-VNextCC/agent/config/runtime.py).
- I updated [optimizer/providers.py](/Users/andrew/Desktop/AutoAgent-VNextCC/optimizer/providers.py) so routing is credential-aware:
- If `use_mock: true` is explicitly requested, mock mode is used intentionally.
- If real mode is requested but no credentials are available for configured models, the router falls back to mock mode with a concrete reason.
- If some configured models are usable and others are missing credentials, only the usable real models are activated.
- I threaded that mock-state metadata through [optimizer/proposer.py](/Users/andrew/Desktop/AutoAgent-VNextCC/optimizer/proposer.py), [api/models.py](/Users/andrew/Desktop/AutoAgent-VNextCC/api/models.py), [api/routes/health.py](/Users/andrew/Desktop/AutoAgent-VNextCC/api/routes/health.py), [api/server.py](/Users/andrew/Desktop/AutoAgent-VNextCC/api/server.py), [runner.py](/Users/andrew/Desktop/AutoAgent-VNextCC/runner.py), and the frontend banner in [web/src/components/MockModeBanner.tsx](/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/components/MockModeBanner.tsx).
- Regression coverage was added in [tests/test_provider_runtime.py](/Users/andrew/Desktop/AutoAgent-VNextCC/tests/test_provider_runtime.py), [tests/test_runtime_config.py](/Users/andrew/Desktop/AutoAgent-VNextCC/tests/test_runtime_config.py), and [tests/test_api.py](/Users/andrew/Desktop/AutoAgent-VNextCC/tests/test_api.py).

### 5. UI ghost routes
- The prompt's missing-route issue was already fixed in this checkout.
- [web/src/App.tsx](/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/App.tsx) already defines `/sandbox`, `/knowledge`, `/what-if`, and `/reviews`, and the corresponding page files exist.
- While auditing route/API consistency, I found one adjacent integration mismatch: the frontend calls `/api/memory` while the backend only exposed `/api/memory/`, relying on redirect behavior.
- I fixed that by adding no-trailing-slash aliases in [api/routes/memory.py](/Users/andrew/Desktop/AutoAgent-VNextCC/api/routes/memory.py).

## Additional Problems Found
- The audit DB default-path collision described above was not in the prompt and was fixed.
- The trace DB default path was inconsistent between CLI and API flows and is now aligned.
- The health endpoint did not surface mock-mode metadata, so the frontend mock banner could never honestly tell users what mode they were in.
- The eval harness still uses `mock_agent_response` by default in this checkout. I did not replace the harness wholesale, but I made that state visible so the system is honest about simulated eval behavior.

## Verification
- Backend boot:
- `.venv/bin/python -c "from api.server import app; print('Server boots OK')"`
- Result: `Server boots OK`
- Frontend compile:
- `cd web && npx tsc --noEmit`
- Result: success, no TypeScript errors
- Focused regression tests:
- `.venv/bin/pytest tests/test_runtime_config.py tests/test_provider_runtime.py tests/test_runner.py tests/test_api.py tests/test_audit_defaults.py -q`
- Result: `31 passed in 1.45s`
- Full test suite:
- `.venv/bin/pytest tests/ -x -q --tb=short`
- Result: `2925 passed, 10 warnings`

## Files Changed
- [agent/config/runtime.py](/Users/andrew/Desktop/AutoAgent-VNextCC/agent/config/runtime.py)
- [agent/tracing.py](/Users/andrew/Desktop/AutoAgent-VNextCC/agent/tracing.py)
- [api/audit.py](/Users/andrew/Desktop/AutoAgent-VNextCC/api/audit.py)
- [api/models.py](/Users/andrew/Desktop/AutoAgent-VNextCC/api/models.py)
- [api/routes/health.py](/Users/andrew/Desktop/AutoAgent-VNextCC/api/routes/health.py)
- [api/routes/memory.py](/Users/andrew/Desktop/AutoAgent-VNextCC/api/routes/memory.py)
- [api/server.py](/Users/andrew/Desktop/AutoAgent-VNextCC/api/server.py)
- [autoagent.yaml](/Users/andrew/Desktop/AutoAgent-VNextCC/autoagent.yaml)
- [optimizer/proposer.py](/Users/andrew/Desktop/AutoAgent-VNextCC/optimizer/proposer.py)
- [optimizer/providers.py](/Users/andrew/Desktop/AutoAgent-VNextCC/optimizer/providers.py)
- [runner.py](/Users/andrew/Desktop/AutoAgent-VNextCC/runner.py)
- [tests/test_api.py](/Users/andrew/Desktop/AutoAgent-VNextCC/tests/test_api.py)
- [tests/test_audit_defaults.py](/Users/andrew/Desktop/AutoAgent-VNextCC/tests/test_audit_defaults.py)
- [tests/test_provider_runtime.py](/Users/andrew/Desktop/AutoAgent-VNextCC/tests/test_provider_runtime.py)
- [tests/test_runner.py](/Users/andrew/Desktop/AutoAgent-VNextCC/tests/test_runner.py)
- [tests/test_runtime_config.py](/Users/andrew/Desktop/AutoAgent-VNextCC/tests/test_runtime_config.py)
- [web/src/components/MockModeBanner.tsx](/Users/andrew/Desktop/AutoAgent-VNextCC/web/src/components/MockModeBanner.tsx)

## Notes
- I intentionally did not force a registry-store split because the prompt's named collision is stale in the current checkout and could not be reproduced.
- I also intentionally did not rework the entire eval harness beyond wiring traces and surfacing its simulated status, because that would have gone beyond the prompt and current regression evidence.
