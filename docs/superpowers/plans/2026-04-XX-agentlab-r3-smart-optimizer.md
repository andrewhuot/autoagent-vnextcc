# R3 — Optimizer that Learns (TDD expansion plan)

**Status:** draft, ready for execution
**Branch:** `claude/r3-smart-optimizer` (off `master` at `6a0f242`)
**Depends on:** R1 (strict-live) and R2 (lineage store, modular `cli/commands/`)
**Master plan section:** `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md:1243-1292`

## 0. Goal

After R3, the optimizer targets under-tested surfaces with past-effective
strategies, grows its own eval suite when coverage goes thin, scores with
an LLM-backed pairwise judge (cached), and reports calibrated significance
— all with workspace-configurable composite weights that stay reproducible
across weight changes.

```
agentlab optimize --explain-strategy configs/my-agent.yaml
  → coverage gap signal injected into proposer prompt
  → strategy picked via reflection (epsilon-greedy 10%)
  → card_case_generator auto-runs when any surface <30% coverage
  → pairwise judge uses LLM with cache + heuristic fallback
  → composite score annotates weights_snapshot for historical reproducibility
  → paired_significance() reports bootstrap CI and calibrated effect size

agentlab eval weights show | set quality 0.45 safety 0.20 | validate
```

## 1. Architectural decisions

### 1.1 Do NOT migrate the `surface_effectiveness` schema in R3

Master scaffold proposed `surface_effectiveness(surface, strategy,
effectiveness_score, sample_count, updated_at)`. Real schema today
(`optimizer/reflection.py`) is `(surface, attempts, successes,
total_improvement, last_attempted)` — **no `strategy` column**.

**Decision:** R3 ranks strategies by *surface-level* effectiveness. A
strategy whose target surface has high surface-level effectiveness ranks
higher. This preserves the intent of R3.4 without a schema migration.
Strategy-level reflection is deferred (§5 appendix).

Concretely:
- `Reflection.read_surface_effectiveness(surface) -> SurfaceEffectiveness
  | None` — a thin wrapper that queries the existing table.
- `Proposer._rank_strategies(available_strategies, reflection_engine,
  epsilon, rng)` — maps each available strategy to its *target surface*
  via a small static `STRATEGY_TO_SURFACE` table, then ranks by that
  surface's `avg_improvement`. Ties broken by sample count, then name.

No `ALTER TABLE`. No migration script. A separate R-slice will upgrade the
schema once we have enough per-strategy data to make the dimension
meaningful.

### 1.2 Epsilon-greedy is the only defense against runaway feedback

`_rank_strategies(epsilon=0.1)` returns a *random* ordering with
probability `epsilon`. Tests seed `random.Random(42)` so the exploration
branch is deterministic. The epsilon value is a parameter, not a
constant, so workspace yaml can override later.

### 1.3 LLM pairwise judge: cache wired in the same commit as the LLM path

Splitting "add LLM path" from "add cache" would ship a turn where every
judgment hits the wire. **Decision:** R3.7 lands LLM path + cache
together. Tests assert that a second identical call does not touch the
router (mock with `call_count`).

Cache key: `sha256(f"{input_a}|{input_b}|{output_a}|{output_b}")`.
Cache store: SQLite at `.agentlab/llm_judge_cache.db`, schema
`(cache_key TEXT PRIMARY KEY, verdict_json TEXT, created_at REAL)`, TTL
30 days enforced on read.

Fallback semantics:
- `llm_router is None` → heuristic path (current behavior).
- `llm_router` set, call fails or schema validation fails, `strict_live=False`
  → fall back to heuristic.
- `strict_live=True` and any failure → `RuntimeError` (mirrors R1 exit
  code 13 contract; CLI test asserts).

### 1.4 Composite weights: yaml + per-run snapshot, method kwargs already parameterized

`CompositeScore.weighted_breakdown()` already takes weights as kwargs
(line 158 of `evals/scorer.py`) — we do not change that. We add:
- `evals/composite_weights.py::CompositeWeights` dataclass + loader.
- `CompositeScorer.__init__(weights: CompositeWeights | None = None)`,
  defaulting to current class constants so all existing call sites keep
  working.
- `CompositeScore.weights_snapshot: CompositeWeights | None` populated by
  `CompositeScorer.score()`. When an eval run is re-rendered from persisted
  results, the render uses `weights_snapshot`, not current yaml.

### 1.5 CLI subcommand on existing `eval.py`, NOT new `eval_weights.py`

Master scaffold says "Create `cli/commands/eval_weights.py`." Deviation:
add `agentlab eval weights {show|set|validate}` as a subcommand group on
the existing `cli/commands/eval.py`. Rationale: the `eval` noun already
owns that module; splitting it creates an artificial third file when
`weights` is a sub-noun of `eval`. Help output and discoverability improve.

### 1.6 `paired_significance()` CI is separate from `_bootstrap_mean_ci()`

`CompositeScorer._bootstrap_mean_ci()` already computes per-metric
bootstrap CIs (line 309 of `evals/scorer.py`) and attaches them to
`CompositeScore.confidence_intervals`. **R3.12 is NOT about duplicating
that.** R3.12 adds a *paired* bootstrap CI to
`SignificanceResult.confidence_interval` in `evals/statistics.py`,
resampling pairs (not metrics) with replacement. Pattern follows the
existing `ClusteredBootstrapResult` shape at line 105.

### 1.7 Auto card_case_generator hook site

`optimizer/loop.py:368` is `proposal = self.proposer.propose(...)`. The
R3.6 hook sits *immediately before* that call, after the coverage report
is available, so proposals can react to newly-grown cases. The hook is
guarded by a `auto_grow_cases=True` constructor flag so tests that don't
care can disable it.

### 1.8 Lineage: R3 emits no new event types

All new observability (strategy explanation, coverage gap, weights
snapshot) rides on the existing `attempt` event payload — consistent with
R2's "payload-only, never ALTER" rule.

## 2. Repo orientation (verified 2026-04-16)

