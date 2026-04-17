# AgentLab Value-Chain Audit

## 1. Loop closure proof (or disproof)

Status: DISPROVED for the exact sequence requested from a clean scratch directory.

Before the loop even starts, the installed `agentlab` console script is broken from a clean cwd: `pyproject.toml` installs `runner` plus many packages, but omits `agent_card` from the package include list, so importing `cli/commands/dataset.py` fails when it reaches `from agent_card.schema import AgentCardModel` (`pyproject.toml:31-80`, `/tmp/agentlab_help.txt:1-16`). I used `PYTHONPATH=/Users/andrew/Desktop/agentlab` only as a source-tree workaround so the rest of the audit could proceed.

### Exact sequence run in `/tmp/agentlab-audit.4Vd5RB`

1. `agentlab build "a customer support triage agent for a SaaS product"`
   - Exit: `0` (`/tmp/agentlab-audit.4Vd5RB/build.stdout:2-23`).
   - Produced:
     - `.agentlab/build_artifact_latest.json` (legacy artifact JSON, 2846 bytes) (`cli/commands/build.py:194-205`, `shared/contracts/build_artifact.py:9-26`, `/tmp/agentlab-audit-artifacts.txt:1`).
     - `configs/v001_built_from_prompt.yaml` (seed config, 7924 bytes) (`cli/commands/build.py:168-185`, `/tmp/agentlab-audit-artifacts.txt:2`).
     - `evals/cases/generated_build.yaml` (generated eval suite, 646 bytes) (`runner.py:2275-2321`, `/tmp/agentlab-audit-artifacts.txt:3`).
   - Consumed by next stage:
     - `eval run` did **not** read `.agentlab/build_artifact_latest.json`.
     - It discovered a workspace only because `build` had created `.agentlab/`, then resolved the active config from the workspace and suite from `evals/cases/` (`cli/workspace.py:352-360`, `cli/workspace.py:280-306`, `runner.py:1054-1061`, `cli/commands/eval.py:140-158`).
   - Linkage type: implicit filesystem discovery, not explicit ID/FK.
   - Race risk:
     - Fresh-dir builds are not versioned; they use `_next_built_config_path()` to scan filenames and choose the next `vNNN_built_from_prompt.yaml` with no lock (`cli/commands/build.py:171-185`, `runner.py:1956-1968`).
     - Two concurrent builds can both compute the same next version and clobber the same file.
     - `BuildArtifactStore.save_latest()` is also last-writer-wins, with no file locking (`shared/build_artifact_store.py:28-54`).

2. `agentlab eval run --output-format stream-json`
   - Exit: `0` (`/tmp/agentlab-audit.4Vd5RB/eval_pre.stdout:1-10`).
   - Produced:
     - `.agentlab/eval_results_latest.json` (2268 bytes after the later post run overwrite; same path was used here) (`cli/commands/eval.py:367-379`, `/tmp/agentlab-audit-artifacts.txt:4`).
     - `eval_history.db` rows keyed by `run_id` (`evals/runner.py:1018-1057`, `evals/history.py:20-75`).
   - Consumed by next stage:
     - `optimize` searched for the latest eval result JSON by mtime, not by build ID (`runner.py:867-880`, `runner.py:1125-1143`, `cli/commands/optimize.py:690-705`).
   - Linkage type: implicit "latest eval result file" lookup.
   - Observed score:
     - Pre-optimize run `89e43651-4f3` scored `0.9749` on `2/2` generated-build cases (`/tmp/agentlab-audit-eval-history.txt:1`).
   - Race risk:
     - `_latest_eval_result_file()` chooses the newest matching JSON across cwd and `.agentlab/` by `st_mtime` (`runner.py:867-880`).
     - If two evals finish near-simultaneously, `optimize` without `--eval-run-id` can pick the wrong run.
     - Worse, `_latest_eval_payload_for_active_config()` accepts payloads with no `config_path` as valid for the active config (`runner.py:1125-1143`).

3. `agentlab optimize --cycles 2 --strategy adaptive`
   - Exit: `0` (`/tmp/agentlab-audit.4Vd5RB/optimize.stdout:2-22`).
   - Produced:
     - No candidate config.
     - No review card.
     - No optimization attempt row visible from the CLI output; both cycles skipped.
   - Why it skipped:
     - `optimize` converts the latest eval payload into a `HealthReport`.
     - `needs_optimization` is set only when there are failed case IDs, not when composite or quality are merely mediocre (`runner.py:1252-1286`).
     - Because the 2 generated build cases both passed, cycle 1 and cycle 2 reported `Latest eval passed; no optimization needed` (`cli/commands/optimize.py:741-772`, `/tmp/agentlab-audit.4Vd5RB/optimize.stdout:12-16`).
   - Consumed by next stage:
     - Nothing. The exact next command, `improve run --auto`, did not consume an optimize attempt.
   - Linkage type: none in practice for this run.
   - Race risk:
     - When a cycle *does* create an attempt, the CLI reports `attempt_id` by reading `memory.recent(limit=1)` after the run, not by a stable return value from the cycle (`cli/commands/optimize.py:440-443`, `optimizer/memory.py:118-132`).
     - A concurrent optimize process can therefore cause the wrong attempt ID to be surfaced.

