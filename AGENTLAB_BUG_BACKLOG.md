# AgentLab Bug Backlog for Agentic Coding Tools

This backlog is derived from the architectural audit in
[AGENTLAB_VALUE_CHAIN_AUDIT.md](/Users/andrew/Desktop/agentlab/AGENTLAB_VALUE_CHAIN_AUDIT.md).

The goal here is not to restate every finding. The goal is to give an agentic
coding tool a set of self-contained, implementation-ready bug tickets that can
be worked in sequence or, where noted, in parallel.

## How To Use This Backlog

- Treat each ticket as one logical change.
- Prefer small, local fixes over refactors.
- Preserve existing CLI surface area unless the ticket explicitly calls for a
  breaking behavior change.
- Every ticket should land with tests.
- Where a ticket mentions an audit citation, use it as the ground truth for the
  bug being fixed.

## Suggested Priority Order

Phase 1:

1. B001 - Fix packaged CLI import failure
2. B002 - Version build outputs in fresh directories
3. B006 - Fix deploy degraded-eval gate parsing
4. B004 - Make `improve run --auto` use the real improve loop
5. B005 - Bind `improve accept` to the selected attempt's candidate version
6. B003 - Make deploy failures return nonzero consistently

Phase 2:

7. B007 - Trigger optimization on low-scoring all-pass evals
8. B008 - Eliminate latest-eval lookup races
9. B009 - Eliminate latest-attempt reporting races
10. B011 - Fix version-manager active/canary divergence

Phase 3:

11. B010 - Prevent failure-cluster variant contamination
12. B012 - Surface state-store corruption instead of silently resetting
13. B013 - Tighten failure-analysis payload validation
14. B014 - Close acceptance-test gaps around the advertised value chain

## Ticket Template Conventions

Each ticket includes:

- `Why this matters`
- `Observed behavior`
- `Root cause`
- `Scope`
- `Likely files`
- `Implementation notes`
- `Acceptance criteria`
- `Regression tests to add`
- `Agent prompt stub`

## B001 - Packaged CLI crashes from a clean cwd

- Priority: P0
- Effort: hours
- Parallel-safe: yes
- Audit citations:
  - [pyproject.toml](/Users/andrew/Desktop/agentlab/pyproject.toml):31
  - [pyproject.toml](/Users/andrew/Desktop/agentlab/pyproject.toml):80
  - `/tmp/agentlab_help.txt:1`

### Why this matters

Nothing else in the value chain matters if the installed `agentlab` command
cannot import successfully outside the repo root.

### Observed behavior

From a clean working directory, `agentlab --help` crashes with
`ModuleNotFoundError: No module named 'agent_card'`.

### Root cause

`pyproject.toml` defines the console script entrypoint as `runner:cli`, but the
setuptools package include list omits the `agent_card` package, even though the
CLI imports `agent_card.schema` during command registration.

### Scope

Packaging only. Avoid functional CLI changes.

### Likely files

- [pyproject.toml](/Users/andrew/Desktop/agentlab/pyproject.toml)
- Possibly packaging-related tests under [tests](/Users/andrew/Desktop/agentlab/tests)

### Implementation notes

- Add `agent_card` and `agent_card.*` to the setuptools package discovery list.
- Add a smoke test that installs or simulates the installed console-script import
  path from outside the repo root.

### Acceptance criteria

- Running `agentlab --help` from a temp directory succeeds without needing
  `PYTHONPATH`.
- Running `agentlab build --help`, `agentlab eval --help`, and
  `agentlab optimize --help` from a temp directory also succeeds.

### Regression tests to add

- Packaging/import smoke test for the console script from a temp cwd.
- Optional parametrized smoke test over a few top-level commands.

### Agent prompt stub

Fix the installed CLI import failure by updating packaging so `agent_card` is
included in the built distribution. Add a regression test that runs the
console-script entrypoint from a temp directory without `PYTHONPATH`. Keep the
change narrowly scoped to packaging and smoke coverage.

## B002 - `build` does not create deployable version state in a fresh directory

