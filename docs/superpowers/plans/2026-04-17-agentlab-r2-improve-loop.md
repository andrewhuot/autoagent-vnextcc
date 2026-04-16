# R2 — Unified Improve Loop (TDD expansion plan)

**Status:** draft, ready for execution
**Branch:** `claude/r2-improve-loop` (off `master` at `fa79c5e`)
**Depends on:** R1 (`claude/elastic-sutherland`, commits `433e803`→`1ac4409`)
**Master plan section:** `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md:1187-1239`

## 0. Goal

One command — `agentlab improve` — owns the full lifecycle from "I have an
agent" to "I shipped a measured improvement," with evidence threading via
`attempt_id` (the R1 lineage key, 8-char uuid prefix).

After R2:

```
$ agentlab improve run configs/my-agent.yaml
  → eval → 1-cycle optimize → present top attempt_id + diff
$ agentlab improve accept <attempt_id>
  → deploy canary → schedule measurement event
$ agentlab improve measure <attempt_id>
  → post-deploy eval → compute composite_delta → persist
$ agentlab improve lineage <attempt_id>
  → eval_run → attempt → rejection? → deployment → measurement
```

Every event is threaded through the same `attempt_id` key that R1 already
emits from `optimizer/loop.py:675`. **No new identifiers.**

## 1. Architectural decisions

### 1.1 Do NOT create a parallel `attempt_lineage` table

The master plan scaffold proposes a new wide denormalized table
`attempt_lineage(eval_run_id, attempt_id, deployment_id, measurement_id,
parent_attempt_id, composite_delta, status, created_at)` in a new
`optimizer/lineage.py`.

The codebase already has `optimizer/improvement_lineage.py` with
`ImprovementLineageStore` — an append-only event table
`lineage_events(event_id, attempt_id, event_type, timestamp, version,
payload)` at `.agentlab/improvement_lineage.db`. It is already consumed by
`api/server.py:366` and `api/routes/improvements.py`. `runner.py` already
references the env var `AGENTLAB_IMPROVEMENT_LINEAGE_DB` at line 5121.

**Decision:** extend `ImprovementLineageStore`. Do not add a new file, a new
DB, or a new identifier. Never `ALTER TABLE`; new per-event fields go into
the existing `payload` JSON column. Expose a `view_attempt(attempt_id) ->
AttemptLineageView` aggregator that flattens the event stream into the
denormalized shape tests need.

### 1.2 Event types (append-only)

We add these `event_type` values to `lineage_events`:

| event_type    | Emitter                         | Payload keys                                                     |
|---------------|---------------------------------|------------------------------------------------------------------|
| `eval_run`    | `evals/runner.py` (new)         | `eval_run_id`, `config_path`, `composite_score`, `case_count`    |
| `attempt`     | `optimizer/loop.py` (new)       | `eval_run_id`, `status`, `score_before`, `score_after`, `parent_attempt_id` |
| `rejection`   | `optimizer/loop.py` (new)       | `reason` (from `RejectionReason`), `detail`                      |
| `deploy_canary` | `deployer/*` (already present in API path; extend for CLI) | `deployment_id`, `version` |
| `promote`     | `deployer/*` (already present in API path; extend for CLI) | `deployment_id`, `version` |
| `rollback`    | `deployer/*`                    | `deployment_id`, `rolled_back_from_version`                      |
| `measurement` | `cli/commands/improve.py` (new) | `measurement_id`, `composite_delta`, `eval_run_id`               |

Existing event types (`accept`, `reject`, `deploy_canary`, `promote`,
`rollback`, `measurement`) from the API path keep working unchanged — we're
augmenting, not replacing.

### 1.3 `attempt_id` invariant

`OptimizationAttempt.attempt_id = str(uuid.uuid4())[:8]` (8 chars) is the
lineage key. Every R2 event **must** use this exact value. R1's
`RejectionRecord.attempt_id` already matches; R2's new events continue the
pattern. Never introduce a second identifier.

### 1.4 Resolving the `improve run` namespace collision