| Location | Fact |
|---|---|
| `optimizer/llm_proposer.py:138` | `_build_user_prompt()` module-level fn |
| `optimizer/llm_proposer.py:255` | `LLMProposer.propose()` — calls `_build_user_prompt` |
| `optimizer/proposer.py:132` | `Proposer._mock_propose` (dominant-bucket dispatch) |
| `optimizer/proposer.py:282` | `Proposer._llm_propose` |
| `optimizer/reflection.py` | `ReflectionEngine`, `SurfaceEffectiveness(surface, attempts, successes, avg_improvement, last_attempted)` — no `strategy` column |
| `optimizer/loop.py:368` | `proposal = self.proposer.propose(...)` — R3.6 hook site |
| `evals/judges/pairwise_judge.py` | `PairwiseLLMJudge.judge_case()` — pure heuristic today |
| `evals/scorer.py:158` | `CompositeScore.weighted_breakdown()` — kwargs-parameterized |
| `evals/scorer.py:207-210` | `CompositeScorer` class-constant weights |
| `evals/scorer.py:309` | `_bootstrap_mean_ci()` — per-metric (do not duplicate) |
| `evals/scorer.py:346-348` | `ConstrainedScorer` objective weights |
| `evals/statistics.py:25` | `paired_significance()` — no CI today |
| `evals/statistics.py:105` | `clustered_bootstrap()` — pattern for paired CI |
| `evals/coverage_analyzer.py` | `CoverageReport.gaps: list[CoverageGap]` |
| `evals/card_case_generator.py` | Already exists; R3.6 wires it |
| `cli/commands/eval.py` | Existing eval subcommand module (R3.10 extends) |
| `agentlab.yaml` | Top-level keys today: optimizer, loop, eval, budget, optimization, harness. No `eval.composite` yet |

Python 3.10+. Every subagent dispatch uses `uv run pytest`, never bare
`pytest` / `python3`.

## 3. Slice structure and commit plan

~15 commits in 3 slices. One PR per slice.

### Slice A — Coverage-aware proposer + reflection feedback (R3.1–R3.6)

| # | Task | Commit message |
|---|---|---|
| A.1 | Coverage `gap_signal()` | `feat(evals): add CoverageAnalyzer.gap_signal for proposer targeting` |
| A.2 | Coverage in proposer prompt | `feat(optimizer): inject coverage gaps into LLM proposer prompt` |
| A.3 | `read_surface_effectiveness` | `feat(optimizer): add read_surface_effectiveness thin wrapper` |
| A.4 | `_rank_strategies` + epsilon-greedy | `feat(optimizer): rank strategies by surface effectiveness with epsilon-greedy` |
| A.5 | `--explain-strategy` flag | `feat(cli): --explain-strategy flag on optimize` |
| A.6 | Auto card_case_generator | `feat(optimizer): auto-grow eval cases when coverage below threshold` |

### Slice B — LLM judge + configurable weights + statistics (R3.7–R3.13)

| # | Task | Commit message |
|---|---|---|
| B.1 | LLM judge + cache (same commit) | `feat(evals): LLM-backed pairwise judge with SQLite cache and TTL` |
| B.2 | Heuristic as fallback | `feat(evals): heuristic judge fallback on LLM failure` |
| B.3 | Weights → yaml | `feat(evals): load composite weights from workspace yaml` |
| B.4 | `eval weights` subcommand | `feat(cli): agentlab eval weights show/set/validate` |
| B.5 | Weights snapshot on `CompositeScore` | `feat(evals): snapshot composite weights per eval run` |
| B.6 | Bootstrap CI in `paired_significance` | `feat(evals): paired bootstrap CI in paired_significance` |
| B.7 | Variance-calibrated effect size | `feat(evals): variance-calibrated effect size on SignificanceResult` |

### Slice C — Docs (R3.14)

| # | Task | Commit message |
|---|---|---|
| C.1 | Docs update | `docs: document R3 smart-optimizer features` |

## 4. Per-step TDD recipes — Slice A

### A.1 — R3.1 `CoverageAnalyzer.gap_signal()`

**Test first** (`tests/test_coverage_gap_signal.py`):

```python
from evals.coverage_analyzer import CoverageAnalyzer, CoverageReport, CoverageGap

def _make_report(gaps):
    r = CoverageReport(surfaces={}, gaps=gaps, overall_coverage=0.0, generated_at=0.0)
    return r

def test_gap_signal_returns_sorted_tuples():
    gaps = [
        CoverageGap(surface="api", component_name="routes", gap_type="undertested",
                    current_count=2, recommended_count=10, description="", severity="high"),
        CoverageGap(surface="cli", component_name="flags", gap_type="undertested",
                    current_count=1, recommended_count=3, description="", severity="low"),
        CoverageGap(surface="db", component_name="migrations", gap_type="undertested",
                    current_count=0, recommended_count=5, description="", severity="high"),
    ]
    analyzer = CoverageAnalyzer.__new__(CoverageAnalyzer)
    analyzer._last_report = _make_report(gaps)
    signal = analyzer.gap_signal()
    # (surface, severity, delta) — sorted: severity desc, then delta desc
    assert signal[0] == ("db", "high", 5)
    assert signal[1] == ("api", "high", 8)
    assert signal[-1] == ("cli", "low", 2)

def test_gap_signal_dict_keys_surfaces():
    analyzer = CoverageAnalyzer.__new__(CoverageAnalyzer)
    analyzer._last_report = _make_report([
        CoverageGap(surface="api", component_name="x", gap_type="undertested",
                    current_count=0, recommended_count=10, description="only 0 cases",
                    severity="high"),
    ])
    d = analyzer.gap_signal_dict()
    assert "api" in d
    assert d["api"]["gap"] == 10
    assert d["api"]["severity"] == "high"
```

**Minimal impl** (`evals/coverage_analyzer.py`):

```python
_SEVERITY_ORDER = {"high": 2, "medium": 1, "low": 0}

def gap_signal(self) -> list[tuple[str, str, int]]:
    report = self._last_report
    if report is None:
        return []
    out = [(g.surface, g.severity, g.recommended_count - g.current_count)
           for g in report.gaps]
    out.sort(key=lambda t: (-_SEVERITY_ORDER.get(t[1], 0), -t[2]))
    return out

def gap_signal_dict(self) -> dict[str, dict]:
    report = self._last_report
    if report is None:
        return {}
    return {
        g.surface: {
            "severity": g.severity,
            "gap": g.recommended_count - g.current_count,
            "current": g.current_count,
            "recommended": g.recommended_count,
            "description": g.description,
        }
        for g in report.gaps
    }
```

