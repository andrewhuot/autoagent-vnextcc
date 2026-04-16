# R4 — Workbench is the Harness (TDD expansion plan)

**Status:** draft, ready for execution
**Branch:** `claude/r4-workbench-harness` (off `master` at `47ff7f8`)
**Depends on:** R2 (modular `cli/commands/*.py`, `agentlab improve` command group)
**Master plan section:** `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md:1296-1346`

## 0. Goal

After R4, the Workbench TUI is the harness: `/eval`, `/build`, `/optimize`,
`/improve`, `/deploy` all run **in-process** (no `subprocess.Popen`),
automatically share `eval_run_id`/`attempt_id` through a
`WorkbenchSession`, persist that session across restarts, render rich
progress widgets, expose `/diff` and `/lineage` viewers, and surface
uncaught exceptions as error cards instead of crashing the TUI.

```
Open Workbench:
  /build "Support agent with Shopify + Slack"
    → session.current_config_path = configs/v012.yaml
  /eval
    → session.last_eval_run_id = er_2026-04-16T20:03_ab12cd
  /optimize                        # auto --eval-run-id from session
    → session.last_attempt_id = att_9f8e7d
  /improve accept att_9f8e7d
    → deployment_id logged against attempt
  /deploy                          # auto --attempt-id from session
  /diff att_9f8e7d
  /lineage er_2026-04-16T20:03_ab12cd

All five commands executed in-process. No subprocess spawned.
Crash in /eval renders an error card. TUI stays interactive.
```

## 1. Architectural decisions

### 1.1 The refactor target is `_default_stream_runner`, not `runtime.py`

The master plan's "Modify `cli/workbench_app/runtime.py` to replace
`stream_subprocess` calls" is misleading. `runtime.py` owns
`WorkbenchAgentRuntime` (the coordinator-turn service) — it has nothing
to do with the slash-command subprocess harness.

The actual call sites for `stream_subprocess` are the five per-command
`_default_stream_runner` functions in
`cli/workbench_app/{eval,optimize,build,deploy,improve}_slash.py`.
Each one builds a `cmd = [sys.executable, "-m", "runner", ...]` argv
and delegates to `_subprocess.stream_subprocess`. R4 rewrites those
five runner functions; `runtime.py` is not touched.

### 1.2 Business-logic extraction: pure `run_*_in_process` functions

`cli/commands/*.py`'s Click callbacks (e.g. `eval_run`, `build_command`,
`optimize_run`) are nested inside `register_*_commands(cli)` and weave
together:

1. Argument parsing (Click decorators).
2. Business logic (load runtime, run eval, write lineage, …).
3. Text rendering (`click.echo` of phase banners, progress lines, …).

The slash handler needs (2) without (1) or (3). **Decision:** extract
each command's business logic into a **module-level pure function**
that takes keyword arguments and a `on_event: Callable[[dict], None]`
callback, emits the same `stream-json` event dicts the subprocess path
emits today, and returns the final summary. The Click callback becomes
a thin shell that parses argv → kwargs, subscribes a stdout JSON
emitter as `on_event`, and calls the pure function.

Why callback-per-event vs. returning a generator:

- Several command bodies (e.g. `build_command`) already drive an
  `asyncio.run()` loop internally. Wrapping that as a sync generator
  is awkward and forces every test to juggle an event loop.
- A callback is a single function, trivially mocked in tests, and
  works identically under sync and async bodies.

**Function signature contract:**

```python
def run_eval_in_process(
    *,
    config_path: str | None,
    suite: str | None,
    category: str | None,
    dataset: str | None,
    dataset_split: str = "all",
    output_path: str | None = None,
    real_agent: bool = False,
    force_mock: bool = False,
    require_live: bool = False,
    strict_live: bool = False,
    on_event: Callable[[dict], None],
) -> EvalRunResult: ...
```

- Keyword-only. No `**kwargs` catch-alls — every argument is typed.
- Returns a small result dataclass (`EvalRunResult`,
  `BuildRunResult`, …) with the fields the slash handler needs
  (`eval_run_id`, `attempt_id`, `config_path`, exit status). The
  Click wrapper ignores the return value.
- Raises the same domain errors the subprocess path surfaces
  (`LiveEvalRequiredError`, `MockFallbackError`). The slash handler
  catches and renders; the Click wrapper prints and exits.

### 1.3 Strict-live semantics are preserved through `raise`, not exit codes