`runner.py:5000` has a hidden `improve run` alias for the old autofix flow
(eval → diagnose → suggest → optional apply, no args). R2's new `improve
run <config>` replaces it.

**Decision:**
- New `improve run <config>` is the canonical, un-hidden command.
- Old behavior moves to `agentlab autofix apply` (new top-level wrapper).
  The hidden `improve run` alias **with zero args** keeps working and prints
  a deprecation notice routing to `autofix apply`. Test locks both paths.

### 1.5 Strict-live policy is preserved

Every R2 path that invokes a proposer or eval plumbs `--strict-live`
through. R1 wired it on `eval run`, `build`, and `optimize`; R2's `improve
run` sits on top and must pass it down.

### 1.6 Lineage writes never block user flows

All `lineage.record_*` calls are wrapped in try/except with structured log.
Lineage is observability, not a hard dependency. Store failures must not
crash eval, optimize, or deploy.

### 1.7 runner.py extraction byte-equivalence

`agentlab --help` output must be byte-identical before and after each
extraction in Slice C. Enforced by `tests/test_cli_help_golden.py`.
Decorator order, docstring whitespace, option order — all preserved.

## 2. Repo orientation (verified 2026-04-17)

| Location                                    | Fact                                           |
|---------------------------------------------|------------------------------------------------|
| `runner.py`                                 | 12,834 lines, single file                      |
| `runner.py:4995`                            | `@cli.group("improve", ...)`                   |
| `runner.py:5000`                            | `@improve_group.command("run", hidden=True)` — old autofix alias |
| `runner.py:5116`                            | `@improve_group.command("list")`               |
| `runner.py:5248`                            | `@improve_group.command("show")`               |
| `runner.py:5311`                            | `@improve_group.command("optimize")` — hidden compat alias for `agentlab optimize` |
| `runner.py:3029`                            | `@cli.group("build", ...)`                     |
| `runner.py:3322`                            | `@cli.group("eval", ...)`                      |
| `runner.py:4562`                            | `@cli.command("optimize")`                     |
| `runner.py:6085`                            | `@cli.command("deploy")`                       |
| `optimizer/improvement_lineage.py`          | `ImprovementLineageStore`, `LineageEvent`      |
| `optimizer/loop.py:675`                     | `attempt_id = str(uuid.uuid4())[:8]`           |
| `optimizer/loop.py:697`                     | `self.memory.log(attempt)` — R2 emits `attempt` event here |
| `optimizer/loop.py:706`                     | ring-buffer `RejectionRecord` append — R2 emits `rejection` event alongside |
| `evals/runner.py:946`                       | `run_id = str(uuid.uuid4())[:12]` — R2 emits `eval_run` event here |
| `api/server.py:366`                         | Constructs `ImprovementLineageStore` on app start — schema must stay compatible |
| `api/routes/optimize.py:611`                | API path already calls `improvement_lineage.record()` |
| `deployer/release_manager.py`               | Canary + promote entry points                  |
| `cli/workbench_app/`                        | Slash commands (eval, build, optimize, deploy, etc.) |
| `.agentlab/improvement_lineage.db`          | SQLite, existing store                         |

**Python:** 3.10+ required. Host is 3.9.6 — every subagent dispatch MUST
use `uv run python` / `uv run pytest`.

**Known pre-existing failures** (do not fix in R2; note and move on):
`test_full_loop_observe_optimize_deploy_promote`, starlette/httpx API
collection errors.

## 3. Slice structure and commit plan

~24 commits across 5 slices. One PR per slice.

### Slice 0 — Plan + golden baseline

| # | Task | Commit message |
|---|------|----------------|
| 0.1 | Write this file | `docs: expand R2 TDD plan` |
| 0.2 | Golden-file help snapshots | `test(cli): lock CLI --help output with golden snapshots` |

### Slice A — Lineage store (R2.1–R2.5)

| # | Task | Commit message |
|---|------|----------------|
| A.1 | Typed event recorders | `feat(lineage): typed event recorders for eval/attempt/deployment/measurement` |
| A.2 | `view_attempt` aggregator | `feat(lineage): add view_attempt aggregator` |
| A.3 | Emit eval_run event | `feat(evals): record eval_run lineage event` |
| A.4 | Emit attempt + rejection events | `feat(optimizer): emit attempt and rejection lineage events` |
| A.5 | Emit deployment event | `feat(deployer): emit deployment lineage event with attempt_id` |
| A.6 | Measurement round-trip | `feat(lineage): support post-deploy measurement events` |
| A.7 | E2E chain test | `test(lineage): end-to-end chain integration test` |

### Slice B — `improve` first-class commands (R2.6–R2.11)

| # | Task | Commit message |
|---|------|----------------|
| B.0 | Extract `improve` group | `refactor(cli): extract improve group to cli/commands/improve.py` |
| B.1 | `improve run` orchestration | `feat(improve): add improve run orchestration` |
| B.2 | `improve accept` | `feat(improve): add improve accept with deploy + measurement scheduling` |
| B.3 | `improve measure` | `feat(improve): add improve measure for post-deploy metrics` |
| B.4 | `improve diff` | `feat(improve): add improve diff` |
| B.5 | `improve lineage` | `feat(improve): add improve lineage visualizer` |

### Slice C — runner.py extraction (R2.12–R2.16)

| # | Task | Commit message |
|---|------|----------------|
| C.1 | Extract `build` group | `refactor(cli): extract build group to cli/commands/build.py` |
| C.2 | Extract `eval` group | `refactor(cli): extract eval group to cli/commands/eval.py` |
| C.3 | Extract `optimize` command | `refactor(cli): extract optimize command to cli/commands/optimize.py` |
| C.4 | Extract `deploy` command | `refactor(cli): extract deploy command to cli/commands/deploy.py` |

### Slice D — Workbench, backfill, docs (R2.17–R2.19)

| # | Task | Commit message |
|---|------|----------------|
| D.1 | Workbench `/improve` slash | `feat(workbench): /improve slash parity with CLI` |
| D.2 | Lineage backfill | `feat(lineage): backfill orphan eval artifacts` |
| D.3 | Rewrite QUICKSTART | `docs: rewrite QUICKSTART around agentlab improve` |

## 4. Per-step TDD recipes

Every step: failing test → minimal impl → passing test → conventional
commit. Subagent dispatches use `uv run pytest`.

### 0.2 Golden-file help snapshots

**Test first** (`tests/test_cli_help_golden.py`):

```python
import subprocess
from pathlib import Path
import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"