4. `agentlab improve run --auto`
   - Exit: `0` (`/tmp/agentlab-audit.4Vd5RB/improve_run.stdout:1-22`, `/tmp/agentlab-audit.4Vd5RB/improve_run.stderr:1`).
   - What actually happened:
     - Because no `config_path` argument was passed, the Click wrapper printed a deprecation notice and routed into `_invoke_legacy_autofix()` instead of the eval -> optimize -> accept flow (`cli/commands/improve.py:1140-1175`).
     - That legacy path built an `EvalRunner` **without** a workspace `cases_dir`, so it evaluated the package-default suite (`evals/runner.py:97-113`, `cli/commands/improve.py:106-111`).
     - The observed `0.9378` score came from a different 55-case dataset fingerprint, not the just-built 2-case workspace suite (`/tmp/agentlab-audit-eval-history.txt:2`).
   - Produced:
     - `autofix.db` and a diagnosis/proposal view (`cli/commands/improve.py:119-169`, `/tmp/agentlab-audit.4Vd5RB/improve_run.stdout:3-22`).
   - Consumed by next stage:
     - Nothing deployable. No optimize attempt was accepted, and `_invoke_deploy()` was never reached in this exact command path.
   - Linkage type: wrong code path entirely.
   - Race risk:
     - Zero-arg `improve run` is not connected to `optimize` output at all; it cannot deterministically consume the previous optimize cycle.

5. `agentlab eval run` (post-improvement)
   - Exit: `0` (`/tmp/agentlab-audit.4Vd5RB/eval_post.stdout:1-37`).
   - Produced:
     - Overwrote `.agentlab/eval_results_latest.json` for the same workspace build suite (`cli/commands/eval.py:367-379`).
   - Observed score:
     - Post-improvement run `1dc903ab-2fb` also scored `0.9749` on the same 2-case dataset fingerprint (`/tmp/agentlab-audit-eval-history.txt:3`).
   - Improvement verdict:
     - No improvement occurred.
     - Pre and post runs used the same dataset fingerprint (`bfde333...`) and identical composite `0.9749`, so this is not leakage, not variance, and not a real gain; it is a no-op (`/tmp/agentlab-audit-eval-history.txt:1`, `/tmp/agentlab-audit-eval-history.txt:3`).

6. `agentlab deploy --auto-review --yes`
   - Exit: `0` (`/tmp/agentlab-audit.4Vd5RB/deploy.stdout:1`).
   - Produced:
     - No deployment.
   - Why it failed:
     - The first `build` in a fresh directory did not register a config version in `configs/manifest.json`; it only wrote a standalone YAML file (`cli/commands/build.py:171-185`).
     - `deploy` requires manifest history. With no history it prints `No config versions available. Run: agentlab optimize` and returns success in text mode (`cli/commands/deploy.py:691-713`, `/tmp/agentlab-audit.4Vd5RB/deploy.stdout:1`).
   - Linkage type:
     - None from this exact loop; deploy never saw a versioned candidate.
   - Race risk:
     - Even when `improve accept` passes an `attempt_id`, deploy still selects `config_version` by latest candidate/history unless one is explicitly provided (`cli/commands/improve.py:49-82`, `cli/commands/deploy.py:292-318`).
     - `attempt_id` is only written into lineage metadata, not used to select the deployed version (`cli/commands/deploy.py:414-440`).

### Answer to the central score question

For the exact requested loop, the score did **not** improve. Pre and post evals were both `0.9749` on the same 2-case corpus (`/tmp/agentlab-audit-eval-history.txt:1`, `/tmp/agentlab-audit-eval-history.txt:3`).

The only different score I observed, `0.9378`, came from `improve run --auto` evaluating a different 55-case default package suite because the command fell into the legacy autofix path (`cli/commands/improve.py:1140-1175`, `cli/commands/improve.py:106-111`, `evals/runner.py:112-113`, `/tmp/agentlab-audit-eval-history.txt:2`). That score is not comparable to the pre/post build-suite runs.

Live-agent improvement is UNVERIFIED in this sandbox because all runnable evals explicitly fell back to mock mode (`evals/runner.py:113`, `/tmp/agentlab-audit.4Vd5RB/eval_pre.stdout:2`, `/tmp/agentlab-audit.4Vd5RB/eval_post.stdout:7-28`, `/tmp/agentlab-value.f4kBxM/eval.out:7-28`). What I can verify is worse: the default loop silently allows simulated scoring and still no-ops.

## 2. Per-stage correctness audit

### Build

- Help vs code:
  - The command advertises "scaffold eval/deploy handoff files" and does write a config, eval cases, and build artifact (`cli/commands/build.py:69-109`, `cli/commands/build.py:168-205`).
  - But in a fresh non-workspace directory it does **not** create a versioned manifest entry, so the advertised downstream deploy handoff is incomplete (`cli/commands/build.py:171-185`).