Subagent confirms: `_last_report` is the attribute `CoverageAnalyzer.analyze()`
already caches (verify via Read before finalizing).

**Run:** `uv run pytest tests/test_coverage_gap_signal.py -x`

### A.2 — R3.2 Inject coverage gaps into proposer prompt

**Test first** (`tests/test_llm_proposer_coverage_prompt.py`):

```python
from optimizer.llm_proposer import _build_user_prompt

def test_prompt_includes_coverage_section_when_signal_present():
    prompt = _build_user_prompt(
        agent_card_markdown="# Agent",
        failure_analysis="n/a",
        past_attempts="",
        objective="improve",
        constraints="",
        available_mutations=["tighten_prompt"],
        coverage_signal=[("api", "high", 8), ("cli", "low", 2)],
    )
    assert "Eval Coverage Gaps" in prompt
    assert "api" in prompt and "8" in prompt
    assert "cli" in prompt and "2" in prompt

def test_prompt_omits_coverage_section_when_none():
    prompt = _build_user_prompt(
        agent_card_markdown="# Agent",
        failure_analysis="n/a",
        past_attempts="",
        objective="improve",
        constraints="",
        available_mutations=["tighten_prompt"],
        coverage_signal=None,
    )
    assert "Eval Coverage Gaps" not in prompt
```

**Minimal impl** (`optimizer/llm_proposer.py`):

Add kwarg `coverage_signal: list[tuple[str, str, int]] | None = None`
to `_build_user_prompt`. When non-empty, render a section after
"Failure Analysis":

```
## Eval Coverage Gaps

These surfaces have under-tested components — prefer proposals that
improve behavior on them:

- [HIGH] api: 8 cases short of target
- [LOW]  cli: 2 cases short of target
```

Then in `LLMProposer.propose()` (line 255): accept a `coverage_signal`
param, thread it into the `_build_user_prompt` call. `Proposer._llm_propose`
pulls the signal from a new `CoverageAnalyzer` dependency injected at
construction. All call sites that omit `coverage_signal` continue working.

**Run:** `uv run pytest tests/test_llm_proposer_coverage_prompt.py -x`

### A.3 — R3.3 `read_surface_effectiveness`

**Test first** (`tests/test_reflection_read_surface.py`):

```python
from optimizer.reflection import ReflectionEngine, SurfaceEffectiveness

def test_read_surface_effectiveness_returns_record(tmp_path):
    engine = ReflectionEngine(db_path=str(tmp_path / "r.db"))
    # seed one reflection via the existing API
    engine.record_reflection(
        attempt_id="a1", outcome="success",
        score_before=0.70, score_after=0.80,
        what_worked="x", what_didnt="",
        root_cause_update="", next_suggestions="",
        surface_learnings={"api": "tightened prompt helped"},
        confidence=0.9, reasoning="stub",
    )
    eff = engine.read_surface_effectiveness("api")
    assert isinstance(eff, SurfaceEffectiveness)
    assert eff.surface == "api"
    assert eff.attempts >= 1
    assert eff.avg_improvement > 0

def test_read_surface_effectiveness_unknown_surface(tmp_path):
    engine = ReflectionEngine(db_path=str(tmp_path / "r.db"))
    assert engine.read_surface_effectiveness("nonexistent") is None
```

**Minimal impl** (`optimizer/reflection.py`):

```python
def read_surface_effectiveness(self, surface: str) -> SurfaceEffectiveness | None:
    effs = self.get_surface_effectiveness()
    return effs.get(surface)
```

Thin wrapper. No schema change. Subagent verifies exact method names on
`ReflectionEngine` via Read before committing.

**Run:** `uv run pytest tests/test_reflection_read_surface.py -x`

### A.4 — R3.4 `_rank_strategies` with epsilon-greedy

**Test first** (`tests/test_proposer_rank_strategies.py`):

```python
import random
from optimizer.proposer import Proposer
from optimizer.reflection import ReflectionEngine, SurfaceEffectiveness

class _FakeReflection:
    """Minimal stand-in that only implements read_surface_effectiveness."""
    def __init__(self, table: dict[str, SurfaceEffectiveness]):
        self._t = table
    def read_surface_effectiveness(self, s):
        return self._t.get(s)

def _eff(surface, attempts, avg_improvement):
    return SurfaceEffectiveness(
        surface=surface, attempts=attempts, successes=attempts,
        avg_improvement=avg_improvement, last_attempted=0.0)

def test_rank_strategies_prefers_high_effectiveness_surface(monkeypatch):
    # patch STRATEGY_TO_SURFACE so test isn't coupled to prod mapping
    monkeypatch.setattr("optimizer.proposer.STRATEGY_TO_SURFACE", {
        "tighten_prompt": "api",
        "add_tool": "cli",
        "refactor": "db",
    })
    reflection = _FakeReflection({
        "api": _eff("api", 10, 0.20),
        "cli": _eff("cli", 5, 0.05),
        "db": _eff("db", 1, 0.01),
    })
    p = Proposer()
    rng = random.Random(42)
    # epsilon=0 -> pure exploitation
    ranked = p._rank_strategies(
        ["add_tool", "tighten_prompt", "refactor"],
        reflection_engine=reflection, epsilon=0.0, rng=rng)
    assert ranked[0] == "tighten_prompt"  # api has highest avg_improvement
    assert ranked[-1] == "refactor"

def test_rank_strategies_epsilon_explores_deterministically():
    """With epsilon=0.1 and seed=42, over 1000 calls ~10% should be random order."""
    monkeypatch_map = {"tighten_prompt": "api", "add_tool": "cli", "refactor": "db"}
    import optimizer.proposer as pm
    original = pm.STRATEGY_TO_SURFACE
    pm.STRATEGY_TO_SURFACE = monkeypatch_map
    try:
        reflection = _FakeReflection({
            "api": _eff("api", 10, 0.20),
            "cli": _eff("cli", 5, 0.05),
            "db": _eff("db", 1, 0.01),
        })
        p = Proposer()
        rng = random.Random(42)
        exploit_top = 0
        explore_hits = 0
        for _ in range(1000):
            ranked = p._rank_strategies(
                ["add_tool", "tighten_prompt", "refactor"],
                reflection_engine=reflection, epsilon=0.1, rng=rng)
            if ranked[0] == "tighten_prompt":
                exploit_top += 1
            else:
                explore_hits += 1
        # Expect ~100 explorations out of 1000 (bounded tolerance)
        assert 60 <= explore_hits <= 160, f"got {explore_hits}"
    finally:
        pm.STRATEGY_TO_SURFACE = original

def test_rank_strategies_no_reflection_returns_input_order():
    p = Proposer()
    ranked = p._rank_strategies(
        ["a", "b", "c"], reflection_engine=None,
        epsilon=0.0, rng=random.Random(1))
    assert ranked == ["a", "b", "c"]
```