@pytest.mark.parametrize("cmd,fname", [
    (["agentlab", "--help"], "agentlab_help.txt"),
    (["agentlab", "improve", "--help"], "improve_help.txt"),
    (["agentlab", "eval", "--help"], "eval_help.txt"),
    (["agentlab", "build", "--help"], "build_help.txt"),
    (["agentlab", "optimize", "--help"], "optimize_help.txt"),
    (["agentlab", "deploy", "--help"], "deploy_help.txt"),
])
def test_help_matches_golden(cmd, fname):
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    expected = (GOLDEN_DIR / fname).read_text()
    assert result.stdout == expected, f"{' '.join(cmd)} output drifted"
```

**Seed the golden files**: run each command on master tip, write stdout to
the corresponding file in `tests/golden/`. Commit with the test.

**Run:** `uv run pytest tests/test_cli_help_golden.py -v`

### A.1 Typed event recorders

**Test first** (`tests/test_lineage_event_types.py`):

```python
import pytest
from optimizer.improvement_lineage import ImprovementLineageStore, EVENT_EVAL_RUN, \
    EVENT_ATTEMPT, EVENT_REJECTION, EVENT_DEPLOYMENT, EVENT_MEASUREMENT

@pytest.fixture
def store(tmp_path):
    return ImprovementLineageStore(db_path=str(tmp_path / "lineage.db"))

def test_record_eval_run(store):
    ev = store.record_eval_run(
        eval_run_id="run-123", attempt_id="a1b2c3d4",
        config_path="configs/foo.yaml", composite_score=0.82, case_count=55)
    assert ev.event_type == EVENT_EVAL_RUN
    assert ev.payload["eval_run_id"] == "run-123"

def test_record_attempt(store):
    ev = store.record_attempt(
        attempt_id="a1b2c3d4", status="accepted",
        score_before=0.80, score_after=0.85, eval_run_id="run-123")
    assert ev.event_type == EVENT_ATTEMPT
    assert ev.payload["score_after"] == 0.85

def test_record_rejection(store):
    ev = store.record_rejection(
        attempt_id="a1b2c3d4", reason="regression_detected", detail="composite dropped 0.05")
    assert ev.event_type == EVENT_REJECTION
    assert ev.payload["reason"] == "regression_detected"

def test_record_deployment(store):
    ev = store.record_deployment(
        attempt_id="a1b2c3d4", deployment_id="dep-7", version=7)
    assert ev.event_type == EVENT_DEPLOYMENT
    assert ev.version == 7