- Boundary validation:
  - `prompt` is required by Click, but connector names are arbitrary free-form strings and only whitespace-trimmed (`cli/commands/build.py:80-86`, `cli/commands/build.py:127-130`).
  - `output_dir` is any string path; no validation that the target is an initialized workspace (`cli/commands/build.py:87`, `cli/commands/build.py:118-125`).
- Exit codes:
  - `--strict-live` exits `12` if live LLM is unavailable (`cli/commands/build.py:143-152`).
  - Otherwise build falls back to pattern synthesis and still exits `0` (`cli/commands/build.py:153-162`).
- Silent handling:
  - Live-build failures are collapsed into fallback unless `--strict-live` is set (`runner.py:2087-2137`, `cli/commands/build.py:133-162`).
  - Corrupt `build_artifacts.json` is silently reinitialized by `_load()` (`shared/build_artifact_store.py:106-120`).
- Worst accepted input:
  - A nonsense prompt plus arbitrary connector names still yields a plausible-looking config/eval scaffold and "complete" build artifact, even though no external contract was validated (`cli/commands/build.py:127-205`).

### Eval

- Help vs code:
  - `eval run` help matches the implemented top-level flow reasonably well (`cli/commands/eval.py:422-506`, `cli/commands/eval.py:548-565`).
  - `eval dataset` help says "import/export" even though the registered subcommands are `dedupe`, `balance`, `bootstrap`, and `ingest` (`cli/commands/dataset.py:170-175`, `cli/commands/eval.py:1115-1120`).
- Boundary validation:
  - `eval run` validates option types, but case files tolerate duplicate IDs by silently uniquifying them instead of failing (`evals/runner.py:185-224`).
  - Dataset integrity issues only warn unless `dataset_strict_integrity` is enabled (`evals/runner.py:360-413`).
  - `eval ingest --from-traces` is better defended: it validates JSONL shape, requires redaction consent, and exits `20` in non-interactive mode without `--yes` (`cli/commands/ingest.py:36-63`, `cli/commands/ingest.py:187-212`, `cli/commands/ingest.py:218-312`).
- Exit codes:
  - `--strict-live` maps mock fallback to exit `12` (`cli/commands/eval.py:345-353`, `cli/commands/eval.py:566-570`).
  - Other command errors raise `ClickException` and exit nonzero through Click (`cli/commands/eval.py:566-570`).
- Silent handling:
  - Custom evaluator exceptions are swallowed and scored as `0.0` (`evals/runner.py:533-538`).
  - Missing history storage is tolerated; eval still returns scores without durable history (`evals/runner.py:1047-1057`).
- Worst accepted input:
  - An all-pass suite with poor average quality still looks "healthy enough" for the optimizer to skip, because per-case `passed` is only `quality_score >= 0.5 and safety_passed` (`evals/runner.py:458-480`, `runner.py:1252-1286`).

#### Tag-filter check: `_apply_tag_filters`

Three distinguishing tests:

1. Include should be OR-across-tags: `['billing']`, `['safety']`, and `['billing','safety']` all survive `include=['billing','safety']`.
2. Exclude should drop any case carrying any excluded tag: only `['billing']` survives `exclude=['safety','flaky']`.
3. Matching should be case-sensitive: `include=['Billing']` should match `['Billing']`, not `['billing']`.

Observed result: PASS (`evals/runner.py:30-60`, `/tmp/tag_filter_check.txt:1-3`).

### Optimize

- Help vs code:
  - The user-facing API still accepts `--strategy simple|adaptive|full`, but the option is deprecated and internally remapped onto `--mode` (`cli/commands/optimize.py:152-160`, `/tmp/agentlab-audit.4Vd5RB/optimize.stdout:8-9`).
- Boundary validation:
  - Without eval evidence, optimize usually skips and exits `0`; it only hard-fails when `--eval-run-id` or `--require-eval-evidence` is set (`cli/commands/optimize.py:705-739`).
  - The optimizer only triggers on failed cases, not on low composite/quality (`runner.py:1252-1286`).
- Exit codes:
  - `--strict-live` exits `12` when the proposer is mock (`cli/commands/optimize.py:292-306`, `cli/commands/optimize.py:1088-1090`).
  - Otherwise skipped cycles still exit `0` (`cli/commands/optimize.py:741-772`).
- Silent handling:
  - Agent Card markdown generation is best-effort and swallowed on error (`cli/commands/optimize.py:315-323`).
  - Reflection context fetch is swallowed (`optimizer/loop.py:437-448`).
  - Auto-grow cases is a silent no-op unless three optional dependencies are present (`optimizer/loop.py:167-173`, `optimizer/loop.py:333-390`).
- Worst accepted input:
  - A configuration with `3/3` passing cases but only `0.8818` composite is accepted as "no optimization needed" (`/tmp/agentlab-value.f4kBxM/eval.out:15-24`, `/tmp/agentlab-value.f4kBxM/optimize.out:8-20`, `runner.py:1252-1286`).

### Improve

- Help vs code:
  - `improve run` is documented as `eval -> optimize 1 cycle -> present top proposal`, but that is true only when a `config_path` argument is provided (`cli/commands/improve.py:1163-1186`, `cli/commands/improve.py:430-516`).
  - The exact user-visible form `improve run --auto` with no config path is a deprecated legacy autofix workflow (`cli/commands/improve.py:1149-1175`).