- Priority: P0
- Effort: days
- Parallel-safe: mostly yes, but coordinate with B003 and B011
- Audit citations:
  - [cli/commands/build.py](/Users/andrew/Desktop/agentlab/cli/commands/build.py):171
  - [cli/commands/build.py](/Users/andrew/Desktop/agentlab/cli/commands/build.py):185
  - [cli/commands/deploy.py](/Users/andrew/Desktop/agentlab/cli/commands/deploy.py):708
  - [cli/commands/deploy.py](/Users/andrew/Desktop/agentlab/cli/commands/deploy.py):713
  - `/tmp/agentlab-audit.4Vd5RB/deploy.stdout:1`

### Why this matters

The advertised loop says users can build, eval, optimize, improve, then deploy.
In a fresh directory, `build` only writes a YAML file, so `deploy` has no
manifest history to act on.

### Observed behavior

In a scratch directory:

1. `agentlab build ...` succeeds.
2. `agentlab deploy --auto-review --yes` prints
   `No config versions available. Run: agentlab optimize`.
3. Text mode returns success instead of a failing exit code.

### Root cause

`build` only persists through `ConfigVersionManager.save_version()` when it is
running inside an already discovered workspace root. In a fresh non-workspace
directory it writes `configs/v001_built_from_prompt.yaml` directly and never
creates `configs/manifest.json`.

### Scope

Build/deploy handoff behavior for fresh directories.

### Likely files

- [cli/commands/build.py](/Users/andrew/Desktop/agentlab/cli/commands/build.py)
- [deployer/versioning.py](/Users/andrew/Desktop/agentlab/deployer/versioning.py)
- Possibly [cli/workspace.py](/Users/andrew/Desktop/agentlab/cli/workspace.py)
- Acceptance tests in [tests/test_e2e_value_chain_cli.py](/Users/andrew/Desktop/agentlab/tests/test_e2e_value_chain_cli.py)

### Implementation notes

- Best fix shape: when `build` creates `.agentlab`, `configs/`, and `evals/`,
  treat that directory as a workspace-like target and register the seed config
  through `ConfigVersionManager`.
- Ensure a manifest exists after the first build in a fresh dir.
- Be careful not to break the existing workspace-root path.

### Acceptance criteria

- After the first successful `agentlab build ...` in a fresh temp dir,
  `configs/manifest.json` exists.
- The new manifest contains a deployable initial version.
- `agentlab deploy --auto-review --yes` no longer fails due to missing version
  history in that scenario.

### Regression tests to add

- Exact scratch-dir `build -> deploy` test.
- Assert manifest creation after first build.
- Assert that legacy workspace-root behavior still works.

### Agent prompt stub

Fix the build-to-deploy seam in fresh directories. After `agentlab build ...`
in an empty temp dir, there should be version state in `configs/manifest.json`
so downstream deploy commands can resolve a version. Add an e2e regression test
covering first build followed by deploy.

## B003 - Deploy failure modes are inconsistent across text/json/stream-json

- Priority: P0
- Effort: hours to days
- Parallel-safe: yes, but coordinate with B002 and B006
- Audit citations:
  - [cli/commands/deploy.py](/Users/andrew/Desktop/agentlab/cli/commands/deploy.py):224
  - [cli/commands/deploy.py](/Users/andrew/Desktop/agentlab/cli/commands/deploy.py):243
  - [cli/commands/deploy.py](/Users/andrew/Desktop/agentlab/cli/commands/deploy.py):708
  - [cli/commands/deploy.py](/Users/andrew/Desktop/agentlab/cli/commands/deploy.py):713
  - `/tmp/agentlab-deploystream.t3SCu9/out.stdout:1`
  - `/tmp/agentlab-audit.4Vd5RB/deploy.stdout:1`

### Why this matters

An automation or coding tool cannot trust deploy outcomes if a command can emit
`status="failed"` yet still exit `0`.

### Observed behavior

- `run_deploy_in_process()` emits a failed terminal envelope when there are no
  config versions.
- The text-mode CLI path prints an error-like message and returns success.
- Stream-json mode also exits `0` in the no-history case.

### Root cause

The in-process path and the legacy text/json path are not using the same failure
contract. Some failure conditions return payloads, others raise, and the wrapper
does not normalize them consistently.

### Scope

Deploy command failure/exit-code contract only.

### Likely files

- [cli/commands/deploy.py](/Users/andrew/Desktop/agentlab/cli/commands/deploy.py)
- Possibly any helper shared with slash commands

### Implementation notes

- Pick one contract and apply it everywhere:
  - failing terminal status should map to nonzero exit code in CLI mode;
  - benign status reads should remain exit `0`.