**Minimal impl** (`optimizer/proposer.py`):

```python
STRATEGY_TO_SURFACE: dict[str, str] = {
    # seed mapping; extend in follow-ups
    "tighten_prompt": "prompting",
    "add_tool": "tools",
    "refactor": "architecture",
    "expand_card": "agent_card",
    # default: unknown strategies map to None and sort last
}

def _rank_strategies(
    self,
    available_strategies: list[str],
    reflection_engine: "ReflectionEngine | None",
    epsilon: float = 0.1,
    rng: random.Random | None = None,
) -> list[str]:
    rng = rng or random.Random()
    if reflection_engine is None:
        return list(available_strategies)
    # epsilon-greedy
    if rng.random() < epsilon:
        shuffled = list(available_strategies)
        rng.shuffle(shuffled)
        return shuffled

    def _key(strategy: str) -> tuple[float, int, str]:
        surface = STRATEGY_TO_SURFACE.get(strategy)
        if surface is None:
            return (float("-inf"), 0, strategy)
        eff = reflection_engine.read_surface_effectiveness(surface)
        if eff is None:
            return (0.0, 0, strategy)
        return (eff.avg_improvement, eff.attempts, strategy)

    return sorted(available_strategies, key=_key, reverse=True)
```

**Run:** `uv run pytest tests/test_proposer_rank_strategies.py -x`

### A.5 — R3.5 `--explain-strategy` flag on `optimize`

**Test first** (`tests/test_optimize_explain_strategy.py`):

```python
from click.testing import CliRunner
from runner import cli

def test_explain_strategy_prints_line_per_strategy(monkeypatch, tmp_path):
    # patch Proposer to emit an explanation payload for the run
    from optimizer.proposer import Proposer
    def fake_propose(self, *a, **kw):
        self._last_explanation = [
            {"strategy": "tighten_prompt", "surface": "api",
             "effectiveness": 0.70, "samples": 12},
            {"strategy": "add_tool", "surface": "cli",
             "effectiveness": 0.05, "samples": 5},
        ]
        # ... return a minimal valid proposal; subagent fills in
        return _fake_proposal()
    monkeypatch.setattr(Proposer, "propose", fake_propose)
    # stub the rest of the optimize pipeline
    r = CliRunner().invoke(cli, [
        "optimize", "--explain-strategy", "--dry-run",
        str(tmp_path / "cfg.yaml")])
    assert r.exit_code == 0
    assert "selected mutation tighten_prompt" in r.output
    assert "effectiveness=0.70" in r.output
    assert "n=12" in r.output

def test_explain_strategy_omits_when_flag_absent():
    r = CliRunner().invoke(cli, ["optimize", "--dry-run", "x.yaml"])
    assert "selected mutation" not in r.output
```

**Minimal impl** (`cli/commands/optimize.py`):

Add `@click.option("--explain-strategy", is_flag=True, default=False)`.
After the optimize cycle completes, if flag is set:

```python
explanation = getattr(proposer, "_last_explanation", []) or []
for e in explanation:
    click.echo(
        f"selected mutation {e['strategy']} because "
        f"effectiveness={e['effectiveness']:.2f} on similar surfaces "
        f"(n={e['samples']} samples)"
    )
```

`Proposer.propose()` records `self._last_explanation` as a list of dicts
at the end of each call (populated from the ranking that happened above).

**Run:** `uv run pytest tests/test_optimize_explain_strategy.py -x`

### A.6 — R3.6 Auto `card_case_generator` when coverage <30%

**Test first** (`tests/test_loop_auto_grow_cases.py`):

```python
from optimizer.loop import OptimizerLoop  # verify exact class name via Read
from evals.card_case_generator import CardCaseGenerator

class _StubCoverage:
    def __init__(self, by_surface):
        self._by = by_surface
    def analyze(self, *a, **k):
        # produces CoverageReport with per-surface fractions
        ...
    def surface_coverage(self) -> dict[str, float]:
        return dict(self._by)
    def gap_signal(self): return []
    def gap_signal_dict(self): return {}

def test_loop_triggers_card_case_generator_below_threshold(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(CardCaseGenerator, "grow",
                        lambda self, surface, **k: calls.append(surface))
    loop = OptimizerLoop(
        coverage_analyzer=_StubCoverage({"api": 0.20, "cli": 0.90}),
        auto_grow_cases=True,
        proposer=_NullProposer(),
        # ... minimal deps
    )
    loop.run_cycle(...)
    assert "api" in calls
    assert "cli" not in calls

def test_loop_disabled_by_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(CardCaseGenerator, "grow",
                        lambda self, surface, **k: calls.append(surface))
    loop = OptimizerLoop(auto_grow_cases=False, ...)
    loop.run_cycle(...)
    assert calls == []
```

**Minimal impl** (`optimizer/loop.py`):

In `__init__`, add `auto_grow_cases: bool = True` and
`card_case_generator: CardCaseGenerator | None = None` (lazily built if
`None`). Immediately before `self.proposer.propose(...)` at line 368,
insert:

```python
if self.auto_grow_cases and self.coverage_analyzer is not None:
    try:
        coverage = self.coverage_analyzer.surface_coverage()
        for surface, frac in coverage.items():
            if frac < 0.30:
                (self.card_case_generator or CardCaseGenerator()).grow(surface)
    except Exception as e:
        logger.warning("auto case-grow skipped: %s", e)
```

