# AgentLab CLI End-to-End Docs Verification Findings - Codex

Audit dates: 2026-04-12 to 2026-04-13
Branch: audit/cli-docs-end-to-end-codex
Repo: /Users/andrew/Desktop/agentlab-cli-e2e-codex
Base at launch: origin/master 265122c1a68f9f73198362a123c1d99d37990e0a

## Audit Scope

This file records what was actually read, executed, inferred, fixed, and blocked while verifying AgentLab CLI documentation against the current CLI implementation.

This was not a docs-only audit. The run used the installed `.venv/bin/agentlab` console script, created real local workspaces, exercised documented command families, reproduced failures, changed product code where the CLI was wrong, changed docs where the examples were stale, and added regression coverage.

## Documents And Entrypoints Read

| Source | Status | Notes |
|---|---|---|
| `README.md` | Read and updated | Install, prerequisites, primary/secondary CLI overview, web console commands. |
| `docs/cli-reference.md` | Read and updated | Primary, secondary, advanced, power command, eval results examples, and deprecated alias claims. |
| `docs/QUICKSTART_GUIDE.md` | Read and updated | First-run workspace, instruction, build, eval, optimize, review/deploy flow. |
| `docs/DETAILED_GUIDE.md` | Read and updated | Extended CLI walkthrough, providers/mode, MCP, connect, CX, daily flow. |
| `docs/app-guide.md` | Read | CLI/server to web UI crossover, `agentlab server`, `./start.sh`, routes. |
| `runner.py` | Read and updated | Click command definitions and command behavior. The implementation is Click, not Typer. |
| `pyproject.toml` | Read and updated | `agentlab = runner:cli` console script and explicit package discovery. |
| Existing tests | Read and updated | Existing coverage is mostly in-process `CliRunner`; this audit added regressions for observed CLI failures and fixed a quickstart test isolation leak. |

## Environment

| Item | Value |
|---|---|
| Python used | `/opt/homebrew/bin/python3.12` in `.venv` |
| System `python3` | 3.9.6, below project requirement |
| Editable install | `.venv/bin/python -m pip install -e '.[dev]'` |
| Temp workspace root | `/tmp/agentlab-cli-e2e-codex.W3rTJI` |
| Main test workspaces | `my-agent`, `dryrun-agent`, `imported-agent`, `http-agent`, `quickstart-agent2` |
| Provider credentials | No real provider keys used |
| Live external services | Not used except `git ls-remote` URL checks |

## Specialist Passes

| Specialist | Result |
|---|---|
| Docs extraction | Extracted documented workflows from README, CLI reference, quickstart, detailed guide, and app guide. |
| CLI implementation map | Identified Click command tree, hidden/advanced commands, eval result syntax, review export selector bug, and packaging gaps. |
| Test coverage inventory | Found broad command coverage through `CliRunner`; identified need for regression coverage around installed script packaging, path resolution, dry-run state mutation, and friendly error handling. |

## Commands Actually Run

This table is grouped by workflow. It distinguishes executed commands from inferred behavior. All listed commands were executed unless marked as blocked or inferred.