- Preserve existing `13` behavior for degraded deployment blocks.

### Acceptance criteria

- Missing-history deploy exits nonzero in text, JSON, and stream-json modes.
- Blocked degraded deploy still exits `13`.
- Successful deploys still exit `0`.

### Regression tests to add

- Parametrized tests over `text`, `json`, and `stream-json` for no-history
  deploy.
- Separate test for degraded deploy block and exit `13`.

### Agent prompt stub

Normalize deploy failure behavior across text, JSON, and stream-json. A failed
deploy should not exit `0`. Preserve the special degraded gate exit code `13`.
Add focused CLI tests for missing-history and degraded-deploy scenarios.

## B004 - `improve run --auto` takes the legacy autofix path instead of the real improve loop

- Priority: P0
- Effort: days
- Parallel-safe: no, coordinate with B005
- Audit citations:
  - [cli/commands/improve.py](/Users/andrew/Desktop/agentlab/cli/commands/improve.py):1140
  - [cli/commands/improve.py](/Users/andrew/Desktop/agentlab/cli/commands/improve.py):1175
  - [cli/commands/improve.py](/Users/andrew/Desktop/agentlab/cli/commands/improve.py):106
  - [cli/commands/improve.py](/Users/andrew/Desktop/agentlab/cli/commands/improve.py):111
  - [evals/runner.py](/Users/andrew/Desktop/agentlab/evals/runner.py):112
  - [evals/runner.py](/Users/andrew/Desktop/agentlab/evals/runner.py):113
  - `/tmp/agentlab-audit.4Vd5RB/improve_run.stdout:1`
  - `/tmp/agentlab-audit.4Vd5RB/improve_run.stderr:1`

### Why this matters

This is the biggest user-trust bug in the loop surface. The command name says
"improve", but the implementation silently routes into a different subsystem.

### Observed behavior

Running `agentlab improve run --auto` after optimize:

- prints a deprecation warning,
- runs legacy autofix,
- evaluates the package-default suite,
- produces no deployable optimize attempt linkage.

### Root cause

The Click wrapper special-cases `config_path is None` and calls
`_invoke_legacy_autofix()` instead of `run_improve_run_in_process()`.

### Scope

The zero-arg `improve run` UX and command semantics.

### Likely files

- [cli/commands/improve.py](/Users/andrew/Desktop/agentlab/cli/commands/improve.py)
- Possibly related tests under [tests](/Users/andrew/Desktop/agentlab/tests)

### Implementation notes

Choose one of these and implement it explicitly:

1. Preferred: zero-arg `improve run` resolves the workspace active config and
   runs the real eval -> optimize -> present flow.
2. Acceptable: zero-arg `improve run` becomes a hard error with a clear message
   telling the user to pass a config path or use a new explicit legacy command.

Do not keep silent semantic drift.

### Acceptance criteria

- `agentlab improve run --auto` in a workspace no longer enters legacy autofix.
- The command consumes the workspace active config or fails clearly and nonzero.
- The resulting eval/optimize lineage belongs to the same workspace suite, not
  the package-default suite.

### Regression tests to add

- Exact `optimize -> improve run --auto` test in a workspace.
- Assert no legacy autofix notice appears in the normal improve path.
- Assert the produced eval references the workspace config and suite.

### Agent prompt stub

Fix `agentlab improve run --auto` so it no longer routes to legacy autofix when
run inside a workspace. It should execute the real improve workflow against the
active config, or fail clearly if no config can be resolved. Add e2e coverage
for the exact CLI sequence.

## B005 - `improve accept <attempt-id>` does not guarantee deployment of that attempt's candidate

- Priority: P0
- Effort: days
- Parallel-safe: no, coordinate with B004 and B011
- Audit citations:
  - [cli/commands/improve.py](/Users/andrew/Desktop/agentlab/cli/commands/improve.py):49
  - [cli/commands/improve.py](/Users/andrew/Desktop/agentlab/cli/commands/improve.py):82
  - [cli/commands/improve.py](/Users/andrew/Desktop/agentlab/cli/commands/improve.py):1457
  - [cli/commands/deploy.py](/Users/andrew/Desktop/agentlab/cli/commands/deploy.py):292
  - [cli/commands/deploy.py](/Users/andrew/Desktop/agentlab/cli/commands/deploy.py):318
  - [cli/commands/deploy.py](/Users/andrew/Desktop/agentlab/cli/commands/deploy.py):414
  - [cli/commands/deploy.py](/Users/andrew/Desktop/agentlab/cli/commands/deploy.py):440