Subagent verifies `CardCaseGenerator.grow(surface)` signature before
committing; adapt if it differs.

**Run:** `uv run pytest tests/test_loop_auto_grow_cases.py -x`

## 5. Per-step TDD recipes — Slice B

### B.1 — R3.7 LLM pairwise judge + SQLite cache (single commit)

**Test first** (`tests/test_pairwise_llm_judge_cached.py`):

```python
import json
from unittest.mock import MagicMock
from evals.judges.pairwise_judge import (
    PairwiseLLMJudge, PairwiseJudgeCache, PairwiseJudgeVerdict,
)

def _case(input_a="i", input_b="i", output_a="a", output_b="b"):
    # subagent uses the real PairwiseCase / PairwiseCaseResult factory
    return ...

def test_cache_miss_calls_llm_then_caches(tmp_path):
    router = MagicMock()
    router.call.return_value = json.dumps(
        {"winner": "a", "confidence": 0.82, "rationale": "tighter"})
    cache = PairwiseJudgeCache(db_path=str(tmp_path / "c.db"))
    judge = PairwiseLLMJudge(llm_router=router, cache=cache)
    v1 = judge.judge_case(_case())
    assert v1.winner == "a"
    assert router.call.call_count == 1
    v2 = judge.judge_case(_case())  # same inputs → cache hit
    assert v2.winner == "a"
    assert router.call.call_count == 1, "second call must hit cache"

def test_cache_ttl_expires_after_30_days(tmp_path, monkeypatch):
    import time
    t = [1_000_000.0]
    monkeypatch.setattr("evals.judges.pairwise_judge.time.time", lambda: t[0])
    router = MagicMock()
    router.call.return_value = json.dumps(
        {"winner": "b", "confidence": 0.5, "rationale": "x"})
    cache = PairwiseJudgeCache(db_path=str(tmp_path / "c.db"))
    judge = PairwiseLLMJudge(llm_router=router, cache=cache)
    judge.judge_case(_case())
    t[0] += 31 * 86400  # 31 days later
    judge.judge_case(_case())
    assert router.call.call_count == 2

def test_llm_schema_validation_failure_falls_back_to_heuristic(tmp_path):
    router = MagicMock()
    router.call.return_value = "not json"
    cache = PairwiseJudgeCache(db_path=str(tmp_path / "c.db"))
    judge = PairwiseLLMJudge(llm_router=router, cache=cache, strict_live=False)
    v = judge.judge_case(_case())
    # heuristic must have produced a PairwiseJudgeVerdict, not raise
    assert isinstance(v, PairwiseJudgeVerdict)

def test_strict_live_raises_on_failure(tmp_path):
    router = MagicMock()
    router.call.side_effect = RuntimeError("provider 500")
    cache = PairwiseJudgeCache(db_path=str(tmp_path / "c.db"))
    judge = PairwiseLLMJudge(llm_router=router, cache=cache, strict_live=True)
    import pytest
    with pytest.raises(RuntimeError):
        judge.judge_case(_case())

def test_heuristic_path_when_router_none():
    judge = PairwiseLLMJudge(llm_router=None)
    v = judge.judge_case(_case())
    assert isinstance(v, PairwiseJudgeVerdict)
```

**Minimal impl** (`evals/judges/pairwise_judge.py`):

```python
import hashlib
import json
import sqlite3
import time
from dataclasses import asdict

CACHE_TTL_SECONDS = 30 * 86400

class PairwiseJudgeCache:
    def __init__(self, db_path: str = ".agentlab/llm_judge_cache.db"):
        self._db_path = db_path
        self._init_schema()

    def _init_schema(self):
        con = sqlite3.connect(self._db_path)
        con.execute("""CREATE TABLE IF NOT EXISTS judge_cache(
            cache_key TEXT PRIMARY KEY,
            verdict_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )""")
        con.commit(); con.close()

    @staticmethod
    def key_for(input_a, input_b, output_a, output_b) -> str:
        raw = f"{input_a}|{input_b}|{output_a}|{output_b}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str):
        con = sqlite3.connect(self._db_path)
        row = con.execute(
            "SELECT verdict_json, created_at FROM judge_cache WHERE cache_key=?",
            (key,)).fetchone()
        con.close()
        if row is None:
            return None
        verdict_json, created_at = row
        if time.time() - created_at > CACHE_TTL_SECONDS:
            return None
        return json.loads(verdict_json)

    def put(self, key: str, verdict_dict: dict):
        con = sqlite3.connect(self._db_path)
        con.execute(
            "INSERT OR REPLACE INTO judge_cache VALUES (?, ?, ?)",
            (key, json.dumps(verdict_dict), time.time()))
        con.commit(); con.close()


class PairwiseLLMJudge:
    def __init__(self, llm_router=None, cache: PairwiseJudgeCache | None = None,
                 strict_live: bool = False):
        self._router = llm_router
        self._cache = cache
        self._strict_live = strict_live

    def judge_case(self, case) -> PairwiseJudgeVerdict:
        if self._router is None:
            return self._heuristic(case)
        key = PairwiseJudgeCache.key_for(
            case.input_a, case.input_b, case.output_a, case.output_b)
        cached = self._cache.get(key) if self._cache else None
        if cached:
            return PairwiseJudgeVerdict(**cached)
        try:
            raw = self._router.call(self._build_prompt(case))
            parsed = self._validate(raw)  # may raise
        except Exception:
            if self._strict_live:
                raise RuntimeError("pairwise judge live call failed")
            return self._heuristic(case)
        verdict = PairwiseJudgeVerdict(
            winner=parsed["winner"],
            reasoning=parsed["rationale"],
            confidence=float(parsed["confidence"]),
        )
        if self._cache:
            self._cache.put(key, asdict(verdict))
        return verdict

    def _validate(self, raw: str) -> dict:
        obj = json.loads(raw)  # may raise
        if obj.get("winner") not in ("a", "b", "tie"):
            raise ValueError("invalid winner")
        if not isinstance(obj.get("confidence"), (int, float)):
            raise ValueError("invalid confidence")
        if not isinstance(obj.get("rationale"), str):
            raise ValueError("invalid rationale")
        return obj
```

The existing heuristic lives as `_heuristic(self, case)` — rename the
current `judge_case` body.

