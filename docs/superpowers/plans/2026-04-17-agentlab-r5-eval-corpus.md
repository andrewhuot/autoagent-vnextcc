# R5 — Eval Corpus & Dataset Tooling (TDD expansion plan)

**Status:** shipped on 943e551 (2026-04-17)
**Branch:** `claude/r5-eval-corpus` (off `master` at `777df64`)
**Depends on:** R1 (strict-live), R2 (modular `cli/commands/`). Parallel-
shippable with R4.
**Master plan section:** `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md:1350-1397`

## 0. Goal

After R5, the eval corpus is a first-class dataset: importable from
JSONL/CSV/HuggingFace, exportable losslessly, de-duplicatable, balanceable,
bootstrappable to hundreds of cases, tag-filterable at eval time,
extendable from production traces, and auto-grown when the failure
analyzer finds a cluster the optimizer cannot fix with prompt surgery
alone.

```
agentlab eval dataset import cases.jsonl   → 100 new cases
agentlab eval dataset export --format csv  → lossless round-trip
agentlab eval dataset dedupe --threshold 0.95
agentlab eval dataset balance --by category
agentlab eval dataset bootstrap --target 200 --card configs/card.yaml
agentlab eval ingest --from-traces traces.jsonl   → redaction prompt → N cases
agentlab eval run --tag safety --exclude-tag slow
# failure_analyzer finds a cluster → auto-generates 3–5 variants
#   tagged `generated_from: failure_cluster:<id>`
```

## 1. Architectural decisions

### 1.1 "Tag" is a new metadata field; `category` stays as-is

`TestCase` at `evals/runner.py:31` has `category: str` but no `tags`. The
master plan says "tag-based eval filtering." Two options:

- **(Rejected)** Alias `category` to `tags`. Breaks the single-category
  assumption in `run_category()` (`evals/runner.py:497`) and several
  scorers that pivot on `case.category`.
- **(Chosen)** Add `tags: list[str] = field(default_factory=list)` to
  `TestCase`. Cases without tags default to `[category]` at load time
  so existing filters like `--category safety` keep working, and
  `--tag safety` matches them too. New YAML/JSONL/CSV schemas read an
  optional `tags` field; no existing YAML needs rewriting.

`--tag X` = case matches if `X in case.tags`. `--exclude-tag Y` =
reject if `Y in case.tags`. Multiple `--tag` flags OR together.
Multiple `--exclude-tag` flags AND together (reject if any match).

### 1.2 Dataset abstraction stays thin

Don't introduce a `Dataset` class on top of `list[TestCase]`. The three
importers are free functions returning `list[TestCase]`. The exporters
are free functions taking `list[TestCase]` and a path. The CLI glues
them to the case store.

Canonical on-disk form is the existing YAML under `evals/cases/*.yaml`.
Import writes new YAML files into `evals/cases/` (or a user-specified
dir). Export reads from the case dir and emits the requested format.
This keeps the "cases live in version control" contract from R0.

### 1.3 Round-trip invariant: JSONL is the golden format

YAML round-trips are fragile (key order, quoting, multi-line strings).
JSONL is stable enough for a bit-identical golden file test.

Acceptance path:
1. Start from a curated `tests/evals/fixtures/golden_cases.jsonl` (N=20
   cases covering every `TestCase` field + tags + metadata).
2. Import → write YAML into a temp dir.
3. Export from that dir as JSONL.
4. Assert the exported JSONL equals the golden file byte-for-byte after
   canonical ordering: keys sorted, `tags` sorted, trailing newline.

Field order inside each JSON object is the canonical sort of keys so
dict insertion order drift doesn't break the test.

YAML and CSV round-trips are tested semantically (parse both sides,
compare `TestCase` equality) rather than byte-for-byte. Only JSONL
gets the golden-file check.

### 1.4 Embedder interface: one method, lazy batching

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Batching is an implementation detail; the OpenAI impl batches in chunks
of 100, the fake in-memory impl doesn't batch. Callers pass `list[str]`
and get back same-length `list[list[float]]`.

Ships with three implementations:
- `FakeEmbedder` — deterministic, hashes text into a fixed-dim vector.
  Used by default in tests. Zero network.
- `OpenAIEmbedder` — wraps `text-embedding-3-small`, 1536 dims. Used by
  default at runtime when `OPENAI_API_KEY` is set.
- `CachedEmbedder(inner: Embedder, db_path: str)` — decorator that
  caches `(sha256(text), model_name) → vector` in SQLite. 90-day TTL.