| Area | Command or action | Exit | Evidence or outcome |
|---|---|---:|---|
| Git/base | `git status --short --branch`, `git remote -v`, `git rev-parse HEAD`, `git rev-parse origin/master` | 0 | Branch was `audit/cli-docs-end-to-end-codex`; base and HEAD started at `265122c1a68f9f73198362a123c1d99d37990e0a`. |
| Clone URLs | `git ls-remote https://github.com/andrewhuot/agentlab.git HEAD` | 0 | Resolved to `265122c1a68f9f73198362a123c1d99d37990e0a`. |
| Clone URLs | `git ls-remote https://github.com/andrewhuot/autoagent-vnextcc.git HEAD` | 0 | Also resolved to `265122c1a68f9f73198362a123c1d99d37990e0a`; docs still updated to canonical `agentlab`. |
| Install | `.venv/bin/python -m pip install -e '.[dev]'` | 0 | Editable install completed after using Python 3.12. |
| Help/version | `.venv/bin/agentlab --no-banner --help` | 0 | Top-level primary/secondary command surface rendered. |
| Help/version | `.venv/bin/agentlab --version` | 0 | Reported `agentlab, version 1.0.0`. |
| Help/version | `.venv/bin/agentlab --no-banner advanced` | 0 | Hidden/advanced commands rendered. |
| Entrypoint | `.venv/bin/python -m runner --no-banner --help` | 0 | Module entrypoint rendered CLI help. |
| Workspace | `agentlab --no-banner new my-agent --template customer-support --demo` | 0 | Created seeded mock workspace. |
| Status/doctor | `status`, `status --json`, `doctor --json` | 0 | Local workspace status and doctor payloads worked. |
| Mode | `mode show`, `mode set live`, `mode set auto` | mixed expected | Live mode failed without keys; auto mode saved preference and fell back to mock. |
| Instructions | `instruction show`, `instruction validate`, `instruction generate --brief "customer support agent for order tracking and refunds" --apply` | 0 | Instruction lifecycle worked and validation passed after generation. |
| Config | `config list`, `config show active` | 0 | Active config surfaced correctly. |
| Models/providers | `model list`, `model show`, `provider list`, `provider configure --provider openai --model gpt-4o --api-key-env OPENAI_API_KEY`, `provider test` | mixed expected | Missing provider/key failures were clear; `OPENAI_API_KEY=sk-test provider test` passed environment-presence check only. |
| Memory | `memory where`, `memory list`, `memory show` | 0 | Workspace-local memory surfaces worked. |
| Permissions | `permissions show`, `permissions set acceptEdits` | 0 | Permission mode surfaced and changed. |
| MCP config | `mcp status`, `mcp list`, `mcp add my-tool --command npx --arg -y --arg @my/tool-server`, `mcp inspect my-tool`, `mcp remove my-tool` | 0 | MCP config lifecycle worked for a fake tool definition. |
| Build | `build "customer support agent for order tracking, refunds, and cancellations"` | 0 | Created versioned config/artifacts/evals in mock mode. |
| Build | `build show latest`, `status --json` | 0 | Latest build and workspace status reflected new candidate state. |
| Eval | `eval run` | 0 | Mock eval passed 5/5. |
| Eval | `eval show latest`, `eval list`, `eval breakdown` | 0 | Eval summaries rendered. |
| Eval | `eval run --category safety --output safety-results.json` | 0 | Safety-filtered eval wrote an output file. |
| Eval results | `eval results`, `eval results --run-id 034197fc-5c5 --failures`, `eval results export 034197fc-5c5 --format markdown` | 0 | Result browsing, failure filter, and export worked. |
| Eval results stale docs | `eval results annotate 034197fc-5c5 cs_safe_001 --type note --content "Needs human review"` | 2 | Reproduced stale docs: `--content` is invalid; command expects `--comment` with `--run-id`. |
| Eval results fixed docs syntax | `eval results annotate cs_safe_001 --run-id 034197fc-5c5 --type note --comment "Needs human review"` | 0 | Correct syntax worked. |
| Eval results stale docs | `eval results diff 034197fc-5c5 --other-run eval-122` | 2 | Reproduced stale docs: `--other-run` is invalid; command expects two positional run IDs. |
| Eval results fixed docs syntax | `eval results diff 06748729-851 034197fc-5c5` | 0 | Correct positional diff worked. |
| Eval compare | `eval compare --left-run .agentlab/eval_results_latest.json --right-run safety-results.json` | 0 | Comparison of two result files worked. |
| Eval generation | `eval generate --config configs/v001.yaml --output generated_eval_suite.json` | 0 | Generated 31 cases in workspace. |
| Eval overrides | `eval run --instruction-overrides instruction_override.yaml --output override-results.json` | 0 | Override path worked in workspace. |
| Optimize | `optimize --cycles 1`, `optimize --cycles 1 --dry-run` | 0 | Mock optimization completed with safe no-op/healthy behavior. |
| Review | `review list`, `review show pending` | 0 | Seeded demo review card was visible. |
| Review bug | `review export pending` | 1 before fix, 0 after fix | Reproduced selector mismatch and fixed export selector resolution. |
| Deploy bug | `deploy --auto-review --yes --dry-run` | 0 before/after | Reproduced state mutation before fix; after fix dry run did not approve pending cards. |
| Deploy | `deploy --auto-review --yes`, `deploy status`, `review list`, `status` | 0 | Real local deploy flow created release/canary state and approved pending card only without dry-run. |
| Shell | `printf '/status\n/exit\n' | agentlab --no-banner shell` | 0 | Interactive shell accepted scripted commands and exited cleanly. |
| Connect packaging bug | `connect transcript --file ./conversations.jsonl --name imported-agent` from installed script | failed before fix, 0 after fix | Initially failed with `ModuleNotFoundError: No module named 'adapters'`; package include fixed. |
| Connect path bug | Same transcript command inside child of parent workspace | failed before fix, 0 after fix | Initially resolved `./conversations.jsonl` relative to parent workspace; fixed invocation-cwd path resolution. |
| Connect HTTP | `connect http --url https://agent.example.com --name http-agent` | 0 | Local wrapper workspace created without network call. |
| Quickstart bug | `quickstart --dir quickstart-agent --agent-name "Support Bot" --no-open` under parent workspace | wrong output before fix | Created target under `/private/tmp` parent workspace instead of invocation cwd before fix. |
| Quickstart retest | `quickstart --dir quickstart-agent2 --agent-name "Support Bot" --no-open` | 0 | Created workspace under invocation cwd after fix. |
| CX bug | `cx auth` | failed before/after | Before fix stacktraced on missing `google-auth`; after fix returned `Error: CX authentication failed: ...`. |
| CX bug | `cx list --project PROJECT --location us-central1` | failed before/after | After fix returned `Error: CX agent listing failed: ...`; real remote list blocked by missing auth/env. |
| ADK valid | `adk status tests/fixtures/sample_adk_agent` | 0 | Parsed sample ADK agent, tools, and sub-agent. |
| ADK invalid bug | `adk status /tmp/.../dryrun-agent` | failed before/after | Before fix raised parser traceback; after fix returned friendly `Error: ADK status failed: agent.py not found...`. |
| Server | `server --host 127.0.0.1 --port 8125` plus `curl /`, `/openapi.json`, `/api/setup/overview` | 0 | Backend routes returned 200; OpenAPI emitted duplicate operation ID warning. |
| MCP server | `mcp-server --help`; `mcp-server --host 127.0.0.1 --port 8126`; `curl /` | 0/404 expected | Process started; root returned HTTP 404, proving server responsiveness. |
| Advanced/local-safe | `compare candidates`, `usage`, `session list`, `template list` | 0 | Sampled advanced/documented surfaces. |
| Test isolation bug | Full `pytest` run dirtied `evals/synthetic_dataset.json` | 0 test exit, dirty worktree | `tests/test_auto_open.py` ran quickstart flows in repo root; tests now use `runner.isolated_filesystem()`. |
| UI frontend | `./start.sh` / browser UI | blocked | Not run; backend server endpoints were the local CLI/UI crossover verification. |
| Cloud/live | Real provider calls, Dialogflow CX calls, Docker/Fly/GCP deploy | blocked | No credentials/projects/agents available; only local dry-run/error paths verified. |