**Run:** `uv run pytest tests/test_pairwise_llm_judge_cached.py -x`

### B.2 — R3.8 Heuristic fallback (consolidation commit)

B.1 already landed fallback. B.2 is a cleanup pass that:
1. Moves the heuristic body into a named `_heuristic(case)` if not already.
2. Adds an integration test that runs the judge on a known fixture with
   `llm_router=None` and confirms byte-identical output to pre-R3 behavior.

**Test** (`tests/test_pairwise_judge_heuristic_unchanged.py`): pin a small
golden fixture of verdicts from a known case set. Judge with `router=None`
must produce the same verdicts as master tip did.

**Run:** `uv run pytest tests/test_pairwise_judge_heuristic_unchanged.py -x`

### B.3 — R3.9 Composite weights → yaml

**Test first** (`tests/test_composite_weights_yaml.py`):

```python
from pathlib import Path
from evals.composite_weights import (
    CompositeWeights, validate_weights, load_from_workspace,
)
from evals.scorer import CompositeScorer

def test_validate_weights_ok():
    w = CompositeWeights(quality=0.4, safety=0.25, latency=0.2, cost=0.15)
    validate_weights(w)  # no raise

def test_validate_weights_bad_sum_rejected():
    w = CompositeWeights(quality=0.5, safety=0.25, latency=0.2, cost=0.15)
    import pytest
    with pytest.raises(ValueError):
        validate_weights(w)

def test_load_from_yaml_reads_eval_composite_weights(tmp_path):
    yml = tmp_path / "agentlab.yaml"
    yml.write_text(
        "eval:\n  composite:\n    weights:\n"
        "      quality: 0.45\n      safety: 0.25\n"
        "      latency: 0.15\n      cost: 0.15\n"
    )
    w = load_from_workspace(str(yml))
    assert w.quality == 0.45 and w.cost == 0.15

def test_load_from_yaml_missing_returns_defaults(tmp_path):
    yml = tmp_path / "agentlab.yaml"
    yml.write_text("harness: {}\n")
    w = load_from_workspace(str(yml))
    # defaults = current class constants
    assert (w.quality, w.safety, w.latency, w.cost) == (0.40, 0.25, 0.20, 0.15)

def test_composite_scorer_uses_injected_weights():
    w = CompositeWeights(quality=0.8, safety=0.1, latency=0.05, cost=0.05)
    scorer = CompositeScorer(weights=w)
    # ... score a known fixture and assert composite differs from default
```

**Minimal impl** (new `evals/composite_weights.py`):

```python
from dataclasses import dataclass
import yaml

@dataclass(frozen=True)
class CompositeWeights:
    quality: float = 0.40
    safety: float = 0.25
    latency: float = 0.20
    cost: float = 0.15

def validate_weights(w: CompositeWeights, tolerance: float = 1e-6) -> None:
    total = w.quality + w.safety + w.latency + w.cost
    if abs(total - 1.0) > tolerance:
        raise ValueError(f"weights must sum to 1.0, got {total:.4f}")
    for name in ("quality", "safety", "latency", "cost"):
        if getattr(w, name) < 0:
            raise ValueError(f"{name} weight must be non-negative")

def load_from_workspace(yaml_path: str) -> CompositeWeights:
    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return CompositeWeights()
    block = ((data.get("eval") or {}).get("composite") or {}).get("weights") or {}
    return CompositeWeights(
        quality=float(block.get("quality", 0.40)),
        safety=float(block.get("safety", 0.25)),
        latency=float(block.get("latency", 0.20)),
        cost=float(block.get("cost", 0.15)),
    )
```

`CompositeScorer.__init__(weights: CompositeWeights | None = None)`
stores `self._weights = weights or CompositeWeights()`. All uses of the
class constants inside the scorer become `self._weights.quality`, etc.
Default behavior equals current constants — no existing call site breaks.

**Run:** `uv run pytest tests/test_composite_weights_yaml.py -x`

### B.4 — R3.10 `agentlab eval weights` subcommand

**Test first** (`tests/test_cli_eval_weights.py`):

```python
from click.testing import CliRunner
from runner import cli

def test_eval_weights_show(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agentlab.yaml").write_text(
        "eval:\n  composite:\n    weights:\n"
        "      quality: 0.45\n      safety: 0.25\n"
        "      latency: 0.15\n      cost: 0.15\n")
    r = CliRunner().invoke(cli, ["eval", "weights", "show"])
    assert r.exit_code == 0
    assert "quality: 0.45" in r.output

def test_eval_weights_set_updates_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agentlab.yaml").write_text("harness: {}\n")
    r = CliRunner().invoke(cli, [
        "eval", "weights", "set",
        "--quality", "0.5", "--safety", "0.2",
        "--latency", "0.15", "--cost", "0.15"])
    assert r.exit_code == 0
    import yaml
    d = yaml.safe_load((tmp_path / "agentlab.yaml").read_text())
    assert d["eval"]["composite"]["weights"]["quality"] == 0.5

def test_eval_weights_validate_rejects_bad_sum(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agentlab.yaml").write_text(
        "eval:\n  composite:\n    weights:\n"
        "      quality: 0.9\n      safety: 0.25\n"
        "      latency: 0.2\n      cost: 0.15\n")
    r = CliRunner().invoke(cli, ["eval", "weights", "validate"])
    assert r.exit_code != 0
    assert "sum" in r.output.lower()
```

**Minimal impl** (`cli/commands/eval.py` — add inside the existing
`register_eval_commands` function):

```python
@eval_group.group("weights")
def eval_weights():
    """Manage composite score weights."""

@eval_weights.command("show")
def eval_weights_show():
    w = load_from_workspace("agentlab.yaml")
    click.echo(f"quality: {w.quality}")
    click.echo(f"safety: {w.safety}")
    click.echo(f"latency: {w.latency}")
    click.echo(f"cost: {w.cost}")

@eval_weights.command("set")
@click.option("--quality", type=float, required=True)
@click.option("--safety", type=float, required=True)
@click.option("--latency", type=float, required=True)
@click.option("--cost", type=float, required=True)
def eval_weights_set(quality, safety, latency, cost):
    w = CompositeWeights(quality, safety, latency, cost)
    validate_weights(w)  # raises if bad
    _write_yaml_weights("agentlab.yaml", w)

@eval_weights.command("validate")
def eval_weights_validate():
    w = load_from_workspace("agentlab.yaml")
    try:
        validate_weights(w)
        click.echo("weights OK")
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        raise SystemExit(2)
```