### Why this matters

This creates a silent wrong-artifact deployment bug. The lineage may say one
attempt was accepted while a different candidate version was actually deployed.

### Observed behavior

`improve accept` passes only `attempt_id` and `strategy` into deploy.
Deploy still chooses the version via "latest deployable candidate" logic when
`config_version` is `None`.

### Root cause

Attempt identity and config-version identity are not tied together at deploy
selection time. `attempt_id` is currently only used for lineage emission.

### Scope

Improve/deploy seam only. Avoid broad refactors.

### Likely files

- [cli/commands/improve.py](/Users/andrew/Desktop/agentlab/cli/commands/improve.py)
- [cli/commands/deploy.py](/Users/andrew/Desktop/agentlab/cli/commands/deploy.py)
- Potentially change-card / experiment metadata if needed

### Implementation notes

- Best fix shape: resolve the candidate config version associated with the
  accepted attempt and pass `config_version` explicitly into deploy.
- If that mapping is not currently durable enough, add the smallest persistence
  needed to make it durable.

### Acceptance criteria

- If two candidate versions exist, `improve accept <attempt-id>` deploys the
  candidate associated with that attempt, not the newest candidate globally.
- Improvement lineage records the same attempt and version that were deployed.

### Regression tests to add

- Create two candidate versions from different attempts and ensure accepting the
  older one deploys its own candidate.
- Verify the lineage view shows the same version that manifest/deploy selected.

### Agent prompt stub

Fix the improve-to-deploy seam so `improve accept <attempt-id>` deploys the
candidate version produced by that attempt, not whichever candidate is newest.
Make the linkage durable and add a regression test with multiple candidates.

## B006 - Deploy degraded gate ignores the standard `scores.composite` eval shape

- Priority: P0
- Effort: hours
- Parallel-safe: yes
- Audit citations:
  - [runner.py](/Users/andrew/Desktop/agentlab/runner.py):1423
  - [runner.py](/Users/andrew/Desktop/agentlab/runner.py):1493
  - [runner.py](/Users/andrew/Desktop/agentlab/runner.py):802
  - [runner.py](/Users/andrew/Desktop/agentlab/runner.py):816
  - `/tmp/agentlab-deploygate.NdsNPt/deploygate.stdout:1`
  - `/tmp/agentlab-deploygate-top.xiQ71R/deploygate.stderr:1`

### Why this matters

This lets degraded configs ship.

### Observed behavior

- A synthetic latest eval payload with `scores.composite = 0.4` still allowed
  deploy to proceed.
- A synthetic payload with top-level `composite = 0.4` correctly blocked deploy.

### Root cause

`_deploy_gate_check()` reads `payload.get("composite")` and `payload.get("score")`,
but the standard eval result format stores the score under `scores.composite`.

### Scope

Deploy gate parsing only.

### Likely files

- [runner.py](/Users/andrew/Desktop/agentlab/runner.py)
- Tests touching deploy-gate behavior

### Implementation notes

- Reuse the existing `_extract_eval_scores()` helper instead of hand-parsing
  another shape.
- Keep force-override behavior unchanged.

### Acceptance criteria

- A latest eval payload with `scores.composite < 0.6` blocks deploy.
- Top-level legacy shapes continue to work.
- `--force-deploy-degraded --reason ...` still overrides correctly.

### Regression tests to add

- Standard-shape payload test.
- Legacy-shape payload test.
- Override-with-reason test.

### Agent prompt stub

Fix deploy's degraded-eval gate so it blocks on the standard eval result shape
that stores metrics under `scores.composite`. Reuse existing score-normalization
helpers if possible. Add regression tests for both standard and legacy payload
shapes.

## B007 - Optimizer refuses to run on low-scoring all-pass evals

- Priority: P1
- Effort: days
- Parallel-safe: yes, but coordinate with B008
- Audit citations:
  - [runner.py](/Users/andrew/Desktop/agentlab/runner.py):1252
  - [runner.py](/Users/andrew/Desktop/agentlab/runner.py):1286
  - [evals/runner.py](/Users/andrew/Desktop/agentlab/evals/runner.py):458
  - [evals/runner.py](/Users/andrew/Desktop/agentlab/evals/runner.py):480
  - `/tmp/agentlab-value.f4kBxM/eval.out:15`
  - `/tmp/agentlab-value.f4kBxM/optimize.out:10`

