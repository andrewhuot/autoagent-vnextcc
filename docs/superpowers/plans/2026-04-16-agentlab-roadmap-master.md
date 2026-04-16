# AgentLab Roadmap — Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship six releases (R1–R6) that take AgentLab from "structurally sound but fragmented" to "trustworthy, coherent, continuously-improving agent platform."

**Architecture:** Six releases sequenced by dependency. R1 (Trust) ships first and unblocks all others. R2 (Unified Improve) and R3 (Smart Optimizer) are the core differentiators. R4 (Workbench Harness) depends on R2's runner.py refactor. R5 (Eval Corpus) is parallel-shippable. R6 (Continuous) requires everything before.

**Tech Stack:** Python 3.11+, Click, Pydantic, SQLite, Textual, FastAPI. Existing test framework: pytest. Existing code style follows the repository.

---

## Scope Note — Multi-Subsystem Plan

This master plan covers six independent releases. Each release is its own self-contained working software increment. To stay under context limits and keep tasks bite-sized, this document:

- **R1 — full TDD task plan inline below.** Ready to execute immediately.
- **R2–R6 — task-list scaffolds with file-level decisions and acceptance tests.** Each must be expanded into its own full TDD plan (`docs/superpowers/plans/2026-04-XX-agentlab-rN-<name>.md`) before execution. The scaffolds are sufficient to estimate scope, allocate work, and start expansion.

**Recommended sequencing:** Execute R1 fully → expand R2 plan → execute R2 → branch (R3 ‖ R5) → R4 → R6.

---

## Repository Conventions (Read Before Any Task)

**Test layout:** `tests/test_<module>.py` mirrors source paths. Pytest with `pytest-asyncio`. Run with `pytest -xvs tests/test_<file>.py::test_<name>`.

**Commit style:** Conventional commits — `feat(scope):`, `fix(scope):`, `refactor(scope):`, `test(scope):`, `docs(scope):`, `chore(scope):`. Scopes match top-level directories: `cli`, `optimizer`, `evals`, `builder`, `deployer`, `agent_card`.

**Branching:** Feature branches off `master`. Never commit to master.

**No `any` in TypeScript surfaces (web).** Python: prefer `pydantic` models over dicts at boundaries.

**Error handling:** Explicit. Silent fallbacks (mock fallback when LLM fails) MUST log a structured warning and propagate to the result payload's `warnings` list.

**File size hint:** [runner.py](runner.py) is currently 12,627 lines. Don't add new commands to it; place them in `cli/commands/<group>.py` and register via `register_<group>_commands(cli)` (pattern from [cli/skills.py](cli/skills.py)).

---

## R1 — Trust the Loop

**Goal:** A new user can run `build → eval → optimize → deploy` end-to-end and trust every result is real, or fail loudly when it isn't.

**Architecture:** Five surgical changes — kill silent mock fallback, add a deploy verdict gate, surface rejected proposals, inline provider setup in onboarding, add `--strict-live` flag.

**Tech Stack:** Click, pytest, Pydantic. No new dependencies.

### File Structure for R1

| File | Status | Responsibility |
|---|---|---|
| `cli/strict_live.py` | **Create** | Strict-live policy: detect, raise `MockFallbackError`, integrate with command exit codes |
| `cli/exit_codes.py` | **Create** | Centralized exit code constants (`EXIT_OK=0`, `EXIT_MOCK_FALLBACK=12`, `EXIT_DEGRADED_DEPLOY=13`, etc.) |
| `tests/test_strict_live.py` | **Create** | Unit tests for strict-live detection and error propagation |
| `tests/test_deploy_gate.py` | **Create** | Unit tests for deploy verdict gate |
| `tests/test_onboarding_provider_setup.py` | **Create** | Tests for inline provider setup during init |
| `tests/test_proposal_rejection_surfacing.py` | **Create** | Tests for `improve list` showing rejected proposals with reasons |
| [runner.py](runner.py) | **Modify** | `eval`, `optimize`, `build`, `deploy`, `init`, `new` commands — add `--strict-live`, gate logic, rejection display |
| [optimizer/proposer.py:any line with use_mock=True](optimizer/proposer.py) | **Modify** | Default `use_mock=False`; require explicit opt-in |
| [optimizer/loop.py:118](optimizer/loop.py) | **Modify** | `Proposer(use_mock=True)` → `Proposer(use_mock=_resolve_mock_default())` |
| [optimizer/gates.py](optimizer/gates.py) | **Modify** | Add `RejectionReason` enum and structured rejection record |
| [deployer/](deployer/) — relevant deploy module | **Modify** | Add `_check_deploy_verdict()` precondition |
| [cli/init_flow.py](cli/init_flow.py) | **Modify** | Inline provider key prompt + validation step |
| [cli/onboarding.py](cli/onboarding.py) | **Modify** | Same prompt for `agentlab new` flow |
| `agentlab.yaml` (template) — `templates/*/agentlab.yaml` | **Modify** | Default `optimizer.use_mock: false` (already done in root); audit all template copies |

---

### Task R1.1: Create exit code constants

**Files:**
- Create: `cli/exit_codes.py`
- Test: `tests/test_exit_codes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_exit_codes.py
from cli.exit_codes import (
    EXIT_OK,
    EXIT_MOCK_FALLBACK,
    EXIT_DEGRADED_DEPLOY,
    EXIT_MISSING_PROVIDER,
)


def test_exit_codes_are_distinct_and_nonzero_for_failure():
    assert EXIT_OK == 0
    assert EXIT_MOCK_FALLBACK == 12
    assert EXIT_DEGRADED_DEPLOY == 13
    assert EXIT_MISSING_PROVIDER == 14
    codes = {EXIT_OK, EXIT_MOCK_FALLBACK, EXIT_DEGRADED_DEPLOY, EXIT_MISSING_PROVIDER}
    assert len(codes) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_exit_codes.py -xvs`
Expected: `ImportError: No module named cli.exit_codes`

- [ ] **Step 3: Write minimal implementation**

```python
# cli/exit_codes.py
"""Centralized exit codes for the AgentLab CLI.

Codes 0–9 are reserved for standard process exit semantics.
Codes 10+ are AgentLab-specific failure modes that scripts can switch on.
"""

EXIT_OK = 0
EXIT_GENERIC_ERROR = 1

EXIT_MOCK_FALLBACK = 12
"""--strict-live was set, but a step fell back to mock execution."""

EXIT_DEGRADED_DEPLOY = 13
"""Deploy was attempted on a workspace whose latest eval was degraded."""

EXIT_MISSING_PROVIDER = 14
"""Live mode requested but no provider credentials are configured."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_exit_codes.py -xvs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/exit_codes.py tests/test_exit_codes.py
git commit -m "feat(cli): add centralized exit codes for strict failure modes"
```

---

### Task R1.2: Create strict-live detection module

**Files:**
- Create: `cli/strict_live.py`
- Test: `tests/test_strict_live.py`

- [ ] **Step 1: Write the failing test for the policy class**