`_write_yaml_weights` round-trips the existing yaml preserving other keys.

**Run:** `uv run pytest tests/test_cli_eval_weights.py -x`

### B.5 — R3.11 `CompositeScore.weights_snapshot`

**Test first** (`tests/test_composite_score_snapshot.py`):

```python
def test_score_carries_weights_snapshot(tmp_path):
    from evals.scorer import CompositeScorer
    from evals.composite_weights import CompositeWeights
    scorer = CompositeScorer(weights=CompositeWeights(
        quality=0.5, safety=0.2, latency=0.15, cost=0.15))
    score = scorer.score(...)  # subagent fills minimal fixture
    assert score.weights_snapshot is not None
    assert score.weights_snapshot.quality == 0.5

def test_historical_rerender_uses_snapshot_not_current_yaml(tmp_path, monkeypatch):
    """Freeze a score, mutate yaml, re-render — composite must match snapshot."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agentlab.yaml").write_text(
        "eval:\n  composite:\n    weights:\n"
        "      quality: 0.4\n      safety: 0.25\n"
        "      latency: 0.2\n      cost: 0.15\n")
    from evals.scorer import CompositeScorer, CompositeScore
    scorer = CompositeScorer()
    score = scorer.score(...)  # uses yaml (0.4, 0.25, 0.2, 0.15)
    frozen_composite = score.composite
    # mutate yaml to wildly different weights
    (tmp_path / "agentlab.yaml").write_text(
        "eval:\n  composite:\n    weights:\n"
        "      quality: 0.9\n      safety: 0.05\n"
        "      latency: 0.03\n      cost: 0.02\n")
    # re-render from persisted score + snapshot
    rerendered = CompositeScore.rerender(score)
    assert rerendered.composite == frozen_composite
```

**Minimal impl** (`evals/scorer.py`):

Add field to `CompositeScore`:
```python
weights_snapshot: CompositeWeights | None = None
```

In `CompositeScorer.score()` end, before return: `result.weights_snapshot = self._weights`.

Add classmethod:
```python
@classmethod
def rerender(cls, score: "CompositeScore") -> "CompositeScore":
    if score.weights_snapshot is None:
        return score
    w = score.weights_snapshot
    return score.weighted_breakdown(
        quality=w.quality, safety=w.safety,
        latency=w.latency, cost=w.cost)
```

(Subagent reconciles signature with existing `weighted_breakdown`
return type — may need a wrapper.)

**Run:** `uv run pytest tests/test_composite_score_snapshot.py -x`

### B.6 — R3.12 Bootstrap CI in `paired_significance()`

**Test first** (`tests/test_paired_significance_ci.py`):

```python
from evals.statistics import paired_significance

def test_ci_brackets_observed_delta():
    pairs = [(0.80, 0.85), (0.70, 0.74), (0.60, 0.66), (0.50, 0.58), (0.90, 0.93)]
    r = paired_significance(pairs, bootstrap_ci=True, n_bootstrap=2000, seed=42)
    assert r.confidence_interval is not None
    lo, hi = r.confidence_interval
    assert lo <= r.observed_delta <= hi

def test_ci_disabled_returns_none():
    pairs = [(0.80, 0.85), (0.70, 0.74)]
    r = paired_significance(pairs, bootstrap_ci=False)
    assert r.confidence_interval is None

def test_ci_is_deterministic_with_seed():
    pairs = [(0.8, 0.9), (0.7, 0.75), (0.6, 0.65)]
    r1 = paired_significance(pairs, bootstrap_ci=True, seed=7)
    r2 = paired_significance(pairs, bootstrap_ci=True, seed=7)
    assert r1.confidence_interval == r2.confidence_interval
```

**Minimal impl** (`evals/statistics.py`):

Extend `SignificanceResult`:
```python
@dataclass
class SignificanceResult:
    observed_delta: float
    p_value: float
    is_significant: bool
    n_pairs: int
    alpha: float
    min_effect_size: float
    confidence_interval: tuple[float, float] | None = None
    calibrated_effect_size: float | None = None  # B.7
```

Extend `paired_significance(pairs, alpha=0.05, min_effect_size=0.02,
bootstrap_ci=True, n_bootstrap=2000, seed=None)`:

```python
if bootstrap_ci and len(pairs) >= 2:
    rng = random.Random(seed)
    diffs = [b - a for a, b in pairs]
    resamples = []
    n = len(diffs)
    for _ in range(n_bootstrap):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        resamples.append(sum(sample) / n)
    resamples.sort()
    lo = resamples[int((alpha / 2) * n_bootstrap)]
    hi = resamples[int((1 - alpha / 2) * n_bootstrap)]
    ci = (lo, hi)
else:
    ci = None
```

Pattern mirrors `clustered_bootstrap()` at line 105.

**Run:** `uv run pytest tests/test_paired_significance_ci.py -x`

### B.7 — R3.13 Variance-calibrated effect size

**Test first** (`tests/test_effect_size_calibrated.py`):

```python
from evals.statistics import paired_significance

def test_small_but_stable_improvement_passes():
    # every pair: exactly +0.03 (zero variance)
    pairs = [(0.80, 0.83)] * 20
    r = paired_significance(pairs, bootstrap_ci=False,
                            min_calibrated_effect=1.0)  # demand ES >= 1
    # zero variance → calibrated ES is inf → always passes
    assert r.is_significant
    assert r.calibrated_effect_size is not None

def test_large_but_noisy_improvement_fails():
    # mean delta +0.10 but with huge variance
    pairs = [(0.50, 0.60), (0.50, 0.30), (0.50, 0.70), (0.50, 0.20),
             (0.50, 0.80), (0.50, 0.10), (0.50, 0.90), (0.50, 0.40)]
    r = paired_significance(pairs, bootstrap_ci=False,
                            min_calibrated_effect=0.5)
    # calibrated_effect_size = mean_diff / std_diff — noisy → small ES
    assert r.calibrated_effect_size < 0.5
    # is_significant is False because calibrated ES fails gate
    assert not r.is_significant
```