### Why this matters

The product promise is measurable improvement, not just pass/fail cleanup.
Today the loop can report a middling composite while refusing to optimize.

### Observed behavior

In a fresh workspace, eval produced `3/3 passed` but only `0.8818` composite.
Optimize still said `Latest eval passed; no optimization needed`.

### Root cause

`_health_report_from_eval()` sets `needs_optimization` solely from the presence
of failed cases, not from low composite, low quality, or regressions relative to
prior runs.

### Scope

Optimize trigger policy. Avoid changing acceptance gates in the same patch unless
necessary.

### Likely files

- [runner.py](/Users/andrew/Desktop/agentlab/runner.py)
- Possibly [cli/commands/optimize.py](/Users/andrew/Desktop/agentlab/cli/commands/optimize.py)
- Possibly optimizer config defaults if thresholds need configuration

### Implementation notes

- Minimal fix options:
  - add a minimum composite threshold for "needs optimization";
  - add a minimum quality threshold;
  - or consult recent eval history for relative regressions.
- Prefer a conservative threshold and make it configurable if the codebase
  already has a place for that.

### Acceptance criteria

- A low-composite all-pass eval can still trigger optimize.
- High-quality all-pass evals still skip as before.
- The reason text should explain whether optimize is being triggered due to
  failures, low composite, or both.

### Regression tests to add

- All-pass / low-composite optimize path.
- All-pass / high-composite skip path.
- Reason-string assertions.

### Agent prompt stub

Fix the optimize trigger so it does not rely only on failed cases. An all-pass
eval with clearly low quality/composite should still be eligible for
optimization. Keep the change conservative and add regression tests for low-score
and high-score all-pass cases.

## B008 - Latest-eval resolution is race-prone and can select the wrong evidence

- Priority: P1
- Effort: days
- Parallel-safe: yes
- Audit citations:
  - [runner.py](/Users/andrew/Desktop/agentlab/runner.py):867
  - [runner.py](/Users/andrew/Desktop/agentlab/runner.py):898
  - [runner.py](/Users/andrew/Desktop/agentlab/runner.py):1125
  - [runner.py](/Users/andrew/Desktop/agentlab/runner.py):1143
  - [cli/commands/optimize.py](/Users/andrew/Desktop/agentlab/cli/commands/optimize.py):690
  - [cli/commands/optimize.py](/Users/andrew/Desktop/agentlab/cli/commands/optimize.py):705

### Why this matters

Optimizing the wrong eval run is a silent correctness failure.

### Observed behavior

Optimize resolves eval evidence by newest matching JSON file mtime. It also
accepts payloads with no `config_path` as valid for the active config.

### Root cause

The eval-to-optimize seam is file-discovery based rather than ID-based.

### Scope

Eval evidence selection only.

### Likely files

- [runner.py](/Users/andrew/Desktop/agentlab/runner.py)
- [cli/commands/optimize.py](/Users/andrew/Desktop/agentlab/cli/commands/optimize.py)

### Implementation notes

- Best fix shape:
  - prefer explicit `run_id` and config binding whenever available;
  - when using "latest", require a matching `config_path`;
  - fail or warn loudly if the latest payload is ambiguous.
- Avoid inventing a larger eval registry unless necessary.

### Acceptance criteria

- Optimize does not consume a latest payload for another config.
- Payloads missing `config_path` are not silently treated as valid active-config
  evidence unless there is an explicit justified compatibility path.
- A concurrent or stale latest file does not hijack optimize evidence.

### Regression tests to add

- Multiple eval-result files with different config paths.
- Latest file without `config_path`.
- `--eval-run-id` lookup with matching and mismatching config.

### Agent prompt stub

Harden eval-evidence selection for optimize. Do not rely on raw latest-file
mtime alone, and do not silently accept payloads with missing config binding as
evidence for the active config. Add focused tests for multiple eval-result files
and missing `config_path`.

## B009 - Optimize reports the most recent attempt by timestamp, not the attempt created in the current cycle