At runtime the default embedder is
`CachedEmbedder(OpenAIEmbedder(...), ".agentlab/embedding_cache.db")`.
Override via `EvalRunner(embedder=...)` or a new `AGENTLAB_EMBEDDER=fake`
env knob for CI.

### 1.5 Dedupe: pairwise cosine with small-N simple path

For N ≤ 2000 cases compute full pairwise cosine via NumPy matmul on
normalized vectors (`V @ V.T`). For N > 2000, bucket by MinHash-LSH
before the matmul — but **R5 ships only the simple path**. LSH is
deferred to R5-followup; document the N-cap in help text so users know
what they're getting.

Two cases are duplicates when `cos_sim >= threshold`. Duplicate
resolution: keep the case with the longer `reference_answer`, breaking
ties by earlier `id` (lexicographic). The removed case's id is logged.

### 1.6 Balance = report, not mutate

`dataset balance --by tag` (or `--by category`, default: `category`)
prints a histogram and a recommendation of how many cases to add/remove
per bucket to reach parity with the median bucket. It does **not**
auto-delete or auto-generate. User eyeballs, then runs
`dataset bootstrap --target <N> --tag <bucket>` to fill a gap.

### 1.7 Bootstrap = card generator + farthest-point diversity sampling

Re-uses `evals/card_case_generator.py:CardCaseGenerator` (R3-era, 743
LOC). The new piece is only the sampling wrapper:

```
candidates = card_case_generator.generate_all(card, oversample=3*target)
seed = candidates[0]
selected = [seed]
while len(selected) < target:
    embeddings = embedder.embed([c.user_message for c in candidates])
    # pick candidate maximizing min-distance to selected
    selected.append(argmax_min_distance(candidates, selected, embeddings))
```

Embeddings are computed once up-front (N=3*target calls, cached).
Distance metric: `1 - cos_sim`.

### 1.8 Trace ingestion: redaction confirmation is not optional

`TraceToEvalConverter` already exists at `evals/trace_converter.py:16`.
R5 only adds a CLI surface + redaction prompt. Before any converted
case is persisted:

1. Scan text fields for regex-matched PII: email, phone, credit-card,
   bearer-token, IPv4, path-like tokens containing `/home/` or `/Users/`.
2. Print a per-trace summary of hits, grouped by field.
3. Require `--yes` to auto-accept, or an interactive `[y/N]` when TTY.
4. Default (no flag, no TTY, e.g. CI) is **abort with exit code 20** —
   never write redacted-or-unredacted data without a human saying yes.
5. The actual redaction replaces each hit with `<REDACTED:kind>` and
   writes **only the redacted form**. There is no "pass-through" mode.

### 1.9 Failure-driven generation: tag, don't overwrite

`optimizer/failure_analyzer.py:FailureAnalyzer.analyze()` returns
`FailureAnalysis` with `clusters: list[FailureCluster]`. R5 adds an
optional `case_generator: CardCaseGenerator | None` param. When passed
and a cluster has `size >= 3`, call
`case_generator.generate_variants_from_cluster(cluster)` and tag each
output with `generated_from: failure_cluster:<cluster.id>`.

Generated cases are emitted to `evals/cases/generated_failures.yaml`
(append-only, de-duplicated by id). They flow through the normal eval
pipeline on next run. Any downstream code that wants to exclude
generated cases filters by `--exclude-tag generated_from`.

### 1.10 Strict-live applies to bootstrap and failure-driven generation

If `--strict-live` is set anywhere in the call chain, missing
`OPENAI_API_KEY` (or equivalent provider key) during bootstrap or
variant generation is a hard failure (exit 13), not a silent fallback
to heuristic generation. Mirrors R1 semantics.

## 2. File map