The subprocess path signaled strict-live violations via exit code 12
(from R1). The in-process path can't. **Decision:** `run_*_in_process`
raises `MockFallbackError` (or the relevant `LiveRequired*Error`) on
violation. The slash handler translates that to the same transcript
error the non-zero-exit path produced. The Click wrapper translates
it to `sys.exit(12)`.

This means the exit-code contract survives at the CLI boundary (R1
tests still pass) *and* the TUI gets a clean Python exception to
render.

### 1.4 `WorkbenchSession` is a single dataclass behind one `threading.Lock`

Not a proliferation of per-field locks. One lock guards mutations; reads
of immutable-at-snapshot fields (`current_config_path`,
`last_eval_run_id`, `last_attempt_id`) do not block.

```python
@dataclass
class WorkbenchSession:
    current_config_path: str | None = None
    last_eval_run_id: str | None = None
    last_attempt_id: str | None = None
    cost_ticker_usd: float = 0.0
    # --- internals ---
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _path: Path | None = None  # persistence target; None = in-memory only
```

Mutation goes through `session.update(**changes)` which takes the lock,
updates fields, and (if `_path` is set) atomically writes
`.agentlab/workbench_session.json` using `os.replace` semantics.

### 1.5 Persistence: JSON at `.agentlab/workbench_session.json`, atomic writes

- Format: flat JSON object, fields match dataclass, `_lock` and `_path`
  omitted.
- Path: `<workspace_root>/.agentlab/workbench_session.json`. If no
  workspace is resolved, persistence is disabled (`_path = None`).
- Atomic: write to a sibling `.tmp` file, then `os.replace`. Crash
  during write never leaves a half-written file on disk.
- Schema versioning: top-level `"version": 1`. Loader tolerates
  missing fields (treats as defaults) and unknown fields (logs a
  warning, ignores). Downgrade-safe.
- Corruption: on `json.JSONDecodeError`, emit a warning and start
  fresh. Don't crash the TUI.

### 1.6 Error boundaries ship with Slice A, not deferred to R4.13

In-process execution moves every uncaught exception in command code
into the TUI process. Deferring error boundaries to R4.13 (as the master
plan suggests) means Slice A could ship with a latent crash-the-TUI
regression. **Decision:** every refactored slash handler ships with a
stub error boundary in Slice A (R4.2–R4.6). R4.13 later upgrades these
to render a formatted error card; the Slice A shape is:

```python
try:
    run_eval_in_process(**kwargs, on_event=emit)
except KeyboardInterrupt:
    ...  # existing cancel path
except (EvalCommandError, MockFallbackError) as exc:
    ...  # existing domain error path
except Exception as exc:  # pragma: no cover - error boundary
    echo(theme.error(f"  /eval crashed: {exc}"))
    return on_done(result=f"  /eval crashed: {exc}", display="skip")
```

### 1.7 Slash commands stay byte-identical after each refactor

The user-visible output of `/eval`, `/build`, `/optimize`, `/improve`,
`/deploy` must not change from subprocess → in-process. **Decision:**
each Slice A task includes a snapshot-style test that captures the
sequence of rendered transcript lines for a canned event stream and
asserts it unchanged before/after the refactor. Because the `on_event`
callback emits the same event dicts the subprocess path emitted (§1.2),
the renderer sees the same input and produces the same output.

### 1.8 Out of scope for Slice A

- `pilot.snap` Textual snapshots (Slice B).
- Rich widgets (Slice B).
- `/diff` / `/lineage` viewers (Slice C).
- Inline-edit `/improve accept --edit` (Slice C).
- Full error-card UI (Slice C — R4.13). Slice A ships stub boundaries.
- Cost ticker widget (Slice B — R4.9). Slice A wires
  `session.cost_ticker_usd` but doesn't render it yet.

## 2. Slice A tasks

### R4.1 — `WorkbenchSession` dataclass + thread-safe accessors + persistence

**Create:** `cli/workbench_app/session_state.py`

**Tests** (create `tests/test_workbench_session_state.py`):

1. `test_session_defaults_empty` — fresh `WorkbenchSession()` has all
   `None`/`0.0` fields.
2. `test_session_update_takes_lock_and_mutates` — `session.update(last_eval_run_id="er_1")`
   reflects on subsequent reads.
3. `test_session_concurrent_updates_do_not_corrupt` — spin 8 threads,
   each calling `session.update(cost_ticker_usd=session.cost_ticker_usd + 0.01)`
   100 times under the lock via `session.increment_cost(0.01)`; final
   value == 8.0 (within float tolerance).
