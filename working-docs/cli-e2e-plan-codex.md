# AgentLab CLI End-to-End Docs Verification Plan - Codex

Audit dates: 2026-04-12 to 2026-04-13
Branch: audit/cli-docs-end-to-end-codex
Repo: /Users/andrew/Desktop/agentlab-cli-e2e-codex
Base at launch: origin/master 265122c1a68f9f73198362a123c1d99d37990e0a

## Mission

Verify the CLI-facing documentation against the real `agentlab` CLI end to end. Prefer product fixes when the CLI is broken, documentation fixes when the product behavior is correct and the docs are stale, and leave a clear audit record of what was executed, inferred, fixed, or blocked.

## Source Contract

Required sources read and used as the audit contract:

- `README.md`
- `docs/cli-reference.md`
- `docs/QUICKSTART_GUIDE.md`
- `docs/DETAILED_GUIDE.md`
- `docs/app-guide.md` for CLI/UI crossover
- CLI entrypoint and command definitions in `runner.py`
- Packaging and console script metadata in `pyproject.toml`
- Existing CLI, packaging, connect/import, CX, quickstart, review/deploy, and result-command tests

## Execution Model

- Created a local editable install in `.venv` with `/opt/homebrew/bin/python3.12` because system `python3` is 3.9.6 and the project requires Python 3.11+.
- Used the installed console script `.venv/bin/agentlab` for live CLI verification, not only in-process `CliRunner` tests.
- Created isolated workspaces under `/tmp/agentlab-cli-e2e-codex.W3rTJI`.
- Kept real provider credentials out of the run. Provider checks used missing-key failures and one `OPENAI_API_KEY=sk-test` environment-presence check only.
- Used three read-only specialist passes for docs extraction, CLI implementation mapping, and existing test coverage inventory.
- Fixed behavior only after reproducing it through the CLI or an equivalent regression test.

## Status Checklist

- [x] Confirm branch, base commit, origin, and initial clean state.
- [x] Read required CLI-facing docs and CLI entrypoint/package metadata.
- [x] Extract documented command/workflow claims from the docs.
- [x] Generate live help and advanced command surfaces from installed CLI.
- [x] Exercise local end-to-end workspace creation and quickstart paths.
- [x] Exercise instruction, config, model, provider, mode, memory, permissions, MCP, build, eval, optimize, review, deploy, status, doctor, shell, server, connect, CX, ADK, and advanced command families where locally safe.
- [x] Reproduce stale docs and product breakages before fixing.
- [x] Add regression tests for product behavior changes.
- [x] Fix test isolation that rewrote a tracked synthetic dataset fixture during full-suite runs.
- [x] Update docs for stale install, eval results, and CX prerequisite claims.
- [x] Run targeted regression suites.
- [x] Run the full test suite.
- [x] Prepare scoped changes for commit, push, and the required completion signal.

The commit SHA, push result, and completion event happen after this document is finalized and are recorded in the final handoff summary.

## Coverage Matrix