def test_record_measurement(store):
    ev = store.record_measurement(
        attempt_id="a1b2c3d4", measurement_id="m-1",
        composite_delta=0.03, eval_run_id="run-456")
    assert ev.event_type == EVENT_MEASUREMENT
    assert ev.payload["composite_delta"] == 0.03
```

**Impl** (`optimizer/improvement_lineage.py`):

Add module-level constants and thin façades over `record()`:

```python
EVENT_EVAL_RUN = "eval_run"
EVENT_ATTEMPT = "attempt"
EVENT_REJECTION = "rejection"
EVENT_DEPLOYMENT = "deployment"
EVENT_MEASUREMENT = "measurement"

# inside class:
def record_eval_run(self, eval_run_id, attempt_id="", config_path="",
                    composite_score=None, case_count=None, **extra):
    return self.record(attempt_id, EVENT_EVAL_RUN, payload={
        "eval_run_id": eval_run_id, "config_path": config_path,
        "composite_score": composite_score, "case_count": case_count, **extra})

# ... similar wrappers for attempt / rejection / deployment / measurement
```

Keep `EVENT_DEPLOYMENT` distinct from the existing `deploy_canary` /
`promote` types so the classifier in `improve list` still works. Plan:
`record_deployment` writes both a semantic `deployment` event AND — when
called from the existing API paths — the legacy `promote` / `deploy_canary`
events they already emit. The façade is additive.

**Run:** `uv run pytest tests/test_lineage_event_types.py -v`

### A.2 `view_attempt` aggregator

**Test first** (`tests/test_lineage_view.py`):

```python
from optimizer.improvement_lineage import ImprovementLineageStore, AttemptLineageView

def test_view_attempt_flattens_chain(tmp_path):
    store = ImprovementLineageStore(db_path=str(tmp_path / "l.db"))
    aid = "a1b2c3d4"
    store.record_eval_run(eval_run_id="r1", attempt_id=aid, composite_score=0.80)
    store.record_attempt(attempt_id=aid, status="accepted",
                         score_before=0.80, score_after=0.85, eval_run_id="r1")
    store.record_deployment(attempt_id=aid, deployment_id="d1", version=3)
    store.record_measurement(attempt_id=aid, measurement_id="m1",
                             composite_delta=0.04, eval_run_id="r2")
    view = store.view_attempt(aid)
    assert isinstance(view, AttemptLineageView)
    assert view.attempt_id == aid
    assert view.eval_run_id == "r1"
    assert view.deployment_id == "d1"
    assert view.measurement_id == "m1"
    assert view.composite_delta == 0.04
    assert view.status == "accepted"

def test_view_attempt_partial(tmp_path):
    store = ImprovementLineageStore(db_path=str(tmp_path / "l.db"))
    store.record_attempt(attempt_id="a1", status="proposed")
    view = store.view_attempt("a1")
    assert view.status == "proposed"
    assert view.deployment_id is None
    assert view.measurement_id is None
```

**Impl:**

```python
@dataclass
class AttemptLineageView:
    attempt_id: str
    eval_run_id: str | None = None
    deployment_id: str | None = None
    deployed_version: int | None = None
    measurement_id: str | None = None
    composite_delta: float | None = None
    status: str | None = None
    parent_attempt_id: str | None = None
    events: list[LineageEvent] = field(default_factory=list)

# inside class:
def view_attempt(self, attempt_id: str) -> AttemptLineageView:
    events = self.events_for(attempt_id)
    view = AttemptLineageView(attempt_id=attempt_id, events=events)
    for e in events:
        if e.event_type == EVENT_EVAL_RUN and view.eval_run_id is None:
            view.eval_run_id = e.payload.get("eval_run_id")
        elif e.event_type == EVENT_ATTEMPT:
            view.status = e.payload.get("status", view.status)
            if e.payload.get("eval_run_id"):
                view.eval_run_id = e.payload["eval_run_id"]
            if e.payload.get("parent_attempt_id"):
                view.parent_attempt_id = e.payload["parent_attempt_id"]
        elif e.event_type in (EVENT_DEPLOYMENT, "promote", "deploy_canary"):
            view.deployment_id = e.payload.get("deployment_id", view.deployment_id)
            if e.version is not None:
                view.deployed_version = e.version
        elif e.event_type == EVENT_MEASUREMENT:
            view.measurement_id = e.payload.get("measurement_id", view.measurement_id)
            view.composite_delta = e.payload.get("composite_delta", view.composite_delta)
    return view
