# Eval Dataset Tooling

## Overview

R5 promotes the eval corpus from a stash of hand-written YAML to a first-class
dataset with importers (JSONL, CSV, HuggingFace), lossless exporters,
cosine-similarity dedupe, category/tag balance reports, card-driven bootstrap,
tag filtering at run time, trace ingestion with mandatory PII redaction, and
auto-generation of regression cases from failure clusters. Everything lives
under the `agentlab eval dataset` subgroup, with trace ingestion on
`agentlab eval ingest` and tag filters on the pre-existing `agentlab eval run`.

## Quick reference

| Command | Purpose |
|---|---|
| `agentlab eval dataset import` | Load JSONL, CSV, or HuggingFace cases into `evals/cases/*.yaml`. |
| `agentlab eval dataset export` | Dump YAML cases to JSONL or CSV. |
| `agentlab eval dataset dedupe` | Remove near-duplicates by cosine similarity (N ≤ 2000). |
| `agentlab eval dataset balance` | Print a histogram + rebalance recommendations. Read-only. |
| `agentlab eval dataset bootstrap` | Farthest-point sample a diverse set of cases from an Agent Card. |
| `agentlab eval ingest --from-traces` | Convert production JSONL traces into YAML cases with mandatory PII redaction. |
| `agentlab eval run --tag / --exclude-tag` | Filter the run to cases carrying (or not carrying) the given tags. |

## Import / export

### Import

```bash
agentlab eval dataset import cases.jsonl
agentlab eval dataset import cases.csv --output evals/cases
agentlab eval dataset import my/hf-set --format hf --dataset-name my_cases --hf-split train
```

- Format is inferred from the file extension (`.jsonl`, `.ndjson`, `.csv`);
  HuggingFace loads require an explicit `--format hf` and a `--dataset-name`.
- Output YAML lands at `<output>/<stem>.yaml` (default output dir is
  `evals/cases`).
- `--force` replaces an existing file; without it, the CLI refuses to
  overwrite.

### Export

```bash
agentlab eval dataset export out.jsonl
agentlab eval dataset export out.csv --source evals/cases
```

- Canonical JSONL form: keys sorted within each object, `tags` list sorted,
  trailing newline at end of file.
- `import → export` of a JSONL source is **byte-identical** against the
  golden file (guarded by `test_jsonl_round_trip_bit_identical`).
- CSV round-trip is semantic — parse both sides, compare `TestCase` equality.

## Embedder plug points

Dedupe and bootstrap both need embeddings. The `Embedder` protocol is one
method:

```python
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Three implementations ship:

- `FakeEmbedder` — deterministic hash-to-vector, no network. The test
  default.
- `OpenAIEmbedder` — wraps `text-embedding-3-small`, 1536 dims, batches in
  chunks of 100.
- `CachedEmbedder(inner, db_path)` — SQLite-backed cache keyed on
  `(sha256(text), model_name)` with a 90-day TTL.

The runtime default is
`CachedEmbedder(OpenAIEmbedder(), ".agentlab/embedding_cache.db")`. Tests and
CI opt out by setting:

```bash
export AGENTLAB_EMBEDDER=fake
```

`FakeEmbedder` then replaces the default; no provider key is needed and no
HTTP call is made.

## Dedupe

Pairwise cosine similarity on normalized embeddings. Two cases are
duplicates when `cos_sim >= threshold`. When both members of a pair are
duplicates the keeper is the case with the longer `reference_answer`;
lexicographic `id` breaks ties. Dropped ids are logged to stdout as
`keeper <- dropped (sim=0.987)`.

```bash
agentlab eval dataset dedupe --source evals/cases --dry-run
agentlab eval dataset dedupe --threshold 0.95
agentlab eval dataset dedupe --output deduped.yaml --force
```

- `--dry-run` prints the report and exits without touching YAML.
- Without `--output`, dedupe rewrites each source YAML in place. A file
  whose cases are all dropped is deleted.
- With `--output`, all surviving cases are written to one YAML at that path.
- **N ≤ 2000 cap.** Above that size the current simple path (full
  `V @ V.T` matmul) is rejected; LSH bucketing is deferred to a follow-up
  release.

## Balance

Read-only analysis — prints a histogram and a rebalance recommendation
targeting the median bucket size. Never mutates.

```bash
agentlab eval dataset balance
agentlab eval dataset balance --by tag
agentlab eval dataset balance --json
```

- `--by category` (default) groups on `case.category`; buckets are disjoint.
- `--by tag` groups on `case.tags`; a case with three tags appears in three
  buckets, so the total across buckets exceeds the number of cases.
- `--json` emits
  `{"by", "histogram", "median", "recommendations"}` for scripting.

Default text output:

```
Balance by category (median: 12)
  code          12  (at median)
  safety         8  [+4]
  tool_use     18  [-6 recommended]
Recommendations:
  Add 4 cases to 'safety' to reach median (12).