## Findings

| ID | Severity | Type | Status | Evidence | Resolution |
|---|---|---|---|---|---|
| F-001 | P2 | Docs stale | Fixed | README and guides used old `autoagent-vnextcc` clone URL while `origin` is `andrewhuot/agentlab.git`; `git ls-remote` showed both URLs currently resolve to the same HEAD. | Updated install docs to canonical `https://github.com/andrewhuot/agentlab.git` and retained a note that old URLs currently resolve. |
| F-002 | P2 | Docs stale | Fixed | Documented `agentlab eval results diff eval-123 --other-run eval-122` failed with `No such option: --other-run`. | Updated example to two positional run IDs: `agentlab eval results diff eval-122 eval-123`. |
| F-003 | P2 | Docs stale | Fixed | Documented `agentlab eval results annotate eval-123 example_001 --type note --content ...` failed with `No such option: --content`. | Updated example to `agentlab eval results annotate example_001 --run-id eval-123 --type note --comment ...`. |
| F-004 | P1 | Product bug | Fixed | `agentlab review export pending` failed with `Change card not found: pending`, while sibling review commands support selectors. | Added selector resolution for `review export pending/latest` and regression coverage. |
| F-005 | P1 | Product bug | Fixed | `agentlab deploy --auto-review --yes --dry-run` approved pending review cards even though it was a dry run. | Moved auto-approval behind `not dry_run`; added regression coverage proving pending cards remain pending. |
| F-006 | P1 | Packaging bug | Fixed | Installed console script `agentlab connect transcript ...` failed with `ModuleNotFoundError: No module named 'adapters'`. | Added `adapters`, `adapters.*`, `portability`, and `portability.*` to explicit setuptools package discovery and packaging test coverage. |
| F-007 | P1 | Product bug | Fixed | `connect transcript --file ./conversations.jsonl` inside a child directory of a parent workspace resolved relative to the auto-detected parent workspace instead of the invocation cwd. | Resolved connect source/output paths against original invocation cwd; added transcript regression. The same path pattern was applied to OpenAI Agents, Anthropic, and HTTP connect output paths. |
| F-008 | P1 | Product bug | Fixed | `quickstart --dir quickstart-agent ...` inside a child directory of a parent workspace created the output under the parent workspace instead of the invocation cwd. | Resolved quickstart/demo quickstart target dirs against original invocation cwd; added regression coverage. |
| F-009 | P2 | Product/docs prerequisite | Fixed | `cx auth` and `cx list` stacktraced when `google-auth` was missing. | Wrapped CX auth/list errors as Click exceptions and documented optional `google-auth` prerequisite. |
| F-010 | P2 | Product bug | Fixed | `adk status` on a non-ADK workspace raised an `AdkParseError` traceback. | Wrapped parser errors as `ClickException`; added CLI regression and retested valid/invalid paths. |
| F-011 | P3 | Runtime warning | Open | `agentlab server` served `/openapi.json` with HTTP 200 but emitted a FastAPI duplicate Operation ID warning for `list_pending_reviews_api_reviews_pending_get`. | Documented as residual warning; not blocking CLI docs verification. |
| F-012 | P2 | Test isolation bug | Fixed | Full-suite verification rewrote tracked `evals/synthetic_dataset.json` because quickstart auto-open tests ran default output paths in the repo root. | Wrapped the quickstart auto-open run tests in `runner.isolated_filesystem()` and restored the fixture. |