```

**Run:** `uv run pytest tests/test_lineage_view.py -v`

### A.3 Emit eval_run event from evals/runner.py

**Test first** (`tests/test_lineage_emit_eval.py`):

```python
from evals.runner import EvalRunner  # or whatever the class is
from optimizer.improvement_lineage import ImprovementLineageStore, EVENT_EVAL_RUN

def test_eval_emits_lineage(tmp_path, monkeypatch):
    db = tmp_path / "lineage.db"
    monkeypatch.setenv("AGENTLAB_IMPROVEMENT_LINEAGE_DB", str(db))
    store = ImprovementLineageStore(db_path=str(db))
    # minimal runnable eval config; subagent fills in based on existing fixtures
    runner = EvalRunner(...)
    score = runner.run(config=...)
    events = [e for e in store.recent() if e.event_type == EVENT_EVAL_RUN]
    assert len(events) >= 1
    assert events[0].payload["eval_run_id"] == score.run_id
```

**Impl:** In `evals/runner.py`, after `run_id = str(uuid.uuid4())[:12]` at
line 946, add a guarded block:

```python
try:
    lineage_db = os.environ.get("AGENTLAB_IMPROVEMENT_LINEAGE_DB",
                                 ".agentlab/improvement_lineage.db")
    from optimizer.improvement_lineage import ImprovementLineageStore
    ImprovementLineageStore(db_path=lineage_db).record_eval_run(
        eval_run_id=run_id,
        config_path=getattr(config, "config_path", ""),
        composite_score=score.composite,
        case_count=len(score.case_results) if hasattr(score, "case_results") else None,
    )
except Exception:
    pass  # lineage is observability, not a hard dep
```

Subagent verifies exact attribute names on the score object.

**Run:** `uv run pytest tests/test_lineage_emit_eval.py -v`

### A.4 Emit attempt + rejection from optimizer/loop.py

**Test first** (`tests/test_lineage_emit_optimizer.py`):

```python
from optimizer.loop import Optimizer
from optimizer.improvement_lineage import ImprovementLineageStore, EVENT_ATTEMPT, EVENT_REJECTION

def test_optimizer_emits_attempt_and_rejection_on_reject(tmp_path):
    store = ImprovementLineageStore(db_path=str(tmp_path / "l.db"))
    opt = Optimizer(..., lineage_store=store)
    # force a rejection via AGENTLAB_TEST_FORCE_REJECTION or stub proposer
    opt.run_cycle(...)
    attempt_events = [e for e in store.recent() if e.event_type == EVENT_ATTEMPT]
    rejection_events = [e for e in store.recent() if e.event_type == EVENT_REJECTION]
    assert len(attempt_events) == 1
    assert len(rejection_events) == 1
    assert attempt_events[0].attempt_id == rejection_events[0].attempt_id
```

**Impl:** Constructor accepts `lineage_store=None`. After
`self.memory.log(attempt)` at line 697:

```python
if self.lineage_store is not None:
    try:
        self.lineage_store.record_attempt(
            attempt_id=attempt.attempt_id,
            status=attempt.status,
            score_before=attempt.score_before,
            score_after=attempt.score_after,
            eval_run_id=getattr(baseline_score, "run_id", None),
            parent_attempt_id=getattr(self, "_parent_attempt_id", None),
        )
        if not accepted:
            self.lineage_store.record_rejection(
                attempt_id=attempt.attempt_id,
                reason=rejection_reason_enum.value,
                detail=reason,
            )
    except Exception:
        pass
```

Wire the store construction in the CLI `optimize` command (pull from env
like `improve list` already does).

**Run:** `uv run pytest tests/test_lineage_emit_optimizer.py -v`

### A.5 Emit deployment event from deployer

**Test first** (`tests/test_lineage_emit_deployer.py`):

Subagent locates the promote entry point in `deployer/release_manager.py`
and tests that a successful promote with `attempt_id` writes a
`deployment` event.

**Impl:** Thread `attempt_id` through `ReleaseManager.promote()` / `canary_deploy()` signatures. On success, write:

```python
if self._lineage_store is not None and attempt_id:
    try:
        self._lineage_store.record_deployment(
            attempt_id=attempt_id, deployment_id=deployment_id, version=version)
    except Exception:
        pass