- Boundary validation:
  - `improve accept` correctly rejects missing or ambiguous attempt prefixes (`cli/commands/improve.py:1422-1433`).
  - But zero-arg `improve run` does not validate that it is consuming the prior optimize attempt; it simply diverges onto another subsystem (`cli/commands/improve.py:1168-1175`).
- Exit codes:
  - Missing/ambiguous attempt prefixes exit `1` (`cli/commands/improve.py:1422-1433`).
  - Zero-arg legacy improve returns `0` even when it produces no deployable change (`/tmp/agentlab-audit.4Vd5RB/improve_run.stdout:1-22`).
- Silent handling:
  - Measurement scheduling errors after `improve accept` are swallowed (`cli/commands/improve.py:1461-1469`).
  - `improve diff` swallows patch-bundle JSON parse failure (`cli/commands/improve.py:934-1008`).
- Worst accepted input:
  - `improve run --auto` in a workspace silently evaluates the package default suite rather than the workspace suite, then suggests autofix proposals unrelated to the immediately preceding optimize cycle (`cli/commands/improve.py:106-111`, `cli/commands/improve.py:1140-1175`, `evals/runner.py:112-113`).

### Deploy

- Help vs code:
  - `deploy --auto-review --yes` sounds like a reliable release entry point, but in text mode a missing-version failure prints a message and exits `0` (`cli/commands/deploy.py:530-538`, `cli/commands/deploy.py:708-713`, `/tmp/agentlab-audit.4Vd5RB/deploy.stdout:1`).
- Boundary validation:
  - `--force-deploy-degraded` requires a reason of at least 10 chars (`runner.py:1457-1468`).
  - The degraded-eval gate itself is malformed for standard eval payloads, because it ignores `scores.composite` (`runner.py:1436-1446`).
- Exit codes:
  - Blocked degraded verdicts exit `13` only when the gate actually parses a top-level `composite` or `score.composite` (`cli/commands/deploy.py:51-55`, `cli/commands/deploy.py:586-588`, `/tmp/agentlab-deploygate-top.xiQ71R/deploygate.stderr:1-5`).
  - Missing history returns a failed stream-json terminal envelope but still exits `0` (`cli/commands/deploy.py:224-243`, `/tmp/agentlab-deploystream.t3SCu9/out.stdout:1-3`).
- Silent handling:
  - Auto-review approval exceptions are swallowed (`cli/commands/deploy.py:177-188`, `cli/commands/deploy.py:539-550`).
  - Improvement-lineage emission is swallowed (`cli/commands/deploy.py:414-440`).
- Worst accepted input:
  - A degraded standard eval artifact with `scores.composite: 0.4` still allows deploy to proceed (`runner.py:1436-1446`, `/tmp/agentlab-deploygate.NdsNPt/deploygate.stdout:1-3`, `/tmp/agentlab-deploygate.NdsNPt/configs/manifest.json:1-16`).

### Special attention: `FailureClusterer` / failure-analysis fallback safety

- The deterministic fallback itself is safe in the narrow sense that malformed or unparseable LLM output falls back to one cluster per non-zero failure bucket with a fixed surface mapping (`optimizer/failure_analyzer.py:445-463`, `optimizer/failure_analyzer.py:269-359`).
- However, `_parse_llm_analysis()` does not semantically validate fields beyond `float()` / `int()` coercion. A payload with unknown `failure_type`, nonsense `sample_ids`, or out-of-range-but-numeric `severity` will be accepted and forwarded downstream (`optimizer/failure_analyzer.py:225-261`).
- If a numeric coercion raises, `_llm_analyze()` bubbles the exception and `analyze()` logs a warning then falls back (`optimizer/failure_analyzer.py:586-592`, `optimizer/failure_analyzer.py:445-463`).

### Special attention: `deployer/versioning.py`

`active_version` and `canary_version` can diverge incorrectly under at least three conditions:

1. `save_version(..., status="active")` updates `active_version` but does not clear an existing `canary_version`, so a stale canary pointer can survive an immediate deploy (`deployer/versioning.py:84-99`).
2. `mark_canary(version)` does not reject `version == active_version`; the CLI has a guard, but the underlying version manager does not (`deployer/versioning.py:116-130`, `cli/commands/deploy.py:336-349`).
3. The manifest is read and written without locking or reload-on-write sequencing, so concurrent `save_version`, `promote`, or `mark_canary` calls can race (`deployer/versioning.py:32-41`, `deployer/versioning.py:59-130`).

## 3. The "does it actually improve performance?" question

### (a) Train/test contamination

- The variant-generation helper is contamination-prone if activated:
  - `FailureAnalyzer.analyze(..., case_generator=...)` appends generated variants to `evals/cases/generated_failures.yaml` and documents that the runner will pick them up on the next `load_cases()` (`optimizer/failure_analyzer.py:395-429`, `optimizer/failure_analyzer.py:487-557`).
  - `EvalRunner.load_cases()` loads all `*.yaml` files in the cases directory with no train/test partition discipline (`evals/runner.py:160-224`).
  - `_run_holdout_scores()` then partitions that same merged corpus by case-id hash, not by an explicit immutable holdout split (`optimizer/loop.py:1081-1114`).