## Files Changed

| File | Purpose |
|---|---|
| `runner.py` | Fixed connect path resolution, dry-run deploy mutation, review export selectors, quickstart target path resolution, CX error surfacing, and ADK status error surfacing. |
| `pyproject.toml` | Added missing install packages for connect/import and portability code. |
| `README.md` | Updated canonical clone URL and CX prerequisite note. |
| `docs/QUICKSTART_GUIDE.md` | Updated canonical clone URL. |
| `docs/DETAILED_GUIDE.md` | Updated canonical clone URL and CX `google-auth` prerequisite/install step. |
| `docs/cli-reference.md` | Corrected stale `eval results diff` and `eval results annotate` examples. |
| `tests/test_cli_commands.py` | Added ADK status friendly-error regression. |
| `tests/test_cli_permissions.py` | Added deploy dry-run and review export selector regressions. |
| `tests/test_connect_cli.py` | Added transcript path-resolution regression. |
| `tests/test_quickstart.py` | Added quickstart invocation-cwd regression. |
| `tests/test_cx_studio.py` | Added CX auth friendly-error regression. |
| `tests/test_auto_open.py` | Isolated quickstart no-open tests so full-suite runs do not mutate tracked workspace fixtures. |
| `tests/test_packaging.py` | Added package discovery assertions for `adapters` and `portability`. |
| `working-docs/cli-e2e-plan-codex.md` | Planning and coverage record. |
| `working-docs/cli-e2e-findings-codex.md` | Findings, evidence, fixes, blocked flows, and verification record. |

## Regression Tests Added Or Updated

| Test | Behavior locked |
|---|---|
| `test_deploy_auto_review_dry_run_keeps_review_cards_pending` | Dry-run deploy with auto-review does not approve pending review cards. |
| `test_review_export_pending_resolves_selector` | `review export pending` resolves newest pending card. |
| `test_connect_transcript_resolves_relative_paths_from_invocation_cwd` | Transcript import relative file and output paths use invocation cwd even under parent workspace detection. |
| `test_quickstart_relative_dir_uses_invocation_cwd_inside_parent_workspace` | Quickstart relative target path uses invocation cwd. |
| `test_cx_auth_reports_auth_errors_without_traceback` | CX auth dependency/auth failures are CLI-friendly. |
| `test_adk_status_reports_parse_errors_without_traceback` | ADK status parser failures are CLI-friendly. |
| `test_quickstart_no_open_runs` and `test_demo_quickstart_no_open_runs` | Quickstart auto-open smoke tests run in isolated filesystems. |
| `test_pyproject_declares_explicit_package_discovery_for_editable_installs` | Editable installs include `adapters` and `portability`. |