4. `test_session_persists_to_json` — session with `_path` set writes
   `{...}` to disk on update; `WorkbenchSession.load(path)` round-trips.
5. `test_session_atomic_write_no_partial_file` — inject a fake `os.replace`
   that raises; assert the final file is unchanged (still the prior version).
6. `test_session_tolerates_corrupt_json` — write garbage to the file;
   `load()` returns defaults and logs a warning.
7. `test_session_version_mismatch_accepts_unknown_fields` — write
   `{"version": 1, "last_eval_run_id": "er_x", "future_field": 42}`;
   load ignores `future_field`, restores `last_eval_run_id`.

**Impl sketch:**

```python
@dataclass
class WorkbenchSession:
    current_config_path: str | None = None
    last_eval_run_id: str | None = None
    last_attempt_id: str | None = None
    cost_ticker_usd: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _path: Path | None = field(default=None, repr=False, compare=False)

    def update(self, **changes: Any) -> None:
        with self._lock:
            for k, v in changes.items():
                if k.startswith("_"):
                    raise ValueError(f"cannot update private field {k}")
                setattr(self, k, v)
            self._flush_locked()

    def increment_cost(self, delta_usd: float) -> None:
        with self._lock:
            self.cost_ticker_usd += delta_usd
            self._flush_locked()

    def _flush_locked(self) -> None:
        if self._path is None:
            return
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, **self._as_dict()}))
        os.replace(tmp, self._path)

    @classmethod
    def load(cls, path: Path) -> "WorkbenchSession":
        if not path.exists():
            return cls(_path=path)
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return cls(_path=path)
        fields = {f.name for f in dataclasses.fields(cls) if not f.name.startswith("_")}
        data.pop("version", None)
        known = {k: v for k, v in data.items() if k in fields}
        return cls(**known, _path=path)
```

**Run:** `uv run pytest tests/test_workbench_session_state.py -v`

**Commit:** `feat(workbench): add WorkbenchSession with thread-safe persistence (R4.1)`

### R4.2 — Extract eval business logic + refactor `/eval` to in-process (pilot)

This is the pilot for the §1.2 extraction pattern. Land it carefully;
R4.3–R4.6 copy its shape.

**Modify:** `cli/commands/eval.py`

- Extract `eval_run`'s body into module-level
  `run_eval_in_process(*, config_path, suite, category, dataset,
  dataset_split, output_path, instruction_overrides_path, real_agent,
  force_mock, require_live, strict_live, on_event) -> EvalRunResult`.
- The Click callback `eval_run` now parses argv → kwargs, subscribes
  an `on_event` that emits `stream-json` to stdout when
  `resolved_output_format == "stream-json"`, and calls the function.
- Behavior at the CLI boundary is identical: same flags, same exit
  codes, same text/stream-json output.

**Modify:** `cli/workbench_app/eval_slash.py`

- `_default_stream_runner` becomes in-process: parse `args` into
  `run_eval_in_process` kwargs, queue events from the callback, yield
  them to the caller.
- Use a `queue.Queue` so the existing `_summarise`/spinner machinery
  keeps its synchronous-generator shape.
- Translate `LiveEvalRequiredError` / `MockFallbackError` to
  `EvalCommandError` at the runner boundary (same as today).
- Wrap in stub error boundary (§1.6).
- On success, `session.update(last_eval_run_id=result.eval_run_id,
  current_config_path=result.config_path)` — session passed via
  `SlashContext.meta["workbench_session"]` (new seam).

**Modify:** `cli/workbench_app/app.py`

- Wire `WorkbenchSession.load(...)` at startup, stash on slash context
  meta. (Minimal — just the plumbing, tests isolate to the session.)

**Tests** (modify `tests/test_workbench_eval_slash.py`, create
`tests/test_eval_in_process.py`):

1. `test_run_eval_in_process_emits_expected_events` — call directly
   with mock `on_event`; assert the event sequence includes
   `phase_started`, `task_progress`, `eval_complete`.
2. `test_run_eval_in_process_raises_on_strict_live_mock_fallback` —
   force mock under `strict_live=True`; assert `MockFallbackError`.
3. `test_eval_slash_does_not_spawn_subprocess` — patch
   `subprocess.Popen` with a sentinel that raises on call; run the
   `/eval` handler; assert no raise. (This is the "no Popen" assertion
   from the master plan.)