| Area | Docs source | Verification performed | Status | Notes |
|---|---|---|---|---|
| Install, package, entrypoint | README, Quick Start, CLI Reference, pyproject | `.venv/bin/python -m pip install -e '.[dev]'`, `.venv/bin/agentlab --version`, `.venv/bin/agentlab --no-banner --help`, `.venv/bin/python -m runner --no-banner --help` | Verified and fixed | Editable install initially missed `adapters`/`portability`; package include list fixed. |
| Clone URL | README, Quick Start, Detailed Guide | `git ls-remote` against `andrewhuot/agentlab.git` and old `autoagent-vnextcc.git` | Docs fixed | Both currently resolve to the same HEAD, but docs now use canonical `agentlab`. |
| Workspace creation | README, Quick Start, Detailed Guide | `agentlab new my-agent --template customer-support --demo`; `quickstart --dir quickstart-agent2 --agent-name "Support Bot" --no-open` | Verified and fixed | Quickstart relative output paths were wrong inside a parent workspace; fixed. |
| Instructions | Quick Start, Detailed Guide, CLI Reference | `instruction show`, `instruction validate`, `instruction generate --brief ... --apply`, then `instruction validate` | Verified | Noninteractive flow works in mock workspace. |
| Config, model, provider, mode | Detailed Guide, CLI Reference | `config list`, `config show active`, `model list`, `model show`, `provider list`, `provider configure`, `provider test`, `mode show`, `mode set live`, `mode set auto` | Verified with credential limits | Live mode correctly failed without keys; auto mode fell back to mock. |
| Memory | CLI Reference, Detailed Guide | `memory where`, `memory list`, `memory show` | Verified | Kept inside isolated workspace. |
| Permissions | CLI Reference, Detailed Guide | `permissions show`, `permissions set acceptEdits` | Verified | Used for review/deploy flow context. |
| MCP config lifecycle | Detailed Guide, app guide | `mcp status`, `mcp list`, `mcp add`, `mcp inspect`, `mcp remove` | Verified | Fake tool config lifecycle only; no external MCP package execution for fake tool. |
| Build | README, Quick Start, Detailed Guide | `build "customer support agent for order tracking, refunds, and cancellations"`, `build show latest`, `status --json` | Verified | Produced config/artifact/eval state in mock workspace. |
| Eval basics and results | README, CLI Reference, Detailed Guide | `eval run`, `eval show latest`, `eval list`, `eval breakdown`, `eval run --category safety --output safety-results.json`, `eval results`, `eval results --run-id ... --failures`, `eval results export ...`, `eval results annotate ...`, `eval results diff ...`, `eval compare ...`, `eval generate ...`, `eval run --instruction-overrides ...` | Verified and docs fixed | Docs had stale `--content` and `--other-run` examples. |
| Optimize | README, CLI Reference, Detailed Guide | `optimize --cycles 1`, `optimize --cycles 1 --dry-run` | Verified | Healthy mock workspace produced expected no-op/safe result. |
| Review/deploy | README, Quick Start, Detailed Guide | `review list`, `review show pending`, `review export pending`, `deploy --auto-review --yes --dry-run`, `deploy --auto-review --yes`, `deploy status` | Verified and fixed | `review export pending` failed; dry-run deploy mutated review state; both fixed. |
| Status, doctor, shell | README, CLI Reference, Detailed Guide | `status`, `status --json`, `doctor --json`, `printf '/status\n/exit\n' | agentlab --no-banner shell` | Verified | Shell did not hang and exited cleanly. |
| Connect/import | CLI Reference, Detailed Guide, app guide | `connect transcript --file ./conversations.jsonl --name imported-agent`, `connect http --url https://agent.example.com --name http-agent` | Verified and fixed | Installed console script import and relative path handling were broken; fixed. |
| CX | Detailed Guide | `cx auth`, `cx list --project PROJECT --location us-central1` | Verified error paths and fixed | Missing `google-auth` now returns CLI-friendly errors; real CX auth/list/import/export blocked by environment. |
| ADK | Detailed Guide | `adk status tests/fixtures/sample_adk_agent`, `adk status /tmp/.../dryrun-agent` | Verified and fixed | Valid sample works; non-ADK path now reports a friendly parser error. |
| Server/API crossover | app guide | `server --host 127.0.0.1 --port 8125`; `curl /`, `/openapi.json`, `/api/setup/overview` | Verified with warning | Endpoints returned 200; duplicate FastAPI operation ID warning remains. |
| MCP server | app guide/advanced help | `mcp-server --help`, `mcp-server --host 127.0.0.1 --port 8126`, `curl /` | Partially verified | HTTP process starts and responds; protocol-level MCP client handshake not exercised. |
| Advanced commands | CLI Reference | `advanced`, `compare candidates`, `usage`, `session list`, `template list` | Verified | Sampled local-safe advanced/documented surfaces. |
| UI frontend | app guide | Read docs and verified backend server endpoints | Environment blocked | Did not run `./start.sh`, npm frontend build, or browser UI flow in this campaign. |
| Cloud deploy/live providers | README, Detailed Guide | Local missing-credential and dry-run/error paths only | Environment blocked | No real API keys, GCP project, Dialogflow CX agent, Docker/Fly/cloud deployment credentials used. |

## Fix Strategy Used

1. Reproduced the CLI/doc mismatch or product bug through the installed CLI where practical.
2. Added a narrow regression test covering the failure.
3. Applied the smallest product fix aligned with existing command patterns.
4. Updated docs only where product behavior was correct and documentation was stale.
5. Reran the original CLI command and targeted tests.
6. Reran the full test suite before commit preparation.

## Verification Commands

Targeted regression command:

```bash
.venv/bin/pytest tests/test_cli_commands.py tests/test_cli_permissions.py tests/test_connect_cli.py tests/test_quickstart.py tests/test_cx_studio.py tests/test_packaging.py
```

Result:

```text
147 passed, 2 warnings in 19.46s
```

Full suite command:

```bash
.venv/bin/pytest
```

Result:

```text
3976 passed, 11 warnings in 147.90s
```

## Open Items Documented As Blocked Or Residual

- Live provider calls were not made because no real provider API keys were used.
- Dialogflow CX remote list/import/export/sync flows were not exercised because `google-auth`, GCP credentials, project, and agent identifiers were not available in the local environment.
- Cloud deployment flows for Docker/Fly/GCP/Vertex were not exercised because deployment credentials and external services were out of scope.
- UI frontend browser flow was not exercised; backend server endpoints were verified.
- Standalone `mcp-server` was only smoke-tested for process startup and HTTP responsiveness.
- `agentlab server` emits a duplicate FastAPI operation ID warning for `/openapi.json`; endpoints still returned 200.