- Priority: P1
- Effort: hours to days
- Parallel-safe: yes
- Audit citations:
  - [cli/commands/optimize.py](/Users/andrew/Desktop/agentlab/cli/commands/optimize.py):440
  - [cli/commands/optimize.py](/Users/andrew/Desktop/agentlab/cli/commands/optimize.py):443
  - [cli/commands/optimize.py](/Users/andrew/Desktop/agentlab/cli/commands/optimize.py):787
  - [optimizer/memory.py](/Users/andrew/Desktop/agentlab/optimizer/memory.py):118
  - [optimizer/memory.py](/Users/andrew/Desktop/agentlab/optimizer/memory.py):132

### Why this matters

This produces misleading IDs in CLI output and downstream automations.

### Observed behavior

After optimize finishes, the command reads `memory.recent(limit=1)` to find the
attempt ID. Under concurrency, that row may belong to another process.

### Root cause

The optimize path does not carry the created attempt ID through the return value.

### Scope

Optimize result plumbing only.

### Likely files

- [cli/commands/optimize.py](/Users/andrew/Desktop/agentlab/cli/commands/optimize.py)
- [optimizer/loop.py](/Users/andrew/Desktop/agentlab/optimizer/loop.py)
- Possibly related result structs

### Implementation notes

- Preferred fix: have the optimization call return the created attempt ID when
  one exists, and thread that through instead of re-querying by timestamp.

### Acceptance criteria

- The attempt ID surfaced by optimize belongs to the current run.
- Concurrent optimize runs cannot swap surfaced attempt IDs.

### Regression tests to add

- Simulated concurrent or interleaved attempt creation.
- Assert returned attempt ID matches the attempt persisted for that cycle.

### Agent prompt stub

Fix optimize result plumbing so the command surfaces the attempt created by the
current cycle instead of re-reading the latest row by timestamp. Add a test that
would fail if another attempt is inserted between creation and reporting.

## B010 - Failure-cluster variant generation writes into the same eval corpus it will later be judged against

- Priority: P1
- Effort: days
- Parallel-safe: yes, but coordinate with any work on eval corpus layout
- Audit citations:
  - [optimizer/failure_analyzer.py](/Users/andrew/Desktop/agentlab/optimizer/failure_analyzer.py):395
  - [optimizer/failure_analyzer.py](/Users/andrew/Desktop/agentlab/optimizer/failure_analyzer.py):557
  - [evals/runner.py](/Users/andrew/Desktop/agentlab/evals/runner.py):160
  - [evals/runner.py](/Users/andrew/Desktop/agentlab/evals/runner.py):224
  - [optimizer/loop.py](/Users/andrew/Desktop/agentlab/optimizer/loop.py):1081
  - [optimizer/loop.py](/Users/andrew/Desktop/agentlab/optimizer/loop.py):1114

### Why this matters

If activated, this is classic train/test contamination.

### Observed behavior

The helper appends generated failure-cluster variants into
`evals/cases/generated_failures.yaml`, and the normal eval loader pulls every
YAML case file into the same corpus.

### Root cause

Generated cases are not partitioned into a training-only dataset. Holdout logic
is a hash slice over the same merged corpus, not a separate immutable test set.

### Scope

Eval corpus partitioning for generated failure-cluster variants.

### Likely files

- [optimizer/failure_analyzer.py](/Users/andrew/Desktop/agentlab/optimizer/failure_analyzer.py)
- [evals/runner.py](/Users/andrew/Desktop/agentlab/evals/runner.py)
- Possibly eval corpus layout docs/tests

### Implementation notes

- Minimal safe fix options:
  - write generated variants to a training-only directory excluded from normal
    `eval run`;
  - or tag/split them explicitly and make the default runner exclude them from
    held-out evaluation.
- Keep backward compatibility for existing case files where possible.

### Acceptance criteria

- Generated failure-cluster variants are not included in the held-out eval set
  by default.
- If there is a training/eval toggle, the default user-facing eval should remain
  contamination-safe.

### Regression tests to add

- Case-generation path writes to a non-held-out corpus.
- Default `eval run` excludes generated-training-only cases.
- Optional training mode includes them when requested.

### Agent prompt stub

Prevent train/test contamination from failure-cluster-generated cases. Do not
let default eval runs grade the system on cases it just generated from its own
failures. Introduce the smallest safe partitioning mechanism and add tests that
prove generated variants stay out of the held-out eval path.