- Important nuance for the current CLI:
  - I found no production call site in the audited CLI path that passes `case_generator=` into `FailureAnalyzer.analyze()` (`optimizer/proposer.py:454-463`, `cli/commands/optimize.py:285-343`).
  - So commit `a7b290c`'s contamination path exists in code and tests, but it is not active in the default `agentlab optimize` CLI flow I audited.
- `EvalHistoryStore` is not part of case loading at all; it is write-side history only (`evals/history.py:45-75`, `evals/runner.py:1018-1057`).

### (b) Statistical significance

- `significance_p_value` is computed in `Optimizer._finalize_candidate()` by calling `paired_significance()` on paired per-case composite values from baseline and candidate eval runs (`optimizer/loop.py:709-740`).
- The underlying test is a paired sign-flip permutation test, which is appropriate for paired per-case score deltas (`evals/statistics.py:47-140`).
- Multiple-comparisons correction is **not** applied across cycles:
  - A Holm-Bonferroni helper exists, but nothing in the audited optimization path calls it (`evals/statistics.py:333-360`, search result: only tests reference it).
- Minimum-N is not a hard gate:
  - If `n_pairs < min_pairs`, the significance result is advisory only and the candidate can still be accepted (`optimizer/loop.py:727-731`).

### (c) Regression detection

- Intended behavior:
  - Deploy should block when the latest eval verdict is `Degraded` or `Needs Attention` (`runner.py:1423-1493`).
- Actual behavior:
  - The gate reads only top-level `composite` or nested `score.composite`, but standard eval output stores the metric under `scores.composite` (`runner.py:1440-1446`, `cli/commands/eval.py:367-379`, `runner.py:802-816`).
  - I verified the bug:
    - `scores.composite = 0.4` still deployed v001 as canary (`/tmp/agentlab-deploygate.NdsNPt/deploygate.stdout:1-3`).
    - top-level `composite = 0.4` correctly blocked deploy with exit `13` (`/tmp/agentlab-deploygate-top.xiQ71R/deploygate.stderr:1-5`).

### (d) Feedback closure

- `agentlab eval ingest --from-traces` converts production trace JSONL into `evals/cases/ingested_traces.yaml` after mandatory redaction consent (`cli/commands/ingest.py:218-312`).
- That command does **not** write into `EvalHistoryStore`; only `eval run` does (`cli/commands/ingest.py:257-312`, `evals/runner.py:1018-1057`).
- The next optimize cycle only sees those ingested traces if a fresh `eval run` happens afterward, because optimize reads the latest eval payload JSON and uses an `EvalRunner` over the workspace case directory (`cli/commands/optimize.py:690-705`, `runner.py:1054-1061`, `evals/runner.py:160-224`).
- So the closure exists only as:
  - traces -> ingested YAML
  - manual `eval run`
  - eval payload/history
  - later optimize
- There is no direct automatic `trace ingest -> EvalHistoryStore -> optimizer` seam.

### (e) Metric honesty

- `CompositeScorer` is a weighted sum: quality `0.40`, safety `0.25`, latency `0.20`, cost `0.15` (`evals/scorer.py:237-307`).
- Therefore composite can increase while safety decreases.
- Concrete example under the shipped weights:
  - Baseline: quality `1.0`, safety `1.0`, latency `0.5`, cost `0.5` -> composite `0.825`.
  - Candidate: quality `1.0`, safety `0.97`, latency `1.0`, cost `1.0` -> composite `0.9925`.
  - Safety regresses, composite improves.
- The optimizer gates only reject metric drops greater than the regression threshold (`0.05` by default), so smaller safety regressions can still be accepted (`optimizer/gates.py:15-17`, `optimizer/gates.py:45-71`, `optimizer/gates.py:89-116`).

## 4. Seam & contract gaps

### build -> eval

- Contract:
  - Build writes a seed config YAML, generated eval YAML, and a legacy build artifact JSON (`cli/commands/build.py:168-205`, `shared/contracts/build_artifact.py:9-26`).
- Linkage:
  - Eval ignores the build artifact JSON and discovers workspace state from `.agentlab/`, active config from workspace metadata/manifest/max-version, and cases from `evals/cases` (`cli/workspace.py:280-306`, `cli/workspace.py:352-360`, `runner.py:1054-1061`, `cli/commands/eval.py:140-158`).
- Failure mode:
  - First build in a fresh dir is not versioned, so deploy later has no manifest history.
  - Concurrent builds can collide on `_next_built_config_path()` and latest-artifact writes.

### eval -> optimize

- Contract:
  - Eval persists a latest JSON file, an eval results DB, and optional SQLite history (`cli/commands/eval.py:367-379`, `evals/runner.py:1018-1057`, `evals/history.py:20-75`).
- Linkage:
  - Optimize uses latest-file lookup by mtime unless `--eval-run-id` is passed (`runner.py:867-880`, `runner.py:1125-1175`, `cli/commands/optimize.py:690-705`).