| File | Status | Why |
|---|---|---|
| `cli/commands/dataset.py` | **Create** | `agentlab eval dataset <sub>` group |
| `evals/dataset/__init__.py` | **Create** | package marker |
| `evals/dataset/importers.py` | **Create** | JSONL/CSV/HF importers |
| `evals/dataset/exporters.py` | **Create** | JSONL/CSV exporters |
| `evals/dataset/dedupe.py` | **Create** | cosine dedupe |
| `evals/dataset/balance.py` | **Create** | histogram + recommendations |
| `evals/dataset/bootstrap.py` | **Create** | farthest-point sampling wrapper |
| `evals/dataset/embedder.py` | **Create** | Embedder protocol + Fake + OpenAI + Cached |
| `evals/dataset/redact.py` | **Create** | PII regex scan + replace |
| `evals/runner.py` | **Modify** | add `tags` to `TestCase`; `--tag`/`--exclude-tag` filter; `AGENTLAB_EMBEDDER` env |
| `evals/trace_converter.py` | **Read-only** | wire verbatim through CLI |
| `cli/commands/eval.py` | **Modify** | register dataset subgroup; `--tag`/`--exclude-tag`/`ingest --from-traces` flags |
| `optimizer/failure_analyzer.py` | **Modify** | accept optional `case_generator`; call for size≥3 clusters |
| `evals/card_case_generator.py` | **Modify** | add `generate_variants_from_cluster()` |
| `tests/evals/fixtures/golden_cases.jsonl` | **Create** | 20-case golden file for round-trip |
| `docs/evals/dataset-tooling.md` | **Create** | R5.12 user-facing guide |

## 3. Slice plan

R5 ships in three slices. Each ends with a green test suite and an
optional PR.

### Slice A — import/export foundation (R5.1–R5.4)

**Goal:** cases can flow in and out of AgentLab losslessly.

| # | Task | Test first |
|---|---|---|
| A.1 | `tags` field on `TestCase`; load-time default to `[category]`. | `test_testcase_tags_default_to_category`, `test_testcase_tags_explicit` |
| A.2 | `evals/dataset/importers.py:load_jsonl(path) -> list[TestCase]`. | `test_load_jsonl_20_cases`, `test_load_jsonl_missing_field_raises`, `test_load_jsonl_infers_tags` |
| A.3 | `importers.py:load_csv(path)`. | `test_load_csv_round_trip_fields`, `test_load_csv_empty_tags_ok` |
| A.4 | `importers.py:load_huggingface(name, split, cache_dir)`. Offline: clear error with cache-path hint. | `test_load_hf_with_local_fixture_dataset`, `test_load_hf_network_error_messages_cache_dir`. HF network test gated on `HF_TOKEN` env. |
| A.5 | `evals/dataset/exporters.py:export_jsonl(cases, path)` + `export_csv`. Canonical key order; sorted `tags`; trailing newline. | `test_export_jsonl_matches_golden_file_bytes`, `test_export_csv_round_trip` |
| A.6 | `cli/commands/dataset.py`: `eval dataset import/export` commands. | `test_cli_import_jsonl_persists_cases`, `test_cli_export_csv_round_trips` |
| A.7 | **Acceptance:** golden-file round-trip: import `golden_cases.jsonl` → export → byte-identical. | `test_jsonl_round_trip_bit_identical` |

Commit style (one per task):
- `feat(evals): add tags field to TestCase with category fallback`
- `feat(evals): JSONL importer for cases`
- …
- `test(evals): golden-file JSONL round-trip`

### Slice B — embedder + dedupe + balance + bootstrap (R5.5–R5.8)

**Goal:** scale the corpus intelligently.

| # | Task | Test first |
|---|---|---|
| B.1 | `evals/dataset/embedder.py`: `Embedder` Protocol + `FakeEmbedder` + `OpenAIEmbedder` + `CachedEmbedder`. | `test_fake_embedder_deterministic`, `test_cached_embedder_hits_cache_on_second_call`, `test_cached_embedder_respects_ttl`, `test_openai_embedder_batches` (mock SDK) |
| B.2 | `evals/dataset/dedupe.py:dedupe(cases, embedder, threshold) -> (kept, dropped_ids)`. Keeps longer `reference_answer`. | `test_dedupe_identical_texts_removed`, `test_dedupe_below_threshold_kept`, `test_dedupe_keeps_longer_reference_answer`, `test_dedupe_logs_dropped_ids` |
| B.3 | `cli/commands/dataset.py:dedupe` subcommand. | `test_cli_dedupe_dry_run`, `test_cli_dedupe_applies` |
| B.4 | `evals/dataset/balance.py:histogram(cases, by) -> dict` + `recommendations(hist) -> list[str]`. | `test_balance_histogram_default_by_category`, `test_balance_recommendations_targets_median` |
| B.5 | `cli/commands/dataset.py:balance` subcommand. | `test_cli_balance_prints_histogram` |
| B.6 | `evals/dataset/bootstrap.py:bootstrap(card, target, embedder, generator)` via farthest-point sampling. | `test_bootstrap_fps_selects_diverse`, `test_bootstrap_respects_target`, `test_bootstrap_strict_live_requires_key` |
| B.7 | `cli/commands/dataset.py:bootstrap` subcommand. | `test_cli_bootstrap_writes_yaml` |
| B.8 | **Acceptance:** dedupe known-duplicated set → expected count. | `test_acceptance_dedupe_known_duplicates` |