```

Add `--attempt-id` option to `agentlab deploy` in `runner.py:6085`.

**Run:** `uv run pytest tests/test_lineage_emit_deployer.py -v`

### A.6 Measurement round-trip

**Test first** (`tests/test_lineage_measurement.py`):

```python
def test_measurement_round_trip(tmp_path):
    store = ImprovementLineageStore(db_path=str(tmp_path / "l.db"))
    store.record_deployment(attempt_id="a1", deployment_id="d1", version=3)
    store.record_measurement(attempt_id="a1", measurement_id="m1",
                             composite_delta=0.02, eval_run_id="r2")
    view = store.view_attempt("a1")
    assert view.measurement_id == "m1"
    assert view.composite_delta == 0.02
```

Already covered by A.1 + A.2, but this is the explicit gate test for R2.5.

**Run:** `uv run pytest tests/test_lineage_measurement.py -v`

### A.7 E2E chain integration test

**Test** (`tests/test_lineage_e2e_chain.py`): construct a tmp lineage DB,
stub eval runner + proposer + deployer, simulate a full improve cycle, and
assert `view_attempt()` returns a fully populated
`AttemptLineageView` for the accepted attempt.

**Run:** `uv run pytest tests/test_lineage_e2e_chain.py -v`

### B.0 Extract improve group

**Test:** `test_cli_help_golden.py` must still pass byte-identically. Plus:

```python
# tests/test_improve_group_registration.py
from runner import cli
def test_improve_group_registered():
    assert "improve" in cli.commands
    improve = cli.commands["improve"]
    assert set(improve.commands.keys()) >= {"run", "list", "show", "optimize"}
```

**Impl:** Create `cli/commands/__init__.py`:

```python
def register_all(cli_group):
    from .improve import register_improve_commands
    register_improve_commands(cli_group)