- Failure mode:
  - Wrong eval can be optimized under concurrency or stale artifacts.
  - If all cases pass, optimize skips regardless of low composite.

### optimize -> improve

- Contract:
  - Optimize persists accepted attempts in optimizer memory and candidate configs in manifest, and may create review cards (`optimizer/loop.py:768-800`, `cli/commands/optimize.py:829-885`, `cli/commands/optimize.py:538-585`).
- Linkage:
  - `improve run` with no config path does not consume any of that state; it routes into legacy autofix (`cli/commands/improve.py:1140-1175`).
  - `improve accept` resolves an attempt prefix from `OptimizationMemory` (`cli/commands/improve.py:1422-1437`).
- Failure mode:
  - The exact documented "optimize, then improve run --auto" chain is broken.

### improve -> deploy

- Contract:
  - `_invoke_deploy()` passes only `attempt_id` and `strategy`; it does not pass `config_version` (`cli/commands/improve.py:49-82`).
- Linkage:
  - Deploy chooses version by latest deployable candidate/history when `config_version` is `None` (`cli/commands/deploy.py:292-318`).
  - `attempt_id` is only emitted into lineage after the version is already chosen (`cli/commands/deploy.py:414-440`).
- Failure mode:
  - If multiple candidate versions exist, `improve accept <attempt-id>` can deploy whichever candidate is newest, not necessarily the one that created that attempt.

### deploy -> eval

- Contract:
  - Deploy mutates `configs/manifest.json` via `promote()` / `mark_canary()` (`deployer/versioning.py:101-130`).
- Linkage:
  - `eval run` resolves the active config from workspace metadata/manifest or falls back to the highest config version (`cli/workspace.py:280-306`, `cli/commands/eval.py:146-158`).
- Failure mode:
  - If manifest and workspace metadata diverge, eval can target a different config than deploy just changed.
  - `save_version(status="active")` does not clear stale canary pointers.

### optimize -> eval (failure-cluster variants)

- Contract:
  - Optional failure-cluster variants are appended into `evals/cases/generated_failures.yaml` (`optimizer/failure_analyzer.py:487-557`).
- Linkage:
  - `EvalRunner.load_cases()` loads that file alongside all other case YAMLs (`evals/runner.py:160-224`).
- Failure mode:
  - If the hook is activated, the optimizer can end up re-evaluating on cases it just wrote, with only hash-based "holdout" slices inside the same merged corpus (`optimizer/loop.py:1081-1114`).

### Registry seams

- `registry/skill_store.py` and `registry/tool_contracts.py` both version records (`registry/skill_store.py:284-319`, `registry/tool_contracts.py:21-68`).
- But I found no cross-stage drift detection:
  - no check that a built config references a tool-contract version that eval/deploy still understands;
  - no persistent agent-usage mapping for tool contracts beyond an in-memory dict (`registry/tool_contracts.py:16-19`, `registry/tool_contracts.py:74-82`).
- Failure mode:
  - Build/eval/optimize/deploy can drift across skill/tool contract revisions without an explicit compatibility gate.

## 5. TODOs, stubs, and load-bearing fakes

### Confirmed half-built pieces

- `builder/harness.py` emits stub tool implementations that return `"stub_placeholder"` and a TODO comment instead of real integrations (`builder/harness.py:2204-2221`).
  - Impact on audited loop:
    - The exact build/eval/optimize/deploy loop I ran did not execute generated tool code, so this is not the direct reason the loop failed.
    - It does mean build can synthesize deployable-looking agents whose tool layer is fake.

- `evals/data_engine.py` has stub scorers:
  - hallucination scoring always returns `1.0` (`evals/data_engine.py:377-384`);
  - user-simulation scoring always returns `0.0` (`evals/data_engine.py:405-413`).
  - Impact on audited loop:
    - I found no call site from the audited `eval run` path into these methods, so loop dependence is UNVERIFIED and appears inactive in the default CLI path.

- `policy_opt/backends/openai_dpo.py` and `openai_rft.py` are explicit `NotImplementedError` stubs for start/status/result/cancel (`policy_opt/backends/openai_dpo.py:61-109`, `policy_opt/backends/openai_rft.py:57-105`).
  - Impact on audited loop:
    - I found no dependency from the five audited stages onto these backends.

- `runner.py` hardcodes `pass_rate=0.5` in curriculum generation (`runner.py:7130-7136`).
  - Impact on audited loop:
    - Search showed this fake feeds curriculum difficulty generation, not build/eval/optimize/improve/deploy gating (`optimizer/curriculum_generator.py:128-199`).
    - So it is a fake oracle, but not one currently making ship/no-ship decisions in the audited loop.

### TODO / stub search inside the audited modules

Searching the five-stage modules plus their core dependencies found very few literal TODO markers, which makes the real risk more subtle: broad fallbacks and swallowed exceptions, not explicit TODO banners (`/Users/andrew/Desktop/agentlab/evals/data_engine.py:381-409`, `/Users/andrew/Desktop/agentlab/runner.py:7135`, `/Users/andrew/Desktop/agentlab/policy_opt/backends/openai_dpo.py:64-108`, `/Users/andrew/Desktop/agentlab/policy_opt/backends/openai_rft.py:60-104`, `/Users/andrew/Desktop/agentlab/builder/harness.py:2215`).