## Verification Results

| Command | Result |
|---|---|
| `.venv/bin/pytest tests/test_packaging.py tests/test_connect_cli.py tests/test_cli_permissions.py tests/test_quickstart.py tests/test_cx_studio.py` | `100 passed, 2 warnings in 18.51s` before ADK fix. |
| `.venv/bin/pytest tests/test_cli_commands.py tests/test_workspace_cli.py tests/test_cli_ux_refactor_v2.py tests/test_results_cli.py tests/test_golden_path_fresh_install.py tests/test_cli_model.py tests/test_cli_integrations.py tests/test_mcp_runtime.py tests/test_mcp_server.py tests/test_transcript_cli.py tests/test_e2e_value_chain_cli.py tests/test_cli_usage.py tests/test_cli_taxonomy.py` | `181 passed in 4.70s`. |
| `.venv/bin/pytest` | `3976 passed, 11 warnings in 147.90s` after all fixes, including test isolation. |
| `.venv/bin/pytest tests/test_cli_commands.py tests/test_cli_permissions.py tests/test_connect_cli.py tests/test_quickstart.py tests/test_cx_studio.py tests/test_packaging.py` | `147 passed, 2 warnings in 19.46s` after ADK fix. |
| `.venv/bin/pytest tests/test_auto_open.py` | `6 passed in 0.39s` after isolating quickstart no-open tests. |
| `.venv/bin/agentlab --no-banner adk status /tmp/agentlab-cli-e2e-codex.W3rTJI/dryrun-agent` | Exit 1 with friendly `Error: ADK status failed: agent.py not found...`. |
| `.venv/bin/agentlab --no-banner adk status tests/fixtures/sample_adk_agent` | Exit 0, parsed `support_agent` with 3 tools and 1 sub-agent. |
| `git diff -- evals/synthetic_dataset.json --stat --exit-code` | Exit 0 after the final full suite, confirming the tracked fixture stayed clean. |

## Blocked Or Not Fully Exercised

| Area | Reason | Local verification still performed |
|---|---|---|
| Real provider calls | No real OpenAI/Anthropic/Google API keys were used. | Provider configuration, missing-key failure, auto fallback, and environment-presence test with `sk-test`. |
| Dialogflow CX remote workflows | Missing `google-auth`, GCP credentials, project ID, location, and agent IDs. | CX auth/list dependency failure paths now friendly; docs list prerequisite. |
| Cloud deployment | No Docker/Fly/GCP/Vertex credentials or external services used. | Local `deploy --dry-run`, `deploy --auto-review --yes`, and `deploy status` verified. |
| Browser UI frontend | `./start.sh`, npm frontend build, and browser route sweep were not run. | Backend `agentlab server` started and `/`, `/openapi.json`, `/api/setup/overview` returned 200. |
| MCP protocol handshake | No real MCP client handshake was performed against `mcp-server`. | `mcp-server` help and HTTP startup were smoke-tested; workspace MCP config lifecycle was verified. |
| OpenAI Agents / Anthropic source imports | No local fixture projects for these import formats were used. | Shared path-resolution fix was applied; transcript import and HTTP import were live-tested. |

## Final Assessment

The core local CLI workflows documented for first-run usage are now verified: install/help, workspace creation, instruction/config/mode/provider basics, memory, MCP config, build, eval, results browsing, optimize, review, deploy, status, doctor, shell, connect transcript/HTTP, ADK status, CX error paths, server startup, and selected advanced commands.

The highest-risk product issues found were not documentation nits: installed connect commands were missing packages, dry-run deploy mutated review state, and relative paths were misresolved after workspace auto-discovery. Those are fixed with regression tests.

The remaining gaps are external-service or environment-dependent, except for the nonblocking FastAPI duplicate operation ID warning observed during server OpenAPI generation.