```

Create `cli/commands/improve.py` with a `register_improve_commands(cli)`
function that wraps all existing `@improve_group.*` decorators. In
`runner.py`, delete the original decorators and add a single call at the
CLI registration site:

```python
from cli.commands import register_all
register_all(cli)
```

Preserve every option, hidden flag, and docstring. Golden test is the
safety net.

**Run:** `uv run pytest tests/test_cli_help_golden.py tests/test_improve_group_registration.py -v`

### B.1 `improve run <config>`

**Test:**

```python
# tests/test_improve_run_cmd.py
from click.testing import CliRunner
def test_improve_run_orchestrates_eval_then_optimize(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("cli.commands.improve._run_eval_step", lambda *a, **k: calls.append("eval") or FakeScore())
    monkeypatch.setattr("cli.commands.improve._run_optimize_step", lambda *a, **k: calls.append("optimize") or FakeAttempt("a1b2c3d4"))
    r = CliRunner().invoke(cli, ["improve", "run", str(tmp_path / "cfg.yaml")])
    assert r.exit_code == 0
    assert calls == ["eval", "optimize"]
    assert "a1b2c3d4" in r.output

def test_improve_run_propagates_strict_live(monkeypatch):
    captured = {}
    monkeypatch.setattr(..., lambda *a, strict_live=False, **k: captured.setdefault("strict_live", strict_live))
    CliRunner().invoke(cli, ["improve", "run", "cfg.yaml", "--strict-live"])
    assert captured["strict_live"] is True

def test_improve_run_zero_args_is_deprecated_autofix(monkeypatch):
    r = CliRunner().invoke(cli, ["improve", "run"])
    assert "deprecated" in r.output.lower()
    assert "autofix apply" in r.output
```

**Impl:** `cli/commands/improve.py::improve_run`:

```python
@improve_group.command("run")
@click.argument("config_path", required=False, type=click.Path(exists=False))
@click.option("--strict-live", is_flag=True, ...)
# ... other options mirroring the hidden autofix flow for backward compat
def improve_run(config_path, strict_live, ...):
    if config_path is None:
        # preserve hidden autofix alias
        click.echo(click.style(
            "Note: `improve run` (no args) is deprecated. Use `agentlab autofix apply`.",
            fg="yellow"))
        return _legacy_autofix_run(...)
    score = _run_eval_step(config_path, strict_live=strict_live, ...)
    attempt = _run_optimize_step(config_path, eval_run_id=score.run_id,
                                 strict_live=strict_live, ...)
    _present_proposal(attempt)
```

**Run:** `uv run pytest tests/test_improve_run_cmd.py -v`

### B.2 `improve accept <attempt_id>`

**Test:**

```python
# tests/test_improve_accept_cmd.py
def test_improve_accept_deploys_with_attempt_id(monkeypatch):
    deploy_calls = []
    monkeypatch.setattr("cli.commands.improve._invoke_deploy",
                        lambda attempt_id, **k: deploy_calls.append(attempt_id))
    CliRunner().invoke(cli, ["improve", "accept", "a1b2c3d4"])
    assert deploy_calls == ["a1b2c3d4"]

def test_improve_accept_idempotent_if_already_deployed(lineage_store):
    lineage_store.record_deployment(attempt_id="a1b2c3d4", deployment_id="d1", version=3)
    r = CliRunner().invoke(cli, ["improve", "accept", "a1b2c3d4"])
    assert "already deployed" in r.output.lower()
    assert r.exit_code == 0
```

**Impl:** Look up attempt in memory, verify status is "accepted", invoke
`deploy` with `--attempt-id`, then write a `measurement_scheduled` payload
into the lineage store as a stub for B.3 to consume.

**Run:** `uv run pytest tests/test_improve_accept_cmd.py -v`

### B.3 `improve measure <attempt_id>`

**Test:**

```python
# tests/test_improve_measure_cmd.py
def test_improve_measure_errors_without_deployment(monkeypatch):
    r = CliRunner().invoke(cli, ["improve", "measure", "a1b2c3d4"])
    assert r.exit_code != 0
    assert "not been deployed" in r.output.lower()

def test_improve_measure_writes_measurement_event(lineage_store, monkeypatch):
    lineage_store.record_deployment(attempt_id="a1", deployment_id="d1", version=3)
    monkeypatch.setattr("cli.commands.improve._run_eval_step", lambda *a, **k: FakeScore(composite=0.85))
    # also need score_before from memory
    CliRunner().invoke(cli, ["improve", "measure", "a1"])
    view = lineage_store.view_attempt("a1")
    assert view.measurement_id is not None
    assert view.composite_delta is not None
```

**Impl:** Pull `score_before` from `OptimizationMemory`, run eval on the
current deployed config, compute delta, write `measurement` event.

**Run:** `uv run pytest tests/test_improve_measure_cmd.py -v`

### B.4 `improve diff <attempt_id>`

**Test:**

```python
def test_improve_diff_shows_change_and_rationale(memory_store):
    memory_store.log(FakeAttempt(attempt_id="a1b2c3d4",
                                 change_description="Tighten system prompt",
                                 config_diff="- old\n+ new"))
    r = CliRunner().invoke(cli, ["improve", "diff", "a1b2c3d4"])
    assert "Tighten system prompt" in r.output
    assert "- old" in r.output
    assert "+ new" in r.output
```

**Impl:** Read `OptimizationAttempt` from memory by prefix-match, print
`change_description`, `config_diff`, and pretty-printed `patch_bundle` if
present.

**Run:** `uv run pytest tests/test_improve_diff_cmd.py -v`

### B.5 `improve lineage <attempt_id>`

**Test:**

```python
def test_improve_lineage_renders_chain(lineage_store):
    aid = "a1b2c3d4"
    lineage_store.record_eval_run(eval_run_id="r1", attempt_id=aid, composite_score=0.80)
    lineage_store.record_attempt(attempt_id=aid, status="accepted",
                                 score_before=0.80, score_after=0.85, eval_run_id="r1")
    lineage_store.record_deployment(attempt_id=aid, deployment_id="d1", version=3)
    lineage_store.record_measurement(attempt_id=aid, measurement_id="m1",
                                     composite_delta=0.04, eval_run_id="r2")
    r = CliRunner().invoke(cli, ["improve", "lineage", aid])
    assert "eval_run" in r.output
    assert "attempt" in r.output
    assert "deployment" in r.output
    assert "measurement" in r.output
    assert "v003" in r.output
```

**Impl:** Call `view_attempt()`, render as an indented tree with timestamps
and versions.

**Run:** `uv run pytest tests/test_improve_lineage_cmd.py -v`

### C.1–C.4 Group extractions

**Invariant for all:** golden help test stays byte-identical.

Each slice:
1. Copy the group decorator block from `runner.py` into
   `cli/commands/<group>.py`.
2. Wrap in `register_<group>_commands(cli)` function.
3. Update `cli/commands/__init__.py::register_all` to call it.
4. Delete the original block from `runner.py`.
5. Re-run `uv run pytest tests/test_cli_help_golden.py` — must pass.
6. Run full test suite — no regressions.
7. Commit.

Order matters: `build` (C.1) is simplest, then `eval` (C.2), then
`optimize` (C.3), then `deploy` (C.4, touches R1's force-deploy-degraded
path — add a pinning test first).

**Run for each:** `uv run pytest tests/test_cli_help_golden.py tests/test_<group>*.py -v`

### D.1 Workbench `/improve` slash

**Test:** Textual `pilot.pause()` + snapshot check per subcommand.

**Impl:** `cli/workbench_app/improve_slash.py` follows the pattern of
`cli/workbench_app/eval_slash.py` — subprocess invocation, streaming
output.

**Run:** `uv run pytest tests/test_workbench_improve_slash.py -v`

### D.2 Lineage backfill

**Test:**

```python
# tests/test_lineage_backfill.py
def test_backfill_scans_eval_artifacts(tmp_path):
    # seed fake eval artifacts in tmp_path / ".agentlab/eval_runs/"
    ...
    store = ImprovementLineageStore(db_path=str(tmp_path / "l.db"))
    n1 = store.backfill_orphans(root=str(tmp_path / ".agentlab"))
    assert n1 > 0
    n2 = store.backfill_orphans(root=str(tmp_path / ".agentlab"))
    assert n2 == 0  # idempotent
```

**Impl:** `backfill_orphans(root)` globs for eval artifacts, hashes their
`attempt_id` (if present) or `run_id`, inserts missing `eval_run` events.
Sentinel file: `.agentlab/.lineage_backfill_done`.

**Run:** `uv run pytest tests/test_lineage_backfill.py -v`

### D.3 QUICKSTART rewrite

Update `docs/QUICKSTART.md` (or closest equivalent) to lead with:

```
# 1. Initialize
agentlab init

# 2. Run the improve loop
agentlab improve run configs/my-agent.yaml

# 3. Accept a proposal
agentlab improve accept <attempt_id>

# 4. Measure after deploy
agentlab improve measure <attempt_id>

# 5. See the chain
agentlab improve lineage <attempt_id>
```

No test required; docs-only commit.

## 5. Acceptance tests (end-to-end gate)

Per master plan:

- **E2E:** `agentlab improve run` from fresh workspace through accepted
  proposal and measurement. Verified by Slice A.7 + Slice B tests combined.
- **Lineage:** query `lineage_events` for a sample `attempt_id`; full chain
  (`eval_run → attempt → deployment → measurement`) queryable via
  `view_attempt()`. Verified by A.2, A.6, B.5.
- **Workbench:** `/improve run` → `/improve accept` → `/improve lineage`
  works end-to-end in TUI. Verified by D.1.
- **Refactor smoke:** `agentlab --help` output byte-identical pre- and
  post-refactor. Verified by `tests/test_cli_help_golden.py` at every Slice
  C commit boundary.

## 6. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Schema drift breaking `api/server.py` | Additive payload only; never `ALTER TABLE` |
| Byte-equivalence drift during extraction | Golden-file test; pause + fix immediately if it fails |
| `improve run` namespace collision | Split: new command takes `<config>` arg; zero-arg path prints deprecation + routes to `autofix apply` |
| `attempt_id` drift | Never introduce a second id; `str(uuid.uuid4())[:8]` everywhere |
| Lineage write crashes user flow | Wrap all emits in try/except with structured log |
| Subagent uses host Python 3.9.6 | Every dispatch prompt says "use `uv run pytest`" |
| Pre-existing flaky tests | Note + skip; don't fix in R2 |
| Concurrent lineage writes | Existing SQLite default isolation + `PRAGMA journal_mode=WAL` added in A.1 |

## 7. Execution workflow

Per `superpowers:subagent-driven-development`:

1. Lead thread (this session) dispatches one subagent per task in the
   commit plan.
2. Each subagent: read this plan file, read the named source files, write
   failing test, run `uv run pytest <test>` to confirm RED, write minimal
   impl, run to confirm GREEN, run broader suite to confirm no regression,
   commit with the exact message from §3.
3. Lead marks TaskCreate tasks complete immediately (not batched).
4. At each slice boundary, lead opens a PR for review.

## 8. First subagent dispatch

After committing this file, dispatch Slice 0.2 (golden help snapshots).
Pass the exact per-step recipe from §4.0.2 above.