```python
# tests/test_strict_live.py
import pytest
from cli.strict_live import StrictLivePolicy, MockFallbackError


def test_policy_disabled_allows_mock_warnings():
    policy = StrictLivePolicy(enabled=False)
    policy.record_mock_warning("provider returned 403, used mock fallback")
    # Should not raise.
    assert policy.has_fallback() is True
    assert policy.warnings == ["provider returned 403, used mock fallback"]


def test_policy_enabled_raises_on_first_warning():
    policy = StrictLivePolicy(enabled=True)
    with pytest.raises(MockFallbackError) as exc:
        policy.record_mock_warning("provider returned 403, used mock fallback")
    assert "strict-live" in str(exc.value).lower()
    assert "provider returned 403" in str(exc.value)


def test_policy_enabled_check_after_run_raises_when_warnings_present():
    """Some warnings are appended post-hoc to the score object; policy must
    expose a final check() method that raises if any accumulated."""
    policy = StrictLivePolicy(enabled=True)
    # Simulate post-hoc warning ingestion (not via record_mock_warning).
    policy.ingest_existing_warnings(["eval_run.live_fallback_to_mock: gemini 429"])
    with pytest.raises(MockFallbackError):
        policy.check()


def test_policy_enabled_check_passes_when_no_warnings():
    policy = StrictLivePolicy(enabled=True)
    policy.check()  # no raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_strict_live.py -xvs`
Expected: `ImportError: No module named cli.strict_live`

- [ ] **Step 3: Write minimal implementation**

```python
# cli/strict_live.py
"""Strict-live policy: turn silent mock fallback into a hard failure.

When --strict-live is passed to build/eval/optimize/deploy, any mock fallback
(provider 403, rate limit, missing key handled silently, etc.) raises
MockFallbackError. The CLI catches this and exits with EXIT_MOCK_FALLBACK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


class MockFallbackError(RuntimeError):
    """Raised when --strict-live is enabled and a mock fallback was detected."""

    def __init__(self, warnings: list[str]) -> None:
        joined = "\n  - ".join(warnings) if warnings else "(no warnings recorded)"
        super().__init__(
            "strict-live: command fell back to mock execution.\n"
            f"  - {joined}\n"
            "Hint: configure a real provider with `agentlab provider configure` "
            "or remove --strict-live to allow mock fallback."
        )
        self.warnings = list(warnings)


@dataclass
class StrictLivePolicy:
    enabled: bool
    warnings: list[str] = field(default_factory=list)

    def record_mock_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.enabled:
            raise MockFallbackError([warning])

    def ingest_existing_warnings(self, warnings: Iterable[str]) -> None:
        """Absorb warnings produced by lower layers (eval runner, etc.)
        without raising immediately. Call check() after to enforce."""
        for w in warnings:
            self.warnings.append(w)

    def has_fallback(self) -> bool:
        return bool(self.warnings)

    def check(self) -> None:
        """Final gate. Raises if strict mode is enabled and any fallback occurred."""
        if self.enabled and self.warnings:
            raise MockFallbackError(self.warnings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_strict_live.py -xvs`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add cli/strict_live.py tests/test_strict_live.py
