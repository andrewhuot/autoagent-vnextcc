# R5 Handoff Prompt — Eval Corpus & Dataset Tooling

Paste the block below into a fresh Claude Code session at the repo root
(`/Users/andrew/Desktop/agentlab`).

**Prerequisite:** R1 must be merged. R2 is preferred (R5 adds a
`dataset` command group alongside the R2-extracted `cli/commands/*.py`
layout; doing R5 before R2 means you'd have to port the new command
group during R2's refactor). R5 is **parallel-shippable with R3** — the
two touch mostly disjoint code.

---

## Session prompt

You are picking up the AgentLab roadmap at **R5 — Eval Corpus & Dataset
Tooling**. R1 and R2 have already shipped on master. R3 may or may not
be in flight in parallel — that's fine, R5 and R3 rarely conflict. R5
is its own session for clean context.

### What already shipped (context, don't re-do)

**R1:** strict-live policy, exit codes, rejection records, deploy
verdict gate, provider-key validation.

**R2:** lineage store, `agentlab improve` command group, runner.py
split into `cli/commands/{build,eval,optimize,deploy,improve}.py`.

**R3 (if merged):** coverage-aware proposer, reflection feedback,
configurable composite weights, LLM-backed pairwise judge.

### Your job

Ship **R5** following subagent-driven TDD:

- Fresh subagent per task, full task text + code in the dispatch prompt
- Each subagent uses `uv run pytest` (project requires Python 3.10+)
- Every task: failing test → minimal impl → passing test → conventional commit
- Mark TodoWrite tasks complete immediately; don't batch
- Verify assumptions (file line numbers, function signatures) before
  dispatching

### R5 goal

First-class dataset tooling so the eval corpus can grow beyond the
current 55 cases: importers, exporters, dedupe, balance, bootstrap,
tag-filtered evals, trace ingestion, failure-driven generation.

### Before dispatching anything

1. **Read the R5 scaffold in the master plan** at
   `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md:1350-1397`
   (12 tasks, acceptance tests, risks).

2. **Expand R5 into its own TDD plan file** at
   `docs/superpowers/plans/2026-04-XX-agentlab-r5-eval-corpus.md`.
   Use R1's plan section as the template shape. Commit the plan alone
   (`docs: expand R5 TDD plan`) before any code.

3. **Verify the current state of these files before writing dispatch prompts:**
   - `evals/` — what's the current shape? Is there already a dataset abstraction or just `evals/cases/*.yaml`? How are cases loaded? (Check `evals/runner.py` for the case-loading path.)
   - `evals/trace_converter.py` — exists already; confirm its output shape (what does a converted trace look like?).
   - `optimizer/failure_analyzer.py` — how does it currently cluster failures? The hook for "when cluster found, auto-generate variants" (R5.11) sits here.
   - `cli/commands/eval.py` (from R2) — adding `dataset` as a subgroup vs. a top-level `agentlab eval dataset` group. The master plan says `agentlab eval dataset <subcommand>` — confirm the command group nesting fits the R2 layout.
   - Is there already a case-generator module? If yes, R5.5 extends it rather than creating parallel code.

4. **Split R5 into three dispatchable slices.** Don't try to ship all
   12 tasks in one session.

   - **Slice A — Import/export foundation** (R5.1–R5.4): JSONL
     importer, CSV importer, HuggingFace importer, exporters with
     round-trip tests. Additive; unblocks the rest.
   - **Slice B — Dedupe/balance/bootstrap + embedder** (R5.5–R5.8):
     pluggable embedder interface, bootstrap with diversity sampling,
     dedupe, balance. These share the embedder so land them together.
   - **Slice C — Tag filtering + trace ingestion + failure-driven
     generation** (R5.9–R5.11): `--tag`, `--exclude-tag`, `eval ingest
     --from-traces`, failure cluster → auto-generate variants with
     `generated_from: failure_cluster:<id>` tag.

   R5.12 (docs) comes after Slice C.

5. **Confirm with the user which slice to start with.** Default to Slice A.

### Critical invariants R5 must preserve

- **Round-trip is lossless.** Import → export → import must yield
  identical cases (acceptance test R5.4 explicitly requires this).
  That includes tags, metadata, case ids. Test with a
  golden-file: a known JSONL, round-tripped twice, bit-identical.
- **Embedder is pluggable, not OpenAI-locked.** R5.6 ships the OpenAI
  `text-embedding-3-small` default, but the interface must accept any
  callable `list[str] -> list[list[float]]`. Tests must cover a fake
  in-memory embedder so CI doesn't need a provider key.
- **Embedding cost is bounded.** Cache `(text_hash, model) → embedding`
  in `.agentlab/embedding_cache.db` with a long TTL (90 days default).
  `dataset dedupe --threshold 0.95` on a 1000-case set must not cost
  more than ~$0.02 in embeddings (rough budget).
- **Offline fallback for HuggingFace** (R5.3). If the HF download
  fails, surface a clear error with the `datasets` library's cache
  path hint — don't silently fall back to an empty dataset.
- **Trace ingestion privacy** (R5.10). Before writing any ingested
  trace to disk, surface a redaction confirmation step — enumerate the
  PII-shaped fields (emails, tokens, addresses) and require `--yes`
  or an interactive prompt. Default to redact, not pass-through.
- **Failure-driven generation tagging** (R5.11). Every auto-generated
  case MUST carry `generated_from: failure_cluster:<id>` metadata.
  Downstream code that filters out generated cases relies on this tag.
- **Strict-live still applies.** If `dataset bootstrap` uses an LLM
  to generate cases and `--strict-live` is set, missing provider key
  is a hard failure, not silent fallback.

### Architectural decisions the master plan defers to you

- **Importer interface shape:** a common `load(path) -> Iterator[Case]`
  protocol; each format implements it. Don't over-abstract — three
  importers is fine with three functions.
- **Embedder interface:** one method, `embed(texts: list[str]) ->
  list[list[float]]`. No batching exposed to callers; implementers
  handle their own batching.
- **Dedupe algorithm:** cosine similarity ≥ threshold → mark as
  duplicate. For N cases, compute pairwise with a vectorized matmul;
  if that's too expensive above some N (say 10k), bucket by
  locality-sensitive hashing. Start simple.
- **Balance definition:** the master plan says "category histogram +
  rebalance recommendations." A "category" defaults to the `tag` field;
  if cases have no tags, fall back to input-length-bucketing. The
  rebalance step outputs recommendations (cases to add/remove per
  category), doesn't auto-mutate — user approves.
- **Bootstrap diversity metric:** embed candidate cases, pick next
  case to maximize minimum distance to already-selected set (farthest-
  point sampling). Cheap and effective.
- **Trace conversion shape:** if `evals/trace_converter.py` already
  defines a converter, wire it up verbatim. Don't rewrite the
  converter as part of R5.10 — just surface it through
  `agentlab eval ingest --from-traces`.
- **Failure cluster → variant generation (R5.11):** when
  `failure_analyzer` finds a cluster of N≥3 failures, call the case
  generator with the cluster's representative case + failure mode as a
  prompt, generate 3–5 variants tagged `generated_from:
  failure_cluster:<id>`. Variants go through the normal eval pipeline.

### Workflow

1. Create a new worktree:
   `git worktree add .claude/worktrees/<r5-name> -b claude/r5-eval-corpus master`
2. Follow `superpowers:subagent-driven-development` — dispatch one
   subagent per task, don't implement in the main thread.
3. After each slice, offer to open a PR before moving to the next.
4. If R3 is in flight in parallel, coordinate on `evals/scorer.py` /
   `evals/statistics.py` touch points — those are R3's turf.

### If you get stuck

- Stale line numbers in the master plan: verify with `Read` before dispatching.
- Subagent hits Python 3.9 on the host: tell it to use `uv run python` / `uv run pytest`.
- HuggingFace auth errors in CI: skip the HF importer test on CI
  with `@pytest.mark.skipif(not os.getenv("HF_TOKEN"))` or use a
  local fixture dataset.
- Embedding cost spikes in tests: confirm the test embedder is the
  fake in-memory one, not the OpenAI default. Tests should never
  hit a real provider.
- Pre-existing failing tests (starlette/httpx collection errors in API
  tests): note them and move on — not R5's problem.

### First action

After the user confirms they want to start, read the master plan's R5
section, read the `evals/` files listed above to ground-truth
assumptions, write the expansion plan, commit it, then ask which slice
(A/B/C) to execute first.

Use superpowers and TDD. Work in subagents. Be specific.