## B011 - `ConfigVersionManager` can leave `active_version` and `canary_version` in a stale or contradictory state

- Priority: P1
- Effort: days
- Parallel-safe: no, coordinate with B002 and B005
- Audit citations:
  - [deployer/versioning.py](/Users/andrew/Desktop/agentlab/deployer/versioning.py):59
  - [deployer/versioning.py](/Users/andrew/Desktop/agentlab/deployer/versioning.py):99
  - [deployer/versioning.py](/Users/andrew/Desktop/agentlab/deployer/versioning.py):101
  - [deployer/versioning.py](/Users/andrew/Desktop/agentlab/deployer/versioning.py):130

### Why this matters

Manifest truth is the backbone of build, eval, improve, and deploy resolution.

### Observed behavior

- `save_version(status="active")` updates `active_version` but does not clear an
  existing `canary_version`.
- `mark_canary()` can mark the active version as canary if called directly.

### Root cause

Manifest invariants are enforced inconsistently between CLI wrappers and the
version manager itself.

### Scope

Version-manager invariants only.

### Likely files

- [deployer/versioning.py](/Users/andrew/Desktop/agentlab/deployer/versioning.py)
- Tests around deploy/versioning behavior

### Implementation notes

- Encode invariants in the version manager itself:
  - at most one canary;
  - active and canary cannot point at contradictory states unless explicitly
    intended;
  - saving a new active version should clear or reconcile old canary state.

### Acceptance criteria

- Manifest invariants hold after `save_version`, `promote`, `mark_canary`, and
  `rollback`.
- Direct API usage cannot create impossible active/canary combinations.

### Regression tests to add

- Save active when canary exists.
- Mark active as canary should fail or normalize.
- Promote and rollback state-transition tests.

### Agent prompt stub

Harden `ConfigVersionManager` so manifest invariants hold even when it is used
directly, not just through CLI guards. Add tests covering `save_version`,
`mark_canary`, `promote`, and `rollback` transitions.

## B012 - Corrupt build/eval state stores are silently ignored or reset

- Priority: P2
- Effort: days
- Parallel-safe: yes
- Audit citations:
  - [shared/build_artifact_store.py](/Users/andrew/Desktop/agentlab/shared/build_artifact_store.py):106
  - [shared/build_artifact_store.py](/Users/andrew/Desktop/agentlab/shared/build_artifact_store.py):120
  - [shared/build_artifact_store.py](/Users/andrew/Desktop/agentlab/shared/build_artifact_store.py):79
  - [shared/build_artifact_store.py](/Users/andrew/Desktop/agentlab/shared/build_artifact_store.py):82
  - [runner.py](/Users/andrew/Desktop/agentlab/runner.py):1104
  - [runner.py](/Users/andrew/Desktop/agentlab/runner.py):1112

### Why this matters

Silent corruption turns real failures into silent no-ops and wrong-latest
selection.

### Observed behavior

- Corrupt `build_artifacts.json` is treated as empty state.
- Corrupt latest eval JSON becomes `(latest_path, None)` and downstream logic may
  skip or degrade behavior instead of surfacing corruption clearly.

### Root cause

State-store reads are designed to be permissive, but for core handoff artifacts
that permissiveness hides integrity failures.

### Scope

Core persisted state handling only.

### Likely files

- [shared/build_artifact_store.py](/Users/andrew/Desktop/agentlab/shared/build_artifact_store.py)
- [runner.py](/Users/andrew/Desktop/agentlab/runner.py)

### Implementation notes

- Convert silent resets into explicit errors or warnings for load-bearing state.
- If backward compatibility requires lenient reads, at least surface a prominent
  operator warning and avoid continuing with an ambiguous "latest" artifact.

### Acceptance criteria

- Corrupt latest build/eval state is surfaced clearly.
- The CLI does not silently proceed as if there were no prior state when core
  handoff files are unreadable.

### Regression tests to add

- Corrupt `build_artifacts.json`.
- Corrupt `eval_results_latest.json`.
- Assert explicit failure or explicit warning plus safe stop.

### Agent prompt stub

Harden core state-store reads so corrupt build/eval handoff artifacts are not
silently ignored or reset. Add tests for unreadable JSON state and ensure the
CLI fails loudly or stops safely with a clear warning.

## B013 - Failure-analysis LLM payload parsing is too permissive