```

## Bootstrap

Farthest-point sampling over `CardCaseGenerator` candidates seeded from an
Agent Card. Oversamples 3× the target, embeds every candidate once, then
iteratively picks the candidate whose minimum cosine distance to the
already-selected set is largest. The seed is always `candidates[0]`.

```bash
agentlab eval dataset bootstrap --card .agentlab/agent_card.md --target 50
agentlab eval dataset bootstrap --card ./my_agent_dir --target 20 --force
agentlab eval dataset bootstrap --card card.md --target 10 --output diverse.yaml --strict-live
```

- `--card` accepts a markdown file or a workspace directory.
- `--target` clamps down when the generator can't produce that many unique
  candidates; the command succeeds with a smaller set.
- `--output` defaults to `evals/cases/bootstrapped.yaml`.
- `--strict-live` — see the strict-live contract below.

## Tag filtering (`eval run`)

Tags live on each `TestCase`. Cases without an explicit `tags` list inherit
`[category]` at load time, so the new flags work against YAML written before
R5.

```bash
agentlab eval run --tag safety
agentlab eval run --tag safety --tag security
agentlab eval run --exclude-tag slow
agentlab eval run --tag safety --exclude-tag generated_from:failure_cluster:2
```

Semantics:

- `--tag X` matches `case.tags` (not `case.category`). Multiple `--tag`
  flags OR together: a case matches if **any** flag matches.
- `--exclude-tag Y` drops a case when **any** exclude matches.
- Matching is case-sensitive.
- `--category` still matches `case.category` exactly and is independent of
  `--tag`.

## Trace ingestion & redaction

`agentlab eval ingest --from-traces` converts a JSONL file of production
traces into YAML cases. Redaction is mandatory — there is no pass-through
mode.

```bash
agentlab eval ingest --from-traces traces.jsonl --yes
agentlab eval ingest --from-traces traces.jsonl --max-cases 10
agentlab eval ingest --from-traces traces.jsonl --expected-output "Helpful answer" --force
```

### Redaction scan

Every string field (including strings nested inside lists and dicts) is
scanned for six PII kinds: `EMAIL`, `PHONE`, `CREDIT_CARD`, `BEARER_TOKEN`,
`IPV4`, `USER_PATH` (`/home/<user>` or `/Users/<user>`). Each hit is
rewritten to `<REDACTED:KIND>`. Redaction is one-way and idempotent —
re-running it on already-redacted text is a no-op.

### Consent flow

1. The CLI prints a per-kind hit summary before touching the disk.
2. `--yes` auto-accepts the redaction.
3. On an interactive TTY, the user is prompted with `[y/N]` (default No).
4. Non-interactive runs without `--yes` **exit 20** — the output YAML is
   never written and the error goes to stderr.

### Flags

- `--output` — destination YAML (default: `evals/cases/ingested_traces.yaml`).
- `--max-cases` — cap on traces to convert (default 30).
- `--expected-output` — override the expected output field on every case.
- `--force` — overwrite an existing output YAML.

## Failure-driven case generation

`FailureAnalyzer.analyze()` accepts an optional `case_generator` argument.
When passed a `CardCaseGenerator`, any cluster with
`size >= min_cluster_size` (default 3) triggers
`case_generator.generate_variants_from_cluster(cluster)` — 3-5 variants per
cluster.

Variants are written append-only to
`evals/cases/generated_failures.yaml`, each tagged
`generated_from:failure_cluster:<cluster_id>`. Idempotent — re-running
against the same clusters does not duplicate cases (dedupe on id).

To exclude the auto-generated cases from a later run:

```bash
agentlab eval run --exclude-tag "generated_from:failure_cluster:2"
```

## Strict-live contract

`--strict-live` (on both `eval dataset bootstrap` and any path that invokes
`CardCaseGenerator.generate_variants_from_cluster`) raises `RuntimeError`
when an LLM router is attached but no provider key is present in the
environment. Mirrors R1 semantics — silent fallback to heuristic generation
is never allowed under strict-live.

## Invariants at a glance

1. JSONL round-trip is byte-identical against the golden file.
2. The embedder is pluggable — tests never hit OpenAI.
3. Embedding cost is bounded via `CachedEmbedder` TTL (90 days).
4. HuggingFace offline fallback is a clear error, not a silent empty
   dataset.
5. Trace ingestion redacts-or-aborts; no-consent non-interactive runs
   exit 20.
6. Failure-driven cases always carry the `generated_from:failure_cluster:…`
   tag.
7. Strict-live kills silent fallback on bootstrap and variant generation.

## Out of scope / deferred

- MinHash-LSH bucketing above N=2000 for dedupe (the simple path refuses
  above the cap).
- Auto-mutate balance (balance is advisory; user runs bootstrap to fill).
- Daemon-mode trace ingestion — R6 covers the continuous-loop work.
- A generic `Dataset` class on top of `list[TestCase]` — the thin
  free-function shape is deliberate.