**Minimal impl** (`evals/statistics.py`):

```python
import statistics as _st

def _calibrated_effect_size(diffs: list[float]) -> float:
    if not diffs:
        return 0.0
    mean = sum(diffs) / len(diffs)
    if len(diffs) < 2:
        return float("inf") if mean != 0 else 0.0
    sd = _st.pstdev(diffs)
    if sd == 0:
        return float("inf") if mean != 0 else 0.0
    return mean / sd
```

Wire into `paired_significance()`:
```python
diffs = [b - a for a, b in pairs]
calibrated = _calibrated_effect_size(diffs)
# update is_significant gate: p < alpha AND abs(calibrated) >= min_calibrated_effect
is_sig = (p_value < alpha
          and abs(observed_delta) >= min_effect_size
          and abs(calibrated) >= min_calibrated_effect)
```

Add param `min_calibrated_effect: float = 0.0` (0.0 keeps the gate
backward-compatible).

**Run:** `uv run pytest tests/test_effect_size_calibrated.py -x`

## 6. Docs — Slice C

### C.1 — R3.14 Doc update

Update `docs/QUICKSTART.md` and `AGENTLAB.md` sections on eval/optimize to
mention:
- `--explain-strategy` flag.
- Workspace `eval.composite.weights` block.
- `agentlab eval weights show|set|validate`.
- Automatic case growth when surface coverage <30%.
- Bootstrap CI and calibrated effect size in significance output.

No test required; docs-only commit.

**Commit:** `docs: document R3 smart-optimizer features`

## 7. Acceptance tests (end-to-end gate)

Per master plan:

- **After 5 cycles**, optimizer has executed ≥1 proposal targeting an
  under-covered surface. Gate: `tests/test_r3_acceptance_coverage_cycles.py`
  stubs a 5-cycle loop with one low-coverage surface; asserts at least one
  proposal's `target_surface` matches that surface.
- **After 10 cycles**, reflection table has surface effectiveness, and
  proposer's chosen strategy correlates with high-effectiveness surfaces.
  Gate: `tests/test_r3_acceptance_reflection_influence.py`.
- **LLM judge agreement** with human-labeled gold ≥80% on 20 fixture
  pairs. Gate: `tests/test_r3_acceptance_judge_gold.py` with a mocked
  router returning gold labels (since this is deterministic in CI).
- **Weights validator rejects** `sum != 1.0`. Gate: covered by B.3 test.
- **Historical reproducibility**: mutate yaml, re-render, composite
  stable. Gate: covered by B.5 test.
- **Strict-live exit code 13** when judge provider missing. Gate:
  `tests/test_r3_strict_live_judge_exits_13.py` mirrors R1 pattern.

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Reflection feedback loop runaway (proposer picks one strategy forever because it worked once) | Epsilon-greedy exploration in `_rank_strategies` (default 10%); deterministic test with `random.Random(42)` over 1000 calls asserts ~10% exploration |
| LLM judge cost explosion | SQLite cache with 30-day TTL, key = sha256 of both inputs + outputs; test asserts second identical call does NOT touch router (mock `call_count`) |
| Composite weight migration breaks historical scores | `weights_snapshot` on every `CompositeScore`; `rerender()` uses snapshot, not current yaml; test freezes + mutates yaml + re-renders and asserts stability |
| Heuristic fallback regresses after LLM path lands | Golden-fixture test pins heuristic verdicts to pre-R3 behavior (B.2) |
| `strict_live` path hides failures | `strict_live=True` raises `RuntimeError`, CLI test asserts exit code 13 (R1 convention) |
| Schema drift on `surface_effectiveness` | R3 does not touch schema; only adds wrapper read fn (§1.1) |
| Card-case-generator growth pollutes eval runs during tests | `auto_grow_cases=False` constructor flag; default tests disable it |
| Subagent uses host Python 3.9.6 | Every dispatch prompt says `uv run pytest`, never bare `pytest` |
| Yaml round-trip loses comments when `eval weights set` writes | Use `ruamel.yaml` round-trip loader if already a project dep; else accept comment loss and document it in `eval weights set --help` |
| Bootstrap CI is slow | `n_bootstrap=2000` by default; seedable for determinism; paired CI path is O(n × n_bootstrap) which is fine at our scale |

## 9. Execution workflow

Per `superpowers:subagent-driven-development`:

1. Lead thread dispatches one subagent per task in §3.
2. Each subagent: read this plan file, read the named source files,
   write failing test, run `uv run pytest <test> -x` to confirm RED,
   write minimal impl, run to confirm GREEN, run broader suite to
   confirm no regression, commit with the exact message from §3.
3. Lead marks TaskCreate tasks complete immediately (not batched).
4. At each slice boundary, lead opens a PR.

## 10. First subagent dispatch

After committing this file, dispatch **A.1** (CoverageAnalyzer.gap_signal).
Pass the exact per-step recipe from §4.A.1.

## 11. Deferred for future R

These deliberately punt out of R3:

1. **Strategy-dimension reflection schema** — add `strategy` column to
   `surface_effectiveness(surface, strategy, effectiveness_score,
   sample_count, updated_at)` with a proper migration. Enables per-strategy
   ranking rather than via `STRATEGY_TO_SURFACE` proxy. Requires
   backfill of historical reflections.
2. **Effect-size calibration beyond variance** — Cohen's d with
   variance-partitioning across groups (e.g., per-surface pooled
   variance). Today we use simple `mean / std` which ignores group
   structure.
3. **Per-surface weight profiles** — different composite weights for
   different surfaces (e.g., safety weighted higher on external-facing
   surfaces, cost lower). Today weights are workspace-global.
4. **Live LLM judge calibration harness** — 20-pair gold set evaluated
   against live provider on schedule, drift alert. Today the acceptance
   test uses a mocked router returning gold labels.
5. **Yaml comment preservation in `eval weights set`** — pending
   `ruamel.yaml` dependency review.
6. **Strategy-level lineage events** — emit `strategy_selected` event on
   every proposer call. Out of scope because R3 invariant §1.8 says no
   new event types in this slice.