The load-bearing fakes that *do* affect correctness today are:

1. Mock eval mode is the default fallback, and the CLI lets the loop proceed with simulated scores unless `--strict-live` is explicitly set (`evals/runner.py:113`, `cli/commands/eval.py:168-178`, `cli/commands/optimize.py:292-306`).
2. `improve run --auto` is effectively a compatibility shim over the old autofix system, not the new optimize/improve/deploy chain (`cli/commands/improve.py:1140-1175`).
3. Deploy's degraded gate is wired to the wrong JSON shape (`runner.py:1436-1446`).

## 6. Acceptance harness reality check

### `test_demo_build_to_ship_golden_path`

- What it asserts:
  - `new` exits `0` and prints a recommended loop (`tests/test_e2e_value_chain_cli.py:68-77`).
  - Every command in the scripted list exits `0` (`tests/test_e2e_value_chain_cli.py:82-95`).
  - Final manifest has a non-null `canary_version` and no pending change cards (`tests/test_e2e_value_chain_cli.py:96-98`).
- Could this pass with a no-op optimizer?
  - Yes.
  - The test never asserts that `optimize` created the candidate that was deployed.
  - A demo workspace that already contains a candidate or any other deployable version would satisfy the test as long as deploy ends with a canary.

### `test_eval_run_defaults_to_workspace_eval_suite`

- What it asserts:
  - `eval run` exits `0`.
  - The latest eval used exactly the 3 workspace case IDs, not hidden package fixtures (`tests/test_e2e_value_chain_cli.py:112-121`).
- Could this pass with a no-op optimizer?
  - Not relevant; this scenario only checks eval routing.

### `test_full_loop_creates_reviewable_candidate_and_improves_after_apply`

- What it asserts:
  - Baseline eval succeeds and points at `configs/v001.yaml` (`tests/test_e2e_value_chain_cli.py:138-143`).
  - Optimize exits `0` and either saved a review card or skipped with "no optimization needed" (`tests/test_e2e_value_chain_cli.py:144-148`).
  - If optimized, one pending card exists and `metrics_after["composite"] > metrics_before["composite"]` (`tests/test_e2e_value_chain_cli.py:150-158`).
  - After `review apply`, a re-eval on `v002` must beat baseline (`tests/test_e2e_value_chain_cli.py:172-185`).
  - Deploy canary and rollback mutate manifest as expected (`tests/test_e2e_value_chain_cli.py:193-212`).
  - A later optimize on an all-pass state prints "no optimization needed" (`tests/test_e2e_value_chain_cli.py:214-216`).
- Could this pass with a no-op optimizer?
  - Yes.
  - The branch at `tests/test_e2e_value_chain_cli.py:146-148` explicitly allows `skipped = "no optimization needed" in optimize_result.output`.
  - If optimize always no-ops, the entire `if optimized:` block is skipped, and the test still passes as long as optimize prints the skip string.

### `test_cli_and_api_review_surfaces_share_pending_and_applied_candidate_state`

- What it asserts:
  - Optimize exits `0`.
  - If optimized, one pending review card and one pending experiment exist and stay in sync across CLI/API surfaces (`tests/test_e2e_value_chain_cli.py:233-270`).
  - Else, it only asserts there are zero review cards (`tests/test_e2e_value_chain_cli.py:271-272`).
- Could this pass with a no-op optimizer?
  - Yes. The `else` branch explicitly blesses total no-op behavior.

### `test_optimize_without_eval_data_guides_user_and_deploy_rejects_active_only_workspace`

- What it asserts:
  - Optimize without eval data exits `0`, tells the user to run eval, and creates no pending cards (`tests/test_e2e_value_chain_cli.py:287-290`).
  - Deploy canary fails in an active-only workspace (`tests/test_e2e_value_chain_cli.py:292-294`).
- Could this pass with a no-op optimizer?
  - Yes; it is explicitly a no-evidence no-op scenario.

### What is not covered

The acceptance harness does **not** cover:

1. The exact loop in this audit: `build -> eval -> optimize --cycles 2 --strategy adaptive -> improve run --auto -> eval -> deploy --auto-review --yes`.
2. A first build in a fresh scratch directory where no manifest/version history exists.
3. The broken packaged entrypoint (`ModuleNotFoundError: agent_card`).
4. `improve run --auto` taking the legacy autofix path and evaluating package-default cases.
5. `improve accept` deploying the wrong candidate when multiple candidate versions exist.
6. Deploy gate behavior on standard `scores.composite` payloads.
7. All-pass / low-quality evals where optimizer should still improve but currently no-ops.
8. Concurrent builds/evals/optimizes writing to "latest" files or manifests.
9. Corrupted `build_artifacts.json`, `manifest.json`, or `eval_results_latest.json`.
10. Failure-cluster variant generation contaminating future eval corpora.

### Acceptance tests that should exist before production trust