- Priority: P2
- Effort: hours to days
- Parallel-safe: yes
- Audit citations:
  - [optimizer/failure_analyzer.py](/Users/andrew/Desktop/agentlab/optimizer/failure_analyzer.py):225
  - [optimizer/failure_analyzer.py](/Users/andrew/Desktop/agentlab/optimizer/failure_analyzer.py):261
  - [optimizer/failure_analyzer.py](/Users/andrew/Desktop/agentlab/optimizer/failure_analyzer.py):445
  - [optimizer/failure_analyzer.py](/Users/andrew/Desktop/agentlab/optimizer/failure_analyzer.py):463

### Why this matters

Malformed-but-parseable LLM output can steer the optimizer toward nonsense
surfaces without tripping the deterministic fallback.

### Observed behavior

`_parse_llm_analysis()` coerces strings/numbers into a `FailureAnalysis` object
but does not validate semantic constraints like known surfaces, severity range,
or cluster/sample consistency.

### Root cause

There is syntactic coercion but no semantic validation layer.

### Scope

Failure-analysis payload validation only.

### Likely files

- [optimizer/failure_analyzer.py](/Users/andrew/Desktop/agentlab/optimizer/failure_analyzer.py)

### Implementation notes

- Add a narrow validation step after JSON extraction and before accepting the
  parsed analysis.
- On invalid semantic payloads, fall back to deterministic analysis.

### Acceptance criteria

- Unknown or semantically invalid cluster payloads do not propagate into the
  accepted analysis.
- Invalid payloads trigger deterministic fallback.

### Regression tests to add

- Unknown surface / failure type.
- Out-of-range severity.
- Non-matching sample IDs or malformed clusters.

### Agent prompt stub

Add semantic validation to failure-analysis parsing so malformed-but-JSON-valid
LLM output does not drive optimizer decisions. Invalid payloads should trigger
deterministic fallback. Add targeted tests for bad cluster payloads.

## B014 - Acceptance tests do not cover the actual advertised value chain

- Priority: P2
- Effort: days
- Parallel-safe: yes, but easiest after B002-B008 land
- Audit citations:
  - [tests/test_e2e_value_chain_cli.py](/Users/andrew/Desktop/agentlab/tests/test_e2e_value_chain_cli.py):61
  - [tests/test_e2e_value_chain_cli.py](/Users/andrew/Desktop/agentlab/tests/test_e2e_value_chain_cli.py):294

### Why this matters

Several critical bugs survived because the acceptance harness allows the loop to
no-op and never exercises the exact user-facing command chain.

### Observed behavior

Current acceptance tests:

- allow optimize to skip and still pass;
- use `review apply` rather than the `improve` flow;
- do not cover first-build-in-fresh-dir;
- do not cover deploy gate parsing on `scores.composite`.

### Root cause

The acceptance suite validates component survivability, not true value-chain
closure.

### Scope

Test coverage only.

### Likely files

- [tests/test_e2e_value_chain_cli.py](/Users/andrew/Desktop/agentlab/tests/test_e2e_value_chain_cli.py)
- Possibly adjacent CLI acceptance tests

### Implementation notes

- Add new tests; do not weaken existing ones.
- Keep fixtures deterministic and mock-provider-safe.

### Acceptance criteria

- There is a test for the exact published loop:
  `build -> eval -> optimize -> improve -> eval -> deploy`.
- There are tests for first-build manifest creation, degraded deploy gating on
  `scores.composite`, and multiple-candidate improve acceptance.

### Regression tests to add

- This ticket is itself the test work:
  - exact published loop,
  - no-op optimize rejection when score is low,
  - `improve run --auto`,
  - `improve accept` with multiple candidates,
  - deploy gate on standard eval payload shape.

### Agent prompt stub

Strengthen the CLI acceptance harness so it covers the actual user-facing value
chain rather than only partial or skip-friendly paths. Add targeted tests for
the exact advertised loop and the key seam failures identified in the audit.

## Optional Follow-On Work

These are not bug tickets yet, but they are likely to become one once the main
loop is stabilized:

- Add explicit artifact IDs across build -> eval -> optimize -> improve -> deploy
  instead of relying on latest-file or latest-row lookups.
- Separate training, tuning, canary, and held-out eval corpora more explicitly.
- Introduce a live-eval mode acceptance harness that uses an owned deterministic
  stub agent instead of `mock_agent_response`.