### Slice C — tag filtering + trace ingestion + failure-driven (R5.9–R5.11)

**Goal:** close the loop from production signal to new eval cases.

| # | Task | Test first |
|---|---|---|
| C.1 | `EvalRunner.load_cases(tags=[...], exclude_tags=[...])`. | `test_load_cases_filters_by_tag`, `test_load_cases_excludes_tag`, `test_load_cases_tag_or_semantics`, `test_load_cases_exclude_tag_and_semantics` |
| C.2 | `eval run --tag/--exclude-tag` CLI. | `test_cli_eval_run_tag_filter`, `test_cli_eval_run_exclude_tag_filter` |
| C.3 | `evals/dataset/redact.py:scan(text) -> list[Hit]` + `redact(text, hits) -> str`. | `test_redact_email`, `test_redact_bearer_token`, `test_redact_path_in_user_home`, `test_redact_idempotent` |
| C.4 | `cli/commands/eval.py:ingest --from-traces <path>` wiring `TraceToEvalConverter` + redaction prompt. | `test_cli_ingest_redaction_abort_without_yes_in_noninteractive`, `test_cli_ingest_yes_writes_redacted_cases`, `test_cli_ingest_exit_20_on_unapproved` |
| C.5 | `CardCaseGenerator.generate_variants_from_cluster(cluster)` — 3–5 variants; each tagged. | `test_generate_variants_returns_3_to_5`, `test_generate_variants_tag_format`, `test_generate_variants_strict_live_no_key_raises` |
| C.6 | `FailureAnalyzer.analyze(..., case_generator=...)`: size≥3 cluster → variants appended to `evals/cases/generated_failures.yaml`. | `test_failure_analyzer_skips_small_clusters`, `test_failure_analyzer_tags_generated_cases`, `test_failure_analyzer_appends_idempotent` |
| C.7 | **Acceptance:** import 200 cases → `eval run --tag safety` → only safety cases run. | `test_acceptance_tag_filter_200_cases` |

### R5.12 — Documentation

`docs/evals/dataset-tooling.md` covering: every command, the embedder
plug points, the redaction flow, the failure-driven tag contract, the
strict-live contract, and the N-cap on dedupe.

## 4. Invariants (verified by tests)

1. **JSONL round-trip is byte-identical** (§1.3, test A.7).
2. **Embedder is pluggable** — tests never hit OpenAI (§1.4, test B.1).
3. **Embedding cost bounded** — `CachedEmbedder` skips on TTL-valid hit
   (§1.4, test B.1).
4. **HF offline fallback** is a clear error, not silent empty (§1.4,
   test A.4).
5. **Trace ingestion redacts-or-aborts** — exit 20 on no-consent (§1.8,
   test C.4).
6. **Failure-driven cases carry the cluster tag** (§1.9, test C.6).
7. **Strict-live kills silent fallback** (§1.10, tests B.6, C.5).

## 5. Risks and mitigations

- **Stale `runner.py` references** (line 31 for TestCase, 497 for
  run_category). Verify with `Read` before modifying.
- **`cli/commands/eval.py` is long (911 lines)**. Dataset subgroup
  belongs in its own module (`cli/commands/dataset.py`) registered from
  `eval.py`. Don't expand `eval.py` further.
- **`evals/cases/` only has 3 YAML files today** (55 cases total across
  them). Don't assume 55 files; assume few, large, categorized YAML.
- **`TraceToEvalConverter.convert()` returns a dict, not `TestCase`**
  (`trace_converter.py:38-90`). CLI glue must convert dict → TestCase
  via the same mapper importers use.
- **Pre-existing test collection failures** (starlette/httpx in API
  tests) are not R5's problem — record and skip.

## 6. Out of scope for R5

- LSH bucketing above N=2000 (deferred, documented in help text).
- Auto-mutate balance (user approves bootstrap; balance is advisory).
- Full daemon-mode trace ingestion (that's R6.1–R6.3).
- Generic `Dataset` abstraction on top of `list[TestCase]` — the thin
  free-function shape is deliberate.