1. Exact advertised scratch-dir loop, including `improve run --auto`.
2. First-build-then-deploy in a fresh directory should either produce a versioned candidate or fail loudly before deploy.
3. `improve run --auto` should assert it consumes the preceding optimize attempt, not legacy autofix.
4. Deploy should block on a standard eval payload with `scores.composite < 0.6`.
5. `improve accept <attempt-id>` should deploy the candidate version associated with that attempt, even when newer candidates exist.
6. Optimize should attempt improvement on all-pass-but-low-score suites.
7. Concurrent eval runs should not let `optimize` pick the wrong latest payload.
8. Corrupted `manifest.json` / `eval_results_latest.json` should fail loudly, not silently reinitialize or skip.
9. Failure-variant generation, when enabled, should write only into an explicit training corpus and never into the held-out eval corpus.
10. Live-mode acceptance test with a real agent function or a deterministic owned stub that preserves the same seams but is not `mock_agent_response`.

## 7. Verdict & ranked gap list

VERDICT: do-not-ship-yet

### Top 5 blockers

1. `pyproject.toml:31-80`
   - Gap: packaged CLI omits `agent_card`, so `agentlab` crashes from a clean cwd before any command runs.
   - Fix shape: include `agent_card` in setuptools package discovery and add an import-smoke acceptance test for the installed console script.
   - User-visible failure mode: `agentlab --help` crashes with `ModuleNotFoundError` (`/tmp/agentlab_help.txt:1-16`).
   - Effort: hours.

2. `cli/commands/build.py:171-185` + `cli/commands/deploy.py:708-713`
   - Gap: the first build in a fresh directory writes a plain YAML config, not a versioned manifest entry, so the advertised `deploy --auto-review --yes` step cannot deploy anything and still exits `0`.
   - Fix shape: when `build` creates `.agentlab` in a fresh dir, register the seed config through `ConfigVersionManager` and write `manifest.json`; alternatively make deploy fail nonzero on missing history.
   - User-visible failure mode: exact published loop ends with `No config versions available. Run: agentlab optimize` and no deployment (`/tmp/agentlab-audit.4Vd5RB/deploy.stdout:1`).
   - Effort: days.

3. `cli/commands/improve.py:1140-1175` + `cli/commands/improve.py:106-111` + `evals/runner.py:112-113`
   - Gap: `improve run --auto` with no config path is not the new improve loop; it is the legacy autofix workflow and evaluates the package-default suite.
   - Fix shape: either make zero-arg `improve run` call `run_improve_run_in_process()` against the workspace active config, or reject the invocation with a nonzero error and a precise migration message.
   - User-visible failure mode: users think they are accepting an optimize attempt, but they get an unrelated 55-case legacy diagnosis instead (`/tmp/agentlab-audit.4Vd5RB/improve_run.stdout:1-22`, `/tmp/agentlab-audit-eval-history.txt:2`).
   - Effort: days.

4. `runner.py:1252-1286` + `evals/runner.py:458-480`
   - Gap: optimize only triggers when at least one case fails, even though eval reports richer quality/composite metrics and can mark all cases passed with mediocre scores.
   - Fix shape: derive `needs_optimization` from score thresholds and/or deltas, not only failed-case presence; add a gate on minimum acceptable composite/quality.
   - User-visible failure mode: optimizer says "no optimization needed" for a `0.8818` composite run (`/tmp/agentlab-value.f4kBxM/eval.out:15-24`, `/tmp/agentlab-value.f4kBxM/optimize.out:8-20`).
   - Effort: days.

5. `runner.py:1436-1446`
   - Gap: deploy's degraded-eval gate ignores the standard `scores.composite` shape emitted by `eval run`.
   - Fix shape: reuse `_extract_eval_scores()` inside `_deploy_gate_check()` and add coverage for both envelope shapes.
   - User-visible failure mode: a config with latest eval `scores.composite = 0.4` can still be deployed (`/tmp/agentlab-deploygate.NdsNPt/deploygate.stdout:1-3`), while a synthetic top-level `composite = 0.4` blocks correctly (`/tmp/agentlab-deploygate-top.xiQ71R/deploygate.stderr:1-5`).
   - Effort: hours.

### Top 5 non-blockers worth tracking

1. `cli/commands/improve.py:49-82` + `cli/commands/deploy.py:292-318` + `cli/commands/deploy.py:414-440`
   - `attempt_id` is not a deployment selector, only lineage metadata.

2. `optimizer/failure_analyzer.py:395-557` + `evals/runner.py:160-224`
   - If failure-cluster variant persistence is ever wired on in production, it will contaminate the eval corpus unless an explicit training partition is introduced.

3. `optimizer/loop.py:727-731` + `evals/statistics.py:333-360`
   - Minimum-N significance is advisory only, and multiple-testing correction exists but is unused.

4. `cli/commands/deploy.py:224-243` + `/tmp/agentlab-deploystream.t3SCu9/out.stdout:1-3`
   - Stream-json can emit terminal `status="failed"` while the CLI still exits `0`.

5. `shared/build_artifact_store.py:106-120`
   - Corrupt build-artifact state is silently reinitialized instead of surfaced as operator-facing corruption.