git commit -m "feat(cli): add StrictLivePolicy for hard-fail on mock fallback"
```

---

### Task R1.3: Wire `--strict-live` into the `eval` command

**Files:**
- Modify: [runner.py](runner.py) — find the `eval` command definition (search for `@cli.group("eval"` or `@eval_group.command("run"`)
- Modify: [runner.py](runner.py) line 3491–3512 region (post-eval mock-warning ingestion)
- Test: `tests/test_eval_strict_live.py`

- [ ] **Step 1: Locate the eval command**

Run: `grep -n "@eval_group.command(\"run\"\\|def eval_run\\|eval_run_cmd" runner.py | head`

Note the line range of the `eval run` Click command (look for `@click.option(...)` decorators above its `def`).

- [ ] **Step 2: Write the failing test**

```python
# tests/test_eval_strict_live.py
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a minimal mock-mode workspace via the CLI."""
    subprocess.run(
        [sys.executable, "-m", "runner", "new", "ws", "--template",
         "customer-support", "--demo"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path / "ws"


def test_eval_strict_live_exits_12_when_mock_fallback(workspace: Path, monkeypatch):
    """In a workspace forced into mock mode, --strict-live must exit 12."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    result = subprocess.run(
        [sys.executable, "-m", "runner", "eval", "run", "--strict-live", "--json"],
        cwd=workspace, capture_output=True, text=True,
    )
    assert result.returncode == 12, result.stderr
    assert "strict-live" in result.stderr.lower()


def test_eval_without_strict_live_allows_mock_fallback(workspace: Path):
    result = subprocess.run(
        [sys.executable, "-m", "runner", "eval", "run", "--json"],
        cwd=workspace, capture_output=True, text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "warnings" in payload
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_eval_strict_live.py -xvs`
Expected: FAIL — option not yet defined.

- [ ] **Step 4: Add the `--strict-live` option to the eval command**

In [runner.py](runner.py), locate the `eval run` command's `@click.option(...)` block and add:

```python
@click.option(
    "--strict-live/--no-strict-live",
    default=False,
    help="Exit non-zero (12) if any step falls back to mock execution.",
)
```

Add `strict_live: bool` to the function signature.

- [ ] **Step 5: Wire the policy into the post-eval mock check**

In the `eval run` function, after the existing block at [runner.py:3491–3512](runner.py:3491-3512):

```python
from cli.strict_live import StrictLivePolicy, MockFallbackError
from cli.exit_codes import EXIT_MOCK_FALLBACK

policy = StrictLivePolicy(enabled=strict_live)
policy.ingest_existing_warnings(getattr(score, "warnings", []) or [])
try:
    policy.check()
except MockFallbackError as err:
    click.echo(str(err), err=True)
    sys.exit(EXIT_MOCK_FALLBACK)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_eval_strict_live.py -xvs`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add runner.py tests/test_eval_strict_live.py
git commit -m "feat(cli): add --strict-live to eval run, exit 12 on mock fallback"
```

---

### Task R1.4: Wire `--strict-live` into `optimize` and `build`

**Files:**
- Modify: [runner.py](runner.py) — `optimize` and `build` command definitions
- Test: `tests/test_strict_live_propagation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strict_live_propagation.py
import subprocess, sys
from pathlib import Path
import pytest


@pytest.fixture
def workspace(tmp_path):
    subprocess.run(
        [sys.executable, "-m", "runner", "new", "ws",
         "--template", "customer-support", "--demo"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path / "ws"


def test_optimize_strict_live_exits_12(workspace, monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    result = subprocess.run(
        [sys.executable, "-m", "runner", "optimize", "--cycles", "1", "--strict-live"],
        cwd=workspace, capture_output=True, text=True,
    )
    assert result.returncode == 12


def test_build_strict_live_exits_12(workspace, monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    result = subprocess.run(
        [sys.executable, "-m", "runner", "build",
         "support agent for refunds", "--strict-live"],
        cwd=workspace, capture_output=True, text=True,
    )
    assert result.returncode == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_strict_live_propagation.py -xvs`
Expected: FAIL — option not yet on optimize/build.

- [ ] **Step 3: Add `--strict-live` to optimize**

In [runner.py](runner.py), locate `@cli.command("optimize")` (or `@optimize_group.command("run")`) and add the same `--strict-live/--no-strict-live` option. After the optimization loop returns, ingest `result.warnings` (or equivalent) into a `StrictLivePolicy` and `policy.check()` with `EXIT_MOCK_FALLBACK` on raise.

- [ ] **Step 4: Add `--strict-live` to build**

Same pattern in the `build run` command. After build artifact is generated, check `artifact.warnings` for any mock fallback messages.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_strict_live_propagation.py -xvs`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add runner.py tests/test_strict_live_propagation.py
git commit -m "feat(cli): propagate --strict-live to optimize and build commands"
```

---

### Task R1.5: Default `Proposer(use_mock=False)` in optimizer loop

**Files:**
- Modify: [optimizer/loop.py:118](optimizer/loop.py)
- Modify: [optimizer/proposer.py](optimizer/proposer.py) — `__init__` default
- Test: `tests/test_proposer_default_live.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_proposer_default_live.py
from optimizer.proposer import Proposer
from optimizer.loop import Optimizer


def test_proposer_defaults_to_live():
    p = Proposer()
    assert p.use_mock is False, (
        "Proposer should default to live; mock must be explicit opt-in."
    )


def test_optimizer_loop_does_not_force_mock():
    opt = Optimizer()
    # Even though loop.py at line 118 used to force use_mock=True,
    # it should now defer to environment / explicit construction.
    assert opt.proposer.use_mock is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_proposer_default_live.py -xvs`
Expected: FAIL — `use_mock` is True by default.

- [ ] **Step 3: Change Proposer default**

In [optimizer/proposer.py](optimizer/proposer.py), find `__init__` and change `use_mock: bool = True` → `use_mock: bool = False`.

- [ ] **Step 4: Update [optimizer/loop.py:118](optimizer/loop.py)**

Replace:
```python
self.proposer = proposer or Proposer(use_mock=True)
```
with:
```python
self.proposer = proposer or Proposer()
```

- [ ] **Step 5: Run the broader optimizer test suite to catch regressions**

Run: `pytest tests/test_optimizer.py tests/test_proposer_default_live.py -xvs`
Expected: PASS (or surface tests that explicitly relied on mock — those tests must be updated to pass `use_mock=True` explicitly).

- [ ] **Step 6: Update tests that relied on implicit mock**

For any test that fails after step 5, change the test to explicitly construct `Proposer(use_mock=True)` or mock the LLM call. Do NOT silently restore the old default.

- [ ] **Step 7: Commit**

```bash
git add optimizer/proposer.py optimizer/loop.py tests/
git commit -m "fix(optimizer): default Proposer to live, mock requires explicit opt-in"
```

---

### Task R1.6: Add `RejectionReason` enum and structured rejection record

**Files:**
- Modify: [optimizer/gates.py](optimizer/gates.py)
- Test: `tests/test_gates_rejection.py`

- [ ] **Step 1: Read current gates.py to understand existing rejection shape**

Run: `grep -n "reject\|Rejection\|gate\|GateResult" optimizer/gates.py | head -30`

- [ ] **Step 2: Write the failing test**

```python
# tests/test_gates_rejection.py
from optimizer.gates import RejectionReason, RejectionRecord


def test_rejection_reason_enum_has_canonical_codes():
    assert RejectionReason.SAFETY_VIOLATION.value == "safety_violation"
    assert RejectionReason.REGRESSION_DETECTED.value == "regression_detected"
    assert RejectionReason.NO_SIGNIFICANT_IMPROVEMENT.value == "no_significant_improvement"
    assert RejectionReason.GATE_FAILED.value == "gate_failed"
    assert RejectionReason.COVERAGE_INSUFFICIENT.value == "coverage_insufficient"


def test_rejection_record_serializes_to_dict():
    rec = RejectionRecord(
        attempt_id="att-123",
        reason=RejectionReason.REGRESSION_DETECTED,
        detail="composite dropped 0.04 vs baseline 0.82",
        baseline_score=0.82,
        candidate_score=0.78,
    )
    payload = rec.to_dict()
    assert payload["reason"] == "regression_detected"
    assert payload["detail"].startswith("composite dropped")
    assert payload["baseline_score"] == 0.82
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_gates_rejection.py -xvs`
Expected: ImportError.

- [ ] **Step 4: Implement RejectionReason and RejectionRecord**

Add to [optimizer/gates.py](optimizer/gates.py):

```python
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional


class RejectionReason(str, Enum):
    SAFETY_VIOLATION = "safety_violation"
    REGRESSION_DETECTED = "regression_detected"
    NO_SIGNIFICANT_IMPROVEMENT = "no_significant_improvement"
    GATE_FAILED = "gate_failed"
    COVERAGE_INSUFFICIENT = "coverage_insufficient"


@dataclass
class RejectionRecord:
    attempt_id: str
    reason: RejectionReason
    detail: str
    baseline_score: Optional[float] = None
    candidate_score: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reason"] = self.reason.value
        return d
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_gates_rejection.py -xvs`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add optimizer/gates.py tests/test_gates_rejection.py
git commit -m "feat(optimizer): add RejectionReason enum and RejectionRecord"
```

---

### Task R1.7: Plumb RejectionRecord through the optimizer loop

**Files:**
- Modify: [optimizer/loop.py](optimizer/loop.py)
- Test: `tests/test_loop_rejection_records.py`

- [ ] **Step 1: Audit existing rejection plumbing**

Run: `grep -n "reject\|rejected" optimizer/loop.py | head -20`

Identify the points where the current loop discards/skips a candidate. These become RejectionRecord emission sites.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_loop_rejection_records.py
from optimizer.loop import Optimizer
from optimizer.gates import RejectionReason


def test_loop_emits_rejection_records_when_safety_fails():
    """An optimization cycle that produces a safety-failing candidate must
    record a RejectionRecord with reason=SAFETY_VIOLATION."""
    opt = Optimizer(force_mock_safety_failure_for_test=True)  # add test hook
    result = opt.run_one_cycle()
    assert any(
        r.reason == RejectionReason.SAFETY_VIOLATION
        for r in result.rejections
    )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_loop_rejection_records.py -xvs`
Expected: FAIL — no `rejections` attribute on cycle result yet.

- [ ] **Step 4: Add `rejections: list[RejectionRecord]` to the cycle result**

Find the dataclass returned by `Optimizer.run_one_cycle()` (search for `class CycleResult` or similar) and add the field. At each rejection point in `loop.py`, construct a `RejectionRecord` and append.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_loop_rejection_records.py -xvs`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add optimizer/loop.py tests/test_loop_rejection_records.py
git commit -m "feat(optimizer): emit structured RejectionRecord per cycle"
```

---

### Task R1.8: Surface rejected proposals in `improve list`

**Files:**
- Modify: [runner.py:4988](runner.py:4988) — `improve list` command
- Test: `tests/test_improve_list_rejections.py`

- [ ] **Step 1: Read current `improve list` implementation**

Run: `sed -n '4988,5070p' runner.py`

Note how it currently fetches and renders proposals. Identify where rejected proposals are filtered out.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_improve_list_rejections.py
import subprocess, sys, json, os
from pathlib import Path


def test_improve_list_shows_rejected_with_reason(tmp_path):
    """After a cycle that rejects a proposal, `improve list --json` must
    include the rejected entry with its reason."""
    env = {**os.environ, "AGENTLAB_TEST_FORCE_REJECTION": "regression_detected"}
    subprocess.run(
        [sys.executable, "-m", "runner", "new", "ws",
         "--template", "customer-support", "--demo"],
        cwd=tmp_path, check=True, env=env, capture_output=True,
    )
    workspace = tmp_path / "ws"
    subprocess.run(
        [sys.executable, "-m", "runner", "optimize", "--cycles", "1"],
        cwd=workspace, env=env, capture_output=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "runner", "improve", "list", "--json"],
        cwd=workspace, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    rejected = [item for item in payload["items"] if item["status"] == "rejected"]
    assert rejected, f"expected at least one rejected proposal, got {payload}"
    assert rejected[0]["reason"] == "regression_detected"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_improve_list_rejections.py -xvs`
Expected: FAIL — rejected items not in payload.

- [ ] **Step 4: Update `improve list` to include rejected proposals**

In [runner.py:4988](runner.py:4988):
- Remove the filter that hides `status == "rejected"`.
- For each rejected entry, attach `reason` (from RejectionRecord) and `detail`.
- In text output, render rejected proposals with a distinct color (yellow) and prefix `✗ rejected: <reason>`.

- [ ] **Step 5: Add the test hook for forced rejection**

In [optimizer/loop.py](optimizer/loop.py), check for env var `AGENTLAB_TEST_FORCE_REJECTION` and synthesize a rejection of the matching reason. This is a test seam — gate it behind the env var so production behavior is unchanged.

- [ ] **Step 6: Un-hide the `improve` group**

In [runner.py:4867](runner.py:4867):
```python
@cli.group("improve", cls=DefaultCommandGroup, default_command="run", default_on_empty=True)
```
(Remove `hidden=True`.)

Also remove `hidden=True` from `@improve_group.command("run", hidden=True)` at [runner.py:4872](runner.py:4872).

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_improve_list_rejections.py -xvs`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add runner.py optimizer/loop.py tests/test_improve_list_rejections.py
git commit -m "feat(cli): surface rejected proposals in improve list with reasons"
```

---

### Task R1.9: Add deploy verdict gate

**Files:**
- Modify: [runner.py](runner.py) — `deploy` command (search `@cli.group("deploy"` or `@deploy_group.command`)
- Modify: [deployer/](deployer/) — relevant deploy module (locate `def release` or `def promote`)
- Test: `tests/test_deploy_verdict_gate.py`

- [ ] **Step 1: Locate the deploy command and target function**

Run: `grep -n "@deploy_group\\|def deploy_run\\|def _do_deploy\\|def release" runner.py deployer/*.py | head`

- [ ] **Step 2: Write the failing test**

```python
# tests/test_deploy_verdict_gate.py
import subprocess, sys, os
from pathlib import Path


def _new_workspace(tmp_path):
    subprocess.run(
        [sys.executable, "-m", "runner", "new", "ws",
         "--template", "customer-support", "--demo"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path / "ws"


def test_deploy_blocks_on_degraded_eval(tmp_path, monkeypatch):
    """When latest eval is Degraded, deploy --auto-review --yes must exit 13
    unless --force-deploy-degraded is set."""
    monkeypatch.setenv("AGENTLAB_TEST_FORCE_EVAL_DEGRADED", "1")
    ws = _new_workspace(tmp_path)
    subprocess.run(
        [sys.executable, "-m", "runner", "eval", "run"],
        cwd=ws, capture_output=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "runner", "deploy", "--auto-review", "--yes"],
        cwd=ws, capture_output=True, text=True,
    )
    assert result.returncode == 13
    assert "degraded" in result.stderr.lower()


def test_deploy_force_degraded_requires_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTLAB_TEST_FORCE_EVAL_DEGRADED", "1")
    ws = _new_workspace(tmp_path)
    subprocess.run(
        [sys.executable, "-m", "runner", "eval", "run"],
        cwd=ws, capture_output=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "runner", "deploy",
         "--auto-review", "--yes",
         "--force-deploy-degraded", "--reason", "hotfix for sev1"],
        cwd=ws, capture_output=True, text=True,
    )
    assert result.returncode == 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_deploy_verdict_gate.py -xvs`
Expected: FAIL — no gate, deploy succeeds despite degraded.

- [ ] **Step 4: Implement the gate**

In the deploy command in [runner.py](runner.py):

```python
@click.option("--force-deploy-degraded", is_flag=True,
              help="Allow deploy even when latest eval is degraded. Requires --reason.")
@click.option("--reason", default=None, help="Required with --force-deploy-degraded.")
```

Before invoking the actual deploy:

```python
from cli.exit_codes import EXIT_DEGRADED_DEPLOY

verdict = _latest_eval_verdict(workspace)  # add helper that reads .agentlab/eval/latest.json
if verdict == "degraded":
    if not force_deploy_degraded:
        click.echo(
            "Deploy blocked: latest eval is degraded vs. baseline.\n"
            "Re-run optimization, or pass --force-deploy-degraded --reason '<why>'.",
            err=True,
        )
        sys.exit(EXIT_DEGRADED_DEPLOY)
    if not reason:
        click.echo("--force-deploy-degraded requires --reason.", err=True)
        sys.exit(EXIT_DEGRADED_DEPLOY)
    _log_force_deploy(workspace, reason=reason, verdict=verdict)
```

Add `_latest_eval_verdict` and `_log_force_deploy` helpers in the same file or in a new `deployer/verdict.py`.

- [ ] **Step 5: Add test hook in eval runner**

In [runner.py](runner.py) post-eval result construction, if `os.getenv("AGENTLAB_TEST_FORCE_EVAL_DEGRADED")`, override the verdict written to `.agentlab/eval/latest.json` to `"degraded"`.

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_deploy_verdict_gate.py -xvs`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add runner.py deployer/ tests/test_deploy_verdict_gate.py
git commit -m "feat(deploy): block deploys on degraded eval; --force-deploy-degraded requires --reason"
```

---

### Task R1.10: Inline provider setup in `agentlab init` and `agentlab new`

**Files:**
- Modify: [cli/init_flow.py](cli/init_flow.py)
- Modify: [cli/onboarding.py](cli/onboarding.py)
- Test: `tests/test_onboarding_provider_setup.py`

- [ ] **Step 1: Read the current onboarding flows**

Run: `cat cli/init_flow.py | head -120` and `cat cli/onboarding.py | head -120`

Identify where the workspace is finalized — that's where the provider prompt belongs.

- [ ] **Step 2: Write the failing test (with mocked stdin)**

```python
# tests/test_onboarding_provider_setup.py
from cli.init_flow import InitFlow


def test_init_flow_prompts_for_provider_when_no_keys(monkeypatch, tmp_path):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)

    answers = iter(["openai", "sk-test-fake", "y"])  # provider, key, confirm
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))

    flow = InitFlow(workspace_dir=tmp_path, non_interactive=False,
                    provider_validator=lambda *_: True)
    result = flow.run()

    assert "provider_configured" in result.steps_completed
    env_file = tmp_path / ".agentlab" / ".env"
    assert env_file.exists()
    assert "OPENAI_API_KEY=sk-test-fake" in env_file.read_text()


def test_init_flow_skips_provider_setup_when_keys_present(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-already-set")
    flow = InitFlow(workspace_dir=tmp_path, non_interactive=False)
    result = flow.run()
    assert "provider_already_configured" in result.steps_completed


def test_init_flow_validates_key_with_one_token_call(monkeypatch, tmp_path):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    answers = iter(["openai", "sk-bad", "y"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))

    flow = InitFlow(workspace_dir=tmp_path, non_interactive=False,
                    provider_validator=lambda provider, key: False)
    result = flow.run()
    assert "provider_validation_failed" in result.warnings
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_onboarding_provider_setup.py -xvs`
Expected: FAIL — no provider prompt yet.

- [ ] **Step 4: Implement the provider prompt step**

Add a `_setup_provider()` method to `InitFlow`:

```python
def _setup_provider(self) -> None:
    if any(os.getenv(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")):
        self.steps_completed.append("provider_already_configured")
        return
    if self.non_interactive:
        self.warnings.append("no_provider_configured")
        return
    provider = input("Configure provider now? [openai/anthropic/google/skip]: ").strip().lower()
    if provider in ("", "skip"):
        self.warnings.append("provider_setup_skipped")
        return
    if provider not in ("openai", "anthropic", "google"):
        self.warnings.append(f"unknown_provider:{provider}")
        return
    key = input(f"Paste {provider} API key (will be saved to .agentlab/.env): ").strip()
    if not key:
        self.warnings.append("provider_setup_skipped_no_key")
        return
    if not self.provider_validator(provider, key):
        self.warnings.append("provider_validation_failed")
        return
    self._write_env_var(self._env_var_for(provider), key)
    self.steps_completed.append("provider_configured")

@staticmethod
def _env_var_for(provider: str) -> str:
    return {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
    }[provider]
```

Wire `_setup_provider()` early in `run()` (before eval generation).

Add a default `provider_validator` that does a real 1-token call when the constructor argument is not provided (this lives in `cli/providers.py` — reuse `agentlab provider test` logic).

- [ ] **Step 5: Mirror in `cli/onboarding.py` (the `agentlab new` path)**

Either call `InitFlow._setup_provider()` directly or duplicate the prompt with the same surface.

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_onboarding_provider_setup.py -xvs`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add cli/init_flow.py cli/onboarding.py tests/test_onboarding_provider_setup.py
git commit -m "feat(cli): inline provider setup with validation in init/new flows"
```

---

### Task R1.11: Audit and fix mock-mode defaults in template workspaces

**Files:**
- Modify: every `templates/*/agentlab.yaml` (and any other workspace template)
- Test: `tests/test_template_defaults.py`

- [ ] **Step 1: Find all template yaml files**

Run: `find . -path ./.git -prune -o -name "agentlab.yaml" -print | grep -v ".claude/"`

- [ ] **Step 2: Write the failing test**

```python
# tests/test_template_defaults.py
import yaml
from pathlib import Path


def test_no_template_ships_with_use_mock_true():
    repo = Path(__file__).resolve().parents[1]
    bad = []
    for yml in repo.rglob("agentlab.yaml"):
        if ".claude" in yml.parts or ".venv" in yml.parts:
            continue
        data = yaml.safe_load(yml.read_text()) or {}
        opt = data.get("optimizer", {}) or {}
        if opt.get("use_mock") is True:
            bad.append(str(yml))
    assert not bad, f"Templates ship with use_mock=true: {bad}"
```

- [ ] **Step 3: Run test to verify it fails (or passes if root is already fixed)**

Run: `pytest tests/test_template_defaults.py -xvs`
Expected: PASS or FAIL with a list of files.

- [ ] **Step 4: For each failing file, set `optimizer.use_mock: false`**

Edit each file that fails the assertion.

- [ ] **Step 5: Re-run test to verify**

Run: `pytest tests/test_template_defaults.py -xvs`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_template_defaults.py templates/ configs/
git commit -m "fix(templates): default optimizer.use_mock=false in all shipped workspaces"
```

---

### Task R1.12: Update `agentlab doctor` to distinguish mock-by-config vs mock-by-missing-key

**Files:**
- Modify: [cli/harness_doctor.py](cli/harness_doctor.py) (or wherever `doctor` is implemented — `grep -n "def doctor\\|@cli.command(\"doctor" runner.py`)
- Test: `tests/test_doctor_mock_distinction.py`

- [ ] **Step 1: Locate doctor implementation**

Run: `grep -n "@cli.command(\"doctor\"\\|def doctor" runner.py cli/*.py | head`

- [ ] **Step 2: Write the failing test**

```python
# tests/test_doctor_mock_distinction.py
import subprocess, sys, json, os
from pathlib import Path


def test_doctor_reports_mock_by_missing_key(tmp_path, monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    subprocess.run(
        [sys.executable, "-m", "runner", "new", "ws",
         "--template", "customer-support"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "runner", "doctor", "--json"],
        cwd=tmp_path / "ws", capture_output=True, text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["execution_mode"] == "mock"
    assert payload["mock_reason"] == "missing_provider_key"


def test_doctor_reports_mock_by_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    subprocess.run(
        [sys.executable, "-m", "runner", "new", "ws",
         "--template", "customer-support", "--mode", "mock"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "runner", "doctor", "--json"],
        cwd=tmp_path / "ws", capture_output=True, text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["execution_mode"] == "mock"
    assert payload["mock_reason"] == "configured"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_doctor_mock_distinction.py -xvs`
Expected: FAIL — `mock_reason` field missing.

- [ ] **Step 4: Add `mock_reason` to doctor output**

In the doctor command, after determining execution mode, add:

```python
if execution_mode == "mock":
    if any(os.getenv(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")):
        payload["mock_reason"] = "configured"
    else:
        payload["mock_reason"] = "missing_provider_key"
```

In text output, render distinct lines:
- `Mock mode (configured): set live with 'agentlab mode set live' or 'agentlab mode set auto'`
- `Mock mode (no provider key): run 'agentlab provider configure --provider openai'`

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_doctor_mock_distinction.py -xvs`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add cli/harness_doctor.py runner.py tests/test_doctor_mock_distinction.py
git commit -m "feat(doctor): distinguish mock-by-config from mock-by-missing-key"
```

---

### Task R1.13: Document R1 changes

**Files:**
- Modify: [docs/QUICKSTART_GUIDE.md](docs/QUICKSTART_GUIDE.md)
- Modify: [docs/cli-reference.md](docs/cli-reference.md)
- Modify: [CHANGELOG.md](CHANGELOG.md)

- [ ] **Step 1: Add CHANGELOG entry**

```markdown
## [Unreleased] — R1: Trust the Loop

### Added
- `--strict-live` flag on `build`, `eval`, `optimize` — exits 12 on mock fallback.
- Deploy verdict gate: `agentlab deploy` blocks on degraded eval (exit 13). Override with `--force-deploy-degraded --reason "<why>"`.
- `improve list` (now public) shows rejected proposals with structured reason.
- Inline provider setup during `agentlab init` and `agentlab new` with key validation.
- `agentlab doctor` distinguishes `mock_reason: configured` vs `missing_provider_key`.

### Changed
- `Proposer` defaults to live (`use_mock=False`); mock now requires explicit opt-in.
- All shipped workspace templates default to `optimizer.use_mock: false`.

### Migration
- Workspaces created before R1 with `optimizer.use_mock: true` are unchanged. Run `agentlab mode set live` or edit `agentlab.yaml` to opt in.
```

- [ ] **Step 2: Update QUICKSTART_GUIDE with the strict-live note**

Add a one-paragraph note in the Quick Start about `--strict-live` for CI/CD.

- [ ] **Step 3: Update cli-reference.md**

Add the new flags to the eval/build/optimize/deploy reference sections.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/
git commit -m "docs: document R1 (Trust the Loop) changes"
```

---

### R1 Acceptance — End-to-End

After R1, this E2E sequence must pass:

```bash
# Without keys
unset OPENAI_API_KEY ANTHROPIC_API_KEY GOOGLE_API_KEY
agentlab new ws --template customer-support
cd ws
agentlab eval run --strict-live  # exits 12
agentlab doctor --json | jq .mock_reason  # "missing_provider_key"

# With keys
export OPENAI_API_KEY=sk-real-key
cd ..
agentlab new ws2 --template customer-support  # prompts for provider, validates
cd ws2
agentlab eval run --strict-live  # exits 0
agentlab optimize --cycles 1
agentlab improve list  # shows accepted + rejected with reasons
# Force a degraded eval scenario
AGENTLAB_TEST_FORCE_EVAL_DEGRADED=1 agentlab eval run
agentlab deploy --auto-review --yes  # exits 13
agentlab deploy --auto-review --yes --force-deploy-degraded --reason "hotfix"  # exits 0
```

**R1 Scope: Medium (~2 weeks for one engineer, 13 commits).**

---

## R2 — Unified Improve Loop

> **Expansion required:** This release must be expanded into its own full TDD plan (`docs/superpowers/plans/2026-04-XX-agentlab-r2-improve-loop.md`) before execution. The scaffold below is the seed.

**Goal:** One command — `agentlab improve` — owns the full lifecycle from "I have an agent" to "I shipped a measured improvement," with evidence threading via `attempt_id`.

### File Structure

| File | Status | Responsibility |
|---|---|---|
| `cli/commands/improve.py` | **Create** | New canonical `improve` command (replaces hidden one) |
| `cli/commands/__init__.py` | **Create** | Module init for the new commands package |
| `cli/commands/build.py`, `eval.py`, `optimize.py`, `deploy.py` | **Create** | Extracted from runner.py, one group per file |
| `optimizer/lineage.py` | **Create** | SQLite lineage table + `LineageStore` API |
| `optimizer/lineage_schema.sql` | **Create** | DDL for `attempt_lineage` table |
| `cli/workbench_app/improve_slash.py` | **Create** | TUI parity for `/improve` commands |
| [runner.py](runner.py) | **Modify** | Replace inline command defs with `register_*_commands(cli)` calls; shrink from 12k → ~2k lines |
| [optimizer/loop.py](optimizer/loop.py) | **Modify** | Emit lineage records at each cycle event |
| [evals/runner.py](evals/runner.py) | **Modify** | Emit `eval_run_id` lineage record |
| [deployer/](deployer/) | **Modify** | Emit `deployment_id` lineage record; accept `--attempt-id` |

### Task Outline (each becomes 5–10 TDD steps)

- [ ] **R2.1**: Write `LineageStore` with SQLite schema (`attempt_lineage(eval_run_id, attempt_id, deployment_id, measurement_id, parent_attempt_id, composite_delta, status, created_at)`).
- [ ] **R2.2**: Add `lineage.record_eval_run(eval_run_id, config_path, composite_score)` and call it from `evals/runner.py`.
- [ ] **R2.3**: Add `lineage.record_attempt(attempt_id, eval_run_id, status, candidate_score)` and call from `optimizer/loop.py`.
- [ ] **R2.4**: Add `lineage.record_deployment(deployment_id, attempt_id)` and call from deployer.
- [ ] **R2.5**: Add `lineage.record_measurement(measurement_id, deployment_id, composite_delta)` for post-deploy metrics.
- [ ] **R2.6**: Extract one Click group from runner.py (start with `improve`) into `cli/commands/improve.py`. Establish `register_improve_commands(cli)` pattern.
- [ ] **R2.7**: Implement `improve run <config>` orchestration that calls eval → optimize → present.
- [ ] **R2.8**: Implement `improve accept <id>` that deploys AND schedules measurement.
- [ ] **R2.9**: Implement `improve measure <id>` (post-deploy eval).
- [ ] **R2.10**: Implement `improve diff <id>` (full config diff with rationale).
- [ ] **R2.11**: Implement `improve lineage <id>` (visualize ancestry).
- [ ] **R2.12 – R2.16**: Extract remaining groups (build, eval, optimize, deploy) into `cli/commands/`.
- [ ] **R2.17**: Add `cli/workbench_app/improve_slash.py` mirroring all CLI subcommands.
- [ ] **R2.18**: Migration: on first run after R2, scan `.agentlab/` for orphan eval runs and seed lineage table.
- [ ] **R2.19**: Documentation: rewrite QUICKSTART around `agentlab improve` as the primary command.

### Acceptance Tests

- E2E: `agentlab improve run` from fresh workspace through accepted proposal and measurement.
- Lineage: query `attempt_lineage` for a sample attempt; full chain (`eval_run_id → attempt_id → deployment_id → measurement_id`) is queryable.
- Workbench: `/improve run` then `/improve accept <id>` then `/improve lineage <id>` works end-to-end in the TUI.
- Refactor smoke: `agentlab --help` output is byte-identical to pre-refactor (golden file test).

### Risks

- **runner.py refactor footprint** — 12k lines → modular. Mitigate: extract one group at a time, ship between extractions, use snapshot tests on `--help` output. Each extraction is its own PR.
- **Lineage migration** — existing workspaces have orphan data. Mitigate: idempotent backfill on first lineage write.
- **`improve run` orchestration error semantics** — if eval fails, don't continue; if optimize finds nothing, exit clean with informational message.

**R2 Scope: Large (~3 weeks for two engineers, ~25 commits).**

---

## R3 — Optimizer that Learns

> **Expansion required:** Expand into `docs/superpowers/plans/2026-04-XX-agentlab-r3-smart-optimizer.md` before execution.

**Goal:** Optimizer uses coverage data to target proposals, reads back its own reflection learnings, auto-grows the eval suite when coverage is thin, and uses an LLM-backed pairwise judge.

### File Structure

| File | Status | Responsibility |
|---|---|---|
| [optimizer/llm_proposer.py](optimizer/llm_proposer.py) | **Modify** | Read `CoverageAnalyzer` output, weight proposals toward low-coverage surfaces |
| [optimizer/proposer.py](optimizer/proposer.py) | **Modify** | Consume `surface_learnings` table from reflection; rank strategies by historical effectiveness |
| [optimizer/reflection.py](optimizer/reflection.py) | **Modify** | Add `read_surface_effectiveness(surface)` API |
| [evals/judges/pairwise_judge.py](evals/judges/pairwise_judge.py) | **Modify** | Wire LLM judge with structured output; heuristic becomes fallback |
| [evals/scorer.py](evals/scorer.py) | **Modify** | Move composite weights from hardcoded to per-workspace config |
| `cli/commands/eval_weights.py` | **Create** | `agentlab eval weights show / set / validate` |
| [evals/statistics.py](evals/statistics.py) | **Modify** | Add bootstrap CI; effect-size calibration based on score variance |
| [optimizer/loop.py](optimizer/loop.py) | **Modify** | Auto-trigger `card_case_generator` when coverage <30% on any surface |

### Task Outline

- [ ] **R3.1**: `CoverageAnalyzer.gap_signal()` returns structured `[(surface, severity, recommended_cases), ...]`. Test: low-coverage surfaces rank higher.
- [ ] **R3.2**: `LLMProposer._build_proposer_context()` includes coverage signal. Test: proposer prompt contains "Surface X has only N cases" when coverage thin.
- [ ] **R3.3**: `Reflection.read_surface_effectiveness(surface)` returns `{strategy: effectiveness_score}`. Test: round-trip write/read.
- [ ] **R3.4**: `Proposer._rank_strategies()` weights by reflection effectiveness. Test: deterministic ranking given known history.
- [ ] **R3.5**: `--explain-strategy` flag on `optimize` shows rationale. Test: output contains "selected mutation X because effectiveness=0.7 on similar surfaces".
- [ ] **R3.6**: `optimize` cycle auto-runs `card_case_generator` for surfaces with coverage <30%. Test: post-cycle case count grew on low-cov surface.
- [ ] **R3.7**: LLM pairwise judge with structured-output schema (`{winner: "a"|"b"|"tie", confidence: float, rationale: str}`). Test: stub LLM returns expected schema; judge uses it.
- [ ] **R3.8**: Heuristic judge moved to fallback path when LLM unavailable.
- [ ] **R3.9**: Composite weights moved to `agentlab.yaml` under `eval.composite.weights`. Test: changing weights changes composite score.
- [ ] **R3.10**: `agentlab eval weights show / set / validate` commands. Validate weights sum to 1.0.
- [ ] **R3.11**: Snapshot weights per eval run (back-compat for historical scores). Test: rerunning historical eval reproduces score.
- [ ] **R3.12**: Bootstrap CI in `paired_significance()`. Test: returned CI brackets the point estimate.
- [ ] **R3.13**: Effect-size calibration based on observed variance. Test: small but stable improvements pass; large but noisy don't.
- [ ] **R3.14**: Documentation update.

### Acceptance Tests

- After 5 cycles, optimizer has executed at least 1 proposal targeting an under-covered surface.
- After 10 cycles, reflection table has effectiveness scores per (surface, strategy); proposer's chosen strategy correlates with high-effectiveness entries.
- LLM judge: in a fixture suite of 20 pairs, agreement with human-labeled gold ≥80%.
- Composite weights: invalid weights (sum != 1.0) rejected by validator.

### Risks

- **Reflection feedback loop runaway** — proposer always picks one strategy because it worked once. Mitigate: epsilon-greedy exploration (10% random strategy).
- **LLM judge cost** — cache (input_a, input_b, output_a, output_b) → verdict. TTL 30 days.
- **Composite weight migration** — historical eval runs have old weights. Snapshot weights at run time; render with snapshot when comparing across weight changes.

**R3 Scope: Large (~3 weeks for one engineer, ~14 commits).**

---

## R4 — Workbench is the Harness

> **Expansion required:** Expand into `docs/superpowers/plans/2026-04-XX-agentlab-r4-workbench-harness.md` before execution. **Depends on R2** (modular CLI commands required).

**Goal:** Workbench owns session state. Slash commands call command implementations directly (in-process), share `eval_run_id` / `attempt_id` automatically, render rich progress widgets.

### File Structure

| File | Status | Responsibility |
|---|---|---|
| `cli/workbench_app/session_state.py` | **Create** | `WorkbenchSession` dataclass: current config, last eval_run_id, last attempt_id, cost ticker |
| `cli/workbench_app/lineage_view.py` | **Create** | Multi-pane ancestry visualizer for `/lineage <id>` |
| `cli/workbench_app/progress_widgets.py` | **Create** | Structured progress widgets (eval case grid, failure cards) |
| `cli/workbench_app/diff_view.py` | **Create** | Multi-pane diff for `/diff <attempt_id>` |
| [cli/workbench_app/runtime.py](cli/workbench_app/runtime.py) | **Modify** | Replace `stream_subprocess` calls with in-process command invocation |
| [cli/workbench_app/eval_slash.py](cli/workbench_app/eval_slash.py) | **Modify** | In-process; auto-uses session config |
| [cli/workbench_app/optimize_slash.py](cli/workbench_app/optimize_slash.py) | **Modify** | In-process; auto-passes `--eval-run-id` from session |
| [cli/workbench_app/build_slash.py](cli/workbench_app/build_slash.py) | **Modify** | Sets `session.current_config_path` on success |
| [cli/workbench_app/deploy_slash.py](cli/workbench_app/deploy_slash.py) | **Modify** | Auto-passes `--attempt-id` from session |
| `cli/workbench_app/improve_slash.py` (from R2) | **Modify** | Use session state |

### Task Outline

- [ ] **R4.1**: `WorkbenchSession` dataclass with thread-safe accessors. Test: concurrent reads/writes don't corrupt.
- [ ] **R4.2**: Refactor one slash command (`/eval`) from `stream_subprocess` to in-process. Test: `/eval` works without spawning a subprocess (assert no `Popen` calls via mock).
- [ ] **R4.3**: Same for `/build`. After `/build`, `session.current_config_path` is set.
- [ ] **R4.4**: Same for `/optimize`. Auto-uses `session.last_eval_run_id`.
- [ ] **R4.5**: Same for `/improve` (depends on R2).
- [ ] **R4.6**: Same for `/deploy`. Auto-uses `session.last_attempt_id`.
- [ ] **R4.7**: Eval progress widget (case grid). Test: snapshot of widget state after 3/12 cases shows expected grid.
- [ ] **R4.8**: Failure preview cards with diff + suggested fix. Test: failed case renders with suggestion.
- [ ] **R4.9**: Cost ticker in status bar. Test: after 3 LLM calls, ticker reflects accumulated cost.
- [ ] **R4.10**: `/diff <attempt_id>` multi-pane viewer.
- [ ] **R4.11**: `/lineage <id>` ancestry visualizer.
- [ ] **R4.12**: Inline edit of proposal before accepting (`/improve accept <id> --edit`).
- [ ] **R4.13**: Error boundary per command — uncaught exception in slash command shows error card, doesn't crash TUI.
- [ ] **R4.14**: Documentation update.

### Acceptance Tests

- Open Workbench → `/build "..."` → `/eval` → `/optimize` → `/improve list` → `/improve accept <id>` → `/deploy` works in one session, with no manual ID passing.
- TUI snapshot tests for each new widget (Textual `pilot.snap`).
- Crash injection: force exception in `/eval` handler — TUI surfaces error card and remains interactive.

### Risks

- **In-process execution couples TUI to CLI internals** — bugs propagate immediately. Mitigate: error boundaries + per-command isolation.
- **Cost ticker requires reliable cost tracking** — start with model-name-based estimates, refine with actual token counts when providers return them.
- **Session state corruption** — locks around mutating accessors.

**R4 Scope: Large (~3 weeks for one engineer, ~14 commits).**

---

## R5 — Eval Corpus & Dataset Tooling

> **Expansion required:** Expand into `docs/superpowers/plans/2026-04-XX-agentlab-r5-eval-corpus.md` before execution. Parallel-shippable with R3.

**Goal:** First-class dataset tooling so the eval corpus can grow beyond 55 cases.

### File Structure

| File | Status | Responsibility |
|---|---|---|
| `cli/commands/dataset.py` | **Create** | `agentlab eval dataset <subcommand>` group |
| `evals/dataset/importers.py` | **Create** | JSONL, CSV, HuggingFace dataset importers |
| `evals/dataset/exporters.py` | **Create** | Format-specific exporters |
| `evals/dataset/dedupe.py` | **Create** | Embedding-based dedupe with pluggable embedder |
| `evals/dataset/balance.py` | **Create** | Category distribution analyzer + rebalancer |
| `evals/dataset/bootstrap.py` | **Create** | Large-scale generation with diversity sampling |
| [evals/trace_converter.py](evals/trace_converter.py) | **Modify** | Wire into `agentlab eval ingest --from-traces` |
| [evals/runner.py](evals/runner.py) | **Modify** | Tag-based filtering: `--tag safety`, `--exclude-tag slow` |
| [optimizer/failure_analyzer.py](optimizer/failure_analyzer.py) | **Modify** | When cluster found, auto-call case generator for variants |

### Task Outline

- [ ] **R5.1**: `dataset import <file>` — JSONL importer. Test: import 100 cases from JSONL, all visible in `eval cases list`.
- [ ] **R5.2**: CSV importer.
- [ ] **R5.3**: HuggingFace dataset importer (with cache).
- [ ] **R5.4**: `dataset export --format jsonl/csv` — round-trip. Test: import → export → import yields identical cases.
- [ ] **R5.5**: `dataset bootstrap --target 200` — diversity-sampled generation.
- [ ] **R5.6**: Pluggable embedder interface; default OpenAI `text-embedding-3-small`.
- [ ] **R5.7**: `dataset dedupe --threshold 0.95` with the embedder.
- [ ] **R5.8**: `dataset balance` — category histogram + rebalance recommendations.
- [ ] **R5.9**: Tag-based eval filtering (`--tag`, `--exclude-tag`).
- [ ] **R5.10**: `agentlab eval ingest --from-traces <path>` — convert traces to cases.
- [ ] **R5.11**: Failure-driven case generation: tag generated cases with `generated_from: failure_cluster:<id>`.
- [ ] **R5.12**: Documentation.

### Acceptance Tests

- Import 200 cases from a JSONL file → run eval with `--tag safety` → only safety cases run.
- Dedupe a known-duplicated set → expected count after dedupe.
- Bootstrap 100 cases from an Agent Card → cases pass `evals.coverage_analyzer` requirements.

### Risks

- **Embedding cost** — cache (text → embedding) aggressively; surface running cost.
- **HuggingFace network dependency** — graceful offline fallback with clear error message.
- **Trace ingestion privacy** — surface a confirmation/redaction step before writing.

**R5 Scope: Medium (~2 weeks for one engineer, ~12 commits).**

---

## R6 — Continuous Improvement & Observability

> **Expansion required:** Expand into `docs/superpowers/plans/2026-04-XX-agentlab-r6-continuous.md` before execution. **Depends on R1, R2, R3, R5.**

**Goal:** AgentLab runs continuously against production traffic, suggests improvements, measures real-world impact, surfaces drift.

### File Structure

| File | Status | Responsibility |
|---|---|---|
| `cli/commands/loop.py` | **Create** | New `agentlab loop` (replaces hidden one) — daemon/scheduled mode |
| `optimizer/continuous.py` | **Create** | Continuous improvement orchestrator |
| `evals/drift.py` | **Create** | Drift detection: production score distribution vs training |
| `optimizer/canary_scoring.py` | **Create** | A/B-style scoring during canary deploys |
| `notifications/slack.py`, `notifications/email.py` | **Create** | Notification adapters |
| [optimizer/pareto.py](optimizer/pareto.py) | **Modify** | Multi-objective with cost as first-class objective |
| [deployer/](deployer/) | **Modify** | Canary scoring hooks; gradual rollout |

### Task Outline

- [ ] **R6.1**: `agentlab loop run --interval 1h` (scheduled, not daemon initially).
- [ ] **R6.2**: Trace ingestion hook (depends on R5).
- [ ] **R6.3**: Score new traces; detect regression; queue improvement.
- [ ] **R6.4**: Slack notification adapter (incoming webhook).
- [ ] **R6.5**: Email notification adapter (SMTP).
- [ ] **R6.6**: `agentlab improve measure <id>` runs eval on production-replay set.
- [ ] **R6.7**: Calibration: actual vs predicted improvement → store calibration factor; expose to `optimize --explain-strategy`.
- [ ] **R6.8**: Canary A/B scoring infrastructure.
- [ ] **R6.9**: Drift detection (KL divergence on score distributions).
- [ ] **R6.10**: Drift alert → trigger eval-set refresh recommendation.
- [ ] **R6.11**: Cost-aware Pareto: `(quality, safety, cost)` jointly.
- [ ] **R6.12**: `optimize --show-tradeoffs` surfaces "5% quality / 30% cost" explicitly.
- [ ] **R6.13**: Daemon-mode wrapper (systemd unit / launchd plist samples).
- [ ] **R6.14**: Documentation.

### Acceptance Tests

- 24-hour loop run with simulated trace ingestion completes N cycles, no leaked file handles.
- Slack notification fires on regression; payload contains regression score and link to improvement.
- Drift detection: synthetic distribution shift → alert fires.
- Cost-aware Pareto: a "cheap-and-good-enough" candidate is preferred over "expensive-and-marginally-better" given the same workspace cost weight.

### Risks

- **Daemon state management** — start as scheduled CLI run before full daemon. Document operational story.
- **Notification spam** — rate-limiting + dedupe.
- **A/B traffic routing** — requires deployment-platform integration; design as a pluggable interface, ship adapters for common platforms (k8s, Cloud Run) progressively.
- **Production data privacy** — explicit redaction step; opt-in.

**R6 Scope: Large (~4 weeks for two engineers, ~14 commits).**

---

## Cross-Release Risks

1. **Big runner.py refactor (R2)** — biggest single risk. Mitigate: snapshot test of `agentlab --help`, extract one group at a time, ship between extractions, fully reversible per-group.
2. **Lineage migration (R2)** — back up workspace before first write; idempotent backfill; logged migration record.
3. **Mock-mode default flip (R1)** — surprises users on upgrade. Banner on first run after upgrade explaining the change.
4. **LLM judge cost (R3)** — aggressive caching; heuristic-only mode preserved.
5. **Workbench in-process execution (R4)** — couples TUI to CLI bugs. Error boundaries + per-command isolation.
6. **Embedding/HuggingFace network deps (R5)** — graceful offline fallback; clear errors.
7. **Continuous-mode operational complexity (R6)** — start scheduled, evolve to daemon. Document failure modes.

## Cross-Release Edge Cases

- Workspaces with no Agent Card (legacy) → auto-generate on upgrade (R2 or earlier).
- Coverage analyzer can't parse the config → fall back to no coverage hinting; log clearly.
- Provider mid-cycle outage → pause loop, retry with backoff, surface in TUI.
- Two `improve run` invocations in parallel on the same workspace → file lock; second exits with clear error.
- Eval set entirely empty → `improve run` refuses to start, points to `eval generate`.
- Composite-weight schema change (R3) → snapshot weights per-run for back-compat.
- Trace ingestion of malformed records → quarantine + report, don't fail the loop.

## Overall Scope

**Six releases, total estimated scope: Large** — roughly a quarter of focused work for a 2–4 engineer team.

- **R1 (Trust)** — Medium, ~2 weeks
- **R2 (Improve loop)** — Large, ~3 weeks
- **R3 (Smart optimizer)** — Large, ~3 weeks
- **R4 (Workbench harness)** — Large, ~3 weeks (depends on R2)
- **R5 (Eval corpus)** — Medium, ~2 weeks (parallel with R3)
- **R6 (Continuous)** — Large, ~4 weeks (depends on R1+R2+R3+R5)

**MVP cut (90 days): R1 + R2 + R3.** Ship-worthy major version.
**Full roadmap (180 days): all six.**

---

## Self-Review Checklist (run after writing this plan)

- ✅ Spec coverage: every R1–R6 release from the prior roadmap is represented.
- ✅ Placeholder scan: R1 has full TDD steps; R2–R6 are explicit task lists with acceptance tests (not "TBD"). Each R2–R6 task is small enough to TDD-expand without re-architecting.
- ✅ Type consistency: `RejectionReason`, `RejectionRecord`, `LineageStore`, `WorkbenchSession` referenced consistently across releases.
- ✅ Each release has acceptance tests, file structure, risks.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-16-agentlab-roadmap-master.md`.

**Recommended execution path:**

1. **Execute R1 inline now** using superpowers:executing-plans (it has full TDD steps).
2. **Before starting R2**, expand the R2 scaffold into its own full TDD plan using the writing-plans skill again, then execute it via subagent-driven-development (one subagent per task).
3. Repeat the expand-then-execute pattern for R3–R6.

**Two execution options for R1:**

1. **Subagent-Driven (recommended for R2+)** — fresh subagent per task, two-stage review.
2. **Inline Execution (recommended for R1 since steps are surgical and tightly coupled)** — execute in this session with checkpoints between tasks.

**Which approach for R1?**