4. `test_eval_slash_updates_session_last_eval_run_id` — run `/eval`
   with an event stream that contains a
   `{"event": "eval_complete", "run_id": "er_abc"}`; assert
   `session.last_eval_run_id == "er_abc"` after the handler returns.
5. `test_eval_slash_transcript_output_unchanged` — feed a canned event
   sequence through the new in-process runner; capture transcript
   lines; assert they match a golden string list taken from the
   subprocess path.
6. `test_eval_slash_error_boundary_catches_unexpected` — inject a
   `run_eval_in_process` that raises `ValueError("boom")`; assert
   handler returns an error `OnDoneResult` and does not propagate.

**Run:**
`uv run pytest tests/test_eval_in_process.py tests/test_workbench_eval_slash.py -v`

**Commit:** `refactor(workbench): run /eval in-process via run_eval_in_process (R4.2)`

### R4.3 — Refactor `/build` to in-process; session writes `current_config_path`

`/build`'s business logic lives in `cli/workbench.py::build_command`,
which already drives `service.run_build_stream` (an async generator).
Wrap that into `run_build_in_process` using `asyncio.run` + callback.

**Modify:** `cli/workbench.py`

- Extract `build_command`'s body into
  `run_build_in_process(*, brief, project_id, start_new, target,
  environment, mock, require_live, auto_iterate, max_iterations,
  max_seconds, max_tokens, max_cost_usd, on_event) -> BuildRunResult`.
- `BuildRunResult` includes `project_id`, `config_path` (the written
  artifact location), `status`.
- Click wrapper becomes a thin shell.

**Modify:** `cli/workbench_app/build_slash.py`

- `_default_stream_runner` calls `run_build_in_process` with a queue
  callback. Async execution runs on a background thread; the
  `_default_stream_runner` generator dequeues events.
- Remember to re-wrap synthetic warnings under `data` per the existing
  `on_nonjson` contract so event shapes don't change.
- On success, `session.update(current_config_path=result.config_path)`.
- Stub error boundary.

**Tests** (modify `tests/test_workbench_build_slash.py`):

1. `test_run_build_in_process_emits_expected_events`.
2. `test_build_slash_does_not_spawn_subprocess`.
3. `test_build_slash_updates_session_current_config_path`.
4. `test_build_slash_transcript_output_unchanged`.
5. `test_build_slash_error_boundary`.

**Run:** `uv run pytest tests/test_workbench_build_slash.py -v`

**Commit:** `refactor(workbench): run /build in-process; session.current_config_path (R4.3)`

### R4.4 — Refactor `/optimize` to in-process; auto-injects `last_eval_run_id`

**Modify:** `cli/commands/optimize.py`

- Extract `optimize_run` body into `run_optimize_in_process(*, ...,
  eval_run_id, on_event) -> OptimizeRunResult`.
- Result includes `attempt_id`.

**Modify:** `cli/workbench_app/optimize_slash.py`

- `_default_stream_runner` resolves `eval_run_id`: if not present in
  args, pull from `session.last_eval_run_id`; if that's `None`, raise
  `OptimizeCommandError("no eval run in session — run /eval first")`.
- Preserve strict-live semantics (§1.3) — `MockFallbackError` → same
  transcript error the R1 exit-code-12 path produced.
- On success, `session.update(last_attempt_id=result.attempt_id)`.

**Tests** (modify `tests/test_workbench_optimize_slash.py`):

1. `test_optimize_slash_auto_injects_eval_run_id_from_session`.
2. `test_optimize_slash_errors_when_session_missing_eval_run_id`.
3. `test_optimize_slash_user_override_beats_session`.
4. `test_optimize_slash_does_not_spawn_subprocess`.
5. `test_optimize_slash_updates_session_last_attempt_id`.
6. `test_optimize_slash_strict_live_mock_fallback_surfaces_error`.
7. `test_optimize_slash_transcript_output_unchanged`.

**Run:** `uv run pytest tests/test_workbench_optimize_slash.py -v`

**Commit:** `refactor(workbench): run /optimize in-process with session eval_run_id (R4.4)`

### R4.5 — Refactor `/improve` to in-process; session-aware subcommands

**Modify:** `cli/commands/improve.py`

- Extract per-subcommand bodies: `run_improve_run_in_process`,
  `run_improve_accept_in_process`, `run_improve_measure_in_process`,
  `run_improve_diff_in_process`, `run_improve_lineage_in_process`,
  `run_improve_list_in_process`, `run_improve_show_in_process`.
- Each takes `on_event` + typed kwargs + returns a small result
  dataclass.

**Modify:** `cli/workbench_app/improve_slash.py`

- Dispatch on first arg → the right `run_improve_*_in_process`.
- For `accept`, `measure`, `diff`: when `--attempt-id` is missing,
  auto-inject `session.last_attempt_id`; surface a clear error when
  session is empty.
- `_parse_args` still validates subcommand names (keep
  `_KNOWN_SUBCOMMANDS` frozenset).

**Tests** (modify `tests/test_workbench_improve_slash.py`):

1. `test_improve_run_does_not_spawn_subprocess`.
2. `test_improve_accept_auto_injects_session_attempt_id`.
3. `test_improve_measure_auto_injects_session_attempt_id`.
4. `test_improve_errors_when_session_missing_attempt_id`.
5. `test_improve_transcript_output_unchanged_per_subcommand` —
   parameterized over all 7 subcommands.
6. `test_improve_error_boundary`.

**Run:** `uv run pytest tests/test_workbench_improve_slash.py -v`

**Commit:** `refactor(workbench): run /improve in-process with session attempt_id (R4.5)`

### R4.6 — Refactor `/deploy` to in-process; auto-injects `last_attempt_id`

**Modify:** `cli/commands/deploy.py`

- Extract `deploy_run` body into `run_deploy_in_process(*, attempt_id,
  environment, require_live, strict_live, on_event) -> DeployRunResult`.
- Preserve R1's deploy verdict gate (raises on blocked verdict).

**Modify:** `cli/workbench_app/deploy_slash.py`

- Auto-inject `session.last_attempt_id` when `--attempt-id` absent.
- Translate deploy verdict block to the same transcript error the
  R1 CLI path produced.

**Tests** (modify `tests/test_workbench_deploy_slash.py`):

1. `test_deploy_slash_auto_injects_session_attempt_id`.
2. `test_deploy_slash_errors_when_session_missing_attempt_id`.
3. `test_deploy_slash_user_override_beats_session`.
4. `test_deploy_slash_does_not_spawn_subprocess`.
5. `test_deploy_slash_preserves_verdict_gate_block`.
6. `test_deploy_slash_transcript_output_unchanged`.
7. `test_deploy_slash_error_boundary`.

**Run:** `uv run pytest tests/test_workbench_deploy_slash.py -v`

**Commit:** `refactor(workbench): run /deploy in-process with session attempt_id (R4.6)`

## 3. Slice A acceptance gate

Before declaring Slice A complete and opening PR:

1. `uv run pytest tests/test_workbench_session_state.py tests/test_workbench_eval_slash.py tests/test_workbench_build_slash.py tests/test_workbench_optimize_slash.py tests/test_workbench_improve_slash.py tests/test_workbench_deploy_slash.py -v`
2. `uv run pytest -x` — full suite. Pre-existing starlette/httpx
   collection errors in API tests noted and skipped.
3. Manual smoke:
   - Launch workbench.
   - Check `.agentlab/workbench_session.json` exists after `/build` +
     `/eval`.
   - Kill workbench, relaunch, confirm session restored.
   - `grep -r "subprocess.Popen\|stream_subprocess" cli/workbench_app/*_slash.py`
     returns zero matches (sanity check the refactor landed).

## 4. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Business-logic extraction changes CLI-path behavior | Snapshot `stream-json` output of each Click command against a golden before/after the refactor in a dedicated test. |
| Async `build_command` body deadlocks under sync-generator wrapper | Run `asyncio.run` on a background thread with a `queue.Queue` bridge; tests simulate the thread with a fake async generator. |
| Session JSON gets stale between sessions | On load, validate `last_eval_run_id` still exists in the lineage store; if not, clear it with a warning. (Not in Slice A — add as a follow-up if reports come in.) |
| TUI crash from uncaught exception in command code | §1.6 error boundaries around every slash handler. |
| Thread-safety regression in session state | §1.4 single-lock design; concurrent-write test in R4.1. |

## 5. Out-of-scope (Slice B / C / R4.14)

- Slice B: R4.7 eval case grid widget, R4.8 failure preview cards, R4.9
  cost ticker rendering.
- Slice C: R4.10 `/diff <attempt_id>`, R4.11 `/lineage <id>`, R4.12
  inline-edit accept (`/improve accept --edit`), R4.13 full error-card
  UI.
- R4.14: documentation update.

Each slice gets its own PR off `claude/r4-workbench-harness` (or a
branch cut from Slice A's merge point).
